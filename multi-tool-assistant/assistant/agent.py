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

import json
import logging
import os
import re
from datetime import date
from dataclasses import dataclass, field
from typing import Any, Protocol

from .profile import UserProfile
from .tools import ToolRegistry

BASE_PROMPT = (
    "You are a concise personal assistant. Use the tools to get real data for weather, "
    "trip planning, country facts, tasks and the user's profile. Never invent forecasts, "
    "facts or tasks. When you have enough information, reply to the user in plain language."
)


@dataclass
class Decision:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class Planner(Protocol):
    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision: ...


class AnthropicPlanner:
    def __init__(self, profile: UserProfile | None = None, model: str | None = None, client: Any | None = None) -> None:
        if client is None:
            import anthropic  # imported lazily so the rule planner works without it

            client = anthropic.Anthropic()
        self.client = client
        self.profile = profile or UserProfile()
        self.model = model or os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")

    def _system(self) -> str:
        today = date.today().isoformat()
        return f"{BASE_PROMPT} Today is {today}. {self.profile.to_prompt()}"

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
                api.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": json.dumps(m["content"]),
                }]})
        return api

    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision:
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self._system(),
                tools=tools.schemas(),
                messages=self._to_api(messages),
            )
        except Exception as exc:  # network, auth, rate-limit: report it instead of crashing the session
            logging.getLogger(__name__).warning("Claude API call failed: %s", exc)
            return Decision(text=f"Sorry, I couldn't reach Claude just now ({type(exc).__name__}). Please try again.")
        text, calls = "", []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                calls.append({"id": block.id, "name": block.name, "input": dict(block.input)})
        return Decision(text=text.strip(), tool_calls=calls)


class RulePlanner:
    """Offline planner for fixed patterns. Good for demos and tests."""

    def __init__(self, profile: UserProfile | None = None) -> None:
        self.profile = profile or UserProfile()
        self._counter = 0

    def _call(self, name: str, args: dict[str, Any]) -> Decision:
        self._counter += 1
        return Decision(tool_calls=[{"id": f"rule_{self._counter}", "name": name, "input": args}])

    def plan(self, messages: list[dict[str, Any]], tools: ToolRegistry) -> Decision:
        last_user = next(m["text"] for m in reversed(messages) if m["role"] == "user")
        results = [m for m in messages if m["role"] == "tool"]
        if results:  # a tool already ran for this request: summarise it
            return Decision(text=summarise(results[-1], self.profile))

        text = last_user.strip().rstrip("?!. ")
        m = re.search(r"^trip to (.+?)(?: for (\d+) days?)?$", text, re.I)
        if m:
            args: dict[str, Any] = {"destination": m.group(1).strip()}
            if m.group(2):
                args["days"] = int(m.group(2))
            return self._call("plan_trip", args)
        m = re.search(r"^(?:facts|info|country info) (?:about |on |for )?(?:the country )?(.+)$", text, re.I)
        if m:
            return self._call("country_info", {"country": m.group(1).strip()})
        m = re.search(r"weather (?:in|for) (.+)$", text, re.I)
        if m:
            return self._call("get_weather", {"city": m.group(1).strip()})
        if re.search(r"^(?:what'?s the )?weather$", text, re.I):
            return self._call("get_weather", {})  # uses the saved home city
        m = re.search(r"(?:use|set units to|units) (fahrenheit|celsius)", text, re.I)
        if m:
            return self._call("update_profile", {"units": m.group(1).lower()})
        m = re.search(r"my (?:home city|home|city) is (.+)$", text, re.I)
        if m:
            return self._call("update_profile", {"home_city": m.group(1).strip()})
        m = re.search(r"my name is (\w+)", text, re.I)
        if m:
            return self._call("update_profile", {"name": m.group(1)})
        if re.search(r"\b(my profile|what do you know about me)\b", text, re.I):
            return self._call("get_profile", {})
        m = re.search(r"add (?:a )?task (?:to |called )?(.+)$", text, re.I)
        if m:
            return self._call("add_task", {"title": m.group(1).strip()})
        if re.search(r"\b(list|show|my) tasks\b|\btodo\b", text, re.I):
            return self._call("list_tasks", {})
        m = re.search(r"(?:done|complete|finish) task (\w+)", text, re.I)
        if m:
            return self._call("complete_task", {"task_id": m.group(1)})
        return Decision(text=(
            "I can plan trips, check weather, look up country facts, manage tasks and update your profile. "
            "Try 'trip to Tokyo for 4 days', 'weather in Kyoto' or 'facts about Japan'."
        ))


def summarise(tool_msg: dict[str, Any], profile: UserProfile) -> str:
    content = tool_msg["content"]
    name = tool_msg["name"]
    if "error" in content:
        return f"Sorry, that failed: {content['error']}"
    if name == "get_weather":
        cur = content["current"]
        lines = [f"Right now in {content['location']}: {profile.format_temp(cur['temperature_c'])}, {cur['conditions']}."]
        if content.get("source"):
            lines.insert(0, f"[{content['source']}]")
        for d in content["daily"]:
            lines.append(f"  {d['date']}: {d['conditions']}, {profile.format_temp(d['low_c'])} to "
                         f"{profile.format_temp(d['high_c'])}, {d['rain_chance_pct']}% chance of rain")
        return "\n".join(lines)
    if name == "plan_trip":
        f = content["forecast"]
        lines = [f"Trip plan for {content['destination']}:"]
        if f.get("source"):
            lines.insert(0, f"[{f['source']}]")
        for d in f["daily"]:
            lines.append(f"  {d['date']}: {d['conditions']}, {profile.format_temp(d['low_c'])} to "
                         f"{profile.format_temp(d['high_c'])}, {d['rain_chance_pct']}% rain")
        if content["country"]:
            c = content["country"]
            lines.append(f"Country: {c['name']}; capital {c['capital']}; currency {', '.join(c['currencies']) or 'n/a'}; "
                         f"language {', '.join(c['languages'][:3]) or 'n/a'}.")
        elif content.get("country_error"):
            lines.append(f"(Country facts unavailable: {content['country_error']})")
        lines.append("Tasks added:")
        lines += [f"  [{t['id']}] {t['title']} (due {t['due'] or 'no date'})" for t in content["tasks_added"]]
        return "\n".join(lines)
    if name == "country_info":
        c = content
        prefix = f"[{c['source']}] " if c.get("source") else ""
        return (f"{prefix}{c['name']}: capital {c['capital']}, region {c['region']}, "
                f"currency {', '.join(c['currencies']) or 'n/a'}, languages {', '.join(c['languages']) or 'n/a'}.")
    if name == "list_tasks":
        tasks = content["tasks"]
        if not tasks:
            return "You have no open tasks."
        return "\n".join(f"[{t['id']}] {t['title']} (due {t['due'] or 'no date'}, {t['priority']})" for t in tasks)
    if name == "add_task":
        return f"Added task [{content['id']}] {content['title']}."
    if name == "complete_task":
        return f"Marked [{content['id']}] {content['title']} as done."
    if name in {"get_profile", "update_profile"}:
        return (f"Profile: name {content['name']}, home city {content['home_city'] or 'not set'}, "
                f"units {content['units']}.")
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
                status = "error" if "error" in result else "ok"
                trace.append(f"step {step}: {call['name']}({call['input']}) -> {status}")
                messages.append({
                    "role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result,
                })
        return AgentResult(reply="Stopped: reached the step limit before finishing.", trace=trace)
