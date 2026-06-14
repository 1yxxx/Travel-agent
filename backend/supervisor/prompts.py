"""
集中式提示词管理 —— 所有 LLM 提示词统一存放，支持版本化和 A/B 测试。

设计原则：
- 提示词与代码分离，便于调优和复用
- 每个提示词函数接收结构化参数，返回完整的 SystemMessage / HumanMessage
- 支持 Jinja2 风格的变量插值，但保持纯 Python 以降低依赖
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


# ======================== 意图解析提示词 ========================

INTENT_PARSE_SYSTEM = """你是"旅小智"智能旅行规划系统的意图解析器。

你的任务是：从用户的自然语言描述中，**精确提取**旅行规划的约束信息，并识别缺失的关键字段。

## 提取规则

请从用户输入中提取以下字段（如果存在）：
1. **departure** (str | null): 出发城市（用户明确提到"从XX出发"、"从XX飞"等）
2. **destination** (str | null): 目的地城市/地区
3. **start_date** (str | null): 出发日期，统一格式 YYYY-MM-DD
4. **end_date** (str | null): 返回日期，统一格式 YYYY-MM-DD
5. **duration** (int | null): 旅行天数
6. **budget_range** (str | null): 预算范围，如"经济型（300-800元/天）"、"中等预算"、"豪华型"
7. **group_size** (int | null): 出行人数
8. **interests** (list[str]): 兴趣偏好，如 ["美食", "历史", "自然风光"]
9. **transportation_preference** (str | null): 交通偏好（飞机/高铁/自驾/公共交通）
10. **accommodation_preference** (str | null): 住宿偏好（酒店/民宿/青旅）

## 日期处理规则
- 如果用户说"下周"、"下个月"等相对时间，**不要猜测具体日期**，在 missing 中标记
- 如果用户说"国庆"、"五一"等节日，**不要猜测具体日期**，在 clarification 中询问
- 如果用户给出了具体日期（如"8月15日"），转换为 YYYY-MM-DD 格式

## 输出格式

严格返回 JSON，包含：
- **extracted**: 提取到的信息字典（只包含有值的字段）
- **missing**: 缺失的关键信息列表（必须包含 destination, time_info 至少一个）
- **confidence**: 理解的置信度（0.0-1.0）
- **clarification**: 需要用户澄清的问题（如果有，用中文自然语言描述）

关键信息定义：destination 和 time_info（start_date/end_date/duration 至少一个）
"""


def build_intent_parse_messages(user_message: str, current_date: str = "") -> List[Dict[str, str]]:
    """
    构建意图解析的消息列表。

    Args:
        user_message: 用户的自然语言输入
        current_date: 当前日期字符串，用于帮助 LLM 理解相对时间
    """
    if not current_date:
        current_date = datetime.now().strftime("%Y年%m月%d日")

    return [
        {"role": "system", "content": INTENT_PARSE_SYSTEM},
        {
            "role": "user",
            "content": f"用户说：{user_message}\n\n今天是 {current_date}",
        },
    ]


# ======================== Agent 子任务理解提示词 ========================

AGENT_SUBTASK_SYSTEM = """你是旅行规划系统中的一个领域专家 Agent：**{agent_display_name}**。

你的职责是：基于 Supervisor 分配的子任务和共享上下文，调用工具获取数据，然后**用自然语言总结输出**。

## 执行步骤
1. 理解子任务指令和上下文
2. 调用对应的工具获取数据
3. 对工具返回的结果进行结构化总结

## 输出要求
- 使用 Markdown 格式输出
- 给出具体的数据和建议，而非泛泛而谈
- 如果数据不完整，说明哪些信息需要用户补充
- 标注数据来源和置信度

