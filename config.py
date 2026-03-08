import os
from datetime import timedelta

class Config:
    # 基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24).hex())
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # ========== 多数据库支持 ==========
    # 主数据库（Aiven PostgreSQL）
    PRIMARY_DATABASE_URL = os.environ.get('DATABASE_URL', '')
    # 备用数据库（本地或另一个云数据库）
    BACKUP_DATABASE_URL = os.environ.get('BACKUP_DATABASE_URL', '')
    
    # 数据库连接池配置
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'max_overflow': 20
    }
    
    # 根据环境变量决定使用哪个数据库
    if os.environ.get('USE_BACKUP_DB', 'false').lower() == 'true' and BACKUP_DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = BACKUP_DATABASE_URL.replace('postgres://', 'postgresql://')
    else:
        SQLALCHEMY_DATABASE_URI = PRIMARY_DATABASE_URL.replace('postgres://', 'postgresql://')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 修复：只添加有效的数据库绑定
    SQLALCHEMY_BINDS = {}
    if PRIMARY_DATABASE_URL:
        SQLALCHEMY_BINDS['primary'] = PRIMARY_DATABASE_URL.replace('postgres://', 'postgresql://')
    if BACKUP_DATABASE_URL:
        SQLALCHEMY_BINDS['backup'] = BACKUP_DATABASE_URL.replace('postgres://', 'postgresql://')
    
    # Aiven SSL配置
    if 'aiven' in PRIMARY_DATABASE_URL.lower():
        SQLALCHEMY_ENGINE_OPTIONS['connect_args'] = {
            'sslmode': 'require',
            'sslrootcert': os.environ.get('CA_CERT_PATH', 'ca.pem')
        }
    
    # 管理员配置
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    
    # ========== 存储配置 ==========
    SCREENSHOT_DIR = os.environ.get('SCREENSHOT_DIR', '/data/screenshots')
    
    # 图片格式和质量设置
    SCREENSHOT_FORMAT = os.environ.get('SCREENSHOT_FORMAT', 'webp').lower()  # webp 或 jpg
    SCREENSHOT_QUALITY = int(os.environ.get('SCREENSHOT_QUALITY', '80'))
    
    # WebP特定配置
    if SCREENSHOT_FORMAT == 'webp':
        SCREENSHOT_EXTENSION = '.webp'
        SCREENSHOT_MIME = 'image/webp'
    else:
        SCREENSHOT_EXTENSION = '.jpg'
        SCREENSHOT_MIME = 'image/jpeg'
    
    # ========== 自动清理配置 ==========
    # 清理间隔（秒）- 6小时 = 21600秒
    CLEANUP_INTERVAL = int(os.environ.get('CLEANUP_INTERVAL', '21600'))
    # 保留时间（小时）- 6小时
    SCREENSHOT_RETENTION_HOURS = int(os.environ.get('SCREENSHOT_RETENTION_HOURS', '4'))
    # 是否启用自动清理
    AUTO_CLEANUP_ENABLED = os.environ.get('AUTO_CLEANUP_ENABLED', 'true').lower() == 'true'
    
    # 缩略图配置
    THUMBNAIL_SIZE = (320, 240)
    THUMBNAIL_QUALITY = 75
    
    # 上传限制
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'bmp'}
