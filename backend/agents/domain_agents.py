"""
单一职责的领域 Agent —— 由 Supervisor 调度执行。

每个 Agent 遵循统一的执行范式（需求文档 §10.2）：
receive_subtask → call_llm（可选）→ invoke_tool → summarize_output

V1 实现：
- 每个 Agent 通过 build_tool_params 将事实转为工具参数
- 调用工具获取数据，返回结构化结果
- 工具不可用时自动降级到 fallback_output

设计原则：
- 每个 Agent 只负责单领域问题，不混做全链路规划
- Agent 不直接写 HTTP 请求，通过 Tool 层间接访问
- 优雅降级：单个工具失败不阻塞该 Agent
"""

from __future__ import annotations

import importlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 导入统一结果模型
try:
    from backend.tools.result import ToolResult, normalize_tool_result
except ImportError:
    from tools.result import ToolResult, normalize_tool_result  # type: ignore

# 事件回调类型
EventCallback = Optional[Callable[[Dict[str, Any]], None]]


class BaseDomainAgent:
    """
    领域 Agent 基类 —— 所有子 Agent 继承此类。

    统一的执行模式：
    1. build_tool_params(facts) → 构建工具调用参数
    2. invoke_tool(params, facts) → 调用工具获取数据
    3. normalize_tool_result → 统一结果格式
    4. fallback_output(facts, reason) → 工具失败时降级

    子类只需重写 build_tool_params 和 fallback_output，
    invoke_tool 默认通过 _load_tool 动态加载。

    属性：
        name: Agent 内部名称（如 flight_agent）
        tool_module: 工具模块名（如 flight_tool）
        tool_name: 工具函数名（如 search_flights）
    """

    name = "base_agent"
    tool_module = ""
    tool_name = ""

    def execute(
        self,
        subtask: str,
        facts: Dict[str, Any],
        event_callback: EventCallback = None,
    ) -> Dict[str, Any]:
        """
        执行 Agent 的主流程。

        流程：
        1. 构建工具参数
        2. 调用工具
        3. 标准化结果
        4. 失败时降级

        Args:
            subtask: Supervisor 分配的子任务指令
            facts: 共享事实上下文（目的地、日期、预算等）
            event_callback: SSE 事件回调

        Returns:
            包含 status、response、tool_artifacts 等字段的结果字典
        """
        started_at = datetime.now().isoformat()

        # --- 步骤 1：构建工具参数 ---
        params = self.build_tool_params(facts)

        # 记录工具调用开始
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

        # --- 步骤 2 & 3：调用工具并标准化结果 ---
        try:
            tool_result = normalize_tool_result(self.invoke_tool(params, facts))
            text = tool_result.message.strip()

            # 如果工具返回为空，使用降级输出
            if not text:
                text = self.fallback_output(facts, tool_result.error or "工具返回为空")

            # 映射工具状态到 Agent 状态
            agent_status = {
                "success": "completed",
                "degraded": "degraded",
                "failed": "failed",
            }[tool_result.status]

            # 更新 artifact 记录
            artifact.update({
                "status": agent_status,
                "result_preview": text[:500],
                "result_data": tool_result.data,
                "source": tool_result.source,
                "error": tool_result.error,
                "finished_at": datetime.now().isoformat(),
            })

            # 根据状态选择事件类型
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
            # --- 步骤 4：异常降级 ---
            fallback = self.fallback_output(facts, str(exc))
            artifact.update({
                "status": "degraded",
                "error": str(exc),
                "result_preview": fallback[:500],
                "finished_at": datetime.now().isoformat(),
            })

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

    # ======================== 子类必须重写的方法 ========================

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据共享事实构建工具调用参数。

        子类必须重写此方法，将 facts 映射为对应工具的输入参数。

        Args:
            facts: 标准化事实（来自 normalize_request）

        Returns:
            工具参数字典

        Raises:
            NotImplementedError: 子类未重写
        """
        raise NotImplementedError(
            f"{self.name} 必须重写 build_tool_params 方法"
        )

    # ======================== 子类可选重写的方法 ========================

    def invoke_tool(self, params: Dict[str, Any], facts: Dict[str, Any]) -> Any:
        """
        调用工具获取数据。

        默认实现：通过 _load_tool 动态加载工具函数并调用。
        子类可重写以实现自定义调用逻辑（如 BudgetAgent 的纯计算）。

        Args:
            params: build_tool_params 构建的参数
            facts: 共享事实上下文

        Returns:
            工具返回的原始结果
        """
        tool = self._load_tool()
        return tool.invoke(params)

    def fallback_output(self, facts: Dict[str, Any], reason: str) -> str:
        """
        工具不可用时的降级输出。

        返回明确的错误说明，不生成任何虚假数据。
        子类可重写以实现领域特定的降级逻辑（如 LocalExpertAgent 的本地文件回退）。

        Args:
            facts: 共享事实上下文
            reason: 降级原因

        Returns:
            Markdown 格式的降级说明文本
        """
        destination = facts.get('destination', '未指定')
        return (
            f"## {self.name} 数据暂不可用\n"
            f"- 目的地：{destination}\n"
            f"- 原因：{reason}\n"
            f"- 请通过携程/12306/航空公司官网等渠道查询实时数据。"
        )

    # ======================== 内部辅助方法 ========================

    def _load_tool(self) -> Any:
        """
        动态加载工具函数。

        尝试两个路径：
        1. backend.tools.{tool_module}（从项目根启动）
        2. tools.{tool_module}（从 backend/ 目录启动）

        Returns:
            工具函数对象

        Raises:
            RuntimeError: 两个路径都加载失败
        """
        errors: List[str] = []
        for module_name in (
            f"backend.tools.{self.tool_module}",
            f"tools.{self.tool_module}",
        ):
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
        """
        构建统一的 Agent 执行结果字典。

        Args:
            subtask: 原始子任务指令
            output: 最终输出文本
            artifacts: 工具调用记录列表
            started_at: 开始时间
            status: 执行状态
            error: 错误信息
            degraded: 是否降级

        Returns:
            标准化的 AgentExecution 字典
        """
        return {
            "status": status,
            "subtask": subtask,
            "response": output,
            "output": output,
            "tool_artifacts": artifacts,
            "error": error,
            "degraded": degraded,
            "retry_count": 0,
            "llm_calls": 0,
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
        """
        推送事件给 Supervisor 的 event_callback。

        Args:
            callback: 事件回调函数
            event_type: 事件类型
            message: 事件描述
            data: 附加数据
        """
        if callback:
            callback({
                "type": event_type,
                "message": message,
                "agent": self.name,
                "status": "processing",
                "data": data,
                "timestamp": datetime.now().isoformat(),
            })


# ======================== 航班 Agent ========================

class FlightAgent(BaseDomainAgent):
    """
    航班搜索 Agent。

    职责：查询出发地到目的地的可用航班，比较直飞/中转方案和价格。

    工具：search_flights（聚合数据 API）
    """

    name = "flight_agent"
    tool_module = "flight_tool"
    tool_name = "search_flights"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建航班搜索参数。

        提取 departure（出发地）、arrival（目的地）、date（出发日期）。
        """
        return {
            "departure": facts.get("departure", ""),
            "arrival": facts.get("destination", ""),
            "date": facts.get("start_date", ""),
        }


