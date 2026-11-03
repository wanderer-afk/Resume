# Multi-agent AI workflow

Three specialised agents work on one request in sequence, coordinated by an orchestrator:

| Agent | Job | Inputs → outputs |
|---|---|---|
| **Planner** | Reads the request and decides the topic, whether to write a report, and which automations to run | request text → `Plan` |
| **Research** | Searches a folder of `.md` and `.txt` notes and returns the best-matching snippets with sources | `Plan.query` → `Findings` |
| **Executor** | Writes a markdown report with sources, then triggers the automations named in the plan | `Plan` + `Findings` → `Report` |

The orchestrator passes typed messages between them, records a trace of every hand-off, and
keeps going when one automation fails. Research never invents content: if nothing matches, the
report says so.

## Run it

```bash
pip install -r requirements.txt

python main.py "Make a report about sleep and remind me to review it"
python main.py "Summarise my notes on reading, no report please"
python main.py "Send it to my team on sleep" --webhook-url https://example.test/hook
```

Options: `--corpus` (default `examples/notes`), `--out` (default `reports/`), `--tasks-file`
(default `data/tasks.json`).

## Planner phrasing

- The topic follows "about", "on", "regarding" or "for", and ends at a comma or at "and", "then", "but", "no report" or "please".
- "remind", "reminder", "task" or "todo" adds a `create_task` automation.
- "notify", "webhook" or "send it to" adds a `webhook` automation, which only runs when `--webhook-url` is given.
- "no report" turns off the report file.

The planner is rule-based, so it works offline. A Claude-backed planner can replace
`PlannerAgent.plan` and return the same `Plan` type.

## Test

```bash
pytest -q
```

16 tests run offline. They cover planning, research ranking, report contents, failure isolation
for automations, webhook payloads, and a full run through all three agents.
**The webhook has not been sent to a live endpoint.**

## Layout

```
main.py                    CLI
workflow/messages.py       Typed hand-off objects: Plan, Findings, Report, RunResult
workflow/planner.py        Planner agent
workflow/research.py       Research agent (local notes search)
workflow/executor.py       Executor agent (report + automations)
workflow/automations.py    create_task and webhook automations
workflow/orchestrator.py   Hands work between agents and records the trace
workflow/__init__.py       build_workflow(): wires the agents together
examples/notes/            Sample notes to research
tests/                     Offline tests
```

## Adding an agent or automation

- **Automation:** write `(plan, findings) -> str`, register it in `build_workflow`, and add a
  keyword pattern in `PlannerAgent` so the planner can request it.
- **Agent:** give it a `name`, a typed input and output in `messages.py`, and a step in
  `Orchestrator.run`.

## Known gaps

- The planner is rule-based. A Claude planner has not been built or tested.
- Research uses keyword matching only. There's no semantic search and no web source.
- Only one request runs at a time, and nothing is retried after a failure.
- The Executor doesn't check whether a report already exists before writing a new one.
