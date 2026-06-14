# 旅小智 TripAI — 多轮对话 & 需求修改 技术方案

> 版本: 1.0  
> 日期: 2026-06-15  
> 状态: 待实施

---

## 一、需求分析

### 1.1 当前能力矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| 单次旅行规划 | ✅ 完整 | Plan-Execute 8 阶段流水线，7 个领域 Agent 并行 |
| SSE 流式推送 | ✅ 完整 | 15+ 种事件类型，增量推送 |
| 多轮对话 | ❌ 缺失 | `/chat` 无状态，每轮独立解析 |
| 对话上下文 | ❌ 缺失 | 无 session/conversation 管理 |
| 需求修改 | ❌ 缺失 | 无 refine 接口，`/retry` 只能完全重跑 |
| 增量调整 | ❌ 缺失 | 无法只修改某一部分（如只换酒店） |

### 1.2 目标能力

| # | 用户故事 | 验收标准 |
|---|---------|---------|
| 1 | 用户分多轮逐步描述需求，系统记住上下文 | 第 2 轮能正确合并第 1 轮信息 |
| 2 | 用户对已生成计划提出修改意见 | 返回修改后的计划，只重跑受影响的 Agent |
| 3 | 用户说"换个便宜的酒店" | 只重新执行 hotel_agent + budget_optimizer |
| 4 | 用户说"再加一天行程" | 只重新执行 itinerary_planner + budget_optimizer |
| 5 | 用户可以查看对话历史 | 前端聊天面板展示历史消息 |
| 6 | 会话跨页面刷新保持 | Redis 持久化，24h TTL |

### 1.3 不改的范围

- 7 个领域 Agent 的实现逻辑
- 8 阶段 Plan-Execute 流水线的内部执行
- SSE 流式推送机制
- API Provider 层

---

## 二、架构设计：Plan-Execute + ReAct 混合模式

### 2.1 为什么是混合模式

```
纯 Plan-Execute                   纯 ReAct                    混合模式（采用）
═══════════════                   ════════                    ════════════════
一次性规划全部执行                LLM 反复思考-行动-观察       ReAct 管对话 + Plan-Execute 管执行
❌ 不支持多轮对话                 ❌ 成本高、延迟大            ✅ 各取所长
❌ 不支持增量修改                 ❌ 丢失领域分工              ✅ 最小改动
✅ 高效、可控                    ✅ 天然支持对话修改           ✅ 保留所有现有能力
```

### 2.2 架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        ChatSessionManager                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Redis: session:{id} → {                         │ │
│  │                session_id, user_id,                          │ │
│  │                messages: [...],    ← 对话历史                │ │
│  │                accumulated_facts: {...}, ← 累积的结构化需求   │ │
│  │                active_task_id,                               │ │
│  │                created_at, updated_at                        │ │
│  │              }                                               │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      ReAct 对话循环（新增）                       │
│                                                                    │
│  用户消息 ──→ Thought: 分析意图                                   │
│                    │                                               │
│         ┌──────────┼──────────┬──────────────┐                    │
│         ▼          ▼          ▼              ▼                    │
│    信息补全    创建规划    修改计划        闲聊/帮助               │
│    (追问)     (plan)     (refine)        (直接回复)               │
│         │          │          │              │                    │
│         │          ▼          ▼              │                    │
│         │    Plan-Execute  Delta-Replan      │                    │
│         │    完整流水线    增量重跑           │                    │
│         │          │          │              │                    │
│         └──────────┴──────────┴──────────────┘                    │
│                              │                                    │
│                              ▼                                    │
│                       Observation: 生成回复                       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 意图路由决策树

```
用户输入 → LLM 分析（携带对话历史 + 累积事实）
    │
    ├─ 意图 = "provide_info"（补充需求信息）
    │   → 更新 accumulated_facts
    │   → 检查信息是否完整
    │       ├─ 完整 → 自动触发 plan
    │       └─ 不完整 → 追问缺失字段
    │
    ├─ 意图 = "create_plan"（确认创建）
    │   → 调用 Plan-Execute 完整流水线
    │   → 返回结果
    │
    ├─ 意图 = "modify_plan"（修改已有计划）
    │   → 分析修改范围（哪些 Agent 受影响）
    │   → Delta-Replan：只重跑受影响的 Agent
    │   → 合并结果
    │
    └─ 意图 = "chat"（闲聊/帮助）
        → LLM 直接回复
```