# ======================== 铁路 Agent ========================

class TrainAgent(BaseDomainAgent):
    """
    铁路搜索 Agent。

    职责：查询出发地到目的地的高铁/动车/火车，比较时间和价格。

    工具：search_trains（聚合数据 API）
    """

    name = "train_agent"
    tool_module = "train_tool"
    tool_name = "search_trains"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建铁路搜索参数。

        提取 departure（出发地）、arrival（目的地）、date（出发日期）。
        """
        return {
            "departure": facts.get("departure", ""),
            "arrival": facts.get("destination", ""),
            "date": facts.get("start_date", ""),
        }


# ======================== 酒店 Agent ========================

class HotelAgent(BaseDomainAgent):
    """
    酒店推荐 Agent。

    职责：根据目的地、预算和天数搜索住宿选项。

    工具：search_hotels（高德 POI + Mock 价格）

    星级选择策略：
    - 豪华/高端 → 五星级
    - 经济 → 三星级
    - 默认 → 四星级
    """

    name = "hotel_agent"
    tool_module = "hotel_tool"
    tool_name = "search_hotels"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建酒店搜索参数。

        根据预算范围推断期望的星级：
        - 豪华/高端 → 5星
        - 经济 → 3星
        - 默认 → 4星
        """
        budget = str(facts.get("budget_range", ""))

        if any(word in budget for word in ("豪华", "高端", "奢侈")):
            star = 5
        elif any(word in budget for word in ("经济", "穷游", "背包")):
            star = 3
        else:
            star = 4

        return {
            "city": facts.get("destination", ""),
            "check_in": facts.get("start_date", ""),
            "check_out": facts.get("end_date", ""),
            "star": star,
        }


# ======================== 景点 Agent ========================

