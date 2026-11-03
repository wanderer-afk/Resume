"""Tests for the Claude planner using a fake client, so no API key or network is needed."""

from __future__ import annotations

from types import SimpleNamespace

from assistant import AnthropicPlanner, UserProfile, build_registry, TaskStore, WeatherService, DestinationService
from assistant.agent import Agent


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="end_turn")


def make_tools(tmp_path):
    return build_registry(
        WeatherService(), DestinationService(), TaskStore(tmp_path / "t.json"), UserProfile(), str(tmp_path / "p.json"),
    )


def test_planner_passes_tools_and_profile_in_system_prompt(tmp_path):
    client = FakeClient([response(text_block("hi"))])
    profile = UserProfile(name="Ana", units="fahrenheit", home_city="Lisbon")
    planner = AnthropicPlanner(profile, client=client, model="test-model")
    Agent(planner, make_tools(tmp_path)).run("hello")
    call = client.messages.calls[0]
    assert call["model"] == "test-model"
    assert {t["name"] for t in call["tools"]} >= {"get_weather", "plan_trip", "add_task"}
    assert "Ana" in call["system"] and "fahrenheit" in call["system"] and "Lisbon" in call["system"]
    assert "Today is" in call["system"]


def test_planner_returns_tool_use_decision(tmp_path):
    client = FakeClient([response(tool_block("tu_1", "list_tasks", {}))])
    decision = AnthropicPlanner(client=client).plan(
        [{"role": "user", "text": "what's on my list?"}], make_tools(tmp_path),
    )
    assert decision.tool_calls == [{"id": "tu_1", "name": "list_tasks", "input": {}}]


def test_full_loop_sends_tool_result_back_as_tool_result_block(tmp_path):
    client = FakeClient([
        response(tool_block("tu_1", "add_task", {"title": "Buy umbrella"})),
        response(text_block("Added it.")),
    ])
    reply = Agent(AnthropicPlanner(client=client), make_tools(tmp_path)).run("add task buy umbrella").reply
    assert reply == "Added it."
    second_call_messages = client.messages.calls[1]["messages"]
    assert second_call_messages[-2]["role"] == "assistant"
    assert second_call_messages[-2]["content"][0]["type"] == "tool_use"
    result_block = second_call_messages[-1]["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["tool_use_id"] == "tu_1"
    assert "Buy umbrella" in result_block["content"]


def test_api_failure_becomes_a_reply_not_a_crash(tmp_path):
    class Boom:
        def create(self, **kwargs):
            raise ConnectionError("network down")

    client = SimpleNamespace(messages=Boom())
    reply = Agent(AnthropicPlanner(client=client), make_tools(tmp_path)).run("hi").reply
    assert "couldn't reach Claude" in reply