---

## 三、数据模型

### 3.1 ChatSession（新增）

```python
# backend/storage/chat_session.py

@dataclass
class ChatMessage:
    role: str          # "user" | "assistant" | "system"
    content: str
    timestamp: str     # ISO 8601
    metadata: dict     # {intent, extracted_facts, task_id, ...}

@dataclass  
class ChatSession:
    session_id: str
    user_id: str          # 预留，当前可为 "anonymous"
    messages: List[ChatMessage]
    accumulated_facts: dict  # 多轮累积的结构化需求
    active_task_id: Optional[str]
    created_at: str
    updated_at: str
```

### 3.2 累积事实 accumulated_facts

```python
{
    "destination": "杭州",        # 第 1 轮提取
    "start_date": "2026-06-22",   # 第 2 轮补充
    "end_date": "2026-06-25",     # 第 2 轮补充
    "budget_range": "中等预算",    # 第 3 轮补充
    "group_size": 2,
    "interests": ["美食", "历史"],
    "departure": "北京",
    "accommodation_preference": "酒店",
    "transportation_preference": "公共交通",
    "special_requirements": "",
    "missing_fields": ["start_date", "end_date"],  # 仍缺失的字段
    "confidence": 0.85,
}
```

### 3.3 RefineRequest（新增）

```python
class RefineRequest(BaseModel):
    task_id: str
    feedback: str          # 自然语言修改意见，如"换便宜酒店"
    session_id: Optional[str] = None
```

### 3.4 RefineResult（新增）

```python
class RefineResult(BaseModel):
    task_id: str
    original_task_id: str
    modified_agents: List[str]   # 被重跑的 Agent 列表
    unchanged_agents: List[str]  # 未变动的 Agent 列表
    result: dict                 # 合并后的完整结果
```

---

## 四、API 设计

### 4.1 改造 `POST /chat`（核心接口）

**改造前**（无状态）:
```
POST /chat  {"message": "我想去杭州"}
→ 返回澄清问题，不保存上下文
```

**改造后**（有状态）:
```
POST /chat  {"message": "我想去杭州", "session_id": null}
→ 创建 session，返回 {"session_id": "sess_xxx", "clarification": "请问预算和日期？"}

POST /chat  {"message": "预算3000，下周三出发", "session_id": "sess_xxx"}
→ 读取历史上下文，合并信息，返回 {"can_proceed": true, "task_id": "task_xxx"}
```

**返回结构**:
```python
class ChatResponse(BaseModel):
    session_id: str
    intent: str              # "clarify" | "plan_created" | "plan_modified" | "chat"
    message: str             # 人类可读回复
    task_id: Optional[str]   # 如果创建/修改了计划
    extracted_facts: dict    # 当前累积的事实
    missing_fields: List[str]
    can_proceed: bool
```

### 4.2 新增 `POST /tasks/{task_id}/refine`

```
POST /tasks/{task_id}/refine
{
    "feedback": "把酒店换成便宜点的，预算控制在2000以内",
    "session_id": "sess_xxx"
}

→ 200 {
    "task_id": "task_new",
    "original_task_id": "task_old",
    "modified_agents": ["hotel_agent", "budget_optimizer"],
    "unchanged_agents": ["flight_agent", "weather_agent", "attraction_agent", "local_expert"],
    "result": {...}
}
```

### 4.3 新增 `GET /sessions/{session_id}`

```
GET /sessions/{session_id}
→ 返回对话历史 + 累积事实
```

### 4.4 新增 `DELETE /sessions/{session_id}`

```
DELETE /sessions/{session_id}
→ 清除会话（用户主动结束对话）
```

---

## 五、Delta-Replan 机制

