import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.supervisor.router import find_missing_info, normalize_request, select_agents
from backend.supervisor.runtime import SupervisorTravelPlanner
from backend.agents.domain_agents import BaseDomainAgent, parse_budget_estimate
from backend.tools.result import ToolResult
from backend.tools.weather_utils import normalize_forecast_days


class FakeAgent:
    def __init__(self, name, *, fail=False, degraded=False):
        self.name = name
        self.fail = fail
        self.degraded = degraded

    def execute(self, subtask, facts, event_callback=None):
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return {
            "status": "degraded" if self.degraded else "completed",
            "subtask": subtask,
            "response": f"{self.name}: {facts['destination']}",
            "output": f"{self.name}: {facts['destination']}",
            "tool_artifacts": [],
            "error": "provider unavailable" if self.degraded else "",
            "degraded": self.degraded,
        }


class StructuredResultAgent(BaseDomainAgent):
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


class SupervisorRouterTests(unittest.TestCase):
    def test_explicit_capabilities_only_select_requested_agents(self):
        facts = normalize_request(
            {
                "destination": "杭州",
                "travel_dates": "2026-07-01 至 2026-07-03",
                "requested_capabilities": ["酒店", "天气"],
            }
        )
        self.assertEqual(select_agents(facts), ["hotel_agent", "weather_agent"])

    def test_mixed_transport_selects_flight_and_train_when_origin_exists(self):
        facts = normalize_request(
            {
                "departure": "北京",
                "destination": "成都",
                "start_date": "2026-07-01",
                "end_date": "2026-07-04",
                "transportation_preference": "混合交通",
            }
        )
        selected = select_agents(facts)
        self.assertEqual(selected[:2], ["flight_agent", "train_agent"])

    def test_explicit_transport_capability_requires_origin(self):
        facts = normalize_request(
            {
                "destination": "成都",
                "travel_dates": "2026-07-01 至 2026-07-03",
                "requested_capabilities": ["航班"],
            }
        )
        self.assertIn("departure", find_missing_info(facts))


class SupervisorRuntimeTests(unittest.TestCase):
    def test_runtime_keeps_existing_api_contract(self):
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent"),
        }
        planner = SupervisorTravelPlanner(registry, use_langgraph=False)
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
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent", fail=True),
        }
        planner = SupervisorTravelPlanner(registry, use_langgraph=False)
        result = planner.run_travel_planning(
            {
                "destination": "广州",
                "travel_dates": "2026-09-01 至 2026-09-03",
                "requested_capabilities": ["酒店", "天气"],
            }
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["planning_complete"])
        self.assertEqual(result["missing_agents"], ["weather_agent"])
        self.assertIn("hotel_agent", result["travel_plan"]["agent_contributions"])

    def test_runtime_marks_degraded_agent_as_partial_not_missing(self):
        registry = {
            "hotel_agent": FakeAgent("hotel_agent"),
            "weather_agent": FakeAgent("weather_agent", degraded=True),
        }
        planner = SupervisorTravelPlanner(registry, use_langgraph=False)
        result = planner.run_travel_planning(
            {
                "destination": "成都",
                "travel_dates": "2026-09-01 至 2026-09-03",
                "requested_capabilities": ["酒店", "天气"],
            }
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["missing_agents"], [])
        self.assertEqual(result["degraded_agents"], ["weather_agent"])
        self.assertFalse(result["planning_complete"])
        self.assertEqual(result["completion_status"], "partial")
        self.assertIn("weather_agent", result["travel_plan"]["agent_contributions"])


class DomainReliabilityTests(unittest.TestCase):
    def test_structured_tool_result_propagates_degraded_status(self):
        result = StructuredResultAgent().execute(
            "查询候选数据",
            {"destination": "杭州"},
        )

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["error"], "provider_timeout")
        self.assertEqual(result["tool_artifacts"][0]["source"], "stub_provider")

    def test_daily_team_budget_is_converted_to_trip_total(self):
        estimate = parse_budget_estimate(
            "经济型（300-800元/天）",
            duration=3,
            group_size=2,
        )

        self.assertEqual(estimate["basis"], "团队每日预算上限")
        self.assertEqual(estimate["total_budget"], 2400)
        self.assertEqual(estimate["per_person_day"], 400)

    def test_per_person_daily_budget_accounts_for_group_size(self):
        estimate = parse_budget_estimate(
            "人均500元/天",
            duration=3,
            group_size=2,
        )

        self.assertEqual(estimate["basis"], "人均每日预算上限")
        self.assertEqual(estimate["total_budget"], 3000)
        self.assertEqual(estimate["per_person_day"], 500)

    def test_weather_days_use_supported_endpoint_slots(self):
        self.assertEqual(normalize_forecast_days(1), 3)
        self.assertEqual(normalize_forecast_days(4), 7)
        self.assertEqual(normalize_forecast_days(7), 7)


if __name__ == "__main__":
    unittest.main()
