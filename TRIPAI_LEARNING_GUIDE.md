# TripAI 项目学习指南

更新日期：2026-06-14

## 1. 先给项目定性

当前 TripAI 不是生产就绪的企业级旅行 Agent 产品，而是一套具备企业级分层思路的 Supervisor 多 Agent MVP。

准确描述应该是：

> 基于 FastAPI、可选 LangGraph、领域 Agent、Provider、SSE、Redis、PostgreSQL 和本地知识 RAG 构建的多 Agent 旅行规划工程化原型，已经完成动态路由、并发执行、事件流、持久化接口和失败降级骨架，但仍需补齐真实环境联调、状态检查点、质量评估、生产观测和完整测试。

学习时必须区分三件事：

- 架构设计：需求文档中计划达到的目标。
- 当前代码：仓库里真正执行的逻辑。
- 企业级差距：从当前实现走向生产系统还缺什么。

## 2. 企业级完成度评估

| 维度 | 当前状态 | 结论 |
|---|---|---|
| Supervisor 编排 | 已实现统一状态和主流程，支持可选 LangGraph | 基本完成 |
| 动态路由 | 可按能力、出发地和交通偏好选择 Agent | 基本完成 |
| 领域 Agent | 航班、铁路、酒店、景点、天气、本地知识、预算已拆分 | 基本完成 |
| Tool / Provider 分层 | Agent -> Tool -> Provider 调用链已建立 | 基本完成 |
| 并发执行 | 领域 Agent 使用线程池并行 | 已实现 |
| SSE 事件流 | API 支持任务级事件推送，前端支持轮询回退 | 已实现 |
| 失败隔离 | 单 Agent 异常不会终止全链路，降级状态可向最终结果传播 | 已实现 |
| Redis / PostgreSQL | 存储类和 API 接入存在 | 未完成真实环境验收 |
| RAG | Chroma 与本地 Markdown 降级链路存在 | 部分完成 |
| 短期记忆 | 结果快照可写 Redis | 部分完成 |
| 历史记忆召回 | `memory_recall` 目前没有读取历史偏好 | 未实现 |
| Checkpoint | Supervisor 图没有 Checkpointer | 未实现 |
| 高质量行程合成 | 当前主要使用规则模板，没有真正做约束优化 | 未完成 |
| Reflection | 检查缺失字段、失败和降级列表，并生成完整/部分完成状态 | 初级实现 |
| 可观测性 | 有日志和事件，没有完整指标、Trace、告警 | 部分完成 |
| 测试 | 10 个 Supervisor/可靠性测试，持久化测试依赖真实服务 | 覆盖仍不足 |
| 可复现部署 | 缺少依赖清单、Docker、CI | 未完成 |
| 安全 | 密钥未硬编码，但 CORS、输入限制、鉴权不足 | 未达到生产标准 |

综合判断：

- 架构完整度：约 65%
- 功能闭环完整度：约 55%
- 生产可靠性：约 35%
- 当前阶段：企业级方向 MVP，而非企业生产系统

## 3. 必须先理解的主链路

一次结构化规划请求的执行链路：

```text
Streamlit
-> POST /plan
-> FastAPI 创建 task_id
-> run_planning_task
-> SupervisorTravelPlanner
-> memory_recall
-> intent_parser
-> dispatcher
-> domain agents in parallel
-> collector
-> budget optimizer
-> itinerary
-> reflection
-> summarizer
-> memory_store
-> Redis / PostgreSQL / result files
-> SSE /status /download
```

先用一句话记住各层职责：

- API 层管理任务生命周期，不负责旅行领域决策。
- Supervisor 层决定执行顺序和需要哪些 Agent。
- Agent 层负责单一领域任务。
- Tool 层把领域参数转换为可调用工具。
- Provider 层负责 HTTP、缓存、重试和数据标准化。
- Storage 层负责热状态和最终结果归档。

## 4. 推荐源码阅读顺序

### 第 1 阶段：理解输入和动态路由

阅读：

1. `backend/supervisor/state.py`
2. `backend/supervisor/router.py`
3. `backend/tests/test_supervisor_runtime.py`

重点理解：

