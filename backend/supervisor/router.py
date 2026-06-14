"""
Supervisor 请求路由 —— 确定性规则 + 可选的 LLM 增强解析。

职责：
1. normalize_request：将 API/聊天 payload 规范化为统一的事实模型
2. find_missing_info：识别缺失的关键信息字段
3. select_agents：基于规则动态选择需要的领域 Agent
4. build_subtasks：为每个选中 Agent 生成中文指令
5. build_clarification_prompt：生成澄清问题（LLM 模式）

设计原则（需求文档 §10.2）：
- 规则路由作为基础兜底（零依赖、可预测）
- LLM 路由作为增强模式（更灵活、更智能）
- 两种模式可切换，规则模式不依赖 LLM 可用性
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ======================== 能力别名映射 ========================

# 将用户输入的各种中文/英文表达统一映射到内部 Agent 名称
CAPABILITY_ALIASES: Dict[str, str] = {
    # 航班
    "flight": "flight_agent",
    "flights": "flight_agent",
    "航班": "flight_agent",
    "飞机": "flight_agent",
    "机票": "flight_agent",
    # 铁路
    "train": "train_agent",
    "trains": "train_agent",
    "火车": "train_agent",
    "高铁": "train_agent",
    "动车": "train_agent",
    # 酒店
    "hotel": "hotel_agent",
    "hotels": "hotel_agent",
    "酒店": "hotel_agent",
    "住宿": "hotel_agent",
    "宾馆": "hotel_agent",
    "民宿": "hotel_agent",
    # 景点
    "attraction": "attraction_agent",
    "attractions": "attraction_agent",
    "景点": "attraction_agent",
    "活动": "attraction_agent",
    "景区": "attraction_agent",
    # 天气
    "weather": "weather_agent",
    "天气": "weather_agent",
    # 本地专家
    "local": "local_expert",
    "local_expert": "local_expert",
    "本地": "local_expert",
    "在地": "local_expert",
    "攻略": "local_expert",
    # 预算
    "budget": "budget_optimizer",
    "预算": "budget_optimizer",
}

# 默认选中的规划 Agent（当用户没有显式指定能力时）
# 包含酒店、景点、天气、本地专家、预算优化（不含交通，因为可能没有出发地）
DEFAULT_PLANNING_AGENTS = [
    "hotel_agent",
    "attraction_agent",
    "weather_agent",
    "local_expert",
    "budget_optimizer",
]

# ======================== 请求标准化 ========================

def normalize_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 API 和聊天 payload 规范化为统一的 Supervisor 事实模型。

    处理逻辑：
    1. 标准化 interests 字段（字符串→列表）
    2. 从 travel_dates 中提取 start_date 和 end_date
    3. 自动计算 duration（如果未提供但有日期）
    4. 补全所有可选字段的默认值

    Args:
        request: 原始请求字典，可能来自 API 表单或 /chat 解析结果

    Returns:
        标准化后的事实字典，包含所有核心字段
    """
    # --- 兴趣偏好标准化 ---
    interests = request.get("interests", [])
    if isinstance(interests, str):
        # "美食,徒步" → ["美食", "徒步"]
        interests = [item.strip() for item in re.split(r"[,，、]", interests) if item.strip()]
    elif not isinstance(interests, list):
        interests = [str(interests)] if interests else []

    # --- 日期处理 ---
    start_date = str(request.get("start_date", "")).strip()
    end_date = str(request.get("end_date", "")).strip()
    travel_dates = str(request.get("travel_dates", "")).strip()

    # 如果用户通过 travel_dates 描述日期范围，尝试提取具体日期
    if travel_dates and (not start_date or not end_date):
        date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", travel_dates)
        if date_matches:
            start_date = start_date or date_matches[0]
            end_date = end_date or date_matches[-1]

    # --- 天数计算 ---
    duration = _positive_int(request.get("duration"), default=0)
    if duration == 0 and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            duration = max(1, (end - start).days + 1)
        except ValueError:
            duration = 0

    # --- 组装标准化事实 ---
    return {
        # 出发地与目的地
        "departure": str(
            request.get("departure")
            or request.get("origin")
            or request.get("departure_city")
            or ""
        ).strip(),
        "destination": str(request.get("destination", "")).strip(),

        # 日期与天数
        "start_date": start_date,
        "end_date": end_date,
        "travel_dates": travel_dates,
        "duration": duration or 3,  # 默认 3 天

        # 预算与人数
        "budget_range": str(request.get("budget_range", "中等预算")).strip(),
        "group_size": _positive_int(request.get("group_size"), default=1),

        # 偏好
        "interests": interests,
        "transportation_preference": str(
            request.get("transportation_preference", "公共交通")
        ).strip(),
        "accommodation_preference": str(
            request.get("accommodation_preference", "酒店")
        ).strip(),

        # 特殊需求与能力
        "special_requirements": str(request.get("special_requirements", "")).strip(),
        "requested_capabilities": request.get("requested_capabilities", []),

        # 附加信息
        "travel_style": str(request.get("travel_style", "探索者")).strip(),
        "activity_level": str(request.get("activity_level", "适中")).strip(),
        "dietary_restrictions": str(request.get("dietary_restrictions", "")).strip(),
    }


