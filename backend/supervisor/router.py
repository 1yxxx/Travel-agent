"""Deterministic request routing for the Supervisor."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List


CAPABILITY_ALIASES = {
    "flight": "flight_agent",
    "flights": "flight_agent",
    "航班": "flight_agent",
    "飞机": "flight_agent",
    "train": "train_agent",
    "trains": "train_agent",
    "火车": "train_agent",
    "高铁": "train_agent",
    "hotel": "hotel_agent",
    "hotels": "hotel_agent",
    "酒店": "hotel_agent",
    "住宿": "hotel_agent",
    "attraction": "attraction_agent",
    "attractions": "attraction_agent",
    "景点": "attraction_agent",
    "活动": "attraction_agent",
    "weather": "weather_agent",
    "天气": "weather_agent",
    "local": "local_expert",
    "local_expert": "local_expert",
    "本地": "local_expert",
    "在地": "local_expert",
    "budget": "budget_optimizer",
    "预算": "budget_optimizer",
}

DEFAULT_PLANNING_AGENTS = [
    "hotel_agent",
    "attraction_agent",
    "weather_agent",
    "local_expert",
    "budget_optimizer",
]


def normalize_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize API and chat payloads into one Supervisor fact model."""
    interests = request.get("interests", [])
    if isinstance(interests, str):
        interests = [item.strip() for item in re.split(r"[,，、]", interests) if item.strip()]
    elif not isinstance(interests, list):
        interests = [str(interests)] if interests else []

    start_date = str(request.get("start_date", "")).strip()
    end_date = str(request.get("end_date", "")).strip()
    travel_dates = str(request.get("travel_dates", "")).strip()
    if travel_dates and (not start_date or not end_date):
        date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", travel_dates)
        if date_matches:
            start_date = start_date or date_matches[0]
            end_date = end_date or date_matches[-1]

    duration = _positive_int(request.get("duration"), default=0)
    if duration == 0 and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            duration = max(1, (end - start).days + 1)
        except ValueError:
            duration = 0

    return {
        "departure": str(
            request.get("departure")
            or request.get("origin")
            or request.get("departure_city")
            or ""
        ).strip(),
        "destination": str(request.get("destination", "")).strip(),
        "start_date": start_date,
        "end_date": end_date,
        "travel_dates": travel_dates,
        "duration": duration or 3,
        "budget_range": str(request.get("budget_range", "中等预算")).strip(),
        "group_size": _positive_int(request.get("group_size"), default=1),
        "interests": interests,
        "transportation_preference": str(
            request.get("transportation_preference", "公共交通")
        ).strip(),
        "accommodation_preference": str(
            request.get("accommodation_preference", "酒店")
        ).strip(),
        "special_requirements": str(request.get("special_requirements", "")).strip(),
        "requested_capabilities": request.get("requested_capabilities", []),
    }


def find_missing_info(facts: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not facts.get("destination"):
        missing.append("destination")
    if not facts.get("start_date") and not facts.get("travel_dates"):
        missing.append("travel_dates")
    requested = _normalize_capabilities(facts.get("requested_capabilities", []))
    if not facts.get("departure") and any(
        agent in requested for agent in ("flight_agent", "train_agent")
    ):
        missing.append("departure")
    return missing


def select_agents(facts: Dict[str, Any]) -> List[str]:
    """Select only the agents required by the normalized request."""
    explicit = _normalize_capabilities(facts.get("requested_capabilities", []))
    if explicit:
        selected = explicit
    else:
        selected = list(DEFAULT_PLANNING_AGENTS)
        accommodation = str(facts.get("accommodation_preference", "")).lower()
        if any(token in accommodation for token in ("无需", "不需要", "当天往返", "no hotel")):
            selected.remove("hotel_agent")

    departure = str(facts.get("departure", "")).strip()
    preference = str(facts.get("transportation_preference", "")).lower()
    if departure:
        if any(token in preference for token in ("飞机", "航班", "flight")):
            selected.insert(0, "flight_agent")
        elif any(token in preference for token in ("高铁", "火车", "动车", "train")):
            selected.insert(0, "train_agent")
        elif any(token in preference for token in ("混合", "均可", "不限", "公共交通", "public")):
            selected[0:0] = ["flight_agent", "train_agent"]

    return _deduplicate(selected)


def build_subtasks(facts: Dict[str, Any], selected_agents: Iterable[str]) -> List[Dict[str, str]]:
    destination = facts.get("destination") or "目的地"
    departure = facts.get("departure") or "出发地"
    duration = facts.get("duration", 3)
    interests = "、".join(facts.get("interests", [])) or "综合体验"
    instructions = {
        "flight_agent": f"查询{departure}到{destination}的可用航班并给出选择依据。",
        "train_agent": f"查询{departure}到{destination}的高铁或火车并给出选择依据。",
        "hotel_agent": f"查询{destination}住宿，兼顾预算、位置和{duration}天行程通勤。",
        "attraction_agent": f"围绕{interests}查询{destination}景点并形成候选清单。",
        "weather_agent": f"查询{destination}行程期间天气并给出室内外调整建议。",
        "local_expert": f"补充{destination}在地体验、餐饮、礼仪和避坑信息。",
        "budget_optimizer": f"核对{duration}天行程预算，识别超支风险并给出降级方案。",
    }
    return [
        {"agent": agent, "instruction": instructions[agent]}
        for agent in selected_agents
        if agent in instructions
    ]


def _normalize_capabilities(raw: Any) -> List[str]:
    if isinstance(raw, str):
        values = [item.strip() for item in re.split(r"[,，、]", raw) if item.strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        values = []
    return _deduplicate(
        CAPABILITY_ALIASES.get(value.lower(), CAPABILITY_ALIASES.get(value, value))
        for value in values
        if CAPABILITY_ALIASES.get(value.lower(), CAPABILITY_ALIASES.get(value, value))
        in set(CAPABILITY_ALIASES.values())
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _deduplicate(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
