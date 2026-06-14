"""
天气查询工具 —— 封装和风天气 API。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.qweather import QweatherProvider
from backend.tools.result import ToolResult


class WeatherSearchInput(BaseModel):
    """天气查询参数。"""
    city: str = Field(description="城市名")
    days: int = Field(3, description="预报天数 (1-7)")


@tool(args_schema=WeatherSearchInput)
def search_weather(city: str, days: int = 3) -> ToolResult:
    """
    查询城市天气。输入城市名和天数，返回天气预报。
    """
    if not settings.qweather_api_key:
        return ToolResult.degraded(
            "[天气查询] 和风天气 API Key 未配置",
            error="qweather_api_key_missing",
            source="qweather",
        )

    provider = QweatherProvider(settings.qweather_api_key)
    try:
        results = provider.search({"city": city, "days": min(days, 7)})
    except Exception as e:
        logger.error("天气查询失败 | city={} | {}", city, str(e))
        return ToolResult.degraded(
            f"[天气查询暂时不可用] {city}",
            error=str(e),
            source="qweather",
        )

    if not results or "error" in results[0]:
        return ToolResult.degraded(
            f"未找到 {city} 的天气信息",
            error="no_weather_results",
            source="qweather",
        )

    lines = [f"**{city} 未来 {len(results)} 天天气**"]
    for w in results:
        lines.append(
            f"- {w['date']}: {w['text_day']} | "
            f"{w['temp_min']}°C ~ {w['temp_max']}°C | "
            f"{w['wind_dir']} {w['wind_scale']}级"
        )
    return ToolResult.success("\n".join(lines), data=results, source="qweather")
