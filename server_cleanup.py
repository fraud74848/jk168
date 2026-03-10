"""
数据清理模块 - 定时删除过期数据
"""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import text

from server_database import PrimarySessionLocal
from server_config import Config

logger = logging.getLogger(__name__)


class DataCleanup:
    """数据清理管理器"""

    def __init__(self):
        self.retention_hours = Config.SCREENSHOT_RETENTION_HOURS
        self.storage_path = Path(Config.SCREENSHOT_DIR)
        self.running = False

    async def start_cleanup_task(self):
        """启动清理任务"""
        if not Config.AUTO_CLEANUP_ENABLED:
            logger.info("自动清理未启用")
            return

        self.running = True
        logger.info(f"自动清理任务已启动，间隔: {Config.CLEANUP_INTERVAL/3600}小时")

        while self.running:
            try:
                await asyncio.sleep(Config.CLEANUP_INTERVAL)
                if self.running:
                    await self.cleanup_old_data()
            except Exception as e:
                logger.error(f"清理任务异常: {e}")

    async def cleanup_old_data_once(self):
        """执行一次清理"""
        await self.cleanup_old_data()

    async def cleanup_old_data(self):
        """清理旧数据"""
        if self.retention_hours <= 0:
            logger.info("保留时间设置为0，不执行清理")
            return

        try:
            from datetime import datetime, timedelta

            # ===== 修改点1：使用北京时间作为基准时间 =====
            # 获取当前北京时间
            beijing_now = datetime.utcnow() + timedelta(hours=8)
            # 计算清理时间界限（北京时间）
            cutoff_time = beijing_now - timedelta(hours=self.retention_hours)
            # ==========================================

            logger.info(f"开始清理 {self.retention_hours} 小时前的数据...")
            logger.info(f"当前北京时间: {beijing_now.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"清理时间界限: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 使用数据库会话
            db = PrimarySessionLocal()

            try:
                # 获取要删除的截图记录
                screenshots_to_delete = db.execute(
                    text(
                        """
                        SELECT id, filename, thumbnail 
                        FROM screenshots 
                        WHERE screenshot_time < :cutoff
                    """
                    ),
                    {"cutoff": cutoff_time},
                ).fetchall()

                logger.info(f"找到 {len(screenshots_to_delete)} 个待清理的截图记录")

                # 删除文件
                file_count = 0
                size_freed = 0

                for screenshot in screenshots_to_delete:
                    # 删除原图
                    file_path = self.storage_path / screenshot[1]
                    if file_path.exists():
                        size_freed += file_path.stat().st_size
                        file_path.unlink()
                        file_count += 1
                        logger.debug(f"已删除文件: {screenshot[1]}")

                    # 删除缩略图
                    if screenshot[2]:
                        thumb_path = self.storage_path / screenshot[2]
                        if thumb_path.exists():
                            thumb_path.unlink()
                            logger.debug(f"已删除缩略图: {screenshot[2]}")

                # 删除数据库记录
                result = db.execute(
                    text(
                        """
                        DELETE FROM screenshots 
                        WHERE screenshot_time < :cutoff
                        RETURNING id
                    """
                    ),
                    {"cutoff": cutoff_time},
                )

                deleted_count = len(result.fetchall())
                db.commit()

                if deleted_count > 0:
                    logger.info(
                        f"✅ 清理完成: 删除 {deleted_count} 条记录，{file_count} 个文件，释放 {size_freed/1024/1024:.2f}MB"
                    )

                    # ===== 修改点2：记录活动时间使用北京时间 =====
                    # 记录清理活动
                    db.execute(
                        text(
                            """
                            INSERT INTO activities (employee_id, action, details, created_at)
                            VALUES ('system', 'auto_cleanup', :details, :now)
                        """
                        ),
                        {
                            "details": {
                                "deleted": deleted_count,
                                "size_freed": size_freed,
                            },
                            "now": beijing_now,  # 原来是 datetime.utcnow()
                        },
                    )
                    db.commit()
                    # ==========================================
                else:
                    logger.info("没有需要清理的数据")

            except Exception as e:
                logger.error(f"清理过程中出错: {e}")
                db.rollback()
                raise
            finally:
                db.close()

        except Exception as e:
            logger.error(f"清理失败: {e}")
            # 不抛出异常，避免影响主程序运行

    def stop(self):
        """停止清理任务"""
        self.running = False
        logger.info("清理任务已停止")
