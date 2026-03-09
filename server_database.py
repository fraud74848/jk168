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


# ========== 关键修复：强制转换URL格式 ==========
def fix_database_url(url):
    """强制将 postgres:// 转换为 postgresql://"""
    if not url:
        return url
    
    # 打印原始URL（隐藏密码）
    safe_url = url
    if '@' in url:
        parts = url.split('@')
        auth_part = parts[0].split(':')
        if len(auth_part) > 2:
            safe_url = f"{auth_part[0]}:****@{parts[1]}"
    logger.info(f"原始URL: {safe_url}")
    
    # 强制转换
    if url.startswith('postgres://'):
        fixed_url = url.replace('postgres://', 'postgresql://', 1)
        logger.info(f"✅ 数据库URL已修复: postgres:// -> postgresql://")
        return fixed_url
    
    return url


# ========== SSL 连接配置 ==========
def get_connect_args():
    """获取数据库连接参数，支持 Aiven SSL"""
    connect_args = {}
    
    # 获取数据库URL（使用修复后的）
    db_url = Config.PRIMARY_DATABASE_URL or ""
    
    # 检查是否需要 SSL
    if "sslmode=require" in db_url or "aiven" in db_url.lower():
        connect_args["sslmode"] = "require"
        logger.info("✅ 启用 SSL 连接")

        # 优先使用系统证书（Render环境）
        if os.path.exists('/etc/ssl/certs/ca-certificates.crt'):
            connect_args["sslrootcert"] = '/etc/ssl/certs/ca-certificates.crt'
            logger.info("✅ 使用系统CA证书")
        # 其次使用自定义证书
        elif os.path.exists(Config.CA_CERT_PATH):
            connect_args["sslrootcert"] = Config.CA_CERT_PATH
            logger.info(f"使用自定义CA证书: {Config.CA_CERT_PATH}")

    return connect_args


# ========== 修复主数据库URL ==========
fixed_primary_url = fix_database_url(Config.PRIMARY_DATABASE_URL)
logger.info(f"连接到主数据库: {fixed_primary_url.split('@')[-1] if '@' in fixed_primary_url else fixed_primary_url}")

# 主数据库引擎
primary_engine = create_engine(
    fixed_primary_url,  # 使用修复后的URL
    pool_size=Config.DB_POOL_SIZE,
    max_overflow=Config.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=Config.DB_POOL_RECYCLE,
    connect_args=get_connect_args(),
    echo=Config.DEBUG,
)

# 主数据库会话
PrimarySessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=primary_engine
)

# ========== 备用数据库（如果配置了）==========
backup_engine = None
BackupSessionLocal = None

if Config.BACKUP_DATABASE_URL:
    fixed_backup_url = fix_database_url(Config.BACKUP_DATABASE_URL)
    logger.info(f"连接到备用数据库: {fixed_backup_url.split('@')[-1] if '@' in fixed_backup_url else fixed_backup_url}")
    
    backup_engine = create_engine(
        fixed_backup_url,
        pool_size=Config.DB_POOL_SIZE,
        max_overflow=Config.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=Config.DB_POOL_RECYCLE,
        connect_args=get_connect_args(),
        echo=Config.DEBUG,
    )
    BackupSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=backup_engine
    )

Base = declarative_base()

# 导出 engine 变量
engine = primary_engine

# 定义 __all__ 列表
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
