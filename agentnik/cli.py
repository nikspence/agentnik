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
            from keyring.errors import KeyringError

            try:
                store.save_connection(name, connection, plaintext=plaintext)
            except KeyringError:
                if not key or plaintext:
                    raise
                if input("Credential store unavailable. Save the API key in the local config "
                         "without encryption? [y/N] ").strip().lower() != "y":
                    print("Connection not saved.")
                    return
                store.save_connection(name, connection, plaintext=True)
        except (EOFError, KeyboardInterrupt):
            raise
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

    from . import __version__

    parser = argparse.ArgumentParser(prog="agentnik code")
    parser.add_argument("--version", action="version", version=f"Agentnik Code {__version__}")
    parser.add_argument("--data-dir", type=Path, help="Override the application data directory")
    parser.add_argument("--resume", nargs="?", const="latest", metavar="ID",
                        help="Resume a session in this project (default: latest)")
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                        help="Project folder (default: current directory)")
    options = parser.parse_args(args[1:])
    if options.resume is not None and not options.resume.strip():
        parser.error("--resume needs a session ID, unique prefix, or latest")
    try:
        root = options.project.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
    if not root.is_dir():
        parser.error("project must be a directory")

    if not sys.stdin.isatty():
        parser.error("an interactive terminal is required")
    from .code_lease import SessionLease
    from .code_attachments import ImageQueue
    from .storage import default_home

    try:
        options.data_dir = (options.data_dir or default_home()).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        parser.error(f"cannot resolve the application data directory: {exc}")
    if options.data_dir.exists() and not options.data_dir.is_dir():
        parser.error("application data path must be a directory")

    with SessionLease(options.data_dir) as lease, ImageQueue() as images:
        return terminal_session(options, root, lease, images)