### 5.1 修改意图 → Agent 映射

当用户提出修改意见时，LLM 分析需要重跑哪些 Agent：

| 用户输入示例 | 受影响 Agent | 原因 |
|-------------|-------------|------|
| "换个便宜酒店" | hotel_agent, budget_optimizer | 酒店变化 → 预算重新核算 |
| "再加一天" | itinerary_planner, budget_optimizer | 行程天数变化 |
| "不去杭州了，去成都" | 全部 | 目的地变化 → 全链路重算 |
| "改成坐高铁去" | flight_agent, train_agent, budget_optimizer | 交通方式切换 |
| "对海鲜过敏，换个餐厅推荐" | local_expert, itinerary_planner | 餐饮偏好变化 |
| "不要自然风光，改成购物" | attraction_agent, itinerary_planner | 兴趣偏好变化 |

### 5.2 Delta-Replan 执行流程

```python
def delta_replan(original_result, feedback, session_context):
    """
    增量重规划：只重跑受影响的 Agent，其余结果复用。
    """
    # 1. LLM 分析修改意图，确定受影响 Agent
    affected_agents = analyze_modification_intent(feedback, original_result)
    
    # 2. 提取原始 Agent 结果中不变的部分
    unchanged = {
        name: output 
        for name, output in original_result["agent_outputs"].items()
        if name not in affected_agents
    }
    
    # 3. 只对受影响 Agent 执行（复用 SupervisorTravelPlanner 的 dispatcher）
    new_results = execute_agents(affected_agents, session_context)
    
    # 4. 合并结果
    merged = {**unchanged, **new_results}
    
    # 5. 重新生成行程 + 预算核对
    merged = rerun_itinerary_and_budget(merged, session_context)
    
    return merged
```

### 5.3 影响范围分析 Prompt

```python
MODIFICATION_ANALYSIS_PROMPT = """你是一个旅行规划系统的修改意图分析器。

当前计划摘要：
{plan_summary}

用户修改意见：
{feedback}

请分析：哪些 Agent 需要重新执行？

可选的 Agent：
- flight_agent: 航班查询
- train_agent: 铁路查询  
- hotel_agent: 酒店推荐
- attraction_agent: 景点推荐
- weather_agent: 天气分析
- local_expert: 本地攻略
- budget_optimizer: 预算分析
- itinerary_planner: 行程规划

返回 JSON:
{
    "affected_agents": ["hotel_agent", "budget_optimizer"],
    "reason": "用户要求换便宜酒店，只需更新酒店推荐和预算核算",
    "updated_facts": {"budget_range": "经济型"}
}
"""
```

---

## 六、实施计划

### Phase 1: 基础设施（后端）

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 1.1 新增 `ChatSession` 数据模型 | `backend/storage/chat_session.py` | 30min |
| 1.2 新增 `ChatSessionStore`（Redis 实现） | `backend/storage/chat_session.py` | 45min |
| 1.3 新增 `IntentRouter`（ReAct 循环） | `backend/supervisor/intent_router.py` | 1.5h |
| 1.4 重写 `POST /chat` 端点 | `backend/api_server.py` | 1h |
| 1.5 新增 `POST /tasks/{id}/refine` | `backend/api_server.py` | 1h |
| 1.6 新增 `DeltaReplanner` | `backend/supervisor/delta_replanner.py` | 1.5h |
| 1.7 新增 `GET/DELETE /sessions/{id}` | `backend/api_server.py` | 30min |

### Phase 2: 前端

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 2.1 新增聊天面板组件 | `frontend/streamlit_app.py` | 2h |
| 2.2 流式打字效果 | `frontend/streamlit_app.py` | 1h |
| 2.3 计划修改交互（气泡内操作） | `frontend/streamlit_app.py` | 1.5h |
| 2.4 Session 持久化（页面刷新保持） | `frontend/streamlit_app.py` | 30min |

### Phase 3: 测试 & 打磨

