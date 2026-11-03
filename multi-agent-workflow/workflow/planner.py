"""Planner Agent: turns a free-text request into a Plan.

This version is rule-based so it runs offline. A Claude-backed planner can replace
`PlannerAgent.plan` as long as it returns the same `Plan` type.
"""

from __future__ import annotations

import re

from .messages import Plan

AUTOMATION_KEYWORDS = {
    "create_task": r"\b(remind|reminder|task|todo|to-do)\b",
    "webhook": r"\b(notify|webhook|send (?:it )?to)\b",
}


class PlannerAgent:
    name = "planner"

    def plan(self, request: str) -> Plan:
        text = request.strip()
        if not text:
            raise ValueError("request is empty")

        query = self._extract_topic(text)
        if not query:
            raise ValueError("could not find a topic to research; say e.g. 'about <topic>'")

        automations = tuple(
            name for name, pattern in AUTOMATION_KEYWORDS.items() if re.search(pattern, text, re.I)
        )
        want_report = not re.search(r"\bno report\b", text, re.I)
        return Plan(request=text, query=query, want_report=want_report, automations=automations)

    @staticmethod
    def _extract_topic(text: str) -> str:
        m = re.search(r"\b(?:about|on|regarding|for)\s+(.+)$", text, re.I)
        if m:
            # the topic ends at a comma or at the start of a second instruction
            topic = re.split(r",|\s+(?:and|then|but|no report|please)\b", m.group(1), flags=re.I)[0]
            return topic.strip(" .?!,")
        return text.strip(" .?!,") if len(text.split()) <= 6 else ""
