"""
统一工具返回结果契约 —— Agent 和 Tool 之间的数据交换标准。

设计原则（需求文档 §11）：
- Agent 不直接处理原始 HTTP 响应，而是通过 ToolResult 获取标准化结果
- 明确区分三种状态：成功（权威数据）、降级（备选方案）、失败（不可用）
- 新旧工具兼容：旧工具返回字符串时自动包装为 ToolResult

Python 新手提示：
- @dataclass 是 Python 的"数据类"，自动生成 __init__ 等方法，比普通类更简洁
- frozen=True 表示实例创建后不可修改（不可变对象，更安全）
- @classmethod 是"类方法"，第一个参数是类本身（cls）而非实例（self）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

# ======================== 工具状态类型 ========================

# Literal 类型表示只能取这三个值之一，写错会触发类型检查器报错
ToolStatus = Literal["success", "degraded", "failed"]
"""
工具执行结果的三种状态：
- success  ✅：工具正常返回了权威数据（如和风天气实时预报）
- degraded ⚠️：工具不可用但提供了降级输出（如 API Key 缺失时返回通用建议）
- failed   ❌：工具完全失败，无可用数据
"""


# ======================== ToolResult 数据类 ========================

@dataclass(frozen=True)
class ToolResult:
    """
    明确描述工具是否产出了权威数据的标准化结果。

    每个 Tool（如 search_flights、search_weather）都返回此类型，
    Agent 根据 status 决定如何使用结果：
    - success  → 直接使用权威数据
    - degraded → 标注"该维度信息暂不完整"后参与方案生成
    - failed   → 跳过该维度，由 Supervisor 在最终方案中标记

    字段说明：
        status:  执行状态（success / degraded / failed）
        message: 人类可读的结果文本（会直接展示给用户）
        data:    结构化数据（供下游程序使用，可选）
        error:   错误信息（仅在 degraded 或 failed 时有值）
        source:  数据来源标识（如 "qweather"、"amap"），用于排障
    """

    status: ToolStatus
    message: str
    data: Any = None
    error: str = ""
    source: str = ""

    # ---- 工厂方法：提供语义化的创建方式 ----

    @classmethod
    def success(
        cls,
        message: str,
        *,
        data: Any = None,
        source: str = "",
    ) -> "ToolResult":
        """
        创建一个"成功"的结果。

        使用示例：
            return ToolResult.success(
                "北京 8月1日 晴 25°C~35°C",
                data={"temp_max": 35, "temp_min": 25},
                source="qweather",
            )
        """
        return cls("success", message, data=data, source=source)

    @classmethod
    def degraded(
        cls,
        message: str,
        *,
        data: Any = None,
        error: str = "",
        source: str = "",
    ) -> "ToolResult":
        """
        创建一个"降级"的结果。

        降级意味着：工具无法获取权威数据，但返回了备选方案。
        例如：和风天气 API Key 未配置，返回一段通用天气建议。

        使用示例：
            return ToolResult.degraded(
                "建议查看当地天气预报，8月北京通常炎热多雨。",
                error="qweather_api_key_missing",
                source="fallback",
            )
        """
        return cls("degraded", message, data=data, error=error, source=source)

    @classmethod
    def failed(
        cls,
        message: str,
        *,
        error: str = "",
        source: str = "",
    ) -> "ToolResult":
        """
        创建一个"失败"的结果。

        失败意味着：工具完全不可用，且没有备选方案。
        Supervisor 会在最终方案中标记该维度信息缺失。

        使用示例：
            return ToolResult.failed(
                "无法查询航班信息",
                error="tianxing_api_timeout",
                source="tianxing",
            )
        """
        return cls("failed", message, error=error, source=source)

    def __str__(self) -> str:
        """让 ToolResult 可以像字符串一样使用。"""
        return self.message


# ======================== 结果标准化函数 ========================

def normalize_tool_result(value: Any) -> ToolResult:
    """
    将任意工具返回值标准化为 ToolResult。

    兼容三种输入：
    1. 已经是 ToolResult → 直接返回
    2. 字典（含 status 字段）→ 转换为 ToolResult
    3. 字符串 → 包装为 ToolResult.success()
    4. 空字符串 → 包装为 ToolResult.degraded()

    这个函数的作用是"统一入口"：无论新旧工具返回什么格式，
    经过 normalize_tool_result 后都是标准的 ToolResult。

    使用场景：
        raw = old_tool.invoke(params)        # 旧工具可能返回字符串
        result = normalize_tool_result(raw)  # 统一转换为 ToolResult
    """

    # 情况 1：已经是 ToolResult 实例
    if isinstance(value, ToolResult):
        return value

    # 情况 2：字典格式（兼容旧代码中返回 {"status": "success", ...} 的工具）
    if isinstance(value, Mapping) and value.get("status") in {
        "success",
        "degraded",
        "failed",
    }:
        return ToolResult(
            status=value["status"],
            message=str(value.get("message", "")),
            data=value.get("data"),
            error=str(value.get("error", "")),
            source=str(value.get("source", "")),
        )

    # 情况 3 & 4：字符串（旧工具最常见的返回格式）
    message = str(value).strip()
    if message:
        return ToolResult.success(message)
    return ToolResult.degraded("工具返回为空", error="empty_tool_result")
