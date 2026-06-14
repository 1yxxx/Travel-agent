"""
景点搜索工具 —— 封装高德 POI 景点搜索。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.amap import AmapAttractionProvider


class AttractionSearchInput(BaseModel):
    """景点搜索参数。"""
    city: str = Field(description="城市名")
    keywords: str = Field("热门景点", description="搜索关键词，如：自然风光、博物馆")


@tool(args_schema=AttractionSearchInput)
def search_attractions(city: str, keywords: str = "热门景点") -> str:
    """
    搜索城市景点。输入城市名和偏好类型，返回景点列表。
    """
    if not settings.amap_api_key:
        return f"[景点查询] 高德地图 API Key 未配置"

    provider = AmapAttractionProvider(settings.amap_api_key)
    try:
        results = provider.search({"city": city, "keywords": keywords})
    except Exception as e:
        logger.error("景点查询失败 | city={} | {}", city, str(e))
        return f"[景点查询暂时不可用] {city}"

    if not results:
        return f"未找到 {city} 的 {keywords} 类景点"

    lines = [f"**{city} {keywords} 推荐**"]
    for a in results[:8]:
        lines.append(f"- {a['name']} | 评分 {a.get('rating', 'N/A')} | {a.get('address', '')[:30]}")
    return "\n".join(lines)