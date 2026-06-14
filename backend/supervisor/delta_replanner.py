"""
DeltaReplanner — 增量重规划。

当用户提出修改意见时，只重跑受影响的 Agent，
其余 Agent 结果直接复用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.supervisor.intent_router import analyze_modification_intent
from backend.storage.chat_session import ChatSession


class DeltaReplanner:
    """
    增量重规划器。

    使用方式:
        replanner = DeltaReplanner(agent_registry, llm)
        new_result = replanner.refine(original_result, feedback, session)
    """

    def __init__(self, agent_registry: Dict[str, Any], llm=None):
        self.agent_registry = agent_registry
        self.llm = llm

    def refine(
        self,
        original_result: Dict[str, Any],
        feedback: str,
        session: Optional[ChatSession] = None,
        event_callback=None,
    ) -> Dict[str, Any]:
        """
        增量重规划主入口。

        Args:
            original_result: 原始计划结果（来自 _build_api_result）
            feedback: 用户自然语言修改意见
            session: 当前会话（可选，用于获取累积事实）
            event_callback: SSE 事件回调

        Returns:
            合并后的新结果，格式同 _build_api_result
        """
        # 1. 生成计划摘要
        plan_summary = self._summarize_plan(original_result)

        # 2. 分析修改意图，确定受影响 Agent
        analysis = analyze_modification_intent(feedback, plan_summary, self.llm)
        affected = analysis.get("affected_agents", [])
        updated_facts = analysis.get("updated_facts", {})

        # 3. 合并新事实到 session
        facts = dict(original_result.get("travel_plan", {}))
        if session:
            session.merge_facts(updated_facts)
            facts.update(session.accumulated_facts)
        facts.update(updated_facts)

        # 4. 检查是否全部重跑
        all_agents = list(self.agent_registry.keys())
        if len(affected) >= len(all_agents) - 2:  # 超过 2/3 → 全量
            affected = all_agents

        # 5. 保留不变的 Agent 结果
        original_agent_outputs = original_result.get("agent_outputs", {}) or {}
        unchanged_outputs = {
            name: output
            for name, output in original_agent_outputs.items()
            if name not in affected
        }

        # 6. 重新执行受影响 Agent
        new_outputs = {}
        if event_callback:
            event_callback({
                "type": "refine_started",
                "message": f"正在调整：{'、'.join(affected)}",
                "agent": "supervisor",
                "status": "processing",
                "data": {"affected_agents": affected},
                "timestamp": datetime.now().isoformat(),
            })

        for agent_name in affected:
            agent = self.agent_registry.get(agent_name)
            if agent is None:
                continue

            if event_callback:
                event_callback({
                    "type": "agent_started",
                    "message": f"重新执行 {agent_name}",
                    "agent": agent_name,
                    "status": "processing",
                    "timestamp": datetime.now().isoformat(),
                })

            try:
                # 构建子任务
                subtask = f"根据更新后的需求为 {facts.get('destination', '')} 重新执行 {agent_name}"
                result = agent.execute(subtask, facts, event_callback)
                new_outputs[agent_name] = result
            except Exception as e:
                new_outputs[agent_name] = {
                    "status": "failed",
                    "response": f"{agent_name} 执行失败: {str(e)}",
                    "error": str(e),
                }

        # 7. 合并结果
        merged_outputs = {**unchanged_outputs, **new_outputs}

        # 8. 重新生成行程（如果 itinerary 受影响）
        if "itinerary_planner" in affected:
            # itinerary_planner 已在上面重跑
            pass

        # 9. 构建新结果
        new_result = dict(original_result)
        new_result["agent_outputs"] = merged_outputs
        new_result["travel_plan"] = {**original_result.get("travel_plan", {}), **facts}
        new_result["travel_plan"]["modified_agents"] = affected
        new_result["travel_plan"]["unchanged_agents"] = sorted(
            set(original_agent_outputs.keys()) - set(affected)
        )
        new_result["travel_plan"]["modification_feedback"] = feedback
        new_result["short_term_memory"] = original_result.get("short_term_memory", {})
        new_result["planning_complete"] = True
        new_result["completion_status"] = "refined"

        return new_result

    def _summarize_plan(self, result: Dict[str, Any]) -> str:
        """生成计划摘要（供 LLM 分析修改意图）。"""
        tp = result.get("travel_plan", {}) or {}
        ao = result.get("agent_outputs", {}) or {}

        lines = [
            f"目的地: {tp.get('destination', '未知')}",
            f"日期: {tp.get('travel_dates', '未知')}",
            f"天数: {tp.get('duration', '?')}天",
            f"人数: {tp.get('group_size', '?')}人",
            f"预算: {tp.get('budget_range', '未知')}",
        ]

        for name, output in ao.items():
            if not isinstance(output, dict):
                continue
            resp = output.get("response", "")
            if resp:
                # 取前 150 字
                summary = resp[:150].replace("\n", " ").strip()
                lines.append(f"{name}: {summary}")

        return "\n".join(lines)
