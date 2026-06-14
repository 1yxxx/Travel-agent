"""
ReAct 意图路由 — 分析用户消息，决定下一步动作。

核心逻辑：
- 携带对话历史 + 累积事实，由 LLM 判断意图
- 4 种意图：provide_info / create_plan / modify_plan / chat
- LLM 不可用时降级为关键词规则匹配
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.storage.chat_session import ChatSession, ChatMessage


# ======================== LLM Prompt ========================

INTENT_ANALYSIS_SYSTEM = """你是旅小智的对话意图分析器。分析用户消息，判断意图并提取信息。

## 意图分类

1. **provide_info**: 用户提供了新的旅行需求信息
   - 提取结构化字段：destination, departure, start_date, end_date, budget_range, group_size, interests, accommodation_preference, transportation_preference
   - 注意用户可能用自然语言表达（"下周三"→日期，"两个人"→group_size=2，"3000块"→budget）
   - 只提取用户明确提到的信息，不要编造

2. **create_plan**: 用户确认要生成旅行计划
   - 用户说"开始规划""帮我生成""可以了""就这样"等
   - 检查 accumulated_facts 中是否有 destination + 日期信息

3. **modify_plan**: 用户想修改已有计划
   - 用户说"换一个""改成""不要这个"等
   - 只在存在 active_task_id 时才可能触发

4. **chat**: 闲聊、问候、帮助、感谢等
   - 与旅行规划无关的对话

## 当前累积信息
{accumulated_facts}

## 对话历史
{chat_history}

## 今天日期
{today}

