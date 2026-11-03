"""Agent loop: the planner picks tools, the registry runs them, results go back until done.

Planners implement one method, `plan(messages, tools) -> Decision`:
  * AnthropicPlanner uses Claude tool use (needs ANTHROPIC_API_KEY).
  * RulePlanner is a small offline fallback so the project runs without a key.

Messages use a neutral format so planners can be swapped:
  {"role": "user", "text": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "input"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": dict}
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import ToolRegistry

SYSTEM_PROMPT = (
    "You are a concise personal assistant. Use the tools to get real data for weather, "
    "trip planning and tasks. Never invent forecasts or tasks. When you have enough "
    "information, reply to the user in plain language."
)


@dataclass
class Decision:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class Planner(Protocol):
    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision: ...


class AnthropicPlanner:
    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        if client is None:
            import anthropic  # imported lazily so the rule planner works without it

            client = anthropic.Anthropic()
        self.client = client
        self.model = model or os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")

    def _to_api(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        api: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "user":
                api.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.get("text"):
                    blocks.append({"type": "text", "text": m["text"]})
                for c in m.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]})
                api.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                import json

                api.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": json.dumps(m["content"]),
                }]})
        return api

    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools.schemas(),
            messages=self._to_api(messages),
        )
        text, calls = "", []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                calls.append({"id": block.id, "name": block.name, "input": dict(block.input)})
        return Decision(text=text.strip(), tool_calls=calls)


class RulePlanner:
    """Offline planner: handles a few fixed patterns. Good for demos and tests."""

    _call_counter = 0

    def _call(self, name: str, args: dict[str, Any]) -> Decision:
        RulePlanner._call_counter += 1
        return Decision(tool_calls=[{"id": f"rule_{RulePlanner._call_counter}", "name": name, "input": args}])

    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision:
        last_user = next(m["text"] for m in reversed(messages) if m["role"] == "user")
        results = [m for m in messages if m["role"] == "tool"]
        if results:  # a tool already ran for this request: summarise it
            return Decision(text=_summarise(results[-1]))

        text = last_user.strip()
        m = re.search(r"weather (?:in|for) (.+)$", text, re.I)
        if m:
            return self._call("get_weather", {"city": m.group(1).strip(" ?.!")})
        m = re.search(r"add (?:a )?task (?:to |called )?(.+)$", text, re.I)
        if m:
            return self._call("add_task", {"title": m.group(1).strip()})
        if re.search(r"\b(list|show|my) tasks\b|\btodo\b", text, re.I):
            return self._call("list_tasks", {})
        m = re.search(r"(?:done|complete|finish) task (\w+)", text, re.I)
        if m:
            return self._call("complete_task", {"task_id": m.group(1)})
        return Decision(text="I can check weather, add tasks, list tasks or complete tasks. Try 'weather in Paris'.")


def _summarise(tool_msg: dict[str, Any]) -> str:
    content = tool_msg["content"]
    if "error" in content:
        return f"Sorry, that failed: {content['error']}"
    if tool_msg["name"] == "get_weather":
        cur = content["current"]
        lines = [f"Right now in {content['location']}: {cur['temperature_c']}°C, {cur['conditions']}."]
        for d in content["daily"]:
            lines.append(f"  {d['date']}: {d['conditions']}, {d['low_c']}–{d['high_c']}°C, "
                         f"{d['rain_chance_pct']}% chance of rain")
        return "\n".join(lines)
    if tool_msg["name"] == "list_tasks":
        tasks = content["tasks"]
        if not tasks:
            return "You have no open tasks."
        return "\n".join(f"[{t['id']}] {t['title']} (due {t['due'] or 'no date'}, {t['priority']})" for t in tasks)
    if tool_msg["name"] == "add_task":
        return f"Added task [{content['id']}] {content['title']}."
    if tool_msg["name"] == "complete_task":
        return f"Marked [{content['id']}] {content['title']} as done."
    return str(content)


@dataclass
class AgentResult:
    reply: str
    trace: list[str]


class Agent:
    def __init__(self, planner: Planner, tools: ToolRegistry, max_steps: int = 5) -> None:
        self.planner = planner
        self.tools = tools
        self.max_steps = max_steps

    def run(self, user_text: str) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "user", "text": user_text}]
        trace: list[str] = []
        for step in range(1, self.max_steps + 1):
            decision = self.planner.plan(messages, self.tools)
            if not decision.tool_calls:
                return AgentResult(reply=decision.text or "(no reply)", trace=trace)

            messages.append({"role": "assistant", "text": decision.text, "tool_calls": decision.tool_calls})
            for call in decision.tool_calls:
                result = self.tools.call(call["name"], call["input"])
                trace.append(f"step {step}: {call['name']}({call['input']}) -> {'error' if 'error' in result else 'ok'}")
                messages.append({
                    "role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result,
                })
        return AgentResult(reply="Stopped: reached the step limit before finishing.", trace=trace)