- `SupervisorState` 为什么是跨节点共享状态。
- `AgentExecution` 为什么要保留 `tool_artifacts`、`error` 和 `degraded`。
- `normalize_request()` 如何统一表单与聊天输入。
- `select_agents()` 如何实现按需路由。
- 为什么交通 Agent 只有在存在出发地时才启用。

必须能回答：

1. 用户只查询酒店和天气时，系统为什么不会执行景点 Agent？
2. `requested_capabilities` 和默认 Agent 集合的优先级是什么？
3. 输入中只有 `travel_dates` 时，起止日期如何提取？
4. 多目的地为什么当前不支持？

动手练习：

- 为“无需住宿”补一个路由测试。
- 为非法日期、空目的地和人数为零补边界测试。
- 增加 `business_trip` 场景，使路由优先选择交通、酒店和天气。

### 第 2 阶段：理解 Supervisor 状态机

阅读：

1. `backend/supervisor/runtime.py`
2. `backend/supervisor/state.py`

按节点阅读：

```text
_memory_recall
_intent_parser
_dispatcher
_collector
_itinerary
_reflection
_summarizer
_memory_store
```

重点理解：

- `_build_graph()` 安装 LangGraph 时构建状态图。
- `_run_pipeline()` 是无 LangGraph 环境下的兼容执行路径。
- `_dispatcher()` 使用 `ThreadPoolExecutor` 并行执行领域 Agent。
- `_collector()` 将预算 Agent 放在领域结果之后串行执行。
- `_build_api_result()` 负责兼容既有 API 返回结构。

必须能回答：

1. 这是真正的图级动态路由，还是节点内部的动态路由？
2. 为什么 Budget Agent 在 Collector 阶段执行？
3. 单个 Future 抛异常后，为什么其他 Agent 还能完成？
4. `planning_complete` 如何综合缺失 Agent、降级 Agent 和缺失输入计算？
5. 为什么当前图还不能断点恢复？

关键结论：

当前 LangGraph 图本身是线性的，动态 Agent 选择发生在 `intent_parser` 和 `dispatcher` 内部。它是 Supervisor 架构，但还没有使用条件边、Send API 或 Checkpointer 实现更细粒度的图级调度。

### 第 3 阶段：理解领域 Agent

阅读：

1. `backend/agents/domain_agents.py`
2. `backend/tools/flight_tool.py`
3. `backend/tools/train_tool.py`
4. `backend/tools/hotel_tool.py`
5. `backend/tools/attraction_tool.py`
6. `backend/tools/weather_tool.py`

重点理解：

- `BaseDomainAgent.execute()` 定义统一执行模板。
- 每个领域 Agent 只负责构造本领域工具参数。
- `_load_tool()` 让工具延迟加载，缺少依赖时仍可降级。
- `LocalExpertAgent` 可以从本地 Markdown 文件降级读取知识。
- `BudgetAgent` 是纯规则 Agent，没有调用外部工具或 LLM。

统一执行范式：

```text
build params
-> emit tool_called
-> invoke tool
-> collect artifact
-> emit tool_completed/tool_failed
-> return AgentExecution
```

必须能回答：

1. Agent、Tool、Provider 分别应该承担什么职责？
2. 为什么 Agent 不应该直接发送 HTTP 请求？
3. `tool_artifacts` 中的状态、数据源、错误和结果数据对排障有什么价值？
4. `ToolResult` 如何避免错误提示字符串被误判为成功？
5. 当前 Agent 是否真的具备自主推理能力？

关键结论：

当前新领域 Agent 本质上是“有统一生命周期的领域工具执行器”，自主推理能力较弱。LLM 主要用于 `/chat` 意图解析，新的 Supervisor 行程生成没有真正调用 LLM。

### 第 4 阶段：理解 Provider 和横切能力

阅读：

1. `apis/base.py`
2. `apis/providers/amap.py`
3. `apis/providers/tianxing.py`
4. `apis/providers/qweather.py`
5. `apis/providers/mock_price.py`
6. `core/retry.py`
7. `core/cache.py`
8. `core/config.py`

调用链：

```text
Domain Agent
-> LangChain Tool
-> Provider.search()
-> cache_api_call()
-> retry_api_call()
-> HTTP API
```

必须能回答：

1. 为什么 Provider 返回统一的 `list[dict]`？
2. 重试应该放在 Agent、Tool 还是 Provider 层？
3. 哪些异常适合重试，哪些业务错误不适合重试？
4. 航班和天气为什么不应该使用过长缓存？
5. MockPriceProvider 为什么只能叫参考价格？

本轮已修复：

- 和风天气请求已映射到 `3d/7d` 固定预报档位。
- OpenAI Key 改为按能力使用时校验，国内 Provider 不再被无关配置耦合。
- 新领域 Tool 使用结构化 `ToolResult`，API Key 缺失和 Provider 故障会传播为降级状态。

仍需处理：

- 航班和铁路缓存 TTL 当前是 24 小时，不适合高时效数据。
- Provider 还缺少契约测试、限流处理和统一错误码。

### 第 5 阶段：理解 API、任务和 SSE

阅读：

1. `backend/api_server.py`
2. `frontend/streamlit_app.py`

重点接口：

- `POST /plan`
- `GET /status/{task_id}`
- `GET /stream/{task_id}`
- `GET /download/{task_id}`
- `POST /chat`

重点理解：

- API 先返回 `task_id`，实际规划在后台执行。
- `append_task_event()` 为事件分配递增序号。
- 并发 Agent 会同时回调事件，因此 API 使用线程锁保护任务状态。
- SSE 按事件序号增量推送。
- 前端流式连接失败后退回轮询。

必须能回答：

1. 为什么规划接口不能同步等待全部 Agent 完成？
2. SSE 和 WebSocket 在这个项目中的取舍是什么？
3. 为什么事件必须带 `seq`？
4. Redis Stream 和内存事件列表分别解决什么问题？
5. 服务重启后，内存任务状态如何恢复？

现存问题：

- `api_server.py` 同时保留旧运行函数、简化模式和新 Supervisor，文件过大。
- CORS 当前允许任意来源。
- 没有任务取消、任务重试、事件查询和 Artifact 查询接口。
- `tasks_state.json` 是单进程本地文件方案，不适合多实例部署。
- 没有鉴权、限流、请求幂等和任务队列。

### 第 6 阶段：理解持久化

阅读：

1. `backend/storage/persistence.py`
2. `backend/tests/test_persistence_integration.py`

存储职责：

- Redis：任务元信息、请求快照、结果快照、短期记忆、事件流。
- PostgreSQL：最终结果、Markdown、Agent 参与信息、缺失 Agent。

必须能回答：

1. 为什么热状态适合 Redis，最终归档适合 PostgreSQL？
2. Redis Key 为什么需要 TTL？
3. PostgreSQL 为什么使用 `task_id` 唯一约束和 Upsert？
4. Redis 不可用时系统是否还能执行？
5. 当前 `memory_recall` 为什么不算真正的历史记忆？

关键结论：

当前只有“结果写入”闭环，没有“历史召回 -> 参与新规划”的闭环。`memory_recall` 只是初始化字典，不会读取 Redis、PostgreSQL 或用户画像。

### 第 7 阶段：理解 Local Expert 和 RAG

阅读：

1. `backend/skills/local_expert/SKILL.md`
2. `backend/skills/local_expert/skill.py`
3. `backend/tools/local_rag.py`
4. `backend/tools/travel_tools.py`
5. `SimpleExample-knowledge-rag/*.md`

重点理解：

- 优先城市使用 Chroma RAG。
- RAG 失败或无命中时回退搜索。
- 搜索再失败时使用结构化默认建议。
- 新 Supervisor 仍通过旧 `travel_tools.py` 调用 `local_expert_skill`。

必须能回答：

1. 为什么 RAG 必须按城市过滤？
2. 如何避免跨城市知识污染？
3. 检索结果为什么需要保留来源标签？
4. 当前是否真的有 rerank？
5. Chroma Cloud 不可用时系统如何降级？

## 5. 当前最重要的可靠性缺口

### 已完成：完成状态可信化

- Tool 返回结构化 `ToolResult`。
- Agent 明确区分 `completed`、`degraded`、`failed`。
- `planning_complete` 同时检查缺失输入、缺失 Agent 和降级 Agent。
- Reflection 和 API 返回 `completion_status=complete/partial`。
- 降级结果仍可参与报告生成，但不会再伪装成完整结果。

### P0：行程没有真正消费领域约束

当前 `_itinerary()` 只根据天数生成通用模板，没有读取景点地址、天气日期、酒店位置、交通时间和预算结果做实际排程。

正确改造：

- Agent 输出改为 Pydantic 结构。
- Collector 形成统一候选数据。
- Itinerary Agent 根据时间、地点、天气和预算生成结构化日程。
- Reflection 校验时间冲突、跨区折返和预算超限。

### P0：缺少可复现运行环境

仓库没有 `requirements.txt`、`pyproject.toml`、Dockerfile 或 CI。

正确改造：

- 使用 `pyproject.toml` 锁定依赖和 Python 版本。
- 增加开发、测试、生产依赖分组。
- 增加 Docker Compose 启动 API、Redis、PostgreSQL。
- 增加 GitHub Actions 执行静态检查和测试。

### P1：没有 Supervisor Checkpoint

LangGraph 只执行内存状态图，没有 Checkpointer。进程中断后无法从图节点恢复。

正确改造：

- 为每个任务使用稳定 `thread_id`。
- 开发环境接入 SQLite Checkpointer。
- 生产环境使用 PostgreSQL Checkpointer。
- 设计幂等节点，避免恢复后重复调用外部 API。

### P1：缺少真实集成验收

现有测试主要覆盖路由、API 契约和单 Agent 失败隔离，没有验证：

- 真实 Provider 响应 Schema。
- Redis 状态和事件一致性。
- PostgreSQL Upsert 与恢复。
- SSE 断线重连。
- FastAPI 到 Supervisor 的完整任务链路。
- Streamlit 到 FastAPI 的实际交互。

### P1：可观测性不足

当前可以看到事件和日志，但缺少：

- 任务、Agent、Provider 耗时指标。
- 成功率、降级率、重试次数。
- Token 与模型成本。
- Trace ID 贯穿 API、Agent 和 Provider。
- 告警与日志脱敏验证。

## 6. 10 天学习计划

### 第 1 天：画出全链路

- 阅读 README 和需求文档。
- 手画从 `/plan` 到最终 Markdown 的调用链。
- 输出一张模块职责图。

验收：不看代码解释一次完整请求如何流转。

### 第 2 天：状态和路由

- 阅读 `state.py`、`router.py`。
- 跑 Supervisor 单元测试。
- 新增两个路由边界测试。

验收：能独立修改 Agent 选择规则。

### 第 3 天：Supervisor 图

- 阅读 `runtime.py`。
- 给每个节点记录输入字段和输出字段。
- 比较 LangGraph 路径与 `_run_pipeline()` 路径。

验收：能解释图节点、状态、边和并发的关系。

### 第 4 天：领域 Agent

- 阅读 `domain_agents.py`。
- 跟踪 Hotel Agent 完整调用链。
- 新增一个 Restaurant Agent。

验收：能按现有模式新增 Agent、Tool 和 Provider。

### 第 5 天：Provider、缓存和重试

- 阅读 `apis/providers` 和 `core`。
- 复盘天气预报档位映射实现。
- 为 Provider 写 Mock 单元测试。

验收：能解释哪些错误应该重试、缓存多久。

### 第 6 天：API 和 SSE

- 阅读 `api_server.py` 中任务创建、状态、事件流和结果保存部分。
- 使用 curl 或 API 客户端模拟任务。
- 画出任务状态机。

验收：能解释后台任务、SSE、轮询和 Redis Stream 的关系。

### 第 7 天：持久化和记忆

- 阅读 `persistence.py`。
- 启动 Redis 和 PostgreSQL。
- 跑持久化集成测试。

验收：能从 Redis 和 PostgreSQL 中找到同一任务的数据。

### 第 8 天：RAG

- 阅读 Local Expert Skill。
- 理解城市过滤、来源标签和降级链。
- 为一个新城市添加知识文件。

验收：能解释 RAG、搜索回退和纯模型回答的差异。

### 第 9 天：可靠性改造

