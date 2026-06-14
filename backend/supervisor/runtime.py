"""Supervisor workflow runtime with optional LangGraph execution."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from backend.agents.domain_agents import build_default_agent_registry
except ImportError:
    from agents.domain_agents import build_default_agent_registry

from .router import build_subtasks, find_missing_info, normalize_request, select_agents
from .state import EventCallback, SupervisorState


class SupervisorTravelPlanner:
    """Dynamic multi-agent planner compatible with the existing API contract."""

    def __init__(
        self,
        agent_registry: Optional[Dict[str, Any]] = None,
        *,
        use_langgraph: bool = True,
    ) -> None:
        self.agent_registry = agent_registry or build_default_agent_registry()
        self.graph = self._build_graph() if use_langgraph else None

    def run_travel_planning(
        self,
        travel_request: Dict[str, Any],
        event_callback: EventCallback = None,
    ) -> Dict[str, Any]:
        state: SupervisorState = {
            "task_id": str(travel_request.get("task_id") or uuid.uuid4()),
            "user_request": dict(travel_request),
            "extracted_facts": {},
            "missing_info": [],
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
        }
        self._event_callback = event_callback

        try:
            final_state = self.graph.invoke(state) if self.graph is not None else self._run_pipeline(state)
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

    def _build_graph(self) -> Any:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

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

    def _run_pipeline(self, state: SupervisorState) -> SupervisorState:
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

    def _memory_recall(self, state: SupervisorState) -> SupervisorState:
        state["memory_context"] = {
            "request_snapshot": dict(state.get("user_request", {})),
            "recalled_preferences": {},
        }
        self._emit("memory_recalled", "短期记忆初始化完成。", 8, agent="supervisor")
        return state

    def _intent_parser(self, state: SupervisorState) -> SupervisorState:
        facts = normalize_request(state.get("user_request", {}))
        state["extracted_facts"] = facts
        state["missing_info"] = find_missing_info(facts)
        state["selected_agents"] = select_agents(facts)
        state["subtasks"] = build_subtasks(facts, state["selected_agents"])
        self._emit(
            "intent_parsed",
            "需求解析和动态路由完成。",
            16,
            agent="supervisor",
            data={
                "selected_agents": state["selected_agents"],
                "missing_info": state["missing_info"],
            },
        )
        return state

    def _dispatcher(self, state: SupervisorState) -> SupervisorState:
        facts = state["extracted_facts"]
        subtasks = {
            item["agent"]: item["instruction"]
            for item in state.get("subtasks", [])
            if item["agent"] != "budget_optimizer"
        }
        results = dict(state.get("agent_results", {}))
        if not subtasks:
            state["agent_results"] = results
            return state

        self._emit(
            "dispatcher_started",
            f"开始并行执行 {len(subtasks)} 个领域 Agent。",
            22,
            agent="supervisor",
            data={"agents": list(subtasks)},
        )
        with ThreadPoolExecutor(max_workers=min(len(subtasks), 6)) as executor:
            future_map = {}
            for agent_name, instruction in subtasks.items():
                agent = self.agent_registry.get(agent_name)
                if agent is None:
                    results[agent_name] = self._failed_result(instruction, "Agent 未注册")
                    continue
                self._emit(
                    "agent_started",
                    f"{agent_name} 开始执行。",
                    25,
                    agent=agent_name,
                )
                future = executor.submit(
                    agent.execute,
                    instruction,
                    facts,
                    self._event_callback,
                )
                future_map[future] = (agent_name, instruction)

            completed = 0
            for future in as_completed(future_map):
                agent_name, instruction = future_map[future]
                try:
                    results[agent_name] = future.result()
                except Exception as exc:
                    results[agent_name] = self._failed_result(instruction, str(exc))
                completed += 1
                progress = 25 + int(38 * completed / max(len(future_map), 1))
                self._emit(
                    "agent_completed",
                    f"{agent_name} 执行完成。",
                    progress,
                    agent=agent_name,
                    data={"status": results[agent_name].get("status")},
                )

        state["agent_results"] = results
        return state

    def _collector(self, state: SupervisorState) -> SupervisorState:
        results = dict(state.get("agent_results", {}))
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
                results["budget_optimizer"] = budget_agent.execute(
                    budget_subtask,
                    state["extracted_facts"],
                    self._event_callback,
                )

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

    def _itinerary(self, state: SupervisorState) -> SupervisorState:
        facts = state["extracted_facts"]
        duration = int(facts.get("duration", 3))
        destination = facts.get("destination", "目的地")
        sections = state.get("collector_output", {}).get("sections", {})
        available_names = "、".join(sections) or "通用规划信息"
        lines = [
            f"## {destination}{duration}日行程框架",
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
            lines.extend(
                [
                    f"### 第 {day} 天",
                    f"- 上午：{focus}",
                    "- 下午：安排同片区候选景点，结合天气和预约情况调整。",
                    "- 晚上：本地餐饮或休闲活动，预留返回住宿地时间。",
                    "",
                ]
            )
        state["itinerary_output"] = "\n".join(lines).strip()
        state["agent_results"]["itinerary_planner"] = {
            "status": "completed",
            "subtask": "整合领域结果并生成逐日行程。",
            "response": state["itinerary_output"],
            "output": state["itinerary_output"],
            "tool_artifacts": [],
            "error": "",
            "degraded": False,
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

    def _reflection(self, state: SupervisorState) -> SupervisorState:
        collector = state.get("collector_output", {})
        warnings: List[str] = []
        if state.get("missing_info"):
            warnings.append("缺少信息：" + "、".join(state["missing_info"]))
        if collector.get("failed_agents"):
            warnings.append("失败 Agent：" + "、".join(collector["failed_agents"]))
        if collector.get("degraded_agents"):
            warnings.append("降级 Agent：" + "、".join(collector["degraded_agents"]))
        passed = not warnings
        state["reflection_output"] = {
            "passed": passed,
            "completion_status": "complete" if passed else "partial",
            "warnings": warnings,
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

    def _summarizer(self, state: SupervisorState) -> SupervisorState:
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
            "flight_agent": "航班方案",
            "train_agent": "铁路方案",
            "hotel_agent": "住宿方案",
            "attraction_agent": "景点方案",
            "weather_agent": "天气建议",
            "local_expert": "在地建议",
            "budget_optimizer": "预算建议",
        }
        for name, content in sections.items():
            report.extend([f"## {display_names.get(name, name)}", content, ""])
        report.extend([state.get("itinerary_output", ""), ""])
        warnings = state.get("reflection_output", {}).get("warnings", [])
        if warnings:
            report.extend(["## 风险与待确认项"])
            report.extend(f"- {warning}" for warning in warnings)
        state["final_output"] = "\n".join(report).strip()
        self._emit("summary_completed", "最终旅行方案生成完成。", 97, agent="supervisor")
        return state

    def _memory_store(self, state: SupervisorState) -> SupervisorState:
        state["memory_context"].update(
            {
                "selected_agents": list(state.get("selected_agents", [])),
                "collector_output": state.get("collector_output", {}),
                "reflection_output": state.get("reflection_output", {}),
                "stored_at": datetime.now().isoformat(),
            }
        )
        passed = bool(state.get("reflection_output", {}).get("passed"))
        state["task_status"] = "completed" if passed else "partial"
        message = (
            "Supervisor 多 Agent 规划完整完成。"
            if passed
            else "Supervisor 多 Agent 规划已完成，部分能力降级或信息待补充。"
        )
        self._emit(
            "task_completed",
            message,
            100,
            status="completed",
            data={"completion_status": "complete" if passed else "partial"},
        )
        return state

    def _build_api_result(self, state: SupervisorState) -> Dict[str, Any]:
        facts = state["extracted_facts"]
        agent_outputs = dict(state.get("agent_results", {}))
        expected_agents = list(state.get("selected_agents", []))
        if "itinerary_planner" not in expected_agents:
            expected_agents.append("itinerary_planner")
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
        planning_complete = not (
            missing_agents or degraded_agents or state.get("missing_info")
        )
        completion_status = "complete" if planning_complete else "partial"
        contributions = {
            name: result.get("response", "") for name, result in agent_outputs.items()
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

    def _failed_result(self, subtask: str, error: str) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "status": "failed",
            "subtask": subtask,
            "response": "",
            "output": "",
            "tool_artifacts": [],
            "error": error,
            "degraded": False,
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
