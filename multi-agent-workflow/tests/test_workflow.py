"""Offline tests for the multi-agent workflow. No network: the webhook uses a fake session."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from workflow import (
    ExecutorAgent, Orchestrator, PlannerAgent, ResearchAgent, build_workflow, make_create_task, make_webhook,
)
from workflow.messages import Findings, Plan

NOTES = "examples/notes"


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "sleep.md").write_text("Sleep notes.\nAim for seven hours of sleep.\nCaffeine hurts sleep.\n")
    (tmp_path / "pricing.txt").write_text("Pricing page review is due in September.\n")
    (tmp_path / "ignored.pdf").write_text("sleep sleep sleep")  # wrong type, must be skipped
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "habits.md").write_text("Habits compound. Sleep is one.\n")
    return tmp_path


# --- planner -----------------------------------------------------------------

def test_planner_extracts_topic_and_automation_keywords():
    plan = PlannerAgent().plan("Make a report about the Q3 roadmap and remind me to review it")
    assert plan.query == "the Q3 roadmap"
    assert plan.want_report is True
    assert "create_task" in plan.automations


def test_planner_detects_webhook_and_no_report():
    plan = PlannerAgent().plan("Send it to my team on sleep, no report please")
    assert plan.query == "sleep"  # topic follows 'on'
    assert "webhook" in plan.automations
    assert plan.want_report is False


def test_planner_rejects_empty_and_topicless_requests():
    with pytest.raises(ValueError):
        PlannerAgent().plan("   ")
    with pytest.raises(ValueError):
        PlannerAgent().plan("please do the thing we talked over earlier today")


# --- research ----------------------------------------------------------------

def test_research_ranks_by_occurrences_and_returns_snippets(corpus):
    findings = ResearchAgent(corpus).research("sleep")
    sources = [f.source for f in findings.items]
    assert sources[0] == "sleep.md"  # three occurrences beats one
    assert "nested/habits.md" in sources
    assert all(not s.endswith(".pdf") for s in sources)
    assert "Aim for seven hours" in findings.items[0].snippet


def test_research_returns_empty_for_no_match(corpus):
    assert ResearchAgent(corpus).research("quantum cooking").empty


def test_research_handles_missing_corpus(tmp_path):
    assert ResearchAgent(tmp_path / "nope").research("sleep").empty


def test_research_reads_the_bundled_examples():
    findings = ResearchAgent(NOTES).research("sleep")
    assert findings.items and findings.items[0].source == "sleep.md"


# --- executor ----------------------------------------------------------------

def test_executor_writes_report_with_sources(corpus, tmp_path):
    plan = Plan(request="report on sleep", query="sleep")
    findings = ResearchAgent(corpus).research("sleep")
    report = ExecutorAgent(tmp_path / "out").execute(plan, findings)
    assert report.path and report.path.endswith(".md")
    text = open(report.path, encoding="utf-8").read()
    assert "# Report: sleep" in text and "## Sources" in text and "sleep.md" in text


def test_executor_is_honest_when_nothing_matched(tmp_path):
    report = ExecutorAgent(tmp_path / "out").execute(
        Plan(request="x", query="quantum cooking"), Findings(query="quantum cooking"),
    )
    assert "No matching notes were found" in report.markdown


def test_executor_skips_file_when_report_disabled(tmp_path):
    report = ExecutorAgent(tmp_path / "out").execute(
        Plan(request="x", query="sleep", want_report=False), Findings(query="sleep"),
    )
    assert report.path is None
    assert not (tmp_path / "out").exists()


def test_failing_automation_does_not_stop_others(tmp_path):
    def boom(plan, findings):
        raise RuntimeError("server down")

    def ok(plan, findings):
        return "done"

    executor = ExecutorAgent(tmp_path, {"boom": boom, "ok": ok})
    plan = Plan(request="x", query="sleep", want_report=False, automations=("boom", "ok", "missing"))
    results = {r.name: r for r in executor.execute(plan, Findings(query="sleep")).automation_results}
    assert results["boom"].ok is False and "server down" in results["boom"].detail
    assert results["ok"].ok is True
    assert results["missing"].ok is False


# --- automations -------------------------------------------------------------

def test_create_task_appends_to_json(tmp_path):
    tasks_file = tmp_path / "tasks.json"
    fn = make_create_task(tasks_file)
    plan = Plan(request="remind me", query="sleep")
    fn(plan, Findings(query="sleep"))
    fn(plan, Findings(query="sleep"))
    tasks = json.loads(tasks_file.read_text())
    assert len(tasks) == 2 and tasks[0]["title"] == "Follow up: sleep"


class FakePost:
    def __init__(self, status=200):
        self.status, self.sent = status, []

    def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        return SimpleNamespace(status_code=self.status, raise_for_status=lambda: None)


def test_webhook_posts_summary_json():
    fake = FakePost()
    fn = make_webhook("https://example.test/hook", session=fake)
    findings = Findings(query="sleep")
    from workflow.messages import Finding
    findings.items.append(Finding("sleep.md", "x", 3))
    msg = fn(Plan(request="notify me", query="sleep"), findings)
    url, body = fake.sent[0]
    assert url == "https://example.test/hook"
    assert body["matches"] == [{"source": "sleep.md", "score": 3}]
    assert "200" in msg


# --- orchestrator end to end -------------------------------------------------

def test_full_run_hands_off_through_all_agents(corpus, tmp_path):
    orch = build_workflow(corpus, tmp_path / "out", tmp_path / "tasks.json")
    result = orch.run("Make a report about sleep and remind me to review it")
    assert result.ok
    assert result.plan.query == "sleep"
    assert result.findings.items[0].source == "sleep.md"
    assert result.report.path
    assert [r.name for r in result.report.automation_results] == ["create_task"]
    assert result.report.automation_results[0].ok
    assert any(line.startswith("planner:") for line in result.trace)
    assert any(line.startswith("research:") for line in result.trace)
    assert any(line.startswith("executor:") for line in result.trace)


def test_run_rejects_bad_request_and_stops_before_research(corpus, tmp_path):
    orch = build_workflow(corpus, tmp_path / "out", tmp_path / "tasks.json")
    result = orch.run("   ")
    assert result.ok is False
    assert result.report is None and result.findings is None
    assert "rejected" in result.trace[0]


def test_webhook_only_enabled_with_url(corpus, tmp_path):
    no_url = build_workflow(corpus, tmp_path / "out", tmp_path / "t.json")
    r = no_url.run("report on sleep and notify the team")
    assert [a.name for a in r.report.automation_results] == ["webhook"]
    assert r.report.automation_results[0].ok is False  # no webhook registered, reported not raised
    assert "no automation registered" in r.report.automation_results[0].detail
