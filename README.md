# TripAI（旅小智）—— Supervisor 多 Agent 旅行规划系统

基于 **FastAPI + LangGraph + Streamlit** 的智能旅行规划助手。输入自然语言旅行需求，系统自动拆解任务、并行调度 7 个领域 Agent 查询真实数据源，汇总生成完整旅行方案。

## 项目亮点

- 🧠 **Supervisor 动态路由**：自动解析用户意图，按需选择领域 Agent
- 🛫 **全量真实数据源**：高德 POI + 聚合航班/高铁 + 和风天气 + Chroma 本地知识 RAG
- ⚡ **8 阶段流水线并行执行**：记忆召回 → 意图解析 → 并行调度 → 结果汇总 → 行程生成 → 质量反思 → 最终总结 → 记忆持久化
- 📡 **SSE 流式输出**：实时推送任务进度，Agent 执行状态透明可见
- 🔄 **优雅降级**：任意 API Key 缺失自动回退，不影响主干流程

## 架构

```
用户请求 → Streamlit 前端 → FastAPI 后端 → Supervisor 编排器
                                                  │
        ┌──────────────────────────────────────────┼──────────────────────────────────────┐
        ▼                  ▼                ▼               ▼               ▼              ▼
   Flight Agent      Train Agent      Hotel Agent    Attraction Agent  Weather Agent  Local Expert
   (聚合航班API)     (聚合火车API)     (高德POI)       (高德POI)        (和风天气)     (Chroma RAG)
        │                  │                │               │               │              │
        └──────────────────┴────────────────┴───────────────┴───────────────┴──────────────┘
                                                  │
                                                  ▼
                                        Collector → Budget → Itinerary → Reflection → Summarizer
                                                  │
                                                  ▼
                              Redis (任务状态) + PostgreSQL (结果归档)
```

## 7 个领域 Agent

| Agent | 数据源 | 职责 |
|-------|--------|------|
| ✈️ Flight | 聚合数据 - 航班 API | 查询直飞/中转航班，比较价格 |
| 🚄 Train | 聚合数据 - 火车 API | 查询高铁/动车，比较时间和票价 |
| 🏨 Hotel | 高德 POI + Mock 价格 | 搜索酒店，按星级和预算筛选 |
| 🎯 Attraction | 高德 POI | 搜索景点，按兴趣主题推荐 |
| 🌤️ Weather | 和风天气 | 查询 7 天天气预报，出行建议 |
| 📍 Local Expert | Chroma 本地知识 RAG | 在地美食/文化/避坑指南 |
| 💰 Budget | 内置计算 | 解析预算，给出分配建议 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Streamlit |
| 后端 | FastAPI + Uvicorn |
| 编排引擎 | LangGraph (StateGraph) |
| LLM | DeepSeek (OpenAI 兼容协议) |
| 实时数据 | 高德地图 / 聚合数据 / 和风天气 |
| 知识检索 | ChromaDB + sentence-transformers |
| 缓存 | Redis + DiskCache |
| 持久化 | PostgreSQL |
| 部署 | Docker Compose / systemd + Nginx |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API Key（编辑 .env）
cp .env.deepseek .env

# 导入本地知识库
python backend/scripts/ingest_local_knowledge_to_chroma.py

# 校验环境
python scripts/validate_env.py

# 启动后端
cd backend && python api_server.py

# 启动前端（新终端）
cd frontend && streamlit run streamlit_app.py --server.port 8501
```

浏览器打开 `http://localhost:8501`。

## 项目结构

```
TripAI/
├── backend/
│   ├── agents/              # 7 个领域 Agent 实现
│   ├── supervisor/          # LangGraph 8 阶段流水线编排
│   ├── tools/               # 工具层 (API 封装 + RAG + MCP)
│   ├── storage/             # Redis + PostgreSQL 持久化
│   ├── skills/              # 本地专家 Skill
│   ├── scripts/             # 知识库导入脚本
│   ├── tests/               # 22 项单元测试
│   └── api_server.py        # FastAPI 入口
├── apis/providers/          # 第三方 API Provider
│   ├── amap.py              # 高德地图
│   ├── juhe.py              # 聚合数据
│   ├── qweather.py          # 和风天气
│   └── mock_price.py        # 模拟酒店价格
├── core/                    # 全局配置/日志/缓存/重试
├── frontend/                # Streamlit 前端
├── SimpleExample-knowledge-rag/  # 5 个城市本地知识
├── scripts/                 # 运维脚本
├── DEPLOYMENT.md            # 部署指南
├── docker-compose.yml       # Docker 编排
├── nginx.conf               # Nginx 反代配置
└── requirements.txt         # Python 依赖
```

## 部署

详见 [DEPLOYMENT.md](./DEPLOYMENT.md)，支持 Docker Compose 一键部署和裸机 systemd 部署。
