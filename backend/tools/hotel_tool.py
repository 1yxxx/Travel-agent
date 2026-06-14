"""
酒店搜索工具 —— 封装高德 POI + Mock 价格。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.amap import AmapHotelProvider
from apis.providers.mock_price import MockPriceProvider
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
    搜索国内酒店。输入城市、日期和星级偏好，返回酒店列表（含参考价格）。
    """
    if not settings.amap_api_key:
        return ToolResult.degraded(
            "[酒店查询] 高德地图 API Key 未配置",
            error="amap_api_key_missing",
            source="amap",
        )

    amap = AmapHotelProvider(settings.amap_api_key)
    price_mock = MockPriceProvider()

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

    prices = price_mock.search({"city": city, "star": star})

    lines = [f"**{city} 酒店推荐 ({check_in} → {check_out})**"]
    for h in hotels[:5]:
        p = prices[0] if prices else {"price_per_night": "N/A"}
        lines.append(
            f"- {h['name']} | "
            f"评分 {h.get('rating', 'N/A')} | "
            f"参考价 ¥{p.get('price_per_night', 'N/A')}/晚 | "
            f"{h.get('address', '')[:20]}"
        )
    lines.append(f"\n*价格标注为参考价，实际以携程/飞猪为准*")
    return ToolResult.success("\n".join(lines), data=hotels[:5], source="amap")
