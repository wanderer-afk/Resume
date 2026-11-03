"""Multi-agent workflow: Planner, Research and Executor agents coordinated by an Orchestrator."""

from .automations import make_create_task, make_webhook
from .executor import ExecutorAgent
from .messages import Plan, Findings, Finding, Report, RunResult
from .orchestrator import Orchestrator
from .planner import PlannerAgent
from .research import ResearchAgent


def build_workflow(corpus_dir, output_dir, tasks_file, webhook_url=None) -> Orchestrator:
    """Wire the agents together. Automations are enabled by name; webhook only when a URL is given."""
    automations = {"create_task": make_create_task(tasks_file)}
    if webhook_url:
        automations["webhook"] = make_webhook(webhook_url)
    return Orchestrator(
        PlannerAgent(),
        ResearchAgent(corpus_dir),
        ExecutorAgent(output_dir, automations),
    )
