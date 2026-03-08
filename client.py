#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
员工监控系统客户端
自动注册并定时截图上传
版本: 2.1 - 支持WebP格式
"""

import os
import sys
import time
import json
import socket
import uuid
import logging
import argparse
import platform
import hashlib
import threading
import io
import zipfile
from datetime import datetime
from pathlib import Path
from functools import wraps

import requests
from PIL import ImageGrab, Image

# 可选导入，如果缺失则禁用相应功能
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False

# 配置日志
def setup_logging(log_level=logging.INFO):
    """配置日志系统"""
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # 文件处理器
    file_handler = logging.FileHandler('monitor.log', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# 重试装饰器
def retry(max_retries=3, delay=1, backoff=2):
    """
    重试装饰器
    :param max_retries: 最大重试次数
    :param delay: 初始延迟（秒）
    :param backoff: 退避倍数
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _delay = delay
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        logger.error(f"{func.__name__} 最终失败: {e}")
                        raise
                    logger.warning(f"{func.__name__} 失败，{_delay}秒后重试 ({i+1}/{max_retries}): {e}")
                    time.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper
    return decorator

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = {}
        self.lock = threading.Lock()
        self.last_mtime = 0
        
    def load(self):
        """加载配置文件"""
        with self.lock:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        self.config = json.load(f)
                    self.last_mtime = os.path.getmtime(self.config_file)
                    logger.info(f"加载配置文件: {self.config_file}")
                    return True
                except Exception as e:
                    logger.error(f"读取配置文件失败: {e}")
            return False
    
    def save(self, config_data):
        """保存配置"""
        with self.lock:
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                self.last_mtime = os.path.getmtime(self.config_file)
                logger.info(f"配置已保存到 {self.config_file}")
                return True
            except Exception as e:
                logger.error(f"保存配置失败: {e}")
                return False
    
    def get(self, key, default=None):
        """获取配置项"""
        with self.lock:
            return self.config.get(key, default)
    
    def set(self, key, value):
        """设置配置项"""
        with self.lock:
            self.config[key] = value
    
    def has_changed(self):
        """检查配置文件是否已更改"""
        if os.path.exists(self.config_file):
            mtime = os.path.getmtime(self.config_file)
            return mtime > self.last_mtime
        return False
    
    def reload_if_changed(self):
        """如果文件已更改则重新加载"""
        if self.has_changed():
            logger.info("检测到配置文件变化，重新加载")
            return self.load()
        return False

