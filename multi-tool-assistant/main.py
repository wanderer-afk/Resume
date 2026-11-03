"""Command-line and web entry point.

  python main.py              chat in the terminal
  python main.py --web        start the web UI on http://127.0.0.1:8000

Set ANTHROPIC_API_KEY to let Claude choose tools. Without it, a rule-based offline
planner handles the fixed patterns listed in the README.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from assistant import (
    Agent, AnthropicPlanner, DestinationService, RulePlanner, TaskStore, UserProfile,
    WeatherService, build_registry,
)
from assistant.web import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.environ.get("ASSISTANT_DATA_DIR", "data"))
    parser.add_argument("--trace", action="store_true", help="print each tool call the agent made (terminal mode)")
    parser.add_argument("--offline", action="store_true", help="use the rule planner even if a key is set")
    parser.add_argument("--web", action="store_true", help="start the web UI instead of the terminal chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    data = Path(args.data_dir)
    profile_path = data / "profile.json"
    profile = UserProfile.load(profile_path)
    tools = build_registry(
        WeatherService(), DestinationService(), TaskStore(data / "tasks.json"), profile, str(profile_path),
    )

    use_claude = bool(os.environ.get("ANTHROPIC_API_KEY")) and not args.offline
    planner = AnthropicPlanner(profile) if use_claude else RulePlanner(profile)
    agent = Agent(planner, tools)
    mode = f"Claude ({planner.model})" if use_claude else "offline rule planner"

    if args.web:
        server = serve(agent, args.host, args.port)
        print(f"Serving on http://{args.host}:{server.server_address[1]} using {mode}. Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
        finally:
            server.server_close()
        return

    print(f"Using {mode}. Type 'quit' to exit.")
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
        try:
            result = agent.run(text)
        except Exception as exc:  # keep the chat alive if one request fails
            print(f"Something went wrong: {exc}")
            continue
        print(result.reply)
        if args.trace:
            for line in result.trace:
                print(f"  [{line}]")


if __name__ == "__main__":
    main()
