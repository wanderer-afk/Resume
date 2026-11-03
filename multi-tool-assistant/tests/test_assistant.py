"""Tests run offline: HTTP is faked and the agent uses a scripted planner."""

from __future__ import annotations

import pytest

from assistant import Agent, RulePlanner, TaskStore, WeatherService, build_registry
from assistant.agent import Decision
from assistant.services import ServiceError
from assistant.tools import Tool, ToolRegistry


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns geocode / forecast payloads based on the URL."""

    def __init__(self, geocode_results):
        self.geocode_results = geocode_results

    def get(self, url, params=None, timeout=None):
        if "geocoding" in url:
            return FakeResponse({"results": self.geocode_results})
        return FakeResponse({
            "current": {"temperature_2m": 18.2, "weather_code": 2, "wind_speed_10m": 11.0},
            "daily": {
                "time": ["2026-11-04", "2026-11-05"],
                "weather_code": [61, 0],
                "temperature_2m_max": [16.0, 19.5],
                "temperature_2m_min": [9.1, 8.0],
                "precipitation_probability_max": [80, 5],
            },
        })


PARIS = [{"name": "Paris", "country": "France", "latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}]


@pytest.fixture
def tasks(tmp_path):
    return TaskStore(tmp_path / "tasks.json")


@pytest.fixture
def tools(tasks):
    return build_registry(WeatherService(FakeSession(PARIS)), tasks)


def test_weather_service_formats_forecast():
    out = WeatherService(FakeSession(PARIS)).forecast("Paris", days=2)
    assert out["location"] == "Paris, France"
    assert out["current"]["conditions"] == "partly cloudy"
    assert out["daily"][0]["conditions"] == "light rain"
    assert out["daily"][0]["rain_chance_pct"] == 80


def test_weather_unknown_city_raises():
    with pytest.raises(ServiceError):
        WeatherService(FakeSession([])).geocode("Nowhereville")


def test_task_store_add_list_complete(tasks):
    t = tasks.add("Pack passport", due="2026-11-04", priority="high")
    assert [x["title"] for x in tasks.list()] == ["Pack passport"]
    tasks.complete(t["id"])
    assert tasks.list() == []
    assert len(tasks.list(include_done=True)) == 1


def test_task_store_rejects_bad_date(tasks):
    with pytest.raises(ValueError):
        tasks.add("Bad", due="next tuesday")


def test_registry_reports_errors_instead_of_raising(tools):
    assert "unknown tool" in tools.call("nope", {})["error"]
    assert "missing required" in tools.call("get_weather", {})["error"]
    assert "bad arguments" in tools.call("get_weather", {"city": "Paris", "bogus": 1})["error"]


def test_registry_rejects_duplicate_names():
    reg = ToolRegistry()
    reg.register(Tool("x", "d", {"type": "object", "properties": {}}, lambda: {}))
    with pytest.raises(ValueError):
        reg.register(Tool("x", "d", {"type": "object", "properties": {}}, lambda: {}))


def test_rule_planner_weather_then_summary(tools):
    result = Agent(RulePlanner(), tools).run("weather in Paris")
    assert "Paris, France" in result.reply
    assert result.trace and result.trace[0].startswith("step 1: get_weather")


def test_rule_planner_task_flow(tools):
    agent = Agent(RulePlanner(), tools)
    agent.run("add task buy umbrella")
    reply = agent.run("list tasks").reply
    assert "buy umbrella" in reply


class ScriptedPlanner:
    """Returns a fixed sequence of decisions, to test the loop itself."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.seen = []

    def plan(self, messages, tools):
        self.seen.append(len(messages))
        return self.decisions.pop(0)


def test_loop_feeds_tool_results_back_then_finishes(tools):
    planner = ScriptedPlanner([
        Decision(tool_calls=[{"id": "a", "name": "list_tasks", "input": {}}]),
        Decision(text="All done."),
    ])
    result = Agent(planner, tools).run("anything")
    assert result.reply == "All done."
    assert planner.seen == [1, 3]  # user msg, then user + assistant + tool result


def test_loop_stops_at_step_limit(tools):
    looping = Decision(tool_calls=[{"id": "a", "name": "list_tasks", "input": {}}])
    result = Agent(ScriptedPlanner([looping] * 10), tools, max_steps=2).run("loop")
    assert "step limit" in result.reply
    assert len(result.trace) == 2
