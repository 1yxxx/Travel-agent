"""Single-responsibility domain agents used by the Supervisor."""

from __future__ import annotations

import importlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


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
            result = self.invoke_tool(params, facts)
            text = str(result).strip() or self.fallback_output(facts, "工具返回为空")
            artifact.update(
                {
                    "status": "completed",
                    "result_preview": text[:500],
                    "finished_at": datetime.now().isoformat(),
                }
            )
            self._emit(
                event_callback,
                "tool_completed",
                f"{self.name} 工具调用完成",
                {"tool": artifact["tool"], "preview": text[:300]},
            )
            return self._result(subtask, text, [artifact], started_at)
        except Exception as exc:
            fallback = self.fallback_output(facts, str(exc))
            artifact.update(
                {
                    "status": "failed",
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
        error: str = "",
        degraded: bool = False,
    ) -> Dict[str, Any]:
        return {
            "status": "completed",
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

    def invoke_tool(self, params: Dict[str, Any], facts: Dict[str, Any]) -> str:
        budget_text = str(params["budget_range"])
        numbers = [int(item) for item in re.findall(r"\d+", budget_text)]
        total_budget = max(numbers) if numbers else 0
        duration = int(params["duration"])
        group_size = int(params["group_size"])
        if total_budget:
            per_person_day = total_budget / max(duration * group_size, 1)
            level = "偏紧" if per_person_day < 350 else "充足" if per_person_day >= 900 else "适中"
            return (
                "## 预算分析\n"
                f"- 总预算参考：¥{total_budget}\n"
                f"- 人均每日预算：约 ¥{per_person_day:.0f}\n"
                f"- 预算状态：{level}\n"
                "- 建议分配：住宿 35%，交通 25%，餐饮 20%，门票活动 15%，机动 5%。"
            )
        return (
            "## 预算分析\n"
            f"- 当前预算描述：{budget_text or '未提供明确金额'}\n"
            "- 建议补充总预算金额；暂按住宿 35%、交通 25%、餐饮 20%、门票活动 15%、机动 5% 分配。"
        )


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
