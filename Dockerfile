# ============================
# TripAI Dockerfile
# 构建: docker build -t tripai:latest .
# ============================

FROM python:3.11-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 先复制依赖文件 (利用 Docker 缓存层)
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目代码
COPY . .

# 声明挂载点 (环境变量文件)
VOLUME ["/app/.env"]

# 后端 API 端口
EXPOSE 8080

# 默认启动后端 (api_server.py 在 backend/ 目录下)
WORKDIR /app/backend
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8080"]
