"""
全局配置管理 —— Pydantic Settings，统一加载运行配置。

设计原则（需求文档 §17.1）：
- 所有配置集中到此处，替代各处 os.getenv 的分散写法
- 启动期自动校验，减少运行期隐性错误
- .env 不入库，敏感信息通过环境变量注入

使用方式：
    from core.config import settings
    api_key = settings.openai_api_key

配置来源优先级：环境变量 > .env 文件 > 默认值
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """
    全局配置单例。

    各能力模块在实际使用时校验所需密钥，不在此处强制要求。
    这意味着即使某个 API Key 缺失，其他能力仍可正常工作。
    """

    # ======================== LLM 配置 ========================
    openai_api_key: str = Field(
        "",
        description="OpenAI 兼容 API Key（支持 DeepSeek、Qwen 等兼容服务）",
    )
    openai_base_url: str = Field(
        "https://api.openai.com/v1",
        description="API 基础地址，可切换为 DeepSeek 等兼容服务",
    )
    openai_model: str = Field(
        "gpt-4o-mini",
        description="默认模型名称",
    )
    llm_temperature: float = Field(
        0,
        ge=0.0,
        le=2.0,
        description="LLM 采样温度（0=确定性，1=创造性）",
    )

    # ======================== 国内 API 密钥（可选） ========================
    amap_api_key: str = Field(
        "",
        description="高德地图 Web API Key（酒店/景点 POI 搜索）",
    )
    juhe_flight_key: str = Field(
        "",
        description="聚合数据 API Key - 航班订票查询",
    )
    juhe_train_key: str = Field(
        "",
        description="聚合数据 API Key - 火车订票查询",
    )
    qweather_api_key: str = Field(
        "",
        description="和风天气 API Key（天气预报）",
    )

    # ======================== 可观测性 ========================
    langsmith_api_key: str = Field(
        "",
        description="LangSmith API Key（LLM 调用追踪）",
    )
    langsmith_project: str = Field(
        "travel-agent",
        description="LangSmith 项目名称",
    )

    # ======================== 持久化配置 ========================
    redis_url: str = Field(
        "redis://localhost:6379/0",
        description="Redis 连接 URL（任务状态、事件流、短期记忆）",
    )
    postgres_url: str = Field(
        "",
        description="PostgreSQL 连接字符串（结果归档）",
    )

    # ======================== 重试配置 ========================
    retry_max_attempts: int = Field(
        3,
        ge=1,
        le=10,
        description="API 调用最大重试次数",
    )
    retry_min_wait: int = Field(
        2,
        ge=1,
        description="重试初始等待秒数（指数退避）",
    )

    # ======================== 缓存配置 ========================
    cache_ttl_hours: int = Field(
        24,
        ge=1,
        description="默认缓存 TTL（小时）",
    )

    # ======================== Agent 配置 ========================
    max_tool_calls: int = Field(
        5,
        ge=1,
        description="单个 Agent 最大工具调用次数",
    )
    agent_timeout_seconds: int = Field(
        30,
        ge=5,
        description="子 Agent 超时时间（秒）",
    )

    # ======================== Chroma 本地知识库 ========================
    chroma_persist_dir: str = Field(
        "./chroma_data",
        description="本地 ChromaDB 数据存储目录",
    )
    chroma_collection: str = Field(
        "travel_local_expert_knowledge",
        description="Chroma Collection 名称",
    )
    chroma_top_k: int = Field(
        4,
        ge=1,
        le=10,
        description="RAG 检索返回数量",
    )

    # ======================== 预算配置 ========================
    budget_max_retries: int = Field(
        3,
        ge=1,
        description="预算循环最大轮次",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 .env 中未定义的字段，避免启动报错


# ======================== 全局单例 ========================
# 导入此实例即可使用所有配置
settings = Settings()
