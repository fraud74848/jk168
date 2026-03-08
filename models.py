from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    computer_name = db.Column(db.String(100))
    windows_user = db.Column(db.String(100))
    department = db.Column(db.String(50))
    position = db.Column(db.String(50))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关联
    screenshots = db.relationship('Screenshot', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    clients = db.relationship('Client', backref='employee', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def display_name(self):
        """显示名称：姓名 (计算机名\用户名)"""
        if self.computer_name and self.windows_user:
            return f"{self.name} ({self.computer_name}\\{self.windows_user})"
        return self.name
    
    @property
    def total_screenshots(self):
        return self.screenshots.count()
    
    @property
    def today_screenshots(self):
        today = datetime.utcnow().date()
        return self.screenshots.filter(
            db.func.date(Screenshot.screenshot_time) == today
        ).count()
    
    @property
    def last_active(self):
        last = self.screenshots.order_by(Screenshot.screenshot_time.desc()).first()
        return last.screenshot_time if last else None
    
    @property
    def online_clients(self):
        """获取在线客户端"""
        now = datetime.utcnow()
        return self.clients.filter(
            Client.last_seen >= now - timedelta(minutes=10)
        ).count()
    
    def to_dict(self):
        return {
            'id': self.employee_id,
            'name': self.name,
            'display_name': self.display_name,
            'computer_name': self.computer_name,
            'windows_user': self.windows_user,
            'department': self.department,
            'position': self.position,
            'email': self.email,
            'phone': self.phone,
            'status': self.status,
            'total_screenshots': self.total_screenshots,
            'today_screenshots': self.today_screenshots,
            'online_clients': self.online_clients,
            'last_active': self.last_active.isoformat() if self.last_active else None
        }

class Client(db.Model):
    __tablename__ = 'clients'
    
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    employee_id = db.Column(db.String(100), db.ForeignKey('employees.employee_id', ondelete='SET NULL'))
    computer_name = db.Column(db.String(100))
    windows_user = db.Column(db.String(100))
    mac_address = db.Column(db.String(17))
    ip_address = db.Column(db.String(45))
    os_version = db.Column(db.String(100))
    cpu_id = db.Column(db.String(100))
    disk_serial = db.Column(db.String(100))
    client_version = db.Column(db.String(20))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    last_stats = db.Column(db.JSON)
    config = db.Column(db.JSON, default={
        'interval': 300,
        'quality': 70,
        'format': 'webp',
        'enable_heartbeat': True,
        'enable_batch_upload': True
    })
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def is_online(self):
        if not self.last_seen:
            return False
        return datetime.utcnow() - self.last_seen < timedelta(minutes=10)
    
    @property
    def employee_name(self):
        if self.employee_id:
            emp = Employee.query.filter_by(employee_id=self.employee_id).first()
            return emp.name if emp else None
        return None
    
    def to_dict(self):
        return {
            'client_id': self.client_id,
            'employee_id': self.employee_id,
            'employee_name': self.employee_name,
            'computer_name': self.computer_name,
            'windows_user': self.windows_user,
            'ip_address': self.ip_address,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'is_online': self.is_online,
            'os_version': self.os_version,
            'config': self.config
        }

class Screenshot(db.Model):
    __tablename__ = 'screenshots'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(100), db.ForeignKey('employees.employee_id', ondelete='CASCADE'), nullable=False)
    client_id = db.Column(db.String(64), db.ForeignKey('clients.client_id', ondelete='SET NULL'))
    computer_name = db.Column(db.String(100))
    windows_user = db.Column(db.String(100))
    filename = db.Column(db.String(255), nullable=False)
    thumbnail = db.Column(db.String(255))
    file_size = db.Column(db.Integer)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    storage_url = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    screenshot_time = db.Column(db.DateTime, nullable=False, index=True)
    image_format = db.Column(db.String(10), default='webp')  # webp, jpg, png
    is_encrypted = db.Column(db.Boolean, default=False)
    
    @property
    def employee_name(self):
        """获取员工姓名"""
        if self.employee_id:
            emp = Employee.query.filter_by(employee_id=self.employee_id).first()
            return emp.name if emp else self.employee_id
        return self.employee_id
    
    @property
    def age_hours(self):
        """获取截图存在的小时数"""
        if self.screenshot_time:
            delta = datetime.utcnow() - self.screenshot_time
            return delta.total_seconds() / 3600
        return 0
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee_name,
            'computer_name': self.computer_name,
            'windows_user': self.windows_user,
            'filename': self.filename.split('/')[-1],
            'time': self.screenshot_time.strftime('%H:%M:%S'),
            'date': self.screenshot_time.strftime('%Y-%m-%d'),
            'datetime': self.screenshot_time.strftime('%Y-%m-%d %H:%M:%S'),
            'url': self.storage_url,
            'thumbnail': f"/screenshots/{self.thumbnail}" if self.thumbnail else None,
            'size': self.file_size,
            'size_str': self._format_size(self.file_size),
            'format': self.image_format,
            'encrypted': self.is_encrypted,
            'age_hours': round(self.age_hours, 1)
        }
    
    @staticmethod
    def _format_size(size):
        for unit in ['B', 'KB', 'MB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"

class Activity(db.Model):
    __tablename__ = 'activities'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(100), db.ForeignKey('employees.employee_id', ondelete='SET NULL'))
    action = db.Column(db.String(50))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def to_dict(self):
        return {
            'employee_id': self.employee_id,
            'action': self.action,
            'time': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }