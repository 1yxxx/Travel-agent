# 简历审计结果

## 一句话结论

你的简历前半段有真实后端实习和 RAG 项目支撑，基础并不弱；当前最拖后腿的是 `社区笔记` 这一段过于常规，无法支撑你在 Agent / AI 应用方向的差异化。没有给出 JD，因此下面是通用版优化，重点提升“后端 + Agent/RAG 工程化”叙事，不等同于针对具体岗位的定制投递版。

## 关键问题

- 问题：项目线割裂，实习写了企业系统和 RAG，项目却落回常规微服务社区项目。
  影响：面试官会默认你 AI/Agent 只是接触过，真正能打的仍是普通 CRUD/微服务。
  修改建议：用当前 `TripAI` 项目替换 `社区笔记`，把个人项目线统一到“后端工程化 + Agent/RAG”。

- 问题：`社区笔记` 属于高频玩具题材，且你的写法集中在通用中间件堆栈。
  影响：容易和大量校招/实习简历同质化，区分度低。
  修改建议：换成能体现任务编排、流式反馈、状态管理、知识增强和降级设计的多 Agent 项目。

- 问题：技能栏大量使用“了解”，项目证明力主要靠实习，个人项目未承接这一点。
  影响：会显得技术面广但深度不够，尤其在 Agent 方向缺少自己的工程实现闭环。
  修改建议：让项目描述证明 LangGraph、FastAPI、Redis、PostgreSQL、RAG、SSE 这些能力，而不是只在技能栏列名词。

## 价值提炼

### 当前项目可识别的交付物

- 基于 LangGraph 的多 Agent 旅行规划流程，包含 `travel_advisor`、`weather_analyst`、`budget_optimizer`、`local_expert`、`itinerary_planner` 等角色。
- FastAPI 后端服务，提供 `/plan`、`/status/{task_id}`、`/stream/{task_id}`、`/download/{task_id}`、`/chat` 等接口。
- Redis 状态存储层，覆盖任务状态、事件流和短期记忆。
- PostgreSQL 结果落库层，保存最终规划结果、参与 Agent 信息和 Markdown 结果。
- 本地知识增强链路，结合 `skill + RAG`、DuckDuckGo 搜索和 MCP 天气工具。
- 失败降级与回退逻辑，外部工具或 LLM 调用异常时仍可返回兜底规划结果。

### 可识别结果

- 将“调用大模型生成结果”推进为“可编排、可追踪、可回放、可流式返回”的后端系统。
- 让复杂任务具备多角色拆分、状态持久化和接口化交付能力，而不是单次脚本运行。
- 具备明显的 Agent 工程化叙事，能直接承接后端 / AI 应用 / Agent 平台类面试。

### 缺失但建议补充的量化点

- [量化指标待补：例如单次任务平均耗时、SSE 首包时间、并发 Agent 数量]
- [量化指标待补：例如知识库规模、城市知识条目数、RAG 检索 top_k 或文档数]
- [量化指标待补：例如异常回退覆盖的工具类型、失败后可用率改善]

## 修改策略

- 保留两段实习经历不动，它们已经能证明企业后端经验。
- 用 `TripAI` 替换 `社区笔记`，让项目线从“普通微服务”切到“后端 + Agent 工程化”。
- 项目写法不强调“旅游”题材，而强调：
  - 多 Agent 编排
  - API 化与流式输出
  - Redis / PostgreSQL 持久化
  - 本地知识增强
  - 失败降级与可扩展 Provider 思路
- 不编造业务数据，所有暂时没有证据的指标保留占位符。

## 改写后版本

### 个人摘要（建议新增）

`后端开发方向本科生，具备 Java 后端与 Python AI 应用项目经验，实习中参与客诉工单系统重构和企业 RAG 知识库问答系统建设；个人项目中基于 LangGraph、FastAPI、Redis、PostgreSQL 搭建多 Agent 旅行规划系统，关注任务编排、状态管理、流式反馈和知识增强等工程化问题。`

### 项目经验替换版

`2023-09 ~ 2023-12  多 Agent 旅行规划系统  后端开发（个人项目）`

`项目描述：面向复杂旅行规划场景，基于 LangGraph 构建多 Agent 协作流程，提供需求解析、天气分析、预算规划、在地知识检索和行程生成能力，并通过 FastAPI 将规划链路封装为可流式返回、可持久化追踪的后端服务。`

`技术栈：Python、FastAPI、LangGraph、Redis、PostgreSQL、ChromaDB、Streamlit、SSE、OpenAI API、MCP`

1. 设计并实现基于 LangGraph 的多 Agent 规划流程，拆分 `travel_advisor`、`weather_analyst`、`budget_optimizer`、`local_expert`、`itinerary_planner` 等角色，通过状态图编排并发分析与串行整合链路，提升复杂任务的可维护性与扩展性。
2. 搭建 FastAPI 后端接口，提供 `/plan`、`/chat`、`/status`、`/stream`、`/download` 等能力，支持任务提交、状态查询、SSE 流式事件推送和结果文件导出，便于前端接入和任务追踪。
3. 设计 Redis + PostgreSQL 的状态与结果持久化方案，分别用于任务元信息、事件流、短期记忆和最终规划结果存储，支持任务回放、结果追溯和异步处理场景下的数据落盘。
4. 构建本地知识增强链路，结合 `local_expert skill + RAG`、DuckDuckGo 搜索和 MCP 天气工具补充在地信息与实时天气，并围绕检索结果参与最终规划生成。
5. 为工具调用和 LLM 生成增加异常捕获与降级回退逻辑，在天气、搜索或模型调用失败时输出兜底规划结果，降低单点依赖导致的任务中断风险。

### 技能栏改写建议

将当前偏“了解”的技能表述收紧为能被项目和实习证明的版本：

- `Java / Python：具备 Java 后端开发经验，能够使用 Python 搭建 FastAPI 服务及 Agent / RAG 应用。`
- `后端基础：熟悉 MySQL、Redis、消息队列、并发编程和常见缓存一致性问题。`
- `框架与中间件：熟悉 Spring Boot、Spring Cloud、MyBatis，了解 Kafka、RabbitMQ 等消息队列使用场景。`
- `AI 应用开发：具备 LangChain / LangGraph、RAG、向量检索、任务异步化、流式接口和状态持久化实践经验。`

## 证据来源

- 多 Agent 编排与角色定义：[backend/agents/langgraph_agents.py](C:\Users\17133\Documents\TripAI\backend\agents\langgraph_agents.py#L774)
- 并发执行与事件流：[backend/agents/langgraph_agents.py](C:\Users\17133\Documents\TripAI\backend\agents\langgraph_agents.py#L1563)
- FastAPI 接口与 SSE：[backend/api_server.py](C:\Users\17133\Documents\TripAI\backend\api_server.py#L965)
- 流式事件接口：[backend/api_server.py](C:\Users\17133\Documents\TripAI\backend\api_server.py#L1072)
- Redis / PostgreSQL 持久化：[backend/storage/persistence.py](C:\Users\17133\Documents\TripAI\backend\storage\persistence.py#L37)
- 项目总览说明：[README.md](C:\Users\17133\Documents\TripAI\README.md)

## 下一步行动清单

- 立即替换掉原简历中的 `社区笔记` 项目。
- 补 2 到 3 个可验证量化点，哪怕是范围值，也比空白更强。
- 如果目标岗位偏 Java 后端，把这个项目定位成“个人 Agent 工程化项目”，不要让它压过实习主线。
- 如果目标岗位偏 AI 应用 / Agent 平台，可以把这个项目放到项目经验第一位。