返回 JSON（不要 markdown 代码块，纯 JSON）:
{{
    "intent": "provide_info",
    "extracted": {{}},
    "updated_facts": {{}},
    "missing_fields": [],
    "clarification": "",
    "can_proceed": false,
    "confidence": 0.85,
    "direct_reply": ""
}}
"""


# ======================== 关键词降级规则 ========================

# 创建计划触发词
CREATE_PLAN_KEYWORDS = [
    "开始规划", "生成方案", "帮我规划", "帮我生成", "可以了", "就这样",
    "开始吧", "生成计划", "规划吧", "确认", "没问题", "好的",
]

# 修改计划触发词
MODIFY_PLAN_KEYWORDS = [
    "换", "改成", "修改", "调整", "不要", "换成", "改一下",
    "便宜点", "贵一点", "再加", "减少", "去掉",
]

# 字段提取规则（正则）
FIELD_EXTRACTORS = {
    "destination": [
        r"去(?:往|到)?(.{1,8})[玩旅游]",
        r"想去(.{1,8})",
        r"目的地[是为:：]\s*(.{1,8})",
    ],
    "departure": [
        r"从(.{1,6})出发",
        r"出发地[是为:：]\s*(.{1,6})",
    ],
    "budget_range": [
        r"预算[是为:：]?\s*(\d+)[块元]",
        r"(\d+)[块元]预算",
        r"预算\s*(\d+)",
    ],
    "group_size": [
        r"(\d+)个?人",
        r"(\d+)人[团行]",
    ],
    "duration": [
        r"(\d+)天",
        r"玩(\d+)天",
    ],
}


def _rule_based_intent(user_message: str, session: ChatSession) -> Dict[str, Any]:
    """LLM 不可用时的关键词规则降级。"""
    msg = user_message.strip()
    facts = dict(session.accumulated_facts)
    missing = []

    # 检查修改意图
    has_task = bool(session.active_task_id)
    for kw in MODIFY_PLAN_KEYWORDS:
        if kw in msg and has_task:
            return {
                "intent": "modify_plan",
                "extracted": {},
                "updated_facts": facts,
                "missing_fields": [],
                "clarification": "请描述您想如何修改当前计划。",
                "can_proceed": False,
                "confidence": 0.5,
                "direct_reply": "",
            }

    # 检查创建意图
    for kw in CREATE_PLAN_KEYWORDS:
        if kw in msg:
            has_dest = bool(facts.get("destination"))
            has_date = bool(facts.get("start_date"))
            if has_dest and has_date:
                return {
                    "intent": "create_plan",
                    "extracted": {},
                    "updated_facts": facts,
                    "missing_fields": [],
                    "clarification": "",
                    "can_proceed": True,
                    "confidence": 0.7,
                    "direct_reply": "",
                }
            else:
                if not has_dest:
                    missing.append("destination")
                if not has_date:
                    missing.append("start_date")
                return {
                    "intent": "provide_info",
                    "extracted": {},
                    "updated_facts": facts,
                    "missing_fields": missing,
                    "clarification": f"还需要以下信息：{', '.join(missing)}",
                    "can_proceed": False,
                    "confidence": 0.6,
                    "direct_reply": "",
                }

    # 尝试提取字段
    extracted = {}
    for field, patterns in FIELD_EXTRACTORS.items():
        for pattern in patterns:
            match = re.search(pattern, msg)
            if match:
                value = match.group(1).strip()
                if field == "budget_range":
                    amount = int(value)
                    if amount < 800:
                        extracted[field] = "经济型 (300-800元/天)"
                    elif amount < 3000:
                        extracted[field] = "中等预算 (1500-3000元/天)"
                    else:
                        extracted[field] = "高端旅行 (3000-6000元/天)"
                elif field == "group_size":
                    extracted[field] = int(value)
                elif field == "duration":
                    extracted[field] = int(value)
                else:
                    extracted[field] = value
                break

    if extracted:
        facts.update({k: v for k, v in extracted.items() if v})
        # 检查缺失字段
        required = ["destination", "start_date", "end_date"]
        missing = [f for f in required if not facts.get(f)]
        missing_fields_text = "、".join(missing) if missing else ""

        return {
            "intent": "provide_info",
            "extracted": extracted,
            "updated_facts": facts,
            "missing_fields": missing,
            "clarification": f"已记录您的需求。{'还需要：' + missing_fields_text if missing_fields_text else '信息已齐全，可以开始规划了！'}",
            "can_proceed": len(missing) == 0,
            "confidence": 0.5,
            "direct_reply": "",
        }

    # 默认：闲聊
    return {
        "intent": "chat",
        "extracted": {},
        "updated_facts": facts,
        "missing_fields": [],
        "clarification": "",
        "can_proceed": False,
        "confidence": 0.5,
        "direct_reply": "您好！我是旅小智，您的 AI 旅行规划助手。请告诉我您想去哪里旅行？",
    }


# ======================== IntentRouter ========================

class IntentRouter:
    """
    ReAct 意图路由器。

    使用方式:
        router = IntentRouter(llm_config)
        result = router.analyze(user_message, session)
    """

    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        self._llm_config = llm_config
        self._llm = None
        if llm_config:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    model=llm_config.get("model", "gpt-4o-mini"),
                    api_key=llm_config.get("api_key", ""),
                    base_url=llm_config.get("base_url", ""),
                    temperature=0.1,
                )
            except Exception:
                self._llm = None

    def analyze(self, user_message: str, session: ChatSession) -> Dict[str, Any]:
        """
        分析用户消息意图。

        Returns:
            {
                "intent": "provide_info|create_plan|modify_plan|chat",
                "extracted": {...},
                "updated_facts": {...},
                "missing_fields": [...],
                "clarification": "...",
                "can_proceed": bool,
                "confidence": float,
                "direct_reply": "..."
            }
        """
        # 优先 LLM
        if self._llm:
            try:
                return self._llm_analyze(user_message, session)
            except Exception:
                pass

        # 降级规则匹配
        return _rule_based_intent(user_message, session)

    def _llm_analyze(self, user_message: str, session: ChatSession) -> Dict[str, Any]:
        from langchain_core.messages import HumanMessage, SystemMessage
        from datetime import date

        system_prompt = INTENT_ANALYSIS_SYSTEM.format(
            accumulated_facts=json.dumps(session.accumulated_facts, ensure_ascii=False, indent=2),
            chat_history=session.get_chat_history_text(max_messages=8),
            today=date.today().strftime("%Y年%m月%d日"),
        )

        response = self._llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])

        text = response.content.strip()

        # 提取 JSON
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                return self._normalize_result(result, session)
            except json.JSONDecodeError:
                pass

        # JSON 解析失败 → 降级
        return _rule_based_intent(user_message, session)

    def _normalize_result(self, result: dict, session: ChatSession) -> dict:
        """标准化 LLM 返回结果，确保字段完整。"""
        defaults = {
            "intent": "chat",
            "extracted": {},
            "updated_facts": dict(session.accumulated_facts),
            "missing_fields": [],
            "clarification": "",
            "can_proceed": False,
            "confidence": 0.5,
            "direct_reply": "",
        }
        for key, default in defaults.items():
            if key not in result:
                result[key] = default

        # 合并 extracted 到 updated_facts
        extracted = result.get("extracted", {})
        if extracted and result["intent"] == "provide_info":
            merged = dict(session.accumulated_facts)
            merged.update({k: v for k, v in extracted.items() if v})
            result["updated_facts"] = merged

        # 检查是否可创建计划
        if result["intent"] == "create_plan":
            facts = result.get("updated_facts", {})
            has_dest = bool(facts.get("destination"))
            has_date = bool(facts.get("start_date") or facts.get("end_date"))
            result["can_proceed"] = has_dest and has_date

        return result


# ======================== 修改意图分析 ========================

MODIFICATION_ANALYSIS_SYSTEM = """你是旅小智的计划修改分析器。

