"""
和风天气 API Provider —— 实时天气 + 多天预报。

接口文档: https://dev.qweather.com/docs/api/weather/

和风天气是国内常用的天气数据服务商，提供免费版 API。
本模块封装了天气查询的完整流程：

两步查询流程：
1. 地理编码：城市名 → Location ID（如"北京" → "101010100"）
   调用 https://geoapi.qweather.com/v2/city/lookup
2. 天气预报：Location ID → 天气预报数据
   调用 https://devapi.qweather.com/v7/weather/3d 或 /7d

天数映射（和风天气免费版只支持 3d 和 7d）：
- 用户请求 1-3 天 → 调用 3d 端点
- 用户请求 4-7 天 → 调用 7d 端点

Python 新手提示：
- resp.raise_for_status() 在 HTTP 状态码非 200 时自动抛异常
- resp.json() 将 HTTP 响应的 JSON body 解析为 Python 字典
- 列表推导式 [d.get("fxDate") for d in daily] 简洁地从列表中提取字段
"""

import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call
from backend.tools.weather_utils import normalize_forecast_days

# 和风天气 API 基础地址
QWEATHER_BASE = "https://devapi.qweather.com/v7"


class QweatherProvider(BaseProvider):
    """
    和风天气查询。

    返回字段：
    - date:       日期（如 2026-08-01）
    - temp_max:   最高温度（°C）
    - temp_min:   最低温度（°C）
    - text_day:   白天天气描述（如"晴"、"多云"）
    - wind_dir:   风向
    - wind_scale: 风力等级
    - humidity:   相对湿度（%）
    """

    def search(self, params: dict) -> list[dict]:
        """
        查询天气预报。

        参数：
            params: 包含 city（城市名）、days（天数，1-7）的字典

        返回：
            天气预报列表，每天一个元素

        流程：
        1. 先通过地理编码 API 获取城市的 Location ID
        2. 再用 Location ID 调用天气预报 API
        """
        city = params.get("city", "")

        # 限制天数范围并映射到支持的端点
        requested_days = min(max(int(params.get("days", 3)), 1), 7)
        endpoint_days = normalize_forecast_days(requested_days)

        def _fetch_city():
            """
            第 1 步：通过城市名获取 Location ID。

            和风天气的所有天气 API 都需要 Location ID，
            不能直接用城市名。所以需要先查一次地理编码。

            例如："北京" → 调用 city/lookup → 返回 location id "101010100"
            """
            resp = requests.get(
                f"https://geoapi.qweather.com/v2/city/lookup",
                params={
                    "key": self.api_key,
                    "location": city,
                },
                timeout=10,
            )
            resp.raise_for_status()
            locs = resp.json().get("location", [])
            # 取第一个匹配结果的 ID
            return locs[0]["id"] if locs else None

        def _fetch():
            """
            第 2 步：用 Location ID 获取天气预报。
            """
            # 先查城市 ID
            location_id = _fetch_city()
            if not location_id:
                return [{"error": f"未找到城市: {city}"}]

            # 根据映射后的天数选择端点
            # 例如：用户要 4 天 → normalize_forecast_days(4) = 7 → 调用 /v7/weather/7d
            resp = requests.get(
                f"{QWEATHER_BASE}/weather/{endpoint_days}d",
                params={
                    "key": self.api_key,
                    "location": location_id,
                },
                timeout=10,
            )
            resp.raise_for_status()
            daily = resp.json().get("daily", [])

            # 将和风原始数据转为统一的字典格式
            return [
                {
                    "date": d.get("fxDate"),          # 预报日期
                    "temp_max": d.get("tempMax"),      # 最高温度
                    "temp_min": d.get("tempMin"),      # 最低温度
                    "text_day": d.get("textDay"),      # 白天天气
                    "wind_dir": d.get("windDirDay"),   # 白天风向
                    "wind_scale": d.get("windScaleDay"), # 白天风力
                    "humidity": d.get("humidity"),     # 湿度
                }
                for d in daily
            ]

        # 缓存参数只包含 city + endpoint_days（不包含 requested_days）
        # 因为缓存的是完整端点数据，不同 requested_days 可能命中同一缓存
        cache_params = {"city": city, "days": endpoint_days}

        # 执行查询（带重试和缓存）
        results = retry_api_call(
            lambda: cache_api_call("qweather", cache_params, _fetch)
        )

        # 截取用户实际需要的天数
        # 例如：调了 7d 端点但用户只要 4 天，只返回前 4 天
        return results[:requested_days]
