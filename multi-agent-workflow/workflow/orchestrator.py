"""Orchestrator: hands a request through Planner -> Research -> Executor and records the trace."""

from __future__ import annotations

from .executor import ExecutorAgent
from .messages import RunResult
from .planner import PlannerAgent
from .research import ResearchAgent


class Orchestrator:
    def __init__(self, planner: PlannerAgent, research: ResearchAgent, executor: ExecutorAgent) -> None:
        self.planner = planner
        self.research = research
        self.executor = executor

    def run(self, request: str) -> RunResult:
        trace: list[str] = []

        # Planner: interpret the request
        try:
            plan = self.planner.plan(request)
        except ValueError as exc:
            trace.append(f"{self.planner.name}: rejected request ({exc})")
            return RunResult(request=request, ok=False, trace=trace, error=str(exc))
        trace.append(f"{self.planner.name}: query='{plan.query}' report={plan.want_report} "
                     f"automations={list(plan.automations)}")

        # Research: gather information from the corpus
        findings = self.research.research(plan.query)
        trace.append(f"{self.research.name}: {len(findings.items)} matching source(s)")

        # Executor: write the report and trigger automations
        report = self.executor.execute(plan, findings)
        if report.path:
            trace.append(f"{self.executor.name}: wrote {report.path}")
        for r in report.automation_results:
            trace.append(f"{self.executor.name}: automation '{r.name}' -> {'ok' if r.ok else 'failed'} ({r.detail})")

        return RunResult(request=request, ok=True, trace=trace, plan=plan, findings=findings, report=report)
