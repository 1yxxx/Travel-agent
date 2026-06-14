"""
和风天气 API Provider —— JWT 认证 + 全球天气。

接口文档: https://dev.qweather.com/docs/api/

认证方式：Ed25519 JWT (JSON Web Token)
查询流程：
1. GeoAPI 城市搜索 → Location ID
   https://api.qweather.com/geo/v2/city/lookup
2. 天气预报 → 每日预报数据
   https://api.qweather.com/v7/weather/{days}

免费订阅每月 5 万次请求，支持全球城市。
"""

import time
import requests
from apis.base import BaseProvider
from core.retry import retry_api_call
from core.cache import cache_api_call
from backend.tools.weather_utils import normalize_forecast_days

# 和风天气 API 地址
QWEATHER_HOST = "https://api.qweather.com"

# JWT 库延迟导入
def _build_jwt(key_id: str, private_key_b64: str) -> str:
    """构建和风天气 JWT Token。"""
    import base64
    import json
    from cryptography.hazmat.primitives.serialization import load_der_private_key

    # 解码 base64 私钥
    raw = base64.b64decode(private_key_b64)
    private_key = load_der_private_key(raw, password=None)

    # JWT header
    header = {"alg": "EdDSA", "kid": key_id}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")

    # JWT payload
    payload = {
        "sub": key_id,
        "iat": int(time.time()) - 30,
        "exp": int(time.time()) + 300,  # 5 分钟有效期
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")

    # 签名
    from cryptography.hazmat.primitives import hashes
    signing_input = header_b64 + b"." + payload_b64
    signature = private_key.sign(signing_input)
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")

    return (signing_input + b"." + sig_b64).decode()


class QweatherProvider(BaseProvider):
    """
    和风天气查询 —— JWT 认证，全球城市。

    返回字段：date, temp_max, temp_min, text_day, wind_dir, wind_scale, humidity
    """

    def __init__(self, key_id: str, private_key: str):
        self.key_id = key_id
        self.private_key = private_key

    def _get_token(self) -> str:
        return _build_jwt(self.key_id, self.private_key)

    def search(self, params: dict) -> list[dict]:
        city = params.get("city", "")
        requested_days = min(max(int(params.get("days", 3)), 1), 10)
        endpoint_days = normalize_forecast_days(requested_days)

        def _fetch_location():
            """第 1 步：城市搜索 → Location ID"""
            token = self._get_token()
            resp = requests.get(
                f"{QWEATHER_HOST}/geo/v2/city/lookup",
                params={"location": city, "number": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 403:
                return None  # API 未启用或凭据问题
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "200":
                return None
            locs = data.get("location", [])
            return locs[0]["id"] if locs else None

        def _fetch():
            """第 2 步：天气预报"""
            location_id = _fetch_location()
            if not location_id:
                return [{"error": f"未找到城市: {city}"}]

            token = self._get_token()
            resp = requests.get(
                f"{QWEATHER_HOST}/v7/weather/{endpoint_days}d",
                params={"location": location_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "200":
                return [{"error": f"API 异常: {data.get('code')}"}]

            daily = data.get("daily", [])
            return [
                {
                    "date": d.get("fxDate"),
                    "temp_max": d.get("tempMax"),
                    "temp_min": d.get("tempMin"),
                    "text_day": d.get("textDay"),
                    "wind_dir": d.get("windDirDay"),
                    "wind_scale": d.get("windScaleDay"),
                    "humidity": d.get("humidity"),
                }
                for d in daily
            ]

        cache_params = {"city": city, "days": endpoint_days}
        results = retry_api_call(
            lambda: cache_api_call("qweather", cache_params, _fetch)
        )
        return results[:requested_days]