分析用户修改意见，确定哪些 Agent 需要重新执行。

## 可选 Agent
- flight_agent: 航班查询
- train_agent: 铁路查询
- hotel_agent: 酒店推荐
- attraction_agent: 景点推荐
- weather_agent: 天气分析
- local_expert: 本地攻略
- budget_optimizer: 预算分析
- itinerary_planner: 行程规划

## 规则
- 目的地变化 → 全部重跑
- 日期/天数变化 → itinerary_planner + budget_optimizer (+ 天气如有日期变化)
- 预算变化 → budget_optimizer (+ 酒店/航班如有价格约束)
- 酒店偏好变化 → hotel_agent + budget_optimizer
- 交通偏好变化 → flight_agent/train_agent + budget_optimizer
- 兴趣变化 → attraction_agent + itinerary_planner
- 餐饮变化 → local_expert + itinerary_planner

## 当前计划
{plan_summary}

## 用户修改意见
{feedback}

返回 JSON:
{{
    "affected_agents": ["hotel_agent", "budget_optimizer"],
    "reason": "...",
    "updated_facts": {{}}
}}
"""


def analyze_modification_intent(
    feedback: str,
    plan_summary: str,
    llm=None,
) -> Dict[str, Any]:
    """
    分析修改意图，确定受影响 Agent。

    Returns:
        {"affected_agents": [...], "reason": "...", "updated_facts": {...}}
    """
    if llm:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system_prompt = MODIFICATION_ANALYSIS_SYSTEM.format(
                plan_summary=plan_summary,
                feedback=feedback,
            )
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=feedback),
            ])
            text = response.content.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass

    # 降级：关键词匹配
    return _rule_based_modification_analysis(feedback)


def _rule_based_modification_analysis(feedback: str) -> Dict[str, Any]:
    """修改意图关键词降级。"""
    msg = feedback.strip()
    agents = set()

    if any(kw in msg for kw in ["酒店", "住宿", "宾馆", "民宿"]):
        agents.update(["hotel_agent", "budget_optimizer"])
    if any(kw in msg for kw in ["航班", "飞机", "机票"]):
        agents.update(["flight_agent", "budget_optimizer"])
    if any(kw in msg for kw in ["高铁", "火车", "动车"]):
        agents.update(["train_agent", "budget_optimizer"])
    if any(kw in msg for kw in ["景点", "景区", "玩", "逛", "自然", "购物", "博物馆"]):
        agents.update(["attraction_agent", "itinerary_planner"])
    if any(kw in msg for kw in ["天气"]):
        agents.add("weather_agent")
    if any(kw in msg for kw in ["吃", "美食", "餐厅", "小吃"]):
        agents.update(["local_expert", "itinerary_planner"])
    if any(kw in msg for kw in ["预算", "价格", "便宜", "贵", "省钱"]):
        agents.add("budget_optimizer")
    if any(kw in msg for kw in ["行程", "安排", "再加", "去掉一天"]):
        agents.update(["itinerary_planner", "budget_optimizer"])
    if any(kw in msg for kw in ["目的地", "城市", "不去", "换成", "改去"]):
        # 目的地变化 → 全部重跑
        agents.update([
            "flight_agent", "train_agent", "hotel_agent",
            "attraction_agent", "weather_agent", "local_expert",
            "budget_optimizer", "itinerary_planner",
        ])

    # 默认至少包含 budget_optimizer
    if not agents:
        agents.update(["budget_optimizer", "itinerary_planner"])

    return {
        "affected_agents": sorted(agents),
        "reason": f"关键词规则匹配到 {len(agents)} 个受影响 Agent",
        "updated_facts": {},
    }
