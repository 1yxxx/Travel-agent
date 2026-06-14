# TripAI 部署指南

> 适用：Windows/macOS/Linux 本地开发 + Ubuntu 20.04+ 云服务器生产部署

---

## 一、本地启动

### 前置要求

| 组件 | 要求 | 检查命令 |
|------|------|---------|
| Python | 3.10+ | `py --version` (Windows) / `python3 --version` |
| pip | 最新版 | `py -m pip install --upgrade pip` |
| Redis | 可选 | `redis-server`（无则回退内存存储） |
| PostgreSQL | 可选 | 无则回退本地 JSON 文件 |

### 1. 克隆项目

```bash
git clone <你的仓库地址> TripAI
cd TripAI
```

### 2. 创建虚拟环境

```bash
# Windows
py -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

> 如果 Windows 报执行策略错误：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

激活后终端前会显示 `(venv)`，表示虚拟环境已激活。

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> 下载慢？换清华镜像：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

### 4. 配置 API Key

编辑项目根目录下的 `.env` 文件：

```bash
# 必填
OPENAI_API_KEY=sk-your-deepseek-key     # https://platform.deepseek.com

# 推荐填入（零降级运行）
AMAP_API_KEY=xxxxxxxx                   # https://lbs.amap.com → Web服务
JUHE_FLIGHT_KEY=xxxxxxxx                # https://www.juhe.cn → 航班订票查询
JUHE_TRAIN_KEY=xxxxxxxx                 # https://www.juhe.cn → 火车订票查询
QWEATHER_KEY_ID=xxxxxxxx                # https://dev.qweather.com → JWT 凭据 ID
QWEATHER_PRIVATE_KEY=xxxxxxxx           # 和风天气 Ed25519 私钥 (base64)
```

> 💡 只需 DeepSeek Key 就能跑通，其他 Key 缺失时自动降级到搜索或高德天气。

### 5. 导入本地知识库（首次运行）

```bash
python backend/scripts/ingest_local_knowledge_to_chroma.py
```

首次运行会自动下载 `all-MiniLM-L6-v2` 嵌入模型（约 80MB）。数据存储在 `chroma_data/` 目录。

### 6. 启动 Redis（可选）

```bash
# Windows
redis-server

# macOS
brew services start redis

# Linux
sudo systemctl start redis
```

### 7. 环境校验

```bash
python scripts/validate_env.py
```

期望输出全部 ✅。

### 8. 启动服务

需要**两个终端**，都要先激活虚拟环境：

```bash
# 终端 1 — 后端 API（端口 8080）
cd backend
python api_server.py

# 终端 2 — 前端界面（端口 8501）
cd frontend
streamlit run streamlit_app.py --server.port 8501
```

### 9. 使用

浏览器打开 **http://localhost:8501**，输入旅行需求：

> "从北京出发去成都玩 4 天，8月1日出发，两个人，预算 5000 元，喜欢美食和自然风光"

---

## 二、云服务器部署（Ubuntu 20.04+）

### 方式 A：Docker Compose（推荐）

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

# 编辑 .env 填入真实 Key
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

#### 4. Nginx 反代（推荐）

```bash
sudo apt install nginx -y
sudo cp nginx.conf /etc/nginx/sites-available/tripai
sudo ln -s /etc/nginx/sites-available/tripai /etc/nginx/sites-enabled/
# 编辑 nginx.conf 中的 server_name
sudo vim /etc/nginx/sites-available/tripai
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

#### 1. 安装系统依赖

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

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
vim .env

# 导入知识库
python backend/scripts/ingest_local_knowledge_to_chroma.py

# 环境校验
python scripts/validate_env.py
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

# 查看状态
sudo systemctl status tripai-api
sudo systemctl status tripai-frontend
```

#### 4. Nginx 反代 & 防火墙

同方式 A 第 4、5 步。

#### 5. 验证

```bash
curl http://localhost:8080/health
curl http://localhost:8501
```

---

## 三、常用命令速查

```bash
# 激活虚拟环境
# Windows:  .\venv\Scripts\Activate.ps1
# macOS/Linux: source venv/bin/activate

# 退出虚拟环境
deactivate

# 安装依赖
pip install -r requirements.txt

# 环境校验
python scripts/validate_env.py

# 导入知识库
python backend/scripts/ingest_local_knowledge_to_chroma.py

# 启动后端
cd backend && python api_server.py

# 启动前端
cd frontend && streamlit run streamlit_app.py --server.port 8501

# 运行单元测试
python -m backend.tests.test_supervisor_runtime
```

## 四、数据源降级说明

| Key 缺失 | 效果 |
|----------|------|
| DeepSeek | ❌ 系统不可用 |
| 高德地图 | ⚠️ 酒店/景点降级到搜索 |
| 聚合数据-航班 | ⚠️ 航班降级到搜索 |
| 聚合数据-火车 | ⚠️ 高铁降级到搜索 |
| 和风天气 | ⚠️ 天气降级到高德天气 |
| Redis | ⚠️ 任务状态存内存（重启丢失） |
| PostgreSQL | ⚠️ 结果存本地 JSON 文件 |
| ChromaDB | ⚠️ 在地建议降级到搜索 |
