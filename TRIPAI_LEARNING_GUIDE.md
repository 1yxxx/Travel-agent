# TripAI 项目学习指南

> 面向 Python 新手 + AI Agent 开发入门者

---

## 一、这个项目是做什么的？

**TripAI（旅小智）** 是一个 **AI 多智能体旅行规划系统**。

简单说：用户在网页上输入"国庆去成都玩4天，预算4000"，系统会自动拆解任务，并行调度 7 个 AI 智能体去查航班、酒店、景点、天气等信息，最后汇总成一份完整的旅行方案。

### 核心概念解释

| 概念 | 通俗理解 | 在本项目中 |
|------|---------|-----------|
| **Agent（智能体）** | 一个专门负责某类任务的 AI 助手 | 如 FlightAgent 专门查航班 |
| **Supervisor（监督者）** | 指挥多个 Agent 协调工作的"总指挥" | SupervisorTravelPlanner |
| **Tool（工具）** | Agent 用来获取外部数据的能力 | 如 search_flights 调用天行数据 API |
| **Provider（数据提供者）** | 封装了某个外部 API 的访问逻辑 | 如 TianxingFlightProvider |
| **Pipeline（流水线）** | 按固定顺序执行的一系列步骤 | 8 阶段：记忆→解析→调度→汇总→行程→反思→总结→存储 |

---

## 二、系统架构（一张图看懂）

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户 (浏览器)                             │
│                    http://localhost:8501                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│               前端层：frontend/streamlit_app.py                  │
│         提供输入表单、进度展示、结果卡片、文件下载                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP + SSE
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│               API 层：backend/api_server.py (FastAPI)             │
│    /plan（创建任务）  /status（查进度）  /stream（实时事件）          │
│    /download（下载）  /retry（重试）   /cancel（取消）             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│         编排层：backend/supervisor/ + backend/agents/            │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ 1.记忆召回│→│ 2.意图解析│→│ 3.并行调度│→│ 4.结果汇总│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│       │                            │               │             │
│       │              ┌─────────────┤               │             │
│       │              ▼             ▼               ▼             │
│       │       ┌──────────┐  ┌──────────┐   ┌──────────┐        │
│       │       │Flight    │  │Hotel     │   │Budget    │        │
│       │       │Agent     │  │Agent     │   │Agent     │        │
│       │       └──────────┘  └──────────┘   └──────────┘        │
│       │       ┌──────────┐  ┌──────────┐                       │
│       │       │Train     │  │Weather   │   6 个 Agent 并行！    │
│       │       │Agent     │  │Agent     │                       │
│       │       └──────────┘  └──────────┘                       │
│       │       ┌──────────┐  ┌──────────┐                       │
│       │       │Attraction│  │Local     │                       │
│       │       │Agent     │  │Expert    │                       │
│       │       └──────────┘  └──────────┘                       │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ 5.行程生成│→│ 6.质量反思│→│ 7.方案总结│→│ 8.记忆存储│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           工具层：backend/tools/                                  │
│   flight_tool.py  train_tool.py  hotel_tool.py                   │
│   attraction_tool.py  weather_tool.py  local_rag.py             │
│   travel_tools.py  result.py（统一返回格式）                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│         数据接入层：apis/providers/                               │
│   amap.py（高德地图）  tianxing.py（天行数据）                      │
│   qweather.py（和风天气）  mock_price.py（模拟价格）               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP 请求
                           ▼
                    ┌──────────────┐
                    │  外部 API 服务  │
                    │  高德/天行/和风  │
                    └──────────────┘
