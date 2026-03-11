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
from sqlalchemy import func, and_

import server_models as models
import server_schemas as schemas
from server_database import engine, get_db, get_backup_db
from server_auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_active_user,
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
THUMBNAIL_PATH = STORAGE_PATH / "thumbnails"
THUMBNAIL_PATH.mkdir(parents=True, exist_ok=True)

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
        if hasattr(client_info, "employee_name") and client_info.employee_name:
            employee_name = client_info.employee_name
        else:
            employee_name = (
                f"{client_info.computer_name} - {client_info.windows_user}"
                if client_info.windows_user
                else client_info.computer_name
            )

        employee = models.Employee(
            employee_id=employee_id,
            name=employee_name,  # 使用用户输入的姓名
            computer_name=client_info.computer_name,
            windows_user=client_info.windows_user,
            department="自动注册",
            status="active",
        )
        db.add(employee)
        logger.info(f"自动创建员工: {employee_id} 姓名: {employee_name}")

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
    """上传截图"""
    # 验证文件类型
    allowed_extensions = {"jpg", "jpeg", "png", "webp", "bmp"}
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file_ext}")

    from server_timezone import get_beijing_now
    from datetime import datetime

    # ===== 获取北京时间 =====
    beijing_now = get_beijing_now()
    # ======================

    # 解析时间
    try:
        if timestamp:
            screenshot_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        else:
            screenshot_time = beijing_now  # 使用北京时间
    except:
        screenshot_time = beijing_now  # 使用北京时间

    # 查找或创建员工
    employee = (
        db.query(models.Employee)
        .filter(models.Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        # 自动创建员工
        employee = models.Employee(
            employee_id=employee_id,
            name=f"{computer_name} - {windows_user}" if windows_user else computer_name,
            computer_name=computer_name,
            windows_user=windows_user,
            department="自动注册",
            status="active",
        )
        db.add(employee)
        logger.info(f"自动创建员工: {employee_id}")

    # ===== 修改点：更新客户端时也使用北京时间 =====
    # 更新客户端
    if client_id:
        client = (
            db.query(models.Client).filter(models.Client.client_id == client_id).first()
        )
        if client:
            client.last_seen = beijing_now  # 原来是 datetime.utcnow()
            if not client.employee_id:
                client.employee_id = employee_id
    # ============================================

    # 保存文件
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

    # 创建缩略图（异步）
    thumbnail_path = (
        THUMBNAIL_PATH
        / f"{safe_employee_id}/{date_str}/{screenshot_time.strftime('%H-%M-%S')}.webp"
    )
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

    background_tasks.add_task(create_thumbnail, str(file_path), str(thumbnail_path))

    # 获取图片尺寸
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            width, height = img.size
    except:
        width = height = 0

    # 保存记录
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

    logger.info(f"✅ 截图保存成功: {filename} ({file_size/1024:.1f}KB)")

    return {
        "success": True,
        "id": screenshot.id,
        "url": screenshot.storage_url,
        "thumbnail": (
            f"/screenshots/{screenshot.thumbnail}" if screenshot.thumbnail else None
        ),
        "size": file_size,
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
@app.get("/api/employees", response_model=List[schemas.Employee], tags=["员工"])
def get_employees(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    online_only: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    获取员工列表（支持分页、搜索和状态筛选）

    - skip: 跳过的记录数
    - limit: 返回的最大记录数
    - status: 状态筛选 (active/inactive)
    - online_only: 是否只返回在线员工
    - search: 搜索关键词（姓名、ID、部门）
    """
    from datetime import datetime, timedelta
    from sqlalchemy import or_

    # 构建基础查询
    query = db.query(models.Employee)

    # 状态筛选
    if status:
        query = query.filter(models.Employee.status == status)

    # 搜索筛选
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

    # 获取所有符合条件的员工（用于在线筛选）
    all_employees = query.all()

    # 在线/离线筛选
    if online_only is not None:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        filtered_employees = []

        for emp in all_employees:
            # 检查员工是否有在线客户端
            has_online = any(
                client.last_seen
                and (
                    client.last_seen.replace(tzinfo=None)
                    if client.last_seen.tzinfo
                    else client.last_seen
                )
                >= cutoff
                for client in emp.clients
            )

            if online_only and has_online:
                filtered_employees.append(emp)
            elif not online_only and not has_online:
                filtered_employees.append(emp)

        employees = filtered_employees
    else:
        employees = all_employees

    # 应用分页
    paginated_employees = (
        employees[skip : skip + limit] if skip < len(employees) else []
    )

    # 转换为字典并添加统计信息
    result = []
    for emp in paginated_employees:
        emp_dict = emp.to_dict()
        result.append(emp_dict)

    # 设置响应头，返回总数（如果需要）
    # 注意：这不会改变返回格式，但前端可以通过响应头获取总数
    from fastapi.responses import JSONResponse

    response = JSONResponse(content=result)
    response.headers["X-Total-Count"] = str(len(employees))

    return response


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
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """获取截图列表（支持分页）"""
    from sqlalchemy import text, func

    # 先获取总数
    count_sql = """
        SELECT COUNT(*) as total
        FROM screenshots s
        WHERE 1=1
    """
    count_params = {}

    if employee_id:
        count_sql += " AND s.employee_id = :employee_id"
        count_params["employee_id"] = employee_id
    if client_id:
        count_sql += " AND s.client_id = :client_id"
        count_params["client_id"] = client_id
    if start_date:
        count_sql += " AND s.screenshot_time >= :start_date"
        count_params["start_date"] = start_date
    if end_date:
        count_sql += " AND s.screenshot_time <= :end_date"
        count_params["end_date"] = end_date

    total_result = db.execute(text(count_sql), count_params).first()
    total = total_result[0] if total_result else 0

    # 使用原生SQL查询，直接连表获取员工姓名
    sql = """
        SELECT 
            s.*,
            e.name as name
        FROM screenshots s
        LEFT JOIN employees e ON s.employee_id = e.employee_id
        WHERE 1=1
    """
    params = {}

    if employee_id:
        sql += " AND s.employee_id = :employee_id"
        params["employee_id"] = employee_id

    if client_id:
        sql += " AND s.client_id = :client_id"
        params["client_id"] = client_id

    if start_date:
        sql += " AND s.screenshot_time >= :start_date"
        params["start_date"] = start_date

    if end_date:
        sql += " AND s.screenshot_time <= :end_date"
        params["end_date"] = end_date

    sql += " ORDER BY s.screenshot_time DESC"
    sql += " OFFSET :skip LIMIT :limit"
    params["skip"] = skip
    params["limit"] = limit

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

    # 返回带总数的对象
    response = JSONResponse(
        content={"items": screenshots, "total": total, "skip": skip, "limit": limit}
    )
    return response


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
    return f"{size/(1024*1024):.1f} MB"


# ==================== 客户端管理接口 ====================


@app.get("/api/clients", response_model=List[schemas.Client], tags=["客户端"])
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


# ==================== 静态文件服务 ====================
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.responses import FileResponse
import os

# 1. 挂载根目录（提供前端页面）
index_path = Path("index.html")
if index_path.exists():
    app.mount("/", StaticFiles(directory=".", html=True), name="static")
    logger.info(f"✅ 前端静态文件已挂载")
else:
    logger.warning(f"⚠️ index.html 不存在于根目录")

# 2. 挂载截图目录（提供图片文件）
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server_main:app", host="0.0.0.0", port=8000, reload=Config.DEBUG)
