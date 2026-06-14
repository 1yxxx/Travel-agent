"""
高德地图 POI 搜索 Provider —— 酒店 + 景点查询。

接口文档: https://lbs.amap.com/api/webservice/guide/api/search

高德地图 POI（Point of Interest，兴趣点）API 提供了丰富的
地理位置搜索能力。本模块封装了两个 Provider：

- AmapHotelProvider：搜索酒店/住宿 POI
- AmapAttractionProvider：搜索景点/风景名胜 POI

核心流程：
1. 接收 Agent 传来的搜索参数（城市、关键词等）
2. 调用高德地图 place/text API
3. 将原始 JSON 响应转为统一的 dict 列表
4. 通过 retry + cache 横切层增强可靠性

Python 新手提示：
- lambda 是匿名函数，lambda: do_something() 等价于 def f(): return do_something()
- 这里用 lambda 包装是因为 retry_api_call 需要接收一个可调用对象
"""

import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

# 高德地图 Web API 基础地址
AMAP_BASE = "https://restapi.amap.com/v3"


class AmapHotelProvider(BaseProvider):
    """
    高德地图酒店搜索。

    调用高德 place/text 接口，types 参数设为 "100000"（住宿服务分类码），
    搜索指定城市的酒店/住宿 POI。

    返回字段：
    - name:     酒店名称
    - address:  详细地址
    - rating:   评分（来自 biz_ext）
    - tel:      联系电话
    - location: 经纬度坐标（"经度,纬度"格式）
    - type:     POI 类型
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索酒店。

        参数：
            params: 包含 city（城市名）、keywords（可选关键词）的字典

        返回：
            酒店 POI 列表，每个元素是包含 name/address/rating 等的字典
        """
        keywords = params.get("keywords", params.get("city", "酒店"))
        city = params.get("city", "")

        def _fetch():
            """
            实际执行 HTTP 请求的内部函数。

            被 retry_api_call 和 cache_api_call 包装：
            - retry：失败时自动重试（指数退避）
            - cache：结果缓存 6 小时（避免重复调用）
            """
            resp = requests.get(
                f"{AMAP_BASE}/place/text",
                params={
                    "key": self.api_key,        # 高德 API Key
                    "keywords": keywords,        # 搜索关键词
                    "city": city,                # 限定城市
                    "types": "100000",           # 高德POI分类码：住宿服务
                    "offset": 10,                # 每页返回数量
                    "extensions": "all",         # 返回详细信息
                },
                timeout=10,                      # 超时 10 秒
            )
            resp.raise_for_status()  # HTTP 错误时抛异常
            pois = resp.json().get("pois", [])

            # 将高德原始数据转为统一的字典格式
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

        # 用 retry + cache 包装 _fetch 函数
        return retry_api_call(
            lambda: cache_api_call("amap_hotel", params, _fetch)
        )


class AmapAttractionProvider(BaseProvider):
    """
    高德地图景点搜索。

    调用高德 place/text 接口，types 参数设为 "110000|140000"
    （风景名胜 + 科教文化场所），搜索指定城市的景点 POI。

    返回字段：
    - name:     景点名称
    - address:  详细地址
    - rating:   评分
    - type:     POI 类型
    - location: 经纬度坐标
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索景点。

        参数：
            params: 包含 city（城市名）、keywords（可选兴趣关键词）的字典

        返回：
            景点 POI 列表
        """
        city = params.get("city", "")
        keywords = params.get("keywords", "景点")

        def _fetch():
            """
            实际执行 HTTP 请求。

            types="110000|140000" 的含义：
            - 110000：风景名胜（国家级景点、公园等）
            - 140000：科教文化场所（博物馆、展览馆等）
            """
            resp = requests.get(
                f"{AMAP_BASE}/place/text",
                params={
                    "key": self.api_key,
                    "keywords": keywords,
                    "city": city,
                    "types": "110000|140000",   # 风景名胜 + 科教文化
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

        # 缓存 24 小时（景点数据变化不频繁）
        return retry_api_call(
            lambda: cache_api_call("amap_attraction", params, _fetch)
        )