```

---

## 三、项目目录结构（按学习顺序）

### 🟢 第一梯队：先看这些（理解核心架构）

```
TripAI/
├── core/
│   ├── config.py          ← 所有配置集中管理（API Key、超时、重试等）
│   ├── logging.py         ← 结构化日志（控制台彩色 + 文件 JSON）
│   ├── retry.py           ← API 调用失败自动重试
│   └── cache.py           ← 缓存查询结果，减少 API 调用
│
├── backend/supervisor/
│   ├── state.py           ← 全局状态定义（任务ID、Agent结果、事件列表等）
│   ├── router.py          ← 动态路由（决定用哪些 Agent、生成子任务）
│   ├── runtime.py         ← ★核心★ 8 阶段流水线编排器
│   └── prompts.py         ← 所有 LLM 提示词集中管理
│
├── backend/agents/
│   └── domain_agents.py   ← ★核心★ 7 个领域 Agent 的实现
│
├── backend/tools/
│   └── result.py          ← 统一工具返回格式（success/degraded/failed）
│
├── apis/
│   └── base.py            ← Provider 抽象基类
```

### 🟡 第二梯队：再看这些（理解外部数据接入）

```
├── apis/providers/
│   ├── amap.py            ← 高德地图（酒店POI + 景点POI）
│   ├── tianxing.py        ← 天行数据（航班 + 高铁）
│   ├── qweather.py        ← 和风天气（3天/7天预报）
│   └── mock_price.py      ← 模拟酒店价格（真实携程API需企业资质）
│
├── backend/tools/
│   ├── flight_tool.py     ← 航班搜索工具
│   ├── train_tool.py      ← 高铁搜索工具
│   ├── hotel_tool.py      ← 酒店搜索工具
│   ├── attraction_tool.py ← 景点搜索工具
│   ├── weather_tool.py    ← 天气查询工具
│   ├── weather_utils.py   ← 天气工具辅助函数
│   ├── travel_tools.py    ← 综合旅行工具（本地专家、搜索等）
│   └── local_rag.py       ← 本地知识库 Chroma 检索
```

### 🔵 第三梯队：最后看这些（基础设施）

```
├── backend/
│   ├── api_server.py      ← FastAPI 后端服务（所有 API 端点）
│   ├── storage/
│   │   └── persistence.py ← Redis + PostgreSQL 数据持久化
│   ├── skills/
│   │   └── local_expert/
│   │       └── skill.py   ← 本地专家技能包（RAG + 搜索 + 降级）
│   └── tests/
│       └── test_supervisor_runtime.py  ← 22 项单元测试
│
├── frontend/
│   └── streamlit_app.py   ← Streamlit 前端界面
│
└── SimpleExample-knowledge-rag/
    ├── beijing.md         ← 北京本地知识
    ├── shanghai.md        ← 上海本地知识
    ├── guangzhou.md       ← 广州本地知识
    ├── shenzhen.md        ← 深圳本地知识
    └── hangzhou.md        ← 杭州本地知识
```

---

## 四、核心数据流（一次完整的旅行规划是怎么跑的）

### 第 1 步：用户输入

```
用户在网页上填写/输入：
  目的地: 成都
  日期: 2026-08-01 至 2026-08-04
  预算: 4000元
  人数: 2人
  兴趣: 美食, 博物馆
```

### 第 2 步：API 层接收请求

```python
# api_server.py → POST /plan
# 生成 task_id，放入后台任务队列，立即返回 task_id 给用户
# 前端拿到 task_id 后，通过 /stream/{task_id} 实时接收进度
```

### 第 3 步：Supervisor 启动 8 阶段流水线

```
阶段 1: memory_recall    (进度 8%)
        初始化短期记忆上下文，记录当前请求快照

阶段 2: intent_parser    (进度 16%)
        ├─ normalize_request()  → 把请求标准化成统一的事实字典
        ├─ find_missing_info()  → 检查缺少哪些必要信息
        ├─ select_agents()      → 根据出发地/偏好动态选择 Agent
        └─ build_subtasks()     → 给每个选中的 Agent 生成中文指令

阶段 3: dispatcher       (进度 22%-63%)
        用线程池并行执行选中的领域 Agent：
        ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
        │ Flight  │  Train  │  Hotel  │Attraction│Weather │ Local   │
        │ Agent   │  Agent  │  Agent  │  Agent  │ Agent  │ Expert  │
        └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘
             │         │         │         │         │         │
             ▼         ▼         ▼         ▼         ▼         ▼
           并行执行 6 个 Agent，每个 Agent 内部：
           ① build_tool_params(facts) → 构建工具调用参数
           ② invoke_tool(params)      → 调用工具获取数据
           ③ 成功 → 返回结构化结果
           ④ 失败 → 自动降级到 fallback_output

