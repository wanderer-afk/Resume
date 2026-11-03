"""Typed messages passed between agents. Each agent only reads and writes these objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:
    """Produced by the Planner. Says what to research and what to do with it."""

    request: str
    query: str                      # what the Research agent should search for
    want_report: bool = True        # Executor writes a markdown report
    automations: tuple[str, ...] = ()  # names of automations for the Executor to trigger


@dataclass(frozen=True)
class Finding:
    source: str                     # file path relative to the corpus
    snippet: str                    # the most relevant lines
    score: int                      # number of matched query terms


@dataclass
class Findings:
    query: str
    items: list[Finding] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items


@dataclass
class AutomationResult:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    path: str | None
    markdown: str
    automation_results: list[AutomationResult] = field(default_factory=list)


@dataclass
class RunResult:
    request: str
    ok: bool
    trace: list[str]
    plan: Plan | None = None
    findings: Findings | None = None
    report: Report | None = None
    error: str | None = None
