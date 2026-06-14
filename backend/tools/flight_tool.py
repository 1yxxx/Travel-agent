"""
航班搜索工具 —— 封装天行数据 API。

LangChain @tool，供 Agent 通过 Function Calling 调用。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.tianxing import TianxingFlightProvider


class FlightSearchInput(BaseModel):
    """航班搜索参数。"""
    departure: str = Field(description="出发城市，例如：北京、上海")
    arrival: str = Field(description="到达城市，例如：成都、广州")
    date: str = Field(description="出发日期，格式 YYYY-MM-DD，例如：2026-05-01")


@tool(args_schema=FlightSearchInput)
def search_flights(departure: str, arrival: str, date: str) -> str:
    """
    搜索国内航班信息。输入出发城市、到达城市和日期，返回航班列表。
    如果没有 API Key 或查询无结果，返回友好提示。
    """
    if not settings.tianxing_api_key:
        return f"[航班查询] 天行数据 API Key 未配置，无法查询 {departure} → {arrival} 的航班"

    provider = TianxingFlightProvider(settings.tianxing_api_key)
    try:
        results = provider.search({"departure": departure, "arrival": arrival, "date": date})
    except Exception as e:
        logger.error("航班查询失败 | {} → {} | {}", departure, arrival, str(e))
        return f"[航班查询暂时不可用] {departure} → {arrival}: 请稍后重试"

    if not results:
        return f"未找到 {date} 从 {departure} 到 {arrival} 的航班"

    lines = [f"**{departure} → {arrival} 航班 ({date})**"]
    for f in results[:5]:
        lines.append(
            f"- {f['airline']} {f['flight_no']} | "
            f"{f['dep_time']} → {f['arr_time']} | "
            f"¥{f.get('price', 'N/A')}"
        )
    return "\n".join(lines)