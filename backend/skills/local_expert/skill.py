"""
本地专家技能包 —— 可复用的在地旅行建议能力。

这是一个独立的"技能模块"（Skill），封装了本地知识检索和旅行建议生成
的完整逻辑。Agent 通过统一的接口调用此技能，不需要关心内部实现。

核心设计（需求文档 §6.4）：
- 三级降级策略：RAG 检索 → DuckDuckGo 搜索 → 默认结构化建议
- 智能路由：优先城市（北京/上海/广州/深圳/杭州）走 RAG，其他走搜索
- 与 Agent 解耦：Agent 只需调用 run() 方法，不关心内部检索逻辑

Python 新手提示：
- @dataclass(frozen=True) 创建不可变数据类（类似 struct）
- Callable[[str], str] 表示"接收一个 str 参数、返回 str 的函数"
- Sequence[str] 是 list/tuple 的抽象基类（只读序列）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Sequence, Tuple


# ======================== 数据模型 ========================

@dataclass(frozen=True)
class LocalExpertSkillSpec:
    """
    技能规格说明（元数据）。

    描述技能的基本属性，类似于 API 文档中的接口说明。
    用于技能发现和文档生成，不参与运行时逻辑。

    字段说明：
        name:        技能名称（唯一标识）
        version:     版本号
        description: 功能描述
        route_rule:  路由规则说明
        resources:   依赖的资源列表
    """
    name: str
    version: str
    description: str
    route_rule: str
    resources: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class LocalExpertSkillInput:
    """
    技能输入参数。

    字段说明：
        destination: 目的地城市名（必填）
        interests:   用户兴趣关键词（可选，如"美食 历史"）
        query:       自定义搜索查询（可选，为空则自动构建）
        top_k:       返回结果数量（默认 4，范围 1-10）
    """
    destination: str
    interests: str = ""
    query: str = ""
    top_k: int = 4


@dataclass(frozen=True)
class LocalExpertSkillOutput:
    """
    技能输出结果。

    字段说明：
        route:           实际使用的检索路径（rag/search/search_fallback）
        local_advice:    生成的在地建议文本（Markdown 格式）
        retrieval_count: 检索到的文档/结果数量
        source_tags:     数据来源标签列表（用于可追溯性）
    """
    route: str
    local_advice: str
    retrieval_count: int
    source_tags: List[str]


# ======================== 技能实现 ========================

class LocalExpertSkill:
    """
    本地专家技能 —— 可复用的在地旅行建议能力包。

    封装了完整的"检索 → 编排 → 建议生成"流程：

    1. 路由决策：根据城市决定走 RAG 还是搜索
       - 北京/上海/广州/深圳/杭州 → RAG（Chroma 向量检索）
       - 其他城市 → 搜索（DuckDuckGo）

    2. 检索执行：
       - RAG 成功 → 返回知识片段
       - RAG 失败 → 自动回退到搜索
       - 搜索失败 → 生成结构化默认建议

    3. 建议合成：将检索结果按 4 个类别整理输出
       - 小众地点、文化礼仪、本地餐饮、避坑建议

    使用方式：
        skill = LocalExpertSkill(
            normalize_city=normalize_city,
            rag_priority_cities={"beijing", "shanghai", ...},
            rag_retriever=my_rag_func,
            search_retriever=my_search_func,
            advice_builder=my_advice_func,
            logger=my_logger,
        )
        output = skill.run(LocalExpertSkillInput(
            destination="北京",
            interests="美食 历史",
        ))
    """

    # 技能元数据
    SPEC = LocalExpertSkillSpec(
        name="local_expert_skill",
        version="1.0.0",
        description=(
            "生成可用于旅行规划的本地化建议。"
            "优先城市走 RAG，其他城市走网络搜索。"
        ),
        route_rule="destination in {北京, 上海, 广州, 杭州, 深圳} → RAG 否则 Search",
        resources=(
            "knowledge-rag markdown 语料库",
            "chroma cloud collection（向量数据库）",
            "duckduckgo_search 网络搜索",
            "local advice 合成模板",
        ),
    )

    def __init__(
        self,
        *,
        normalize_city: Callable[[str], str],
        rag_priority_cities: Sequence[str],
        rag_retriever: Callable[[str, str, int], Tuple[List[str], List[str], int]],
        search_retriever: Callable[[str], Tuple[List[str], List[str], int]],
        advice_builder: Callable[[str, str, List[str], List[str]], str],
        logger,
    ) -> None:
        """
        初始化技能。

        参数（都是可注入的依赖，便于测试和替换）：
            normalize_city:      城市名标准化函数（中文→英文标识）
            rag_priority_cities: 优先使用 RAG 的城市集合
            rag_retriever:       RAG 检索函数 (destination, query, top_k) → (texts, tags, count)
            search_retriever:    搜索函数 (query) → (texts, tags, count)
            advice_builder:      建议合成函数 (destination, route, texts, tags) → markdown
            logger:              日志记录器
        """
        self._normalize_city = normalize_city
        self._rag_priority_cities = set(rag_priority_cities)
        self._rag_retriever = rag_retriever
        self._search_retriever = search_retriever
        self._advice_builder = advice_builder
        self._logger = logger

    def _build_query(self, payload: LocalExpertSkillInput) -> str:
        """
        构建检索查询文本。

        如果用户提供了自定义 query 则直接使用，
        否则自动拼接目的地+兴趣+通用关键词。
        """
        return payload.query.strip() or (
            f"{payload.destination} {payload.interests} "
            f"本地建议 小众景点 文化礼仪 在地美食 交通避坑"
        ).strip()

    def _route(self, payload: LocalExpertSkillInput) -> str:
        """
        路由决策：根据城市决定使用 RAG 还是搜索。

        规则：
        - 标准化后的城市名在 rag_priority_cities 中 → "rag"
        - 否则 → "search"
        """
        norm_city = self._normalize_city(payload.destination)
        return "rag" if norm_city in self._rag_priority_cities else "search"

    def _run_search_fallback(
        self,
        query_text: str,
        reason: str,
    ) -> Tuple[str, List[str], List[str], int]:
        """
        RAG 失败时的搜索回退。

        当 RAG 不可用或返回空结果时，自动切换到 DuckDuckGo 搜索。
        """
        self._logger.info(f"local_expert skill 启用 Search fallback: {reason}")
        texts, source_tags, retrieval_count = self._search_retriever(query_text)
        self._logger.info(
            f"local_expert skill Search fallback 命中 {retrieval_count} 条"
        )
        return "search_fallback", texts, source_tags, retrieval_count

    def run(self, payload: LocalExpertSkillInput) -> LocalExpertSkillOutput:
        """
        执行技能的主入口。

        完整的执行流程（三级降级）：

        1. 路由决策：RAG 还是 Search？
        2. 如果是 RAG：
           a. 尝试 RAG 检索
           b. RAG 成功且命中 > 0 → 使用 RAG 结果
           c. RAG 命中 = 0 → 自动回退到 Search
           d. RAG 抛异常 → 回退到 Search
           e. Search 也失败 → 生成默认建议
        3. 如果是 Search：
           a. 尝试搜索
           b. 搜索失败 → 生成默认建议
        4. 调用 advice_builder 将检索结果合成为结构化建议

        参数：
            payload: 技能输入参数

        返回：
            LocalExpertSkillOutput（包含建议文本和元数据）
        """
        route = self._route(payload)
        route_used = route
        query_text = self._build_query(payload)
        top_k = payload.top_k if payload.top_k > 0 else 4

        self._logger.info(
            "运行 local_expert skill - "
            f"destination={payload.destination}, route={route}, "
            f"top_k={top_k}, query={query_text}"
        )

        texts: List[str] = []
        source_tags: List[str] = []
        retrieval_count = 0

        # ---- RAG 路径 ----
        if route == "rag":
            try:
                # 尝试 RAG 检索
                texts, source_tags, retrieval_count = self._rag_retriever(
                    payload.destination, query_text, top_k
                )
                self._logger.info(
                    f"local_expert skill RAG 命中 {retrieval_count} 条"
                )

                # RAG 返回 0 条结果 → 回退搜索
                if retrieval_count == 0:
                    route_used, texts, source_tags, retrieval_count = (
                        self._run_search_fallback(
                            query_text,
                            f"城市限定 RAG 返回 0 条 ({payload.destination})",
                        )
                    )
            except Exception as exc:
                # RAG 异常 → 回退搜索
                self._logger.warning(
                    f"local_expert skill RAG 失败，回退 Search: {exc}"
                )
                try:
                    route_used, texts, source_tags, retrieval_count = (
                        self._run_search_fallback(
                            query_text,
                            f"RAG 异常 ({payload.destination}): {exc}",
                        )
                    )
                except Exception as search_exc:
                    # 搜索也失败 → 生成默认建议
                    self._logger.warning(
                        "local_expert skill Search fallback 也失败，"
                        f"使用结构化默认建议: {search_exc}"
                    )
                    route_used, texts, source_tags, retrieval_count = (
                        route, [], [], 0
                    )

        # ---- Search 路径 ----
        else:
            try:
                texts, source_tags, retrieval_count = self._search_retriever(
                    query_text
                )
                self._logger.info(
                    f"local_expert skill Search 命中 {retrieval_count} 条"
                )
            except Exception as exc:
                # 搜索失败 → 生成默认建议
                self._logger.warning(
                    "local_expert skill Search 失败，"
                    f"使用结构化默认建议: {exc}"
                )
                texts, source_tags, retrieval_count = [], [], 0

        # ---- 合成最终建议 ----
        local_advice = self._advice_builder(
            payload.destination, route_used, texts, source_tags
        )

        return LocalExpertSkillOutput(
            route=route_used,
            local_advice=local_advice,
            retrieval_count=retrieval_count,
            source_tags=source_tags,
        )
