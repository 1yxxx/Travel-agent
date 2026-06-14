"""
酒店搜索工具 —— 封装高德 POI 真实数据。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.amap import AmapHotelProvider
from backend.tools.result import ToolResult


class HotelSearchInput(BaseModel):
    """酒店搜索参数。"""
    city: str = Field(description="城市名，例如：成都、杭州")
    check_in: str = Field(description="入住日期，格式 YYYY-MM-DD")
    check_out: str = Field(description="退房日期，格式 YYYY-MM-DD")
    star: int = Field(4, description="星级偏好 (3/4/5)")


@tool(args_schema=HotelSearchInput)
def search_hotels(city: str, check_in: str, check_out: str, star: int = 4) -> ToolResult:
    """
    搜索国内酒店。输入城市、日期和星级偏好，返回酒店列表（高德地图真实数据）。
    注意：高德 API 不提供实时房价，价格需用户在携程/飞猪等平台另行查询。
    """
    if not settings.amap_api_key:
        return ToolResult.degraded(
            "[酒店查询] 高德地图 API Key 未配置",
            error="amap_api_key_missing",
            source="amap",
        )

    amap = AmapHotelProvider(settings.amap_api_key)

    try:
        hotels = amap.search({"city": city, "star": star})
    except Exception as e:
        logger.error("酒店查询失败 | city={} | {}", city, str(e))
        return ToolResult.degraded(
            f"[酒店查询暂时不可用] {city}",
            error=str(e),
            source="amap",
        )

    if not hotels:
        return ToolResult.degraded(
            f"未找到 {city} 的酒店信息",
            error="no_hotel_results",
            source="amap",
        )

    lines = [f"**{city} 酒店推荐 ({check_in} → {check_out})**"]
    for h in hotels[:5]:
        lines.append(
            f"- {h['name']} | "
            f"评分 {h.get('rating', 'N/A')} | "
            f"{h.get('address', '')[:20]}"
        )
    lines.append(f"\n> ⚠️ 高德地图不提供实时房价，请前往携程/飞猪等平台查询实际价格。")
    return ToolResult.success("\n".join(lines), data=hotels[:5], source="amap")
