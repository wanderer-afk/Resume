"""Command-line entry point. Type a request, or 'quit' to exit.

Set ANTHROPIC_API_KEY to let Claude choose tools. Without it, a simple offline
planner handles 'weather in <city>', 'add task <title>', 'list tasks' and 'complete task <id>'.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from assistant import Agent, AnthropicPlanner, RulePlanner, TaskStore, WeatherService, build_registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks-file", default=os.environ.get("TASKS_FILE", "data/tasks.json"))
    parser.add_argument("--trace", action="store_true", help="print each tool call the agent made")
    parser.add_argument("--offline", action="store_true", help="use the rule planner even if a key is set")
    args = parser.parse_args()

    tools = build_registry(WeatherService(), TaskStore(Path(args.tasks_file)))
    if os.environ.get("ANTHROPIC_API_KEY") and not args.offline:
        planner = AnthropicPlanner()
        print(f"Using {planner.model}. Type 'quit' to exit.")
    else:
        planner = RulePlanner()
        print("Offline mode (no ANTHROPIC_API_KEY). Type 'quit' to exit.")

    agent = Agent(planner, tools)
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            break
        result = agent.run(text)
        print(result.reply)
        if args.trace:
            for line in result.trace:
                print(f"  [{line}]")


if __name__ == "__main__":
    main()