| 任务 | 工作量 |
|------|--------|
| 3.1 端到端测试：多轮对话流程 | 1h |
| 3.2 端到端测试：需求修改流程 | 1h |
| 3.3 边界情况处理 | 30min |

**总预估**: 约 12 小时

---

## 七、关键 Prompt 设计

### 7.1 意图分析 Prompt

```python
INTENT_ANALYSIS_SYSTEM = """你是旅小智的对话意图分析器。

分析用户消息的意图，分为 4 类：

1. **provide_info**: 用户提供了新的旅行需求信息
   - 提取结构化信息：destination, start_date, end_date, budget, group_size, interests, departure, accommodation, transportation
   - 更新 accumulated_facts

2. **create_plan**: 用户确认要生成旅行计划
   - 检查 accumulated_facts 是否完整（至少需要 destination + 日期）
   - 完整则标记 can_proceed=true

3. **modify_plan**: 用户想修改已有计划
   - 分析需要修改哪些方面（酒店/航班/行程/预算等）
   - 提取修改后的参数

4. **chat**: 闲聊、帮助、问候等，直接回复

当前已累积的信息：
{accumulated_facts}

对话历史：
{chat_history}

返回 JSON:
{{
    "intent": "provide_info|create_plan|modify_plan|chat",
    "extracted": {{"destination": "杭州", ...}},
    "updated_facts": {{...}},       // 合并后的完整 accumulated_facts
    "missing_fields": ["start_date"],
    "clarification": "请问您计划什么时候出发？",
    "can_proceed": false,
    "confidence": 0.85,
    "direct_reply": "你好！我是旅小智..."  // intent=chat 时使用
}}
"""
```

### 7.2 计划摘要生成 Prompt（供 refine 使用）

```python
PLAN_SUMMARY_PROMPT = """将以下旅行计划结果总结为简短摘要：

{plan_result}

只保留关键信息：目的地、日期、预算、酒店名称和价格、主要景点、航班信息。
不超过 300 字。"""
```

---

## 八、文件结构变更

```
TripAI/
├── backend/
│   ├── api_server.py              ← 修改：/chat, 新增 /refine, /sessions
│   ├── storage/
│   │   ├── chat_session.py        ← 新增：ChatSession 模型 + Redis 存储
│   │   └── persistence.py         ← 不变
│   ├── supervisor/
│   │   ├── runtime.py             ← 基本不变
│   │   ├── intent_router.py       ← 新增：ReAct 意图路由
│   │   ├── delta_replanner.py     ← 新增：增量重规划
│   │   ├── prompts.py             ← 修改：新增意图分析/修改分析 prompt
│   │   ├── state.py               ← 修改：新增 ChatSessionState
│   │   └── router.py              ← 不变
│   └── ...
├── frontend/
│   └── streamlit_app.py           ← 修改：新增聊天面板 + 修改交互
└── docs/
    └── CHAT_REFINE_TECH_SPEC.md   ← 本文档
```

---

## 九、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| LLM 意图分析不准确 | 路由到错误分支 | 低 confidence 时追问确认；允许用户手动选择操作 |
| Delta-Replan 影响范围判断错误 | 少重跑 Agent 导致结果不一致 | 修改涉及 destination/duration 时强制全量重跑 |
| Redis 不可用 | 对话历史丢失 | 降级为无状态模式（等同当前行为），日志告警 |
| 对话历史过长 | Token 超限、成本增加 | 只保留最近 10 轮消息；用 plan_summary 压缩历史计划 |

---

## 十、验收清单

- [ ] 用户分 3 轮输入"杭州"、"预算3000"、"下周三出发，2人"，第 3 轮自动创建计划
- [ ] 用户说"把酒店换成300以内的"，只更新 hotel + budget，其他 Agent 结果不变
- [ ] 用户说"再加一天行程"，只更新 itinerary + budget
- [ ] 用户说"不去杭州了，去成都"，全量重新规划
- [ ] 对话历史在页面刷新后保持（24h 内）
- [ ] SSE 流式推送在 plan 和 refine 中均正常工作
- [ ] 降级模式：Redis 不可用时回退为无状态模式
