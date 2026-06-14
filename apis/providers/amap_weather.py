"""
高德天气 API Provider —— 作为和风天气的备用数据源。

接口文档: https://lbs.amap.com/api/webservice/guide/api/weatherinfo

高德天气不需要地理编码，直接传城市名+adcode 即可。
返回 4 天预报（当天 + 未来 3 天）。
"""

import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


class AmapWeatherProvider(BaseProvider):
    """
    高德天气查询（作为和风天气的降级备选）。

    返回字段：
    - date:       日期
    - temp_max:   最高温度
    - temp_min:   最低温度
    - text_day:   白天天气
    - wind_dir:   风向
    - wind_scale: 风力
    """

    def search(self, params: dict) -> list[dict]:
        city = params.get("city", "")
        days = min(max(int(params.get("days", 3)), 1), 4)

        def _fetch():
            resp = requests.get(
                AMAP_WEATHER_URL,
                params={
                    "key": self.api_key,
                    "city": city,
                    "extensions": "all",  # 返回预报（默认只返回当天）
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "1":
                return [{"error": data.get("info", "查询失败")}]

            forecasts = data.get("forecasts", [])
            if not forecasts:
                return [{"error": f"未找到城市: {city}"}]

            # 取第一个匹配城市的预报
            casts = forecasts[0].get("casts", [])
            results = []
            for c in casts[:days]:
                results.append({
                    "date": c.get("date", ""),
                    "temp_max": c.get("daytemp", ""),
                    "temp_min": c.get("nighttemp", ""),
                    "text_day": c.get("dayweather", ""),
                    "wind_dir": c.get("daywind", ""),
                    "wind_scale": c.get("daypower", ""),
                })
            return results

        cache_params = {"city": city, "days": days}
        return retry_api_call(
            lambda: cache_api_call("amap_weather", cache_params, _fetch)
        )
