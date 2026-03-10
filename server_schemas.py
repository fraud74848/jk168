"""
Pydantic数据验证模型
"""

from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List, Dict, Any


# ==================== 用户相关 ====================


class UserBase(BaseModel):
    username: str
    role: str = "user"


class UserCreate(UserBase):
    password: str

    @validator("password")
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError("密码至少6个字符")
        return v


class User(UserBase):
    id: int
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


# ==================== 员工相关 ====================


class EmployeeBase(BaseModel):
    employee_id: str
    name: str
    computer_name: Optional[str] = None
    windows_user: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: str = "active"


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    computer_name: Optional[str] = None
    windows_user: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


class Employee(EmployeeBase):
    total_screenshots: Optional[int] = 0
    today_screenshots: Optional[int] = 0
    online_clients: Optional[int] = 0
    last_active: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== 客户端相关 ====================


class ClientBase(BaseModel):
    client_id: Optional[str] = None
    computer_name: Optional[str] = None
    windows_user: Optional[str] = None
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    os_version: Optional[str] = None
    cpu_id: Optional[str] = None
    disk_serial: Optional[str] = None
    client_version: Optional[str] = None


class ClientCreate(ClientBase):
    interval: Optional[int] = None
    quality: Optional[int] = None
    format: Optional[str] = None
    capabilities: Optional[List[str]] = []


class Client(ClientBase):
    employee_id: Optional[str] = None
    last_seen: Optional[datetime] = None
    is_online: Optional[bool] = False
    config: Optional[Dict[str, Any]] = None
    capabilities: List[str] = []
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Heartbeat(BaseModel):
    status: str = "online"
    stats: Optional[Dict[str, Any]] = None
    client_stats: Optional[Dict[str, Any]] = None
    paused: bool = False
    ip_address: Optional[str] = None
    timestamp: Optional[datetime] = None


# ==================== 截图相关 ====================


class ScreenshotBase(BaseModel):
    employee_id: str
    client_id: Optional[str] = None
    computer_name: Optional[str] = None
    windows_user: Optional[str] = None
    filename: str
    file_size: int = 0
    width: int = 0
    height: int = 0
    image_format: str = "webp"
    is_encrypted: bool = False


class ScreenshotCreate(ScreenshotBase):
    screenshot_time: Optional[datetime] = None


# server_schemas.py


class Screenshot(ScreenshotBase):
    id: int
    thumbnail: Optional[str] = None
    storage_url: Optional[str] = None
    uploaded_at: datetime
    screenshot_time: datetime
    url: Optional[str] = None
    time: Optional[str] = None
    date: Optional[str] = None
    datetime: Optional[str] = None
    size_str: Optional[str] = None
    format: Optional[str] = None
    encrypted: Optional[bool] = None
    employee_name: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== 统计相关 ====================


class Stats(BaseModel):
    today: int
    yesterday: int
    week: int
    total: int
    employees: int
    clients: int
    online: int
    storage_mb: float
    image_formats: Dict[str, int]
    hourly: List[int]
    recent_activities: List[Dict[str, str]]
    top_employees: List[Dict[str, Any]]
    auto_cleanup: Dict[str, Any]


class Activity(BaseModel):
    id: int
    employee_id: Optional[str] = None
    action: str
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 清理相关 ====================


class CleanupStatus(BaseModel):
    enabled: bool
    retention_hours: int
    interval_hours: float
    pending_cleanup: int
    pending_size_mb: float
    last_cleanup: Optional[str] = None
