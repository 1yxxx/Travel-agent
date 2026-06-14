"""
天行数据 API Provider —— 航班 + 高铁查询。

接口文档: https://www.tianapi.com/apiview/
"""
import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

TIANXING_BASE = "https://apis.tianapi.com"


class TianxingFlightProvider(BaseProvider):
    """天行数据航班查询。"""

    def search(self, params: dict) -> list[dict]:
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            resp = requests.get(
                f"{TIANXING_BASE}/flight/index",
                params={
                    "key": self.api_key,
                    "dep": departure,
                    "arr": arrival,
                    "date": date,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                return []
            flights = data.get("result", {}).get("list", [])
            return [
                {
                    "flight_no": f.get("flightno"),
                    "airline": f.get("airlines"),
                    "dep_time": f.get("deptime"),
                    "arr_time": f.get("arrtime"),
                    "dep_airport": f.get("depairport"),
                    "arr_airport": f.get("arrairport"),
                    "price": f.get("price", "N/A"),
                }
                for f in flights
            ]

        return retry_api_call(
            lambda: cache_api_call("tianxing_flight", params, _fetch)
        )


class TianxingTrainProvider(BaseProvider):
    """天行数据高铁/火车查询。"""

    def search(self, params: dict) -> list[dict]:
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            resp = requests.get(
                f"{TIANXING_BASE}/train/index",
                params={
                    "key": self.api_key,
                    "dep": departure,
                    "arr": arrival,
                    "date": date,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                return []
            trains = data.get("result", {}).get("list", [])
            return [
                {
                    "train_no": t.get("trainno"),
                    "type": t.get("type"),
                    "dep_time": t.get("deptime"),
                    "arr_time": t.get("arrtime"),
                    "dep_station": t.get("depstation"),
                    "arr_station": t.get("arrstation"),
                    "duration": t.get("duration"),
                    "price_td": t.get("price_td", "N/A"),  # 二等座
                    "price_t1": t.get("price_t1", "N/A"),  # 一等座
                }
                for t in trains
            ]

        return retry_api_call(
            lambda: cache_api_call("tianxing_train", params, _fetch)
        )