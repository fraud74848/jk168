#!/usr/bin/env python3
"""
员工监控系统服务器 - FastAPI完整增强版
功能：
1. 多数据库支持（主备切换）
2. 自动清理线程
3. 客户端自动注册
4. 截图管理
5. 统计报表
6. 健康检查
7. 备份支持
"""

from fastapi import (
    FastAPI,
    File,
    UploadFile,
    Form,
    Depends,
    HTTPException,
    status,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import os
import uuid
import logging
import asyncio
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from pydantic import BaseModel
from sqlalchemy import exists, and_, or_, select
from sqlalchemy.orm import selectinload

import server_models as models
import server_schemas as schemas
from server_database import engine, get_db, get_backup_db
from server_auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_active_user,
    get_current_admin_user,
    verify_password,
)
from server_cleanup import DataCleanup
from server_config import Config
from server_timezone import get_beijing_now, get_date_range_for_day

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建数据库表
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="员工监控系统 API",
    description="企业级员工行为监控系统",
    version="3.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需要限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 创建存储目录
STORAGE_PATH = Path(Config.SCREENSHOT_DIR)
STORAGE_PATH.mkdir(parents=True, exist_ok=True)
logger.info(f"✅ 截图存储路径: {STORAGE_PATH.absolute()}")

THUMBNAIL_PATH = STORAGE_PATH / "thumbnails"
THUMBNAIL_PATH.mkdir(parents=True, exist_ok=True)
logger.info(f"✅ 缩略图存储路径: {THUMBNAIL_PATH.absolute()}")

# 列出一些文件用于调试
try:
    files = list(STORAGE_PATH.glob("**/*.webp"))[:5]
    if files:
        logger.info(
            f"📸 找到示例截图: {[str(f.relative_to(STORAGE_PATH)) for f in files]}"
        )
except Exception as e:
    logger.error(f"❌ 读取截图目录失败: {e}")

# 启动清理任务
cleanup = DataCleanup()


