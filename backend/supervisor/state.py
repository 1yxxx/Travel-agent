"""
Supervisor 工作流的共享状态契约。

定义 Supervisor 全局状态和 Agent 执行结果的类型结构。
遵循需求文档 §9 的状态模型设计：
- SupervisorState：跨 Agent 全局状态，不直接暴露给子 Agent
- AgentExecution：单个 Agent 的本地执行结果，保留 tool_artifacts 用于排障
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict

# ======================== 类型别名 ========================

# 事件回调函数类型：接收事件字典，无返回值
EventCallback = Optional[Callable[[Dict[str, Any]], None]]

# Agent 执行状态：completed=正常完成, degraded=降级完成, failed=失败
AgentStatus = Literal["completed", "degraded", "failed"]

# 任务整体状态：processing=执行中, completed=完整完成, partial=部分完成, failed=失败
TaskStatus = Literal["processing", "completed", "partial", "failed"]


# ======================== Agent 执行结果 ========================

class AgentExecution(TypedDict, total=False):
    """
    单个领域 Agent 的执行结果。

    对应需求文档 §9.2 SubAgentState，记录单次 Agent 执行的完整生命周期：
    - 接收的子任务
    - 工具调用产物（tool_artifacts，用于排障和追踪）
    - 最终输出和状态

    字段说明：
        status: 执行状态（completed / degraded / failed）
        subtask: 原始子任务指令文本
        response: 最终自然语言响应（给用户的）
        output: 结构化输出（给下游处理的）
        tool_artifacts: 工具调用的完整记录列表，包含参数、结果、耗时等
        error: 错误信息（如果失败或降级）
        degraded: 是否为降级结果（True 表示使用了备选方案）
        started_at: 开始执行的时间戳（ISO 8601）
        finished_at: 完成执行的时间戳（ISO 8601）
        retry_count: 重试次数
        llm_calls: LLM 调用次数
    """
    status: AgentStatus
    subtask: str
    response: str
    output: str
    tool_artifacts: List[Dict[str, Any]]
    error: str
    degraded: bool
    started_at: str
    finished_at: str
    retry_count: int
    llm_calls: int


# ======================== Supervisor 全局状态 ========================

class SupervisorState(TypedDict, total=False):
    """
    Supervisor 编排器的全局共享状态。

    对应需求文档 §9.1 SupervisorState，贯穿整个 8 阶段流水线：
    memory_recall → intent_parser → dispatcher → collector →
    itinerary → reflection → summarizer → memory_store

    设计原则：
    - SupervisorState 负责跨 Agent 的全局协调状态
    - 子 Agent 通过 facts 获取共享上下文，不直接读写 SupervisorState
    - 工具结果保留在 agent_results 中，包含 tool_artifacts 用于排障

    字段说明：
        task_id: 任务唯一标识（UUID）
        trace_id: 追踪 ID，用于 LangSmith/OpenTelemetry 关联
        user_request: 用户原始请求（字典格式）
        extracted_facts: 意图解析提取的结构化事实
        missing_info: 缺失的关键信息字段列表
        clarification_question: 需要向用户澄清的问题（如果信息不足）
        selected_agents: 本次任务选中的领域 Agent 列表
        subtasks: 分配给各 Agent 的子任务 [{agent: str, instruction: str}]
        agent_results: 各 Agent 的执行结果 {agent_name: AgentExecution}
        collector_output: 收集器汇总后的归一化输出
        itinerary_output: 逐日行程文本
        reflection_output: 质量反思结果
        final_output: 最终旅行方案（Markdown）
        task_status: 任务整体状态
        events: SSE 事件列表
        memory_context: 短期记忆上下文
        error_history: 错误历史记录（用于排障）
        retry_count: 全局重试计数
    """
    # ---- 任务标识 ----
    task_id: str
    trace_id: str  # 分布式追踪 ID，用于 LangSmith/OpenTelemetry 关联

    # ---- 用户输入与意图 ----
    user_request: Dict[str, Any]
    extracted_facts: Dict[str, Any]
    missing_info: List[str]
    clarification_question: str  # 需要向用户澄清的问题

    # ---- Agent 调度 ----
    selected_agents: List[str]
    subtasks: List[Dict[str, str]]

    # ---- 执行结果 ----
    agent_results: Dict[str, AgentExecution]
    collector_output: Dict[str, Any]
    itinerary_output: str
    reflection_output: Dict[str, Any]
    final_output: str

    # ---- 状态与追踪 ----
    task_status: str
    events: List[Dict[str, Any]]
    memory_context: Dict[str, Any]
    error_history: List[Dict[str, Any]]  # 错误历史，记录每次失败的时间、位置、原因
    retry_count: int  # 全局重试次数


# ======================== Agent 名称常量 ========================

# 领域 Agent：负责具体领域的数据查询和分析
DOMAIN_AGENT_NAMES = (
    "flight_agent",      # 航班查询
    "train_agent",       # 高铁/火车查询
    "hotel_agent",       # 酒店检索
    "attraction_agent",  # 景点推荐
    "weather_agent",     # 天气查询
    "local_expert",      # 本地知识和在地建议
)

# 后处理 Agent：在领域 Agent 结果汇总后串行执行
POST_PROCESS_AGENT_NAMES = (
    "budget_optimizer",   # 预算分析与核对
    "itinerary_planner",  # 逐日行程整合
)
