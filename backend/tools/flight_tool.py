"""
航班搜索工具 —— 封装聚合数据 API。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.juhe import JuheFlightProvider
from backend.tools.result import ToolResult


class FlightSearchInput(BaseModel):
    """航班搜索参数。"""
    departure: str = Field(description="出发城市，例如：北京、上海")
    arrival: str = Field(description="到达城市，例如：成都、广州")
    date: str = Field(description="出发日期，格式 YYYY-MM-DD，例如：2026-05-01")


@tool(args_schema=FlightSearchInput)
def search_flights(departure: str, arrival: str, date: str) -> ToolResult:
    """
    搜索国内航班信息。输入出发城市、到达城市和日期，返回航班列表。
    如果没有 API Key 或查询无结果，返回友好提示。
    """
    if not settings.juhe_flight_key:
        return ToolResult.degraded(
            f"[航班查询] 聚合数据航班 API Key 未配置，无法查询 {departure} → {arrival} 的航班",
            error="juhe_flight_key_missing",
            source="juhe",
        )

    provider = JuheFlightProvider(settings.juhe_flight_key)
    try:
        results = provider.search({"departure": departure, "arrival": arrival, "date": date})
    except Exception as e:
        logger.error("航班查询失败 | {} → {} | {}", departure, arrival, str(e))
        return ToolResult.degraded(
            f"[航班查询暂时不可用] {departure} → {arrival}: 请稍后重试",
            error=str(e),
            source="juhe",
        )

    if not results:
        return ToolResult.degraded(
            f"未找到 {date} 从 {departure} 到 {arrival} 的航班",
            error="no_flight_results",
            source="juhe",
        )

    lines = [f"**{departure} → {arrival} 航班 ({date})**"]
    for f in results[:5]:
        transfer = "直飞" if f.get("transfer_num") == 1 else f"中转{f.get('transfer_num', '?')}次"
        lines.append(
            f"- {f['airline']} {f['flight_no']} ({transfer}) | "
            f"{f['dep_time']} → {f['arr_time']} | "
            f"¥{f.get('price', 'N/A')} | "
            f"{f.get('dep_airport', '')} → {f.get('arr_airport', '')}"
        )
    return ToolResult.success("\n".join(lines), data=results[:5], source="juhe")
