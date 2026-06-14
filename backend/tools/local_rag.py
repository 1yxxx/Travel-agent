"""
本地知识库 RAG 检索 —— 基于 Chroma 本地向量数据库。

工作流程：
1. 用户问："成都有什么小众景点？"
2. 系统在 Chroma 向量数据库中搜索与"成都+小众景点"最相似的文档片段
3. 把搜索结果格式化后返回给 LocalExpertAgent
4. Agent 基于这些真实知识生成回答

两种模式：
- 本地模式（默认）：使用 PersistentClient + sentence-transformers 嵌入
  数据存储在 CHROMA_PERSIST_DIR 目录（默认 ./chroma_data）
- Chroma Cloud（可选）：设置 CHROMA_API_KEY/TENANT/DATABASE 切换

特性：
- 支持按城市过滤（city 字段），避免"问成都却搜到北京"的跨城市污染
- @lru_cache 缓存 Chroma 客户端，避免重复连接
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

# 创建本模块专用的日志记录器
logger = logging.getLogger("local_rag")

# ======================== 城市名称映射 ========================

# 将中文城市名映射为英文标识（用于 Chroma 中按 city 字段过滤）
CITY_ALIASES = {
    "beijing": "beijing",
    "北京": "beijing",
    "shanghai": "shanghai",
    "上海": "shanghai",
    "guangzhou": "guangzhou",
    "广州": "guangzhou",
    "shenzhen": "shenzhen",
    "深圳": "shenzhen",
    "hangzhou": "hangzhou",
    "杭州": "hangzhou",
}


def normalize_city(city: str) -> str:
    """
    将城市名标准化为 Chroma 中使用的英文标识。

    例如：
    - "北京"  → "beijing"
    - "上海"  → "shanghai"
    - "成都"  → "chengdu"（不在映射表中，转为小写）
    - ""      → ""（空字符串直接返回）

    参数：
        city: 原始城市名（中英文均可）

    返回：
        标准化后的城市标识字符串
    """
    key = (city or "").strip()
    if not key:
        return ""
    # 先尝试精确匹配，再尝试小写匹配，最后转为小写
    return CITY_ALIASES.get(key.lower(), CITY_ALIASES.get(key, key.lower()))


# ======================== Chroma 配置 ========================

def get_collection_name() -> str:
    """
    获取 Chroma 集合（Collection）名称。

    集合类似于关系数据库中的"表"，存储了所有本地知识文档的向量。
    默认名称可通过环境变量 CHROMA_COLLECTION 自定义。
    """
    return os.getenv("CHROMA_COLLECTION", "travel_local_expert_knowledge").strip()


def get_default_top_k() -> int:
    """
    获取默认的检索结果数量。

    top_k 表示"返回最相似的 K 条结果"。
    可通过环境变量 CHROMA_TOP_K 自定义，默认为 4，限制在 1-10 之间。
    """
    value = os.getenv("CHROMA_TOP_K", "4").strip()
    try:
        top_k = int(value)
    except ValueError:
        top_k = 4
    return max(1, min(top_k, 10))


def _is_chroma_cloud_configured() -> bool:
    """检查是否配置了 Chroma Cloud（三个环境变量都非空）。"""
    return bool(
        os.getenv("CHROMA_API_KEY", "").strip()
        and os.getenv("CHROMA_TENANT", "").strip()
        and os.getenv("CHROMA_DATABASE", "").strip()
    )


def _get_persist_dir() -> str:
    """获取本地 ChromaDB 数据存储目录。"""
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data").strip()
    # 相对于项目根目录
    if not os.path.isabs(persist_dir):
        # 从 backend/tools/ 向上两级到项目根
        project_root = Path(__file__).resolve().parents[2]
        persist_dir = str(project_root / persist_dir)
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    return persist_dir


# ======================== Chroma 客户端 ========================

_chroma_client_error: Optional[str] = None


@lru_cache(maxsize=1)
def get_chroma_client() -> Optional[chromadb.api.ClientAPI]:
    """
    获取 Chroma 客户端（单例模式）。

    优先使用本地 ChromaDB（PersistentClient），无需任何 API Key。
    如果配置了 Chroma Cloud，则切换到 CloudClient。
    初始化失败时返回 None，调用方自动降级。

    @lru_cache(maxsize=1) 缓存客户端，避免重复连接。
    """
    global _chroma_client_error

    if _chroma_client_error:
        return None

    # 优先使用 Chroma Cloud
    if _is_chroma_cloud_configured():
        try:
            api_key = os.getenv("CHROMA_API_KEY", "").strip()
            tenant = os.getenv("CHROMA_TENANT", "").strip()
            database = os.getenv("CHROMA_DATABASE", "").strip()
            logger.info("使用 Chroma Cloud 模式: tenant=%s, database=%s", tenant, database)
            return chromadb.CloudClient(api_key=api_key, tenant=tenant, database=database)
        except Exception as e:
            _chroma_client_error = str(e)
            logger.warning("Chroma Cloud 连接失败: %s，RAG 将降级", e)
            return None

    # 默认使用本地 ChromaDB
    try:
        persist_dir = _get_persist_dir()
        logger.info("使用本地 ChromaDB 模式: persist_dir=%s", persist_dir)
        return chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    except Exception as e:
        _chroma_client_error = str(e)
        logger.warning("本地 ChromaDB 初始化失败: %s，RAG 将降级到搜索", e)
        return None


# ======================== 查询结果处理 ========================

def _flatten_query_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将 Chroma 返回的嵌套查询结果展平为易用的字典列表。

    Chroma 的查询结果格式是嵌套的（documents[0][i], metadatas[0][i]...），
    这个函数将其转换为扁平的列表，每个元素包含一条完整结果。

    转换前后对比：
    输入（Chroma 原生格式）：
        {
            "documents": [["doc1", "doc2"]],
            "metadatas": [["meta1", "meta2"]],
            "distances": [[0.1, 0.3]],
            "ids": [["id1", "id2"]]
        }

    输出（展平格式）：
        [
            {"id": "id1", "document": "doc1", "metadata": "meta1", "distance": 0.1},
            {"id": "id2", "document": "doc2", "metadata": "meta2", "distance": 0.3},
        ]

    参数：
        result: Chroma 的 query() 方法返回的原始结果

    返回：
        展平后的命中列表
    """
    # 安全解包：每个字段都是嵌套列表，取第一层
    docs_nested = result.get("documents") or [[]]
    metas_nested = result.get("metadatas") or [[]]
    dists_nested = result.get("distances") or [[]]
    ids_nested = result.get("ids") or [[]]

    # 取出内层列表
    docs = docs_nested[0] if docs_nested else []
    metas = metas_nested[0] if metas_nested else []
    dists = dists_nested[0] if dists_nested else []
    ids = ids_nested[0] if ids_nested else []

    # 逐条组装为字典
    hits: List[Dict[str, Any]] = []
    for idx, doc in enumerate(docs):
        meta = metas[idx] if idx < len(metas) and metas[idx] else {}
        distance = dists[idx] if idx < len(dists) else None
        chunk_id = ids[idx] if idx < len(ids) else None
        hits.append({
            "id": chunk_id,          # 文档片段的唯一 ID
            "document": doc,         # 文档片段的文本内容
            "metadata": meta,        # 元数据（城市、文件名等）
            "distance": distance,    # 向量距离（越小越相似）
        })
    return hits


