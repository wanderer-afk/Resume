"""Trip planning: combines the weather forecast, country facts and packing tasks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .services import DestinationService, ServiceError, TaskStore, WeatherService

RAIN_THRESHOLD_PCT = 50  # days with at least this rain chance get an umbrella task


def plan_trip(
    weather: WeatherService,
    destinations: DestinationService,
    tasks: TaskStore,
    destination: str,
    days: int = 3,
) -> dict[str, Any]:
    forecast = weather.forecast(destination, days)  # raises ServiceError if the city is unknown

    country: dict[str, Any] | None = None
    country_error: str | None = None
    try:
        country = destinations.info(forecast["country"])
    except (ServiceError, Exception) as exc:  # trip plan still works without country facts
        country_error = str(exc)

    start = date.today()
    added: list[dict[str, Any]] = []
    rainy_days = [d for d in forecast["daily"] if (d["rain_chance_pct"] or 0) >= RAIN_THRESHOLD_PCT]
    if rainy_days:
        added.append(tasks.add(
            f"Pack umbrella for {destination}",
            due=(start + timedelta(days=1)).isoformat(),
            priority="high",
        ))
    added.append(tasks.add(f"Check passport and visa rules for {forecast['country']}", priority="high"))

    return {
        "destination": forecast["location"],
        "forecast": forecast,
        "country": country,
        "country_error": country_error,
        "rainy_days": [d["date"] for d in rainy_days],
        "tasks_added": added,
    }