# ======================== 缺失信息检测 ========================

def find_missing_info(facts: Dict[str, Any]) -> List[str]:
    """
    检测当前事实中缺失的关键信息字段。

    检测逻辑（按优先级）：
    1. destination 必须存在
    2. travel_dates 或 (start_date + end_date) 至少有一个
    3. 如果选中了交通 Agent，departure 必须存在

    Args:
        facts: normalize_request 返回的标准化事实

    Returns:
        缺失字段名称列表，如 ["destination", "travel_dates"]
    """
    missing: List[str] = []

    # 目的地是必须的
    if not facts.get("destination"):
        missing.append("destination")

    # 日期信息必须至少有一个
    if not facts.get("start_date") and not facts.get("travel_dates"):
        missing.append("travel_dates")

    # 如果用户想查交通但没有出发地
    requested = _normalize_capabilities(facts.get("requested_capabilities", []))
    if not facts.get("departure") and any(
        agent in requested for agent in ("flight_agent", "train_agent")
    ):
        missing.append("departure")

    return missing


# ======================== Agent 动态选择 ========================

def select_agents(facts: Dict[str, Any]) -> List[str]:
    """
    根据标准化请求动态选择需要的领域 Agent。

    选择策略（需求文档 §6.2）：
    1. 如果用户显式指定了 requested_capabilities，只执行那些 Agent
    2. 否则，默认选中 hotel/attraction/weather/local_expert/budget_optimizer
    3. 根据交通偏好和出发地，动态添加 flight_agent 和/或 train_agent：
       - 有出发地 + 偏好"飞机/航班" → 添加 flight_agent
       - 有出发地 + 偏好"高铁/火车" → 添加 train_agent
       - 有出发地 + 偏好"混合/均可/公共交通" → 同时添加两者
    4. 如果用户说"无需住宿"等，移除 hotel_agent

    Args:
        facts: 标准化事实

    Returns:
        去重后的 Agent 名称列表，保持优先级顺序
    """
    # --- 显式指定模式 ---
    explicit = _normalize_capabilities(facts.get("requested_capabilities", []))
    if explicit:
        selected = explicit
    else:
        # --- 默认模式 ---
        selected = list(DEFAULT_PLANNING_AGENTS)

        # 如果用户不需要住宿，移除酒店 Agent
        accommodation = str(facts.get("accommodation_preference", "")).lower()
        if any(token in accommodation for token in ("无需", "不需要", "当天往返", "no hotel")):
            if "hotel_agent" in selected:
                selected.remove("hotel_agent")

    # --- 交通 Agent 动态添加 ---
    departure = str(facts.get("departure", "")).strip()
    preference = str(facts.get("transportation_preference", "")).lower()

    if departure:
        # 有出发地时才添加交通 Agent
        if any(token in preference for token in ("飞机", "航班", "flight", "机票")):
            selected.insert(0, "flight_agent")
        elif any(token in preference for token in ("高铁", "火车", "动车", "train")):
            selected.insert(0, "train_agent")
        elif any(token in preference for token in ("混合", "均可", "不限", "公共交通", "public")):
            # 混合交通：航班 + 铁路都选
            selected[0:0] = ["flight_agent", "train_agent"]

    return _deduplicate(selected)


# ======================== 子任务构建 ========================

