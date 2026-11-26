"""Dispatch desktop and terminal entry points without importing Qt for Code."""

import argparse
from collections import deque
from getpass import GetPassWarning, getpass
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
import warnings


def connection_settings_path(filename):
    filename = filename.strip()
    if len(filename) >= 2 and filename[0] == filename[-1] and filename[0] in ("'", '"'):
        filename = filename[1:-1]
    return Path(filename).expanduser()


def portable_connection(settings):
    return {field: settings[field] for field in
            ("url", "protocol", "model", "reasoning", "service_tier", "context_limit", "stream")
            if field in settings}


def export_connection_settings(store, filename):
    saved = store.config["connections"]
    if not saved:
        print("No saved connections to export.")
        return
    path = connection_settings_path(filename)
    settings = {name: portable_connection(connection) for name, connection in saved.items()}
    content = json.dumps({"connections": settings}, indent=2) + "\n"
    if len(settings) > 100 or len(content.encode("utf-8")) > 1_048_576:
        raise ValueError("The saved connections exceed the portable file limit of 100 connections and 1 MiB.")
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except FileExistsError:
        raise ValueError("The export destination already exists. Choose a new file.") from None
    print(f"Exported {len(saved)} saved connection(s) without API keys.")


def import_connection_settings(store, filename):
    from .core import validate_connections

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Ambiguous connection import.")
            result[key] = value
        return result

    path = connection_settings_path(filename)
    if not path.is_file():
        raise ValueError("Choose an existing connections JSON file.")
    with path.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Connection imports must be no larger than 1 MiB.")
    try:
        incoming = validate_connections(json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object))
    except (ValueError, RecursionError):
        raise ValueError("Use valid Agentnik connections JSON with no duplicate names or fields.") from None
    if len(incoming) > 100:
        raise ValueError("Import at most 100 connections at a time.")
    new = {name: settings for name, settings in incoming.items() if name not in store.config["connections"]}
    if not new:
        print("No new connections to import. Existing connections were not changed.")
        return
    print("Import settings for: " + ", ".join(repr(name) for name in new))
    print(f"Skip {len(incoming) - len(new)} existing connection(s). API keys will not be imported.")
    if input("Import these settings? [y/N] ").strip().lower() != "y":
        return
    for name, settings in new.items():
        store.save_connection(name, portable_connection(settings))
    print(f"Imported {len(new)} connection(s). Use /connections key NAME to add credentials.")


def connection_name_argument(name, known_names):
    if len(name) >= 2 and name[0] == name[-1] and name[0] in ("'", '"') and name not in known_names:
        return name[1:-1]
    return name


