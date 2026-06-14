"""
和风天气 API Provider —— 实时天气 + 7天预报。

接口文档: https://dev.qweather.com/docs/api/weather/
"""
import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

QWEATHER_BASE = "https://devapi.qweather.com/v7"


class QweatherProvider(BaseProvider):
    """和风天气查询。"""

    def search(self, params: dict) -> list[dict]:
        city = params.get("city", "")
        days = params.get("days", 3)

        def _fetch_city():
            """先通过城市名获取 Location ID。"""
            resp = requests.get(
                f"https://geoapi.qweather.com/v2/city/lookup",
                params={"key": self.api_key, "location": city},
                timeout=10,
            )
            resp.raise_for_status()
            locs = resp.json().get("location", [])
            return locs[0]["id"] if locs else None

        def _fetch():
            location_id = _fetch_city()
            if not location_id:
                return [{"error": f"未找到城市: {city}"}]

            resp = requests.get(
                f"{QWEATHER_BASE}/weather/{days}d",
                params={"key": self.api_key, "location": location_id},
                timeout=10,
            )
            resp.raise_for_status()
            daily = resp.json().get("daily", [])
            return [
                {
                    "date": d.get("fxDate"),
                    "temp_max": d.get("tempMax"),
                    "temp_min": d.get("tempMin"),
                    "text_day": d.get("textDay"),
                    "wind_dir": d.get("windDirDay"),
                    "wind_scale": d.get("windScaleDay"),
                    "humidity": d.get("humidity"),
                }
                for d in daily
            ]

        return retry_api_call(
            lambda: cache_api_call("qweather", params, _fetch)
        )