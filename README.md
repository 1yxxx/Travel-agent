# Agent Travel

一个面向旅行规划场景的 Supervisor 多 Agent 系统，基于 FastAPI、Streamlit 和可选 LangGraph 状态图构建，支持动态任务路由、领域 Agent 并行执行、任务级流式输出、本地专家 skill/RAG、短期记忆、Redis 状态存储与 PostgreSQL 结果落库。

## 项目亮点

- Supervisor 根据请求动态选择领域 Agent
- 航班、铁路、酒店、景点、天气和本地专家 Agent 并行执行
- 预算核对、行程整合、Reflection 串行收敛
- 基于 SSE 的任务级流式输出
- 本地专家 `skill + RAG` 保留并参与最终规划
- 短期记忆可落 Redis，最终结果可落 PostgreSQL
- 支持 OpenAI 兼容模型、DuckDuckGo 搜索、MCP 天气工具

## 当前架构

`Supervisor 状态图 + 动态路由 + Agent 私有上下文 + 并行领域查询 + 串行收敛`

核心流程如下：

1. 用户提交旅行请求
2. Supervisor 解析约束并动态选择所需领域 Agent
3. `flight/train/hotel/attraction/weather/local_expert` 按需并发执行
4. Collector 汇总结果并串行执行预算核对
5. `itinerary_planner` 生成逐日行程
6. Reflection 检查缺失信息、失败和降级项
7. Summarizer 输出最终文档
8. 结果写入本地文件、Redis、PostgreSQL

## 架构图

```mermaid
graph TD
  U["User"] --> FE["Streamlit Frontend"]
  FE --> API["FastAPI Backend"]
  API --> SUP["Supervisor Runtime"]

  SUP --> INTENT["Intent Parser + Dynamic Router"]
  INTENT --> FLIGHT["Flight Agent"]
  INTENT --> TRAIN["Train Agent"]
  INTENT --> HOTEL["Hotel Agent"]
  INTENT --> POI["Attraction Agent"]
  INTENT --> WEATHER["Weather Agent"]
  INTENT --> LOCAL["Local Expert Agent"]

  FLIGHT --> COL["Collector"]
  TRAIN --> COL
  HOTEL --> COL
  POI --> COL
  WEATHER --> COL
  LOCAL --> COL

  COL --> BUDGET["Budget Optimizer"]
  BUDGET --> ITI["Itinerary Planner"]
  ITI --> REF["Reflection"]
  REF --> SUM["Final Summarizer"]

  SUP --> SSE["SSE Event Stream"]
  SSE --> FE

  SUP --> REDIS["Redis: Task State / Events / Short-term Memory"]
  SUP --> PG["PostgreSQL: Final Result"]
```

## 核心模块

### 1. 多 Agent 规划引擎

后端主编排位于 `backend/supervisor/`，领域 Agent 位于 `backend/agents/domain_agents.py`，负责：

- 统一 SupervisorState
- 动态选择与派发领域 Agent
- Provider 工具调用及失败降级
- 汇总、预算核对、行程整合和 Reflection

### 2. API 与事件流

后端 API 位于 `backend/api_server.py`，负责：

- 接收规划请求
- 创建后台任务
- 输出任务状态
- 提供 SSE 流式事件接口
- 保存最终结果

### 3. 工具层

工具位于 `backend/tools/`，包括：

- DuckDuckGo 搜索工具
- MCP 天气客户端与天气服务
- 本地知识 RAG 工具
- 本地专家 skill

### 4. 存储层

存储逻辑位于 `backend/storage/persistence.py`，支持：

- Redis：任务元信息、事件流、短期记忆
- PostgreSQL：最终规划结果、Markdown、Agent 参与情况

### 5. RAG-LLM rerank示例
你是旅行本地知识检索系统的重排器，不负责回答用户问题，只负责从候选证据中挑出最适合给最终回答模型使用的前 5 条。

排序原则：
1. 与 query 的约束匹配越完整越靠前
2. 同时满足“城市、主题、场景、限制条件”的证据优先
3. section_path 与 query 主题高度一致的证据优先
4. 信息具体、可执行、事实明确的证据优先
5. 内容重复时，只保留更完整的一条
6. 城市不一致、主题漂移、语义过泛的证据排后

只返回 JSON：
{
  "top_ids": ["...", "...", "...", "...", "..."],
  "notes": {
    "dropped_as_duplicate": ["..."],
    "dropped_as_weak_match": ["..."]
  }
}


## 短期记忆与流式输出

### 短期记忆

短期记忆是任务级状态，不做跨任务长期用户画像。当前短期记忆包含：

- `session_id`
- `shared_facts`
- `coordinator_plan`
- `collector_output`
- `itinerary_output`
- `coordinator_final_output`
- `agent_slots` 状态快照

### 流式输出

项目使用 SSE 实现任务级流式输出，事件包括：

- `task_created`
- `task_started`
- `coordinator_planned`
- `agent_started`
- `tool_called`
- `tool_completed`
- `agent_completed`
- `collector_completed`
- `itinerary_completed`
- `coordinator_finalized`
- `task_completed`

前端通过 `/stream/{task_id}` 实时消费这些事件，并在失败时回退到轮询模式。

## 技术栈

- Frontend: Streamlit
- Backend: FastAPI
- Workflow: LangGraph
- LLM: OpenAI-compatible API
- MCP: Weather MCP client/server
- RAG: Chroma-based local knowledge retrieval
- Cache / State: Redis
- Final Storage: PostgreSQL


## 环境建议

- Python 3.10+
- Anaconda 环境：`agent-travel`

### 常用环境变量

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=your_openai_compatible_base_url
OPENAI_MODEL=your_model_name

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=postgres

QWEATHER_API_KEY=your_qweather_key
```

## 项目结构

```text
Agent-travel/
├─ backend/
│  ├─ agents/
│  ├─ tools/
│  ├─ storage/
│  ├─ skills/
│  ├─ config/
│  └─ api_server.py
├─ frontend/
│  └─ streamlit_app.py
├─ knowledge-rag/
```

## Acknowledgement
本项目的代码参考了开源工作：[FlyAIBox](https://github.com/FlyAIBox/Agent_In_Action/tree/main/03-agent-build-docker-deploy)

