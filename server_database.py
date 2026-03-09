"""
数据库连接配置 - 支持主备切换，支持 Aiven SSL
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
import logging

from server_config import Config

logger = logging.getLogger(__name__)


# ========== 添加 SSL 连接配置 ==========
def get_connect_args():
    """获取数据库连接参数，支持 Aiven SSL"""
    connect_args = {}

    # 检查是否需要 SSL（Aiven 需要）
    if (
        "aiven" in Config.PRIMARY_DATABASE_URL.lower()
        or "sslmode" in Config.PRIMARY_DATABASE_URL
    ):
        connect_args["sslmode"] = "require"

        # 如果有 CA 证书文件
        if os.path.exists(Config.CA_CERT_PATH):
            connect_args["sslrootcert"] = Config.CA_CERT_PATH
            logger.info(f"使用 CA 证书: {Config.CA_CERT_PATH}")

    return connect_args


# 主数据库引擎 - 添加 connect_args
primary_engine = create_engine(
    Config.PRIMARY_DATABASE_URL,
    pool_size=Config.DB_POOL_SIZE,
    max_overflow=Config.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=Config.DB_POOL_RECYCLE,
    connect_args=get_connect_args(),  # 添加这行
    echo=Config.DEBUG,
)

# 主数据库会话
PrimarySessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=primary_engine
)

# 备用数据库引擎（如果配置了）
backup_engine = None
BackupSessionLocal = None

if Config.BACKUP_DATABASE_URL:
    backup_engine = create_engine(
        Config.BACKUP_DATABASE_URL,
        pool_size=Config.DB_POOL_SIZE,
        max_overflow=Config.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=Config.DB_POOL_RECYCLE,
        connect_args=get_connect_args(),  # 添加这行
        echo=Config.DEBUG,
    )
    BackupSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=backup_engine
    )

Base = declarative_base()

# 导出 engine 变量
engine = primary_engine

# 定义 __all__ 列表，明确指定可以导入的内容
__all__ = [
    "Base",
    "engine",
    "PrimarySessionLocal",
    "get_db",
    "get_backup_db",
    "get_db_context",
    "check_database_health",
]


def get_db():
    """获取主数据库会话"""
    db = PrimarySessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_backup_db():
    """获取备用数据库会话"""
    if not BackupSessionLocal:
        raise Exception("备用数据库未配置")
    db = BackupSessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """上下文管理器方式获取数据库会话"""
    db = PrimarySessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_health():
    """检查数据库健康状态"""
    try:
        db = PrimarySessionLocal()
        db.execute("SELECT 1")
        db.close()
        return True, "healthy"
    except Exception as e:
        logger.error(f"主数据库健康检查失败: {e}")

        # 尝试备用数据库
        if BackupSessionLocal:
            try:
                db = BackupSessionLocal()
                db.execute("SELECT 1")
                db.close()
                return True, "healthy (using backup)"
            except Exception as e2:
                logger.error(f"备用数据库健康检查失败: {e2}")
                return False, str(e2)

        return False, str(e)
