"""Multi-tool AI assistant: weather and task tools driven by an agent loop."""

from .agent import Agent, AgentResult, AnthropicPlanner, RulePlanner
from .services import TaskStore, WeatherService
from .tools import Tool, ToolRegistry


def build_registry(weather: WeatherService, tasks: TaskStore) -> ToolRegistry:
    """Register every tool the agent can use. Add new tools here."""
    registry = ToolRegistry()
    registry.register(Tool(
        name="get_weather",
        description="Get the current weather and a daily forecast for a city. Use for trip or weather questions.",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Lisbon'"},
                "days": {"type": "integer", "description": "Forecast days, 1-7", "default": 3},
            },
            "required": ["city"],
        },
        func=lambda city, days=3: weather.forecast(city, days),
    ))
    registry.register(Tool(
        name="add_task",
        description="Add a to-do item, optionally with a due date (YYYY-MM-DD) and priority.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due": {"type": "string", "description": "Due date as YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            },
            "required": ["title"],
        },
        func=lambda title, due=None, priority="normal": tasks.add(title, due, priority),
    ))
    registry.register(Tool(
        name="list_tasks",
        description="List open to-do items, soonest due first.",
        parameters={"type": "object", "properties": {}},
        func=lambda: {"tasks": tasks.list()},
    ))
    registry.register(Tool(
        name="complete_task",
        description="Mark a to-do item as done by its id.",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        func=lambda task_id: tasks.complete(task_id),
    ))
    return registry
