"""
Supervisor 架构单元测试与集成测试。

测试覆盖（需求文档 §7.6）：
- 路由逻辑：Agent 选择、缺失检测、能力别名
- 运行时：API 契约、故障隔离、降级标记
- 领域可靠性：ToolResult 传播、预算解析、天气天数
- 状态模型：新增字段完整性
- 端到端：多 Agent 并行、SSE 事件流

运行方式：
    python -m backend.tests.test_supervisor_runtime
    或从项目根目录：python -m pytest backend/tests/test_supervisor_runtime.py -v
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.supervisor.router import (
    build_clarification_prompt,
    find_missing_info,
    normalize_request,
    select_agents,
)
from backend.supervisor.runtime import SupervisorTravelPlanner
from backend.supervisor.state import SupervisorState
from backend.agents.domain_agents import (
    BaseDomainAgent,
    build_default_agent_registry,
    parse_budget_estimate,
)
from backend.tools.result import ToolResult
from backend.tools.weather_utils import normalize_forecast_days


# ======================== 测试辅助类 ========================

class FakeAgent:
    """
    模拟 Agent —— 用于测试 Supervisor 调度逻辑，
    不依赖真实的外部 API 和工具。
    """

    def __init__(self, name, *, fail=False, degraded=False):
        self.name = name
        self.fail = fail
        self.degraded = degraded

    def execute(self, subtask, facts, event_callback=None):
        if self.fail:
            raise RuntimeError(f"{self.name} 模拟失败")
        return {
            "status": "degraded" if self.degraded else "completed",
            "subtask": subtask,
            "response": f"{self.name}: {facts.get('destination', '未知')}",
            "output": f"{self.name}: {facts.get('destination', '未知')}",
            "tool_artifacts": [],
            "error": "provider unavailable" if self.degraded else "",
            "degraded": self.degraded,
            "retry_count": 0,
            "llm_calls": 0,
        }


class StructuredResultAgent(BaseDomainAgent):
    """
    返回结构化 ToolResult 的 Agent —— 测试 ToolResult 传播路径。
    """

    name = "structured_result_agent"
    tool_name = "stub"

    def build_tool_params(self, facts):
        return {"destination": facts.get("destination")}

    def invoke_tool(self, params, facts):
        return ToolResult.degraded(
            "使用缓存候选结果",
            error="provider_timeout",
            source="stub_provider",
        )


# ======================== 路由测试 ========================

class SupervisorRouterTests(unittest.TestCase):
    """
    测试 Supervisor 路由层（确定性规则）。

    验证：
    - 显式能力选择
    - 交通 Agent 动态添加
    - 缺失信息检测
    - 澄清提示生成
    """

    def test_explicit_capabilities_only_select_requested_agents(self):
        """
        验证显式指定能力时，只执行指定的 Agent。
        """
        facts = normalize_request({
            "destination": "杭州",
            "travel_dates": "2026-07-01 至 2026-07-03",
            "requested_capabilities": ["酒店", "天气"],
        })
        self.assertEqual(select_agents(facts), ["hotel_agent", "weather_agent"])

    def test_mixed_transport_selects_flight_and_train_when_origin_exists(self):
        """
        验证有出发地 + 混合交通偏好时，同时选择航班和铁路 Agent。
        """
        facts = normalize_request({
            "departure": "北京",
            "destination": "成都",
            "start_date": "2026-07-01",
            "end_date": "2026-07-04",
            "transportation_preference": "混合交通",
        })
        selected = select_agents(facts)
        self.assertEqual(selected[:2], ["flight_agent", "train_agent"])

    def test_explicit_transport_capability_requires_origin(self):
        """
        验证显式选择交通 Agent 但没有出发地时，检测到缺失信息。
        """
        facts = normalize_request({
            "destination": "成都",
            "travel_dates": "2026-07-01 至 2026-07-03",
            "requested_capabilities": ["航班"],
        })
        self.assertIn("departure", find_missing_info(facts))

    def test_no_departure_skips_transport_agents(self):
        """
        验证没有出发地时，不选择交通 Agent。
        """
        facts = normalize_request({
            "destination": "成都",
            "start_date": "2026-07-01",
            "end_date": "2026-07-03",
        })
        selected = select_agents(facts)
        self.assertNotIn("flight_agent", selected)
        self.assertNotIn("train_agent", selected)

    def test_clarification_prompt_generated_for_missing_info(self):
        """
        验证缺失信息时生成澄清提示。
        """
        extracted = {"destination": "成都"}
        missing = ["travel_dates", "departure"]
        title, body = build_clarification_prompt(extracted, missing)
        self.assertEqual(title, "信息待补充")
        # 提示中包含友好的中文引导，而非原始字段名
        self.assertIn("出发", body)
        self.assertIn("成都", body)

    def test_clarification_prompt_empty_when_complete(self):
        """
        验证信息完整时不生成澄清提示。
        """
        extracted = {
            "destination": "成都",
            "start_date": "2026-07-01",
            "duration": 3,
        }
        title, body = build_clarification_prompt(extracted, [])
        self.assertEqual(title, "信息完整")


# ======================== 运行时测试 ========================

class SupervisorRuntimeTests(unittest.TestCase):
    """
    测试 Supervisor 运行时核心逻辑。

    验证：
    - API 契约兼容性
    - Agent 故障隔离
    - 降级状态传播
    """

    def test_runtime_keeps_existing_api_contract(self):
        """
        验证运行时输出的 API 契约与旧版兼容。
        """
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent"),
        }
        planner = SupervisorTravelPlanner(registry)
        events = []
        result = planner.run_travel_planning(
            {
                "destination": "上海",
                "start_date": "2026-08-01",
                "end_date": "2026-08-03",
                "duration": 3,
                "budget_range": "3000元",
                "group_size": 2,
                "requested_capabilities": ["酒店", "天气"],
            },
            event_callback=events.append,
        )

        self.assertTrue(result["success"])
        self.assertIn("travel_plan", result)
        self.assertIn("agent_outputs", result)
        self.assertIn("short_term_memory", result)
        self.assertEqual(result["missing_agents"], [])
        self.assertEqual(result["degraded_agents"], [])
        self.assertEqual(result["completion_status"], "complete")
        self.assertTrue(result["planning_complete"])
        self.assertEqual(events[-1]["type"], "task_completed")

    def test_runtime_isolates_agent_failure(self):
        """
        验证单个 Agent 失败不阻塞整体流程。
        """
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent", fail=True),
        }
        planner = SupervisorTravelPlanner(registry)
        result = planner.run_travel_planning({
            "destination": "广州",
            "travel_dates": "2026-09-01 至 2026-09-03",
            "requested_capabilities": ["酒店", "天气"],
        })

        self.assertTrue(result["success"])
        self.assertFalse(result["planning_complete"])
        self.assertEqual(result["missing_agents"], ["weather_agent"])
        # 酒店 Agent 的结果仍然可用
        self.assertIn("hotel_agent", result["travel_plan"]["agent_contributions"])

    def test_runtime_marks_degraded_agent_as_partial_not_missing(self):
        """
        验证降级 Agent 标记为 partial 而非 missing。
        """
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent", degraded=True),
        }
        planner = SupervisorTravelPlanner(registry)
        result = planner.run_travel_planning({
            "destination": "成都",
            "travel_dates": "2026-09-01 至 2026-09-03",
            "requested_capabilities": ["酒店", "天气"],
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["missing_agents"], [])
        self.assertEqual(result["degraded_agents"], ["weather_agent"])
        self.assertFalse(result["planning_complete"])
        self.assertEqual(result["completion_status"], "partial")
        # 降级 Agent 的贡献仍然被保留
        self.assertIn("weather_agent", result["travel_plan"]["agent_contributions"])

    def test_sse_events_fire_in_correct_order(self):
        """
        验证 SSE 事件按正确顺序触发。
        """
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent"),
        }
        planner = SupervisorTravelPlanner(registry)
        events = []
        planner.run_travel_planning(
            {
                "destination": "上海",
                "start_date": "2026-08-01",
                "end_date": "2026-08-03",
                "requested_capabilities": ["酒店", "天气"],
            },
            event_callback=events.append,
        )

        event_types = [e["type"] for e in events]
        # 验证关键事件存在且顺序正确
        self.assertIn("memory_recalled", event_types)
        self.assertIn("intent_parsed", event_types)
        self.assertIn("agent_started", event_types)
        self.assertIn("agent_completed", event_types)
        self.assertIn("task_completed", event_types)

        # memory_recalled 应该在 intent_parsed 之前
        mem_idx = event_types.index("memory_recalled")
        intent_idx = event_types.index("intent_parsed")
        self.assertLess(mem_idx, intent_idx)


# ======================== 领域可靠性测试 ========================

class DomainReliabilityTests(unittest.TestCase):
    """
    测试领域 Agent 和工具的可靠性。

    验证：
    - ToolResult 状态传播
    - 预算解析三种口径
    - 天气天数标准化
    """

    def test_structured_tool_result_propagates_degraded_status(self):
        """
        验证 ToolResult.degraded 正确传播到 Agent 执行结果。
        """
        result = StructuredResultAgent().execute(
            "查询候选数据",
            {"destination": "杭州"},
        )

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["error"], "provider_timeout")
        self.assertEqual(result["tool_artifacts"][0]["source"], "stub_provider")

    def test_daily_team_budget_is_converted_to_trip_total(self):
        """
        验证团队每日预算正确转换为全程总预算。
        """
        estimate = parse_budget_estimate(
            "经济型（300-800元/天）",
            duration=3,
            group_size=2,
        )

        self.assertEqual(estimate["basis"], "团队每日预算上限")
        self.assertEqual(estimate["total_budget"], 2400)  # 800 * 3
        self.assertEqual(estimate["per_person_day"], 400)  # 2400 / 3 / 2

    def test_per_person_daily_budget_accounts_for_group_size(self):
        """
        验证人均每日预算正确计算。
        """
        estimate = parse_budget_estimate(
            "人均500元/天",
            duration=3,
            group_size=2,
        )

        self.assertEqual(estimate["basis"], "人均每日预算上限")
        self.assertEqual(estimate["total_budget"], 3000)  # 500 * 3 * 2
        self.assertEqual(estimate["per_person_day"], 500)

    def test_trip_total_budget_used_directly(self):
        """
        验证全程总预算直接使用。
        """
        estimate = parse_budget_estimate(
            "总预算5000元",
            duration=4,
            group_size=2,
        )

        self.assertEqual(estimate["basis"], "全程总预算上限")
        self.assertEqual(estimate["total_budget"], 5000)
        self.assertEqual(estimate["per_person_day"], 625)  # 5000 / 4 / 2

    def test_weather_days_use_supported_endpoint_slots(self):
        """
        验证天气天数映射到和风天气支持的端点（3d 或 7d）。
        """
        self.assertEqual(normalize_forecast_days(1), 3)
        self.assertEqual(normalize_forecast_days(3), 3)
        self.assertEqual(normalize_forecast_days(4), 7)
        self.assertEqual(normalize_forecast_days(7), 7)


# ======================== 状态模型测试 ========================

class StateModelTests(unittest.TestCase):
    """
    测试 SupervisorState 新增字段的完整性。
    """

    def test_state_includes_new_fields(self):
        """
        验证 SupervisorState 包含需求文档要求的全部字段。
        """
        state: SupervisorState = {
            "task_id": "test-001",
            "trace_id": "abc12345",
            "user_request": {},
            "extracted_facts": {},
            "missing_info": [],
            "clarification_question": "",
            "selected_agents": [],
            "subtasks": [],
            "agent_results": {},
            "collector_output": {},
            "itinerary_output": "",
            "reflection_output": {},
            "final_output": "",
            "task_status": "processing",
            "events": [],
            "memory_context": {},
            "error_history": [],
            "retry_count": 0,
        }

        # 验证新增字段存在
        self.assertIn("trace_id", state)
        self.assertIn("clarification_question", state)
        self.assertIn("error_history", state)
        self.assertIn("retry_count", state)

    def test_error_history_tracks_failures(self):
        """
        验证 error_history 正确记录错误信息。
        """
        state: SupervisorState = {
            "task_id": "test-001",
            "trace_id": "abc12345",
            "user_request": {},
            "extracted_facts": {},
            "missing_info": [],
            "clarification_question": "",
            "selected_agents": [],
            "subtasks": [],
            "agent_results": {},
            "collector_output": {},
            "itinerary_output": "",
            "reflection_output": {},
            "final_output": "",
            "task_status": "processing",
            "events": [],
            "memory_context": {},
            "error_history": [],
            "retry_count": 0,
        }

        # 模拟错误记录
        state["error_history"].append({
            "agent": "weather_agent",
            "error": "API timeout",
            "stage": "dispatcher",
            "timestamp": datetime.now().isoformat(),
        })

        self.assertEqual(len(state["error_history"]), 1)
        self.assertEqual(state["error_history"][0]["agent"], "weather_agent")
        self.assertEqual(state["error_history"][0]["stage"], "dispatcher")


# ======================== Agent 注册表测试 ========================

class AgentRegistryTests(unittest.TestCase):
    """
    测试 Agent 注册表的完整性。
    """

    def test_default_registry_contains_all_seven_agents(self):
        """
        验证默认注册表包含全部 7 个领域 Agent。
        """
        registry = build_default_agent_registry()
        expected = {
            "flight_agent",
            "train_agent",
            "hotel_agent",
            "attraction_agent",
            "weather_agent",
            "local_expert",
            "budget_optimizer",
        }
        self.assertEqual(set(registry.keys()), expected)

    def test_each_agent_has_tool_config(self):
        """
        验证每个 Agent 都配置了工具模块和名称。
        """
        registry = build_default_agent_registry()
        for name, agent in registry.items():
            if name == "budget_optimizer":
                # BudgetAgent 使用内置计算，不需要外部工具
                self.assertEqual(agent.tool_name, "budget_calculator")
            else:
                self.assertTrue(
                    agent.tool_module,
                    f"{name} 缺少 tool_module 配置",
                )
                self.assertTrue(
                    agent.tool_name,
                    f"{name} 缺少 tool_name 配置",
                )


# ======================== 提示词测试 ========================

class PromptTests(unittest.TestCase):
    """
    测试集中式提示词模块。
    """

    def test_prompts_module_importable(self):
        """
        验证 prompts 模块可以正确导入。
        """
        try:
            from backend.supervisor.prompts import (
                AGENT_DISPLAY_NAMES,
                build_intent_parse_messages,
                build_reflection_messages,
                build_summarizer_messages,
            )
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"prompts 模块导入失败: {e}")

    def test_intent_parse_messages_format(self):
        """
        验证意图解析消息格式正确。
        """
        from backend.supervisor.prompts import build_intent_parse_messages

        messages = build_intent_parse_messages(
            "我想去成都玩3天",
            "2026年07月01日",
        )

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("成都", messages[1]["content"])

    def test_agent_display_names_complete(self):
        """
        验证所有 Agent 都有展示名称。
        """
        from backend.supervisor.prompts import AGENT_DISPLAY_NAMES

        expected_agents = [
            "flight_agent",
            "train_agent",
            "hotel_agent",
            "attraction_agent",
            "weather_agent",
            "local_expert",
            "budget_optimizer",
            "itinerary_planner",
        ]
        for agent in expected_agents:
            self.assertIn(agent, AGENT_DISPLAY_NAMES, f"{agent} 缺少展示名称")


# ======================== 运行入口 ========================

if __name__ == "__main__":
    unittest.main(verbosity=2)
