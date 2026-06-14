"""Shared state contracts for the Supervisor workflow."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict


EventCallback = Optional[Callable[[Dict[str, Any]], None]]
AgentStatus = Literal["completed", "degraded", "failed"]


class AgentExecution(TypedDict, total=False):
    status: AgentStatus
    subtask: str
    response: str
    output: str
    tool_artifacts: List[Dict[str, Any]]
    error: str
    degraded: bool
    started_at: str
    finished_at: str


class SupervisorState(TypedDict, total=False):
    task_id: str
    user_request: Dict[str, Any]
    extracted_facts: Dict[str, Any]
    missing_info: List[str]
    selected_agents: List[str]
    subtasks: List[Dict[str, str]]
    agent_results: Dict[str, AgentExecution]
    collector_output: Dict[str, Any]
    itinerary_output: str
    reflection_output: Dict[str, Any]
    final_output: str
    task_status: str
    events: List[Dict[str, Any]]
    memory_context: Dict[str, Any]


DOMAIN_AGENT_NAMES = (
    "flight_agent",
    "train_agent",
    "hotel_agent",
    "attraction_agent",
    "weather_agent",
    "local_expert",
)

POST_PROCESS_AGENT_NAMES = ("budget_optimizer", "itinerary_planner")
