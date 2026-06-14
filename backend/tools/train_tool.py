"""
高铁搜索工具 —— 封装天行数据 API。
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from core.logging import logger
from core.config import settings
from apis.providers.tianxing import TianxingTrainProvider


class TrainSearchInput(BaseModel):
    """高铁搜索参数。"""
    departure: str = Field(description="出发城市，例如：北京")
    arrival: str = Field(description="到达城市，例如：上海")
    date: str = Field(description="出发日期，格式 YYYY-MM-DD")


@tool(args_schema=TrainSearchInput)
def search_trains(departure: str, arrival: str, date: str) -> str:
    """
    搜索国内高铁/动车信息。输入出发城市、到达城市和日期，返回车次列表。
    """
    if not settings.tianxing_api_key:
        return f"[高铁查询] 天行数据 API Key 未配置"

    provider = TianxingTrainProvider(settings.tianxing_api_key)
    try:
        results = provider.search({"departure": departure, "arrival": arrival, "date": date})
    except Exception as e:
        logger.error("高铁查询失败 | {} → {} | {}", departure, arrival, str(e))
        return f"[高铁查询暂时不可用] {departure} → {arrival}"

    if not results:
        return f"未找到 {date} 从 {departure} 到 {arrival} 的高铁/动车"

    lines = [f"**{departure} → {arrival} 高铁/动车 ({date})**"]
    for t in results[:5]:
        lines.append(
            f"- {t['type']}{t['train_no']} | "
            f"{t['dep_time']} → {t['arr_time']} | {t['duration']} | "
            f"二等座 ¥{t.get('price_td', 'N/A')}"
        )
    return "\n".join(lines)