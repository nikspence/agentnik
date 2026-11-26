"""Dispatch desktop and terminal entry points without importing Qt for Code."""

import argparse
from pathlib import Path
import sys


def main():
    args = sys.argv[1:]
    if args[:1] != ["code"]:
        from .ui import main as desktop_main

        return desktop_main()

    parser = argparse.ArgumentParser(prog="agentnik code")
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                        help="Project folder (default: current directory)")
    options = parser.parse_args(args[1:])
    try:
        root = options.project.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
    if not root.is_dir():
        parser.error("project must be a directory")

    if not sys.stdin.isatty():
        parser.error("an interactive terminal is required")
    print(f"Agentnik Code preview · {str(root)!r}")
    print("Project selection preview. Model runs are not available yet. Type /help.")
    while True:
        try:
            command = input("code> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if command == "/exit":
            return 0
        if command == "/help":
            print("/status  Show the project folder\n/exit    Close Agentnik Code")
        elif command == "/status":
            print(f"Project: {str(root)!r}")
        elif command:
            print("Command unavailable in this preview. Type /help.")


if __name__ == "__main__":
    raise SystemExit(main())
