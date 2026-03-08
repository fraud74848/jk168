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
    tree \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt gunicorn psycopg2-binary

# 复制应用代码（包括templates目录）
COPY . .

# 调试：检查文件是否被正确复制
RUN echo "=== 检查复制的文件 ===" && \
    ls -la /app/ && \
    echo "=== 检查 templates 目录 ===" && \
    ls -la /app/templates/ || echo "⚠️ templates目录不存在，正在创建..." && \
    mkdir -p /app/templates

# 创建必要目录
RUN mkdir -p /data/screenshots /data/logs && \
    chmod +x /app/entrypoint.sh

# 创建缺失的错误页面（如果没有）
RUN if [ ! -f /app/templates/404.html ]; then \
    echo '<!DOCTYPE html><html><head><title>404</title></head><body><h1>404 - Page Not Found</h1></body></html>' > /app/templates/404.html; \
    fi && \
    if [ ! -f /app/templates/500.html ]; then \
    echo '<!DOCTYPE html><html><head><title>500</title></head><body><h1>500 - Internal Server Error</h1></body></html>' > /app/templates/500.html; \
    fi

# 验证所有必要文件存在
RUN echo "=== 验证必要文件 ===" && \
    REQUIRED_FILES="login.html dashboard.html employees.html screenshots.html" && \
    for file in $REQUIRED_FILES; do \
        if [ -f "/app/templates/$file" ]; then \
            echo "✅ $file 存在"; \
        else \
            echo "❌ $file 不存在"; \
            exit 1; \
        fi \
    done

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["/app/entrypoint.sh"]
