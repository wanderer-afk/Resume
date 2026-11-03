"""Research Agent: searches a local folder of notes and returns the most relevant snippets.

It only reads files under the corpus directory, and it never invents content: if nothing
matches, it returns an empty Findings object and the Executor says so.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .messages import Finding, Findings

STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "my", "me", "is", "with", "about"}
TEXT_SUFFIXES = {".md", ".txt"}
MAX_SNIPPET_LINES = 4


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


class ResearchAgent:
    name = "research"

    def __init__(self, corpus_dir: str | Path, max_results: int = 5) -> None:
        self.corpus = Path(corpus_dir)
        self.max_results = max_results

    def research(self, query: str) -> Findings:
        terms = set(_terms(query))
        findings = Findings(query=query)
        if not terms or not self.corpus.is_dir():
            return findings

        scored: list[Finding] = []
        for path in sorted(self.corpus.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            best_line, best_score = None, 0
            for i, line in enumerate(lines):
                score = len(terms & set(_terms(line)))
                if score > best_score:
                    best_line, best_score = i, score
            if best_line is None:
                continue
            counts = Counter(_terms(" ".join(lines)))
            score = sum(counts[t] for t in terms)  # total occurrences of query terms in the file
            snippet = "\n".join(lines[best_line:best_line + MAX_SNIPPET_LINES]).strip()
            scored.append(Finding(source=str(path.relative_to(self.corpus)), snippet=snippet, score=score))

        scored.sort(key=lambda f: (-f.score, f.source))
        findings.items = scored[: self.max_results]
        return findings
