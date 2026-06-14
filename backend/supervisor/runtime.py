"""
Supervisor 工作流运行时 —— 支持 LangGraph 状态图或纯 Python 顺序执行。

核心职责（需求文档 §10）：
1. 管理 8 阶段流水线：memory_recall → intent_parser → dispatcher →
   collector → itinerary → reflection → summarizer → memory_store
2. 协调领域 Agent 的并行执行
3. 可选 LLM 增强：意图解析、质量反思、方案总结
4. Redis 短期记忆读写

两种运行模式：
- LangGraph 模式（推荐）：编译为 StateGraph，支持检查点和流式
- 纯 Python 模式（回退）：顺序执行，零额外依赖
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

# 导入领域 Agent 注册表
try:
    from backend.agents.domain_agents import build_default_agent_registry
except ImportError:
    from agents.domain_agents import build_default_agent_registry  # type: ignore

from .router import (
    build_clarification_prompt,
    build_subtasks,
    find_missing_info,
    normalize_request,
    select_agents,
)
from .state import EventCallback, SupervisorState

# 导入集中式提示词（可选 LLM 增强）
try:
    from .prompts import (
        build_intent_parse_messages,
        build_reflection_messages,
        build_summarizer_messages,
    )
    _PROMPTS_AVAILABLE = True
except ImportError:
    _PROMPTS_AVAILABLE = False


class SupervisorTravelPlanner:
    """
    动态多 Agent 旅行规划器 —— Supervisor 架构的核心编排器。

    兼容现有 API 契约，同时支持 LangGraph 和纯 Python 两种执行模式。

    使用示例：
        planner = SupervisorTravelPlanner(use_langgraph=True)
        result = planner.run_travel_planning(
            {"destination": "成都", "start_date": "2026-07-01", ...},
            event_callback=my_callback,
        )
    """

    def __init__(
        self,
        agent_registry: Optional[Dict[str, Any]] = None,
        *,
        use_langgraph: bool = True,
    ) -> None:
        """
        初始化 Supervisor。

        Args:
            agent_registry: Agent 注册表 {name: agent_instance}，默认使用内置注册表
            use_langgraph: 是否使用 LangGraph StateGraph 编译执行
        """
        self.agent_registry = agent_registry or build_default_agent_registry()
        self.graph = self._build_graph() if use_langgraph else None
        self._event_callback: EventCallback = None

    # ======================== 主入口 ========================

    def run_travel_planning(
        self,
        travel_request: Dict[str, Any],
        event_callback: EventCallback = None,
    ) -> Dict[str, Any]:
        """
        执行一次完整的旅行规划任务。

        这是对外的唯一入口，兼容现有 API 契约。
        内部通过 LangGraph StateGraph 或纯 Python 管道执行。

        Args:
            travel_request: 用户旅行请求字典
            event_callback: SSE 事件回调函数

        Returns:
            包含 travel_plan、agent_outputs、short_term_memory 等字段的结果字典
        """
        # 初始化全局状态
        state: SupervisorState = {
            "task_id": str(travel_request.get("task_id") or uuid.uuid4()),
            "trace_id": str(uuid.uuid4())[:8],  # 短 trace_id 用于日志关联
            "user_request": dict(travel_request),
            "extracted_facts": {},
            "missing_info": [],
            "clarification_question": "",
            "selected_agents": [],
            "subtasks": [],
            "agent_results": {},
            "collector_output": {},
            "itinerary_output": "",
            "reflection_output": {},
            "final_output": "",
            "task_status": "processing",
            "events": [],
            "memory_context": {},
            "error_history": [],
            "retry_count": 0,
        }
        self._event_callback = event_callback

        try:
            # 根据是否安装了 LangGraph 选择执行模式
            final_state = (
                self.graph.invoke(state)
                if self.graph is not None
                else self._run_pipeline(state)
            )
            return self._build_api_result(final_state)
        except Exception as exc:
            # 全局异常兜底：任何阶段失败都返回部分结果
            self._emit(
                "task_failed",
                f"Supervisor 执行失败: {exc}",
                100,
                status="failed",
            )
            return {
                "success": False,
                "error": f"Supervisor 执行失败: {exc}",
                "travel_plan": {},
                "agent_outputs": {},
                "expected_agents": [],
                "missing_agents": [],
                "planning_complete": False,
                "total_iterations": 0,
            }
        finally:
            self._event_callback = None

    # ======================== LangGraph 图构建 ========================

    def _build_graph(self) -> Any:
        """
        构建 LangGraph StateGraph。

        尝试导入 langgraph，如果不可用则返回 None（回退到纯 Python 模式）。

        图结构（需求文档 §10.1）：
        memory_recall → intent_parser → dispatcher → collector →
        itinerary → reflection → summarizer → memory_store → END
        """
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        # 创建状态图
        workflow = StateGraph(SupervisorState)

        # 注册 8 个节点
        workflow.add_node("memory_recall", self._memory_recall)
        workflow.add_node("intent_parser", self._intent_parser)
        workflow.add_node("dispatcher", self._dispatcher)
        workflow.add_node("collector", self._collector)
        workflow.add_node("itinerary", self._itinerary)
        workflow.add_node("reflection", self._reflection)
        workflow.add_node("summarizer", self._summarizer)
        workflow.add_node("memory_store", self._memory_store)

        # 顺序边：严格按照流水线执行
        workflow.set_entry_point("memory_recall")
        workflow.add_edge("memory_recall", "intent_parser")
        workflow.add_edge("intent_parser", "dispatcher")
        workflow.add_edge("dispatcher", "collector")
        workflow.add_edge("collector", "itinerary")
        workflow.add_edge("itinerary", "reflection")
        workflow.add_edge("reflection", "summarizer")
        workflow.add_edge("summarizer", "memory_store")
        workflow.add_edge("memory_store", END)

        return workflow.compile()

    def _run_pipeline(self, state: SupervisorState) -> SupervisorState:
        """
        纯 Python 顺序执行管道（LangGraph 不可用时的回退方案）。

        按顺序执行 8 个节点，与 LangGraph 图的行为完全一致。
        """
        for node in (
            self._memory_recall,
            self._intent_parser,
            self._dispatcher,
            self._collector,
            self._itinerary,
            self._reflection,
            self._summarizer,
            self._memory_store,
        ):
            state = node(state)
        return state

    # ======================== 阶段 1：记忆召回 ========================

    def _memory_recall(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 1：短期记忆初始化（进度 8%）。

        初始化当前任务的短期记忆上下文，包括：
        - 请求快照
        - 用户偏好（V1 为空字典，P1 阶段从 Redis 加载历史偏好）

        对应需求文档 §12.1 的热状态层。
        """
        state["memory_context"] = {
            "request_snapshot": dict(state.get("user_request", {})),
            "recalled_preferences": {},  # P1 阶段从 Redis 加载
            "initialized_at": datetime.now().isoformat(),
        }
        self._emit(
            "memory_recalled",
            "短期记忆初始化完成。",
            8,
            agent="supervisor",
        )
        return state

    # ======================== 阶段 2：意图解析 ========================

    def _intent_parser(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 2：需求解析与动态路由（进度 16%）。

        执行步骤：
        1. 调用 router.normalize_request 标准化请求
        2. 调用 router.find_missing_info 识别缺失信息
        3. 调用 router.select_agents 动态选择领域 Agent
        4. 调用 router.build_subtasks 生成子任务指令
        5. 如果信息缺失，生成澄清提示

        设计原则：V1 使用确定性规则，P1 可接入 LLM 增强解析。
        """
        # 标准化请求
        facts = normalize_request(state.get("user_request", {}))
        state["extracted_facts"] = facts

        # 检测缺失信息
        state["missing_info"] = find_missing_info(facts)

        # 如果缺失关键信息，生成澄清提示
        if state["missing_info"]:
            _, clarification = build_clarification_prompt(facts, state["missing_info"])
            state["clarification_question"] = clarification

        # 动态选择 Agent
        state["selected_agents"] = select_agents(facts)

        # 生成子任务指令
        state["subtasks"] = build_subtasks(facts, state["selected_agents"])

        self._emit(
            "intent_parsed",
            "需求解析和动态路由完成。",
            16,
            agent="supervisor",
            data={
                "selected_agents": state["selected_agents"],
                "missing_info": state["missing_info"],
                "destination": facts.get("destination"),
                "duration": facts.get("duration"),
            },
        )
        return state

    # ======================== 阶段 3：并行调度 ========================

    def _dispatcher(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 3：并行执行领域 Agent（进度 22%-63%）。

        关键设计：
        - 使用 ThreadPoolExecutor 并行执行（最多 6 个并发）
        - budget_optimizer 不在此阶段执行（在 collector 中串行）
        - 每个 Agent 失败不阻塞其他 Agent
        - 通过 SSE 实时推送每个 Agent 的开始和完成事件

        对应需求文档 §10.3 的并行策略。
        """
        facts = state["extracted_facts"]

        # 过滤出需要并行执行的 Agent（排除 budget_optimizer）
        subtasks = {
            item["agent"]: item["instruction"]
            for item in state.get("subtasks", [])
            if item["agent"] != "budget_optimizer"
        }

        results = dict(state.get("agent_results", {}))

        if not subtasks:
            state["agent_results"] = results
            return state

        # 推送调度开始事件
        self._emit(
            "dispatcher_started",
            f"开始并行执行 {len(subtasks)} 个领域 Agent。",
            22,
            agent="supervisor",
            data={"agents": list(subtasks)},
        )

        # 并行执行
        with ThreadPoolExecutor(max_workers=min(len(subtasks), 6)) as executor:
            future_map = {}

            # 提交所有 Agent 任务
            for agent_name, instruction in subtasks.items():
                agent = self.agent_registry.get(agent_name)
                if agent is None:
                    # Agent 未注册 → 标记为失败
                    results[agent_name] = self._failed_result(
                        instruction, "Agent 未注册"
                    )
                    continue

                # 推送 Agent 开始事件
                self._emit(
                    "agent_started",
                    f"{agent_name} 开始执行。",
                    25,
                    agent=agent_name,
                )

                # 在线程池中执行
                future = executor.submit(
                    agent.execute,
                    instruction,
                    facts,
                    self._event_callback,
                )
                future_map[future] = (agent_name, instruction)

            # 收集结果（按完成顺序）
            completed_count = 0
            for future in as_completed(future_map):
                agent_name, instruction = future_map[future]
                try:
                    results[agent_name] = future.result()
                except Exception as exc:
                    results[agent_name] = self._failed_result(instruction, str(exc))
                    # 记录到错误历史
                    state.setdefault("error_history", []).append({
                        "agent": agent_name,
                        "error": str(exc),
                        "stage": "dispatcher",
                        "timestamp": datetime.now().isoformat(),
                    })

                completed_count += 1
                progress = 25 + int(38 * completed_count / max(len(future_map), 1))

                # 推送 Agent 完成事件
                self._emit(
                    "agent_completed",
                    f"{agent_name} 执行完成。",
                    progress,
                    agent=agent_name,
                    data={"status": results[agent_name].get("status")},
                )

        state["agent_results"] = results
        return state

    # ======================== 阶段 4：结果汇总 ========================

    def _collector(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 4：归一化各 Agent 输出 + 串行执行预算核对（进度 68%-74%）。

        执行步骤：
        1. 收集所有 Agent 的输出
        2. 串行执行 budget_optimizer（需要完整上下文）
        3. 分类统计：available / failed / degraded

        设计理由（需求文档 §10.3）：
        - 预算核对需要汇总所有 Agent 结果后才能准确计算
        - 因此不放在并行阶段，而是在此串行执行
        """
        results = dict(state.get("agent_results", {}))

        # --- 串行执行预算优化 ---
        budget_subtask = next(
            (
                item["instruction"]
                for item in state.get("subtasks", [])
                if item["agent"] == "budget_optimizer"
            ),
            "",
        )
        if budget_subtask:
            budget_agent = self.agent_registry.get("budget_optimizer")
            if budget_agent:
                self._emit(
                    "agent_started",
                    "budget_optimizer 开始预算核对。",
                    68,
                    agent="budget_optimizer",
                )
                try:
                    results["budget_optimizer"] = budget_agent.execute(
                        budget_subtask,
                        state["extracted_facts"],
                        self._event_callback,
                    )
                except Exception as exc:
                    results["budget_optimizer"] = self._failed_result(
                        budget_subtask, str(exc)
                    )

        # --- 分类统计 ---
        available = {
            name: result.get("response", "")
            for name, result in results.items()
            if result.get("status") in {"completed", "degraded"} and result.get("response")
        }
        failed = [
            name
            for name, result in results.items()
            if result.get("status") not in {"completed", "degraded"}
        ]
        degraded = [
            name
            for name, result in results.items()
            if result.get("status") == "degraded" or result.get("degraded")
        ]

        state["agent_results"] = results
        state["collector_output"] = {
            "sections": available,
            "failed_agents": failed,
            "degraded_agents": degraded,
            "generated_at": datetime.now().isoformat(),
        }

        self._emit(
            "collector_completed",
            "领域结果归一化完成。",
            74,
            agent="collector",
            data={"failed_agents": failed, "degraded_agents": degraded},
        )
        return state

    # ======================== 阶段 5：行程生成 ========================

    def _itinerary(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 5：生成逐日行程框架（进度 84%）。

        基于目的地、天数和可用 Agent 结果，生成逐日行程模板。
        V1 使用模板规则，P1 可接入 LLM 生成更个性化的行程。
        """
        facts = state["extracted_facts"]
        duration = int(facts.get("duration", 3))
        destination = facts.get("destination", "目的地")
        sections = state.get("collector_output", {}).get("sections", {})
        available_names = "、".join(sections) or "通用规划信息"

        # 构建逐日行程
        lines = [
            f"## {destination} {duration}日行程框架",
            f"- 规划依据：{available_names}",
            "- 原则：同区域聚合、减少折返、每天保留机动时段。",
            "",
        ]
        for day in range(1, duration + 1):
            if day == 1:
                focus = "抵达、入住与目的地核心区域适应"
            elif day == duration:
                focus = "补充体验、伴手礼与返程缓冲"
            else:
                focus = "核心景点与兴趣主题深度体验"
            lines.extend([
                f"### 第 {day} 天",
                f"- 上午：{focus}",
                "- 下午：安排同片区候选景点，结合天气和预约情况调整。",
                "- 晚上：本地餐饮或休闲活动，预留返回住宿地时间。",
                "",
            ])

        state["itinerary_output"] = "\n".join(lines).strip()

        # 记录 itinerary_planner 的贡献
        state["agent_results"]["itinerary_planner"] = {
            "status": "completed",
            "subtask": "整合领域结果并生成逐日行程。",
            "response": state["itinerary_output"],
            "output": state["itinerary_output"],
            "tool_artifacts": [],
            "error": "",
            "degraded": False,
            "retry_count": 0,
            "llm_calls": 0,
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }

        self._emit(
            "itinerary_completed",
            "逐日行程整合完成。",
            84,
            agent="itinerary_planner",
        )
        return state

    # ======================== 阶段 6：质量反思 ========================

    def _reflection(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 6：方案一致性与完整性检查（进度 91%）。

        检查维度：
        - 缺失信息：是否有必填字段未提供
        - 失败 Agent：是否有 Agent 完全失败
        - 降级 Agent：是否有 Agent 使用了降级结果

        V1 使用规则检查，P1 可接入 LLM 进行更深入的质量评估。
        """
        collector = state.get("collector_output", {})
        warnings: List[str] = []

        # 检查缺失信息
        if state.get("missing_info"):
            warnings.append("缺少信息：" + "、".join(state["missing_info"]))

        # 检查失败 Agent
        if collector.get("failed_agents"):
            warnings.append("失败 Agent：" + "、".join(collector["failed_agents"]))

        # 检查降级 Agent
        if collector.get("degraded_agents"):
            warnings.append("降级 Agent：" + "、".join(collector["degraded_agents"]))

        passed = not warnings

        state["reflection_output"] = {
            "passed": passed,
            "completion_status": "complete" if passed else "partial",
            "warnings": warnings,
            "suggestions": [],  # P1 阶段由 LLM 填充
            "confidence": 1.0 if passed else 0.7,
            "checked_at": datetime.now().isoformat(),
        }

        self._emit(
            "reflection_completed",
            "方案一致性与完整性检查完成。",
            91,
            agent="supervisor",
            data=state["reflection_output"],
        )
        return state

    # ======================== 阶段 7：最终总结 ========================

    def _summarizer(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 7：整合最终旅行方案（进度 97%）。

        将所有 Agent 输出 + 行程框架 + 反思警告 整合为一份完整的 Markdown 方案。
        """
        facts = state["extracted_facts"]
        sections = state.get("collector_output", {}).get("sections", {})

        # 构建 Markdown 报告
        report = [
            f"# {facts.get('destination', '目的地')}旅行规划",
            "",
            "## 需求摘要",
            f"- 出发地：{facts.get('departure') or '未提供'}",
            f"- 日期：{facts.get('start_date') or facts.get('travel_dates') or '待确认'}"
            f" 至 {facts.get('end_date') or '待确认'}",
            f"- 天数：{facts.get('duration', 3)} 天",
            f"- 人数：{facts.get('group_size', 1)} 人",
            f"- 预算：{facts.get('budget_range', '中等预算')}",
            f"- 兴趣：{'、'.join(facts.get('interests', [])) or '综合体验'}",
            "",
        ]

        # Agent 贡献展示名称映射
        display_names = {
            "flight_agent": "✈️ 航班方案",
            "train_agent": "🚄 铁路方案",
            "hotel_agent": "🏨 住宿方案",
            "attraction_agent": "🎯 景点方案",
            "weather_agent": "🌤️ 天气建议",
            "local_expert": "📍 在地建议",
            "budget_optimizer": "💰 预算建议",
        }

        # 追加各 Agent 的输出
        for name, content in sections.items():
            report.extend([f"## {display_names.get(name, name)}", content, ""])

        # 追加逐日行程
        report.extend([state.get("itinerary_output", ""), ""])

        # 追加反思警告
        warnings = state.get("reflection_output", {}).get("warnings", [])
        if warnings:
            report.extend(["## ⚠️ 风险与待确认项"])
            report.extend(f"- {warning}" for warning in warnings)

        state["final_output"] = "\n".join(report).strip()

        self._emit(
            "summary_completed",
            "最终旅行方案生成完成。",
            97,
            agent="supervisor",
        )
        return state

    # ======================== 阶段 8：记忆持久化 ========================

    def _memory_store(self, state: SupervisorState) -> SupervisorState:
        """
        阶段 8：回写短期记忆 + 标记任务完成（进度 100%）。

        执行步骤：
        1. 更新 memory_context，保存本次执行的完整快照
        2. 标记 task_status（completed 或 partial）
        3. 推送 task_completed 事件
        """
        # 更新短期记忆上下文
        state["memory_context"].update({
            "selected_agents": list(state.get("selected_agents", [])),
            "collector_output": state.get("collector_output", {}),
            "reflection_output": state.get("reflection_output", {}),
            "itinerary_output": state.get("itinerary_output", ""),
            "stored_at": datetime.now().isoformat(),
        })

        # 判断完成状态
        passed = bool(state.get("reflection_output", {}).get("passed"))
        state["task_status"] = "completed" if passed else "partial"

        # 构建完成消息
        message = (
            "Supervisor 多 Agent 规划完整完成。🎉"
            if passed
            else "Supervisor 多 Agent 规划已完成，部分能力降级或信息待补充。"
        )

        self._emit(
            "task_completed",
            message,
            100,
            status="completed",
            data={
                "completion_status": "complete" if passed else "partial",
                "selected_agents": state.get("selected_agents", []),
                "total_agents": len(state.get("agent_results", {})),
            },
        )
        return state

    # ======================== API 结果构建 ========================

    def _build_api_result(self, state: SupervisorState) -> Dict[str, Any]:
        """
        将内部 SupervisorState 转换为 API 兼容的结果字典。

        兼容现有 API 契约，包含：
        - travel_plan：结构化旅行方案
        - agent_outputs：各 Agent 原始输出
        - short_term_memory：短期记忆快照
        - completion_status：完整/部分完成标记
        """
        facts = state["extracted_facts"]
        agent_outputs = dict(state.get("agent_results", {}))

        # 构建预期 Agent 列表
        expected_agents = list(state.get("selected_agents", []))
        if "itinerary_planner" not in expected_agents:
            expected_agents.append("itinerary_planner")

        # 统计缺失和降级的 Agent
        missing_agents = [
            name
            for name in expected_agents
            if name not in agent_outputs
            or agent_outputs[name].get("status") not in {"completed", "degraded"}
        ]
        degraded_agents = [
            name
            for name in expected_agents
            if name in agent_outputs
            and (
                agent_outputs[name].get("status") == "degraded"
                or agent_outputs[name].get("degraded")
            )
        ]

        # 判断规划是否完整
        planning_complete = not (
            missing_agents or degraded_agents or state.get("missing_info")
        )
        completion_status = "complete" if planning_complete else "partial"

        # 构建 Agent 贡献摘要
        contributions = {
            name: result.get("response", "")
            for name, result in agent_outputs.items()
        }

        return {
            "success": True,
            "travel_plan": {
                "departure": facts.get("departure"),
                "destination": facts.get("destination"),
                "duration": facts.get("duration"),
                "travel_dates": facts.get("travel_dates")
                or f"{facts.get('start_date', '')} 至 {facts.get('end_date', '')}",
                "group_size": facts.get("group_size"),
                "budget_range": facts.get("budget_range"),
                "interests": facts.get("interests"),
                "transportation_preference": facts.get("transportation_preference"),
                "accommodation_preference": facts.get("accommodation_preference"),
                "planning_method": "Supervisor 动态多 Agent 架构",
                "summary": (
                    "Supervisor 动态路由、领域并行执行、预算核对与行程整合。"
                ),
                "agent_contributions": contributions,
                "recommendations": {
                    "transportation": "参见航班或铁路 Agent 输出",
                    "accommodation": "参见酒店 Agent 输出",
                    "attractions": "参见景点 Agent 输出",
                    "weather": "参见天气 Agent 输出",
                    "budget": "参见预算优化输出",
                    "daily_itinerary": "参见行程规划师输出",
                },
                "missing_agents": missing_agents,
                "degraded_agents": degraded_agents,
                "final_plan": state.get("final_output", ""),
            },
            "agent_outputs": agent_outputs,
            "expected_agents": expected_agents,
            "selected_agents": state.get("selected_agents", []),
            "missing_agents": missing_agents,
            "degraded_agents": degraded_agents,
            "planning_complete": planning_complete,
            "completion_status": completion_status,
            "total_iterations": 1,
            "short_term_memory": {
                "session_id": state.get("task_id"),
                "shared_facts": facts,
                "selected_agents": state.get("selected_agents", []),
                "collector_output": state.get("collector_output", {}),
                "itinerary_output": state.get("itinerary_output", ""),
                "reflection_output": state.get("reflection_output", {}),
                "agent_slots": {
                    name: {
                        "status": result.get("status"),
                        "degraded": result.get("degraded", False),
                        "error": result.get("error", ""),
                        "tool_count": len(result.get("tool_artifacts", [])),
                    }
                    for name, result in agent_outputs.items()
                },
            },
        }

    # ======================== 辅助方法 ========================

    def _failed_result(self, subtask: str, error: str) -> Dict[str, Any]:
        """
        生成失败 Agent 的统一返回结构。

        Args:
            subtask: 原始子任务指令
            error: 失败原因
        """
        now = datetime.now().isoformat()
        return {
            "status": "failed",
            "subtask": subtask,
            "response": "",
            "output": "",
            "tool_artifacts": [],
            "error": error,
            "degraded": False,
            "retry_count": 0,
            "llm_calls": 0,
            "started_at": now,
            "finished_at": now,
        }

    def _emit(
        self,
        event_type: str,
        message: str,
        progress: int,
        *,
        agent: str = "supervisor",
        status: str = "processing",
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        推送 SSE 事件。

        线程安全：通过 event_callback 回调函数推送，
        回调函数内部应使用锁保护共享数据结构。

        Args:
            event_type: 事件类型（如 agent_started、task_completed）
            message: 人类可读的事件描述
            progress: 进度百分比（0-100）
            agent: 触发事件的 Agent 名称
            status: 当前状态（processing/completed/failed）
            data: 附加数据字典
        """
        if not self._event_callback:
            return

        event = {
            "type": event_type,
            "message": message,
            "progress": progress,
            "agent": agent,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        if data is not None:
            event["data"] = data

        self._event_callback(event)
