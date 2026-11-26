"""Dispatch desktop and terminal entry points without importing Qt for Code."""

import argparse
from getpass import GetPassWarning, getpass
from pathlib import Path
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
    connection_name = model = ""
    while True:
        try:
            command = input("code> ").strip()
        except (EOFError, KeyboardInterrupt):
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
                  "/exit             Close Agentnik Code")
        elif command == "/status":
            print(f"Project: {str(root)!r} · Connection: {connection_name or '(none)'!r}"
                  f" · Model: {model or '(connection default)'!r}")
        elif command in ("/connections", "/connections add"):
            connection_menu(options.data_dir, command.endswith(" add"))
        elif command.startswith("/connection "):
            connection_name = command.removeprefix("/connection ").strip()
            model = ""
        elif command == "/model" or command.startswith("/model "):
            model = command[6:].strip()
        elif command.startswith("/"):
            print("Unknown command. Type /help.")
        elif command:
            if not connection_name:
                print("Select a connection with /connection NAME first.")
                continue
            from .code_agent import CodingRun
            from .code_terminal import drive_run, load_run_settings, terminal_text

            try:
                connection, limits = load_run_settings(options.data_dir, connection_name, model)
                run = CodingRun(connection, root, command, limits=limits)
                run.stream_activity = True
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            drive_run(run)


if __name__ == "__main__":
    raise SystemExit(main())
