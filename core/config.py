"""
全局配置管理 —— Pydantic Settings，统一加载运行配置。

替代后端各处 `os.getenv` 的分散写法。
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """全局配置。各能力在实际使用时校验所需密钥。"""

    # --- LLM ---
    openai_api_key: str = Field("", description="OpenAI 兼容 API Key")
    openai_base_url: str = Field("https://api.openai.com/v1", description="API 基础地址，可切 DeepSeek")
    openai_model: str = Field("gpt-4o-mini", description="默认模型名称")
    llm_temperature: float = Field(0.7, ge=0.0, le=2.0, description="LLM 采样温度")

    # --- 国内 API (可选) ---
    amap_api_key: str = Field("", description="高德地图 Web API Key")
    tianxing_api_key: str = Field("", description="天行数据 API Key")
    qweather_api_key: str = Field("", description="和风天气 API Key")

    # --- 可观测性 ---
    langsmith_api_key: str = Field("", description="LangSmith API Key")
    langsmith_project: str = Field("travel-agent", description="LangSmith 项目名")

    # --- 持久化 ---
    redis_url: str = Field("redis://localhost:6379/0", description="Redis 连接")
    postgres_url: str = Field("", description="PostgreSQL 连接字符串")

    # --- 重试 ---
    retry_max_attempts: int = Field(3, ge=1, le=10, description="API 调用最大重试次数")
    retry_min_wait: int = Field(2, ge=1, description="重试初始等待秒数")

    # --- 缓存 ---
    cache_ttl_hours: int = Field(24, ge=1, description="默认缓存 TTL（小时）")

    # --- Agent ---
    max_tool_calls: int = Field(5, ge=1, description="单个 Agent 最大工具调用次数")
    agent_timeout_seconds: int = Field(30, ge=5, description="子 Agent 超时时间")

    # --- 预算 ---
    budget_max_retries: int = Field(3, ge=1, description="预算循环最大轮次")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 .env 中未定义的字段


# 全局单例
settings = Settings()
