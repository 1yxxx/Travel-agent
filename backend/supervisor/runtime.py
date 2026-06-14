"""
Supervisor 工作流运行时 —— 纯 LangGraph 范式。

每个节点只返回本阶段更新的字段（Dict[str, Any]），
LangGraph 自动合并返回值到累积的 SupervisorState 中。

8 阶段流水线：
  memory_recall → intent_parser → dispatcher → collector →
  itinerary → reflection → summarizer → memory_store → END
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

# 导入领域 Agent 注册表（兼容两种启动路径）
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

# 可选 LLM 增强提示词
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
    LangGraph 范式的 Supervisor 编排器。

    节点契约：def node(state: SupervisorState) -> Dict[str, Any]
    - 只读取 state，不修改 state
    - 只返回本阶段新增/修改的字段
    - LangGraph 自动将返回值合并到累积 state
    """

    def __init__(self, agent_registry: Optional[Dict[str, Any]] = None) -> None:
        self.agent_registry = agent_registry or build_default_agent_registry()
        self.graph = self._build_graph()
        self._event_callback: EventCallback = None

    # ======================== 主入口 ========================

    def run_travel_planning(
        self,
        travel_request: Dict[str, Any],
        event_callback: EventCallback = None,
    ) -> Dict[str, Any]:
        """对外的唯一入口，兼容现有 API 契约。"""
        initial_state: SupervisorState = {
            "task_id": str(travel_request.get("task_id") or uuid.uuid4()),
            "trace_id": str(uuid.uuid4())[:8],
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
            final_state = self.graph.invoke(initial_state)
            return self._build_api_result(final_state)
        except Exception as exc:
            self._emit("task_failed", f"Supervisor 执行失败: {exc}", 100, status="failed")
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

        图结构（需求文档 §10.1）：
        memory_recall → intent_parser → dispatcher → collector →
        itinerary → reflection → summarizer → memory_store → END
        """
        workflow = StateGraph(SupervisorState)
        workflow.add_node("memory_recall", self._memory_recall)
        workflow.add_node("intent_parser", self._intent_parser)
        workflow.add_node("dispatcher", self._dispatcher)
        workflow.add_node("collector", self._collector)
        workflow.add_node("itinerary", self._itinerary)
        workflow.add_node("reflection", self._reflection)
        workflow.add_node("summarizer", self._summarizer)
        workflow.add_node("memory_store", self._memory_store)

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

    # ======================== 阶段 1：记忆召回 ========================

    def _memory_recall(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 1：短期记忆初始化（进度 8%）。"""
        self._emit("memory_recalled", "短期记忆初始化完成。", 8, agent="supervisor")
        return {
            "memory_context": {
                "request_snapshot": dict(state.get("user_request", {})),
                "recalled_preferences": {},
                "initialized_at": datetime.now().isoformat(),
            }
        }

    # ======================== 阶段 2：意图解析 ========================

    def _intent_parser(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 2：需求解析与动态路由（进度 16%）。"""
        facts = normalize_request(state.get("user_request", {}))
        missing = find_missing_info(facts)
        agents = select_agents(facts)
        subtasks = build_subtasks(facts, agents)
        clarification = ""

        if missing:
            _, clarification = build_clarification_prompt(facts, missing)

        self._emit(
            "intent_parsed", "需求解析和动态路由完成。", 16, agent="supervisor",
            data={
                "selected_agents": agents,
                "missing_info": missing,
                "destination": facts.get("destination"),
                "duration": facts.get("duration"),
            },
        )
        return {
            "extracted_facts": facts,
            "missing_info": missing,
            "clarification_question": clarification,
            "selected_agents": agents,
            "subtasks": subtasks,
        }

    # ======================== 阶段 3：并行调度 ========================

    def _dispatcher(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 3：并行执行领域 Agent（进度 22%-63%）。"""
        facts = state["extracted_facts"]

        subtask_map = {
            item["agent"]: item["instruction"]
            for item in state.get("subtasks", [])
            if item["agent"] != "budget_optimizer"
        }

        if not subtask_map:
            return {"agent_results": dict(state.get("agent_results", {}))}

        self._emit(
            "dispatcher_started",
            f"开始并行执行 {len(subtask_map)} 个领域 Agent。",
            22, agent="supervisor", data={"agents": list(subtask_map)},
        )

        results = dict(state.get("agent_results", {}))
        new_errors: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=min(len(subtask_map), 6)) as executor:
            future_map = {}

            for agent_name, instruction in subtask_map.items():
                agent = self.agent_registry.get(agent_name)
                if agent is None:
                    results[agent_name] = self._failed_result(instruction, "Agent 未注册")
                    continue

                self._emit("agent_started", f"{agent_name} 开始执行。", 25, agent=agent_name)
                future = executor.submit(agent.execute, instruction, facts, self._event_callback)
                future_map[future] = (agent_name, instruction)

            completed_count = 0
            for future in as_completed(future_map):
                agent_name, instruction = future_map[future]
                try:
                    results[agent_name] = future.result()
                except Exception as exc:
                    results[agent_name] = self._failed_result(instruction, str(exc))
                    new_errors.append({
                        "agent": agent_name,
                        "error": str(exc),
                        "stage": "dispatcher",
                        "timestamp": datetime.now().isoformat(),
                    })

                completed_count += 1
                progress = 25 + int(38 * completed_count / max(len(future_map), 1))
                self._emit(
                    "agent_completed", f"{agent_name} 执行完成。",
                    progress, agent=agent_name,
                    data={"status": results[agent_name].get("status")},
                )

        return {
            "agent_results": results,
            "error_history": state.get("error_history", []) + new_errors,
        }

    # ======================== 阶段 4：结果汇总 ========================

    def _collector(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 4：归一化 + 串行预算核对（进度 68%-74%）。"""
        results = dict(state.get("agent_results", {}))

        # 串行执行预算优化（需要全部 Agent 结果）
        budget_subtask = next(
            (item["instruction"]
             for item in state.get("subtasks", [])
             if item["agent"] == "budget_optimizer"),
            "",
        )
        if budget_subtask:
            budget_agent = self.agent_registry.get("budget_optimizer")
            if budget_agent:
                self._emit(
                    "agent_started", "budget_optimizer 开始预算核对。",
                    68, agent="budget_optimizer",
                )
                try:
                    results["budget_optimizer"] = budget_agent.execute(
                        budget_subtask, state["extracted_facts"], self._event_callback,
                    )
                except Exception as exc:
                    results["budget_optimizer"] = self._failed_result(budget_subtask, str(exc))

        available = {
            name: r.get("response", "")
            for name, r in results.items()
            if r.get("status") in {"completed", "degraded"} and r.get("response")
        }
        failed = [
            n for n, r in results.items()
            if r.get("status") not in {"completed", "degraded"}
        ]
        degraded = [
            n for n, r in results.items()
            if r.get("status") == "degraded" or r.get("degraded")
        ]

        self._emit(
            "collector_completed", "领域结果归一化完成。",
            74, agent="collector",
            data={"failed_agents": failed, "degraded_agents": degraded},
        )

        return {
            "agent_results": results,
            "collector_output": {
                "sections": available,
                "failed_agents": failed,
                "degraded_agents": degraded,
                "generated_at": datetime.now().isoformat(),
            },
        }

    # ======================== 阶段 5：行程生成 ========================

    def _itinerary(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 5：生成逐日行程框架（进度 84%）。"""
        facts = state["extracted_facts"]
        duration = int(facts.get("duration", 3))
        destination = facts.get("destination", "目的地")
        sections = state.get("collector_output", {}).get("sections", {})

        lines = [
            f"## {destination} {duration}日行程框架",
            f"- 规划依据：{'、'.join(sections) or '通用规划信息'}",
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

        itinerary_output = "\n".join(lines).strip()
        self._emit("itinerary_completed", "逐日行程整合完成。", 84, agent="itinerary_planner")

        now = datetime.now().isoformat()
        return {
            "itinerary_output": itinerary_output,
            "agent_results": {
                **state.get("agent_results", {}),
                "itinerary_planner": {
                    "status": "completed",
                    "subtask": "整合领域结果并生成逐日行程。",
                    "response": itinerary_output,
                    "output": itinerary_output,
                    "tool_artifacts": [],
                    "error": "",
                    "degraded": False,
                    "retry_count": 0,
                    "llm_calls": 0,
                    "started_at": now,
                    "finished_at": now,
                },
            },
        }

    # ======================== 阶段 6：质量反思 ========================

    def _reflection(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 6：一致性与完整性检查（进度 91%）。"""
        collector = state.get("collector_output", {})
        warnings: List[str] = []

        if state.get("missing_info"):
            warnings.append("缺少信息：" + "、".join(state["missing_info"]))
        if collector.get("failed_agents"):
            warnings.append("失败 Agent：" + "、".join(collector["failed_agents"]))
        if collector.get("degraded_agents"):
            warnings.append("降级 Agent：" + "、".join(collector["degraded_agents"]))

        passed = not warnings
        reflection_output = {
            "passed": passed,
            "completion_status": "complete" if passed else "partial",
            "warnings": warnings,
            "suggestions": [],
            "confidence": 1.0 if passed else 0.7,
            "checked_at": datetime.now().isoformat(),
        }

        self._emit(
            "reflection_completed", "方案一致性与完整性检查完成。",
            91, agent="supervisor", data=reflection_output,
        )
        return {"reflection_output": reflection_output}

    # ======================== 阶段 7：最终总结 ========================

    def _summarizer(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 7：整合最终 Markdown 方案（进度 97%）。"""
        facts = state["extracted_facts"]
        sections = state.get("collector_output", {}).get("sections", {})

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

        display_names = {
            "flight_agent": "✈️ 航班方案",
            "train_agent": "🚄 铁路方案",
            "hotel_agent": "🏨 住宿方案",
            "attraction_agent": "🎯 景点方案",
            "weather_agent": "🌤️ 天气建议",
            "local_expert": "📍 在地建议",
            "budget_optimizer": "💰 预算建议",
        }

        for name, content in sections.items():
            report.extend([f"## {display_names.get(name, name)}", content, ""])

        report.extend([state.get("itinerary_output", ""), ""])

        warnings = state.get("reflection_output", {}).get("warnings", [])
        if warnings:
            report.extend(["## ⚠️ 风险与待确认项"])
            report.extend(f"- {warning}" for warning in warnings)

        final_output = "\n".join(report).strip()
        self._emit("summary_completed", "最终旅行方案生成完成。", 97, agent="supervisor")
        return {"final_output": final_output}

    # ======================== 阶段 8：记忆持久化 ========================

    def _memory_store(self, state: SupervisorState) -> Dict[str, Any]:
        """阶段 8：回写短期记忆 + 标记完成（进度 100%）。"""
        passed = bool(state.get("reflection_output", {}).get("passed"))
        task_status = "completed" if passed else "partial"

        message = (
            "Supervisor 多 Agent 规划完整完成。🎉" if passed
            else "Supervisor 多 Agent 规划已完成，部分能力降级或信息待补充。"
        )

        self._emit(
            "task_completed", message, 100, status="completed",
            data={
                "completion_status": "complete" if passed else "partial",
                "selected_agents": state.get("selected_agents", []),
                "total_agents": len(state.get("agent_results", {})),
            },
        )

        return {
            "task_status": task_status,
            "memory_context": {
                **state.get("memory_context", {}),
                "selected_agents": list(state.get("selected_agents", [])),
                "collector_output": state.get("collector_output", {}),
                "reflection_output": state.get("reflection_output", {}),
                "itinerary_output": state.get("itinerary_output", ""),
                "stored_at": datetime.now().isoformat(),
            },
        }

    # ======================== API 结果构建 ========================

    def _build_api_result(self, state: SupervisorState) -> Dict[str, Any]:
        """将内部 SupervisorState 转换为 API 兼容结果字典。"""
        facts = state["extracted_facts"]
        agent_outputs = dict(state.get("agent_results", {}))

        expected_agents = list(state.get("selected_agents", []))
        if "itinerary_planner" not in expected_agents:
            expected_agents.append("itinerary_planner")

        missing_agents = [
            n for n in expected_agents
            if n not in agent_outputs
            or agent_outputs[n].get("status") not in {"completed", "degraded"}
        ]
        degraded_agents = [
            n for n in expected_agents
            if n in agent_outputs and (
                agent_outputs[n].get("status") == "degraded"
                or agent_outputs[n].get("degraded")
            )
        ]

        planning_complete = not (missing_agents or degraded_agents or state.get("missing_info"))
        completion_status = "complete" if planning_complete else "partial"

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
                "planning_method": "Supervisor 动态多 Agent 架构（LangGraph）",
                "summary": "Supervisor 动态路由、领域并行执行、预算核对与行程整合。",
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
        """生成失败 Agent 的统一返回结构。"""
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
        """推送 SSE 事件回调。"""
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
