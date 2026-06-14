"""
天气查询工具 —— 和风天气优先 + 高德天气降级。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.qweather import QweatherProvider
from apis.providers.amap_weather import AmapWeatherProvider
from backend.tools.result import ToolResult


class WeatherSearchInput(BaseModel):
    city: str = Field(description="城市名")
    days: int = Field(3, description="预报天数 (1-7)")


def _format_weather(city: str, results: list, source: str) -> str:
    """格式化天气结果为文本。"""
    lines = [f"**{city} 未来 {len(results)} 天天气 ({source})**"]
    for w in results:
        lines.append(
            f"- {w['date']}: {w['text_day']} | "
            f"{w['temp_min']}°C ~ {w['temp_max']}°C | "
            f"{w.get('wind_dir', '')} {w.get('wind_scale', '')}级"
        )
    return "\n".join(lines)


@tool(args_schema=WeatherSearchInput)
def search_weather(city: str, days: int = 3) -> ToolResult:
    """
    查询城市天气。优先和风天气，失败则降级到高德天气。
    """

    # ---- 方案 A: 和风天气 (JWT) ----
    if settings.qweather_key_id and settings.qweather_private_key:
        try:
            provider = QweatherProvider(settings.qweather_key_id, settings.qweather_private_key)
            results = provider.search({"city": city, "days": min(days, 7)})
            if results and "error" not in results[0]:
                return ToolResult.success(
                    _format_weather(city, results, "和风天气"),
                    data=results,
                    source="qweather",
                )
            logger.warning("和风天气返回异常: %s，尝试高德降级", results[0].get("error", "unknown"))
        except Exception as e:
            logger.warning("和风天气调用失败: %s，尝试高德降级", str(e))

    # ---- 方案 B: 高德天气降级 ----
    if settings.amap_api_key:
        try:
            provider = AmapWeatherProvider(settings.amap_api_key)
            results = provider.search({"city": city, "days": min(days, 4)})
            if results and "error" not in results[0]:
                return ToolResult.success(
                    _format_weather(city, results, "高德天气"),
                    data=results,
                    source="amap_weather",
                )
            logger.warning("高德天气返回异常: %s", results[0].get("error", "unknown"))
        except Exception as e:
            logger.warning("高德天气调用失败: %s", str(e))

    # ---- 方案 C: 全部失败 ----
    return ToolResult.degraded(
        f"[天气查询暂时不可用] {city}",
        error="all_weather_providers_failed",
        source="fallback",
    )