## 当前上下文
- 目的地：{destination}
- 出发地：{departure}
- 日期：{start_date} 至 {end_date}（共 {duration} 天）
- 人数：{group_size} 人
- 预算：{budget_range}
- 兴趣：{interests}
"""


def build_agent_subtask_prompt(
    agent_name: str,
    agent_display_name: str,
    instruction: str,
    facts: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    构建单个 Agent 的子任务提示词。

    Args:
        agent_name: Agent 内部名称（如 flight_agent）
        agent_display_name: Agent 展示名称（如 航班搜索专家）
        instruction: Supervisor 分配的子任务指令
        facts: 共享事实上下文
    """
    system = AGENT_SUBTASK_SYSTEM.format(
        agent_display_name=agent_display_name,
        destination=facts.get("destination", "未指定"),
        departure=facts.get("departure", "未提供"),
        start_date=facts.get("start_date", "待确认"),
        end_date=facts.get("end_date", "待确认"),
        duration=facts.get("duration", 3),
        group_size=facts.get("group_size", 1),
        budget_range=facts.get("budget_range", "中等预算"),
        interests="、".join(facts.get("interests", [])) or "综合体验",
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请执行以下子任务：\n\n{instruction}"},
    ]


# ======================== 反思/质量检查提示词 ========================

REFLECTION_SYSTEM = """你是旅行规划系统的**质量检查员**。

你的任务是：审查已生成的旅行方案，检查以下维度：

## 检查清单

### 1. 信息完整性
- 是否所有必需的维度都已覆盖？（交通、住宿、景点、天气、预算）
- 是否有缺失的关键信息？

### 2. 逻辑一致性
- 逐日行程是否合理？（距离、时间、体力消耗）
- 交通衔接是否可行？
- 酒店位置与景点分布是否匹配？

### 3. 预算合理性
- 总预算是否与各项开销匹配？
- 是否有明显的超支风险？

### 4. 用户体验
- 行程节奏是否合理？（不要太赶也不要太空）
- 是否考虑了天气因素？
- 是否有备选方案？

## 输出格式

返回 JSON：
- **passed** (bool): 是否通过质量检查
- **completion_status** (str): "complete" 或 "partial"
- **warnings** (list[str]): 发现的问题列表
- **suggestions** (list[str]): 改进建议
- **confidence** (float): 对方案质量的信心（0.0-1.0）
"""


def build_reflection_messages(
    final_output: str,
    collector_output: Dict[str, Any],
    missing_info: List[str],
    failed_agents: List[str],
    degraded_agents: List[str],
) -> List[Dict[str, str]]:
    """
    构建质量反思的消息列表。

    Args:
        final_output: 当前生成的最终方案文本
        collector_output: 收集器汇总的输出
        missing_info: 缺失的信息字段
        failed_agents: 失败的 Agent 列表
        degraded_agents: 降级的 Agent 列表
    """
    context_parts = []

    if missing_info:
        context_parts.append(f"## 缺失信息\n- " + "\n- ".join(missing_info))
    if failed_agents:
        context_parts.append(f"## 失败 Agent\n- " + "\n- ".join(failed_agents))
    if degraded_agents:
        context_parts.append(f"## 降级 Agent\n- " + "\n- ".join(degraded_agents))

    context = "\n\n".join(context_parts) if context_parts else "所有 Agent 均正常完成"

    user_message = f"""## 执行上下文
{context}

## 生成的旅行方案
{final_output[:3000]}

请按检查清单审查方案质量。"""

    return [
        {"role": "system", "content": REFLECTION_SYSTEM},
        {"role": "user", "content": user_message},
    ]


# ======================== 行程总结提示词 ========================

SUMMARIZER_SYSTEM = """你是旅行规划系统的**最终方案撰写者**。

你的任务是：将各个领域 Agent 的输出整合为一份**完整、流畅、实用的旅行方案**。

## 输出结构
1. **需求摘要**：目的地、时间、人数、预算概览
2. **交通方案**：去程/返程交通建议
3. **住宿方案**：推荐酒店及位置理由
4. **逐日行程**：每天的详细安排（上午/下午/晚上）
5. **景点清单**：推荐景点及简要说明
6. **天气贴士**：行程期间天气及穿衣建议
7. **在地建议**：当地美食、礼仪、避坑信息
8. **预算分析**：开销预估和分配建议
9. **注意事项**：风险提示和备选方案

## 写作要求
- 使用 Markdown 格式，层次分明
- 语言亲切自然，像一位贴心的旅行顾问
- 给出具体建议，而非泛泛而谈
- 标注信息来源（尤其是降级/不确定的部分）
"""


