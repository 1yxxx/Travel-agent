"""Structured result contract shared by domain tools and agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


ToolStatus = Literal["success", "degraded", "failed"]


@dataclass(frozen=True)
class ToolResult:
    """Explicitly describes whether a tool produced authoritative data."""

    status: ToolStatus
    message: str
    data: Any = None
    error: str = ""
    source: str = ""

    @classmethod
    def success(
        cls,
        message: str,
        *,
        data: Any = None,
        source: str = "",
    ) -> "ToolResult":
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
        return cls("degraded", message, data=data, error=error, source=source)

    @classmethod
    def failed(
        cls,
        message: str,
        *,
        error: str = "",
        source: str = "",
    ) -> "ToolResult":
        return cls("failed", message, error=error, source=source)

    def __str__(self) -> str:
        return self.message


def normalize_tool_result(value: Any) -> ToolResult:
    """Normalize new structured results while keeping legacy string tools usable."""

    if isinstance(value, ToolResult):
        return value
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

    message = str(value).strip()
    if message:
        return ToolResult.success(message)
    return ToolResult.degraded("工具返回为空", error="empty_tool_result")