class SystemInfoCollector:
    """系统信息收集器"""
    
    @staticmethod
    def get_mac_address():
        """获取MAC地址作为唯一标识"""
        try:
            mac = uuid.getnode()
            return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
        except:
            return "00:00:00:00:00:00"
    
    @staticmethod
    def get_computer_name():
        """获取计算机名"""
        return socket.gethostname()
    
    @staticmethod
    def get_ip_address():
        """获取IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    @staticmethod
    def get_system_info():
        """获取系统信息"""
        info = {
            'computer_name': SystemInfoCollector.get_computer_name(),
            'mac_address': SystemInfoCollector.get_mac_address(),
            'ip_address': SystemInfoCollector.get_ip_address(),
            'os_version': platform.platform(),
            'python_version': platform.python_version(),
            'hostname': socket.gethostname(),
            'processor': platform.processor(),
            'machine': platform.machine()
        }
        
        # 添加系统资源信息（如果psutil可用）
        if PSUTIL_AVAILABLE:
            try:
                info['cpu_count'] = psutil.cpu_count()
                info['memory_total'] = psutil.virtual_memory().total
                info['disk_total'] = psutil.disk_usage('/').total
            except:
                pass
        
        return info
    
    @staticmethod
    def get_system_stats():
        """获取系统状态"""
        if not PSUTIL_AVAILABLE:
            return {}
        
        try:
            stats = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent,
                'network_io': {
                    'bytes_sent': psutil.net_io_counters().bytes_sent,
                    'bytes_recv': psutil.net_io_counters().bytes_recv
                },
                'process_count': len(psutil.pids()),
                'boot_time': psutil.boot_time(),
                'timestamp': datetime.now().isoformat()
            }
            
            # 获取CPU温度（如果可用）
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            stats['cpu_temperature'] = entries[0].current
                            break
            
            return stats
        except Exception as e:
            logger.debug(f"获取系统状态失败: {e}")
            return {}

class ScreenshotManager:
    """截图管理器"""
    
    def __init__(self, quality=80, format='webp', max_history=10):
        self.quality = quality
        self.format = format.lower()
        self.max_history = max_history
        self.last_screenshot_path = None
        self.screenshot_history = []
        self.encryption_key = os.environ.get('ENCRYPTION_KEY')
        
        # 验证格式
        if self.format not in ['webp', 'jpg', 'jpeg']:
            logger.warning(f"不支持的图片格式 {self.format}，使用 webp")
            self.format = 'webp'
    
    def take_screenshot(self):
        """截取屏幕"""
        try:
            # 截取屏幕
            screenshot = ImageGrab.grab()
            
            # 生成文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            temp_file = f"screenshot_{timestamp}.{self.format}"
            
            # 保存图片
            if self.format == 'webp':
                screenshot.save(temp_file, 'WEBP', quality=self.quality, optimize=True, method=6)
            else:
                screenshot.save(temp_file, 'JPEG', quality=self.quality, optimize=True)
            
            file_size = os.path.getsize(temp_file)
            
            # 添加到历史记录
            self.screenshot_history.append(temp_file)
            if len(self.screenshot_history) > self.max_history:
                old_file = self.screenshot_history.pop(0)
                if os.path.exists(old_file) and old_file != self.last_screenshot_path:
                    try:
                        os.remove(old_file)
                    except:
                        pass
            
            logger.info(f"截图成功: {temp_file} ({file_size/1024:.1f}KB, {self.format})")
            return temp_file
            
        except Exception as e:
            logger.error(f"截图失败: {e}")
            return None
    
    def encrypt_screenshot(self, image_path):
        """加密截图文件"""
        if not CRYPTO_AVAILABLE or not self.encryption_key:
            return image_path
        
        try:
            # 初始化加密器
            cipher = Fernet(self.encryption_key.encode())
            
            # 读取图片
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # 加密
            encrypted_data = cipher.encrypt(image_data)
            
            # 保存加密文件
            encrypted_path = image_path + '.encrypted'
            with open(encrypted_path, 'wb') as f:
                f.write(encrypted_data)
            
            # 删除原文件
            os.remove(image_path)
            
            logger.debug(f"截图已加密: {encrypted_path}")
            return encrypted_path
            
        except Exception as e:
            logger.error(f"加密失败: {e}")
            return image_path
    
    def are_similar(self, img1_path, img2_path, threshold=0.95):
        """判断两张图片是否相似"""
        if not img1_path or not img2_path or not os.path.exists(img1_path) or not os.path.exists(img2_path):
            return False
        
        try:
            # 计算文件哈希
            hash1 = hashlib.md5(open(img1_path, 'rb').read()).hexdigest()
            hash2 = hashlib.md5(open(img2_path, 'rb').read()).hexdigest()
            
            if hash1 == hash2:
                return True
            
            # 如果哈希不同，可以进一步比较图片内容
            img1 = Image.open(img1_path)
            img2 = Image.open(img2_path)
            
            # 调整大小以加快比较
            img1 = img1.resize((100, 100))
            img2 = img2.resize((100, 100))
            
            # 计算直方图差异
            h1 = img1.histogram()
            h2 = img2.histogram()
            
            rms = sum((a - b) ** 2 for a, b in zip(h1, h2)) / len(h1)
            similarity = 1 - (rms ** 0.5) / 255.0
            
            return similarity >= threshold
            
        except Exception as e:
            logger.debug(f"图片比较失败: {e}")
            return False
    
    def cleanup_old_screenshots(self, max_age_hours=24):
        """清理旧截图"""
        try:
            now = time.time()
            pattern = f'screenshot_*.{self.format}'
            for file in Path('.').glob(pattern):
                if now - os.path.getmtime(file) > max_age_hours * 3600:
                    os.remove(file)
                    logger.debug(f"已清理旧截图: {file}")
        except Exception as e:
            logger.error(f"清理旧截图失败: {e}")

class APIClient:
    """API客户端"""
    
    def __init__(self, base_url, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        
        # 设置默认头
        self.session.headers.update({
            'User-Agent': f'MonitorClient/{platform.platform()}',
            'Accept': 'application/json'
        })
        
    @retry(max_retries=3, delay=1)
    def post(self, endpoint, **kwargs):
        """POST请求"""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('timeout', self.timeout)
        
        # 添加SSL验证
        if CERTIFI_AVAILABLE:
            kwargs.setdefault('verify', certifi.where())
        
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response.json()
    
    @retry(max_retries=3, delay=1)
    def get(self, endpoint, **kwargs):
        """GET请求"""
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('timeout', self.timeout)
        
        if CERTIFI_AVAILABLE:
            kwargs.setdefault('verify', certifi.where())
        
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response.json()
    
    def health_check(self):
        """健康检查"""
        try:
            response = self.session.get(f"{self.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False

class MonitorClient:
    """监控客户端主类"""
    
    def __init__(self, config_file='config.json'):
        # 初始化组件
        self.config_manager = ConfigManager(config_file)
        self.system_info = SystemInfoCollector()
        self.api_client = None
        
        # 加载配置
        self.config_manager.load()
        
        # 客户端状态
        self.running = False
        self.client_id = self.config_manager.get('client_id')
        self.employee_id = self.config_manager.get('employee_id')
        self.server_url = self.config_manager.get('server_url')
        self.interval = self.config_manager.get('interval', 120)
        self.quality = self.config_manager.get('quality', 80)
        self.format = self.config_manager.get('format', 'webp')
        
        # 初始化截图管理器
        self.screenshot_manager = ScreenshotManager(
            quality=self.quality, 
            format=self.format
        )
        
        # 统计信息
        self.stats = {
            'screenshots_taken': 0,
            'screenshots_uploaded': 0,
            'upload_failures': 0,
            'start_time': None,
            'last_upload_time': None
        }
        
        # 线程锁
        self.stats_lock = threading.Lock()
        
        # 验证配置
        self.validate_config()
        
    def validate_config(self):
        """验证配置有效性"""
        if self.server_url:
            # 验证服务器URL格式
            if not self.server_url.startswith(('http://', 'https://')):
                logger.error(f"无效的服务器URL: {self.server_url}")
                self.server_url = None
        
        # 验证截图间隔
        if self.interval < 10 or self.interval > 3600:
            logger.warning(f"截图间隔{self.interval}秒不合理，使用默认值300秒")
            self.interval = 300
            
        # 验证图片质量
        if self.quality < 10 or self.quality > 100:
            logger.warning(f"图片质量{self.quality}不合理，使用默认值80")
            self.quality = 80
        
        # 验证图片格式
        if self.format not in ['webp', 'jpg', 'jpeg']:
            logger.warning(f"图片格式{self.format}不合理，使用webp")
            self.format = 'webp'
    
    def init_api_client(self):
        """初始化API客户端"""
        if self.server_url and not self.api_client:
            self.api_client = APIClient(self.server_url)
    
    @retry(max_retries=3, delay=2)
    def register_with_server(self):
        """向服务器注册"""
        # 如果配置中已有client_id，尝试使用
        if self.client_id and self.server_url:
            logger.info(f"使用现有配置: client_id={self.client_id}")
            self.init_api_client()
            
            # 尝试获取服务器配置
            try:
                config = self.api_client.get(f'/api/client/{self.client_id}/config')
                if config:
                    self.interval = config.get('interval', self.interval)
                    self.quality = config.get('quality', self.quality)
                    self.format = config.get('format', self.format)
                    self.screenshot_manager.format = self.format
                    self.screenshot_manager.quality = self.quality
                    logger.info(f"从服务器获取配置: interval={self.interval}, quality={self.quality}, format={self.format}")
            except:
                pass
            
            return True
        
        # 从环境变量或用户输入获取服务器地址
        server_url = os.environ.get('MONITOR_SERVER_URL')
        if not server_url:
            print("\n" + "="*50)
            print("员工监控系统客户端 - 首次注册")
            print("="*50)
            server_url = input("请输入服务器地址 (例如: https://employee-monitor.onrender.com): ").strip()
            print()
        
        if not server_url:
            logger.error("未提供服务器地址")
            return False
        
        self.server_url = server_url.rstrip('/')
        self.init_api_client()
        
        # 健康检查
        if not self.api_client.health_check():
            logger.warning("服务器健康检查失败，但将继续尝试注册")
        
        # 获取系统信息
        system_info = self.system_info.get_system_info()
        
        # 添加客户端版本和配置
        system_info['client_version'] = '2.1'
        system_info['format'] = self.format
        system_info['quality'] = self.quality
        
        try:
            logger.info(f"正在向服务器注册: {self.server_url}")
            
            data = self.api_client.post(
                '/api/client/register',
                json=system_info
            )
            
            self.client_id = data['client_id']
            self.employee_id = data.get('employee_id', system_info['computer_name'])
            
            # 从服务器获取配置
            if 'config' in data:
                self.interval = data['config'].get('interval', self.interval)
                self.quality = data['config'].get('quality', self.quality)
                self.format = data['config'].get('format', self.format)
                self.screenshot_manager.format = self.format
                self.screenshot_manager.quality = self.quality
            
            logger.info(f"注册成功!")
            logger.info(f"客户端ID: {self.client_id}")
            logger.info(f"员工ID: {self.employee_id}")
            logger.info(f"截图间隔: {self.interval}秒")
            logger.info(f"图片格式: {self.format}")
            logger.info(f"图片质量: {self.quality}")
            
            # 保存配置
            self.save_config()
            return True
                
        except requests.exceptions.RequestException as e:
            logger.error(f"注册请求失败: {e}")
            return False
    
    def save_config(self):
        """保存配置"""
        config_data = {
            'client_id': self.client_id,
            'employee_id': self.employee_id,
            'server_url': self.server_url,
            'interval': self.interval,
            'quality': self.quality,
            'format': self.format,
            'last_update': datetime.now().isoformat()
        }
        return self.config_manager.save(config_data)
    
    @retry(max_retries=2, delay=1)
    def sync_config(self):
        """从服务器同步配置"""
        if not self.api_client or not self.client_id:
            return False
        
        try:
            config = self.api_client.get(f'/api/client/{self.client_id}/config')
            
            changed = False
            if 'interval' in config and config['interval'] != self.interval:
                self.interval = config['interval']
                changed = True
                logger.info(f"截图间隔已更新: {self.interval}秒")
            
            if 'quality' in config and config['quality'] != self.quality:
                self.quality = config['quality']
                self.screenshot_manager.quality = self.quality
                changed = True
                logger.info(f"图片质量已更新: {self.quality}")
            
            if 'format' in config and config['format'] != self.format:
                self.format = config['format']
                self.screenshot_manager.format = self.format
                changed = True
                logger.info(f"图片格式已更新: {self.format}")
            
            if changed:
                self.save_config()
            
            return True
        except Exception as e:
            logger.debug(f"同步配置失败: {e}")
            return False
    
    @retry(max_retries=2, delay=1)
    def send_heartbeat(self):
        """发送心跳"""
        if not self.api_client or not self.client_id:
            return False
        
        try:
            stats = self.system_info.get_system_stats()
            heartbeat_data = {
                'status': 'online',
                'timestamp': datetime.now().isoformat(),
                'stats': stats,
                'client_stats': self.get_stats()
            }
            
            self.api_client.post(
                f'/api/client/{self.client_id}/heartbeat',
                json=heartbeat_data
            )
            return True
        except Exception as e:
            logger.debug(f"心跳发送失败: {e}")
            return False
    
    @retry(max_retries=3, delay=1)
    def upload_screenshot(self, image_path):
        """上传截图"""
        if not self.api_client or not self.client_id:
            return False
        
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 加密截图（如果需要）
            if CRYPTO_AVAILABLE and self.screenshot_manager.encryption_key:
                image_path = self.screenshot_manager.encrypt_screenshot(image_path)
            
            # 准备上传
            with open(image_path, 'rb') as f:
                files = {
                    'image': (
                        os.path.basename(image_path),
                        f,
                        'image/webp' if image_path.endswith('.webp') else 'image/jpeg' if image_path.endswith(('.jpg', '.jpeg')) else 'application/octet-stream'
                    )
                }
                data = {
                    'employee_id': self.employee_id,
                    'timestamp': timestamp,
                    'client_id': self.client_id,
                    'encrypted': str(image_path.endswith('.encrypted')).lower(),
                    'format': self.format
                }
                
                response = requests.post(
                    f"{self.server_url}/upload",
                    files=files,
                    data=data,
                    timeout=60,
                    verify=certifi.where() if CERTIFI_AVAILABLE else True
                )
                
                if response.status_code == 200:
                    with self.stats_lock:
                        self.stats['screenshots_uploaded'] += 1
                        self.stats['last_upload_time'] = time.time()
                    logger.info(f"截图上传成功: {os.path.basename(image_path)}")
                    return True
                else:
                    logger.warning(f"上传失败: {response.status_code} - {response.text}")
                    with self.stats_lock:
                        self.stats['upload_failures'] += 1
                    return False
                    
        except Exception as e:
            logger.error(f"上传出错: {e}")
            with self.stats_lock:
                self.stats['upload_failures'] += 1
            return False
    
    @retry(max_retries=2, delay=2)
    def upload_screenshots_batch(self):
        """批量上传截图"""
        if not self.api_client or not self.client_id:
            return False
        
        try:
            # 查找未上传的截图（超过10分钟且小于10MB）
            screenshots = []
            now = time.time()
            pattern = f'screenshot_*.{self.format}'
            for file in Path('.').glob(pattern):
                file_age = now - os.path.getmtime(file)
                file_size = file.stat().st_size
                
                # 文件超过10分钟且小于10MB，且不是最后一次截图
                if file_age > 600 and file_size < 10 * 1024 * 1024:
                    if file.name != self.screenshot_manager.last_screenshot_path:
                        screenshots.append(str(file))
            
            if not screenshots:
                return False
            
            logger.info(f"准备批量上传 {len(screenshots)} 个截图")
            
            # 创建ZIP文件
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for screenshot in screenshots:
                    zip_file.write(screenshot, os.path.basename(screenshot))
            
            # 上传ZIP
            files = {
                'batch': (
                    f'screenshots_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip',
                    zip_buffer.getvalue(),
                    'application/zip'
                )
            }
            data = {
                'client_id': self.client_id,
                'count': len(screenshots)
            }
            
            response = requests.post(
                f"{self.server_url}/upload/batch",
                files=files,
                data=data,
                timeout=120,
                verify=certifi.where() if CERTIFI_AVAILABLE else True
            )
            
            if response.status_code == 200:
                # 上传成功后删除本地文件
                for screenshot in screenshots:
                    try:
                        os.remove(screenshot)
                        logger.debug(f"已删除: {screenshot}")
                    except:
                        pass
                
                with self.stats_lock:
                    self.stats['screenshots_uploaded'] += len(screenshots)
                    self.stats['last_upload_time'] = time.time()
                
                logger.info(f"批量上传成功: {len(screenshots)}个文件")
                return True
            else:
                logger.warning(f"批量上传失败: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"批量上传失败: {e}")
            return False
    
    def get_stats(self):
        """获取统计信息"""
        with self.stats_lock:
            stats_copy = self.stats.copy()
            if stats_copy['start_time']:
                uptime = time.time() - stats_copy['start_time']
                stats_copy['uptime'] = uptime
            return stats_copy
    
    def config_watcher(self):
        """配置文件监控线程"""
        while self.running:
            try:
                if self.config_manager.reload_if_changed():
                    # 重新加载配置
                    new_interval = self.config_manager.get('interval', self.interval)
                    if new_interval != self.interval:
                        self.interval = new_interval
                        logger.info(f"配置更新: interval={self.interval}")
                    
                    new_quality = self.config_manager.get('quality', self.quality)
                    if new_quality != self.quality:
                        self.quality = new_quality
                        self.screenshot_manager.quality = self.quality
                        logger.info(f"配置更新: quality={self.quality}")
                    
                    new_format = self.config_manager.get('format', self.format)
                    if new_format != self.format:
                        self.format = new_format
                        self.screenshot_manager.format = self.format
                        logger.info(f"配置更新: format={self.format}")
            except Exception as e:
                logger.error(f"配置监控出错: {e}")
            
            time.sleep(5)
    
    def heartbeat_sender(self):
        """心跳发送线程"""
        while self.running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.debug(f"心跳发送失败: {e}")
            
            # 每分钟发送一次心跳
            for _ in range(60):
                if not self.running:
                    break
                time.sleep(1)
    
    def batch_uploader(self):
        """批量上传线程"""
        while self.running:
            time.sleep(3600)  # 每小时执行一次
            if self.running:
                try:
                    self.upload_screenshots_batch()
                except Exception as e:
                    logger.error(f"批量上传失败: {e}")
    
    def work_loop(self):
        """主工作循环"""
        logger.info(f"开始监控，员工ID: {self.employee_id}")
        logger.info(f"截图间隔: {self.interval}秒")
        logger.info(f"图片格式: {self.format}")
        
        last_sync = 0
        consecutive_failures = 0
        last_screenshot_path = None
        
        while self.running:
            try:
                now = time.time()
                
                # 同步配置（每10分钟）
                if now - last_sync > 600:
                    self.sync_config()
                    last_sync = now
                
                # 截图
                image_path = self.screenshot_manager.take_screenshot()
                if image_path:
                    with self.stats_lock:
                        self.stats['screenshots_taken'] += 1
                    
                    # 检查是否与上一张相似
                    if last_screenshot_path and self.screenshot_manager.are_similar(
                        last_screenshot_path, image_path):
                        logger.debug("屏幕内容无变化，跳过上传")
                        os.remove(image_path)
                        consecutive_failures = 0
                    else:
                        # 上传截图
                        if self.upload_screenshot(image_path):
                            consecutive_failures = 0
                            
                            # 删除上一张截图
                            if last_screenshot_path and os.path.exists(last_screenshot_path):
                                try:
                                    os.remove(last_screenshot_path)
                                except:
                                    pass
                            
                            self.screenshot_manager.last_screenshot_path = image_path
                            last_screenshot_path = image_path
                        else:
                            consecutive_failures += 1
                            logger.warning(f"上传失败，保留本地文件 (连续失败: {consecutive_failures})")
                            
                            # 连续失败太多，降低截图频率
                            if consecutive_failures > 5:
                                self.interval = min(self.interval * 2, 3600)
                                logger.warning(f"连续失败次数过多，调整截图间隔为: {self.interval}秒")
                
                # 等待下一次截图
                for i in range(self.interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"工作循环出错: {e}")
                time.sleep(60)
    
    def start(self):
        """启动监控"""
        print("\n" + "="*50)
        print("员工监控系统客户端 v2.1")
        print("="*50)
        
        # 注册到服务器
        if not self.register_with_server():
            logger.error("注册失败，程序退出")
            return
        
        self.running = True
        self.stats['start_time'] = time.time()
        
        logger.info("="*50)
        logger.info("监控程序启动")
        logger.info("="*50)
        
        # 启动工作线程
        threads = [
            threading.Thread(target=self.work_loop, name="WorkLoop"),
            threading.Thread(target=self.config_watcher, name="ConfigWatcher"),
            threading.Thread(target=self.heartbeat_sender, name="Heartbeat"),
            threading.Thread(target=self.batch_uploader, name="BatchUploader")
        ]
        
        for thread in threads:
            thread.daemon = True
            thread.start()
            logger.debug(f"线程已启动: {thread.name}")
        
        # 保持主线程运行
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.error(f"主线程异常: {e}")
            self.stop()
    
    def stop(self):
        """停止监控"""
        logger.info("正在停止监控程序...")
        self.running = False
        
        # 清理旧截图
        self.screenshot_manager.cleanup_old_screenshots()
        
        # 发送最后一次心跳
        self.send_heartbeat()
        
        # 统计信息
        uptime = time.time() - self.stats['start_time']
        logger.info("="*50)
        logger.info("监控程序停止")
        logger.info(f"运行时间: {uptime/3600:.1f}小时")
        logger.info(f"截图数量: {self.stats['screenshots_taken']}")
        logger.info(f"上传成功: {self.stats['screenshots_uploaded']}")
        logger.info(f"上传失败: {self.stats['upload_failures']}")
        logger.info("="*50)
    
    def test_mode(self):
        """测试模式"""
        print("\n" + "="*50)
        print("测试模式 - 立即截图并上传")
        print("="*50)
        
        if not self.register_with_server():
            logger.error("注册失败")
            return
        
        print(f"客户端ID: {self.client_id}")
        print(f"员工ID: {self.employee_id}")
        print(f"服务器: {self.server_url}")
        print(f"图片格式: {self.format}")
        print("-"*50)
        
        # 截图
        print("正在截图...")
        image_path = self.screenshot_manager.take_screenshot()
        
        if image_path:
            print(f"截图成功: {image_path}")
            print(f"文件大小: {os.path.getsize(image_path)/1024:.1f}KB")
            
            # 上传
            print("正在上传...")
            if self.upload_screenshot(image_path):
                print("✓ 上传成功")
            else:
                print("✗ 上传失败")
            
            # 删除临时文件
            os.remove(image_path)
            print("临时文件已删除")
        else:
            print("✗ 截图失败")
        
        print("="*50)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='员工监控系统客户端',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                          # 正常启动
  %(prog)s --test                    # 测试模式
  %(prog)s --register                 # 仅注册
  %(prog)s --config my_config.json    # 使用自定义配置文件
  %(prog)s --format webp               # 使用WebP格式
  %(prog)s --log-level DEBUG          # 调试模式
        """
    )
    
    parser.add_argument('-c', '--config', default='config.json', 
                       help='配置文件路径 (默认: config.json)')
    parser.add_argument('--test', action='store_true', 
                       help='测试模式：立即截图并上传')
    parser.add_argument('--register', action='store_true', 
                       help='仅注册，不启动监控')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别 (默认: INFO)')
    parser.add_argument('--server', 
                       help='直接指定服务器地址 (覆盖配置文件)')
    parser.add_argument('--interval', type=int,
                       help='截图间隔（秒）')
    parser.add_argument('--quality', type=int, choices=range(10, 101),
                       help='图片质量 (10-100)')
    parser.add_argument('--format', choices=['webp', 'jpg', 'jpeg'],
                       default='webp', help='图片格式 (默认: webp)')
    parser.add_argument('--version', action='version', 
                       version='员工监控系统客户端 2.1')
    
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    
    # 创建客户端实例
    client = MonitorClient(args.config)
    
    # 命令行参数覆盖配置
    if args.server:
        client.server_url = args.server
        logger.info(f"使用命令行指定的服务器: {args.server}")
    
    if args.interval:
        client.interval = args.interval
        logger.info(f"使用命令行指定的截图间隔: {args.interval}秒")
    
    if args.quality:
        client.quality = args.quality
        client.screenshot_manager.quality = args.quality
        logger.info(f"使用命令行指定的图片质量: {args.quality}")
    
    if args.format:
        client.format = args.format
        client.screenshot_manager.format = args.format
        logger.info(f"使用命令行指定的图片格式: {args.format}")
    
    # 执行相应模式
    try:
        if args.test:
            client.test_mode()
        elif args.register:
            client.register_with_server()
        else:
            client.start()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        return 1
    
    return 0

# 生成requirements.txt文件
def generate_requirements():
    """生成依赖文件"""
    requirements = """Pillow>=10.0.0
requests>=2.31.0
psutil>=5.9.0
cryptography>=41.0.0
certifi>=2023.7.22
"""
    with open('requirements.txt', 'w') as f:
        f.write(requirements)
    print("已生成 requirements.txt")

if __name__ == '__main__':
    # 检查是否需要生成requirements.txt
    if len(sys.argv) > 1 and sys.argv[1] == '--generate-requirements':
        generate_requirements()
        sys.exit(0)
    
    # 运行主程序
    sys.exit(main())