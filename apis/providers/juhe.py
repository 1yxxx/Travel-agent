"""
聚合数据 API Provider —— 航班 + 火车查询。

接口文档: https://www.juhe.cn/docs

聚合数据（juhe.cn）是国内最大的基础数据 API 平台。
本模块封装了两个 Provider：

- JuheFlightProvider：航班查询（按出发地、目的地、日期）
- JuheTrainProvider：火车/高铁查询（按出发站、到达站、日期）

注意：航班查询需要 IATA 三字码（如 BJS/SHA），本模块内置了
主要城市中文名到 IATA 码的映射。

核心流程：
1. 接收 Agent 传来的搜索参数
2. 调用聚合数据对应的 API 端点
3. 将原始 JSON 响应转为统一的 dict 列表
4. 通过 retry + cache 横切层增强可靠性
"""

import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call

# 聚合数据 API 基础地址
JUHE_FLIGHT_URL = "https://apis.juhe.cn/flight/query"
JUHE_TRAIN_URL = "https://apis.juhe.cn/fapigw/train/query"

# 城市名 → IATA 三字码（用于航班查询）
CITY_TO_IATA = {
    "北京": "BJS",
    "上海": "SHA",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "杭州": "HGH",
    "重庆": "CKG",
    "西安": "XIY",
    "昆明": "KMG",
    "南京": "NKG",
    "武汉": "WUH",
    "长沙": "CSX",
    "厦门": "XMN",
    "青岛": "TAO",
    "三亚": "SYX",
    "大连": "DLC",
    "哈尔滨": "HRB",
    "天津": "TSN",
    "郑州": "CGO",
    "海口": "HAK",
    "贵阳": "KWE",
    "桂林": "KWL",
    "拉萨": "LXA",
    "乌鲁木齐": "URC",
    "福州": "FOC",
    "合肥": "HFE",
    "济南": "TNA",
    "沈阳": "SHE",
    "南宁": "NNG",
    "南昌": "KHN",
    "呼和浩特": "HET",
    "银川": "INC",
    "西宁": "XNN",
    "兰州": "LHW",
    "石家庄": "SJW",
    "长春": "CGQ",
    "太原": "TYN",
}


def _resolve_iata(city: str) -> str:
    """将城市名转为 IATA 三字码，未知城市原样返回。"""
    key = city.strip()
    # 直接匹配
    if key in CITY_TO_IATA:
        return CITY_TO_IATA[key]
    # 尝试去掉"市"后缀
    if key.endswith("市"):
        key = key[:-1]
        if key in CITY_TO_IATA:
            return CITY_TO_IATA[key]
    # 尝试添加"市"后缀
    key2 = city.strip() + "市"
    if key2 in CITY_TO_IATA:
        return CITY_TO_IATA[key2]
    return city.strip().upper()


class JuheFlightProvider(BaseProvider):
    """
    聚合数据航班查询。

    调用 /flight/query 端点，按出发地、目的地、日期搜索航班。

    返回字段：
    - flight_no:   航班号（如 CA0953）
    - airline:     航空公司
    - dep_time:    出发时间
    - arr_time:    到达时间
    - dep_airport: 出发机场
    - arr_airport: 到达机场
    - price:       参考票价
    - duration:    飞行时长
    - transfer_num: 中转次数 (1=直飞)
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索航班。

        参数：
            params: 包含 departure（出发地）、arrival（目的地）、date（日期）的字典
        """
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            resp = requests.get(
                JUHE_FLIGHT_URL,
                params={
                    "key": self.api_key,
                    "departure": _resolve_iata(departure),
                    "arrival": _resolve_iata(arrival),
                    "departureDate": date,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error_code") != 0:
                return []

            flight_info = data.get("result", {}).get("flightInfo", [])
            results = []
            for f in flight_info:
                results.append({
                    "flight_no": f.get("flightNo", "").replace(" | ", "/"),
                    "airline": f.get("airlineName", ""),
                    "dep_time": f.get("departureTime", ""),
                    "arr_time": f.get("arrivalTime", ""),
                    "dep_airport": f.get("departureName", ""),
                    "arr_airport": f.get("arrivalName", ""),
                    "price": f.get("ticketPrice", "N/A"),
                    "duration": f.get("duration", ""),
                    "transfer_num": f.get("transferNum", 1),
                })
            return results

        return retry_api_call(
            lambda: cache_api_call("juhe_flight", params, _fetch)
        )


class JuheTrainProvider(BaseProvider):
    """
    聚合数据火车/高铁查询。

    调用 /fapigw/train/query 端点，按出发站、到达站、日期搜索列车。

    返回字段：
    - train_no:    车次号（如 G25）
    - departure_station: 出发站
    - arrival_station:   到达站
    - dep_time:    出发时间
    - arr_time:    到达时间
    - duration:    运行时长
    - price_td:    二等座价格
    - price_t1:    一等座价格
    - price_biz:   商务座价格
    - price_labels: 票价标签列表
    """

    def search(self, params: dict) -> list[dict]:
        """
        搜索火车/高铁。

        参数：
            params: 包含 departure（出发地）、arrival（目的地）、date（日期）的字典
        """
        departure = params.get("departure", "")
        arrival = params.get("arrival", "")
        date = params.get("date", "")

        def _fetch():
            resp = requests.get(
                JUHE_TRAIN_URL,
                params={
                    "key": self.api_key,
                    "search_type": "1",           # 按站点名称查询
                    "departure_station": departure,
                    "arrival_station": arrival,
                    "date": date,
                    "enable_booking": "2",        # 返回所有班次
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error_code") != 0:
                return []

            trains = data.get("result", [])
            results = []
            for t in trains:
                # 解析票价
                price_map = {}
                for p in t.get("prices", []):
                    price_map[p.get("seat_name", "")] = p.get("price", "N/A")

                # 构建列车标签
                flags = " ".join(t.get("train_flags", []))

                results.append({
                    "train_no": t.get("train_no", ""),
                    "type": flags or self._guess_type(t.get("train_no", "")),
                    "dep_time": t.get("departure_time", ""),
                    "arr_time": t.get("arrival_time", ""),
                    "dep_station": t.get("departure_station", ""),
                    "arr_station": t.get("arrival_station", ""),
                    "duration": t.get("duration", ""),
                    "price_td": price_map.get("二等座", "N/A"),
                    "price_t1": price_map.get("一等座", "N/A"),
                    "price_biz": price_map.get("商务座", "N/A"),
                    "price_labels": price_map,
                })
            return results

        return retry_api_call(
            lambda: cache_api_call("juhe_train", params, _fetch)
        )

    @staticmethod
    def _guess_type(train_no: str) -> str:
        """根据车次号推测车型。"""
        if not train_no:
            return ""
        prefix = train_no[0].upper()
        type_map = {
            "G": "高铁",
            "D": "动车",
            "C": "城际",
            "Z": "直达特快",
            "T": "特快",
            "K": "快速",
        }
        return type_map.get(prefix, "其他")
