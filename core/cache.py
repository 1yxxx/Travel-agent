"""
API 响应缓存 —— 基于 DiskCache (SQLite)，分级 TTL。

用法:
    from core.cache import cache_api_call
    result = cache_api_call("amap_hotel", params, fetch_func)
"""
import hashlib
import json
from diskcache import Cache
from pathlib import Path
from core.logging import logger
from core.config import settings

# 缓存目录
_cache_dir = Path(__file__).resolve().parents[1] / "cache_db"
_cache_dir.mkdir(parents=True, exist_ok=True)
cache = Cache(str(_cache_dir))

# 不同 Provider 的 TTL（秒）
PROVIDER_TTL = {
    "amap_hotel": 6 * 3600,        # 高德酒店: 6h
    "amap_attraction": 24 * 3600,  # 高德景点: 24h
    "tianxing_flight": 24 * 3600,  # 天行航班: 24h
    "tianxing_train": 24 * 3600,   # 天行高铁: 24h
    "qweather": 1 * 3600,          # 和风天气: 1h
}


def _cache_key(provider: str, params: dict) -> str:
    """生成确定性缓存键。"""
    raw = json.dumps({"p": provider, "a": sorted(params.items())}, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def cache_api_call(provider: str, params: dict, fetch_func):
    """
    带缓存的 API 调用。

    Args:
        provider: Provider 名称 (如 "amap_hotel")
        params: 请求参数字典
        fetch_func: 无缓存时调用的获取函数

    Returns:
        fetch_func 的返回值（从缓存或新调用）
    """
    key = _cache_key(provider, params)
    if key in cache:
        logger.debug("缓存命中 | provider={} key={}", provider, key[:8])
        return cache[key]

    logger.info("API 调用 | provider={} params={}", provider, {k: v for k, v in params.items() if "key" not in k.lower()})
    result = fetch_func()
    ttl = PROVIDER_TTL.get(provider, settings.cache_ttl_hours * 3600)
    cache.set(key, result, expire=ttl)
    return result


def clear_cache(provider: str = None):
    """清除缓存。不传 provider 则全部清除。"""
    if provider:
        count = 0
        for key in list(cache):
            if provider in str(cache.get(key, ""))[:200]:
                del cache[key]
                count += 1
        logger.info("缓存清除 | provider={} count={}", provider, count)
    else:
        cache.clear()
        logger.info("缓存全部清除")