class AttractionAgent(BaseDomainAgent):
    """
    景点推荐 Agent。

    职责：围绕用户兴趣主题，搜索目的地的热门景点和隐藏宝藏。

    工具：search_attractions（高德 POI API）
    """

    name = "attraction_agent"
    tool_module = "attraction_tool"
    tool_name = "search_attractions"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建景点搜索参数。

        将用户兴趣列表拼接为搜索关键词。
        """
        return {
            "city": facts.get("destination", ""),
            "keywords": "、".join(facts.get("interests", [])) or "热门景点",
        }


# ======================== 天气 Agent ========================

class WeatherAgent(BaseDomainAgent):
    """
    天气分析 Agent。

    职责：查询行程期间的天气预报，给出室内外活动调整建议。

    工具：search_weather（和风天气 API）

    天数限制：和风天气仅支持 3 天或 7 天预报。
    1-3 天 → 3d 接口，4-7 天 → 7d 接口。
    """

    name = "weather_agent"
    tool_module = "weather_tool"
    tool_name = "search_weather"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建天气查询参数。

        天数限制在 1-7 天范围内（和风天气 API 限制）。
        """
        return {
            "city": facts.get("destination", ""),
            "days": min(max(int(facts.get("duration", 3)), 1), 7),
        }


# ======================== 本地专家 Agent ========================

class LocalExpertAgent(BaseDomainAgent):
    """
    本地生活专家 Agent。

    职责：补充目的地的在地体验信息——特色美食、餐饮推荐、
    文化礼仪、交通贴士、避坑指南。

    工具：local_expert_skill（Chroma RAG + DuckDuckGo）

    降级策略：当在线 RAG 不可用时，回退到本地 Markdown 知识文件
    （SimpleExample-knowledge-rag/ 目录下的城市知识文件）。
    """

    name = "local_expert"
    tool_module = "travel_tools"
    tool_name = "local_expert_skill"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建本地知识检索参数。

        将目的地和兴趣拼接为检索查询。
        """
        destination = facts.get("destination", "")
        interests = "、".join(facts.get("interests", []))
        return {
            "destination": destination,
            "interests": interests,
            "query": f"{destination} {interests} 在地体验 餐饮 礼仪 避坑".strip(),
            "top_k": 4,
        }

    def fallback_output(self, facts: Dict[str, Any], reason: str) -> str:
        """
        在线 RAG 不可用时，回退到本地知识文件。

        支持的 5 个城市：北京、上海、广州、深圳、杭州。
        如果本地文件也不存在，使用基类的通用降级输出。
        """
        destination = str(facts.get("destination", "")).strip()

        # 城市名称 → 文件名映射
        city_aliases = {
            "北京": "beijing",
            "上海": "shanghai",
            "广州": "guangzhou",
            "深圳": "shenzhen",
            "杭州": "hangzhou",
        }

        # 查找本地知识文件
        knowledge_file = (
            Path(__file__).resolve().parents[2]
            / "SimpleExample-knowledge-rag"
            / f"{city_aliases.get(destination, destination.lower())}.md"
        )

        if knowledge_file.exists():
            content = knowledge_file.read_text(encoding="utf-8").strip()
            excerpt = content[:1800]  # 截取前 1800 字符
            return (
                f"## {destination}本地知识（本地文件降级）\n"
                f"{excerpt}\n\n"
                f"> ⚠️ 在线 RAG 不可用：{reason}\n"
                f"> 📄 数据来源：本地知识库文件"
            )

        # 无本地文件 → 使用基类通用降级
        return super().fallback_output(facts, reason)


# ======================== 预算 Agent ========================

class BudgetAgent(BaseDomainAgent):
    """
    预算分析 Agent。

    职责：解析用户预算描述，核对行程开销合理性，给出分配建议。

    工具：budget_calculator（内置纯计算逻辑，无外部 API 依赖）

    预算解析支持三种口径：
    - 人均每日预算上限（如"人均500元/天"）
    - 团队每日预算上限（如"300-800元/天"）
    - 全程总预算上限（如"总预算5000元"）
    """

    name = "budget_optimizer"
    tool_name = "budget_calculator"

    def build_tool_params(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建预算计算参数。

        提取预算描述、天数、人数。
        """
        return {
            "budget_range": facts.get("budget_range", ""),
            "duration": facts.get("duration", 3),
            "group_size": facts.get("group_size", 1),
        }

    def invoke_tool(self, params: Dict[str, Any], facts: Dict[str, Any]) -> ToolResult:
        """
        执行预算计算（纯 Python，无需外部 API）。

        流程：
        1. 调用 parse_budget_estimate 解析预算文本
        2. 根据人均每日预算判断预算状态
        3. 给出各项开销的分配建议

        Args:
            params: 预算计算参数
            facts: 共享事实（未使用，保留接口一致性）

        Returns:
            ToolResult 包含预算分析结果
        """
        budget_text = str(params["budget_range"])
        estimate = parse_budget_estimate(
            budget_text,
            duration=int(params["duration"]),
            group_size=int(params["group_size"]),
        )

        total_budget = estimate["total_budget"]

        if total_budget:
            # 有明确金额 → 给出详细分析
            per_person_day = estimate["per_person_day"]

            # 预算等级判断
            if per_person_day < 350:
                level = "偏紧"
                tip = "建议优先保证住宿和交通，景点选择免费或低价项目。"
            elif per_person_day >= 900:
                level = "充足"
                tip = "预算充裕，可以考虑升级住宿或增加特色体验项目。"
            else:
                level = "适中"
                tip = "预算合理，可以兼顾舒适度和体验深度。"

            return ToolResult.success(
                (
                    "## 💰 预算分析\n"
                    f"- 预算口径：{estimate['basis']}\n"
                    f"- 全程总预算参考：¥{total_budget:,.0f}\n"
                    f"- 人均每日预算：约 ¥{per_person_day:,.0f}\n"
                    f"- 预算状态：{level}\n"
                    f"- {tip}\n"
                    "- 建议分配：住宿 35%，交通 25%，餐饮 20%，门票活动 15%，机动 5%。"
                ),
                data=estimate,
                source="budget_calculator",
            )

        # 无法解析金额 → 给出通用建议
        return ToolResult.degraded(
            (
                "## 💰 预算分析\n"
                f"- 当前预算描述：{budget_text or '未提供明确金额'}\n"
                "- ⚠️ 建议补充具体预算金额以获得精确分析\n"
                "- 暂按通用比例分配：住宿 35%、交通 25%、餐饮 20%、门票活动 15%、机动 5%。"
            ),
            error="budget_amount_missing",
            source="budget_calculator",
        )


