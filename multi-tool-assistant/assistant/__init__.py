"""Multi-tool AI assistant: weather, travel, tasks and profile tools driven by an agent loop."""

from dataclasses import asdict

from .agent import Agent, AgentResult, AnthropicPlanner, RulePlanner
from .profile import UserProfile
from .services import DestinationService, TaskStore, WeatherService
from .tools import Tool, ToolRegistry
from .trips import plan_trip


def build_registry(
    weather: WeatherService,
    destinations: DestinationService,
    tasks: TaskStore,
    profile: UserProfile,
    profile_path: str,
) -> ToolRegistry:
    """Register every tool the agent can use. Add new tools here."""
    registry = ToolRegistry()

    def get_weather(city=None, days=3):
        city = city or profile.home_city
        if not city:
            raise ValueError("no city given and no home city saved yet; ask the user for a city")
        return weather.forecast(city, days)

    def save_profile(**changes):
        profile.update(**{k: v for k, v in changes.items() if v is not None})
        profile.save(profile_path)
        return asdict(profile)

    registry.register(Tool(
        name="get_weather",
        description="Get the current weather and a daily forecast for a city. If no city is given, uses the user's saved home city.",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Lisbon'"},
                "days": {"type": "integer", "description": "Forecast days, 1-7", "default": 3},
            },
        },
        func=get_weather,
    ))
    registry.register(Tool(
        name="plan_trip",
        description="Build a trip plan for a destination city: forecast, country facts, and packing and document tasks added to the to-do list.",
        parameters={
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Destination city"},
                "days": {"type": "integer", "description": "Trip length in days, 1-7", "default": 3},
            },
            "required": ["destination"],
        },
        func=lambda destination, days=3: plan_trip(weather, destinations, tasks, destination, days),
    ))
    registry.register(Tool(
        name="country_info",
        description="Look up facts about a country: capital, currency, languages, region.",
        parameters={
            "type": "object",
            "properties": {"country": {"type": "string", "description": "Country name, e.g. 'Japan'"}},
            "required": ["country"],
        },
        func=lambda country: destinations.info(country),
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
    registry.register(Tool(
        name="get_profile",
        description="Get the user's saved profile: name, home city and temperature units.",
        parameters={"type": "object", "properties": {}},
        func=lambda: asdict(profile),
    ))
    registry.register(Tool(
        name="update_profile",
        description="Save changes to the user's profile. Only pass the fields that change.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "home_city": {"type": "string"},
                "units": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
        },
        func=save_profile,
    ))
    return registry