def build_subtasks(
    facts: Dict[str, Any],
    selected_agents: Iterable[str],
) -> List[Dict[str, str]]:
    """
    为每个选中的 Agent 生成中文子任务指令。

    指令包含具体的目的地、出发地、天数、兴趣等上下文，
    让 Agent 可以直接理解要做什么。

    Args:
        facts: 标准化事实
        selected_agents: 选中的 Agent 名称列表

    Returns:
        子任务列表 [{"agent": "flight_agent", "instruction": "查询..."}, ...]
    """
    destination = facts.get("destination") or "目的地"
    departure = facts.get("departure") or "出发地"
    duration = facts.get("duration", 3)
    interests = "、".join(facts.get("interests", [])) or "综合体验"

    # 日期信息用于往返查询
    start_date = facts.get("start_date") or ""
    end_date = facts.get("end_date") or ""

    # 各 Agent 的指令模板
    instructions = {
        "flight_agent": (
            f"查询往返航班：\n"
            f"1. 去程：{departure} → {destination}，日期 {start_date or '待确认'}\n"
            f"2. 返程：{destination} → {departure}，日期 {end_date or '待确认'}\n"
            f"请分别列出去程和返程的航班方案，比较直飞/中转、价格和时刻。"
        ),
        "train_agent": (
            f"查询往返高铁/火车：\n"
            f"1. 去程：{departure} → {destination}，日期 {start_date or '待确认'}\n"
            f"2. 返程：{destination} → {departure}，日期 {end_date or '待确认'}\n"
            f"请分别列出去程和返程的车次方案，比较时间、价格和舒适度。"
        ),
        "hotel_agent": (
            f"查询{destination}的住宿选项。"
            f"考虑{duration}天行程的通勤便利性、预算匹配度和用户偏好，给出 3-5 个推荐。"
        ),
        "attraction_agent": (
            f"围绕「{interests}」主题，查询{destination}的热门景点和隐藏宝藏。"
            f"形成候选清单，标注适合{duration}天行程的优先级排序。"
        ),
        "weather_agent": (
            f"查询{destination}在行程期间的天气预报。"
            f"给出室内外活动调整建议、穿衣指南和特殊天气预警。"
        ),
        "local_expert": (
            f"补充{destination}的在地体验信息："
            f"特色美食、本地餐饮推荐、文化礼仪、交通贴士、常见避坑指南。"
        ),
        "budget_optimizer": (
            f"核对{duration}天{destination}行程的预算合理性。"
            f"识别超支风险，给出各项开销的分配建议和降级方案。"
        ),
    }

    return [
        {"agent": agent, "instruction": instructions[agent]}
        for agent in selected_agents
        if agent in instructions
    ]


# ======================== 澄清问题生成 ========================

def build_clarification_prompt(
    extracted: Dict[str, Any],
    missing: List[str],
) -> Tuple[str, str]:
    """
    生成面向用户的澄清提示。

    当检测到缺失信息时，生成友好的中文提示，
    引导用户补充必要信息。

    Args:
        extracted: 已提取的事实
        missing: 缺失字段列表

    Returns:
        (prompt_title, prompt_body) 元组
    """
    if not missing:
        return ("信息完整", "所有必要信息已收集，可以开始规划。")

    # 已知信息摘要
    known_items = []
    if extracted.get("destination"):
        known_items.append(f"📍 目的地：{extracted['destination']}")
    if extracted.get("departure"):
        known_items.append(f"🚀 出发地：{extracted['departure']}")
    if extracted.get("start_date"):
        known_items.append(f"📅 出发日期：{extracted['start_date']}")
    if extracted.get("duration"):
        known_items.append(f"⏰ 天数：{extracted['duration']}天")
    if extracted.get("group_size"):
        known_items.append(f"👥 人数：{extracted['group_size']}人")
    if extracted.get("budget_range"):
        known_items.append(f"💰 预算：{extracted['budget_range']}")

    # 缺失信息提示映射
    missing_hints = {
        "destination": "请告诉我您想去哪个城市/地区旅行？",
        "travel_dates": "请告诉我您计划什么时候出发？（如 2026-08-01）",
        "departure": "请告诉我您从哪个城市出发？",
    }

    # 构建提示
    lines = ["😊 我已经了解到以下信息："]
    lines.extend(known_items)
    lines.append("")
    lines.append("💡 还需要补充以下信息：")
    for field in missing:
        hint = missing_hints.get(field, f"请补充 {field}")
        lines.append(f"  • {hint}")

    prompt_body = "\n".join(lines)
    prompt_title = "信息待补充" if len(missing) > 1 else f"需要{missing[0]}"

    return prompt_title, prompt_body


# ======================== 辅助函数 ========================

def _normalize_capabilities(raw: Any) -> List[str]:
    """
    将用户输入的能力描述标准化为内部 Agent 名称列表。

    支持：
    - 字符串："酒店,天气" → ["hotel_agent", "weather_agent"]
    - 列表：["航班", "景点"] → ["flight_agent", "attraction_agent"]
    - 混合中英文

    Args:
        raw: 原始能力描述

    Returns:
        去重后的内部 Agent 名称列表
    """
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
    """
    安全地将值转换为正整数。

    Args:
        value: 任意输入值
        default: 转换失败或非正数时的默认值

    Returns:
        正整数
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _deduplicate(values: Iterable[str]) -> List[str]:
    """
    对字符串列表去重，保持原始顺序。

    Args:
        values: 可能包含重复的字符串序列

    Returns:
        去重后的列表
    """
    result: List[str] = []
    seen: set = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
