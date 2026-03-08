# 使用官方Python镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt gunicorn psycopg2-binary

# 复制应用代码
COPY . .

# 创建必要目录
RUN mkdir -p /data/screenshots /data/logs && \
    chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["/app/entrypoint.sh"]
