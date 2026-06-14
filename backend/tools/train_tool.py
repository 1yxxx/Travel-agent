"""
高铁搜索工具 —— 封装聚合数据 API。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.juhe import JuheTrainProvider
from backend.tools.result import ToolResult


class TrainSearchInput(BaseModel):
    """高铁搜索参数。"""
    departure: str = Field(description="出发城市，例如：北京")
    arrival: str = Field(description="到达城市，例如：上海")
    date: str = Field(description="出发日期，格式 YYYY-MM-DD")


@tool(args_schema=TrainSearchInput)
def search_trains(departure: str, arrival: str, date: str) -> ToolResult:
    """
    搜索国内高铁/动车信息。输入出发城市、到达城市和日期，返回车次列表。
    """
    if not settings.juhe_train_key:
        return ToolResult.degraded(
            "[高铁查询] 聚合数据火车 API Key 未配置",
            error="juhe_train_key_missing",
            source="juhe",
        )

    provider = JuheTrainProvider(settings.juhe_train_key)
    try:
        results = provider.search({"departure": departure, "arrival": arrival, "date": date})
    except Exception as e:
        logger.error("高铁查询失败 | {} → {} | {}", departure, arrival, str(e))
        return ToolResult.degraded(
            f"[高铁查询暂时不可用] {departure} → {arrival}",
            error=str(e),
            source="juhe",
        )

    if not results:
        return ToolResult.degraded(
            f"未找到 {date} 从 {departure} 到 {arrival} 的高铁/动车",
            error="no_train_results",
            source="juhe",
        )

    lines = [f"**{departure} → {arrival} 高铁/动车 ({date})**"]
    for t in results[:5]:
        price_line = f"二等座 ¥{t.get('price_td', 'N/A')}"
        if t.get("price_t1") != "N/A":
            price_line += f" | 一等座 ¥{t['price_t1']}"
        lines.append(
            f"- {t['type']}{t['train_no']} | "
            f"{t['dep_time']} → {t['arr_time']} | {t['duration']} | "
            f"{price_line}"
        )
    return ToolResult.success("\n".join(lines), data=results[:5], source="juhe")
