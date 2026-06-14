"""
API 调用重试 —— 基于 Tenacity，指数退避 + 异常匹配。

用法:
    from core.retry import retry_api_call
    result = retry_api_call(my_api_function, arg1, arg2)
"""
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from core.logging import logger
from core.config import settings

# 可重试的异常类型
RETRYABLE = (
    requests.ConnectionError,
    requests.Timeout,
    requests.HTTPError,
    OSError,
)


def retry_api_call(func, *args, **kwargs):
    """
    带指数退避重试的 API 调用包装器。

    Args:
        func: 要调用的函数
        *args, **kwargs: 传递给 func 的参数

    Returns:
        func 的返回值

    Raises:
        最后一次重试失败后的异常
    """
    decorated = retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(min=settings.retry_min_wait, max=10),
        retry=retry_if_exception_type(RETRYABLE),
        before_sleep=before_sleep_log(logger, "WARNING"),
        reraise=True,
    )(func)
    return decorated(*args, **kwargs)


def retry_async_api_call(func):
    """
    异步 API 调用的重试装饰器。

    用法:
        @retry_async_api_call
        async def fetch_data(param):
            ...
    """
    return retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(min=settings.retry_min_wait, max=10),
        retry=retry_if_exception_type(RETRYABLE),
        before_sleep=before_sleep_log(logger, "WARNING"),
        reraise=True,
    )(func)