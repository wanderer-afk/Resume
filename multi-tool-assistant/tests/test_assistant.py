"""Offline tests: HTTP is faked, and the agent uses the rule planner or a scripted planner."""

from __future__ import annotations

import json
import threading
import urllib.request
from types import SimpleNamespace

import pytest

from assistant import (
    Agent, DestinationService, RulePlanner, TaskStore, UserProfile, WeatherService, build_registry,
)
from assistant.agent import Decision, summarise
from assistant.services import ServiceError
from assistant.tools import Tool, ToolRegistry
from assistant.trips import plan_trip
from assistant.web import handle_chat, make_handler
from http.server import ThreadingHTTPServer


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Answers Open-Meteo and REST Countries calls based on the URL."""

    def __init__(self, geocode_results=None, country=None, country_status=200):
        self.geocode_results = geocode_results if geocode_results is not None else PARIS
        self.country = country or COUNTRY_FR
        self.country_status = country_status

    def get(self, url, params=None, timeout=None):
        if "geocoding" in url:
            return FakeResponse({"results": self.geocode_results})
        if "restcountries" in url:
            return FakeResponse([self.country], self.country_status)
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
COUNTRY_FR = {
    "name": {"common": "France"}, "capital": ["Paris"], "region": "Europe",
    "languages": {"fra": "French"}, "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
    "timezones": ["UTC+01:00"], "population": 68000000,
}


@pytest.fixture
def tasks(tmp_path):
    return TaskStore(tmp_path / "tasks.json")


@pytest.fixture
def profile(tmp_path):
    return UserProfile()


@pytest.fixture
def session_fake():
    return FakeSession()


@pytest.fixture
def tools(tasks, profile, tmp_path, session_fake):
    return build_registry(
        WeatherService(session_fake), DestinationService(session_fake), tasks, profile, str(tmp_path / "profile.json"),
    )


# --- services -----------------------------------------------------------------

def test_weather_service_formats_forecast():
    out = WeatherService(FakeSession()).forecast("Paris", days=2)
    assert out["location"] == "Paris, France"
    assert out["country"] == "France"
    assert out["current"]["conditions"] == "partly cloudy"
    assert out["daily"][0]["conditions"] == "light rain"
    assert out["daily"][0]["rain_chance_pct"] == 80


def test_weather_unknown_city_raises():
    with pytest.raises(ServiceError):
        WeatherService(FakeSession(geocode_results=[])).geocode("Nowhereville")


def test_destination_service_returns_country_facts():
    info = DestinationService(FakeSession()).info("France")
    assert info["capital"] == "Paris"
    assert info["currencies"] == ["Euro (€)"]
    assert info["languages"] == ["French"]


def test_destination_service_404_raises():
    with pytest.raises(ServiceError):
        DestinationService(FakeSession(country_status=404)).info("Atlantis")


def test_task_store_add_list_complete(tasks):
    t = tasks.add("Pack passport", due="2026-11-04", priority="high")
    assert [x["title"] for x in tasks.list()] == ["Pack passport"]
    tasks.complete(t["id"])
    assert tasks.list() == []
    assert len(tasks.list(include_done=True)) == 1


def test_task_store_rejects_bad_date(tasks):
    with pytest.raises(ValueError):
        tasks.add("Bad", due="next tuesday")


# --- profile -----------------------------------------------------------------

def test_profile_formats_temperature_units():
    p = UserProfile(units="fahrenheit")
    assert p.format_temp(0) == "32°F"
    assert UserProfile().format_temp(20) == "20°C"
    assert p.format_temp(None) == "n/a"


def test_profile_rejects_bad_units():
    with pytest.raises(ValueError):
        UserProfile(units="kelvin")


def test_profile_round_trips_to_disk(tmp_path):
    path = tmp_path / "p.json"
    UserProfile(name="Ana", home_city="Lisbon", units="fahrenheit").save(path)
    loaded = UserProfile.load(path)
    assert (loaded.name, loaded.home_city, loaded.units) == ("Ana", "Lisbon", "fahrenheit")


# --- trip planning -----------------------------------------------------------

def test_plan_trip_combines_weather_country_and_tasks(tasks):
    fake = FakeSession()
    result = plan_trip(WeatherService(fake), DestinationService(fake), tasks, "Paris", days=2)
    assert result["country"]["capital"] == "Paris"
    assert result["rainy_days"] == ["2026-11-04"]
    titles = [t["title"] for t in tasks.list()]
    assert any("umbrella" in t for t in titles)
    assert any("passport" in t.lower() for t in titles)


def test_plan_trip_survives_country_lookup_failure(tasks):
    fake = FakeSession(country_status=500)
    result = plan_trip(WeatherService(fake), DestinationService(fake), tasks, "Paris", days=2)
    assert result["country"] is None
    assert result["country_error"]
    assert result["forecast"]["daily"]


# --- registry ----------------------------------------------------------------

def test_registry_reports_errors_instead_of_raising(tools):
    assert "unknown tool" in tools.call("nope", {})["error"]
    assert "missing required" in tools.call("plan_trip", {})["error"]
    assert "bad arguments" in tools.call("get_weather", {"city": "Paris", "bogus": 1})["error"]


def test_get_weather_without_city_uses_home_city(tools, profile):
    profile.update(home_city="Paris")
    result = tools.call("get_weather", {})
    assert result["location"] == "Paris, France"


def test_get_weather_without_city_and_no_home_is_an_error(tools, profile):
    profile.update(home_city=None)
    assert "no home city" in tools.call("get_weather", {})["error"]


def test_default_home_city_is_tokyo():
    assert UserProfile().home_city == "Tokyo"


def test_trip_to_japan_adds_japan_tasks(tmp_path):
    from assistant.services import SampleDestinationService, SampleWeatherService
    store = TaskStore(tmp_path / "t.json")
    result = plan_trip(SampleWeatherService(), SampleDestinationService(), store, "Kyoto", days=2)
    titles = [t["title"] for t in result["tasks_added"]]
    assert any("Suica" in t for t in titles)
    assert any("yen" in t for t in titles)


def test_profile_tool_saves_changes(tools, profile, tmp_path):
    tools.call("update_profile", {"units": "fahrenheit", "name": "Ana"})
    assert profile.units == "fahrenheit"
    saved = UserProfile.load(tmp_path / "profile.json")
    assert saved.name == "Ana"


def test_profile_tool_rejects_bad_units(tools):
    assert "error" in tools.call("update_profile", {"units": "kelvin"})


def test_registry_rejects_duplicate_names():
    reg = ToolRegistry()
    reg.register(Tool("x", "d", {"type": "object", "properties": {}}, lambda: {}))
    with pytest.raises(ValueError):
        reg.register(Tool("x", "d", {"type": "object", "properties": {}}, lambda: {}))


# --- rule planner and loop ---------------------------------------------------

def run(tools, profile, text):
    return Agent(RulePlanner(profile), tools).run(text)


def test_rule_planner_weather_in_city(tools, profile):
    result = run(tools, profile, "weather in Paris")
    assert "Paris, France" in result.reply
    assert result.trace[0].startswith("step 1: get_weather")


def test_rule_planner_trip(tools, profile):
    result = run(tools, profile, "trip to Paris for 2 days")
    assert "Trip plan for Paris, France" in result.reply
    assert "Capital" not in result.reply or "capital Paris" in result.reply
    assert "Tasks added" in result.reply


def test_rule_planner_country_facts(tools, profile):
    assert "capital Paris" in run(tools, profile, "facts about France").reply


def test_rule_planner_units_and_home_city_personalise_replies(tools, profile):
    run(tools, profile, "set units to fahrenheit")
    run(tools, profile, "my home city is Paris")
    result = run(tools, profile, "weather")
    assert "°F" in result.reply
    assert "Paris, France" in result.reply


def test_rule_planner_task_flow(tools, profile):
    agent = Agent(RulePlanner(profile), tools)
    agent.run("add task buy umbrella")
    assert "buy umbrella" in agent.run("list tasks").reply


def test_rule_planner_help_for_unknown_request(tools, profile):
    assert "I can plan trips" in run(tools, profile, "tell me a joke").reply


class ScriptedPlanner:
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
    assert planner.seen == [1, 3]


def test_loop_stops_at_step_limit(tools):
    looping = Decision(tool_calls=[{"id": "a", "name": "list_tasks", "input": {}}])
    result = Agent(ScriptedPlanner([looping] * 10), tools, max_steps=2).run("loop")
    assert "step limit" in result.reply
    assert len(result.trace) == 2


def test_summarise_surfaces_tool_errors(profile):
    msg = {"role": "tool", "name": "get_weather", "content": {"error": "no location found"}}
    assert summarise(msg, profile) == "Sorry, that failed: no location found"


# --- web endpoint ------------------------------------------------------------

def test_handle_chat_validates_input(tools, profile):
    agent = Agent(RulePlanner(profile), tools)
    lock = threading.Lock()
    assert handle_chat(agent, lock, {"message": ""})[0] == 400
    assert handle_chat(agent, lock, "not a dict")[0] == 400
    assert handle_chat(agent, lock, {"message": "x" * 2000})[0] == 400


def test_http_server_serves_page_and_chat(tools, profile):
    agent = Agent(RulePlanner(profile), tools)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(agent))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as r:
            assert b"Multi-tool assistant" in r.read()
        req = urllib.request.Request(
            base + "/api/chat",
            data=json.dumps({"message": "facts about France"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read())
        assert "capital Paris" in body["reply"]
        assert body["trace"]
    finally:
        server.shutdown()
        server.server_close()


def test_sample_mode_is_labelled_and_trip_plan_gets_country_facts(tasks, profile, tmp_path):
    from assistant.services import SampleDestinationService, SampleWeatherService
    weather, dest = SampleWeatherService(), SampleDestinationService()
    result = plan_trip(weather, dest, tasks, "Lisbon", days=2)
    assert result["forecast"]["source"].startswith("SAMPLE DATA")
    assert result["country"]["capital"] == "Lisbon"
    assert "source" in result["country"]


# --- friendly errors and network check ----------------------------------------

import requests as _requests
from assistant.netcheck import check_network, format_report


class DownSession:
    """Every request fails the way a blocked or offline network does."""

    def get(self, url, params=None, timeout=None):
        raise _requests.ConnectionError("blocked")


def test_unreachable_weather_gives_one_friendly_line(tmp_path):
    reg = build_registry(WeatherService(DownSession()), DestinationService(DownSession()),
                         TaskStore(tmp_path / "t.json"), UserProfile(), str(tmp_path / "p.json"))
    result = reg.call("get_weather", {"city": "Paris"})
    assert result == {"error": "could not reach the weather service; try again or use --sample-data"}


def test_unreachable_country_gives_one_friendly_line(tmp_path):
    reg = build_registry(WeatherService(DownSession()), DestinationService(DownSession()),
                         TaskStore(tmp_path / "t.json"), UserProfile(), str(tmp_path / "p.json"))
    result = reg.call("country_info", {"country": "France"})
    assert result == {"error": "could not reach the country service; try again or use --sample-data"}


def test_chat_reply_shows_the_friendly_line_not_a_traceback(tmp_path):
    reg = build_registry(WeatherService(DownSession()), DestinationService(DownSession()),
                         TaskStore(tmp_path / "t.json"), UserProfile(), str(tmp_path / "p.json"))
    reply = Agent(RulePlanner(), reg).run("weather in Paris").reply
    assert reply == "Sorry, that failed: could not reach the weather service; try again or use --sample-data"
    assert "Traceback" not in reply and "ProxyError" not in reply


def test_check_network_reports_each_site(monkeypatch):
    class Partial:
        def get(self, url, params=None, timeout=None):
            if "restcountries" in url:
                raise _requests.ConnectionError("blocked")
            return FakeResponse({})

    rows = check_network(Partial())
    assert [ok for _, ok, _ in rows] == [True, True, False]
    report = format_report(rows)
    assert "OK" in report and "FAILED" in report
    assert "2 of 3 websites work" in report
    assert "--sample-data" in report


def test_check_network_all_good_message():
    rows = check_network(FakeSession())
    assert all(ok for _, ok, _ in rows)
    assert "All 3 of 3 websites work" in format_report(rows)


def test_sample_data_is_labelled_as_made_up():
    from assistant.services import SAMPLE_NOTE
    assert "made up" in SAMPLE_NOTE


class OddJsonSession:
    """Returns a JSON error object where a list of countries is expected."""

    def get(self, url, params=None, timeout=None):
        return FakeResponse({"status": 400, "message": "Bad Request"}, 200)


def test_unexpected_country_response_is_a_friendly_error():
    with pytest.raises(ServiceError) as exc:
        DestinationService(OddJsonSession()).info("Japan")
    assert str(exc.value) == "could not reach the country service; try again or use --sample-data"


def test_empty_country_list_is_not_found():
    class Empty:
        def get(self, url, params=None, timeout=None):
            return FakeResponse([], 200)
    with pytest.raises(ServiceError) as exc:
        DestinationService(Empty()).info("Japan")
    assert "no country found" in str(exc.value)