# ======================== 知识库查询 ========================

def query_local_knowledge(
    destination: str,
    query: str,
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    查询 Chroma 本地知识库，获取与目的地相关的知识片段。

    关键设计：使用 city 字段过滤，避免跨城市污染。
    例如：查询"北京有什么好吃的"时，只会搜索北京的知识片段，不会混入上海的内容。

    参数：
        destination: 目的地城市名（如"北京"、"上海"）
        query:       查询文本（如"北京 美食 特色小吃"）
        top_k:       返回结果数量（默认 4，最大 10）

    返回：
        命中的知识片段列表，每个元素包含 document、metadata、distance 等字段
    """
    # 获取 Chroma 客户端和集合
    client = get_chroma_client()
    collection = client.get_or_create_collection(name=get_collection_name())

    # 确定返回数量
    n_results = top_k if top_k is not None else get_default_top_k()
    n_results = max(1, min(n_results, 10))

    # 标准化城市名，用于按 city 字段过滤
    city = normalize_city(destination)
    where = {"city": city} if city else None  # 有城市则过滤，无城市则全局搜索

    try:
        # 执行向量相似度搜索
        result = collection.query(
            query_texts=[query],         # 查询文本
            n_results=n_results,         # 返回数量
            where=where,                 # 过滤条件（按城市）
            include=["documents", "metadatas", "distances"],  # 需要返回的字段
        )

        # 展平结果并返回
        hits = _flatten_query_result(result)
        return hits

    except Exception as e:
        logger.warning("Chroma 查询失败: %s (collection 可能为空，请先运行 ingest 脚本)", str(e))
        return []


# ======================== 结果格式化 ========================

def format_hits_for_llm(hits: List[Dict[str, Any]]) -> str:
    """
    将检索命中结果格式化为 LLM 可消费的文本。

    格式：
        1. [source=beijing.md#chunk=3]
        故宫是中国明清两代的皇家宫殿...

        2. [source=beijing.md#chunk=7]
        北京烤鸭是北京的标志性美食...

    参数：
        hits: query_local_knowledge 返回的命中列表

    返回：
        格式化的文本，可直接作为 LLM 的上下文
    """
    if not hits:
        return "未检索到本地知识库内容。"

    lines: List[str] = []
    for i, hit in enumerate(hits, 1):
        doc = (hit.get("document") or "").strip()
        meta = hit.get("metadata") or {}
        source = meta.get("source_file", "unknown")    # 来源文件名
        chunk_index = meta.get("chunk_index", "?")      # 文档分块序号
        lines.append(
            f"{i}. [source={source}#chunk={chunk_index}]\n{doc}"
        )

    return "\n\n".join(lines)
