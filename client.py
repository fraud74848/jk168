#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
员工监控系统客户端 - 完整增强版
功能：
1. 自动注册客户端（支持多服务器检测）
2. 定时截图上传（WebP/JPG格式支持）
3. 系统托盘图标管理
4. 开机自启动管理
5. 配置自动生成和动态加载
6. 心跳保活机制
7. 批量上传支持
8. 图片相似度检测
9. 加密支持
10. 系统信息收集
11. 配置文件监控
12. 错误重试机制
13. 离线模式支持
14. 网络状态自动检测
15. 多服务器故障转移
"""

import os
import sys
import time
import json
import socket
import uuid
import logging
import argparse
import platform
import hashlib
import threading
import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

# 第三方库导入
import requests
from PIL import ImageGrab, Image

# 导入工具模块
from client_utils import (
    SystemInfoCollector,
    ConfigManager,
    TrayIcon,
    retry,
    setup_logging,
    AutoConfig,
)
from client_config import Config

# 配置日志
logger = setup_logging()


class MonitorClient:
    """监控客户端主类"""

    def __init__(self, config_file="config.json"):
        # 初始化组件
        self.config_manager = ConfigManager(config_file)
        self.system_info = SystemInfoCollector()
        self.api_client = None
        self.tray = None

        # 从配置加载设置
        self._load_config()

        # 初始化截图管理器
        self.screenshot_manager = ScreenshotManager(
            quality=self.quality,
            format=self.format,
            max_history=self.max_history,
            similarity_threshold=self.similarity_threshold,
            encryption_key=os.environ.get("ENCRYPTION_KEY"),
        )

        # 状态变量
        self.running = False
        self.paused = False
        self.take_screenshot_now = False
        self.offline_mode = False
        self.current_server_index = 0

        # 统计信息
        self.stats = {
            "screenshots_taken": 0,
            "screenshots_uploaded": 0,
            "upload_failures": 0,
            "start_time": None,
            "last_upload_time": None,
            "last_heartbeat": None,
            "errors": [],
        }

        # 线程锁
        self.stats_lock = threading.RLock()
        self.error_lock = threading.RLock()

        # 尝试创建托盘图标
        try:
            from pystray import Icon

            self.tray = TrayIcon(self)
            logger.info("✅ 托盘图标已创建")
        except ImportError:
            logger.warning("⚠️ pystray未安装，托盘图标功能不可用")
            self.tray = None
        except Exception as e:
            logger.error(f"❌ 创建托盘图标失败: {e}")
            self.tray = None

    def _load_config(self):
        """从配置管理器加载设置"""
        from client_config import Config as ClientConfig

        self.client_id = self.config_manager.get("client_id")
        self.employee_id = self.config_manager.get("employee_id")

        # 服务器地址：使用配置文件
        self.server_urls = ClientConfig.DEFAULT_SERVERS
        self.config_manager.set("server_urls", self.server_urls)
        self.current_server = self.server_urls[0] if self.server_urls else None

        # 初始化配置，但之后会被服务器覆盖
        self.interval = self.config_manager.get(
            "interval", ClientConfig.SCREENSHOT_INTERVAL
        )
        self.quality = self.config_manager.get(
            "quality", ClientConfig.SCREENSHOT_QUALITY
        )
        self.format = self.config_manager.get("format", ClientConfig.SCREENSHOT_FORMAT)

        # 其他配置
        self.auto_start = self.config_manager.get("auto_start", True)
        self.hide_window = self.config_manager.get("hide_window", True)
        self.enable_heartbeat = self.config_manager.get("enable_heartbeat", True)
        self.enable_batch_upload = self.config_manager.get("enable_batch_upload", True)
        self.max_history = self.config_manager.get(
            "max_history", ClientConfig.MAX_HISTORY
        )
        self.similarity_threshold = self.config_manager.get(
            "similarity_threshold", ClientConfig.SIMILARITY_THRESHOLD
        )
        self.retry_times = self.config_manager.get(
            "retry_times", ClientConfig.RETRY_TIMES
        )
        self.retry_delay = self.config_manager.get(
            "retry_delay", ClientConfig.RETRY_DELAY
        )
        self.encryption_enabled = self.config_manager.get("encryption_enabled", False)

        logger.info(
            f"📝 初始配置 - 间隔: {self.interval}秒, 质量: {self.quality}, 格式: {self.format}"
        )

    def validate_config(self):
        """验证配置有效性"""
        if not self.server_urls:
            logger.error("未配置服务器地址")
            return False

        # 验证每个服务器URL
        valid_urls = []
        for url in self.server_urls:
            if url.startswith(("http://", "https://")):
                valid_urls.append(url)
            else:
                logger.warning(f"无效的服务器URL: {url}")

        if not valid_urls:
            logger.error("没有有效的服务器地址")
            return False

        self.server_urls = valid_urls
        self.current_server = valid_urls[0]

        # 验证截图间隔
        if self.interval < 10 or self.interval > 3600:
            logger.warning(f"截图间隔{self.interval}秒不合理，调整为60秒")
            self.interval = 60

        # 验证图片质量
        if self.quality < 10 or self.quality > 100:
            logger.warning(f"图片质量{self.quality}不合理，调整为80")
            self.quality = 80

        # 验证图片格式
        if self.format not in ["webp", "jpg", "jpeg"]:
            logger.warning(f"图片格式{self.format}不合理，使用webp")
            self.format = "webp"

        return True

    def detect_best_server(self):
        """直接返回本地服务器地址，跳过检测"""
        local_server = "http://localhost:8000"
        logger.info(f"🔧 直接使用本地服务器: {local_server}")

        # 简单测试一下连接是否成功
        try:
            response = requests.get(f"{local_server}/health", timeout=2, verify=False)
            if response.status_code == 200:
                logger.info(f"✅ 本地服务器连接成功")
            else:
                logger.warning(f"⚠️ 本地服务器返回状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ 无法连接到本地服务器 {local_server}: {e}")
            logger.error("请确认服务器 (python server_main.py) 是否在运行")

        return local_server

    def register_with_server(self):
        """向服务器注册"""
        # 检测最佳服务器
        self.current_server = self.detect_best_server()

        # 初始化API客户端
        self.api_client = APIClient(
            self.current_server,
            retry_times=self.retry_times,
            retry_delay=self.retry_delay,
        )

        # 如果已有client_id，先获取服务器配置
        if self.client_id:
            logger.info(f"使用现有client_id: {self.client_id}")
            try:
                # 获取服务器配置
                config = self.api_client.get(f"/api/client/{self.client_id}/config")
                if config:
                    self._update_config_from_server(config)
                    logger.info(f"✅ 从服务器获取配置成功")
            except Exception as e:
                logger.debug(f"获取服务器配置失败: {e}")

        # 获取系统信息
        system_info = self.system_info.get_system_info()

        # 添加客户端信息（使用服务器配置的值）
        system_info.update(
            {
                "client_version": "3.0",
                "format": self.format,
                "quality": self.quality,
                "interval": self.interval,
                "capabilities": ["webp", "heartbeat", "batch", "encryption"],
            }
        )

        logger.info(f"正在向服务器注册: {self.current_server}")

        try:
            data = self.api_client.post("/api/client/register", json=system_info)

            self.client_id = data.get("client_id")
            self.employee_id = data.get("employee_id")

            # 从服务器获取最新配置
            if "config" in data:
                self._update_config_from_server(data["config"])

            logger.info(
                f"✅ 注册成功! 客户端ID: {self.client_id}, 员工ID: {self.employee_id}"
            )
            logger.info(
                f"📡 当前服务器配置 - 间隔: {self.interval}秒, 质量: {self.quality}, 格式: {self.format}"
            )

            # 保存配置
            self.config_manager.update(
                client_id=self.client_id,
                employee_id=self.employee_id,
                interval=self.interval,
                quality=self.quality,
                format=self.format,
            )

            return True

        except Exception as e:
            logger.error(f"注册失败: {e}")
            self.offline_mode = True
            return False

    def _update_config_from_server(self, config):
        """从服务器更新配置 - 服务器配置强制覆盖"""
        changed = False

        # 间隔配置 - 完全由服务器控制
        if config.get("interval") and config["interval"] != self.interval:
            self.interval = config["interval"]
            changed = True
            logger.info(f"【服务器强制】截图间隔更新为: {self.interval}秒")

        # 质量配置
        if config.get("quality") and config["quality"] != self.quality:
            self.quality = config["quality"]
            if self.screenshot_manager:
                self.screenshot_manager.quality = self.quality
            changed = True
            logger.info(f"【服务器强制】图片质量更新为: {self.quality}")

        # 格式配置
        if config.get("format") and config["format"] != self.format:
            self.format = config["format"]
            if self.screenshot_manager:
                self.screenshot_manager.format = self.format
            changed = True
            logger.info(f"【服务器强制】图片格式更新为: {self.format}")

        if changed:
            self.config_manager.update(
                interval=self.interval, quality=self.quality, format=self.format
            )

    @retry(max_retries=2)
    def send_heartbeat(self):
        """发送心跳"""
        if not self.enable_heartbeat or self.offline_mode:
            return False
        if not self.api_client or not self.client_id:
            return False

        try:
            stats = self.system_info.get_system_stats()
            heartbeat_data = {
                "status": "online",
                "timestamp": datetime.now().isoformat(),
                "stats": stats,
                "client_stats": self.get_stats(),
                "paused": self.paused,
            }

            self.api_client.post(
                f"/api/client/{self.client_id}/heartbeat", json=heartbeat_data
            )

            with self.stats_lock:
                self.stats["last_heartbeat"] = time.time()

            return True
        except Exception as e:
            logger.debug(f"心跳发送失败: {e}")
            return False

    @retry(max_retries=3)
    def upload_screenshot(self, image_path):
        """上传截图"""
        if self.offline_mode:
            logger.debug("离线模式，保存截图到本地")
            return False

        if not self.api_client or not self.client_id:
            return False

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 加密截图（如果启用）
            if self.encryption_enabled:
                image_path = self.screenshot_manager.encrypt_screenshot(image_path)

            # 准备上传数据
            with open(image_path, "rb") as f:
                files = {
                    "file": (
                        os.path.basename(image_path),
                        f,
                        "application/octet-stream",
                    )
                }
                data = {
                    "employee_id": self.employee_id,
                    "client_id": self.client_id,
                    "timestamp": timestamp,
                    "computer_name": self.system_info.get_computer_name(),
                    "windows_user": self.system_info.get_windows_user(),
                    "encrypted": str(self.encryption_enabled).lower(),
                    "format": self.format,
                }

                response = self.api_client.session.post(
                    f"{self.current_server}/api/upload",
                    files=files,
                    data=data,
                    timeout=60,
                )

            if response.status_code == 200:
                with self.stats_lock:
                    self.stats["screenshots_uploaded"] += 1
                    self.stats["last_upload_time"] = time.time()

                logger.info(f"✅ 截图上传成功: {os.path.basename(image_path)}")

                # 删除本地文件
                try:
                    os.remove(image_path)
                except:
                    pass

                return True
            else:
                logger.warning(f"上传失败: {response.status_code}")
                with self.stats_lock:
                    self.stats["upload_failures"] += 1
                return False

        except Exception as e:
            logger.error(f"上传出错: {e}")
            with self.stats_lock:
                self.stats["upload_failures"] += 1
            return False

    def upload_screenshots_batch(self):
        """批量上传截图"""
        if not self.enable_batch_upload or self.offline_mode:
            return False

        try:
            # 查找待上传的截图
            screenshots = []
            now = time.time()
            pattern = f"screenshot_*.{self.format}"

            for file in Path(".").glob(pattern):
                file_age = now - file.stat().st_mtime
                file_size = file.stat().st_size

                # 文件超过10分钟且小于10MB
                if file_age > 600 and file_size < 10 * 1024 * 1024:
                    if file.name != self.screenshot_manager.last_screenshot_path:
                        screenshots.append(str(file))

            if not screenshots:
                return False

            logger.info(f"准备批量上传 {len(screenshots)} 个截图")

            # 创建ZIP文件
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for screenshot in screenshots:
                    zip_file.write(screenshot, os.path.basename(screenshot))

            # 上传ZIP
            files = {
                "batch": ("screenshots.zip", zip_buffer.getvalue(), "application/zip")
            }
            data = {
                "client_id": self.client_id,
                "employee_id": self.employee_id,
                "count": len(screenshots),
            }

            response = self.api_client.session.post(
                f"{self.current_server}/api/upload/batch",
                files=files,
                data=data,
                timeout=120,
            )

            if response.status_code == 200:
                # 上传成功后删除本地文件
                for screenshot in screenshots:
                    try:
                        os.remove(screenshot)
                    except:
                        pass

                with self.stats_lock:
                    self.stats["screenshots_uploaded"] += len(screenshots)
                    self.stats["last_upload_time"] = time.time()

                logger.info(f"✅ 批量上传成功: {len(screenshots)}个文件")
                return True
            else:
                logger.warning(f"批量上传失败: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"批量上传失败: {e}")
            return False

    def get_stats(self):
        """获取统计信息"""
        with self.stats_lock:
            stats_copy = self.stats.copy()
            if stats_copy["start_time"]:
                stats_copy["uptime"] = time.time() - stats_copy["start_time"]
            return stats_copy

    def add_error(self, error):
        """记录错误"""
        with self.error_lock:
            self.stats["errors"].append(
                {"time": datetime.now().isoformat(), "error": str(error)}
            )
            if len(self.stats["errors"]) > 10:
                self.stats["errors"] = self.stats["errors"][-10:]

    def config_watcher(self):
        """配置文件监控线程"""
        while self.running:
            try:
                if self.config_manager.reload_if_changed():
                    old_interval = self.interval
                    self._load_config()
                    if old_interval != self.interval:
                        logger.info(f"截图间隔已更新为: {self.interval}秒")
            except Exception as e:
                logger.error(f"配置监控出错: {e}")

            time.sleep(5)

    def heartbeat_sender(self):
        """心跳发送线程"""
        while self.running:
            try:
                if not self.offline_mode:
                    self.send_heartbeat()
            except Exception as e:
                logger.debug(f"心跳发送失败: {e}")

            for _ in range(60):
                if not self.running:
                    break
                time.sleep(1)

    def batch_uploader(self):
        """批量上传线程"""
        while self.running:
            time.sleep(3600)
            if self.running and not self.offline_mode:
                try:
                    self.upload_screenshots_batch()
                except Exception as e:
                    logger.error(f"批量上传失败: {e}")

    def network_monitor(self):
        """网络监控线程"""
        consecutive_failures = 0

        while self.running:
            time.sleep(30)

            if not self.running:
                break

            try:
                response = requests.get(
                    f"{self.current_server}/health", timeout=5, verify=False
                )
                if response.status_code == 200:
                    if self.offline_mode:
                        logger.info("网络已恢复，重新连接...")
                        self.offline_mode = False
                        consecutive_failures = 0

                        # 尝试重新注册
                        try:
                            self.register_with_server()
                        except:
                            pass
                    else:
                        consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except:
                consecutive_failures += 1

            # 连续失败5次，切换到离线模式
            if consecutive_failures >= 5 and not self.offline_mode:
                logger.warning("网络连接失败，切换到离线模式")
                self.offline_mode = True

    def work_loop(self):
        """主工作循环"""
        logger.info(f"开始监控，员工ID: {self.employee_id}")
        logger.info(f"截图间隔: {self.interval}秒")
        logger.info(f"图片格式: {self.format}")

        last_sync = 0
        consecutive_failures = 0
        last_screenshot_path = None

        while self.running:
            try:
                if self.paused:
                    time.sleep(5)
                    continue

                if self.take_screenshot_now:
                    self.take_screenshot_now = False
                    logger.info("执行立即截图")
                else:
                    for _ in range(self.interval):
                        if not self.running or self.paused:
                            break
                        time.sleep(1)

                now = time.time()

                # 同步配置（每10分钟）
                if now - last_sync > 600 and not self.offline_mode:
                    try:
                        config = self.api_client.get(
                            f"/api/client/{self.client_id}/config"
                        )
                        if config:
                            self._update_config_from_server(config)
                    except:
                        pass
                    last_sync = now

                # 截图
                image_path = self.screenshot_manager.take_screenshot()
                if image_path:
                    with self.stats_lock:
                        self.stats["screenshots_taken"] += 1

                    # 检查是否与上一张相似
                    if last_screenshot_path and self.screenshot_manager.are_similar(
                        last_screenshot_path, image_path
                    ):
                        logger.debug("屏幕内容无变化，跳过上传")
                        os.remove(image_path)
                        consecutive_failures = 0
                    else:
                        # 上传截图
                        if self.upload_screenshot(image_path):
                            consecutive_failures = 0
                            if last_screenshot_path and os.path.exists(
                                last_screenshot_path
                            ):
                                try:
                                    os.remove(last_screenshot_path)
                                except:
                                    pass
                            self.screenshot_manager.last_screenshot_path = image_path
                            last_screenshot_path = image_path
                        else:
                            consecutive_failures += 1
                            logger.warning(
                                f"上传失败，保留本地文件 (连续失败: {consecutive_failures})"
                            )

                            if consecutive_failures > 5:
                                self.interval = min(self.interval * 2, 3600)
                                logger.warning(
                                    f"连续失败次数过多，调整截图间隔为: {self.interval}秒"
                                )
                                self.config_manager.set("interval", self.interval)

            except Exception as e:
                logger.error(f"工作循环出错: {e}")
                self.add_error(e)
                time.sleep(60)

    def start(self):
        """启动监控"""
        logger.info("=" * 50)
        logger.info("员工监控系统客户端 v3.0")
        logger.info("=" * 50)

        # 验证配置
        if not self.validate_config():
            logger.error("配置验证失败，程序退出")
            return

        # 注册到服务器
        if not self.register_with_server():
            logger.warning("注册失败，将以离线模式运行")
            self.offline_mode = True

        self.running = True
        self.stats["start_time"] = time.time()

        # 启动工作线程
        threads = [
            threading.Thread(target=self.work_loop, name="WorkLoop", daemon=True),
            threading.Thread(
                target=self.config_watcher, name="ConfigWatcher", daemon=True
            ),
            threading.Thread(
                target=self.heartbeat_sender, name="Heartbeat", daemon=True
            ),
            threading.Thread(
                target=self.batch_uploader, name="BatchUploader", daemon=True
            ),
            threading.Thread(
                target=self.network_monitor, name="NetworkMonitor", daemon=True
            ),
        ]

        for thread in threads:
            thread.start()
            logger.debug(f"线程已启动: {thread.name}")

        logger.info("监控程序启动成功")

        # ===== 修改这里 =====
        # 运行托盘图标 - 放在独立线程中
        if self.tray:
            # 在新线程中运行托盘图标
            tray_thread = threading.Thread(
                target=self.tray.run, name="TrayIcon", daemon=True
            )
            tray_thread.start()
            logger.info("✅ 托盘图标线程已启动")

            # 主线程保持运行，等待退出信号
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()
        else:
            # 没有托盘图标时的原有逻辑
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def stop(self):
        """停止监控"""
        logger.info("正在停止监控程序...")
        self.running = False

        # 清理旧截图
        self.screenshot_manager.cleanup_old_screenshots()

        # 发送最后一次心跳
        if not self.offline_mode:
            self.send_heartbeat()

        # 统计信息
        uptime = time.time() - self.stats["start_time"]
        logger.info("=" * 50)
        logger.info("监控程序停止")
        logger.info(f"运行时间: {uptime/3600:.2f}小时")
        logger.info(f"截图数量: {self.stats['screenshots_taken']}")
        logger.info(f"上传成功: {self.stats['screenshots_uploaded']}")
        logger.info(f"上传失败: {self.stats['upload_failures']}")
        logger.info("=" * 50)

    def test_mode(self):
        """测试模式"""
        print("\n" + "=" * 50)
        print("测试模式 - 立即截图并上传")
        print("=" * 50)

        if not self.register_with_server():
            logger.error("注册失败")
            return

        print(f"客户端ID: {self.client_id}")
        print(f"员工ID: {self.employee_id}")
        print(f"服务器: {self.current_server}")
        print(f"图片格式: {self.format}")
        print("-" * 50)

        # 截图
        print("正在截图...")
        image_path = self.screenshot_manager.take_screenshot()

        if image_path:
            print(f"✅ 截图成功: {os.path.basename(image_path)}")
            print(f"文件大小: {os.path.getsize(image_path)/1024:.1f}KB")

            # 上传
            print("正在上传...")
            if self.upload_screenshot(image_path):
                print("✅ 上传成功")
            else:
                print("❌ 上传失败")
        else:
            print("❌ 截图失败")

        print("=" * 50)


class APIClient:
    """API客户端 - 处理所有服务器通信"""

    def __init__(self, base_url, timeout=30, retry_times=3, retry_delay=1):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.last_error = None
        self.error_count = 0

        # 设置默认头
        self.session.headers.update(
            {
                "User-Agent": f"MonitorClient/{platform.platform()}",
                "Accept": "application/json",
            }
        )

        # 配置重试
        adapter = requests.adapters.HTTPAdapter(
            max_retries=retry_times, pool_connections=10, pool_maxsize=10
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    @retry()
    def get(self, endpoint, **kwargs):
        """GET请求"""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", False)

        try:
            response = self.session.get(url, **kwargs)
            response.raise_for_status()
            self.error_count = 0
            self.last_error = None
            return response.json()
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            raise

    @retry()
    def post(self, endpoint, **kwargs):
        """POST请求"""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", False)

        if "json" in kwargs:
            kwargs.setdefault("headers", {})["Content-Type"] = "application/json"

        try:
            response = self.session.post(url, **kwargs)
            response.raise_for_status()
            self.error_count = 0
            self.last_error = None
            return response.json() if response.content else None
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            raise


class ScreenshotManager:
    """截图管理器"""

    def __init__(
        self,
        quality=80,
        format="webp",
        max_history=10,
        similarity_threshold=0.95,
        encryption_key=None,
    ):
        self.quality = quality
        self.format = format.lower()
        self.max_history = max_history
        self.similarity_threshold = similarity_threshold
        self.encryption_key = encryption_key

        self.last_screenshot_path = None
        self.screenshot_history = []
        self.stats = {"taken": 0, "uploaded": 0, "skipped": 0, "failed": 0}

        if self.format not in ["webp", "jpg", "jpeg"]:
            logger.warning(f"不支持的图片格式 {self.format}，使用 webp")
            self.format = "webp"

    def take_screenshot(self):
        """截取屏幕"""
        try:
            screenshot = ImageGrab.grab(all_screens=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.{self.format}"
            filepath = os.path.join(os.getcwd(), filename)

            if self.format == "webp":
                screenshot.save(
                    filepath, "WEBP", quality=self.quality, optimize=True, method=6
                )
            else:
                screenshot.save(filepath, "JPEG", quality=self.quality, optimize=True)

            file_size = os.path.getsize(filepath)

            self.screenshot_history.append(filepath)
            if len(self.screenshot_history) > self.max_history:
                old_file = self.screenshot_history.pop(0)
                if os.path.exists(old_file) and old_file != self.last_screenshot_path:
                    try:
                        os.remove(old_file)
                    except Exception:
                        pass

            self.stats["taken"] += 1
            logger.info(
                f"✅ 截图成功: {filename} ({file_size/1024:.1f}KB, {self.format})"
            )
            return filepath

        except Exception as e:
            logger.error(f"❌ 截图失败: {e}")
            return None

    def encrypt_screenshot(self, image_path):
        """加密截图文件"""
        try:
            from cryptography.fernet import Fernet

            cipher = Fernet(self.encryption_key.encode())

            with open(image_path, "rb") as f:
                image_data = f.read()

            encrypted_data = cipher.encrypt(image_data)
            encrypted_path = image_path + ".encrypted"

            with open(encrypted_path, "wb") as f:
                f.write(encrypted_data)

            os.remove(image_path)
            logger.debug(f"🔐 截图已加密: {os.path.basename(encrypted_path)}")
            return encrypted_path

        except Exception as e:
            logger.error(f"❌ 加密失败: {e}")
            return image_path

    def are_similar(self, img1_path, img2_path):
        """判断两张图片是否相似"""
        if (
            not img1_path
            or not img2_path
            or not os.path.exists(img1_path)
            or not os.path.exists(img2_path)
        ):
            return False

        try:
            # 快速比较：文件大小
            size1 = os.path.getsize(img1_path)
            size2 = os.path.getsize(img2_path)
            if abs(size1 - size2) / max(size1, size2) > 0.3:
                return False

            # 计算文件哈希
            hash1 = hashlib.md5(open(img1_path, "rb").read()).hexdigest()
            hash2 = hashlib.md5(open(img2_path, "rb").read()).hexdigest()

            if hash1 == hash2:
                return True

            # 如果哈希不同，比较图片内容
            img1 = Image.open(img1_path)
            img2 = Image.open(img2_path)

            img1 = img1.resize((200, 200)).convert("L")
            img2 = img2.resize((200, 200)).convert("L")

            h1 = img1.histogram()
            h2 = img2.histogram()

            import math

            mean1 = sum(h1) / len(h1)
            mean2 = sum(h2) / len(h2)

            numerator = sum((a - mean1) * (b - mean2) for a, b in zip(h1, h2))
            denominator = math.sqrt(
                sum((a - mean1) ** 2 for a in h1) * sum((b - mean2) ** 2 for b in h2)
            )

            if denominator == 0:
                return False

            correlation = numerator / denominator
            similarity = (correlation + 1) / 2

            return similarity >= self.similarity_threshold

        except Exception as e:
            logger.debug(f"图片比较失败: {e}")
            return False

    def cleanup_old_screenshots(self, max_age_hours=24):
        """清理旧截图"""
        try:
            now = time.time()
            pattern = f"screenshot_*.{self.format}"
            count = 0
            size_freed = 0

            for file in Path(".").glob(pattern):
                file_age = now - file.stat().st_mtime
                if file_age > max_age_hours * 3600:
                    size_freed += file.stat().st_size
                    file.unlink()
                    count += 1

            if count > 0:
                logger.info(
                    f"清理了 {count} 个旧截图，释放 {size_freed/1024/1024:.2f}MB"
                )

        except Exception as e:
            logger.error(f"清理旧截图失败: {e}")

    def get_stats(self):
        """获取截图统计"""
        return self.stats.copy()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="员工监控系统客户端 - 完整增强版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-c", "--config", default="config.json", help="配置文件路径 (默认: config.json)"
    )
    parser.add_argument("--test", action="store_true", help="测试模式：立即截图并上传")
    parser.add_argument("--register", action="store_true", help="仅注册，不启动监控")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认: INFO)",
    )
    parser.add_argument("--server", action="append", help="指定服务器地址 (可多次使用)")
    parser.add_argument("--interval", type=int, help="截图间隔（秒）")
    parser.add_argument(
        "--quality", type=int, choices=range(10, 101), help="图片质量 (10-100)"
    )
    parser.add_argument("--format", choices=["webp", "jpg", "jpeg"], help="图片格式")
    parser.add_argument("--encrypt", action="store_true", help="启用加密")
    parser.add_argument("--version", action="version", version="员工监控系统客户端 3.0")

    args = parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 创建客户端实例
    client = MonitorClient(args.config)

    # 命令行参数覆盖配置
    if args.server:
        client.server_urls = args.server
        client.config_manager.set("server_urls", args.server)
        logger.info(f"使用命令行指定的服务器: {args.server}")

    if args.interval:
        client.interval = args.interval
        client.config_manager.set("interval", args.interval)

    if args.quality:
        client.quality = args.quality
        client.config_manager.set("quality", args.quality)

    if args.format:
        client.format = args.format
        client.config_manager.set("format", args.format)

    if args.encrypt:
        client.encryption_enabled = True
        client.config_manager.set("encryption_enabled", True)

    # 执行相应模式
    try:
        if args.test:
            client.test_mode()
        elif args.register:
            client.register_with_server()
        else:
            client.start()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
