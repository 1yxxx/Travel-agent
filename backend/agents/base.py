# -*- coding: utf-8 -*-
"""
Agent 基础模块 —— 共享状态定义与通用工具函数。

从 langgraph_agents.py 拆分出的可复用基础组件。
"""
from typing import Dict, Any, List, TypedDict, Annotated, Callable, Optional
import logging
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
import json
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.langgraph_config import langgraph_config as config


# ============================== 日志 ==============================
def setup_agents_logger():
    logger = logging.getLogger("langgraph_agents")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_dir = Path(__file__).resolve().parents[1] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "backend.log", encoding="utf-8")
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger


agents_logger = setup_agents_logger()

# Re-export config for other modules
config = config


# ============================== 状态 ==============================
class TravelPlanState(TypedDict):
    """所有 Agent 共享的状态结构。"""
    messages: Annotated[List[HumanMessage | AIMessage | SystemMessage], add_messages]
    destination: str
    duration: int
    budget_range: str
    interests: List[str]
    group_size: int
    travel_dates: str
    current_agent: str
    agent_outputs: Dict[str, Any]
    final_plan: Dict[str, Any]
    iteration_count: int


# ============================== 通用工具 ==============================
def analysis_agents() -> List[str]:
    """返回分析型 Agent 名称列表。"""
    return ["travel_advisor", "weather_analyst", "budget_optimizer", "local_expert"]


def required_agents() -> List[str]:
    """返回流程必需的 Agent 名称列表。"""
    return ["travel_advisor", "weather_analyst", "budget_optimizer",
            "local_expert", "itinerary_planner"]


def derive_agent_status(response_content: Any) -> str:
    """从 LLM 响应中推断 Agent 状态。"""
    if response_content is None:
        return "no_output"
    content = str(response_content).strip().lower()
    if not content or content in ("none", "null", "[]", "{}", "无"):
        return "empty"
    if len(content) < 20:
        return "insufficient"
    return "produced"


def coordinator_decision_from_text(raw_text: str) -> str:
    """从 Coordinator 输出中提取路由决策。"""
    text = raw_text.strip().lower()
    if "itinerary_planner" in text:
        return "itinerary_planner"
    if any(kw in text for kw in ("summariz", "final", "compile", "completed")):
        return "end"
    return "continue_analysis"