def connection_menu(data_dir, action="", selected_name="", *, discovered=None):
    from .core import PROTOCOLS, environment_connections, validate_connections
    from .storage import ConfigurationError, Store

    try:
        store = Store(data_dir)
    except (ConfigurationError, OSError, sqlite3.Error) as exc:
        print(exc, file=sys.stderr)
        return
    try:
        if action == "import":
            import_connection_settings(store, selected_name or input("Connections JSON file: "))
            return
        if action == "export":
            export_connection_settings(store, selected_name or input("New connections JSON file: "))
            return
        if not action:
            saved = store.config["connections"]
            for label, entries in (("Saved", saved), ("Environment", environment_connections())):
                for name, entry in entries.items():
                    print(f"{label}: {name!r} · {entry.get('model', '')!r}")
            return
        name = selected_name or input("Connection name: ").strip()
        saved = store.config["connections"]
        alternates = {**(discovered or {}), **environment_connections()} if action == "copy" and name not in saved else {}
        if selected_name:
            name = connection_name_argument(name, saved.keys() | alternates.keys())
        old = saved.get(name)
        if action == "copy" and old is None:
            old = alternates.get(name)
            if old is None:
                print("Choose a saved, environment, or discovered connection.")
                return
        if action == "add":
            if not name or old is not None:
                print("Choose a new, nonempty connection name.")
                return
        elif old is None:
            print("Choose an existing saved connection.")
            return
        if action == "show":
            print(f"Saved connection {name!r}")
            for field, label, default in (
                ("protocol", "Protocol", "chat"), ("model", "Model", ""),
                ("reasoning", "Reasoning effort", ""), ("service_tier", "Service tier", ""),
                ("context_limit", "Context tokens", 0), ("stream", "Streaming", True),
            ):
                print(f"{label}: {old.get(field, default)!r}")
            print("Endpoint URL and credentials are not displayed.")
            return
        if action == "copy":
            target = input("New connection name: ").strip()
            if not target or target in store.config["connections"]:
                print("Choose a new, nonempty connection name.")
                return
            source = portable_connection(old)
            store.save_connection(target, validate_connections({"connections": {target: source}})[target])
            print(f"Saved connection {target!r} without an API key. Use /connections key to add one.")
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
    session_action = parser.add_mutually_exclusive_group()
    session_action.add_argument("--check-keys", action="store_true", help="Check keyboard shortcuts without starting a session")
    session_action.add_argument("--list-sessions", action="store_true", help="List saved project sessions as JSON")
    session_action.add_argument("--resume", nargs="?", const="latest", metavar="ID",
                        help="Resume a session in this project (default: latest)")
    parser.add_argument("project", nargs="?", type=Path, default=Path.cwd(),
                        help="Project folder (default: current directory)")
    options = parser.parse_args(args[1:])
    if options.check_keys:
        if not sys.stdin.isatty():
            parser.error("an interactive terminal is required")
        from .code_composer import run_keyboard_check
        return run_keyboard_check()
    if options.resume is not None and not options.resume.strip():
        parser.error("--resume needs a session ID, unique prefix, or latest")
    try:
        root = options.project.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
    if not root.is_dir():
        parser.error("project must be a directory")

    from .code_lease import SessionLease
    from .code_attachments import ImageQueue
    from .storage import default_home

    try:
        options.data_dir = (options.data_dir or default_home()).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        parser.error(f"cannot resolve the application data directory: {exc}")
    if options.data_dir.exists() and not options.data_dir.is_dir():
        parser.error("application data path must be a directory")

    if options.list_sessions:
        from .code_history import saved_session_metadata
        from .code_terminal import terminal_text

        try:
            sessions = saved_session_metadata(options.data_dir, root)
        except (OSError, ValueError, sqlite3.Error) as exc:
            print(terminal_text(exc), file=sys.stderr)
            return 1
        print(json.dumps(sessions))
        return 0
    if not sys.stdin.isatty():
        parser.error("an interactive terminal is required")

    with SessionLease(options.data_dir) as lease, ImageQueue() as images:
        return terminal_session(options, root, lease, images)


def terminal_settings_arguments(command):
    """Keep the exact trailing profile name for named MCP settings."""
    arguments = command.split(None, 3)
    if len(arguments) > 3 and arguments[1] == "mcp":
        action, tail = arguments[2:]
        if action == "timeout":
            return ["mcp", action, *tail.split(None, 1)]
        if action in ("edit-https", "edit-local", "token", "signin", "renew", "enable", "disable", "remove"):
            return ["mcp", action, tail]
    return command.split()[1:]


