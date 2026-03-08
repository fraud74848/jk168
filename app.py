#!/usr/bin/env python3
"""
员工监控系统 - 完整版服务器
功能：员工管理、客户端自动注册、截图关联、自动清理
"""

import os
import uuid
import hashlib
import logging
import zipfile
import io
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, send_file, abort, session, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image
from functools import wraps

from config import Config
from models import db, User, Employee, Client, Screenshot, Activity
from auth import login_required, generate_token, verify_token

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建应用
app = Flask(__name__)
app.config.from_object(Config)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = Config.SECRET_KEY

# 初始化数据库
db.init_app(app)

# 创建表
with app.app_context():
    db.create_all()
    
    # 创建默认管理员
    if not User.query.filter_by(username=Config.ADMIN_USERNAME).first():
        admin = User(username=Config.ADMIN_USERNAME)
        admin.set_password(Config.ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        logger.info(f"默认管理员已创建: {Config.ADMIN_USERNAME}")

# 创建截图目录
os.makedirs(Config.SCREENSHOT_DIR, exist_ok=True)
os.makedirs(os.path.join(Config.SCREENSHOT_DIR, 'thumbnails'), exist_ok=True)

# ==================== 工具函数 ====================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def convert_to_webp(image_path, quality=80):
    """将图片转换为WebP格式"""
    try:
        with Image.open(image_path) as img:
            # 转换RGBA到RGB（如果需要）
            if img.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = bg
            
            webp_path = image_path.rsplit('.', 1)[0] + '.webp'
            img.save(webp_path, 'WEBP', quality=quality, optimize=True)
            
            # 删除原文件
            if webp_path != image_path and os.path.exists(image_path):
                os.remove(image_path)
            
            return webp_path
    except Exception as e:
        logger.error(f"转换WebP失败: {e}")
        return image_path

def compress_image(image_path, target_format='webp', quality=80):
    """压缩图片到指定格式"""
    try:
        with Image.open(image_path) as img:
            # 转换RGBA到RGB（如果需要）
            if img.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = bg
            
            # 生成新文件名
            base_path = image_path.rsplit('.', 1)[0]
            new_path = f"{base_path}.{target_format}"
            
            # 保存压缩后的图片
            if target_format == 'webp':
                img.save(new_path, 'WEBP', quality=quality, optimize=True, method=6)
            else:
                img.save(new_path, 'JPEG', quality=quality, optimize=True)
            
            # 获取新文件大小
            new_size = os.path.getsize(new_path)
            old_size = os.path.getsize(image_path)
            
            logger.info(f"图片压缩: {old_size/1024:.1f}KB -> {new_size/1024:.1f}KB ({target_format})")
            
            # 删除原文件
            if new_path != image_path and os.path.exists(image_path):
                os.remove(image_path)
            
            return new_path
    except Exception as e:
        logger.error(f"图片压缩失败: {e}")
        return image_path

def create_thumbnail(image_path, thumbnail_path):
    try:
        with Image.open(image_path) as img:
            img.thumbnail(Config.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            # 缩略图统一保存为WebP
            thumb_path = thumbnail_path.rsplit('.', 1)[0] + '.webp'
            img.save(thumb_path, 'WEBP', quality=Config.THUMBNAIL_QUALITY, optimize=True)
            
            # 删除原缩略图（如果不是WebP）
            if thumb_path != thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            
            return True
    except Exception as e:
        logger.error(f"创建缩略图失败: {e}")
        return False

def log_activity(employee_id, action, details=None):
    try:
        activity = Activity(
            employee_id=employee_id,
            action=action,
            details=details,
            ip_address=request.remote_addr
        )
        db.session.add(activity)
        db.session.commit()
    except Exception as e:
        logger.error(f"记录活动失败: {e}")

def login_required_web(f):
    """网页登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== 自动清理线程 ====================

class CleanupThread(threading.Thread):
    """自动清理线程"""
    
    def __init__(self, app, interval=21600):
        super().__init__()
        self.app = app
        self.interval = interval
        self.daemon = True
        self.running = True
    
    def run(self):
        with self.app.app_context():
            logger.info(f"自动清理线程启动，间隔: {self.interval/3600}小时")
            while self.running:
                try:
                    time.sleep(self.interval)
                    if self.running:
                        self.cleanup_old_screenshots()
                except Exception as e:
                    logger.error(f"清理线程异常: {e}")
    
    def stop(self):
        self.running = False
    
    def cleanup_old_screenshots(self):
        """清理旧截图"""
        try:
            hours = Config.SCREENSHOT_RETENTION_HOURS
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            
            logger.info(f"开始清理 {hours} 小时前的截图...")
            
            # 查找需要删除的截图
            old_screenshots = Screenshot.query.filter(
                Screenshot.screenshot_time < cutoff
            ).all()
            
            count = 0
            size_freed = 0
            
            for s in old_screenshots:
                # 删除原图
                filepath = os.path.join(Config.SCREENSHOT_DIR, s.filename)
                if os.path.exists(filepath):
                    size_freed += os.path.getsize(filepath)
                    os.remove(filepath)
                
                # 删除缩略图
                if s.thumbnail:
                    thumbpath = os.path.join(Config.SCREENSHOT_DIR, s.thumbnail)
                    if os.path.exists(thumbpath):
                        os.remove(thumbpath)
                
                db.session.delete(s)
                count += 1
                
                # 每100条提交一次
                if count % 100 == 0:
                    db.session.commit()
            
            db.session.commit()
            
            if count > 0:
                logger.info(f"清理完成: 删除 {count} 条记录，释放 {size_freed/1024/1024:.2f}MB 空间")
                
                # 记录清理活动
                activity = Activity(
                    employee_id='system',
                    action='auto_cleanup',
                    details={'deleted': count, 'size_freed': size_freed}
                )
                db.session.add(activity)
                db.session.commit()
            else:
                logger.info("没有需要清理的截图")
                
        except Exception as e:
            logger.error(f"自动清理失败: {e}")
            db.session.rollback()

# 启动自动清理线程
if Config.AUTO_CLEANUP_ENABLED:
    cleanup_thread = CleanupThread(app, Config.CLEANUP_INTERVAL)
    cleanup_thread.start()

# ==================== 健康检查 ====================

@app.route('/health')
def health():
    try:
        db.session.execute('SELECT 1')
        db_status = 'healthy'
    except Exception as e:
        db_status = f'unhealthy: {str(e)}'
    
    return jsonify({
        'status': 'healthy',
        'database': db_status,
        'auto_cleanup': 'enabled' if Config.AUTO_CLEANUP_ENABLED else 'disabled',
        'cleanup_interval': f"{Config.CLEANUP_INTERVAL/3600}小时",
        'retention_hours': Config.SCREENSHOT_RETENTION_HOURS,
        'image_format': Config.SCREENSHOT_FORMAT,
        'time': datetime.utcnow().isoformat()
    })

# ==================== 页面路由 ====================

@app.route('/')
def index():
    """根路径重定向到登录页"""
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    """登录页面"""
    if 'user_id' in session:
        return redirect(url_for('dashboard_page'))
    return render_template('login.html')

@app.route('/dashboard')
@login_required_web
def dashboard_page():
    """仪表盘页面"""
    return render_template('dashboard.html')

@app.route('/employees')
@login_required_web
def employees_page():
    """员工管理页面"""
    return render_template('employees.html')

@app.route('/screenshots')
@login_required_web
def screenshots_page():
    """截图查看页面"""
    return render_template('screenshots.html')

@app.route('/clients')
@login_required_web
def clients_page():
    """客户端管理页面"""
    return render_template('clients.html')

@app.route('/stats')
@login_required_web
def stats_page():
    """数据分析页面"""
    return render_template('stats.html')

# ==================== 认证接口 ====================

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return jsonify({'error': '用户名或密码错误'}), 401
        
        # 设置session
        session['user_id'] = user.id
        session['username'] = user.username
        
        token = generate_token(user.id)
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {'username': user.username, 'role': user.role}
        })
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user': session.get('username')
        })
    return jsonify({'authenticated': False}), 401

# ==================== 客户端接口 ====================

@app.route('/api/client/register', methods=['POST'])
def register_client():
    """客户端注册 - 接收详细识别信息"""
    try:
        data = request.get_json()
        
        # 提取识别信息
        computer_name = data.get('computer_name')
        mac_address = data.get('mac_address')
        windows_user = data.get('windows_user')
        client_id = data.get('client_id')
        ip_address = data.get('ip_address', request.remote_addr)
        os_version = data.get('os_version')
        cpu_id = data.get('cpu_id')
        disk_serial = data.get('disk_serial')
        
        if not computer_name or not mac_address:
            return jsonify({'error': '缺少必要参数'}), 400
        
        # 生成员工ID（组合计算机名和用户名）
        if windows_user:
            employee_id = f"{computer_name}\\{windows_user}"
            employee_name = f"{computer_name} - {windows_user}"
        else:
            employee_id = computer_name
            employee_name = computer_name
        
        # 查找或创建员工
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        if not employee:
            employee = Employee(
                employee_id=employee_id,
                name=employee_name,
                computer_name=computer_name,
                windows_user=windows_user,
                department='自动注册',
                status='active'
            )
            db.session.add(employee)
            logger.info(f"✅ 自动创建员工: {employee_id}")
        
        # 查找或创建客户端
        client = Client.query.filter_by(client_id=client_id).first()
        if not client:
            client = Client(
                client_id=client_id,
                employee_id=employee_id,
                computer_name=computer_name,
                windows_user=windows_user,
                mac_address=mac_address,
                ip_address=ip_address,
                os_version=os_version,
                cpu_id=cpu_id,
                disk_serial=disk_serial,
                last_seen=datetime.utcnow()
            )
            # 从服务器配置获取客户端配置
            client.config['format'] = Config.SCREENSHOT_FORMAT
            client.config['quality'] = Config.SCREENSHOT_QUALITY
            
            db.session.add(client)
            logger.info(f"✅ 新客户端注册: {client_id} ({computer_name}\\{windows_user})")
        else:
            client.last_seen = datetime.utcnow()
            client.ip_address = ip_address
            client.os_version = os_version
            client.employee_id = employee_id
            # 更新配置
            client.config['format'] = Config.SCREENSHOT_FORMAT
            client.config['quality'] = Config.SCREENSHOT_QUALITY
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'client_id': client_id,
            'employee_id': employee_id,
            'employee_name': employee_name,
            'computer_name': computer_name,
            'windows_user': windows_user,
            'config': {
                'interval': client.config.get('interval', 300),
                'quality': client.config.get('quality', Config.SCREENSHOT_QUALITY),
                'format': client.config.get('format', Config.SCREENSHOT_FORMAT)
            }
        })
        
    except Exception as e:
        logger.error(f"注册失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/client/<client_id>/heartbeat', methods=['POST'])
def client_heartbeat(client_id):
    """客户端心跳接口"""
    try:
        data = request.get_json()
        client = Client.query.filter_by(client_id=client_id).first()
        
        if client:
            client.last_seen = datetime.utcnow()
            
            # 更新客户端统计信息
            if 'stats' in data:
                client.last_stats = data['stats']
            
            db.session.commit()
            
            return jsonify({
                'status': 'ok',
                'config': client.config,
                'server_time': datetime.utcnow().isoformat()
            })
        
        return jsonify({'error': '客户端不存在'}), 404
    except Exception as e:
        logger.error(f"心跳处理失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/client/<client_id>/config', methods=['GET'])
def get_client_config(client_id):
    """获取客户端配置"""
    try:
        client = Client.query.filter_by(client_id=client_id).first()
        
        if client:
            return jsonify(client.config)
        
        # 返回默认配置（使用服务器配置）
        return jsonify({
            'interval': 300,
            'quality': Config.SCREENSHOT_QUALITY,
            'format': Config.SCREENSHOT_FORMAT,
            'enable_heartbeat': True,
            'enable_batch_upload': True
        })
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_screenshot():
    """上传截图 - 关联到员工"""
    try:
        file = request.files.get('image')
        employee_id = request.form.get('employee_id')
        client_id = request.form.get('client_id')
        computer_name = request.form.get('computer_name')
        windows_user = request.form.get('windows_user')
        timestamp = request.form.get('timestamp')
        encrypted = request.form.get('encrypted', 'false').lower() == 'true'
        
        if not file or not employee_id:
            return jsonify({'error': '缺少必要参数'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': '不支持的文件类型'}), 400
        
        # 解析时间
        try:
            screenshot_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        except:
            screenshot_time = datetime.utcnow()
        
        # 查找或创建员工
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        if not employee:
            # 如果员工不存在，自动创建
            employee_name = f"{computer_name} - {windows_user}" if windows_user else computer_name
            employee = Employee(
                employee_id=employee_id,
                name=employee_name,
                computer_name=computer_name,
                windows_user=windows_user,
                department='自动注册',
                status='active'
            )
            db.session.add(employee)
            logger.info(f"自动创建员工: {employee_id}")
        
        # 更新客户端
        if client_id:
            client = Client.query.filter_by(client_id=client_id).first()
            if client:
                client.last_seen = datetime.utcnow()
                if not client.employee_id:
                    client.employee_id = employee_id
        
        # 保存文件
        date_str = screenshot_time.strftime('%Y-%m-%d')
        time_str = screenshot_time.strftime('%H-%M-%S')
        
        # 文件名格式：员工ID_计算机名_用户名_时间
        safe_employee_id = employee_id.replace('\\', '_').replace('/', '_')
        
        # 临时保存上传的文件
        temp_filename = f"{safe_employee_id}/{date_str}/{computer_name}_{windows_user}_{time_str}_temp.jpg"
        temp_path = os.path.join(Config.SCREENSHOT_DIR, temp_filename)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        file.save(temp_path)
        
        # 压缩图片
        image_format = Config.SCREENSHOT_FORMAT
        image_quality = Config.SCREENSHOT_QUALITY
        
        # 如果有客户端配置，使用客户端的配置
        if client_id and 'client' in locals() and client:
            image_format = client.config.get('format', image_format)
            image_quality = client.config.get('quality', image_quality)
        
        # 压缩图片
        final_path = compress_image(temp_path, image_format, image_quality)
        
        # 生成最终文件名
        final_filename = f"{safe_employee_id}/{date_str}/{computer_name}_{windows_user}_{time_str}.{image_format}"
        thumbnail = f"thumbnails/{safe_employee_id}/{date_str}/{computer_name}_{windows_user}_{time_str}.webp"
        
        # 如果压缩后的路径和预期的不一致，需要移动文件
        expected_path = os.path.join(Config.SCREENSHOT_DIR, final_filename)
        if final_path != expected_path:
            os.makedirs(os.path.dirname(expected_path), exist_ok=True)
            os.rename(final_path, expected_path)
            final_path = expected_path
        
        # 获取图片尺寸并创建缩略图
        try:
            with Image.open(final_path) as img:
                width, height = img.size
            
            # 创建缩略图
            thumb_path = os.path.join(Config.SCREENSHOT_DIR, thumbnail)
            os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
            create_thumbnail(final_path, thumb_path)
        except Exception as e:
            logger.error(f"处理图片失败: {e}")
            width = height = 0
        
        # 保存记录
        screenshot = Screenshot(
            employee_id=employee_id,
            client_id=client_id,
            filename=final_filename,
            thumbnail=thumbnail,
            file_size=os.path.getsize(final_path),
            width=width,
            height=height,
            storage_url=f"/screenshots/{final_filename}",
            screenshot_time=screenshot_time,
            computer_name=computer_name,
            windows_user=windows_user,
            image_format=image_format,
            is_encrypted=encrypted
        )
        db.session.add(screenshot)
        db.session.commit()
        
        # 记录活动
        log_activity(employee_id, 'screenshot', {
            'filename': final_filename,
            'computer': computer_name,
            'user': windows_user,
            'format': image_format,
            'size': screenshot.file_size
        })
        
        logger.info(f"✅ 截图保存成功: {final_filename} ({image_format}, {screenshot.file_size/1024:.1f}KB)")
        
        return jsonify({
            'success': True,
            'url': screenshot.storage_url,
            'thumbnail': f"/screenshots/{thumbnail}",
            'format': image_format,
            'size': screenshot.file_size
        })
    except Exception as e:
        logger.error(f"上传失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==================== 员工管理接口 ====================

@app.route('/api/employees', methods=['GET'])
@login_required
def get_employees():
    """获取所有员工"""
    try:
        employees = Employee.query.order_by(Employee.employee_id).all()
        return jsonify([e.to_dict() for e in employees])
    except Exception as e:
        logger.error(f"获取员工列表失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/detailed', methods=['GET'])
@login_required
def get_employees_detailed():
    """获取详细的员工信息（包含客户端信息）"""
    try:
        employees = Employee.query.all()
        result = []
        
        for emp in employees:
            # 获取该员工的所有客户端
            clients = Client.query.filter_by(employee_id=emp.employee_id).all()
            
            emp_data = emp.to_dict()
            emp_data['clients'] = [{
                'client_id': c.client_id,
                'computer_name': c.computer_name,
                'windows_user': c.windows_user,
                'ip_address': c.ip_address,
                'last_seen': c.last_seen.isoformat() if c.last_seen else None,
                'is_online': c.is_online,
                'os_version': c.os_version
            } for c in clients]
            
            # 最后活跃时间
            if clients:
                last_seen = max([c.last_seen for c in clients if c.last_seen], default=None)
                emp_data['last_active'] = last_seen.isoformat() if last_seen else None
            
            result.append(emp_data)
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取详细员工信息失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees', methods=['POST'])
@login_required
def create_employee():
    """创建新员工"""
    try:
        data = request.get_json()
        
        employee = Employee(
            employee_id=data['employee_id'],
            name=data.get('name', data['employee_id']),
            computer_name=data.get('computer_name'),
            windows_user=data.get('windows_user'),
            department=data.get('department'),
            position=data.get('position'),
            email=data.get('email'),
            phone=data.get('phone'),
            status=data.get('status', 'active')
        )
        
        db.session.add(employee)
        db.session.commit()
        
        log_activity(employee.employee_id, 'employee_created', data)
        
        return jsonify({'success': True, 'employee': employee.to_dict()})
    except Exception as e:
        logger.error(f"创建员工失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/<employee_id>', methods=['PUT'])
@login_required
def update_employee(employee_id):
    """更新员工信息"""
    try:
        data = request.get_json()
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        
        if not employee:
            return jsonify({'error': '员工不存在'}), 404
        
        # 更新字段
        employee.name = data.get('name', employee.name)
        employee.computer_name = data.get('computer_name', employee.computer_name)
        employee.windows_user = data.get('windows_user', employee.windows_user)
        employee.department = data.get('department', employee.department)
        employee.position = data.get('position', employee.position)
        employee.email = data.get('email', employee.email)
        employee.phone = data.get('phone', employee.phone)
        employee.status = data.get('status', employee.status)
        
        db.session.commit()
        
        log_activity(employee_id, 'employee_updated', data)
        
        return jsonify({'success': True, 'employee': employee.to_dict()})
    except Exception as e:
        logger.error(f"更新员工失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/<employee_id>', methods=['DELETE'])
@login_required
def delete_employee(employee_id):
    """删除员工"""
    try:
        employee = Employee.query.filter_by(employee_id=employee_id).first()
        
        if not employee:
            return jsonify({'error': '员工不存在'}), 404
        
        # 检查是否有截图关联
        screenshot_count = Screenshot.query.filter_by(employee_id=employee_id).count()
        if screenshot_count > 0:
            return jsonify({'error': f'该员工有 {screenshot_count} 张截图，无法删除'}), 400
        
        db.session.delete(employee)
        db.session.commit()
        
        log_activity(employee_id, 'employee_deleted')
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除员工失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/<employee_id>/dates')
@login_required
def get_employee_dates(employee_id):
    """获取员工有截图的所有日期"""
    try:
        screenshots = Screenshot.query.filter_by(employee_id=employee_id).all()
        
        dates = {}
        for s in screenshots:
            date = s.screenshot_time.strftime('%Y-%m-%d')
            dates[date] = dates.get(date, 0) + 1
        
        result = [{'date': d, 'count': dates[d]} for d in sorted(dates.keys(), reverse=True)]
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取日期列表失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 截图接口 ====================

@app.route('/api/screenshots/<employee_id>/<date>')
@login_required
def get_screenshots(employee_id, date):
    """获取员工指定日期的截图"""
    try:
        start = datetime.strptime(date, '%Y-%m-%d')
        end = start + timedelta(days=1)
        
        screenshots = Screenshot.query.filter(
            Screenshot.employee_id == employee_id,
            Screenshot.screenshot_time >= start,
            Screenshot.screenshot_time < end
        ).order_by(Screenshot.screenshot_time.desc()).all()
        
        return jsonify([s.to_dict() for s in screenshots])
    except Exception as e:
        logger.error(f"获取截图列表失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/screenshots/recent')
@login_required
def get_recent_screenshots():
    """获取最近的截图"""
    try:
        limit = request.args.get('limit', 20, type=int)
        
        screenshots = Screenshot.query.order_by(
            Screenshot.screenshot_time.desc()
        ).limit(limit).all()
        
        return jsonify([s.to_dict() for s in screenshots])
    except Exception as e:
        logger.error(f"获取最近截图失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 客户端接口 ====================

@app.route('/api/clients')
@login_required
def get_clients():
    """获取所有客户端"""
    try:
        clients = Client.query.order_by(Client.last_seen.desc()).all()
        return jsonify([c.to_dict() for c in clients])
    except Exception as e:
        logger.error(f"获取客户端列表失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clients/online')
@login_required
def get_online_clients():
    """获取在线客户端"""
    try:
        now = datetime.utcnow()
        clients = Client.query.filter(
            Client.last_seen >= now - timedelta(minutes=10)
        ).order_by(Client.last_seen.desc()).all()
        
        return jsonify([c.to_dict() for c in clients])
    except Exception as e:
        logger.error(f"获取在线客户端失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 统计接口 ====================

@app.route('/api/stats')
@login_required
def get_stats():
    """获取系统统计信息"""
    try:
        now = datetime.utcnow()
        today = now.date()
        week_ago = now - timedelta(days=7)
        
        # 今日截图
        today_count = Screenshot.query.filter(
            db.func.date(Screenshot.screenshot_time) == today
        ).count()
        
        # 昨日截图
        yesterday = today - timedelta(days=1)
        yesterday_count = Screenshot.query.filter(
            db.func.date(Screenshot.screenshot_time) == yesterday
        ).count()
        
        # 本周截图
        week_count = Screenshot.query.filter(
            Screenshot.screenshot_time >= week_ago
        ).count()
        
        # 在线客户端
        online_clients = Client.query.filter(
            Client.last_seen >= now - timedelta(minutes=10)
        ).count()
        
        # 总数据
        total_screenshots = Screenshot.query.count()
        total_employees = Employee.query.count()
        total_clients = Client.query.count()
        
        # 存储大小
        total_size = db.session.query(
            db.func.sum(Screenshot.file_size)
        ).scalar() or 0
        
        # 各格式统计
        webp_count = Screenshot.query.filter_by(image_format='webp').count()
        jpg_count = Screenshot.query.filter_by(image_format='jpg').count()
        other_count = total_screenshots - webp_count - jpg_count
        
        # 每小时活动
        hourly = []
        for i in range(24):
            start = now.replace(hour=i, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
            count = Screenshot.query.filter(
                Screenshot.screenshot_time >= start,
                Screenshot.screenshot_time < end
            ).count()
            hourly.append(count)
        
        # 最近活动
        recent_activities = Activity.query.order_by(
            Activity.created_at.desc()
        ).limit(10).all()
        
        # 各员工截图统计
        employee_stats = []
        employees = Employee.query.limit(5).all()
        for emp in employees:
            employee_stats.append({
                'id': emp.employee_id,
                'name': emp.name,
                'today': Screenshot.query.filter(
                    Screenshot.employee_id == emp.employee_id,
                    db.func.date(Screenshot.screenshot_time) == today
                ).count(),
                'total': Screenshot.query.filter_by(employee_id=emp.employee_id).count()
            })
        
        return jsonify({
            'today': today_count,
            'yesterday': yesterday_count,
            'week': week_count,
            'total': total_screenshots,
            'employees': total_employees,
            'clients': total_clients,
            'online': online_clients,
            'storage_mb': round(total_size / (1024 * 1024), 2),
            'image_formats': {
                'webp': webp_count,
                'jpg': jpg_count,
                'other': other_count
            },
            'hourly': hourly,
            'recent_activities': [a.to_dict() for a in recent_activities],
            'top_employees': employee_stats,
            'auto_cleanup': {
                'enabled': Config.AUTO_CLEANUP_ENABLED,
                'interval_hours': Config.CLEANUP_INTERVAL / 3600,
                'retention_hours': Config.SCREENSHOT_RETENTION_HOURS
            }
        })
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/activities')
@login_required
def get_activities():
    """获取活动日志"""
    try:
        activities = Activity.query.order_by(
            Activity.created_at.desc()
        ).limit(50).all()
        return jsonify([a.to_dict() for a in activities])
    except Exception as e:
        logger.error(f"获取活动日志失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 文件服务 ====================

@app.route('/screenshots/<path:filename>')
@login_required
def serve_screenshot(filename):
    """提供截图文件"""
    try:
        if '..' in filename or filename.startswith('/'):
            abort(404)
        
        filepath = os.path.join(Config.SCREENSHOT_DIR, filename)
        if not os.path.exists(filepath):
            abort(404)
        
        # 根据文件扩展名设置MIME类型
        if filename.endswith('.webp'):
            mimetype = 'image/webp'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            mimetype = 'image/jpeg'
        else:
            mimetype = None
        
        return send_file(filepath, mimetype=mimetype)
    except Exception as e:
        logger.error(f"提供文件失败: {e}")
        abort(404)

# ==================== 清理接口 ====================

@app.route('/api/cleanup', methods=['POST'])
@login_required
def cleanup_old_screenshots():
    """手动清理旧截图"""
    try:
        hours = Config.SCREENSHOT_RETENTION_HOURS
        if hours <= 0:
            return jsonify({'message': '保留小时数设置为0，不清理'})
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        old_screenshots = Screenshot.query.filter(
            Screenshot.screenshot_time < cutoff
        ).all()
        
        count = 0
        size_freed = 0
        
        for s in old_screenshots:
            filepath = os.path.join(Config.SCREENSHOT_DIR, s.filename)
            if os.path.exists(filepath):
                size_freed += os.path.getsize(filepath)
                os.remove(filepath)
            
            if s.thumbnail:
                thumbpath = os.path.join(Config.SCREENSHOT_DIR, s.thumbnail)
                if os.path.exists(thumbpath):
                    os.remove(thumbpath)
            
            db.session.delete(s)
            count += 1
        
        db.session.commit()
        logger.info(f"手动清理完成: 删除 {count} 条记录，释放 {size_freed/1024/1024:.2f}MB 空间")
        
        return jsonify({
            'success': True, 
            'deleted': count,
            'size_freed_mb': round(size_freed / (1024 * 1024), 2)
        })
    except Exception as e:
        logger.error(f"清理失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup/status', methods=['GET'])
@login_required
def get_cleanup_status():
    """获取清理状态"""
    try:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=Config.SCREENSHOT_RETENTION_HOURS)
        
        # 待清理的截图数量
        pending_count = Screenshot.query.filter(
            Screenshot.screenshot_time < cutoff
        ).count()
        
        # 待清理的总大小
        pending_size = db.session.query(
            db.func.sum(Screenshot.file_size)
        ).filter(
            Screenshot.screenshot_time < cutoff
        ).scalar() or 0
        
        # 下次清理时间
        last_cleanup = Activity.query.filter_by(
            action='auto_cleanup'
        ).order_by(Activity.created_at.desc()).first()
        
        next_cleanup = None
        if last_cleanup:
            next_cleanup = last_cleanup.created_at + timedelta(seconds=Config.CLEANUP_INTERVAL)
        
        return jsonify({
            'enabled': Config.AUTO_CLEANUP_ENABLED,
            'retention_hours': Config.SCREENSHOT_RETENTION_HOURS,
            'interval_hours': Config.CLEANUP_INTERVAL / 3600,
            'pending_cleanup': pending_count,
            'pending_size_mb': round(pending_size / (1024 * 1024), 2),
            'last_cleanup': last_cleanup.created_at.isoformat() if last_cleanup else None,
            'next_cleanup': next_cleanup.isoformat() if next_cleanup else None
        })
    except Exception as e:
        logger.error(f"获取清理状态失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': '资源不存在'}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    if request.path.startswith('/api/'):
        return jsonify({'error': '服务器内部错误'}), 500
    return render_template('500.html'), 500

# ==================== 关闭钩子 ====================

@app.teardown_appcontext
def shutdown_cleanup(exception=None):
    """应用上下文销毁时的清理"""
    pass

# ==================== 启动 ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)