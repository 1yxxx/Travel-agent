"""
酒店价格 Mock Provider —— 携程需要企业资质，先用 Mock 数据占位。
"""
import random
from apis.base import BaseProvider

CITY_PRICE_BASE = {
    "北京": 450, "上海": 500, "广州": 350, "深圳": 400,
    "杭州": 380, "成都": 300, "重庆": 280, "西安": 250,
    "南京": 320, "武汉": 260, "长沙": 220, "厦门": 400,
    "三亚": 550, "昆明": 280, "青岛": 350, "大连": 300,
}


class MockPriceProvider(BaseProvider):
    """酒店价格 Mock。"""

    def search(self, params: dict) -> list[dict]:
        city = params.get("city", "")
        star = params.get("star", 4)
        nights = params.get("nights", 3)

        base = CITY_PRICE_BASE.get(city, 300)
        star_multiplier = {3: 0.7, 4: 1.0, 5: 1.8}.get(star, 1.0)
        price_per_night = int(base * star_multiplier * random.uniform(0.8, 1.2))
        total = price_per_night * nights

        return [
            {
                "price_per_night": price_per_night,
                "total": total,
                "currency": "CNY",
                "note": "参考价格（携程开放平台需企业资质）",
            }
        ]