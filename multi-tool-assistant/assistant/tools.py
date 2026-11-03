"""Tool registry: each tool has a name, description, JSON-schema parameters and a Python callable.

The registry is the single place the agent uses to list tools (for the LLM) and to
execute them (for the agent loop). Errors never escape as exceptions; they are
returned to the model as structured results so it can recover or explain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    func: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        """Tool definitions in the shape LLM APIs expect (name, description, input_schema)."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in self._tools.values()
        ]

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Run a tool. Always returns a dict; failures come back as {"error": ...}."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool '{name}'", "available": self.names()}

        arguments = arguments or {}
        missing = [k for k in tool.parameters.get("required", []) if k not in arguments]
        if missing:
            return {"error": f"missing required argument(s): {', '.join(missing)}"}

        try:
            result = tool.func(**arguments)
        except TypeError as exc:  # wrong/unexpected argument names from the model
            return {"error": f"bad arguments for '{name}': {exc}"}
        except Exception as exc:  # external API failures etc.
            return {"error": f"{type(exc).__name__}: {exc}"}

        # Make sure the result is JSON-serialisable before it goes back to the model.
        return json.loads(json.dumps(result, default=str))
