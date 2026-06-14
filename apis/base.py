"""
API Provider 抽象基类 —— 定义统一接口。

所有 Provider 必须实现 search() 方法，返回统一格式的 list[dict]。
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """数据源 Provider 抽象基类。"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.provider_name = self.__class__.__name__

    @abstractmethod
    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """
        执行搜索，返回统一格式的结果列表。

        Args:
            params: 查询参数（与 Provider 类型相关）

        Returns:
            list[dict]: 统一格式的结果列表
        """
        ...