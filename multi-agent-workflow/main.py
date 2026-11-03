"""Run one request through the multi-agent workflow.

  python main.py "Make a report about the Q3 roadmap and remind me to review it"
  python main.py "Summarise my notes on sleep" --corpus examples/notes --out reports
"""

from __future__ import annotations

import argparse

from workflow import build_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("request", help="what you want, in plain words")
    parser.add_argument("--corpus", default="examples/notes", help="folder of .md/.txt notes to research")
    parser.add_argument("--out", default="reports", help="folder for generated reports")
    parser.add_argument("--tasks-file", default="data/tasks.json", help="JSON file the create_task automation appends to")
    parser.add_argument("--webhook-url", default=None, help="enable the webhook automation by giving a URL")
    args = parser.parse_args()

    orchestrator = build_workflow(args.corpus, args.out, args.tasks_file, args.webhook_url)
    result = orchestrator.run(args.request)

    print("Trace:")
    for line in result.trace:
        print(f"  {line}")
    if not result.ok:
        print(f"\nStopped: {result.error}")
        return
    print(f"\nReport: {result.report.path or '(not written)'}")
    print(f"Matches: {len(result.findings.items)}")


if __name__ == "__main__":
    main()
