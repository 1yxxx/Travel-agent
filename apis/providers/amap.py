"""
高德地图 POI 搜索 Provider —— 酒店 + 景点查询。

接口文档: https://lbs.amap.com/api/webservice/guide/api/search
"""
import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

AMAP_BASE = "https://restapi.amap.com/v3"


class AmapHotelProvider(BaseProvider):
    """高德地图酒店搜索。"""

    def search(self, params: dict) -> list[dict]:
        keywords = params.get("keywords", params.get("city", "酒店"))
        city = params.get("city", "")

        def _fetch():
            resp = requests.get(
                f"{AMAP_BASE}/place/text",
                params={
                    "key": self.api_key,
                    "keywords": keywords,
                    "city": city,
                    "types": "100000",  # 住宿服务
                    "offset": 10,
                    "extensions": "all",
                },
                timeout=10,
            )
            resp.raise_for_status()
            pois = resp.json().get("pois", [])
            return [
                {
                    "name": p.get("name"),
                    "address": p.get("address"),
                    "rating": p.get("biz_ext", {}).get("rating", "N/A"),
                    "tel": p.get("tel", ""),
                    "location": p.get("location"),
                    "type": p.get("type"),
                }
                for p in pois
            ]

        return retry_api_call(
            lambda: cache_api_call("amap_hotel", params, _fetch)
        )


class AmapAttractionProvider(BaseProvider):
    """高德地图景点搜索。"""

    def search(self, params: dict) -> list[dict]:
        city = params.get("city", "")
        keywords = params.get("keywords", "景点")

        def _fetch():
            resp = requests.get(
                f"{AMAP_BASE}/place/text",
                params={
                    "key": self.api_key,
                    "keywords": keywords,
                    "city": city,
                    "types": "110000|140000",  # 风景名胜 + 科教文化
                    "offset": 10,
                    "extensions": "all",
                },
                timeout=10,
            )
            resp.raise_for_status()
            pois = resp.json().get("pois", [])
            return [
                {
                    "name": p.get("name"),
                    "address": p.get("address"),
                    "rating": p.get("biz_ext", {}).get("rating", "N/A"),
                    "type": p.get("type"),
                    "location": p.get("location"),
                }
                for p in pois
            ]

        return retry_api_call(
            lambda: cache_api_call("amap_attraction", params, _fetch)
        )