def terminal_session(options, root, lease, images):
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
        print("Enter submits. Ctrl+Enter (where supported) or Ctrl+J adds a line. "
              "Use Up/Down to recall input and Tab for commands.")
        print("Ctrl+T or PageUp opens the transcript.")
    connection_name = model = ""
    discovered = {}
    mcp_selection = []
    context = None
    use_context = True
    last_record = None
    web_enabled = False
    vision_enabled = False
    memory_enabled = False
    show_thinking = False
    skill_pins = {}
    documents = []
    require_approval = True
    machine_scope = False
    session_id = str(uuid4())
    pending_command = f"/resume {options.resume}" if options.resume else None
    while True:
        starting_resume = pending_command is not None
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
                  "/git              Run manual Git status, diff, stage, unstage, commit, or push\n"
                  "/connections      List saved and environment connections\n"
                  "/connections add|edit|options|key|remove [NAME]\n"
                  "/connections discover  Look for supported services on this machine\n"
                  "/connection NAME  Select a connection for this session\n"
                  "/model [NAME]     Override the model, or reset to the connection default\n"
                  "/models [FILTER]  Fetch the selected connection's catalog and choose a model\n"
                  "/goal [OBJECTIVE] Show the saved goal or start an ongoing goal\n"
                  "/continue         Continue the last stopped goal with fresh limits\n"
                  "/context          Inspect, clear, or toggle previous-turn context\n"
                  "/plan             Show the latest saved plan for this session\n"
                  "/memory           List local project memory; show ID, on, or off\n"
                  "/attach PATH      Include a project image or document in the next task\n"
                  "/attachments      List queued files; remove NUMBER or clear\n"
                  "/web on|off       Enable or disable web research for this session\n"
                  "/vision [on|off]  Show or change model image inspection for this session\n"
                  "/thinking on|off  Show model-provided thinking when available\n"
                  "/skills           List, preview or select project and user skills\n"
                  "/mcp              List or select MCP servers for this session\n"
                  "/permissions      Set project and shell approval for this session\n"
                  "/scope [MODE]     Show or set project or machine file scope\n"
                  "/settings         Manage coding limits, TLS and desktop appearance\n"
                  "/history [PAGE]   Show saved turns for this session\n"
                  "/new              Start a fresh session in this project\n"
                  "/sessions [PAGE]  List saved sessions for the current project\n"
                  "/resume ID        Resume by ID, unique prefix, or latest\n"
                  "/exit             Close Agentnik Code")
        elif command == "/mcp off":
            mcp_selection.clear()
            print("MCP disabled in this session.")
        elif command.startswith("/mcp remove "):
            name = command.removeprefix("/mcp remove ").strip()
            mcp_selection = [profile for profile in mcp_selection if profile["name"] != name]
            print("Updated the session’s MCP selection.")
        elif command == "/mcp" or command.startswith(("/mcp use ", "/mcp add ")):
            from .code_terminal import terminal_mcp_profiles, terminal_text

            try:
                profiles = terminal_mcp_profiles(options.data_dir)
                if command == "/mcp":
                    for index, profile in enumerate(mcp_selection, 1):
                        print(terminal_text(f"Selected {index}: {profile['name']}"))
                    for profile in profiles:
                        print(terminal_text(f"Available: {profile['name']}"))
                    print("Use /mcp use NAME to replace the selection, /mcp add NAME, /mcp remove NAME, or /mcp off.")
                else:
                    action, _, name = command.removeprefix("/mcp ").partition(" ")
                    name = name.strip()
                    selected = next((profile for profile in profiles if profile["name"] == name), None)
                    if selected is None:
                        raise ValueError("Choose an enabled local or HTTPS MCP server.")
                    if action == "use":
                        mcp_selection = [selected]
                    else:
                        existing = [profile for profile in mcp_selection if profile["name"] != name]
                        if len(existing) >= 5:
                            raise ValueError("Select at most five MCP servers.")
                        if len(existing) < len(mcp_selection):
                            mcp_selection = [selected if profile["name"] == name else profile for profile in mcp_selection]
                        else:
                            mcp_selection.append(selected)
                    print("Selected MCP server. Terminal Code will ask before connecting or calling a tool.")
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command == "/attachments" or command.startswith("/attachments "):
            from .code_terminal import terminal_text

            if command == "/attachments clear":
                documents.clear()
                images.clear()
                print("Cleared queued attachments.")
            elif command == "/attachments":
                names = [item["name"] for item in documents] + images.names()
                print("\n".join(f"{index}. {terminal_text(name)!r}" for index, name in enumerate(names, 1))
                      or "No queued attachments.")
            else:
                parts = command.split()
                if len(parts) != 3 or parts[1] != "remove" or parts[2] not in "12345678" or len(parts[2]) != 1:
                    print("Use /attachments remove NUMBER or /attachments clear.")
                    continue
                index = int(parts[2]) - 1
                if index >= len(documents) + len(images.names()):
                    print("No queued attachment with that number. Use /attachments to see the queue.")
                    continue
                try:
                    name = documents.pop(index)["name"] if index < len(documents) else images.remove(index - len(documents))
                except OSError:
                    print("Could not remove the queued image.", file=sys.stderr)
                    continue
                print(f"Removed queued attachment {terminal_text(name)!r}.")
        elif command.startswith("/attach "):
            from xml.etree.ElementTree import ParseError
            from zipfile import BadZipFile
            from .code_attachments import IMAGE_SUFFIXES, project_attachment_path
            from .code_terminal import terminal_text
            from .document_reader import read_document, validate_documents

            try:
                path = project_attachment_path(root, command.partition(" ")[2].strip())
                if path.suffix.lower() in IMAGE_SUFFIXES:
                    if not vision_enabled:
                        raise ValueError("Use /vision on with a vision-capable model before attaching images.")
                    images.add(path)
                    print(f"Queued {path.name!r}. The image will be sent with the next task.")
                    continue
                if len(documents) >= 4:
                    raise ValueError("Attach up to four documents per prompt.")
                document = {"name": path.name, "text": read_document(path, headless=True)}
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
        elif command in ("/memory on", "/memory off"):
            memory_enabled = command == "/memory on"
            print("Project memory enabled for model reads. Requested entries may go to the coding model."
                  if memory_enabled else "Project memory disabled for the coding model.")
        elif command == "/memory" or command.startswith("/memory "):
            from .code_terminal import terminal_project_memory, terminal_text

            try:
                print(terminal_project_memory(options.data_dir, root, command.partition(" ")[2].strip()))
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command == "/git" or command.startswith("/git "):
            from .code_git_commands import manual_git
            from .code_terminal import terminal_text

            try:
                manual_git(root, command.partition(" ")[2])
            except (EOFError, KeyboardInterrupt):
                print("Git command interrupted. Check Git state before retrying.")
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
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
            print(f"Data directory: {str(options.data_dir)!r} · Model memory reads: {'on' if memory_enabled else 'off'}"
                  f" · Scope: {'machine' if machine_scope else 'project'}")
        elif command == "/scope" or command.startswith("/scope "):
            mode = command.partition(" ")[2].strip()
            if mode in ("project", "machine"):
                selected_scope = mode == "machine"
                if machine_scope != selected_scope:
                    machine_scope = selected_scope
                    context = None
            elif mode:
                print("Use /scope project or /scope machine.")
                continue
            print(f"File scope: {'machine' if machine_scope else 'project'}. "
                  "Machine scope adds absolute-path directory listing, text reads, edits, and file creation. Approval and OS permissions are unchanged. "
                  "Shell commands are not sandboxed.")
        elif command == "/permissions" or command.startswith("/permissions "):
            mode = command.partition(" ")[2].strip()
            if not mode:
                current = "require" if require_approval else "allow-all"
                print(f"Current mode: {current}. Applies to project edits and ordinary shell commands. "
                      "MCP requests still require review.")
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
                  "Project edits and ordinary shell commands skip approval for this session. "
                  "MCP requests and shell commands that need separate review still prompt.")
        elif command in ("/web on", "/web off"):
            web_enabled = command.endswith(" on")
            print("Web research enabled for next task. Queries may go to configured or fallback services."
                  if web_enabled else "Web research disabled.")
        elif command in ("/thinking on", "/thinking off"):
            show_thinking = command.endswith(" on")
            print("Model-provided thinking will be shown when available." if show_thinking
                  else "Model-provided thinking hidden.")
        elif command == "/vision":
            print(f"Image inspection is {'on' if vision_enabled else 'off'} for this session.")
            print("Use /vision on|off for the coding model. Use /settings image for the separate generation tool.")
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
            memory_enabled = False
            mcp_selection = []
            show_thinking = False
            skill_pins = {}
            documents.clear()
            images.clear()
            require_approval = True
            machine_scope = False
            transcript.clear()
            if composer:
                composer = open_composer()
            print(f"Started session {session_id}. Sessions with a submitted task are available under /sessions.")
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
                    print(configure_code(store, command.split()[1:], root=root))
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif (command.split(" ", 1)[0] in ("/history", "/sessions", "/resume")
              or command.startswith("/open ") or command in ("/plan", "/goal")):
            from .code_history import CodeHistory, Store, activity_preview, resolve_session_id
            from .code_terminal import terminal_text

            action = command.split(" ", 1)[0]
            listing = command == "/resume" or action == "/sessions"
            current_only = action in ("/history", "/plan", "/goal")
            argument = command.partition(" ")[2].strip()
            if (listing or action == "/history") and argument and (
                    not argument.isascii() or not argument.isdecimal() or len(argument) > 9 or int(argument) < 1):
                print(f"Use {action} PAGE with a positive whole page number.")
                continue
            try:
                store = Store(options.data_dir)
                try:
                    history = CodeHistory(store, root)
                    sessions = history.sessions() if not current_only else {}
                    if not listing:
                        ident = resolve_session_id(sessions, argument)
                        if ident in sessions:
                            lease.select(ident)
                        records = history.list(session_id if current_only else ident)
                        if records and not current_only:
                            history.recover_interrupted(records[0], lease)
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                if starting_resume:
                    return 1
                continue
            if listing:
                page = int(argument or 1)
                offset = (page - 1) * 20
                for ident, record in list(sessions.items())[offset:offset + 20]:
                    label = next((e["text"].split("\n")[0][:80] for e in record.get("code_activity", [])
                                  if e["kind"] == "prompt"), record["title"])
                    print(terminal_text(f"{ident}  {record.get('code_state', 'idle')}  {label}"))
                if not sessions:
                    print("No saved sessions for this project.")
                elif offset >= len(sessions):
                    print("No saved sessions on that page.")
                elif len(sessions) > offset + 20:
                    print(f"More saved sessions are available under /sessions {page + 1}.")
                continue
            if command == "/goal":
                saved = next((record["coding_goal"] for record in records if "coding_goal" in record), None)
                if saved:
                    print(terminal_text(f"Most recent saved goal ({saved['status']}):\n{saved['objective']}"))
                    if saved.get("detail"):
                        print(terminal_text(saved["detail"]))
                else:
                    print("No saved goal for this session. Use /goal OBJECTIVE to start one.")
                continue
            if command == "/plan":
                from .code_terminal import terminal_plan

                saved = next((record["coding_plan"] for record in records if "coding_plan" in record), None)
                print(terminal_plan(saved, "Saved plan (model reported):") if saved
                      else "No saved plan for this session.")
                continue
            if action == "/history":
                page = int(argument or 1)
                offset = (page - 1) * 20
                if not records:
                    print("No saved history for this session.")
                elif offset >= len(records):
                    print("No saved turns on that page.")
                else:
                    for saved in reversed(records[offset:offset + 20]):
                        for line in activity_preview(saved):
                            print(terminal_text(line))
                    if len(records) > offset + 20:
                        print(f"More saved turns are available under /history {page + 1}.")
                continue
            if not records:
                print("No saved session with that ID in this project. Sessions are saved when a task starts.")
                if starting_resume:
                    return 1
                continue
            if command != "/history":
                session_id = ident
                use_context = True
                web_enabled = False
                vision_enabled = False
                memory_enabled = False
                mcp_selection = []
                show_thinking = False
                require_approval = True
                machine_scope = False
                documents.clear()
                images.clear()
                transcript.clear()
                if composer:
                    composer = open_composer()
                    # Keep keyboard recall independent of the shorter transcript preview.
                    prompts = []
                    for saved in records:
                        for entry in reversed(saved.get("code_activity", [])):
                            if entry["kind"] == "prompt":
                                prompt = terminal_text(entry["text"])
                                prompts.append("/" + prompt if prompt.startswith("/") else prompt)
                            if len(prompts) == 100:
                                break
                        if len(prompts) == 100:
                            break
                    for prompt in reversed(prompts):
                        composer.history.append_string(prompt)
            for saved in reversed(records[:20]):
                for line in activity_preview(saved):
                    write_activity(terminal_text(line))
            record = records[0]
            last_record = record
            skill_pins = dict(record.get("coding_skill_pins", {}))
            context = record.get("coding_context") if record.get("code_state") == "completed" else None
            from .sessions import coding_model_binding

            binding = coding_model_binding(record)
            connection_name = binding.get("connection", "")
            model = binding.get("model", "")
            if "coding_plan" in record:
                from .code_terminal import terminal_plan

                write_activity(terminal_plan(record["coding_plan"], "Saved plan (model reported):"))
            print(f"Resumed session {session_id}. Enter a new task when ready. Nothing was restarted.")
        elif command == "/connection" or command.startswith("/connection "):
            from .core import environment_connections
            from .storage import ConfigurationError, Store

            name = command.partition(" ")[2].strip()
            if not name:
                print("Use /connection NAME to select a connection, or /connections to list them.")
                continue
            try:
                store = Store(options.data_dir)
                try:
                    available = name in store.config["connections"] or name in discovered or name in environment_connections()
                finally:
                    store.db.close()
            except (ConfigurationError, OSError, sqlite3.Error):
                print("Could not read available connections.", file=sys.stderr)
                continue
            if not available:
                print("No connection with that name. Use /connections to list available connections.")
                continue
            if name != connection_name:
                connection_name = name
                model = ""
                context = None
                last_record = None
                vision_enabled = False
                memory_enabled = False
            print(f"Selected connection {name!r}.")
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
                if selected != model:
                    model = selected
                    vision_enabled = False
                    memory_enabled = False
                print(f"Selected model {model!r}. Catalog entries do not establish tool or vision support.")
        elif command == "/model" or command.startswith("/model "):
            selected = command[6:].strip()
            if selected != model:
                model = selected
                vision_enabled = False
                memory_enabled = False
            print(f"Selected model {model!r}." if model else "Using the connection's default model.")
        elif command.startswith("/") and not command.startswith(("//", "/goal ")) and command != "/continue":
            print("Unknown command. Type /help, or start with // to send a prompt that begins with /.")
        elif command:
            if command == "//":
                print("Enter a prompt after the escape slash.")
                continue
            if not connection_name:
                print("Select a connection with /connection NAME first.")
                continue
            from .code_agent import CodingRun
            from .code_history import CodeHistory, Store, goal_continuation
            from .code_terminal import drive_run, load_run_settings, remember_terminal_subagent_rejection, terminal_text

            continuing = command == "/continue"
            goal = continuing or command.startswith("/goal ")
            resume = goal_continuation(last_record) if continuing else None
            if continuing:
                if resume is None:
                    print("No stopped goal is available to continue in this session.")
                    continue
                print(terminal_text(resume["task"]))
                print(terminal_text(resume["evidence"]))
                try:
                    if input("Continue this goal with fresh limits? [y/N] ").strip().lower() != "y":
                        continue
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
                command = "Continue the saved objective. Inspect current state first and do not repeat uncertain actions."
            elif goal:
                command = command.removeprefix("/goal ").strip()
            elif command.startswith("//"):
                command = command[1:]
            try:
                if images.paths() and not vision_enabled:
                    raise ValueError("Enable /vision on or clear the queued image attachments first.")
                connection, limits, goal_budget, research_options, advice = load_run_settings(
                    options.data_dir, connection_name, model, web_enabled,
                    discovered=discovered, mcp_selection=mcp_selection, root=root, memory_enabled=memory_enabled,
                )
                run = CodingRun(connection, root, command, context=context if use_context and not resume else None,
                                limits=limits,
                                goal=goal, goal_budget=goal_budget, vision_enabled=vision_enabled,
                                resume_context=resume,
                                documents=documents,
                                images=images.paths(),
                                skills=list(skill_pins), skill_pins=skill_pins,
                                **research_options)
                run.stream_activity = True
                run.show_thinking = show_thinking
                run.review_project_edits = require_approval
                run.machine_scope = machine_scope
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
                            *(value for bridge in research_options.get("mcp_bridges", [])
                              for value in bridge.environment_values.values()),
                        ],
                    )
                    transcript.append("Task: " + terminal_text(task) + "\n")
                    documents.clear()
                    def checkpoint(event):
                        if event["kind"] == "subagent_tools_unsupported":
                            if event.get("role") == "model":
                                remember_terminal_subagent_rejection(options.data_dir, connection_name, connection)
                        else:
                            history.checkpoint(record, event)

                    try:
                        result = drive_run(run, write_activity, advice=advice, checkpoint=checkpoint)
                    finally:
                        images.clear()
                    history.finish(record, task, result, save_context=not machine_scope)
                    last_record = record
                    context = record.get("coding_context")
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
