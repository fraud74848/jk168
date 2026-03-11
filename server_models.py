"""
数据库模型定义
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    JSON,
    BigInteger,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from server_database import Base
from datetime import datetime, timedelta
from server_config import Config


class User(Base):
    """用户表（管理员）"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # admin, user
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
        }


class Employee(Base):
    """员工表"""

    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    computer_name = Column(String(100))
    windows_user = Column(String(100))
    department = Column(String(50))
    position = Column(String(50))
    email = Column(String(100))
    phone = Column(String(20))
    status = Column(String(20), default="active")  # active, inactive, deleted
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关联
    screenshots = relationship(
        "Screenshot", back_populates="employee", cascade="all, delete-orphan"
    )
    clients = relationship(
        "Client", back_populates="employee", cascade="all, delete-orphan"
    )
    activities = relationship(
        "Activity", back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def total_screenshots(self):
        return len(self.screenshots)

    @property
    def today_screenshots(self):
        today = datetime.utcnow().date()
        return sum(1 for s in self.screenshots if s.screenshot_time.date() == today)

    @property
    def last_active(self):
        if self.screenshots:
            return max(s.screenshot_time for s in self.screenshots)
        return None

    @property
    def online_clients(self):
        now = datetime.utcnow()
        count = 0
        for c in self.clients:
            if c.last_seen:
                # 确保 last_seen 是 naive
                if c.last_seen.tzinfo is not None:
                    last_seen = c.last_seen.replace(tzinfo=None)
                else:
                    last_seen = c.last_seen
                if (now - last_seen) < timedelta(minutes=10):
                    count += 1
        return count

    def to_dict(self):
        return {
            "id": self.employee_id,
            "name": self.name,
            "computer_name": self.computer_name,
            "windows_user": self.windows_user,
            "department": self.department,
            "position": self.position,
            "email": self.email,
            "phone": self.phone,
            "status": self.status,
            "total_screenshots": self.total_screenshots,
            "today_screenshots": self.today_screenshots,
            "online_clients": self.online_clients,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Client(Base):
    """客户端表"""

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(64), unique=True, nullable=False, index=True)
    employee_id = Column(
        String(100), ForeignKey("employees.employee_id", ondelete="SET NULL")
    )
    computer_name = Column(String(100))
    windows_user = Column(String(100))
    mac_address = Column(String(17))
    ip_address = Column(String(45))
    os_version = Column(String(100))
    cpu_id = Column(String(100))
    disk_serial = Column(String(100))
    client_version = Column(String(20))
    last_seen = Column(DateTime(timezone=True), default=func.now(), index=True)
    last_stats = Column(JSON, nullable=True)

    # ===== 修改这里：使用 lambda 函数从 Config 读取配置 =====

    config = Column(
        JSON,
        default=lambda: {
            "interval": Config.SCREENSHOT_INTERVAL,
            "quality": Config.SCREENSHOT_QUALITY,
            "format": Config.SCREENSHOT_FORMAT,
            "enable_heartbeat": True,
            "enable_batch_upload": True,
        },
    )
    # ====================================================

    capabilities = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关联
    employee = relationship("Employee", back_populates="clients")
    screenshots = relationship("Screenshot", back_populates="client")

    @property
    def is_online(self):
        if not self.last_seen:
            return False
        # 确保两个时间都是 naive（无时区）
        now = datetime.utcnow()
        if self.last_seen.tzinfo is not None:
            # 如果 last_seen 有时区，转换为 naive
            last_seen = self.last_seen.replace(tzinfo=None)
        else:
            last_seen = self.last_seen
        return (now - last_seen) < timedelta(minutes=10)

    def to_dict(self):
        return {
            "client_id": self.client_id,
            "employee_id": self.employee_id,
            "computer_name": self.computer_name,
            "windows_user": self.windows_user,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "os_version": self.os_version,
            "client_version": self.client_version,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_online": self.is_online,
            "config": self.config,
            "capabilities": self.capabilities,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Screenshot(Base):
    """截图表"""

    __tablename__ = "screenshots"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        String(100),
        ForeignKey("employees.employee_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id = Column(
        String(64), ForeignKey("clients.client_id", ondelete="SET NULL"), nullable=True
    )
    filename = Column(String(255), nullable=False)
    thumbnail = Column(String(255), nullable=True)
    file_size = Column(BigInteger, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    storage_url = Column(String(500))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    screenshot_time = Column(DateTime(timezone=True), nullable=False, index=True)
    computer_name = Column(String(100))
    windows_user = Column(String(100))
    image_format = Column(String(10), default="webp")
    is_encrypted = Column(Boolean, default=False)

    # 关联
    employee = relationship("Employee", back_populates="screenshots")
    client = relationship("Client", back_populates="screenshots")

    @property
    def age_hours(self):
        if self.screenshot_time:
            now = datetime.utcnow()
            # 确保两个时间都是 naive（无时区）
            if self.screenshot_time.tzinfo is not None:
                shot_time = self.screenshot_time.replace(tzinfo=None)
            else:
                shot_time = self.screenshot_time
            delta = now - shot_time
            return delta.total_seconds() / 3600
        return 0

    def to_dict(self):
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "client_id": self.client_id,
            "filename": self.filename.split("/")[-1],
            "thumbnail": f"/screenshots/{self.thumbnail}" if self.thumbnail else None,
            "url": self.storage_url,
            "size": self.file_size,
            "size_str": self._format_size(self.file_size),
            "width": self.width,
            "height": self.height,
            "time": self.screenshot_time.strftime("%H:%M:%S"),
            "date": self.screenshot_time.strftime("%Y-%m-%d"),
            "datetime": self.screenshot_time.strftime("%Y-%m-%d %H:%M:%S"),
            "computer_name": self.computer_name,
            "windows_user": self.windows_user,
            "format": self.image_format,
            "encrypted": self.is_encrypted,
            "age_hours": round(self.age_hours, 1),
        }

    @staticmethod
    def _format_size(size):
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"


class Activity(Base):
    """活动日志表"""

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        String(100),
        ForeignKey("employees.employee_id", ondelete="SET NULL"),
        index=True,
    )
    action = Column(String(50), nullable=False)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 关联
    employee = relationship("Employee", back_populates="activities")

    def to_dict(self):
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "action": self.action,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# 系统设置表
class SystemConfig(Base):
    """系统配置表 - 存储所有动态配置"""

    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    description = Column(String(200))
    category = Column(
        String(50), index=True
    )  # general, cleanup, storage, security, notification
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value,
            "description": self.description,
            "category": self.category,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
