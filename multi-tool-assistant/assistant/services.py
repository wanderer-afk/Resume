"""Clients for external APIs and local productivity storage.

External services used (all free, no API key required):
  * Open-Meteo geocoding + forecast  (weather)
  * REST Countries                    (country facts for trip planning)

Productivity tools use a local JSON file so they work offline.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
COUNTRY_URL = "https://restcountries.com/v3.1/name/{name}"
TIMEOUT_SECONDS = 10

# WMO weather interpretation codes used by Open-Meteo.
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


class ServiceError(RuntimeError):
    """Raised when an external service returns no usable data."""


class WeatherService:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = self.session.get(url, params=params, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()

    def geocode(self, city: str) -> dict[str, Any]:
        data = self._get(GEOCODE_URL, {"name": city, "count": 1, "language": "en"})
        results = data.get("results") or []
        if not results:
            raise ServiceError(f"no location found for '{city}'")
        place = results[0]
        return {
            "name": place.get("name"),
            "country": place.get("country"),
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place.get("timezone", "auto"),
        }

    def forecast(self, city: str, days: int = 3) -> dict[str, Any]:
        days = max(1, min(int(days), 7))
        place = self.geocode(city)
        data = self._get(
            FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "timezone": place["timezone"],
                "forecast_days": days,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            },
        )
        daily = data.get("daily", {})
        upcoming = []
        for i, day in enumerate(daily.get("time", [])):
            code = daily["weather_code"][i]
            upcoming.append({
                "date": day,
                "conditions": WMO_CODES.get(code, f"code {code}"),
                "high_c": daily["temperature_2m_max"][i],
                "low_c": daily["temperature_2m_min"][i],
                "rain_chance_pct": daily["precipitation_probability_max"][i],
            })
        current = data.get("current", {})
        return {
            "location": f"{place['name']}, {place['country']}",
            "country": place["country"],
            "current": {
                "temperature_c": current.get("temperature_2m"),
                "conditions": WMO_CODES.get(current.get("weather_code"), "unknown"),
                "wind_kmh": current.get("wind_speed_10m"),
            },
            "daily": upcoming,
        }


class DestinationService:
    """Country facts (capital, currency, languages, timezones) from REST Countries."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def info(self, country: str) -> dict[str, Any]:
        resp = self.session.get(COUNTRY_URL.format(name=country), params={"fullText": "true"}, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 404:
            # retry with a partial match, e.g. "United States" vs "United States of America"
            resp = self.session.get(COUNTRY_URL.format(name=country), params={"fullText": "false"}, timeout=TIMEOUT_SECONDS)
        if resp.status_code == 404:
            raise ServiceError(f"no country found matching '{country}'")
        resp.raise_for_status()
        c = resp.json()[0]
        return {
            "name": c.get("name", {}).get("common"),
            "capital": (c.get("capital") or ["unknown"])[0],
            "region": c.get("region"),
            "languages": sorted((c.get("languages") or {}).values()),
            "currencies": sorted(
                f"{v.get('name')} ({v.get('symbol', '')})".strip()
                for v in (c.get("currencies") or {}).values()
            ),
            "timezones": c.get("timezones", []),
            "population": c.get("population"),
        }


class TaskStore:
    """Small JSON-backed to-do list. Thread-safe enough for a single-user CLI."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, tasks: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")

    def add(self, title: str, due: str | None = None, priority: str = "normal") -> dict[str, Any]:
        if priority not in {"low", "normal", "high"}:
            raise ValueError("priority must be low, normal or high")
        if due is not None:
            date.fromisoformat(due)  # validates YYYY-MM-DD
        with self._lock:
            tasks = self._load()
            task = {
                "id": uuid.uuid4().hex[:8], "title": title, "due": due,
                "priority": priority, "done": False,
            }
            tasks.append(task)
            self._save(tasks)
        return task

    def list(self, include_done: bool = False) -> list[dict[str, Any]]:
        tasks = self._load()
        if not include_done:
            tasks = [t for t in tasks if not t["done"]]
        order = {"high": 0, "normal": 1, "low": 2}
        return sorted(tasks, key=lambda t: (t["due"] or "9999-12-31", order[t["priority"]]))

    def complete(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            tasks = self._load()
            for t in tasks:
                if t["id"] == task_id:
                    t["done"] = True
                    self._save(tasks)
                    return t
        raise ServiceError(f"no task with id '{task_id}'")

    def due_within(self, days: int) -> list[dict[str, Any]]:
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        return [t for t in self.list() if t["due"] and t["due"] <= cutoff]
