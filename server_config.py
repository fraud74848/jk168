import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ========== 基础配置 ==========
    DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(24).hex())

    # ========== 数据库配置（Aiven）==========
    PRIMARY_DATABASE_URL = os.environ.get("DATABASE_URL")
    if not PRIMARY_DATABASE_URL:
        raise ValueError("生产环境必须设置 DATABASE_URL 环境变量")

    # Aiven SSL 配置
    CA_CERT_PATH = os.environ.get("CA_CERT_PATH", "./ca.pem")

    # 数据库连接池配置
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
    DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "300"))

    # ========== JWT配置 ==========
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "480")
    )

    # ========== 管理员配置 ==========
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    if not ADMIN_PASSWORD:
        raise ValueError("生产环境必须设置 ADMIN_PASSWORD 环境变量")

    # ========== 存储配置 ==========
    SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/data/screenshots")
    SCREENSHOT_FORMAT = os.environ.get("SCREENSHOT_FORMAT", "webp").lower()
    SCREENSHOT_QUALITY = int(os.environ.get("SCREENSHOT_QUALITY", "80"))
    SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", "60"))

    # ========== 自动清理配置 ==========
    AUTO_CLEANUP_ENABLED = (
        os.environ.get("AUTO_CLEANUP_ENABLED", "true").lower() == "true"
    )
    CLEANUP_INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", "21600"))
    SCREENSHOT_RETENTION_HOURS = int(os.environ.get("SCREENSHOT_RETENTION_HOURS", "4"))

    # ========== 缩略图配置 ==========
    THUMBNAIL_SIZE = (320, 240)
    THUMBNAIL_QUALITY = 75

    # ========== 上传限制 ==========
    MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", "20")) * 1024 * 1024
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp"}

    # ========== 性能配置 ==========
    MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))
    REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