def terminal_session(options, root, lease, images):
    print(f"Agentnik Code preview · {str(root)!r}")
    print("Select a connection with /connection NAME, then enter a task. Type /help.")
    from .code_composer import COMPOSER_KEYS, TRANSCRIPT_KEYS, create_composer, transcript_pager

    transcript = deque(maxlen=2048)

    def write_activity(text="", *, end="\n", flush=False):
        transcript.append(text + end)
        print(text, end=end, flush=flush)

    machine_scope = False
    require_approval = True

    def prompt_label():
        modes = [name for name, enabled in (("machine", machine_scope), ("allow-all", not require_approval))
                 if enabled]
        return f"code [{', '.join(modes)}]> " if modes else "code> "

    def saved_session_ids():
        from .code_history import saved_session_metadata

        try:
            return tuple(row["id"] for row in saved_session_metadata(options.data_dir, root))
        except (OSError, ValueError, sqlite3.Error):
            return ()

    def open_composer():
        return create_composer(transcript=lambda: "".join(transcript), message=prompt_label, session_ids=saved_session_ids)

    try:
        composer = open_composer()
    except ModuleNotFoundError as exc:
        if exc.name != "prompt_toolkit":
            raise
        composer = None
        print("Install agentnik[terminal] for multiline editing and prompt recall.")
    else:
        print(" ".join(COMPOSER_KEYS[:2]))
        print(f"{COMPOSER_KEYS[2]} Use /keys for the full list.")
    connection_name = model = ""
    discovered = {}
    mcp_selection = []
    context = None
    context_model = ""
    use_context = True
    last_goal_turn = None
    web_enabled = False
    vision_enabled = False
    memory_enabled = False
    show_thinking = False
    skill_pins = {}
    documents = []
    session_id = str(uuid4())
    rejected_draft = draft_to_edit = ""

    def current_run_settings():
        from .code_terminal import load_run_settings

        if not connection_name:
            raise ValueError("Select a connection with /connection NAME first.")
        if images.paths() and not vision_enabled:
            raise ValueError("Enable /vision on or clear the queued image attachments first.")
        if skill_pins:
            from .code_agent import ProjectFiles
            from .project_skills import verify_skill_pins

            try:
                verify_skill_pins(ProjectFiles(root), list(skill_pins), skill_pins)
            except ValueError as exc:
                raise ValueError(f"{exc} Use /skills show ID and /skills add ID, or /skills remove ID.") from None
        return load_run_settings(
            options.data_dir, connection_name, model, web_enabled, discovered=discovered,
            mcp_selection=mcp_selection, root=root, memory_enabled=memory_enabled,
        )

    def change_model(selected):
        nonlocal model, context, context_model, vision_enabled, memory_enabled
        if selected != model:
            model = selected
            if context:
                print("Previous-turn context cleared for the new model. Saved history is unchanged.")
            context = None
            context_model = ""
            vision_enabled = memory_enabled = False

    def reset_session_state():
        nonlocal context, context_model, use_context, last_goal_turn, web_enabled, vision_enabled, memory_enabled
        nonlocal mcp_selection, show_thinking, skill_pins, require_approval, machine_scope, composer
        nonlocal rejected_draft, draft_to_edit
        rejected_draft = draft_to_edit = ""
        context = last_goal_turn = None
        context_model = ""
        use_context = require_approval = True
        web_enabled = vision_enabled = memory_enabled = show_thinking = machine_scope = False
        mcp_selection = []
        skill_pins = {}
        documents.clear()
        images.clear()
        transcript.clear()
        if composer:
            composer = open_composer()

    pending_command = f"/resume {options.resume}" if options.resume else None
    while True:
        starting_resume = pending_command is not None
        editing_rejected_draft = False
        try:
            if pending_command:
                command, pending_command = pending_command, None
            else:
                if composer and draft_to_edit:
                    editing_rejected_draft = True
                    draft, draft_to_edit = draft_to_edit, ""
                    command = composer.prompt(default=draft).strip()
                else:
                    command = (composer.prompt() if composer else input(prompt_label())).strip()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            return 0
        if command == "/exit":
            return 0
        if command == "/keys":
            if composer:
                print("\n".join((*COMPOSER_KEYS, *TRANSCRIPT_KEYS)))
            else:
                print("Enter submits. Install agentnik[terminal] for multiline editing, history and transcript shortcuts.")
            print("Ctrl+C cancels the current input or run.")
            continue
        if command == "/transcript":
            if not transcript:
                print("No transcript for this session yet.")
            elif not composer:
                print("Install agentnik[terminal] for the transcript pager, or use /history for saved turns.")
            else:
                try:
                    transcript_pager("".join(transcript), input=composer.app.input,
                                     output=composer.app.output).run()
                except (KeyboardInterrupt, EOFError):
                    print()
            continue
        if command == "/help":
            print("/keys             Show keyboard shortcuts\n"
                  "/transcript       Open the current session transcript\n"
                  "/status           Show the current session, project, model and permissions\n"
                  "/check            Validate local run settings without contacting the model\n"
                  "/diff --staged   Preview staged changes without native Git\n"
                  "/diff [--staged] PATH  Review a file against HEAD\n"
                  "/git              Run manual Git status, log, diff, stage, unstage, commit, or push\n"
                  "/connections      List saved and environment connections\n"
                  "/connections show|add|edit|copy|options|key|remove [NAME]\n"
                  "/connections import|export PATH   Transfer saved settings without API keys\n"
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
                  "/scope [MODE]     Show or set file scope for the next run (project or machine)\n"
                  "/settings         Manage coding limits, TLS and desktop appearance\n"
                  "/draft           Edit a task rejected before its run started\n"
                  "/history [PAGE]   Show saved turns for this session\n"
                  "/history turn N   Show the full saved activity for turn N\n"
                  "/new              Start a fresh session in this project\n"
                  "/sessions [PAGE]  List saved sessions for the current project\n"
                  "/resume [ID]      List sessions or resume by ID, unique prefix, or latest\n"
                  "/exit             Close Agentnik Code")
        elif command == "/mcp off":
            mcp_selection.clear()
            print("MCP disabled in this session.")
        elif command.startswith("/mcp remove "):
            from .code_settings import mcp_profile_name

            name = mcp_profile_name(command.removeprefix("/mcp remove ").strip(), mcp_selection)
            mcp_selection = [profile for profile in mcp_selection if profile["name"] != name]
            print("Updated the session’s MCP selection.")
        elif command == "/mcp" or command.startswith(("/mcp use ", "/mcp add ")):
            from .code_settings import mcp_profile_name
            from .code_terminal import terminal_mcp_profiles, terminal_text

            try:
                profiles = terminal_mcp_profiles(options.data_dir)
                if command == "/mcp":
                    for index, profile in enumerate(mcp_selection, 1):
                        stale = " [changed or unavailable; reselect or remove]" if profile not in profiles else ""
                        print(terminal_text(f"Selected {index}: {profile['name']}{stale}"))
                    for profile in profiles:
                        print(terminal_text(f"Available: {profile['name']}"))
                    print("Use /mcp use NAME to replace the selection, or /mcp add NAME to add or refresh one server. Use /mcp remove NAME or /mcp off to deselect.")
                else:
                    action, _, name = command.removeprefix("/mcp ").partition(" ")
                    name = mcp_profile_name(name.strip(), profiles)
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
                if machine_scope:
                    print("Project context is paused in machine scope.")
                elif context:
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
                manual_git(root, command.partition(" ")[2], write=write_activity)
            except (EOFError, KeyboardInterrupt):
                write_activity("Git command interrupted. Check Git state before retrying.")
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif command == "/diff" or command.startswith("/diff "):
            from .code_terminal import project_diff, terminal_text

            try:
                write_activity(terminal_text(project_diff(root, command.partition(" ")[2].strip())))
            except (OSError, ValueError) as exc:
                print(terminal_text(exc), file=sys.stderr)
            except KeyError:
                print("Git diff unavailable. The repository may not have an initial commit.", file=sys.stderr)
        elif command == "/check":
            from .code_terminal import run_settings_summary, terminal_text

            try:
                connection, _, _, run_options, _ = current_run_settings()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
            else:
                print("Local run settings passed. No model request was sent. "
                      "This does not verify credentials or provider capabilities.")
                print(run_settings_summary(connection, run_options, vision=vision_enabled,
                                           image_count=len(images.paths()), document_count=len(documents)))
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
                machine_scope = mode == "machine"
            elif mode:
                print("Use /scope project or /scope machine.")
                continue
            if machine_scope:
                print("File scope: machine. Machine tools use absolute paths and run with your OS account's permissions.")
                print("Machine file changes require approval." if require_approval
                      else "Machine file changes normally skip approval (allow-all).")
            else:
                print("File scope: project. Built-in file tools use project-relative paths. Machine tools are unavailable.")
            print("Shell commands are not sandboxed in either scope. Their starting directory is project-relative.")
        elif command == "/permissions" or command.startswith("/permissions "):
            mode = command.partition(" ")[2].strip()
            actions = "File edits in the current scope and ordinary shell commands"
            exceptions = "MCP requests, structured Git changes, and subagent file transfers still require review."
            image_policy = ("Configured image generation also follows this mode and may send reference images "
                            "to the image provider without a prompt in allow-all mode.")
            if not mode:
                current = "require" if require_approval else "allow-all"
                print(f"Current mode: {current}. Applies to {actions.lower()}. {exceptions} {image_policy}")
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
            if require_approval:
                print(f"{actions} require approval for this session.")
            else:
                print(f"{actions} normally skip approval for this session. {exceptions} "
                      "Shell commands that need separate review still prompt. " + image_policy)
                if machine_scope:
                    print("Machine file changes normally skip approval (allow-all).")
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
            from .project_skills import list_resources, list_skills, read_resource, read_skill

            action, _, ident = command.partition(" ")[2].partition(" ")
            ident = ident.strip()
            try:
                files = ProjectFiles(root)
                if not action:
                    available = {skill["id"]: skill for skill in list_skills(files)}
                    for name, skill in available.items():
                        marker = "*" if name in skill_pins else " "
                        state = ""
                        if name in skill_pins:
                            try:
                                if read_skill(files, name)["sha256"] != skill_pins[name]:
                                    state = " [changed since selection]"
                            except (OSError, ValueError):
                                state = " [unavailable]"
                        print(terminal_text(f"{marker} {name}{state} — {skill['description']}"))
                    for name in skill_pins.keys() - available.keys():
                        print(terminal_text(f"* {name} [unavailable]"))
                    print("Use /skills show ID to review, /skills add ID to select the current revision, "
                          "or /skills remove ID to clear a selection.")
                    print("Use /skills resources ID to list supporting files or /skills read ID PATH to read one.")
                elif action == "resources" and ident:
                    result = list_resources(files, ident)
                    if result["resources"]:
                        for path in result["resources"]:
                            print(terminal_text(path))
                    else:
                        print("No supporting files found.")
                    if result["truncated"]:
                        print("The supporting-file list is incomplete due to scan limits.")
                elif action == "read":
                    parts = ident.split(maxsplit=1)
                    if len(parts) != 2:
                        print("Use /skills read ID PATH with a skill-relative path.")
                    else:
                        result = read_resource(files, *parts)
                        print(terminal_text(result["content"]))
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
        elif command == "/draft":
            from .code_terminal import terminal_text

            if not rejected_draft:
                print("No rejected task draft in this session.")
            elif composer:
                draft_to_edit = rejected_draft
            else:
                print(terminal_text(rejected_draft))
        elif command == "/new":
            lease.close()
            session_id = str(uuid4())
            reset_session_state()
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
            if action not in ("", "show", "add", "edit", "copy", "options", "key", "remove", "import", "export"):
                print("Use /connections, /connections import|export PATH, or /connections show|add|edit|copy|options|key|remove [NAME].")
                continue
            connection_menu(options.data_dir, action, name.strip(), discovered=discovered)
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
                    print(configure_code(store, terminal_settings_arguments(command), root=root))
                finally:
                    store.db.close()
            except (EOFError, KeyboardInterrupt):
                print("Settings command interrupted.")
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
        elif (command.split(" ", 1)[0] in ("/history", "/sessions", "/resume", "/open") or command in ("/plan", "/goal")):
            from .code_history import CodeHistory, Store, activity_preview
            from .code_terminal import terminal_text

            action = command.split(" ", 1)[0]
            listing = command in ("/resume", "/open") or action == "/sessions"
            current_only = action in ("/history", "/plan", "/goal")
            argument = command.partition(" ")[2].strip()
            detail = action == "/history" and argument.split()[:1] == ["turn"]
            if detail:
                argument = argument[4:].strip()
            if (listing or action == "/history") and (argument or detail) and (
                    not argument.isascii() or not argument.isdecimal() or len(argument) > 9 or int(argument) < 1):
                print("Use /history turn N with a positive whole turn number." if detail else
                      f"Use {action} PAGE with a positive whole page number.")
                continue
            if action == "/history":
                page = int(argument or 1)
                offset = page - 1 if detail else (page - 1) * 20
            try:
                read_only = listing or current_only
                if not (options.data_dir / "history.sqlite3").exists():
                    sessions, records, snapshot = {}, [], None
                else:
                    store = Store.open_history(options.data_dir, writable=not read_only)
                    try:
                        history = CodeHistory(store, root)
                        if listing:
                            sessions = history.session_summaries()
                        elif action == "/history":
                            records = history.turn_window(session_id, offset, 1 if detail else 21)
                        elif current_only:
                            records = history.list(session_id)
                        else:
                            ident, snapshot = history.prepare_resume(argument, lease)
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
                for ident, (record, goal_status) in list(sessions.items())[offset:offset + 20]:
                    label = next((e["text"].split("\n")[0][:80] for e in record.get("code_activity", [])
                                  if e["kind"] == "prompt"), record["title"])
                    scope = " [machine]" if record.get("coding_file_scope") == "machine" else ""
                    current = " [current]" if ident == session_id else ""
                    goal = f" [goal: {goal_status}]" if goal_status else ""
                    print(terminal_text(f"{ident}  {record.get('code_state', 'idle')}{scope}{current}{goal}  {label}"))
                if not sessions:
                    print("No saved sessions for this project. Your current session is saved when its first task starts.")
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
                if detail:
                    if not records:
                        print("No saved turn with that number.")
                    else:
                        saved = records[0]
                        print(f"Saved turn {page} (newest is 1).")
                        if saved.get("coding_file_scope") == "machine":
                            print("[Saved turn used machine scope]")
                        for entry in saved.get("code_activity", []):
                            print(terminal_text(entry["text"]))
                elif not records:
                    print("No saved history for this session." if page == 1 else "No saved turns on that page.")
                else:
                    for index in range(min(20, len(records)) - 1, -1, -1):
                        number = offset + index + 1
                        print(f"Saved turn {number} (details: /history turn {number})")
                        for line in activity_preview(records[index]):
                            print(terminal_text(line))
                    if len(records) > 20:
                        print(f"More saved turns are available under /history {page + 1}.")
                continue
            if snapshot is None:
                print("No saved session with that ID in this project. Sessions are saved when a task starts.")
                if starting_resume:
                    return 1
                continue
            session_id = ident
            reset_session_state()
            if composer:
                for text in snapshot.prompt_history:
                    prompt = terminal_text(text)
                    composer.history.append_string("/" + prompt if prompt.startswith("/") else prompt)
            for line in snapshot.activity:
                write_activity(terminal_text(line))
            record = snapshot.record
            last_goal_turn = snapshot.latest_goal_turn
            skill_pins = snapshot.skill_pins
            context = snapshot.project_context
            connection_name, model = snapshot.connection, snapshot.model
            context_model = model if context else ""
            if "coding_plan" in record:
                from .code_terminal import terminal_plan

                write_activity(terminal_plan(record["coding_plan"], "Saved plan (model reported):"))
            print(f"Resumed session {session_id}. Enter a new task when ready. Nothing was restarted.")
            if context:
                print("Previous project context restored. Use /context to inspect it.")
            elif record.get("code_state") in ("cancelled", "interrupted", "failed", "limited", "blocked"):
                print("No previous project context restored. Saved activity is available through /history.")
            if record.get("coding_file_scope") == "machine":
                print("The last saved turn used machine scope. New tasks start in project scope.")
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
                    known = store.config["connections"].keys() | discovered.keys()
                    if name not in known:
                        known |= environment_connections().keys()
                    name = connection_name_argument(name, known)
                    available = name in known
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
                context_model = ""
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
                change_model(selected)
                print(f"Selected model {model!r}. Catalog entries do not establish tool or vision support.")
        elif command == "/model" or command.startswith("/model "):
            selected = command[6:].strip()
            change_model(selected)
            print(f"Selected model {model!r}." if model else "Using the connection's default model.")
        elif command.startswith("/") and not command.startswith(("//", "/goal ")) and command != "/continue":
            print("Unknown command. Type /help, or start with // to send a prompt that begins with /.")
        elif command:
            if command == "//":
                print("Enter a prompt after the escape slash.")
                continue
            submitted = command if command != "/continue" else ""
            if not connection_name:
                print("Select a connection with /connection NAME first.")
                if submitted:
                    rejected_draft = submitted
                    print("Use /draft to edit the unsent task.")
                continue
            from .code_agent import CodingRun
            from .code_history import CodeHistory, Store, prepare_goal_continuation
            from .code_terminal import drive_run, remember_terminal_subagent_rejection, terminal_text

            continuing = command == "/continue"
            goal = continuing or command.startswith("/goal ")
            resume = None
            if continuing:
                continuation = prepare_goal_continuation(
                    last_goal_turn, connection_name, "machine" if machine_scope else "project")
                if continuation.status == "unavailable":
                    print("No stopped goal is available to continue in this session.")
                    continue
                if continuation.status == "connection_mismatch":
                    print(terminal_text(f"That goal used connection {continuation.connection!r}. "
                                        "Select it with /connection before continuing."))
                    continue
                if continuation.status == "scope_mismatch":
                    print(f"That goal ran in {continuation.scope} scope. Use /scope {continuation.scope} before continuing.")
                    continue
                saved_scope, resume = continuation.scope, continuation.context
                command = "Continue the saved objective. Inspect current state first and do not repeat uncertain actions."
            elif goal:
                command = command.removeprefix("/goal ").strip()
            elif command.startswith("//"):
                command = command[1:]
            try:
                connection, limits, goal_budget, research_options, advice = current_run_settings()
                if continuing:
                    target_model = connection.get("model", "")
                    approval_mode = "require" if require_approval else "allow-all"
                    print(terminal_text(f"Continue using connection {connection_name!r}, model {target_model!r}, "
                                        f"in {saved_scope} scope with permissions {approval_mode}."))
                    if continuation.model and continuation.model != target_model:
                        from .research import scrub

                        prior_model = scrub(continuation.model, [connection.get("api_key")])
                        print(terminal_text(f"The saved goal used model {prior_model!r}. "
                                            "Confirmation sends the saved objective and evidence to the new model."))
                    from .code_limits import coding_limits, goal_limits

                    run_caps, goal_caps = coding_limits(limits), goal_limits(goal_budget)
                    print("Run budgets · " + " · ".join(
                        f"{label}: {run_caps[key] or 'unlimited'}"
                        for label, key in (("rounds", "rounds"), ("requests", "requests"),
                                           ("tool calls", "calls"), ("seconds", "turn_seconds"))
                    ))
                    print("Goal budgets · " + " · ".join(
                        f"{key}: {goal_caps[key] or 'unlimited'}" for key in ("steps", "seconds")
                    ))
                    print(terminal_text(resume["task"]))
                    print(terminal_text(resume["evidence"]))
                    try:
                        if input("Continue this goal with fresh limits? [y/N] ").strip().lower() != "y":
                            continue
                    except (EOFError, KeyboardInterrupt):
                        print()
                        continue
                if context and connection["model"] != context_model:
                    context = None
                    context_model = ""
                    print("Previous-turn context cleared because the effective model changed. Saved history is unchanged.")
                run = CodingRun(connection, root, command,
                                context=context if use_context and not resume and not machine_scope else None,
                                limits=limits,
                                goal=goal, goal_budget=goal_budget, vision_enabled=vision_enabled,
                                resume_context=resume,
                                documents=documents,
                                images=images.paths(),
                                skills=list(skill_pins), skill_pins=skill_pins,
                                **research_options)
                run.configure_interaction(shell_without_approval=not require_approval,
                                          review_project_edits=require_approval, stream_activity=True,
                                          show_thinking=show_thinking, machine_scope=machine_scope)
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                if submitted:
                    rejected_draft = submitted
                    print("Use /draft to edit the unsent task.")
                continue
            started = False
            try:
                store = Store(options.data_dir)
                try:
                    lease.select(session_id)
                    history = CodeHistory(store, root)
                    record, task = history.start(
                        connection_name, connection, resume["task"] if resume else command, session_id, goal=goal,
                        skill_pins=skill_pins, machine_scope=machine_scope,
                        extra_secrets=[
                            *(item.get("key") for item in research_options["web_backends"]),
                            research_options.get("image_config", {}).get("connection", {}).get("api_key"),
                            (advice or {}).get("api_key"),
                            *(value for bridge in research_options.get("mcp_bridges", [])
                              for value in bridge.environment_values.values()),
                        ],
                    )
                    started = True
                    if submitted and (editing_rejected_draft or submitted == rejected_draft):
                        rejected_draft = ""
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
                    if goal:
                        last_goal_turn = record
                    if not machine_scope:
                        context = record.get("coding_context")
                        context_model = connection["model"] if context else ""
                finally:
                    store.db.close()
            except (OSError, ValueError, sqlite3.Error) as exc:
                print(terminal_text(exc), file=sys.stderr)
                if submitted and not started:
                    rejected_draft = submitted
                    print("Use /draft to edit the unsent task.")


if __name__ == "__main__":
    raise SystemExit(main())
