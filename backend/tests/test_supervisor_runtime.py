import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.supervisor.router import find_missing_info, normalize_request, select_agents
from backend.supervisor.runtime import SupervisorTravelPlanner


class FakeAgent:
    def __init__(self, name, *, fail=False):
        self.name = name
        self.fail = fail

    def execute(self, subtask, facts, event_callback=None):
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return {
            "status": "completed",
            "subtask": subtask,
            "response": f"{self.name}: {facts['destination']}",
            "output": f"{self.name}: {facts['destination']}",
            "tool_artifacts": [],
            "error": "",
            "degraded": False,
        }


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


if __name__ == "__main__":
    unittest.main()
