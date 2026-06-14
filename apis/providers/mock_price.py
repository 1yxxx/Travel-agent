"""
酒店价格 Mock Provider —— 携程需要企业资质，先用 Mock 数据占位。

为什么需要 Mock？
- 携程开放平台需要企业资质才能接入
- 个人开发者无法获取真实酒店价格 API
- 使用 Mock 数据可以让系统在缺少真实 API 时仍然正常运行

Mock 策略：
- 为 16 个热门城市预设了基准价格（基于市场调研）
- 按星级调整价格（3星×0.7、4星×1.0、5星×1.8）
- 加入 ±20% 的随机波动，模拟真实价格的变化

当真实 API 可用时，只需替换此 Provider 即可，不影响上层代码。

Python 新手提示：
- random.uniform(0.8, 1.2) 生成 0.8 到 1.2 之间的随机浮点数
- dict.get(key, default) 在键不存在时返回默认值，避免 KeyError
"""

import random
from apis.base import BaseProvider

# 16 个热门城市的基准酒店价格（元/晚，以四星级为标准）
# 数据来源：市场调研估算，仅供参考
CITY_PRICE_BASE = {
    "北京": 450, "上海": 500, "广州": 350, "深圳": 400,
    "杭州": 380, "成都": 300, "重庆": 280, "西安": 250,
    "南京": 320, "武汉": 260, "长沙": 220, "厦门": 400,
    "三亚": 550, "昆明": 280, "青岛": 350, "大连": 300,
}


class MockPriceProvider(BaseProvider):
    """
    酒店价格 Mock 实现。

    计算逻辑：
    1. 根据城市查基准价格（不在列表中的城市默认为 300 元/晚）
    2. 按星级乘以系数：
       - 3 星：基准价 × 0.7（经济型）
       - 4 星：基准价 × 1.0（舒适型）
       - 5 星：基准价 × 1.8（豪华型）
    3. 乘以随机因子（0.8~1.2），模拟价格波动
    4. 总价 = 每晚价格 × 入住天数

    返回字段：
    - price_per_night: 每晚参考价格（元）
    - total:           总价（元）
    - currency:        货币类型（CNY）
    - note:            数据来源说明
    """

    def search(self, params: dict) -> list[dict]:
        """
        生成模拟酒店价格。

        参数：
            params: 包含 city（城市名）、star（星级，3/4/5）、nights（天数）的字典

        返回：
            包含一条模拟价格记录的列表
        """
        city = params.get("city", "")
        star = params.get("star", 4)    # 默认四星级
        nights = params.get("nights", 3)  # 默认 3 晚

        # 查基准价（未知城市默认 300）
        base = CITY_PRICE_BASE.get(city, 300)

        # 星级价格系数
        # 3 星 = 基准的 70%，4 星 = 100%，5 星 = 180%
        star_multiplier = {3: 0.7, 4: 1.0, 5: 1.8}.get(star, 1.0)

        # 加入随机波动（±20%），模拟真实市场的价格变化
        price_per_night = int(base * star_multiplier * random.uniform(0.8, 1.2))
        total = price_per_night * nights

        return [
            {
                "price_per_night": price_per_night,
                "total": total,
                "currency": "CNY",
                "note": "参考价格（携程开放平台需企业资质，当前为模拟数据）",
            }
        ]
