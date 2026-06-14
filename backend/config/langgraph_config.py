"""
LangGraph 配置 —— LLM 参数 + LangSmith 可观测性。
"""
import os
from typing import Dict, Any


class LangGraphConfig:
    # ---------- LLM ----------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

    # ---------- LangSmith (可观测性) ----------
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "travel-agent")
    LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    @classmethod
    def setup_observability(cls):
        """启用 LangSmith 全链路追踪（如已配置 API Key）。"""
        if cls.LANGSMITH_API_KEY:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = cls.LANGSMITH_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = cls.LANGSMITH_PROJECT
            os.environ["LANGCHAIN_ENDPOINT"] = cls.LANGSMITH_ENDPOINT
            return True
        return False

    @classmethod
    def get_llm_config(cls) -> Dict[str, Any]:
        config = {
            "model": cls.OPENAI_MODEL,
            "temperature": cls.TEMPERATURE,
        }
        if cls.OPENAI_BASE_URL:
            config["base_url"] = cls.OPENAI_BASE_URL
        if cls.OPENAI_API_KEY:
            config["api_key"] = cls.OPENAI_API_KEY
        return config


langgraph_config = LangGraphConfig()

# 模块加载时自动启用可观测性
_obs_enabled = LangGraphConfig.setup_observability()
if _obs_enabled:
    import logging
    logging.getLogger("langgraph_agents").info(
        f"LangSmith 可观测性已启用 | project={LangGraphConfig.LANGSMITH_PROJECT}"
    )