阶段 4: collector         (进度 68%-74%)
        汇总各 Agent 输出 + 串行执行预算分析

阶段 5: itinerary         (进度 84%)
        根据天数生成逐日行程框架

阶段 6: reflection        (进度 91%)
        检查缺失信息、失败 Agent、降级 Agent

阶段 7: summarizer        (进度 97%)
        将所有结果整合为一份 Markdown 旅行方案

阶段 8: memory_store      (进度 100%)
        持久化到 Redis + PostgreSQL + 本地文件
```

### 第 4 步：前端展示结果

```
前端通过 SSE 事件流实时看到：
  ✓ 任务已创建
  ✓ 需求解析完成（选中了 5 个 Agent）
  ✓ Flight Agent 开始执行...
  ✓ Flight Agent 完成 ✅
  ✓ Hotel Agent 开始执行...
  ✓ Hotel Agent 降级 ⚠️（高德API Key未配置）
  ...
  ✓ 旅行方案生成完成 🎉

然后展示最终结果卡片 + Markdown 下载按钮
```

---

## 五、关键设计模式（新手必看）

### 5.1 分层架构（关注点分离）

```
表现层 (frontend/)         → 只负责界面
API 层 (api_server.py)     → 只负责 HTTP 请求/响应
编排层 (supervisor/agents/)→ 只负责调度 Agent
工具层 (tools/)            → 只负责调用外部 API
数据接入层 (apis/)         → 只负责封装 HTTP 调用
横切层 (core/)             → 配置/日志/重试/缓存
持久化层 (storage/)        → 只负责 Redis/PostgreSQL
```

**好处**：改一个层不影响其他层。比如换一个天气数据源，只改 `qweather.py` 即可。

### 5.2 Agent 模式（单一职责）

每个 Agent 只做一件事：
- `FlightAgent` 只查航班，不管酒店
- `HotelAgent` 只查酒店，不管天气
- 各 Agent 之间不直接通信，通过 Supervisor 协调

### 5.3 优雅降级（Graceful Degradation）

```python
# 以天气 Agent 为例，即使 API Key 没配置，系统也不会崩溃：
try:
    result = call_weather_api()  # 尝试调用和风天气
except Exception as e:
    result = fallback_output(e)  # 降级：返回通用建议文本
```

降级结果会被标记为 `degraded`，最终方案中会注明"该维度信息暂不完整"。

### 5.4 Provider 抽象（开闭原则）

```python
class BaseProvider:           # 抽象基类
    def search(self, params):  # 统一接口
        raise NotImplementedError

class AmapHotelProvider(BaseProvider):  # 高德实现
    def search(self, params):
        return call_amap_api(params)

class MockPriceProvider(BaseProvider):  # Mock 实现
    def search(self, params):
        return generate_fake_prices(params)
```

Agent 不关心底层是真实 API 还是 Mock，只要 Provider 实现了 `search()` 接口即可。

---

## 六、Python 新手必备知识点

### 6.1 类型注解（Type Hints）

```python
# 冒号后面是类型，箭头后面是返回值类型
def normalize_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """参数是字典，返回值也是字典"""
    ...

# TypedDict：定义一个字典的"形状"
class SupervisorState(TypedDict, total=False):
    task_id: str          # 必须有一个叫 task_id 的键，值是字符串
    user_request: Dict    # user_request 键的值是一个字典
```

### 6.2 dataclass（数据类）

```python
from dataclasses import dataclass

@dataclass
class ToolResult:
    """比普通类更简洁的数据容器"""
    status: str       # 自动生成 __init__(self, status, ...)
    message: str
    data: dict = None # 有默认值的字段放后面
```

### 6.3 f-string（格式化字符串）

```python
name = "成都"
days = 3
# f 开头的字符串可以直接嵌入变量
text = f"去{name}玩{days}天"
# 结果: "去成都玩3天"
```

### 6.4 列表推导式（List Comprehension）

```python
# 传统写法
result = []
for x in [1, 2, 3]:
    result.append(x * 2)

# 推导式写法（等价，更简洁）
result = [x * 2 for x in [1, 2, 3]]  # [2, 4, 6]

