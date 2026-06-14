"""
天气预报请求标准化工具函数。

和风天气 API 的限制：
- 免费版仅支持 3 天（3d）和 7 天（7d）两种预报端点
- 不能按任意天数查询（如 5 天预报需要映射到 7d 端点）

本模块的作用：
- 将用户请求的任意天数（1-7 天）映射到和风天气支持的端点
- 例如：用户想查 4 天天气 → 实际调用 7d 端点（返回 7 天数据，前端截取前 4 天）

Python 新手提示：
- tuple 是不可变的列表，用圆括号定义
- int() 可以将字符串转为整数，但传入 float 也会截断小数
"""

from __future__ import annotations

# 和风天气免费版支持的预报天数端点
# 注意：这里的 3 和 7 是 API 端点标识，不是任意数字
SUPPORTED_FORECAST_DAYS = (3, 7)


def normalize_forecast_days(days: int) -> int:
    """
    将任意行程天数映射到和风天气支持的端点。

    映射规则（向上取整）：
    - 用户请求 1 天 → 返回 3（调用 3d 端点）
    - 用户请求 2 天 → 返回 3（调用 3d 端点）
    - 用户请求 3 天 → 返回 3（调用 3d 端点）
    - 用户请求 4 天 → 返回 7（调用 7d 端点）
    - 用户请求 5 天 → 返回 7（调用 7d 端点）
    - 用户请求 7 天 → 返回 7（调用 7d 端点）
    - 用户请求 8+ 天 → 返回 7（超出免费版限制，取最大）

    参数：
        days: 用户请求的天数（可以是任意正整数）

    返回：
        和风天气支持的端点天数（3 或 7）

    使用示例：
        >>> normalize_forecast_days(4)
        7
        >>> normalize_forecast_days(3)
        3
    """

    # 确保至少为 1 天（防止传入 0 或负数）
    requested = max(int(days), 1)

    # 从小到大遍历支持的端点，找到第一个 >= 请求天数的端点
    for supported in SUPPORTED_FORECAST_DAYS:
        if requested <= supported:
            return supported

    # 如果请求天数超过所有支持的端点，返回最大的那个
    return SUPPORTED_FORECAST_DAYS[-1]