def build_summarizer_messages(
    facts: Dict[str, Any],
    sections: Dict[str, str],
    itinerary: str,
    warnings: List[str],
) -> List[Dict[str, str]]:
    """
    构建最终方案总结的消息列表。

    Args:
        facts: 共享事实上下文
        sections: 各 Agent 的输出内容 {agent_name: content}
        itinerary: 逐日行程框架
        warnings: 反思阶段发现的警告
    """
    context_parts = [f"## 需求\n"
                     f"- 目的地：{facts.get('destination', '未知')}\n"
                     f"- 出发地：{facts.get('departure', '未提供')}\n"
                     f"- 日期：{facts.get('start_date', '待确认')} 至 {facts.get('end_date', '待确认')}\n"
                     f"- 天数：{facts.get('duration', 3)} 天\n"
                     f"- 人数：{facts.get('group_size', 1)} 人\n"
                     f"- 预算：{facts.get('budget_range', '中等预算')}\n"
                     f"- 兴趣：{'、'.join(facts.get('interests', [])) or '综合体验'}"]

    for name, content in sections.items():
        if content and len(content) > 10:
            context_parts.append(f"## {name}\n{content[:1500]}")

    if itinerary:
        context_parts.append(f"## 行程框架\n{itinerary}")

    if warnings:
        context_parts.append(f"## 注意事项\n" + "\n".join(f"- {w}" for w in warnings))

    user_message = "\n\n".join(context_parts)
    user_message += "\n\n请将以上信息整合为一份完整的旅行方案。"

    return [
        {"role": "system", "content": SUMMARIZER_SYSTEM},
        {"role": "user", "content": user_message},
    ]


# ======================== 澄清提示词 ========================

CLARIFICATION_SYSTEM = """你是"旅小智"旅行规划助手，负责在用户信息不完整时友好地提问。

## 你的风格
- 热情、专业、像朋友一样交流
- 每次只问 2-3 个最关键的问题
- 给出具体选项帮助用户快速回答
- 使用 Emoji 让对话更生动

## 当前已知信息
用户已经告诉你了这些信息（如果有的话），不需要重复询问。
"""


def build_clarification_message(
    extracted: Dict[str, Any],
    missing: List[str],
) -> List[Dict[str, str]]:
    """
    构建澄清问题的消息列表。

    Args:
        extracted: 已提取的信息
        missing: 缺失的字段列表
    """
    known_parts = []
    if extracted.get("destination"):
        known_parts.append(f"- 目的地：{extracted['destination']}")
    if extracted.get("departure"):
        known_parts.append(f"- 出发地：{extracted['departure']}")
    if extracted.get("start_date"):
        known_parts.append(f"- 出发日期：{extracted['start_date']}")
    if extracted.get("duration"):
        known_parts.append(f"- 天数：{extracted['duration']}天")
    if extracted.get("group_size"):
        known_parts.append(f"- 人数：{extracted['group_size']}人")
    if extracted.get("budget_range"):
        known_parts.append(f"- 预算：{extracted['budget_range']}")
    if extracted.get("interests"):
        known_parts.append(f"- 兴趣：{', '.join(extracted['interests'])}")

    known_text = "\n".join(known_parts) if known_parts else "暂无"

    system = CLARIFICATION_SYSTEM + f"\n## 已知信息\n{known_text}"

    missing_text = "、".join(missing)
    user_msg = f"还需要了解的信息：{missing_text}\n\n请友好地向用户提问，引导用户补充这些信息。"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


# ======================== Agent 展示名称映射 ========================

AGENT_DISPLAY_NAMES = {
    "flight_agent": "航班搜索专家",
    "train_agent": "铁路搜索专家",
    "hotel_agent": "酒店推荐专家",
    "attraction_agent": "景点推荐专家",
    "weather_agent": "天气分析专家",
    "local_expert": "本地生活专家",
    "budget_optimizer": "预算分析专家",
    "itinerary_planner": "行程规划师",
}
