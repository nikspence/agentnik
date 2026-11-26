"""Dispatch desktop and terminal entry points without importing Qt for Code."""

import argparse
from collections import deque
from getpass import GetPassWarning, getpass
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
import warnings


def connection_menu(data_dir, action="", selected_name=""):
    from .core import PROTOCOLS, environment_connections, validate_connections
    from .storage import ConfigurationError, Store

    try:
        store = Store(data_dir)
    except (ConfigurationError, OSError, sqlite3.Error) as exc:
        print(exc, file=sys.stderr)
        return
    try:
        if not action:
            saved = store.config["connections"]
            for label, entries in (("Saved", saved), ("Environment", environment_connections())):
                for name, entry in entries.items():
                    print(f"{label}: {name!r} · {entry.get('model', '')!r}")
            return
        name = selected_name or input("Connection name: ").strip()
        old = store.config["connections"].get(name)
        if action == "add":
            if not name or old is not None:
                print("Choose a new, nonempty connection name.")
                return
        elif old is None:
            print("Choose an existing saved connection.")
            return
        if action == "remove":
            if input(f"Remove saved connection {name!r}? [y/N] ").strip().lower() == "y":
                store.delete_connection(name)
                print("Removed saved connection.")
            return
        previous = old or {}
        connection = dict(previous)
        if action in ("add", "edit"):
            for field, label, default in (
                ("url", "Endpoint URL", ""),
                ("protocol", f"Protocol ({', '.join(PROTOCOLS)})", "chat"),
                ("model", "Model", ""),
            ):
                current = previous.get(field, default)
                connection[field] = input(f"{label} [{current!r}]: ").strip() or current
        if action == "options":
            for field, label in (
                ("reasoning", "Reasoning effort"),
                ("service_tier", "Service tier (auto/default/flex/priority/fast/ultrafast/scale)"),
            ):
                value = input(f"{label} [{previous.get(field, '')!r}] (none clears): ").strip()
                if value:
                    connection[field] = "" if value == "none" else value
            value = input(f"Context tokens [{previous.get('context_limit', 0)}] (0 for unknown): ").strip()
            if value:
                try:
                    limit = int(value)
                except ValueError:
                    raise ValueError("Context tokens must be a whole number.") from None
                if not 0 <= limit <= 100_000_000:
                    raise ValueError("Context tokens must be between 0 and 100000000.")
                connection["context_limit"] = limit
            streaming = "on" if previous.get("stream", True) else "off"
            value = input(f"Streaming (on/off) [{streaming}]: ").strip().lower()
            if value:
                if value not in ("on", "off"):
                    raise ValueError("Streaming must be on or off.")
                connection["stream"] = value == "on"
        connection = validate_connections({"connections": {
            name: connection,
        }})[name]
        if action in ("edit", "options"):
            store.update_connection_settings(name, connection)
            print(f"Saved connection {name!r}.")
            return
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            key = getpass("API key (blank for none): ")
        if action == "key" and not key:
            if input("Clear the saved credential? [y/N] ").strip().lower() != "y":
                return
        connection["api_key"] = key
        plaintext = bool(key) and input(
            "Store API key as plaintext on this machine? [y/N, default: credential store] "
        ).strip().lower() == "y"
        try:
            store.save_connection(name, connection, plaintext=plaintext)
        except Exception:
            print("Could not save the connection. Check storage and credential store availability.",
                  file=sys.stderr)
        else:
            print(f"Saved connection {name!r}.")
    except ValueError as exc:
        from .code_terminal import terminal_text

        print(terminal_text(exc), file=sys.stderr)
    except (OSError, sqlite3.Error):
        print("Could not update the saved connection.", file=sys.stderr)
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("Connection setup cancelled or invalid.")
    finally:
        store.db.close()


def desktop_main():
    try:
        from .ui import main as launch
    except ModuleNotFoundError as exc:
        if exc.name != "PySide6":
            raise
        print('Desktop support requires PySide6. Install "agentnik[desktop]" or run agentnik code.',
              file=sys.stderr)
        return 1
    return launch()


