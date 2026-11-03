# Multi-tool AI assistant

A small personal assistant that answers requests by calling tools. Each request runs an
**agent loop**: the planner picks a tool, the tool runs, the result goes back to the planner,
and this repeats until the planner has an answer (capped at a step limit).

Tools today:

| Tool | What it does | External API |
|---|---|---|
| `get_weather` | Current weather and a daily forecast for a city | Open-Meteo (free, no key) |
| `add_task` / `list_tasks` / `complete_task` | Local to-do list | none (JSON file) |

## Run it

```bash
pip install -r requirements.txt

# offline, rule-based planner
python main.py --trace

# Claude chooses the tools
export ANTHROPIC_API_KEY=your-key
python main.py --trace
```

Offline examples: `weather in Lisbon`, `add task pack passport`, `list tasks`, `complete task <id>`.

## Test

```bash
pytest -q
```

The tests fake all HTTP calls and script the planner, so they run without network access or a key.

## Layout

```
main.py                 CLI
assistant/tools.py      Tool + ToolRegistry (schemas for the LLM, safe execution)
assistant/services.py   Weather client and task store
assistant/agent.py      Agent loop, AnthropicPlanner, RulePlanner
assistant/__init__.py   build_registry(): where tools are registered
tests/                  Offline tests
```

## Adding a tool

1. Add a client or function in `assistant/services.py`, or a new module.
2. Register it in `build_registry()` in `assistant/__init__.py` with a name, a description the
   model can use, and a JSON schema for its arguments.
3. Add a test. If you want the offline planner to use it, add a pattern to `RulePlanner.plan`.

## Ideas for next steps

- Travel: flight or hotel APIs, and a `plan_trip` tool that combines weather and tasks
- Personal profile: home city and units stored in a JSON file and added to the system prompt
- Memory across sessions and a web UI