# 带条件的推导式
evens = [x for x in [1, 2, 3, 4] if x % 2 == 0]  # [2, 4]
```

### 6.5 异常处理（try/except）

```python
try:
    result = risky_operation()
except ConnectionError:
    # 网络错误 → 重试
    result = retry()
except Exception as e:
    # 其他错误 → 降级
    result = fallback(str(e))
```

### 6.6 线程池（并行执行）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

# 创建线程池（最多 6 个线程同时运行）
with ThreadPoolExecutor(max_workers=6) as executor:
    # 提交 6 个任务
    future1 = executor.submit(flight_agent.execute, ...)
    future2 = executor.submit(hotel_agent.execute, ...)
    ...
    
    # as_completed: 谁先完成就先处理谁
    for future in as_completed([future1, future2, ...]):
        result = future.result()  # 获取返回值
```

---

## 七、学习路线建议

### 第 1 天：理解"一张图"
1. 读本指南 §二（系统架构图）
2. 读 `core/config.py`（理解配置怎么管的）
3. 读 `backend/supervisor/state.py`（理解状态怎么定义的）

### 第 2 天：理解"一条链路"
4. 读 `backend/tools/result.py`（理解工具返回格式）
5. 读 `apis/base.py`（理解 Provider 抽象）
6. 读 `apis/providers/qweather.py`（看一个真实的 Provider 实现）

### 第 3 天：理解"一个 Agent"
7. 读 `backend/agents/domain_agents.py` 中的 `WeatherAgent`（最简单的 Agent）
8. 读 `backend/tools/weather_tool.py`（Agent 调用的工具）
9. 读 `backend/agents/domain_agents.py` 中的 `BaseDomainAgent`（Agent 基类）

### 第 4 天：理解"编排"
10. 读 `backend/supervisor/router.py`（动态路由逻辑）
11. 读 `backend/supervisor/runtime.py`（8 阶段流水线）
12. 读 `backend/supervisor/prompts.py`（LLM 提示词管理）

### 第 5 天：理解"基础设施"
13. 读 `backend/storage/persistence.py`（Redis + PostgreSQL）
14. 读 `backend/api_server.py`（FastAPI 端点）
15. 读 `backend/tools/local_rag.py`（Chroma 知识检索）
16. 跑一遍测试：`py -m backend.tests.test_supervisor_runtime`

---

## 八、快速运行

```bash
# 1. 安装依赖
pip install fastapi uvicorn streamlit pydantic-settings loguru redis psycopg langgraph

# 2. 配置环境变量（创建 .env 文件）
OPENAI_API_KEY=your_key
QWEATHER_API_KEY=your_key  # 可选
AMAP_API_KEY=your_key      # 可选

# 3. 启动后端
cd backend
py api_server.py
# → http://localhost:8080/docs 可查看 API 文档

# 4. 启动前端（新终端）
cd frontend
streamlit run streamlit_app.py
# → http://localhost:8501

# 5. 运行测试
py -m backend.tests.test_supervisor_runtime
```

---

## 九、常见问题

**Q: 没有 API Key 能跑吗？**
A: 能。系统有完整的降级机制。没有和风天气 Key → 返回通用天气建议。没有高德 Key → 返回城市名+通用建议。核心编排逻辑不依赖外部 API。

**Q: LangGraph 是什么？必须装吗？**
A: LangGraph 是 LangChain 的工作流编排库。不必须——如果没装，系统自动回退到纯 Python 模式，功能完全一致。

**Q: 测试怎么跑？**
A: `py -m backend.tests.test_supervisor_runtime`，当前 22 项全部通过。

**Q: 怎么新增一个 Agent？**
A: 
1. 在 `domain_agents.py` 中继承 `BaseDomainAgent`
2. 设置 `name`、`tool_module`、`tool_name`
3. 实现 `build_tool_params()` 方法
4. 在 `build_default_agent_registry()` 中注册
5. 在 `router.py` 的 `CAPABILITY_ALIASES` 中添加别名
6. 在 `prompts.py` 的 `AGENT_DISPLAY_NAMES` 中添加展示名称
