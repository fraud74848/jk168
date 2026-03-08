# 使用官方Python镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 下载Aiven CA证书
RUN curl -o ca.pem https://certs.aiven.io/ca.pem

# 创建启动脚本
RUN echo '#!/bin/bash\n\
echo "========================================="\n\
echo "Docker容器启动 - 员工监控系统"\n\
echo "========================================="\n\
\n\
# 步骤1：数据库初始化\n\
echo "[1/3] 执行数据库初始化..."\n\
python init_db.py\n\
\n\
if [ $? -ne 0 ]; then\n\
    echo "❌ 数据库初始化失败"\n\
    exit 1\n\
fi\n\
\n\
# 步骤2：检查数据库连接\n\
echo "[2/3] 验证数据库连接..."\n\
python -c "from app import app, db; app.app_context().push(); db.create_all(checkfirst=True); print('\''✅ 数据库连接验证成功'\'')"\n\
\n\
# 步骤3：启动应用\n\
echo "[3/3] 启动Gunicorn服务器..."\n\
exec gunicorn --workers ${GUNICORN_WORKERS:-1} \\\n\
    --bind 0.0.0.0:${PORT:-5000} \\\n\
    --timeout 120 \\\n\
    --access-logfile - \\\n\
    --error-logfile - \\\n\
    app:app\n\
' > /app/start.sh && chmod +x /app/start.sh

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["/app/start.sh"]
