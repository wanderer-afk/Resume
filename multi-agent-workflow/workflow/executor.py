"""Executor Agent: writes the report and triggers the automations named in the Plan.

Each automation is a plain function `(plan, findings) -> str` registered by name. A failing
automation is recorded in the report and does not stop the other steps.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .messages import AutomationResult, Findings, Plan, Report

Automation = Callable[[Plan, Findings], str]


class ExecutorAgent:
    name = "executor"

    def __init__(self, output_dir: str | Path, automations: dict[str, Automation] | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.automations = automations or {}

    def build_markdown(self, plan: Plan, findings: Findings) -> str:
        lines = [f"# Report: {plan.query}", "", f"_Request:_ {plan.request}", ""]
        if findings.empty:
            lines += ["No matching notes were found for this topic.", ""]
        else:
            lines += ["## Key findings", ""]
            for f in findings.items:
                lines += [f"### {f.source} (matched {f.score} terms)", "", "> " + f.snippet.replace("\n", "\n> "), ""]
            lines += ["## Sources", ""] + [f"- {f.source}" for f in findings.items] + [""]
        return "\n".join(lines)

    def execute(self, plan: Plan, findings: Findings) -> Report:
        markdown = self.build_markdown(plan, findings)
        path = None
        if plan.want_report:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            slug = "".join(c if c.isalnum() else "-" for c in plan.query.lower()).strip("-")[:40] or "report"
            file = self.output_dir / f"{stamp}-{slug}.md"
            file.write_text(markdown, encoding="utf-8")
            path = str(file)

        results: list[AutomationResult] = []
        for name in plan.automations:
            fn = self.automations.get(name)
            if fn is None:
                results.append(AutomationResult(name, False, "no automation registered with this name"))
                continue
            try:
                results.append(AutomationResult(name, True, fn(plan, findings)))
            except Exception as exc:  # one failing automation must not stop the others
                results.append(AutomationResult(name, False, f"{type(exc).__name__}: {exc}"))
        return Report(path=path, markdown=markdown, automation_results=results)
