"""
天行数据 API Provider —— 航班 + 高铁查询。

接口文档: https://www.tianapi.com/apiview/

天行数据提供了国内航班和高铁的实时查询 API。
本模块封装了两个 Provider：

- TianxingFlightProvider：航班查询（按出发地、目的地、日期）
- TianxingTrainProvider：高铁/火车查询（按出发地、目的地、日期）

核心流程：
1. 接收 Agent 传来的搜索参数
2. 调用天行数据对应的 API 端点
3. 将原始 JSON 响应转为统一的 dict 列表
4. 通过 retry + cache 横切层增强可靠性

Python 新手提示：
- dict.get("key", default) 安全地获取字典值，键不存在时返回默认值
- 列表推导式 [f(x) for x in items] 是 Python 中常见的简洁写法
"""

import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

# 天行数据 API 基础地址
TIANXING_BASE = "https://apis.tianapi.com"


class TianxingFlightProvider(BaseProvider):
    """
    天行数据航班查询。

    调用 /flight/index 端点，按出发地、目的地、日期搜索航班。

    返回字段：
    - flight_no:   航班号（如 CA1234）
    - airline:     航空公司
    - dep_time:    出发时间
    - arr_time:    到达时间
    - dep_airport: 出发机场
    - arr_airport: 到达机场
    - price:       参考价格
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索航班。

        参数：
            params: 包含 departure（出发地）、arrival（目的地）、date（日期）的字典

        返回：
            航班列表，code != 200 时返回空列表
        """
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            """
            实际执行 HTTP 请求。

            天行数据 API 的响应格式：
            {
                "code": 200,           # 200 表示成功
                "result": {
                    "list": [...]       # 航班列表
                }
            }
            """
            resp = requests.get(
                f"{TIANXING_BASE}/flight/index",
                params={
                    "key": self.api_key,    # 天行数据 API Key
                    "dep": departure,        # 出发城市
                    "arr": arrival,          # 到达城市
                    "date": date,            # 出发日期
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            # code != 200 表示请求失败（如余额不足、参数错误等）
            if data.get("code") != 200:
                return []

            flights = data.get("result", {}).get("list", [])

            # 将天行原始数据转为统一的字典格式
            return [
                {
                    "flight_no": f.get("flightno"),     # 航班号
                    "airline": f.get("airlines"),        # 航空公司
                    "dep_time": f.get("deptime"),         # 出发时间
                    "arr_time": f.get("arrtime"),         # 到达时间
                    "dep_airport": f.get("depairport"),   # 出发机场
                    "arr_airport": f.get("arrairport"),   # 到达机场
                    "price": f.get("price", "N/A"),       # 参考价格
                }
                for f in flights
            ]

        # 缓存 24 小时（航班数据变化不频繁）
        return retry_api_call(
            lambda: cache_api_call("tianxing_flight", params, _fetch)
        )


class TianxingTrainProvider(BaseProvider):
    """
    天行数据高铁/火车查询。

    调用 /train/index 端点，按出发地、目的地、日期搜索列车。

    返回字段：
    - train_no:    车次号（如 G123）
    - type:        车型（高铁/动车/普速等）
    - dep_time:    出发时间
    - arr_time:    到达时间
    - dep_station: 出发站
    - arr_station: 到达站
    - duration:    运行时长
    - price_td:    二等座价格（td = 二等）
    - price_t1:    一等座价格（t1 = 一等）
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索高铁/火车。

        参数：
            params: 包含 departure（出发地）、arrival（目的地）、date（日期）的字典

        返回：
            列车列表
        """
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            """
            实际执行 HTTP 请求。

            返回数据中 price_td 和 price_t1 的含义：
            - price_td：二等座价格（td = "二等"的拼音首字母）
            - price_t1：一等座价格（t1 = "一等"的简写）
            """
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
                    "train_no": t.get("trainno"),      # 车次号
                    "type": t.get("type"),              # 车型（高铁/动车/普速）
                    "dep_time": t.get("deptime"),        # 出发时间
                    "arr_time": t.get("arrtime"),        # 到达时间
                    "dep_station": t.get("depstation"),  # 出发站
                    "arr_station": t.get("arrstation"),  # 到达站
                    "duration": t.get("duration"),       # 运行时长
                    "price_td": t.get("price_td", "N/A"),  # 二等座价格
                    "price_t1": t.get("price_t1", "N/A"),  # 一等座价格
                }
                for t in trains
            ]

        return retry_api_call(
            lambda: cache_api_call("tianxing_train", params, _fetch)
        )