- 阅读结构化 `ToolResult` 和状态传播实现。
- 跟踪一次 API Key 缺失如何传播为 `completion_status=partial`。
- 为失败、空结果和超时继续增加边界测试。

验收：任务状态能准确区分完整、部分完成和失败。

### 第 10 天：面试讲解

- 用 3 分钟讲项目背景和架构。
- 用 5 分钟讲一个技术难点。
- 用 10 分钟讲可靠性缺口和下一步改造。

验收：不夸大实现，能明确区分已完成、设计中和待改造。

## 7. 建议优先完成的改造任务

按收益排序：

1. 增加 `pyproject.toml` 和完整运行说明。
2. 引入结构化 `AgentResult` 和 `ItineraryPlan`，继续扩展已完成的 `ToolResult`。
3. 用领域结果真正生成逐日行程。
4. 接入 LangGraph Checkpointer。
5. 增加 Provider、API、SSE、Redis、PostgreSQL 集成测试。
6. 拆分过大的 `api_server.py`。
7. 增加任务重试、取消、事件和 Artifact 查询接口。
8. 增加 Docker Compose、CI、指标和 Trace。

已完成：结构化 `ToolResult`、降级状态语义、天气档位映射和预算口径解析。

## 8. 面试表达边界

可以说：

- 设计并实现 Supervisor 多 Agent 架构。
- 根据用户约束动态选择领域 Agent。
- 使用线程池并发执行独立领域查询。
- 通过 Tool / Provider 分层隔离 Agent 与外部 API。
- 使用 SSE 返回任务事件，并支持轮询回退。
- 设计 Redis 热状态和 PostgreSQL 结果归档。
- 实现单 Agent 失败隔离和本地知识降级。

暂时不要说：

- 已经达到生产级高可用。
- 已实现完整长期记忆。
- 已实现复杂自主规划和自我修正。
- 已完成真实大规模并发压测。
- 已实现全链路可观测和自动评测。
- 已稳定支持所有国内城市和实时价格。

更准确的表述：

> 当前完成了企业级 Agent 系统的核心工程骨架，并针对真实生产差距设计了 Checkpoint、结构化结果、任务恢复、可观测性和集成测试的后续演进方案。

## 9. 学习完成标准

当你能独立完成以下任务时，说明已经真正掌握项目：

- 不看代码画出全链路架构。
- 修改路由规则并补对应测试。
- 新增一个领域 Agent 和 Provider。
- 解释一次工具失败如何传播到最终任务状态。
- 从 SSE 事件定位失败 Agent 和工具。
- 在 Redis 和 PostgreSQL 中追踪一次任务。
- 指出当前实现中至少 5 个生产风险。
- 能解释结构化结果实现，并完成 Checkpoint 改造或相关测试。
- 用事实回答项目“做了什么”和“还没做什么”。

## 10. 常用命令

当前仓库尚未提供正式依赖清单。依赖环境补齐后，可使用：

```powershell
python -m unittest backend.tests.test_supervisor_runtime -v
python -m pytest backend/tests/test_persistence_integration.py -v
python backend/api_server.py
streamlit run frontend/streamlit_app.py
```

健康检查和接口：

```text
GET  http://localhost:8080/health
POST http://localhost:8080/plan
GET  http://localhost:8080/status/{task_id}
GET  http://localhost:8080/stream/{task_id}
GET  http://localhost:8080/download/{task_id}
```

## 11. 推荐学习资料顺序

仓库内资料按以下顺序阅读：

1. `README.md`
2. `TRIPAI_LEARNING_GUIDE.md`
3. `SUPERVISOR_ENTERPRISE_REQUIREMENTS.md`
4. `IMPLEMENTATION_PROGRESS.md`
5. `backend/tests/test_supervisor_runtime.py`
6. `backend/supervisor/`
7. `backend/agents/domain_agents.py`
8. `backend/tools/` 与 `apis/providers/`
9. `backend/api_server.py`
10. `backend/storage/persistence.py`
11. `backend/skills/local_expert/`
12. `INTERVIEW_QA.md`

说明：`understand-onboard` 需要 `.understand-anything/knowledge-graph.json`，当前仓库没有该图文件，因此本指南基于实际源码、需求文档和测试手工生成。
