#!/bin/bash
# entrypoint.sh - Docker容器入口脚本

set -e  # 遇到错误立即退出

echo "========================================="
echo "员工监控系统 - Docker容器启动"
echo "========================================="
echo "当前时间: $(date)"
echo "Python版本: $(python --version)"
echo "工作目录: $(pwd)"
echo "========================================="

# 下载Aiven CA证书（如果不存在且需要）
if [ ! -f "ca.pem" ] && [ -n "$CA_CERT_PATH" ]; then
    echo "下载Aiven CA证书..."
    curl -o ca.pem https://certs.aiven.io/ca.pem
    echo "✅ CA证书下载完成"
fi

# 步骤1：等待数据库就绪
echo "[1/4] 等待数据库就绪..."
python -c "
import time
import psycopg2
import os
from urllib.parse import urlparse

db_url = os.environ.get('DATABASE_URL', '')
if not db_url:
    print('❌ DATABASE_URL 未设置')
    exit(1)

# 解析数据库URL
result = urlparse(db_url)
conn_params = {
    'dbname': result.path[1:],
    'user': result.username,
    'password': result.password,
    'host': result.hostname,
    'port': result.port or 5432,
    'sslmode': 'require',
    'connect_timeout': 5
}

# 添加CA证书（如果存在）
if os.path.exists('ca.pem'):
    conn_params['sslrootcert'] = 'ca.pem'

# 尝试连接
max_retries = 30
for i in range(max_retries):
    try:
        conn = psycopg2.connect(**conn_params)
        conn.close()
        print('✅ 数据库连接成功')
        exit(0)
    except Exception as e:
        print(f'⏳ 等待数据库就绪 ({i+1}/{max_retries}): {e}')
        time.sleep(2)

print('❌ 数据库连接超时')
exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ 数据库连接失败，退出"
    exit 1
fi

# 步骤2：数据库初始化
echo "[2/4] 执行数据库初始化..."
python init_db.py

if [ $? -ne 0 ]; then
    echo "❌ 数据库初始化失败，退出"
    exit 1
fi

# 步骤3：验证数据库表
echo "[3/4] 验证数据库表..."
python -c "
from app import app, db
from models import User

with app.app_context():
    try:
        # 尝试查询用户表
        user_count = User.query.count()
        print(f'✅ 数据库验证成功，当前用户数: {user_count}')
    except Exception as e:
        print(f'❌ 数据库验证失败: {e}')
        exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ 数据库验证失败，退出"
    exit 1
fi

# 步骤4：启动Gunicorn
echo "[4/4] 启动Gunicorn服务器..."
echo "工作进程数: ${GUNICORN_WORKERS:-2}"
echo "绑定端口: 0.0.0.0:${PORT:-5000}"
echo "========================================="

# 使用exec替换当前进程，确保信号正确传递
exec gunicorn \
    --workers ${GUNICORN_WORKERS:-2} \
    --bind 0.0.0.0:${PORT:-5000} \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level ${LOG_LEVEL:-info} \
    app:app