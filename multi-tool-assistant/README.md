# Multi-tool AI assistant

A personal assistant that answers requests by calling tools. Each request runs an **agent loop**:
the planner picks a tool, the tool runs, the result goes back to the planner, and this repeats
until the planner has an answer (capped at a step limit).

| Tool | What it does | External API |
|---|---|---|
| `get_weather` | Current weather and a daily forecast. Uses the saved home city if no city is given | Open-Meteo (free, no key) |
| `plan_trip` | Forecast + country facts + packing and passport tasks for a destination | Open-Meteo + REST Countries |
| `country_info` | Capital, currency, languages, region for a country | REST Countries (free, no key) |
| `add_task` / `list_tasks` / `complete_task` | Local to-do list | none (JSON file) |
| `get_profile` / `update_profile` | Saved name, home city and temperature units | none (JSON file) |

Replies use the saved units (°C or °F).

## Run it

```bash
pip install -r requirements.txt

# terminal chat, offline rule planner
python main.py --trace

# terminal chat, Claude chooses the tools
export ANTHROPIC_API_KEY=your-key
python main.py --trace

# web UI at http://127.0.0.1:8000
python main.py --web
```

Data is stored in `data/` (`profile.json`, `tasks.json`). Change it with `--data-dir`.

Offline examples the rule planner understands:

- `trip to Lisbon for 4 days`
- `weather in Paris`, or just `weather` once a home city is saved
- `facts about Japan`
- `my home city is Lisbon`, `my name is Ana`, `set units to fahrenheit`, `my profile`
- `add task pack passport`, `list tasks`, `complete task <id>`

## Test

```bash
pytest -q
```

All 32 tests run offline. HTTP is faked, the Claude client is a fake, and the planner is scripted.
**Live API calls have not been exercised yet.** That needs network access to `api.open-meteo.com`,
`geocoding-api.open-meteo.com` and `restcountries.com`, plus an API key for the Claude path.

## Layout

```
main.py                 CLI and web entry point
assistant/tools.py      Tool + ToolRegistry (schemas for the LLM, safe execution)
assistant/services.py   Weather, REST Countries and task-store clients
assistant/trips.py      plan_trip: combines forecast, country facts and tasks
assistant/profile.py    Saved profile (name, home city, units)
assistant/agent.py      Agent loop, AnthropicPlanner, RulePlanner, reply formatting
assistant/web.py        Standard-library web UI and JSON endpoint
assistant/__init__.py   build_registry(): where tools are registered
tests/                  Offline tests
```

## Adding a tool

1. Add a client or function in `assistant/services.py` or a new module.
2. Register it in `build_registry()` in `assistant/__init__.py` with a name, a description the model
   can use, and a JSON schema for its arguments.
3. Add a reply format in `summarise()` in `assistant/agent.py`, and a pattern in `RulePlanner.plan`
   if the offline planner should use it.
4. Add a test.

## Known gaps (from an independent review)

- The Claude path is covered only by a fake client. It has not been run against the live API or
  evaluated for tool-choice accuracy.
- No conversation memory: each request starts fresh, so follow-ups like "and tomorrow?" lack context.
- Tool results are sent back as one message each, and failed tools are not marked with `is_error`.
- `stop_reason` is not checked, so a reply cut off at the token limit is shown as normal text.
- Task writes are not atomic: a crash mid-write can corrupt `tasks.json`.
- Dependencies are unpinned (`>=`).
