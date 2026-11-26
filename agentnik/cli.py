"""Dispatch desktop and terminal entry points without importing Qt for Code."""

import argparse
from collections import deque
from getpass import GetPassWarning, getpass
from pathlib import Path
import sqlite3
import sys
import warnings


def connection_menu(data_dir, add=False):
    from .core import PROTOCOLS, environment_connections, validate_connections
    from .storage import ConfigurationError, Store

    try:
        store = Store(data_dir)
    except (ConfigurationError, OSError) as exc:
        print(exc, file=sys.stderr)
        return
    try:
        if not add:
            saved = store.config["connections"]
            for label, entries in (("Saved", saved), ("Environment", environment_connections())):
                for name, entry in entries.items():
                    print(f"{label}: {name!r} · {entry.get('model', '')!r}")
            return
        name = input("Connection name: ").strip()
        if not name or name in store.config["connections"]:
            print("Choose a new, nonempty connection name.")
            return
        url = input("Endpoint URL: ").strip()
        protocol = input(f"Protocol ({', '.join(PROTOCOLS)}) [chat]: ").strip() or "chat"
        model = input("Model: ").strip()
        connection = validate_connections({"connections": {
            name: {"url": url, "protocol": protocol, "model": model},
        }})[name]
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            connection["api_key"] = getpass("API key (blank for none): ")
        try:
            store.save_connection(name, connection)
        except Exception:
            print("Could not save the connection. Check storage and credential store availability.",
                  file=sys.stderr)
        else:
            print(f"Saved connection {name!r}.")
    except (ValueError, EOFError, KeyboardInterrupt, GetPassWarning):
        print("Connection setup cancelled or invalid.")
    finally:
        store.db.close()


def main():
    args = sys.argv[1:]
    if args[:1] != ["code"]:
        from .ui import main as desktop_main

        return desktop_main()

    parser = argparse.ArgumentParser(prog="agentnik code")
    parser.add_argument("--data-dir", type=Path, help="Override the application data directory")
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
    print("Select a connection with /connection NAME, then enter a task. Type /help.")
    from .code_composer import create_composer

    transcript = deque(maxlen=2048)

    def write_activity(text="", *, end="\n", flush=False):
        transcript.append(text + end)
        print(text, end=end, flush=flush)

    try:
        composer = create_composer(transcript=lambda: "".join(transcript))
    except ModuleNotFoundError as exc:
        if exc.name != "prompt_toolkit":
            raise
        composer = None
        print("Install agentnik[terminal] for multiline editing and prompt recall.")
    else:
        print("Enter adds a line. Alt+Enter submits. Use Up/Down to recall input and Tab for commands.")
        print("Ctrl+T or PageUp opens the transcript.")
    connection_name = model = ""
    context = None
    while True:
        try:
            command = (composer.prompt() if composer else input("code> ")).strip()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            return 0
        if command == "/exit":
            return 0
        if command == "/help":
            print("/status           Show the project folder\n"
                  "/connections      List saved and environment connections\n"
                  "/connections add  Configure a new connection\n"
                  "/connection NAME  Select a connection for this session\n"
                  "/model NAME       Override the connection model\n"
                  "/history          List saved turns for the current project\n"
                  "/open ID          Open a saved turn and select its context\n"
                  "/exit             Close Agentnik Code")
        elif command == "/status":
            print(f"Project: {str(root)!r} · Connection: {connection_name or '(none)'!r}"
                  f" · Model: {model or '(connection default)'!r}")
        elif command in ("/connections", "/connections add"):
            connection_menu(options.data_dir, command.endswith(" add"))
        elif command == "/history" or command.startswith("/open "):
            from .code_history import CodeHistory, Store
            from .code_terminal import terminal_text

            try:
                store = Store(options.data_dir)
                try:
                    records = CodeHistory(store, root).list()
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            if command == "/history":
                for record in records[:20]:
                    print(terminal_text(f"{record['id']}  {record.get('code_state', 'idle')}  {record['title']}"))
                if not records:
                    print("No saved turns for this project.")
                continue
            ident = command.removeprefix("/open ").strip()
            record = next((item for item in records if item["id"] == ident), None)
            if record is None:
                print("No saved turn with that ID in this project.")
                continue
            for entry in record.get("code_activity", [])[-20:]:
                write_activity(terminal_text(entry["text"]))
            context = record.get("coding_context") if record.get("code_state") == "completed" else None
            binding = record.get("coding_models", {}).get("model", {})
            connection_name = binding.get("connection", "")
            model = binding.get("model", "")
            print("Opened saved turn. Enter a new task when ready. Nothing was restarted.")
        elif command.startswith("/connection "):
            connection_name = command.removeprefix("/connection ").strip()
            model = ""
            context = None
        elif command == "/model" or command.startswith("/model "):
            model = command[6:].strip()
        elif command.startswith("/"):
            print("Unknown command. Type /help.")
        elif command:
            if not connection_name:
                print("Select a connection with /connection NAME first.")
                continue
            from .code_agent import CodingRun
            from .code_history import CodeHistory, Store
            from .code_terminal import drive_run, load_run_settings, terminal_text

            try:
                connection, limits = load_run_settings(options.data_dir, connection_name, model)
                run = CodingRun(connection, root, command, context=context, limits=limits)
                run.stream_activity = True
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            transcript.append("Task: " + terminal_text(
                command.replace(connection.get("api_key") or "\0", "[redacted]")
            ) + "\n")
            try:
                store = Store(options.data_dir)
                try:
                    history = CodeHistory(store, root)
                    record, task = history.start(connection_name, connection, command)
                    result = drive_run(run, write_activity)
                    history.finish(record, task, result)
                    context = record.get("coding_context")
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