def main():
    args = sys.argv[1:]
    if args[:1] != ["code"]:
        return desktop_main()

    parser = argparse.ArgumentParser(prog="agentnik code")
    parser.add_argument("--data-dir", type=Path, help="Override the application data directory")
    parser.add_argument("--resume", nargs="?", const="latest", metavar="ID",
                        help="Resume a session in this project (default: latest)")
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
    from .code_lease import SessionLease

    with SessionLease(options.data_dir) as lease:
        return terminal_session(options, root, lease)


def terminal_session(options, root, lease):
    print(f"Agentnik Code preview · {str(root)!r}")
    print("Select a connection with /connection NAME, then enter a task. Type /help.")
    from .code_composer import create_composer

    transcript = deque(maxlen=2048)

    def write_activity(text="", *, end="\n", flush=False):
        transcript.append(text + end)
        print(text, end=end, flush=flush)

    def open_composer():
        return create_composer(transcript=lambda: "".join(transcript))

    try:
        composer = open_composer()
    except ModuleNotFoundError as exc:
        if exc.name != "prompt_toolkit":
            raise
        composer = None
        print("Install agentnik[terminal] for multiline editing and prompt recall.")
    else:
        print("Enter adds a line. Alt+Enter submits. Use Up/Down to recall input and Tab for commands.")
        print("Ctrl+T or PageUp opens the transcript.")
    connection_name = model = ""
    discovered = {}
    context = None
    use_context = True
    last_record = None
    web_enabled = False
    vision_enabled = False
    show_thinking = False
    skill_pins = {}
    documents = []
    require_approval = True
    session_id = str(uuid4())
    pending_command = f"/resume {options.resume}" if options.resume else None
    while True:
        try:
            if pending_command:
                command, pending_command = pending_command, None
            else:
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
                  "/diff [--staged] PATH  Review a file against HEAD\n"
                  "/connections      List saved and environment connections\n"
                  "/connections add|edit|options|key|remove [NAME]\n"
                  "/connections discover  Look for supported services on this machine\n"
                  "/connection NAME  Select a connection for this session\n"
                  "/model NAME       Override the connection model\n"
                  "/models [FILTER]  Fetch the selected connection's catalog and choose a model\n"
                  "/goal OBJECTIVE   Start an ongoing goal in this session\n"
                  "/continue         Continue the last stopped goal with fresh limits\n"
                  "/context          Inspect, clear, or toggle previous-turn context\n"
                  "/attach PATH      Include a project document in the next task\n"
                  "/attachments      List queued documents; /attachments clear removes them\n"
                  "/web on|off       Enable or disable web research for this session\n"
                  "/vision on|off    Allow the coding model to inspect project images\n"
                  "/thinking on|off  Show model-provided thinking when available\n"
                  "/skills           List, preview or select project and user skills\n"
                  "/permissions      Set project and shell approval for this session\n"
                  "/settings         Manage coding limits, TLS and desktop appearance\n"
                  "/history          Show history for this session\n"
                  "/new              Start a fresh session in this project\n"
                  "/sessions         List saved sessions for the current project\n"
                  "/resume ID        Resume a saved session (or use latest)\n"
                  "/exit             Close Agentnik Code")
        elif command == "/attachments" or command == "/attachments clear":
            if command.endswith(" clear"):
                documents.clear()
                print("Cleared queued documents.")
            else:
                print(", ".join(repr(item["name"]) for item in documents) or "No queued documents.")
        elif command.startswith("/attach "):
            from xml.etree.ElementTree import ParseError
            from zipfile import BadZipFile
            from .code_agent import ProjectFiles
            from .code_terminal import terminal_text
            from .document_reader import read_document, validate_documents

            try:
                if len(documents) >= 4:
                    raise ValueError("Attach up to four documents per prompt.")
                path = ProjectFiles(root).path(command.partition(" ")[2].strip())
                if path.suffix.lower() == ".pdf":
                    raise ValueError("PDF extraction is available in the desktop app. Attach a text export here.")
                document = {"name": path.name, "text": read_document(path)}
                documents = validate_documents([*documents, document])
                print(f"Queued {path.name!r}. Its extracted text will be sent with the next task.")
            except (OSError, ValueError, KeyError, IndexError, ParseError, BadZipFile) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command == "/context" or command.startswith("/context "):
            from .code_terminal import terminal_text

            action = command.partition(" ")[2].strip()
            if action == "clear":
                context = None
                print("Cleared context for the next turn. Saved history remains available.")
            elif action in ("on", "off"):
                use_context = action == "on"
                print(f"Previous-turn context {'enabled' if use_context else 'disabled'} for this session.")
            elif not action:
                print(f"Previous-turn context: {'on' if use_context else 'off'}.")
                if context:
                    print(terminal_text(f"Task:\n{context['task']}\n\nAnswer:\n{context['answer']}"))
                else:
                    print("No previous-turn context is available.")
                print("Use /context on, /context off, or /context clear.")
            else:
                print("Use /context to see available actions.")
        elif command == "/diff" or command.startswith("/diff "):
            from .code_terminal import project_diff, terminal_text

            try:
                print(terminal_text(project_diff(root, command.partition(" ")[2].strip())))
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
            except KeyError:
                print("Git diff unavailable. The repository may not have an initial commit.", file=sys.stderr)
        elif command == "/status":
            print(f"Project: {str(root)!r} · Session: {session_id} · Connection: {connection_name or '(none)'!r}"
                  f" · Model: {model or '(connection default)'!r} · Web: {'on' if web_enabled else 'off'}"
                  f" · Vision: {'on' if vision_enabled else 'off'}"
                  f" · Thinking: {'on' if show_thinking else 'off'}"
                  f" · Permissions: {'require' if require_approval else 'allow-all'}")
        elif command == "/permissions" or command.startswith("/permissions "):
            mode = command.partition(" ")[2].strip()
            if not mode:
                current = "require" if require_approval else "allow-all"
                print(f"Current mode: {current}. Applies to project edits and shell commands.")
                try:
                    mode = input("Choose require or allow-all [Enter to keep]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                if not mode:
                    continue
            if mode not in ("require", "allow-all"):
                print("Use /permissions require or /permissions allow-all.")
                continue
            require_approval = mode == "require"
            print("Project edits and shell commands require approval for this session."
                  if require_approval else
                  "Project edits and shell commands will run without approval for this session.")
        elif command in ("/web on", "/web off"):
            web_enabled = command.endswith(" on")
            print("Web research enabled for next task. Queries may go to configured or fallback services."
                  if web_enabled else "Web research disabled.")
        elif command in ("/thinking on", "/thinking off"):
            show_thinking = command.endswith(" on")
            print("Model-provided thinking will be shown when available." if show_thinking
                  else "Model-provided thinking hidden.")
        elif command in ("/vision on", "/vision off"):
            if command == "/vision on":
                from importlib.util import find_spec

                if find_spec("PySide6") is None and find_spec("PIL") is None:
                    print("Install the Agentnik terminal extra for headless image inspection.")
                    continue
            vision_enabled = command == "/vision on"
            print("Image inspection enabled. Requested project images may be sent to the selected model."
                  if vision_enabled else "Image inspection disabled.")
        elif command == "/skills" or command.startswith("/skills "):
            from .code_agent import ProjectFiles
            from .code_terminal import terminal_text
            from .project_skills import list_skills, read_skill

            action, _, ident = command.partition(" ")[2].partition(" ")
            ident = ident.strip()
            try:
                files = ProjectFiles(root)
                if not action:
                    for skill in list_skills(files):
                        name = skill["id"]
                        marker = "*" if name in skill_pins else " "
                        print(terminal_text(f"{marker} {name} — {skill['description']}"))
                    print("Use /skills show ID, /skills add ID, or /skills remove ID.")
                elif action in ("show", "add") and ident:
                    skill = read_skill(files, ident)
                    if action == "show":
                        print(terminal_text(skill["instructions"]))
                    elif len(skill_pins) >= 5 and ident not in skill_pins:
                        print("Select at most five skills.")
                    else:
                        skill_pins[ident] = skill["sha256"]
                        print("Selected this revision. Its instructions will be sent to the coding model.")
                elif action == "remove" and ident:
                    skill_pins.pop(ident, None)
                    print("Skill removed from this session.")
                else:
                    print("Use /skills to see available actions.")
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command == "/new":
            lease.close()
            session_id = str(uuid4())
            context = None
            use_context = True
            last_record = None
            web_enabled = False
            vision_enabled = False
            show_thinking = False
            skill_pins = {}
            documents.clear()
            require_approval = True
            transcript.clear()
            if composer:
                composer = open_composer()
            print(f"Started session {session_id}. Previous sessions are available under /sessions.")
        elif command == "/connections discover":
            from .core import discover
            from .code_terminal import terminal_text

            print("Checking known local model service ports…", flush=True)
            try:
                discovered = discover()
            except KeyboardInterrupt:
                print("\nDiscovery cancelled.")
                continue
            for name, connection in discovered.items():
                print(terminal_text(f"{name} · {connection.get('model', '') or '(model not listed)'}"))
            print("Select a discovered name with /connection NAME." if discovered
                  else "No local model services were found.")
        elif command == "/connections" or command.startswith("/connections "):
            _, _, operation = command.partition(" ")
            action, _, name = operation.strip().partition(" ")
            if action not in ("", "add", "edit", "options", "key", "remove"):
                print("Use /connections, or /connections add|edit|options|key|remove [NAME].")
                continue
            connection_menu(options.data_dir, action, name.strip())
            if not action:
                for label, entry in discovered.items():
                    print(f"Discovered: {label!r} · {entry.get('model', '')!r}")
        elif command == "/settings" or command.startswith("/settings "):
            from .code_settings import configure_code
            from .code_terminal import terminal_text
            from .storage import Store

            try:
                store = Store(options.data_dir)
                try:
                    print(configure_code(store, command.split()[1:]))
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command in ("/history", "/sessions", "/resume") or command.startswith(("/open ", "/resume ")):
            from .code_history import CodeHistory, Store
            from .code_terminal import terminal_text

            try:
                store = Store(options.data_dir)
                try:
                    history = CodeHistory(store, root)
                    sessions = history.sessions() if command != "/history" else {}
                    ident = command.partition(" ")[2].strip()
                    if ident == "latest":
                        ident = next(iter(sessions), "")
                    if ident in sessions and command not in ("/history", "/sessions", "/resume"):
                        lease.select(ident)
                    records = history.list(session_id if command == "/history" else ident)
                    if records and command not in ("/history", "/sessions", "/resume"):
                        history.recover_interrupted(records[0], lease)
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            if command in ("/sessions", "/resume"):
                for ident, record in list(sessions.items())[:20]:
                    label = next((e["text"].split("\n")[0][:80] for e in record.get("code_activity", [])
                                  if e["kind"] == "prompt"), record["title"])
                    print(terminal_text(f"{ident}  {record.get('code_state', 'idle')}  {label}"))
                if not sessions:
                    print("No saved sessions for this project.")
                continue
            if not records:
                print("No saved history for this session." if command == "/history"
                      else "No saved session with that ID in this project.")
                continue
            if command != "/history":
                session_id = ident
                use_context = True
                web_enabled = False
                vision_enabled = False
                show_thinking = False
                require_approval = True
                documents.clear()
                transcript.clear()
                if composer:
                    composer = open_composer()
            for saved in reversed(records[:20]):
                for entry in saved.get("code_activity", [])[-20:]:
                    line = terminal_text(entry["text"])
                    if command == "/history":
                        print(line)
                    else:
                        write_activity(line)
                        if composer and entry["kind"] == "prompt":
                            composer.history.append_string(line)
            if command == "/history":
                continue
            record = records[0]
            last_record = record
            skill_pins = dict(record.get("coding_skill_pins", {}))
            context = record.get("coding_context") if record.get("code_state") == "completed" else None
            binding = record.get("coding_models", {}).get("model", {})
            connection_name = binding.get("connection", "")
            model = binding.get("model", "")
            print(f"Resumed session {session_id}. Enter a new task when ready. Nothing was restarted.")
        elif command.startswith("/connection "):
            connection_name = command.removeprefix("/connection ").strip()
            model = ""
            context = None
            last_record = None
            vision_enabled = False
        elif command == "/models" or command.startswith("/models "):
            from .code_terminal import choose_catalog_model, terminal_text

            try:
                selected = choose_catalog_model(options.data_dir, connection_name, command.partition(" ")[2].strip(),
                                                discovered=discovered)
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            if selected is not None:
                model = selected
                vision_enabled = False
                print(f"Selected model {model!r}. Catalog entries do not establish tool or vision support.")
        elif command == "/model" or command.startswith("/model "):
            model = command[6:].strip()
            vision_enabled = False
        elif command == "/goal":
            print("Enter /goal followed by an objective.")
        elif command.startswith("/") and command != "/continue" and not command.startswith("/goal "):
            print("Unknown command. Type /help.")
        elif command:
            if not connection_name:
                print("Select a connection with /connection NAME first.")
                continue
            from .code_agent import CodingRun
            from .code_history import CodeHistory, Store, goal_continuation
            from .code_terminal import drive_run, load_run_settings, terminal_text

            continuing = command == "/continue"
            goal = continuing or command.startswith("/goal ")
            resume = goal_continuation(last_record) if continuing else None
            if continuing:
                if resume is None:
                    print("No stopped goal is available to continue in this session.")
                    continue
                print(terminal_text(resume["task"]))
                try:
                    if input("Continue this goal with fresh limits? [y/N] ").strip().lower() != "y":
                        continue
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                command = "Continue the saved objective. Inspect current state first and do not repeat uncertain actions."
            elif goal:
                command = command.removeprefix("/goal ").strip()
            try:
                connection, limits, goal_budget, research_options, advice = load_run_settings(
                    options.data_dir, connection_name, model, web_enabled, discovered=discovered
                )
                run = CodingRun(connection, root, command, context=context if use_context and not resume else None,
                                limits=limits,
                                goal=goal, goal_budget=goal_budget, vision_enabled=vision_enabled,
                                resume_context=resume,
                                documents=documents,
                                skills=list(skill_pins), skill_pins=skill_pins,
                                **research_options)
                run.stream_activity = True
                run.show_thinking = show_thinking
                run.review_project_edits = require_approval
                run.set_shell_without_approval(not require_approval)
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                continue
            try:
                store = Store(options.data_dir)
                try:
                    lease.select(session_id)
                    history = CodeHistory(store, root)
                    record, task = history.start(
                        connection_name, connection, resume["task"] if resume else command, session_id, goal=goal,
                        skill_pins=skill_pins,
                        extra_secrets=[
                            *(item.get("key") for item in research_options["web_backends"]),
                            research_options.get("image_config", {}).get("connection", {}).get("api_key"),
                            (advice or {}).get("api_key"),
                        ],
                    )
                    transcript.append("Task: " + terminal_text(task) + "\n")
                    documents.clear()
                    result = drive_run(run, write_activity, advice=advice,
                                       checkpoint=lambda event: history.checkpoint_goal(record, event))
                    history.finish(record, task, result)
                    last_record = record
                    context = record.get("coding_context")
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
