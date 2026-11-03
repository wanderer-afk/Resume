"""Built-in automations the Executor can trigger. Register your own in `default_automations`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import requests

from .messages import Findings, Plan

WEBHOOK_TIMEOUT_SECONDS = 10


def make_create_task(tasks_file: str | Path) -> Callable[[Plan, Findings], str]:
    """Append a follow-up task to a local JSON list."""
    path = Path(tasks_file)

    def create_task(plan: Plan, findings: Findings) -> str:
        tasks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        title = f"Follow up: {plan.query}"
        tasks.append({"title": title, "source_request": plan.request, "sources": [f.source for f in findings.items]})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
        return f"added task '{title}' to {path}"

    return create_task


def make_webhook(url: str, session: requests.Session | None = None) -> Callable[[Plan, Findings], str]:
    """POST a JSON summary to a URL. Only enabled when the caller provides a URL."""
    client = session or requests.Session()

    def webhook(plan: Plan, findings: Findings) -> str:
        body = {
            "query": plan.query,
            "request": plan.request,
            "matches": [{"source": f.source, "score": f.score} for f in findings.items],
        }
        resp = client.post(url, json=body, timeout=WEBHOOK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return f"webhook responded {resp.status_code}"

    return webhook