@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    logger.info("=" * 50)
    logger.info("员工监控系统服务器启动")
    logger.info(f"数据库: {Config.PRIMARY_DATABASE_URL}")
    logger.info(f"存储路径: {STORAGE_PATH}")
    logger.info(f"自动清理: {'启用' if Config.AUTO_CLEANUP_ENABLED else '禁用'}")
    logger.info(f"数据保留: {Config.SCREENSHOT_RETENTION_HOURS}小时")
    logger.info("=" * 50)

    # 启动清理任务
    asyncio.create_task(cleanup.start_cleanup_task())

    # 创建默认管理员
    try:
        db = next(get_db())
        admin = (
            db.query(models.User)
            .filter(models.User.username == Config.ADMIN_USERNAME)
            .first()
        )

        if not admin:
            admin = models.User(
                username=Config.ADMIN_USERNAME,
                password_hash=get_password_hash(Config.ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            db.commit()
            logger.info(f"✅ 默认管理员已创建: {Config.ADMIN_USERNAME}")
        else:
            logger.info(f"✅ 管理员用户已存在: {Config.ADMIN_USERNAME}")

        db.close()
    except Exception as e:
        logger.error(f"创建管理员失败: {e}")


# ==================== 健康检查 ====================


@app.get("/health", tags=["系统"])
async def health_check():
    """系统健康检查"""
    health_status = {
        "status": "healthy",
        "timestamp": get_beijing_now().isoformat(),
        "version": "3.0.0",
        "auto_cleanup": {
            "enabled": Config.AUTO_CLEANUP_ENABLED,
            "interval_hours": Config.CLEANUP_INTERVAL / 3600,
            "retention_hours": Config.SCREENSHOT_RETENTION_HOURS,
        },
        "image_config": {
            "format": Config.SCREENSHOT_FORMAT,
            "quality": Config.SCREENSHOT_QUALITY,
        },
    }

    # 检查主数据库
    try:
        db = next(get_db())
        db.execute("SELECT 1")
        db.close()
        health_status["database"] = "healthy"
    except Exception as e:
        health_status["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # 检查备用数据库（如果配置了）
    if Config.BACKUP_DATABASE_URL:
        try:
            backup_db = next(get_backup_db())
            backup_db.execute("SELECT 1")
            backup_db.close()
            health_status["backup_database"] = "healthy"
        except Exception as e:
            health_status["backup_database"] = f"unhealthy: {str(e)}"

    return health_status


# ==================== 系统设置接口 ====================


class GeneralConfigSchema(BaseModel):
    system_name: str
    default_interval: int
    default_format: str
    default_quality: int
    timezone: str


class CleanupConfigSchema(BaseModel):
    enabled: bool
    retention_hours: int
    interval_hours: int
    cleanup_time: Optional[str] = None


class StorageConfigSchema(BaseModel):
    path: str
    max_size_gb: int
    thumbnail_size: int
    thumbnail_quality: int


class SecurityConfigSchema(BaseModel):
    jwt_expire_minutes: int


class NotificationConfigSchema(BaseModel):
    enabled: bool
    methods: List[str]
    smtp_server: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None
    events: dict


class BackupConfigSchema(BaseModel):
    enabled: bool
    frequency: str
    backup_time: Optional[str] = None
    keep_count: int


@app.get("/api/settings/all", tags=["系统设置"])
def get_all_settings(
    current_user: models.User = Depends(get_current_active_user),
):
    """获取所有系统设置"""
    from server_config_manager import get_config

    return {
        "general": {
            "system_name": get_config("system_name", "员工监控系统"),
            "default_interval": get_config("screenshot_interval", 60),
            "default_format": get_config("screenshot_format", "webp"),
            "default_quality": get_config("screenshot_quality", 80),
            "timezone": get_config("timezone", "Asia/Shanghai"),
        },
        "cleanup": {
            "enabled": get_config("auto_cleanup_enabled", True),
            "retention_hours": get_config("screenshot_retention_hours", 4),
            "interval_hours": get_config("cleanup_interval", 21600) / 3600,
            "cleanup_time": get_config("cleanup_time", None),
        },
        "storage": {
            "path": get_config("screenshot_dir", "/data/screenshots"),
            "max_size_gb": get_config("max_storage_gb", 100),
            "thumbnail_size": get_config("thumbnail_size", 320),
            "thumbnail_quality": get_config("thumbnail_quality", 75),
        },
        "security": {
            "jwt_expire_minutes": get_config("jwt_expire_minutes", 480),
        },
        "backup": {
            "enabled": get_config("backup_enabled", True),
            "frequency": get_config("backup_frequency", "daily"),
            "backup_time": get_config("backup_time", None),
            "keep_count": get_config("backup_keep_count", 7),
        },
        "notification": {
            "enabled": get_config("notification_enabled", True),
            "methods": get_config("notification_methods", ["email"]),
            "smtp_server": get_config("smtp_server", ""),
            "from_email": get_config("from_email", ""),
            "to_email": get_config("to_email", ""),
            "events": get_config(
                "notification_events",
                {
                    "clientRegister": True,
                    "clientOffline": True,
                    "lowStorage": True,
                    "backupComplete": True,
                },
            ),
        },
    }


@app.post("/api/settings/general", tags=["系统设置"])
def update_general_settings(
    config: GeneralConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新通用设置"""
    from server_config_manager import set_config

    set_config(
        "system_name", config.system_name, "general", "系统名称", current_user.id
    )
    set_config(
        "screenshot_interval",
        config.default_interval,
        "general",
        "默认截图间隔",
        current_user.id,
    )
    set_config(
        "screenshot_format",
        config.default_format,
        "general",
        "默认图片格式",
        current_user.id,
    )
    set_config(
        "screenshot_quality",
        config.default_quality,
        "general",
        "默认图片质量",
        current_user.id,
    )
    set_config("timezone", config.timezone, "general", "时区", current_user.id)

    logger.info(f"通用设置已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "通用设置已保存"}


@app.post("/api/settings/cleanup", tags=["系统设置"])
def update_cleanup_settings(
    config: CleanupConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新清理策略"""
    from server_config_manager import set_config

    set_config(
        "auto_cleanup_enabled",
        config.enabled,
        "cleanup",
        "自动清理开关",
        current_user.id,
    )
    set_config(
        "screenshot_retention_hours",
        config.retention_hours,
        "cleanup",
        "截图保留时间",
        current_user.id,
    )
    set_config(
        "cleanup_interval",
        int(config.interval_hours * 3600),
        "cleanup",
        "清理间隔",
        current_user.id,
    )
    if config.cleanup_time:
        set_config(
            "cleanup_time", config.cleanup_time, "cleanup", "清理时间", current_user.id
        )

    logger.info(f"清理策略已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "清理策略已保存"}


@app.post("/api/settings/storage", tags=["系统设置"])
def update_storage_settings(
    config: StorageConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新存储设置"""
    from server_config_manager import set_config

    set_config("screenshot_dir", config.path, "storage", "存储路径", current_user.id)
    set_config(
        "max_storage_gb", config.max_size_gb, "storage", "最大存储空间", current_user.id
    )
    set_config(
        "thumbnail_size",
        config.thumbnail_size,
        "storage",
        "缩略图大小",
        current_user.id,
    )
    set_config(
        "thumbnail_quality",
        config.thumbnail_quality,
        "storage",
        "缩略图质量",
        current_user.id,
    )

    logger.info(f"存储设置已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "存储设置已保存"}


@app.post("/api/settings/security", tags=["系统设置"])
def update_security_settings(
    config: SecurityConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新安全设置"""
    from server_config_manager import set_config

    set_config(
        "jwt_expire_minutes",
        config.jwt_expire_minutes,
        "security",
        "JWT过期时间",
        current_user.id,
    )

    logger.info(f"安全设置已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "安全设置已保存"}


@app.post("/api/settings/backup", tags=["系统设置"])
def update_backup_settings(
    config: BackupConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新备份设置"""
    from server_config_manager import set_config

    set_config(
        "backup_enabled", config.enabled, "backup", "自动备份开关", current_user.id
    )
    set_config(
        "backup_frequency", config.frequency, "backup", "备份频率", current_user.id
    )
    if config.backup_time:
        set_config(
            "backup_time", config.backup_time, "backup", "备份时间", current_user.id
        )
    set_config(
        "backup_keep_count", config.keep_count, "backup", "保留备份数", current_user.id
    )

    logger.info(f"备份设置已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "备份设置已保存"}


@app.post("/api/settings/notification", tags=["系统设置"])
def update_notification_settings(
    config: NotificationConfigSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """更新通知设置"""
    from server_config_manager import set_config

    set_config(
        "notification_enabled",
        config.enabled,
        "notification",
        "通知开关",
        current_user.id,
    )
    set_config(
        "notification_methods",
        config.methods,
        "notification",
        "通知方式",
        current_user.id,
    )
    set_config(
        "smtp_server", config.smtp_server, "notification", "邮件服务器", current_user.id
    )
    set_config(
        "from_email", config.from_email, "notification", "发件人邮箱", current_user.id
    )
    set_config("to_email", config.to_email, "notification", "接收邮箱", current_user.id)
    set_config(
        "notification_events",
        config.events,
        "notification",
        "通知事件",
        current_user.id,
    )

    logger.info(f"通知设置已更新: {config.dict()} 更新者: {current_user.username}")
    return {"message": "通知设置已保存"}


# ==================== 认证接口 ====================


@app.post("/api/auth/register", response_model=schemas.User, tags=["认证"])
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """注册新用户"""
    db_user = (
        db.query(models.User).filter(models.User.username == user.username).first()
    )

    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在"
        )

    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        username=user.username, password_hash=hashed_password, role=user.role or "user"
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    logger.info(f"新用户注册: {user.username}")
    return db_user


@app.post("/api/auth/login", response_model=schemas.Token, tags=["认证"])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    """用户登录"""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=Config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires,
    )

    logger.info(f"用户登录: {user.username}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


@app.get("/api/auth/me", response_model=schemas.User, tags=["认证"])
async def get_current_user_info(
    current_user: models.User = Depends(get_current_active_user),
):
    """获取当前用户信息"""
    return current_user


# ==================== 客户端接口 ====================


@app.post("/api/client/register", response_model=schemas.Client, tags=["客户端"])
async def register_client(
    client_info: schemas.ClientCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """客户端注册"""

    # 获取当前北京时间
    beijing_now = get_beijing_now()

    # 检查是否已存在
    existing_client = (
        db.query(models.Client)
        .filter(
            (models.Client.client_id == client_info.client_id)
            | (models.Client.mac_address == client_info.mac_address)
        )
        .first()
    )

    # ===== 新增：从客户端信息中获取姓名 =====
    employee_name = None
    if hasattr(client_info, "employee_name") and client_info.employee_name:
        employee_name = client_info.employee_name
        logger.info(f"客户端传入姓名: {employee_name}")
    # ======================================

    if existing_client:
        for key, value in client_info.dict(exclude_unset=True).items():
            setattr(existing_client, key, value)
        existing_client.last_seen = beijing_now
        db.commit()
        db.refresh(existing_client)
        logger.info(f"客户端更新: {existing_client.client_id}")
        return existing_client

    # 生成员工ID
    if client_info.computer_name and client_info.windows_user:
        employee_id = f"{client_info.computer_name}\\{client_info.windows_user}"
    else:
        employee_id = client_info.computer_name or str(uuid.uuid4())

    # 检查员工是否存在
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        # ===== 修改：优先使用客户端传入的姓名 =====
        if employee_name:
            # 使用用户输入的姓名
            final_name = employee_name
        else:
            # 降级方案：使用计算机名和用户名组合
            final_name = (
                f"{client_info.computer_name} - {client_info.windows_user}"
                if client_info.windows_user
                else client_info.computer_name
            )

        employee = models.Employee(
            employee_id=employee_id,
            name=final_name,  # 使用用户输入的姓名
            computer_name=client_info.computer_name,
            windows_user=client_info.windows_user,
            department="自动注册",
            status="active",
        )
        db.add(employee)
        logger.info(f"自动创建员工: {employee_id} 姓名: {final_name}")
    else:
        # ===== 新增：如果员工已存在但姓名是默认值，可以更新为真实姓名 =====
        if employee_name and (
            not employee.name or employee.name.startswith(employee.computer_name)
        ):
            employee.name = employee_name
            logger.info(f"更新员工姓名: {employee_id} -> {employee_name}")
    # ============================================================

    # 创建客户端
    new_client = models.Client(
        client_id=client_info.client_id or str(uuid.uuid4()),
        employee_id=employee_id,
        computer_name=client_info.computer_name,
        windows_user=client_info.windows_user,
        mac_address=client_info.mac_address,
        ip_address=client_info.ip_address,
        os_version=client_info.os_version,
        cpu_id=client_info.cpu_id,
        disk_serial=client_info.disk_serial,
        client_version=client_info.client_version,
        last_seen=beijing_now,
        config={
            "interval": Config.SCREENSHOT_INTERVAL,
            "quality": client_info.quality or Config.SCREENSHOT_QUALITY,
            "format": client_info.format or Config.SCREENSHOT_FORMAT,
            "enable_heartbeat": True,
            "enable_batch_upload": True,
        },
        capabilities=client_info.capabilities or [],
    )

    db.add(new_client)
    db.commit()
    db.refresh(new_client)

    logger.info(f"新客户端注册: {new_client.client_id} ({employee_id})")

    background_tasks.add_task(
        log_activity,
        employee_id,
        "client_registered",
        {"client_id": new_client.client_id, "name": employee_name},
    )

    return new_client


@app.post("/api/client/{client_id}/heartbeat", tags=["客户端"])
async def client_heartbeat(
    client_id: str,
    heartbeat: schemas.Heartbeat,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """客户端心跳"""
    # ===== 添加北京时间 =====
    beijing_now = get_beijing_now()
    # ======================

    client = (
        db.query(models.Client).filter(models.Client.client_id == client_id).first()
    )

    if not client:
        raise HTTPException(status_code=404, detail="客户端不存在")

    # 更新客户端信息
    # ===== 修改点：使用北京时间 =====
    client.last_seen = beijing_now  # 原来是 datetime.utcnow()
    # ==============================
    client.last_stats = heartbeat.stats
    client.ip_address = heartbeat.ip_address or client.ip_address

    db.commit()

    return {
        "status": "ok",
        "server_time": beijing_now.isoformat(),  # 也返回北京时间
        "config": client.config,
    }


@app.get("/api/client/{client_id}/config", tags=["客户端"])
async def get_client_config(client_id: str, db: Session = Depends(get_db)):
    """获取客户端配置"""
    client = (
        db.query(models.Client).filter(models.Client.client_id == client_id).first()
    )

    if client:
        return client.config

    # 返回默认配置
    return {
        "interval": Config.SCREENSHOT_INTERVAL,
        "quality": Config.SCREENSHOT_QUALITY,
        "format": Config.SCREENSHOT_FORMAT,
        "enable_heartbeat": True,
        "enable_batch_upload": True,
    }


# ==================== 截图上传接口 ====================
@app.post("/api/upload", tags=["截图"])
async def upload_screenshot(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    employee_id: str = Form(...),
    client_id: Optional[str] = Form(None),
    computer_name: Optional[str] = Form(None),
    windows_user: Optional[str] = Form(None),
    timestamp: Optional[str] = Form(None),
    encrypted: bool = Form(False),
    format: str = Form("webp"),
    file: UploadFile = File(...),
):
    """上传截图 - 优化版：确保更新客户端最后在线时间"""

    # ========== 1. 验证文件类型 ==========
    allowed_extensions = {"jpg", "jpeg", "png", "webp", "bmp"}
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file_ext}")

    from server_timezone import get_beijing_now
    from datetime import datetime

    # ========== 2. 获取北京时间 ==========
    beijing_now = get_beijing_now()

    # ========== 3. 解析截图时间 ==========
    try:
        if timestamp:
            screenshot_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        else:
            screenshot_time = beijing_now
    except:
        screenshot_time = beijing_now

    # ========== 4. 处理客户端（关键修复点）==========
    client = None
    if client_id:
        client = (
            db.query(models.Client).filter(models.Client.client_id == client_id).first()
        )

    if client:
        # ✅ 重要：更新客户端的最后在线时间
        client.last_seen = beijing_now
        logger.debug(f"客户端 {client_id} 最后在线时间已更新为 {beijing_now}")

        # 如果客户端还没有关联员工ID，则关联
        if not client.employee_id:
            client.employee_id = employee_id
            logger.info(f"客户端 {client_id} 已关联员工 {employee_id}")
    else:
        # 客户端不存在，但提供了client_id - 可能是新客户端
        if client_id:
            logger.warning(f"客户端 {client_id} 不存在，将创建新客户端记录")
            # 这里可以选择自动创建客户端，或者只是记录日志

    # ========== 5. 查找或创建员工 ==========
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        # 自动创建员工
        employee_name = (
            f"{computer_name} - {windows_user}" if windows_user else computer_name
        )
        employee = models.Employee(
            employee_id=employee_id,
            name=employee_name,
            computer_name=computer_name,
            windows_user=windows_user,
            department="自动注册",
            status="active",
        )
        db.add(employee)
        logger.info(f"✅ 自动创建员工: {employee_id} - {employee_name}")

    # ========== 6. 保存文件 ==========
    date_str = screenshot_time.strftime("%Y-%m-%d")
    safe_employee_id = employee_id.replace("\\", os.path.sep)

    # 生成文件名
    filename = (
        f"{safe_employee_id}/{date_str}/{screenshot_time.strftime('%H-%M-%S')}.{format}"
    )
    file_path = STORAGE_PATH / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存文件
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    # 获取文件大小
    file_size = file_path.stat().st_size

    # ========== 7. 创建缩略图（异步）==========
    thumbnail_path = (
        THUMBNAIL_PATH
        / f"{safe_employee_id}/{date_str}/{screenshot_time.strftime('%H-%M-%S')}.webp"
    )
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    background_tasks.add_task(create_thumbnail, str(file_path), str(thumbnail_path))

    # ========== 8. 获取图片尺寸 ==========
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            width, height = img.size
    except:
        width = height = 0

    # ========== 9. 保存截图记录 ==========
    screenshot = models.Screenshot(
        employee_id=employee_id,
        client_id=client_id,
        filename=str(filename),
        thumbnail=(
            str(thumbnail_path.relative_to(STORAGE_PATH))
            if thumbnail_path.exists()
            else None
        ),
        file_size=file_size,
        width=width,
        height=height,
        storage_url=f"/screenshots/{filename}",
        screenshot_time=screenshot_time,
        computer_name=computer_name,
        windows_user=windows_user,
        image_format=format,
        is_encrypted=encrypted,
    )

    db.add(screenshot)
    db.commit()

    logger.info(
        f"✅ 截图保存成功: {filename} ({file_size/1024:.1f}KB) - 员工: {employee_id}"
    )

    # ========== 10. 返回结果 ==========
    return {
        "success": True,
        "id": screenshot.id,
        "url": screenshot.storage_url,
        "thumbnail": (
            f"/screenshots/{screenshot.thumbnail}" if screenshot.thumbnail else None
        ),
        "size": file_size,
        "employee_id": employee_id,
        "client_id": client_id,
        "timestamp": screenshot_time.isoformat(),
    }


@app.post("/api/upload/batch", tags=["截图"])
async def upload_batch(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    client_id: str = Form(...),
    employee_id: str = Form(...),
    count: int = Form(...),
    batch: UploadFile = File(...),
):
    """批量上传截图"""
    from server_timezone import get_beijing_now

    # ===== 修改点：使用北京时间生成文件名 =====
    # 保存ZIP文件
    zip_path = (
        STORAGE_PATH
        / "temp"
        / f"batch_{get_beijing_now().strftime('%Y%m%d_%H%M%S')}.zip"
        # 原来是：datetime.now().strftime('%Y%m%d_%H%M%S')
    )
    # ======================================

    zip_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(batch.file, buffer)

        # 异步处理ZIP文件
        background_tasks.add_task(
            process_batch_upload, str(zip_path), client_id, employee_id, count
        )

        return {"success": True, "message": f"批量上传已接收，共 {count} 个文件"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {e}")


# ==================== 员工管理接口 ====================
@app.get("/api/employees", tags=["员工"])
def get_employees(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    online_only: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    获取员工列表（生产级版本）
    支持：
    - 分页
    - 搜索
    - 状态筛选
    - 在线状态筛选
    """
    logger = logging.getLogger(__name__)
    logger.debug(
        f"员工列表请求 - skip:{skip}, limit:{limit}, status:{status}, online_only:{online_only}, search:{search}"
    )

    # 在线判断时间（10分钟内在线）
    cutoff = datetime.utcnow() - timedelta(minutes=10)

    # 基础查询
    query = db.query(models.Employee)

    # 状态筛选
    if status:
        query = query.filter(models.Employee.status == status)

    # 搜索
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Employee.name.ilike(search_term),
                models.Employee.employee_id.ilike(search_term),
                models.Employee.department.ilike(search_term),
                models.Employee.position.ilike(search_term),
            )
        )

    # 在线筛选（数据库级）
    if online_only is not None:
        # 正确的 exists 子查询
        online_subquery = exists().where(
            and_(
                models.Client.employee_id == models.Employee.employee_id,
                models.Client.last_seen >= cutoff,
            )
        )

        if online_only:
            query = query.filter(online_subquery)
            logger.debug(f"应用在线筛选，时间阈值: {cutoff}")
        else:
            query = query.filter(~online_subquery)
            logger.debug(f"应用离线筛选，时间阈值: {cutoff}")

    # 总数统计
    total = query.count()

    # 分页 + 预加载 clients
    employees = (
        query.options(selectinload(models.Employee.clients))
        .offset(skip)
        .limit(limit)
        .all()
    )

    # 转换为 dict
    items = [emp.to_dict() for emp in employees]

    logger.debug(f"返回 {len(items)} 条记录，总数: {total}")

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ===== 修改点1：日期路由必须放在最前面，使用 path 参数 =====
@app.get("/api/employees/{employee_id:path}/dates", tags=["员工"])
def get_employee_dates(
    employee_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取员工有截图的所有日期"""
    screenshots = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.employee_id == employee_id)
        .all()
    )

    dates = {}
    for s in screenshots:
        date = s.screenshot_time.strftime("%Y-%m-%d")
        dates[date] = dates.get(date, 0) + 1

    result = [
        {"date": d, "count": dates[d]} for d in sorted(dates.keys(), reverse=True)
    ]
    return result


# ====================================================


# ===== 修改点2：获取单个员工，使用 path 参数 =====
@app.get(
    "/api/employees/{employee_id:path}", response_model=schemas.Employee, tags=["员工"]
)
def get_employee(
    employee_id: str,  # 这里会捕获完整的 "OS-20250218QMGZ\Administrator"
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取单个员工"""
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    return employee


# ==============================================


@app.post("/api/employees", response_model=schemas.Employee, tags=["员工"])
def create_employee(
    employee: schemas.EmployeeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """创建员工"""
    db_employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee.employee_id)
        .first()
    )

    if db_employee:
        raise HTTPException(status_code=400, detail="员工ID已存在")

    db_employee = models.Employee(**employee.dict())
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)

    logger.info(f"员工创建: {employee.employee_id}")
    return db_employee


# ===== 修改点3：更新员工（你已经改好了） =====
@app.put(
    "/api/employees/{employee_id:path}", response_model=schemas.Employee, tags=["员工"]
)
def update_employee(
    employee_id: str,  # 这里会捕获完整的 "OS-20250218QMGZ\Administrator"
    employee_update: schemas.EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """更新员工信息"""
    db_employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)  # 直接用完整ID查询
        .first()
    )

    if not db_employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    for key, value in employee_update.dict(exclude_unset=True).items():
        setattr(db_employee, key, value)

    db.commit()
    db.refresh(db_employee)

    logger.info(f"员工更新: {employee_id}")
    return db_employee


# ==========================================


# ===== 修改点4：删除员工，使用 path 参数 =====
@app.delete("/api/employees/{employee_id:path}", tags=["员工"])
def delete_employee(
    employee_id: str,  # 这里会捕获完整的 "OS-20250218QMGZ\Administrator"
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """删除员工"""
    db_employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .first()
    )

    if not db_employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    # 检查是否有截图
    screenshot_count = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.employee_id == employee_id)
        .count()
    )

    if screenshot_count > 0:
        # 软删除或提示
        db_employee.status = "deleted"
        db.commit()
        return {"message": f"员工已标记为删除，关联 {screenshot_count} 张截图"}

    db.delete(db_employee)
    db.commit()

    logger.info(f"员工删除: {employee_id}")
    return {"message": "员工已删除"}


# ==================== 截图接口 ====================
@app.get("/api/screenshots", tags=["截图"])
def get_screenshots(
    employee_id: Optional[str] = None,
    client_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取截图列表（支持分页和时间筛选）"""

    from sqlalchemy import text
    import logging
    from datetime import datetime

    logger = logging.getLogger(__name__)

    try:
        # ==============================
        # 1. 参数验证和预处理
        # ==============================

        # 验证分页参数
        if skip < 0 or limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="无效的分页参数")

        # ✅ 修复：放宽日期格式验证，支持完整时间字符串
        # 日期格式可以是 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS
        date_pattern = r"^\d{4}-\d{2}-\d{2}(\s\d{2}:\d{2}:\d{2})?$"
        time_pattern = r"^\d{2}:\d{2}(:\d{2})?$"

        import re

        # 验证日期参数（允许带时间）
        if start_date and not re.match(date_pattern, start_date):
            raise HTTPException(
                status_code=400,
                detail="开始日期格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS",
            )
        if end_date and not re.match(date_pattern, end_date):
            raise HTTPException(
                status_code=400,
                detail="结束日期格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS",
            )

        # 验证时间参数
        if start_time and not re.match(time_pattern, start_time):
            raise HTTPException(
                status_code=400, detail="开始时间格式应为 HH:MM 或 HH:MM:SS"
            )
        if end_time and not re.match(time_pattern, end_time):
            raise HTTPException(
                status_code=400, detail="结束时间格式应为 HH:MM 或 HH:MM:SS"
            )

        # ==============================
        # 2. 构建基础查询
        # ==============================

        # 注意：这里不能简单替换，需要单独构建count查询
        base_sql = """
            FROM screenshots s
            LEFT JOIN employees e ON s.employee_id = e.employee_id
            WHERE 1=1
        """

        select_sql = """
            SELECT
                s.id,
                s.employee_id,
                s.client_id,
                s.filename,
                s.thumbnail,
                s.file_size,
                s.width,
                s.height,
                s.storage_url,
                s.uploaded_at,
                s.screenshot_time,
                s.computer_name,
                s.windows_user,
                s.image_format,
                s.is_encrypted,
                e.name as employee_name
        """

        params = {}

        # 员工筛选
        if employee_id:
            base_sql += " AND s.employee_id = :employee_id"
            params["employee_id"] = employee_id

        # 客户端筛选
        if client_id:
            base_sql += " AND s.client_id = :client_id"
            params["client_id"] = client_id

        # ==============================
        # 3. 日期时间处理（修复版）
        # ==============================

        # 处理带日期的时间范围
        if start_date and start_time:
            # 合并日期和时间
            start_datetime = f"{start_date} {start_time}"
            if len(start_time) == 5:  # HH:MM 格式
                start_datetime += ":00"
            base_sql += " AND s.screenshot_time >= :start_datetime"
            params["start_datetime"] = start_datetime
        elif start_date:
            # 只有日期，从当天开始
            base_sql += " AND s.screenshot_time >= :start_date"
            params["start_date"] = f"{start_date} 00:00:00"
        elif start_time:
            # 只有时间，使用今天日期
            today = datetime.now().strftime("%Y-%m-%d")
            start_datetime = f"{today} {start_time}"
            if len(start_time) == 5:
                start_datetime += ":00"
            base_sql += " AND s.screenshot_time >= :start_datetime"
            params["start_datetime"] = start_datetime

        if end_date and end_time:
            # 合并日期和时间
            end_datetime = f"{end_date} {end_time}"
            if len(end_time) == 5:
                end_datetime += ":59"
            base_sql += " AND s.screenshot_time <= :end_datetime"
            params["end_datetime"] = end_datetime
        elif end_date:
            # 只有日期，到当天结束
            base_sql += " AND s.screenshot_time <= :end_date"
            params["end_date"] = f"{end_date} 23:59:59"
        elif end_time:
            # 只有时间，使用今天日期
            today = datetime.now().strftime("%Y-%m-%d")
            end_datetime = f"{today} {end_time}"
            if len(end_time) == 5:
                end_datetime += ":59"
            base_sql += " AND s.screenshot_time <= :end_datetime"
            params["end_datetime"] = end_datetime

        # ==============================
        # 4. 获取总数
        # ==============================

        count_sql = f"SELECT COUNT(*) {base_sql}"
        total = db.execute(text(count_sql), params).scalar() or 0

        # ==============================
        # 5. 大分页优化（保留第一个接口的优点）
        # ==============================

        if skip >= 1000:
            # 使用游标方式优化大分页
            cursor_sql = f"""
                SELECT screenshot_time 
                {base_sql} 
                ORDER BY screenshot_time DESC 
                OFFSET :skip LIMIT 1
            """
            cursor_params = params.copy()
            cursor_params["skip"] = skip

            cursor_time = db.execute(text(cursor_sql), cursor_params).scalar()

            if cursor_time:
                base_sql += " AND s.screenshot_time <= :cursor_time"
                params["cursor_time"] = cursor_time

            # 重置skip，使用游标后不需要offset
            sql = (
                f"{select_sql} {base_sql} ORDER BY s.screenshot_time DESC LIMIT :limit"
            )
            params["limit"] = limit
        else:
            # 小偏移量直接使用OFFSET
            sql = f"{select_sql} {base_sql} ORDER BY s.screenshot_time DESC OFFSET :skip LIMIT :limit"
            params["skip"] = skip
            params["limit"] = limit

        # ==============================
        # 6. 执行查询
        # ==============================

        result = db.execute(text(sql), params).fetchall()

        # ==============================
        # 7. 数据转换（复用format_size函数）
        # ==============================

        def format_file_size(size):
            """格式化文件大小"""
            if not size:
                return "0 B"
            for unit in ["B", "KB", "MB", "GB"]:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"

        screenshots = []
        for row in result:
            row_dict = dict(row._mapping)
            st = row_dict.get("screenshot_time")

            screenshot = {
                "id": row_dict.get("id"),
                "employee_id": row_dict.get("employee_id"),
                "name": row_dict.get("employee_name") or row_dict.get("employee_id"),
                "client_id": row_dict.get("client_id"),
                "filename": row_dict.get("filename"),
                "thumbnail": row_dict.get("thumbnail"),
                "file_size": row_dict.get("file_size"),
                "width": row_dict.get("width"),
                "height": row_dict.get("height"),
                "storage_url": row_dict.get("storage_url"),
                "uploaded_at": (
                    row_dict.get("uploaded_at").isoformat()
                    if row_dict.get("uploaded_at")
                    else None
                ),
                "screenshot_time": st.isoformat() if st else None,
                "computer_name": row_dict.get("computer_name"),
                "windows_user": row_dict.get("windows_user"),
                "image_format": row_dict.get("image_format"),
                "is_encrypted": row_dict.get("is_encrypted"),
                "url": row_dict.get("storage_url"),
                "time": st.strftime("%H:%M:%S") if st else None,
                "date": st.strftime("%Y-%m-%d") if st else None,
                "datetime": st.strftime("%Y-%m-%d %H:%M:%S") if st else None,
                "size_str": format_file_size(row_dict.get("file_size")),
                "format": row_dict.get("image_format"),
                "encrypted": row_dict.get("is_encrypted"),
            }
            screenshots.append(screenshot)

        logger.info(
            f"截图查询成功: 条件(employee={employee_id}, date={start_date}~{end_date}), 总数={total}, 返回={len(screenshots)}条"
        )

        return {
            "items": screenshots,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(screenshots)) < total,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"截图接口错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@app.get(
    "/api/screenshots/{employee_id}/{date}",
    response_model=List[schemas.Screenshot],
    tags=["截图"],
)
def get_screenshots_by_date(
    employee_id: str,
    date: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取员工指定日期的截图"""
    from sqlalchemy import text

    try:
        start = datetime.strptime(date, "%Y-%m-%d")
        end = start + timedelta(days=1)
    except:
        raise HTTPException(status_code=400, detail="日期格式错误")

    # 使用原生SQL查询，直接连表获取员工姓名
    sql = """
        SELECT 
            s.*,
            e.name as name
        FROM screenshots s
        LEFT JOIN employees e ON s.employee_id = e.employee_id
        WHERE s.employee_id = :employee_id
            AND s.screenshot_time >= :start_date
            AND s.screenshot_time < :end_date
        ORDER BY s.screenshot_time DESC
    """

    params = {"employee_id": employee_id, "start_date": start, "end_date": end}

    # 执行查询
    result = db.execute(text(sql), params).fetchall()

    # 转换为字典列表
    screenshots = []
    for row in result:
        row_dict = dict(row._mapping)

        screenshot = {
            "id": row_dict.get("id"),
            "employee_id": row_dict.get("employee_id"),
            "name": row_dict.get("name") or row_dict.get("employee_id"),
            "client_id": row_dict.get("client_id"),
            "filename": row_dict.get("filename"),
            "thumbnail": row_dict.get("thumbnail"),
            "file_size": row_dict.get("file_size"),
            "width": row_dict.get("width"),
            "height": row_dict.get("height"),
            "storage_url": row_dict.get("storage_url"),
            "uploaded_at": row_dict.get("uploaded_at"),
            "screenshot_time": row_dict.get("screenshot_time"),
            "computer_name": row_dict.get("computer_name"),
            "windows_user": row_dict.get("windows_user"),
            "image_format": row_dict.get("image_format"),
            "is_encrypted": row_dict.get("is_encrypted"),
            "url": row_dict.get("storage_url"),
            "time": (
                row_dict.get("screenshot_time").strftime("%H:%M:%S")
                if row_dict.get("screenshot_time")
                else None
            ),
            "date": (
                row_dict.get("screenshot_time").strftime("%Y-%m-%d")
                if row_dict.get("screenshot_time")
                else None
            ),
            "datetime": (
                row_dict.get("screenshot_time").strftime("%Y-%m-%d %H:%M:%S")
                if row_dict.get("screenshot_time")
                else None
            ),
            "size_str": format_size(row_dict.get("file_size")),
            "format": row_dict.get("image_format"),
            "encrypted": row_dict.get("is_encrypted"),
        }
        screenshots.append(screenshot)

    return screenshots


@app.get(
    "/api/screenshots/recent", response_model=List[schemas.Screenshot], tags=["截图"]
)
def get_recent_screenshots(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取最近的截图"""
    from sqlalchemy import text

    sql = """
        SELECT 
            s.*,
            e.name as name
        FROM screenshots s
        LEFT JOIN employees e ON s.employee_id = e.employee_id
        ORDER BY s.screenshot_time DESC
        LIMIT :limit
    """

    params = {"limit": limit}

    # 执行查询
    result = db.execute(text(sql), params).fetchall()

    # 转换为字典列表
    screenshots = []
    for row in result:
        row_dict = dict(row._mapping)

        screenshot = {
            "id": row_dict.get("id"),
            "employee_id": row_dict.get("employee_id"),
            "name": row_dict.get("name") or row_dict.get("employee_id"),
            "client_id": row_dict.get("client_id"),
            "filename": row_dict.get("filename"),
            "thumbnail": row_dict.get("thumbnail"),
            "file_size": row_dict.get("file_size"),
            "width": row_dict.get("width"),
            "height": row_dict.get("height"),
            "storage_url": row_dict.get("storage_url"),
            "uploaded_at": row_dict.get("uploaded_at"),
            "screenshot_time": row_dict.get("screenshot_time"),
            "computer_name": row_dict.get("computer_name"),
            "windows_user": row_dict.get("windows_user"),
            "image_format": row_dict.get("image_format"),
            "is_encrypted": row_dict.get("is_encrypted"),
            "url": row_dict.get("storage_url"),
            "time": (
                row_dict.get("screenshot_time").strftime("%H:%M:%S")
                if row_dict.get("screenshot_time")
                else None
            ),
            "date": (
                row_dict.get("screenshot_time").strftime("%Y-%m-%d")
                if row_dict.get("screenshot_time")
                else None
            ),
            "datetime": (
                row_dict.get("screenshot_time").strftime("%Y-%m-%d %H:%M:%S")
                if row_dict.get("screenshot_time")
                else None
            ),
            "size_str": format_size(row_dict.get("file_size")),
            "format": row_dict.get("image_format"),
            "encrypted": row_dict.get("is_encrypted"),
        }
        screenshots.append(screenshot)

    return screenshots


# ===== 辅助函数：格式化文件大小 =====
def format_size(size):
    """格式化文件大小"""
    if not size:
        return "0 B"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size/1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size/(1024*1024):.1f} MB"
    return f"{size/(1024*1024*1024):.1f} GB"


# ==================== 客户端管理接口 ====================


@app.get("/api/clients", tags=["客户端"])
def get_clients(
    skip: int = 0,
    limit: int = 100,
    online_only: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取客户端列表"""
    query = db.query(models.Client)

    if online_only:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        query = query.filter(models.Client.last_seen >= cutoff)

    clients = (
        query.order_by(models.Client.last_seen.desc()).offset(skip).limit(limit).all()
    )

    return clients


@app.get("/api/clients/online", tags=["客户端"])
def get_online_clients(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取在线客户端"""
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    clients = db.query(models.Client).filter(models.Client.last_seen >= cutoff).all()

    return [
        {
            "client_id": c.client_id,
            "employee_id": c.employee_id,
            "computer_name": c.computer_name,
            "ip_address": c.ip_address,
            "last_seen": c.last_seen.isoformat(),
            "client_version": c.client_version,
        }
        for c in clients
    ]


@app.delete("/api/clients/{client_id}", tags=["客户端"])
def delete_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """删除客户端"""
    client = (
        db.query(models.Client).filter(models.Client.client_id == client_id).first()
    )

    if not client:
        raise HTTPException(status_code=404, detail="客户端不存在")

    db.delete(client)
    db.commit()

    logger.info(f"客户端删除: {client_id}")
    return {"message": "客户端已删除"}


# ==================== 统计接口 ====================
@app.get("/api/stats", tags=["统计"])
def get_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取系统统计信息"""
    from datetime import datetime, timedelta
    from server_timezone import get_beijing_now, get_date_range_for_day

    # ===== 使用工具函数获取北京时间 =====
    beijing_now = get_beijing_now()
    today = beijing_now.date()
    week_ago = beijing_now - timedelta(days=7)

    # ===== 使用工具函数获取日期范围 =====
    today_start, today_end = get_date_range_for_day(beijing_now)

    # 昨日
    yesterday = today - timedelta(days=1)
    yesterday_start, yesterday_end = get_date_range_for_day(yesterday)
    # ====================================

    # 今日截图
    today_count = (
        db.query(models.Screenshot)
        .filter(
            models.Screenshot.screenshot_time >= today_start,
            models.Screenshot.screenshot_time < today_end,
        )
        .count()
    )

    # 昨日截图
    yesterday_count = (
        db.query(models.Screenshot)
        .filter(
            models.Screenshot.screenshot_time >= yesterday_start,
            models.Screenshot.screenshot_time < yesterday_end,
        )
        .count()
    )

    # 本周截图（过去7天）
    week_count = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.screenshot_time >= week_ago)
        .count()
    )

    # 在线客户端 - 判断最后在线时间是否在最近10分钟内
    cutoff = beijing_now - timedelta(minutes=10)
    online_clients = (
        db.query(models.Client).filter(models.Client.last_seen >= cutoff).count()
    )

    # 总数（这些不受时间影响）
    total_screenshots = db.query(models.Screenshot).count()
    total_employees = db.query(models.Employee).count()
    total_clients = db.query(models.Client).count()

    # 存储大小
    total_size = db.query(func.sum(models.Screenshot.file_size)).scalar() or 0

    # 各格式统计
    webp_count = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.image_format == "webp")
        .count()
    )
    jpg_count = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.image_format == "jpg")
        .count()
    )

    # 每小时活动（使用北京时间）
    hourly = []
    for i in range(24):
        start = beijing_now.replace(hour=i, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        count = (
            db.query(models.Screenshot)
            .filter(
                models.Screenshot.screenshot_time >= start,
                models.Screenshot.screenshot_time < end,
            )
            .count()
        )
        hourly.append(count)

    # 最近活动
    recent_activities = (
        db.query(models.Activity)
        .order_by(models.Activity.created_at.desc())
        .limit(10)
        .all()
    )

    # 各员工截图统计（使用北京时间）
    top_employees = []
    employees = db.query(models.Employee).limit(5).all()
    for emp in employees:
        today_emp = (
            db.query(models.Screenshot)
            .filter(
                models.Screenshot.employee_id == emp.employee_id,
                models.Screenshot.screenshot_time >= today_start,
                models.Screenshot.screenshot_time < today_end,
            )
            .count()
        )

        total_emp = (
            db.query(models.Screenshot)
            .filter(models.Screenshot.employee_id == emp.employee_id)
            .count()
        )

        top_employees.append(
            {
                "id": emp.employee_id,
                "name": emp.name,
                "today": today_emp,
                "total": total_emp,
            }
        )

    return {
        "today": today_count,
        "yesterday": yesterday_count,
        "week": week_count,
        "total": total_screenshots,
        "employees": total_employees,
        "clients": total_clients,
        "online": online_clients,
        "storage_mb": round(total_size / (1024 * 1024), 2),
        "image_formats": {
            "webp": webp_count,
            "jpg": jpg_count,
            "other": total_screenshots - webp_count - jpg_count,
        },
        "hourly": hourly,
        "recent_activities": [
            {
                "employee_id": a.employee_id,
                "action": a.action,
                "time": (
                    a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else None
                ),
            }
            for a in recent_activities
        ],
        "top_employees": top_employees,
        "auto_cleanup": {
            "enabled": Config.AUTO_CLEANUP_ENABLED,
            "interval_hours": Config.CLEANUP_INTERVAL / 3600,
            "retention_hours": Config.SCREENSHOT_RETENTION_HOURS,
        },
    }


@app.get("/api/activities", tags=["统计"])
def get_activities(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取活动日志"""
    activities = (
        db.query(models.Activity)
        .order_by(models.Activity.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "employee_id": a.employee_id,
            "action": a.action,
            "time": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for a in activities
    ]


# ==================== 清理接口 ====================


@app.post("/api/cleanup", tags=["系统"])
def manual_cleanup(
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_active_user),
):
    """手动清理旧截图"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    background_tasks.add_task(cleanup.cleanup_old_data_once)

    return {
        "message": "清理任务已启动",
        "retention_hours": Config.SCREENSHOT_RETENTION_HOURS,
    }


@app.get("/api/cleanup/status", tags=["系统"])
def get_cleanup_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取清理状态"""
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=Config.SCREENSHOT_RETENTION_HOURS)

    # 待清理的截图数量
    pending_count = (
        db.query(models.Screenshot)
        .filter(models.Screenshot.screenshot_time < cutoff)
        .count()
    )

    # 待清理的总大小
    pending_size = (
        db.query(func.sum(models.Screenshot.file_size))
        .filter(models.Screenshot.screenshot_time < cutoff)
        .scalar()
        or 0
    )

    # 上次清理时间
    last_cleanup = (
        db.query(models.Activity)
        .filter(models.Activity.action == "auto_cleanup")
        .order_by(models.Activity.created_at.desc())
        .first()
    )

    return {
        "enabled": Config.AUTO_CLEANUP_ENABLED,
        "retention_hours": Config.SCREENSHOT_RETENTION_HOURS,
        "interval_hours": Config.CLEANUP_INTERVAL / 3600,
        "pending_cleanup": pending_count,
        "pending_size_mb": round(pending_size / (1024 * 1024), 2),
        "last_cleanup": last_cleanup.created_at.isoformat() if last_cleanup else None,
    }


# ==================== 文件服务 ====================


@app.get("/screenshots/{path:path}", tags=["文件"])
async def serve_screenshot(path: str):
    """提供截图文件（公开访问）"""

    if not path or path.strip() == "":
        raise HTTPException(status_code=404, detail="File not specified")

    try:
        # 统一路径分隔符
        path = path.replace("\\", "/")

        # 主存储路径
        base_path = STORAGE_PATH.resolve()
        file_path = (base_path / path).resolve()

        # 防止路径逃逸
        if not str(file_path).startswith(str(base_path)):
            logger.warning(f"路径逃逸尝试: {path}")
            raise HTTPException(status_code=404, detail="Invalid path")

        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        # 备用路径（兼容旧数据）
        backup_base = Path("/data/screenshots").resolve()
        backup_file = (backup_base / path).resolve()

        if str(backup_file).startswith(str(backup_base)) and backup_file.exists():
            logger.info(f"使用备用路径找到文件: {backup_file}")
            return FileResponse(backup_file)

        logger.warning(f"文件不存在: {path}")
        raise HTTPException(status_code=404, detail="File not found")

    except HTTPException:
        raise  # 直接抛出HTTP异常
    except Exception as e:
        logger.error(f"文件访问错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error")


# ==================== 工具函数 ====================


def log_activity(employee_id: str, action: str, details: dict = None):
    """记录活动日志"""
    try:
        db = next(get_db())
        activity = models.Activity(
            employee_id=employee_id, action=action, details=details
        )
        db.add(activity)
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"记录活动失败: {e}")


def create_thumbnail(image_path: str, thumbnail_path: str):
    """创建缩略图"""
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            img.thumbnail((320, 240), Image.Resampling.LANCZOS)
            img.save(thumbnail_path, "WEBP", quality=75, optimize=True)
            logger.debug(f"缩略图创建成功: {thumbnail_path}")
    except Exception as e:
        logger.error(f"创建缩略图失败: {e}")


def process_batch_upload(
    zip_path: str, client_id: str, employee_id: str, expected_count: int
):
    """处理批量上传的ZIP文件"""
    import zipfile
    from server_timezone import get_beijing_now  # 添加导入

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # ===== 修改点：解压到以北京时间命名的临时目录 =====
            extract_path = (
                STORAGE_PATH
                / "temp"
                / f"extract_{get_beijing_now().strftime('%Y%m%d_%H%M%S')}"
                # 原来是：datetime.now().strftime('%Y%m%d_%H%M%S')
            )
            # ==============================================
            extract_path.mkdir(parents=True, exist_ok=True)
            zip_ref.extractall(extract_path)

            # 处理每个文件
            count = 0
            for file_path in extract_path.glob("*"):
                if file_path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                    # TODO: 处理每个截图
                    count += 1

            logger.info(f"批量处理完成: {count}/{expected_count} 个文件")

            # 清理
            import shutil

            shutil.rmtree(extract_path)

        # 删除ZIP文件
        Path(zip_path).unlink()

    except Exception as e:
        logger.error(f"批量处理失败: {e}")


class ChangePasswordSchema(BaseModel):
    current_password: str
    new_password: str


class RegenerateApiKeySchema(BaseModel):
    pass  # 不需要参数


@app.post("/api/auth/change-password", tags=["认证"])
def change_password(
    password_data: ChangePasswordSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """修改当前用户密码"""
    # 验证当前密码
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误"
        )

    # 验证新密码长度
    if len(password_data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少需要6个字符"
        )

    # 更新密码
    current_user.password_hash = get_password_hash(password_data.new_password)
    db.commit()

    logger.info(f"用户密码已修改: {current_user.username}")

    return {"message": "密码修改成功"}


@app.post("/api/auth/regenerate-api-key", tags=["认证"])
def regenerate_api_key(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin_user),
):
    """重新生成API密钥"""
    import secrets

    # 生成新的API密钥
    new_api_key = f"sk-" + secrets.token_urlsafe(32)

    # 这里需要根据你的实际存储方式保存API密钥
    # 例如保存到数据库的 SystemConfig 表
    from server_config_manager import set_config

    set_config(
        key="api_key",
        value=new_api_key,
        category="security",
        description="API密钥",
        user_id=current_user.id,
    )

    logger.info(f"API密钥已重新生成: {current_user.username}")

    return {"api_key": new_api_key}


# ==================== 静态文件服务 ====================

# 1. 先挂载截图目录（必须放在前面）
screenshots_path = Path("/data/screenshots")
if screenshots_path.exists():
    app.mount(
        "/screenshots", StaticFiles(directory="/data/screenshots"), name="screenshots"
    )
    logger.info(f"✅ 截图目录已挂载: /data/screenshots")

    # 列出一些文件用于调试
    try:
        files = list(screenshots_path.glob("**/*.webp"))[:5]
        if files:
            logger.info(
                f"📸 找到示例截图: {[str(f.relative_to(screenshots_path)) for f in files]}"
            )
    except Exception as e:
        logger.error(f"❌ 读取截图目录失败: {e}")
else:
    logger.warning(f"⚠️ 截图目录不存在: /data/screenshots")

# 2. 定义前端文件目录
static_dir = Path(".")
index_path = static_dir / "index.html"

if index_path.exists():
    logger.info(f"✅ 找到 index.html，前端页面可访问")
else:
    logger.warning(f"⚠️ index.html 不存在于根目录")

# 3. 挂载静态资源目录（js, css, 图片等）- 可选
# 如果你有专门的静态资源目录，可以这样挂载
assets_dir = static_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")
    logger.info(f"✅ 静态资源目录已挂载: /assets")


# 4. 处理所有前端路由（关键修复）
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """
    处理所有前端路由：
    - 如果是API请求，返回404（应该已经被前面的路由捕获）
    - 如果是静态资源文件，直接返回
    - 其他所有路径都返回 index.html
    """

    # 跳过API路径
    if full_path.startswith("api/") or full_path == "api":
        return {"error": "API endpoint not found"}, 404

    # 检查是否是静态资源文件（有扩展名的）
    static_extensions = [
        ".js",
        ".css",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
    ]

    if any(full_path.endswith(ext) for ext in static_extensions):
        file_path = static_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

    # 其他所有路径都返回 index.html
    if index_path.exists():
        return FileResponse(index_path)

    return {"error": "Frontend not found"}, 404


# 5. 根路径处理
@app.get("/")
async def serve_root():
    """访问根路径返回 index.html"""
    if index_path.exists():
        return FileResponse(index_path)
    return {"error": "Frontend not found"}, 404


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server_main:app", host="0.0.0.0", port=8000, reload=Config.DEBUG)