# ======================== 预算解析工具函数 ========================

def parse_budget_estimate(
    budget_text: str,
    *,
    duration: int,
    group_size: int,
) -> Dict[str, Any]:
    """
    将中文预算描述转换为全程总预算金额。

    支持三种口径（按优先级）：
    1. "人均500元/天" → 人均每日预算 × 天数 × 人数
    2. "300-800元/天" → 团队每日预算上限 × 天数
    3. "总预算5000元" → 直接作为全程总预算

    Args:
        budget_text: 用户的预算描述文本
        duration: 旅行天数（至少为 1）
        group_size: 出行人数（至少为 1）

    Returns:
        包含 total_budget、per_person_day、basis 等字段的字典
    """
    # 安全归一化
    normalized_duration = max(int(duration), 1)
    normalized_group_size = max(int(group_size), 1)

    # 提取所有数字（支持千位分隔符如 "3,000"）
    numbers = [
        int(item.replace(",", ""))
        for item in re.findall(r"\d[\d,]*", str(budget_text))
    ]
    amount = max(numbers) if numbers else 0

    # 判断是否为每日预算
    is_daily = bool(
        re.search(r"(?:每天|每日|日均|(?:元|块)?\s*/\s*(?:天|日))", budget_text)
    )

    # 判断是否为每人预算
    is_per_person = bool(re.search(r"(?:人均|每人)", budget_text))

    # 根据口径计算全程总预算
    if is_daily and is_per_person:
        # 口径 1：人均每日预算
        total_budget = amount * normalized_duration * normalized_group_size
        basis = "人均每日预算上限"
    elif is_daily:
        # 口径 2：团队每日预算
        total_budget = amount * normalized_duration
        basis = "团队每日预算上限"
    else:
        # 口径 3：全程总预算
        total_budget = amount
        basis = "全程总预算上限"

    # 计算人均每日预算（用于预算等级判断）
    per_person_day = (
        total_budget / (normalized_duration * normalized_group_size)
        if total_budget
        else 0
    )

    return {
        "input": budget_text,
        "basis": basis,
        "total_budget": total_budget,
        "per_person_day": per_person_day,
        "duration": normalized_duration,
        "group_size": normalized_group_size,
    }


# ======================== Agent 注册表工厂 ========================

def build_default_agent_registry() -> Dict[str, BaseDomainAgent]:
    """
    构建默认的 Agent 注册表。

    包含 V1 全部 7 个领域 Agent：
    - FlightAgent：航班查询
    - TrainAgent：铁路查询
    - HotelAgent：酒店推荐
    - AttractionAgent：景点推荐
    - WeatherAgent：天气分析
    - LocalExpertAgent：本地专家
    - BudgetAgent：预算分析

    Returns:
        {agent_name: agent_instance} 字典
    """
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
