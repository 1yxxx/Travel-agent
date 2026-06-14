"""Single-responsibility domain agents used by the Supervisor."""

from __future__ import annotations

import importlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from backend.tools.result import ToolResult, normalize_tool_result
except ImportError:
    from tools.result import ToolResult, normalize_tool_result


EventCallback = Optional[Callable[[Dict[str, Any]], None]]


class BaseDomainAgent:
    name = "base_agent"
    tool_module = ""
    tool_name = ""

    def execute(
        self,
        subtask: str,
        facts: Dict[str, Any],
        event_callback: EventCallback = None,
    ) -> Dict[str, Any]:
        started_at = datetime.now().isoformat()
        params = self.build_tool_params(facts)
        artifact = {
            "agent": self.name,
            "tool": self.tool_name or "internal",
            "params": params,
            "status": "started",
            "timestamp": started_at,
        }
        self._emit(
            event_callback,
            "tool_called",
            f"{self.name} 调用工具: {artifact['tool']}",
            {"tool": artifact["tool"], "params": params},
        )

        try:
            tool_result = normalize_tool_result(self.invoke_tool(params, facts))
            text = tool_result.message.strip()
            if not text:
                text = self.fallback_output(facts, tool_result.error or "工具返回为空")

            agent_status = {
                "success": "completed",
                "degraded": "degraded",
                "failed": "failed",
            }[tool_result.status]
            artifact.update(
                {
                    "status": agent_status,
                    "result_preview": text[:500],
                    "result_data": tool_result.data,
                    "source": tool_result.source,
                    "error": tool_result.error,
                    "finished_at": datetime.now().isoformat(),
                }
            )
            event_type = {
                "success": "tool_completed",
                "degraded": "tool_degraded",
                "failed": "tool_failed",
            }[tool_result.status]
            event_message = {
                "success": f"{self.name} 工具调用完成",
                "degraded": f"{self.name} 工具结果已降级",
                "failed": f"{self.name} 工具调用失败",
            }[tool_result.status]
            self._emit(
                event_callback,
                event_type,
                event_message,
                {
                    "tool": artifact["tool"],
                    "preview": text[:300],
                    "status": tool_result.status,
                    "error": tool_result.error,
                },
            )
            return self._result(
                subtask,
                text,
                [artifact],
                started_at,
                status=agent_status,
                error=tool_result.error,
                degraded=tool_result.status == "degraded",
            )
        except Exception as exc:
            fallback = self.fallback_output(facts, str(exc))
            artifact.update(
                {
                    "status": "degraded",
                    "error": str(exc),
                    "result_preview": fallback[:500],
                    "finished_at": datetime.now().isoformat(),
                }
            )
            self._emit(
                event_callback,
                "tool_failed",
                f"{self.name} 工具不可用，已降级",
                {"tool": artifact["tool"], "error": str(exc)},
            )
            return self._result(
                subtask,
                fallback,
                [artifact],
                started_at,
                status="degraded",
                error=str(exc),
                degraded=True,
            )

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def invoke_tool(self, params: Dict[str, Any], facts: Dict[str, Any]) -> Any:
        tool = self._load_tool()
        return tool.invoke(params)

    def fallback_output(self, facts: Dict[str, Any], reason: str) -> str:
        return (
            f"## {self.name} 降级结果\n"
            f"- 目的地：{facts.get('destination', '未指定')}\n"
            f"- 当前数据源不可用：{reason}\n"
            "- 建议在出发前通过官方渠道复核实时信息。"
        )

    def _load_tool(self) -> Any:
        errors: List[str] = []
        for module_name in (f"backend.tools.{self.tool_module}", f"tools.{self.tool_module}"):
            try:
                module = importlib.import_module(module_name)
                return getattr(module, self.tool_name)
            except Exception as exc:
                errors.append(f"{module_name}: {exc}")
        raise RuntimeError("; ".join(errors))

    def _result(
        self,
        subtask: str,
        output: str,
        artifacts: List[Dict[str, Any]],
        started_at: str,
        *,
        status: str = "completed",
        error: str = "",
        degraded: bool = False,
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "subtask": subtask,
            "response": output,
            "output": output,
            "tool_artifacts": artifacts,
            "error": error,
            "degraded": degraded,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
        }

    def _emit(
        self,
        callback: EventCallback,
        event_type: str,
        message: str,
        data: Dict[str, Any],
    ) -> None:
        if callback:
            callback(
                {
                    "type": event_type,
                    "message": message,
                    "agent": self.name,
                    "status": "processing",
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                }
            )


class FlightAgent(BaseDomainAgent):
    name = "flight_agent"
    tool_module = "flight_tool"
    tool_name = "search_flights"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "departure": facts.get("departure", ""),
            "arrival": facts.get("destination", ""),
            "date": facts.get("start_date", ""),
        }


class TrainAgent(BaseDomainAgent):
    name = "train_agent"
    tool_module = "train_tool"
    tool_name = "search_trains"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "departure": facts.get("departure", ""),
            "arrival": facts.get("destination", ""),
            "date": facts.get("start_date", ""),
        }


class HotelAgent(BaseDomainAgent):
    name = "hotel_agent"
    tool_module = "hotel_tool"
    tool_name = "search_hotels"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        budget = str(facts.get("budget_range", ""))
        star = 5 if any(word in budget for word in ("豪华", "高端")) else 3 if "经济" in budget else 4
        return {
            "city": facts.get("destination", ""),
            "check_in": facts.get("start_date", ""),
            "check_out": facts.get("end_date", ""),
            "star": star,
        }


