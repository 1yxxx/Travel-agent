# TripAI 部署指南

> 适用：Windows/macOS/Linux 本地开发 + Ubuntu 20.04+ 云服务器生产部署

---

## 一、本地启动

### 前置要求

| 组件 | 版本要求 | 检查命令 |
|------|---------|---------|
| Python | 3.10+ | `python --version` |
| pip | 最新版 | `pip install --upgrade pip` |
| Redis | 可选（推荐） | `redis-server` |
| PostgreSQL | 可选 | 无则回退本地文件 |

### 1. 安装 Python 依赖

```bash
cd TripAI
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 从模板创建 .env
cp .env.deepseek .env

# 编辑 .env，填入 Key
```

**必填**：

| 变量 | 获取地址 |
|------|---------|
| `OPENAI_API_KEY` | https://platform.deepseek.com → API Keys |

**推荐填入（零降级运行）**：

| 变量 | 获取地址 | 用途 |
|------|---------|------|
| `AMAP_API_KEY` | https://lbs.amap.com → Web服务 | 酒店/景点 POI |
| `JUHE_FLIGHT_KEY` | https://www.juhe.cn → 航班订票查询 | 航班查询 |
| `JUHE_TRAIN_KEY` | https://www.juhe.cn → 火车订票查询 | 高铁查询 |
| `QWEATHER_API_KEY` | https://dev.qweather.com → 控制台 | 天气预报 |

> 💡 只需 DeepSeek Key 就能跑通，其他 Key 缺失时自动降级到搜索模式。

### 3. 导入本地知识库（首次运行）

```bash
python backend/scripts/ingest_local_knowledge_to_chroma.py
```

首次运行会自动下载 `all-MiniLM-L6-v2` 嵌入模型（约 80MB）。数据存储在 `chroma_data/` 目录。

### 4. 启动 Redis（可选）

```bash
# Windows
redis-server

# macOS
brew services start redis

# Linux
sudo systemctl start redis
```

### 5. 环境校验

```bash
python scripts/validate_env.py
```

期望输出全部 ✅。

### 6. 启动服务

```bash
# 终端 1 — 后端 API（端口 8080）
cd backend
python api_server.py

# 终端 2 — 前端界面（端口 8501）
cd frontend
streamlit run streamlit_app.py --server.port 8501
```

### 7. 使用

浏览器打开 **http://localhost:8501**，输入旅行需求：

> "我计划 8 月 1 日从北京去成都玩 4 天，两个人，预算 5000 元，喜欢美食和自然风光"

---

## 二、云服务器部署

> 目标环境：Ubuntu 20.04+ | 至少 2 核 4G 内存

### 方式 A：Docker Compose 一键部署（推荐）

#### 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
sudo apt install docker-compose-plugin -y
# 重新登录使权限生效
```

#### 2. 拉取项目 & 配置

```bash
git clone <你的仓库> TripAI
cd TripAI

# 编辑 .env
vim .env
```

#### 3. 启动全部服务

```bash
docker compose up -d
```

服务一览：

| 服务 | 端口 | 说明 |
|------|:---:|------|
| Streamlit 前端 | 8501 | 用户界面 |
| FastAPI 后端 | 8080 | API + SSE 流 |
| Redis | 6379 | 任务状态缓存 |
| PostgreSQL | 5432 | 结果归档 |

#### 4. 配置 Nginx 反代（可选，推荐）

```bash
sudo apt install nginx -y
sudo cp nginx.conf /etc/nginx/sites-available/tripai
sudo ln -s /etc/nginx/sites-available/tripai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

#### 5. 防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

#### 6. 常用命令

```bash
docker compose logs -f          # 查看日志
docker compose restart          # 重启
docker compose down             # 停止
docker compose up -d --build    # 重新构建并启动
```

---

### 方式 B：裸机部署（systemd）

#### 1. 系统环境

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv redis-server postgresql nginx -y

# 创建数据库
sudo -u postgres psql -c "CREATE DATABASE tripai;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"
```

#### 2. 部署项目

```bash
cd ~
git clone <你的仓库> TripAI
cd TripAI

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置
cp .env.deepseek .env
vim .env

# 导入知识库
python backend/scripts/ingest_local_knowledge_to_chroma.py
```

#### 3. 创建 systemd 服务

**后端** `/etc/systemd/system/tripai-api.service`：

```ini
[Unit]
Description=TripAI API Server
After=network.target redis.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/TripAI/backend
Environment=PATH=/home/ubuntu/TripAI/venv/bin
ExecStart=/home/ubuntu/TripAI/venv/bin/python api_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**前端** `/etc/systemd/system/tripai-frontend.service`：

```ini
[Unit]
Description=TripAI Frontend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/TripAI/frontend
Environment=PATH=/home/ubuntu/TripAI/venv/bin
ExecStart=/home/ubuntu/TripAI/venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tripai-api tripai-frontend
sudo systemctl start tripai-api tripai-frontend
```

#### 4. Nginx 反代 & 防火墙

同方式 A 第 4、5 步。

#### 5. 验证

```bash
curl http://localhost:8080/health
curl http://localhost:8501
```

---

## 降级说明

| Key 缺失 | 效果 |
|----------|------|
| DeepSeek | ❌ 系统不可用 |
| 高德地图 | ⚠️ 酒店/景点降级到搜索 |
| 聚合数据 | ⚠️ 航班/高铁降级到搜索 |
| 和风天气 | ⚠️ 天气降级到搜索 |
| Redis | ⚠️ 任务状态存内存（重启丢失） |
| PostgreSQL | ⚠️ 结果存本地 JSON 文件 |