class AttractionAgent(BaseDomainAgent):
    name = "attraction_agent"
    tool_module = "attraction_tool"
    tool_name = "search_attractions"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "city": facts.get("destination", ""),
            "keywords": "、".join(facts.get("interests", [])) or "热门景点",
        }


class WeatherAgent(BaseDomainAgent):
    name = "weather_agent"
    tool_module = "weather_tool"
    tool_name = "search_weather"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "city": facts.get("destination", ""),
            "days": min(max(int(facts.get("duration", 3)), 1), 7),
        }


class LocalExpertAgent(BaseDomainAgent):
    name = "local_expert"
    tool_module = "travel_tools"
    tool_name = "local_expert_skill"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        destination = facts.get("destination", "")
        interests = "、".join(facts.get("interests", []))
        return {
            "destination": destination,
            "interests": interests,
            "query": f"{destination} {interests} 在地体验 餐饮 礼仪 避坑".strip(),
            "top_k": 4,
        }

    def fallback_output(self, facts: Dict[str, Any], reason: str) -> str:
        destination = str(facts.get("destination", "")).strip()
        city_aliases = {
            "北京": "beijing",
            "上海": "shanghai",
            "广州": "guangzhou",
            "深圳": "shenzhen",
            "杭州": "hangzhou",
        }
        knowledge_file = (
            Path(__file__).resolve().parents[2]
            / "SimpleExample-knowledge-rag"
            / f"{city_aliases.get(destination, destination.lower())}.md"
        )
        if knowledge_file.exists():
            content = knowledge_file.read_text(encoding="utf-8").strip()
            excerpt = content[:1800]
            return (
                f"## {destination}本地知识（本地文件降级）\n"
                f"{excerpt}\n\n"
                f"> 在线 RAG 不可用：{reason}"
            )
        return super().fallback_output(facts, reason)


class BudgetAgent(BaseDomainAgent):
    name = "budget_optimizer"
    tool_name = "budget_calculator"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "budget_range": facts.get("budget_range", ""),
            "duration": facts.get("duration", 3),
            "group_size": facts.get("group_size", 1),
        }

    def invoke_tool(self, params: Dict[str, Any], facts: Dict[str, Any]) -> ToolResult:
        budget_text = str(params["budget_range"])
        estimate = parse_budget_estimate(
            budget_text,
            duration=int(params["duration"]),
            group_size=int(params["group_size"]),
        )
        total_budget = estimate["total_budget"]
        if total_budget:
            per_person_day = estimate["per_person_day"]
            level = "偏紧" if per_person_day < 350 else "充足" if per_person_day >= 900 else "适中"
            return ToolResult.success(
                (
                    "## 预算分析\n"
                    f"- 预算口径：{estimate['basis']}\n"
                    f"- 全程总预算参考：¥{total_budget:.0f}\n"
                    f"- 人均每日预算：约 ¥{per_person_day:.0f}\n"
                    f"- 预算状态：{level}\n"
                    "- 建议分配：住宿 35%，交通 25%，餐饮 20%，门票活动 15%，机动 5%。"
                ),
                data=estimate,
                source="budget_calculator",
            )
        return ToolResult.degraded(
            (
                "## 预算分析\n"
                f"- 当前预算描述：{budget_text or '未提供明确金额'}\n"
                "- 建议补充总预算金额；暂按住宿 35%、交通 25%、餐饮 20%、门票活动 15%、机动 5% 分配。"
            ),
            error="budget_amount_missing",
            source="budget_calculator",
        )


def parse_budget_estimate(
    budget_text: str,
    *,
    duration: int,
    group_size: int,
) -> Dict[str, Any]:
    """Convert common Chinese budget descriptions into one trip-wide amount."""

    normalized_duration = max(int(duration), 1)
    normalized_group_size = max(int(group_size), 1)
    numbers = [
        int(item.replace(",", ""))
        for item in re.findall(r"\d[\d,]*", str(budget_text))
    ]
    amount = max(numbers) if numbers else 0
    is_daily = bool(
        re.search(r"(?:每天|每日|日均|(?:元|块)?\s*/\s*(?:天|日))", budget_text)
    )
    is_per_person = bool(re.search(r"(?:人均|每人)", budget_text))

    if is_daily and is_per_person:
        total_budget = amount * normalized_duration * normalized_group_size
        basis = "人均每日预算上限"
    elif is_daily:
        total_budget = amount * normalized_duration
        basis = "团队每日预算上限"
    else:
        total_budget = amount
        basis = "全程总预算上限"

    per_person_day = total_budget / (normalized_duration * normalized_group_size)
    return {
        "input": budget_text,
        "basis": basis,
        "total_budget": total_budget,
        "per_person_day": per_person_day,
        "duration": normalized_duration,
        "group_size": normalized_group_size,
    }


def build_default_agent_registry() -> Dict[str, BaseDomainAgent]:
    agents: List[BaseDomainAgent] = [
        FlightAgent(),
        TrainAgent(),
        HotelAgent(),
        AttractionAgent(),
        WeatherAgent(),
        LocalExpertAgent(),
        BudgetAgent(),
    ]
    return {agent.name: agent for agent in agents}
