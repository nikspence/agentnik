"""Terminal adapter for Agentnik's existing Code run and approval contract."""

from queue import Empty, Queue
import sqlite3
import unicodedata

from .task_plan import validate_plan


def terminal_text(text):
    return "".join(
        ch if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
        else repr(ch)[1:-1]
        for ch in str(text)
    )


def terminal_plan(value, heading="Plan update (model reported):"):
    plan = validate_plan(value)
    lines = [heading]
    if plan["explanation"]:
        lines.append(plan["explanation"])
    lines.extend(f"  [{step['status'].replace('_', ' ')}] {step['step']}" for step in plan["steps"])
    return terminal_text("\n".join(lines))


def terminal_project_memory(data_dir, root, argument):
    from .code_history import same_project
    from .project_memory import ProjectMemory
    from .repositories import RepositoryRegistry
    from .storage import Store

    action, _, ident = argument.partition(" ")
    if argument and (action != "show" or not ident.strip()):
        raise ValueError("Use /memory to list project entries or /memory show ID to read one.")
    store = Store(data_dir)
    try:
        registry = RepositoryRegistry(store)
        project = next((row["id"] for row in registry.list() if same_project(row["path"], root)), None)
        if not project:
            return "No saved memory for this project."
        memory = ProjectMemory(store.root / "history.sqlite3", project)
        if action == "show":
            item = memory.read(ident.strip())
            if item is None:
                raise ValueError("No memory entry with that ID in this project.")
            header = item["title"] + (" [stale]" if item["stale"] else "")
            source = f"\nSource: {item['source']}" if item["source"] else ""
            return terminal_text(f"{header}\n{item['text']}{source}")
        lines = [f"{item['id']}  {item['title']}" + (" [stale]" if item["stale"] else "") for item in memory.list()]
        return terminal_text("\n".join(lines)) or "No saved memory for this project."
    finally:
        store.db.close()


def project_diff(root, argument):
    from .code_agent import ProjectFiles
    from .git_service import GitService

    git = GitService(ProjectFiles(root))
    if not argument:
        status = git.inspect("git_status")
        return "\n".join([
            *(f"Conflicted: {path!r}" for path in status["conflicted"]),
            *(f"Staged: {path!r}" for path in status["staged"]),
            *(f"Unstaged: {path!r}" for path in status["unstaged"]),
            *([] if status["head"] else ["No commits yet. Diffs compare with an empty tree."]),
            status["scope"],
            "Use /diff PATH to compare with HEAD or /diff --staged PATH to review the index.",
        ])
    if argument == "--staged":
        status = git.inspect("git_status")
        paths = status["staged"]
        lines = ["Staged changes compared with HEAD." if status["head"]
                 else "Staged changes compared with the empty tree."]
        if not paths:
            lines.append("No staged changes.")
        if status["conflicted"]:
            lines.append("Unresolved merge entries are excluded. Use /diff to list them.")
        for path in paths[:12]:
            lines.append(f"Staged: {path!r}")
            try:
                diff = git.inspect("git_diff_staged", path)["diff"]
                lines.append(diff[:2400] or "No textual changes for this file.")
                if len(diff) > 2400:
                    lines.append("Patch preview shortened.")
            except (OSError, ValueError, KeyError) as exc:
                lines.append(f"Patch unavailable: {exc}")
        if len(paths) > 12:
            lines.append("Only the first 12 staged paths are shown.")
        lines.append("Use /diff --staged PATH for a single-file diff.")
        return "\n".join(lines)
    staged = argument.startswith("--staged ")
    path = argument.partition(" ")[2].strip() if staged else argument
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ("'", '"'):
        path = path[1:-1]
    if not path:
        raise ValueError("Provide a project-relative file after --staged." if staged
                         else "Provide a project-relative file path.")
    result = git.inspect("git_diff_staged" if staged else "git_diff", path)
    return result["diff"] or "No textual changes for this file."


def choose_catalog_model(data_dir, name, match="", discovered=None):
    from . import core, tls
    from .storage import Store

    store = Store(data_dir)
    try:
        connections = {**(discovered or {}), **core.environment_connections(), **store.connections()}
        connection = connections.get(name)
        if connection is None:
            raise ValueError("Select a connection with /connection NAME first.")
        tls.configure(store.config["settings"].get("relaxed_tls", False))
        try:
            catalog = core.models(connection)
        except core.EndpointError as exc:
            raise ValueError(f"Model catalog returned HTTP {exc.status}. You can still use /model NAME.") from None
        except (OSError, ValueError, TypeError, AttributeError):
            raise ValueError("Model catalog unavailable. You can still use /model NAME.") from None
    finally:
        store.db.close()
    key = connection.get("api_key")
    models = [model for model in dict.fromkeys(catalog)
              if 0 < len(model) <= 512 and model.isprintable() and (not key or key not in model)
              and match.casefold() in model.casefold()]
    if not models:
        print("No matching models. You can still use /model NAME.")
        return None
    shown = models[:30]
    for index, model in enumerate(shown, 1):
        print(f"{index:2}. {terminal_text(model)}")
    if len(models) > len(shown):
        print("Showing the first 30 matches. Use /models FILTER to narrow the list.")
    choice = input("Select a model number [Enter to cancel]: ").strip()
    if not choice:
        return None
    if not choice.isascii() or not choice.isdecimal() or len(choice) > 2 or not 1 <= int(choice) <= len(shown):
        raise ValueError("Choose one of the displayed model numbers.")
    return shown[int(choice) - 1]


def terminal_mcp_profiles(data_dir):
    from .storage import Store

    store = Store(data_dir)
    try:
        return [item for item in store.config.get("mcp_servers", []) if item["enabled"]]
    finally:
        store.db.close()


def terminal_mcp_bridges(config, selection):
    from .mcp_terminal import TerminalMCPBridge
    from .mcp_terminal_http import TerminalHTTPMCPBridge

    if not config["settings"].get("mcp_access_enabled", True):
        raise ValueError("Shared MCP access is off. Use /settings mcp on or /mcp off.")
    if len(selection) > 5 or len({profile["name"] for profile in selection}) != len(selection):
        raise ValueError("Select at most five distinct MCP servers.")
    bridges = []
    saved = config.get("mcp_servers", [])
    for profile in selection:
        if profile not in saved or not profile["enabled"]:
            raise ValueError("A selected MCP server changed or is unavailable. Reselect it or remove it.")
        if profile.get("transport") != "http":
            bridges.append(TerminalMCPBridge(profile))
            continue
        token = ""
        if profile.get("auth_type") == "oauth":
            from .mcp_oauth_record import credential_state, read_record

            try:
                record = read_record(profile["credential_id"], profile["url"])
            except Exception:
                raise ValueError(
                    f"MCP OAuth sign-in is unavailable for {profile['name']}. "
                    f"Use /settings mcp signin {profile['name']} or sign in again in desktop settings."
                ) from None
            if credential_state(record) != "ready":
                raise ValueError(f"MCP OAuth sign-in needs renewal. Use /settings mcp renew {profile['name']}.")
            token = record["access_token"]
        elif profile.get("credential_id"):
            import keyring

            try:
                token = keyring.get_password("Agentnik", profile["credential_id"]) or ""
            except Exception:
                token = ""
            if not token or len(token) > 4096 or any(not 33 <= ord(ch) <= 126 for ch in token):
                raise ValueError("A selected MCP bearer token is unavailable or invalid.")
        bridges.append(TerminalHTTPMCPBridge(profile, token))
    return bridges


def load_run_settings(data_dir, name, model, web_enabled=False, discovered=None, mcp_selection=(), root=None,
                      memory_enabled=False):
    from importlib.util import find_spec
    from . import core, tls
    from .code_setup import CodeSelectionError, resolve_run_connection, shared_run_options
    from .image_settings import image_tool_config
    from .storage import Store

    store = Store(data_dir)
    try:
        connections = {**(discovered or {}), **core.environment_connections(), **store.connections()}
        try:
            connection = resolve_run_connection(connections.get(name), model or None)
        except CodeSelectionError as exc:
            if exc.field == "connection":
                raise ValueError("Unknown connection. Use /connections to list names.") from None
            raise ValueError("No model selected. Use /model to specify one.") from None
        settings = store.config["settings"]
        tls.configure(settings.get("relaxed_tls", False))
        capability_connection = dict(connection)
        if name not in store.config["connections"]:
            capability_connection.pop("_capability_scope", None)
        options = shared_run_options(
            store, name, connection, web_enabled=web_enabled, has_mcp=bool(mcp_selection),
            capability_connection=capability_connection,
        )
        if mcp_selection:
            options["mcp_bridges"] = terminal_mcp_bridges(store.config, mcp_selection)
        try:
            image = image_tool_config(settings.get("image_generation"), connections)
        except ValueError as exc:
            raise ValueError(f"{str(exc).rstrip('.')}. Use /settings image set to repair it "
                             "or /settings image off to run without generation.") from None
        if image is not None:
            if find_spec("PySide6") is None and find_spec("PIL") is None:
                raise ValueError("Install the Agentnik terminal extra for headless image generation.")
            options["image_config"] = image
        from .decision_advice import configured_advisor

        _, advice = configured_advisor(settings, connections)
        if root is not None:
            from .code_history import same_project
            from .repositories import RepositoryRegistry

            registry = RepositoryRegistry(store)
            ident = next((row["id"] for row in registry.list() if same_project(row["path"], root)), None)
            if ident:
                options["git_author"] = registry.git_author(ident)
                if memory_enabled:
                    from .project_memory import ProjectMemory

                    options["project_memory"] = ProjectMemory(store.root / "history.sqlite3", ident)
                    options["project_memory_read_only"] = True
        return connection, options.pop("limits"), options.pop("goal_budget"), options, advice
    finally:
        store.db.close()


def run_settings_summary(connection, options, *, vision, image_count, document_count):
    """Describe resolved local settings without URLs, tokens, or attachment contents."""
    from .research import scrub

    model = scrub(connection.get("model", ""), [connection.get("api_key")])
    return terminal_text(
        f"Effective model: {model!r} · "
        f"Web: {'on' if options.get('web_enabled') else 'off'} · "
        f"Image inspection: {'on' if vision else 'off'} · "
        f"Image generation: {'configured' if options.get('image_config') else 'off'} · "
        f"MCP profiles: {len(options.get('mcp_bridges', ()))}\n"
        f"Queued attachments: {image_count} image(s), {document_count} document(s)."
    )


def show_shell_advice(connection, proposal, cancel, write, *, is_pending=None):
    from . import core, decision_advice

    fields = [str(proposal.get(key, "")) for key in ("command", "cwd", "shell", "environment_keys")]
    secret = connection.get("api_key")
    if any("[redacted]" in value or (secret and secret in value) for value in fields):
        write("Advice skipped because the proposal contains a configured credential.")
        return
    try:
        destination = core.endpoint(connection, "decision")
    except ValueError:
        write("The configured System One endpoint is unavailable.")
        return
    write("Advice sends the command, directory, shell, and environment variable names to "
          + terminal_text(destination) + ".")
    if input("Send this proposal for advice? [y/N] ").strip().lower() != "y":
        return
    if is_pending is not None and not is_pending():
        return
    try:
        result = decision_advice.parse_advice(decision_advice.request(connection, proposal, cancel))
    except Exception:
        write("System One advice unavailable. Review the command yourself.")
        return
    confidence = result["confidence"]
    suffix = "" if confidence is None else f" · {confidence:.0%} confidence"
    write(f"System One advice: {result['category'].upper()}{suffix}. You still decide.")


def remember_terminal_subagent_rejection(data_dir, name, connection):
    """Persist an observed rejection only for the unchanged saved connection."""
    from .storage import Store
    from .subagent_capabilities import remember, unsupported

    store = Store(data_dir)
    try:
        saved = store.config["connections"].get(name)
        scope = connection.get("_capability_scope")
        if not saved or not scope or saved.get("_capability_scope") != scope:
            return
        if any(saved.get(key) != connection.get(key) for key in ("url", "protocol", "reasoning", "stream", "context_limit")):
            return
        if not unsupported(store.config, connection):
            remember(store.config, connection)
            store.flush()
    finally:
        store.db.close()


def drive_run(run, write=print, advice=None, checkpoint=None):
    from .code_worker import STEERING_OUTCOMES, start_code_worker

    events = Queue()
    done = object()
    worker = start_code_worker(
        run, events.put, finished=lambda: events.put(done),
        interruption_text="Code stopped before reporting a result. Check the project before continuing. "
                          "Agentnik will not replay the request.",
    )
    streamed = {}
    partial_line = False
    result = {}
    goal_detail = ""

    def completed_result(result):
        result = dict(result)
        if goal_detail:
            result["last_goal_detail"] = goal_detail
        if result.get("status") in ("cancelled", "interrupted", "failed", "limited") and streamed:
            result["partial_response"] = next(reversed(streamed.values()))[:2000]
        return result

    def record_steering(event):
        write(f"{STEERING_OUTCOMES[event['kind']]}: {terminal_text(event['text'])}")
        if checkpoint:
            try:
                checkpoint(event)
            except (OSError, ValueError, sqlite3.Error):
                write("Could not save steering activity.")

    try:
        while True:
            try:
                event = events.get(timeout=0.1)
            except Empty:
                continue
            if event is done:
                if partial_line:
                    write()
                return completed_result(result)
            kind = event["kind"]
            if checkpoint and kind in ("goal_status", "goal_progress"):
                try:
                    checkpoint(event)
                except (OSError, ValueError, sqlite3.Error):
                    write("Could not save goal progress. The active run will continue.")
                    checkpoint = None
            if checkpoint and kind in ("project_change", "image_generated", "subagent_tools_unsupported"):
                try:
                    checkpoint(event)
                except (OSError, ValueError, sqlite3.Error):
                    write("Could not save run activity. The active run will continue.")
            if kind == "finished":
                result = event
            if kind == "model_delta":
                key = event["stream_id"]
                streamed[key] = streamed.get(key, "") + event["text"]
                write(terminal_text(event["text"]), end="", flush=True)
                partial_line = True
                continue
            if kind == "model_response":
                prefix = streamed.pop(event.get("stream_id"), "")
                response = event.get("text", "")
                if prefix and response.startswith(prefix):
                    suffix = response[len(prefix):]
                    if suffix or partial_line:
                        write(terminal_text(suffix))
                    partial_line = False
                else:
                    if partial_line:
                        write()
                        partial_line = False
                    if response:
                        write(terminal_text(response))
                if event.get("thinking"):
                    write("Model thinking:\n" + terminal_text(event["thinking"]))
                continue
            if partial_line:
                write()
                partial_line = False
            if kind in ("edit_proposal", "operation_proposal"):
                if not worker.approval_pending(event["fingerprint"]):
                    write("Skipped an approval prompt that is no longer active.")
                    continue
                proposal = event["proposal"]
                if kind == "edit_proposal":
                    fields = ("cwd", "path", "diff")
                elif proposal.get("operation") == "run_shell":
                    write("This command runs as your account, inherits the terminal environment, "
                          "and is not confined to the project.")
                    fields = ("purpose", "test_format", "cwd", "shell", "command", "max_seconds", "max_output_bytes")
                elif proposal.get("operation") == "machine_patch_file":
                    fields = ("operation", "path", "diff")
                elif proposal.get("operation") == "machine_create_file":
                    fields = ("operation", "path", "content")
                elif proposal.get("operation") == "machine_create_directory":
                    fields = ("operation", "path")
                elif proposal.get("operation") in ("delete_file", "create_directory", "move_file", "move_directory"):
                    fields = ("operation", "cwd", "path", "destination", "entries")
                elif proposal.get("operation") in ("git_stage", "git_unstage", "git_create_branch",
                                                   "git_commit", "git_commit_staged"):
                    fields = ("operation", "cwd", "reference", "head", "paths", "name", "identity", "message", "diff")
                elif proposal.get("operation") == "image_gen":
                    write("Approval sends the prompt and any listed reference images to the configured image provider.")
                    fields = ("operation", "endpoint", "model", "prompt", "references",
                              "aspect_ratio", "background", "cwd", "path")
                elif proposal.get("operation") == "subagent_file_transfer":
                    write("Approval sends this file snapshot to the selected model for the subagent task.")
                    fields = ("cwd", "path", "destination", "model", "child", "task", "payload_bytes", "diff")
                elif proposal.get("operation") == "mcp_start":
                    fields = ("operation", "server", "command", "arguments", "working_directory", "environment")
                    write("The local server runs as your user and inherits the terminal environment.")
                elif proposal.get("operation") == "mcp_connect":
                    fields = ("operation", "server", "url")
                    write("The server receives an initialization request and any configured bearer token.")
                elif proposal.get("operation") in ("mcp_call", "mcp_call_remote"):
                    fields = ("operation", "server", "url", "tool", "description", "arguments")
                elif proposal.get("operation") in ("mcp_list_resources", "mcp_read_resource"):
                    fields = ("operation", "server", "url", "command", "server_arguments", "resource")
                elif proposal.get("operation") in ("mcp_list_resource_templates", "mcp_read_resource_template"):
                    fields = ("operation", "server", "url", "command", "server_arguments", "template", "variables", "uri")
                elif proposal.get("operation") in ("mcp_list_prompts", "mcp_get_prompt"):
                    fields = ("operation", "server", "url", "command", "server_arguments", "prompt", "arguments")
                elif proposal.get("operation") == "mcp_complete_argument":
                    fields = ("operation", "server", "url", "kind", "target", "argument", "value", "context")
                else:
                    write("This operation cannot be reviewed in the terminal preview. Rejected.")
                    worker.decide(event["fingerprint"], False)
                    continue
                for field in fields:
                    if field in proposal:
                        label = "snapshot" if field == "diff" and proposal.get("operation") == "subagent_file_transfer" else field
                        write(f"{label}: {terminal_text(proposal[field])}")
                write("Type /steer MESSAGE to redirect the run instead of deciding this proposal.")
                if advice and proposal.get("operation") == "run_shell":
                    response = input("Approve once? [y/N/a for System One advice] ").strip()
                    if response.lower() == "a":
                        def still_pending():
                            return worker.approval_pending(event["fingerprint"])

                        if still_pending():
                            show_shell_advice(advice, proposal, run.cancel, write, is_pending=still_pending)
                        if not still_pending():
                            write("Skipped an approval prompt that is no longer active.")
                            continue
                        response = input("Approve once? [y/N] ").strip()
                else:
                    response = input("Approve once? [y/N] ").strip()
                while response == "/steer" or response.startswith("/steer "):
                    message = response.removeprefix("/steer").strip()
                    if message and worker.steer(message, approval_fingerprint=event["fingerprint"]):
                        write("Steering queued. The pending proposal was not approved.")
                        response = None
                        break
                    if not worker.approval_pending(event["fingerprint"]):
                        write("This approval prompt is no longer active. Your steering was not queued.")
                        response = None
                        break
                    write("Steering not queued. Enter /steer MESSAGE or decide the proposal.")
                    response = input("Approve once? [y/N] ").strip()
                if response is None:
                    continue
                if worker.decide(event["fingerprint"], response.lower() == "y") is False:
                    write("This approval prompt is no longer active. Your answer was not applied.")
            elif kind in STEERING_OUTCOMES:
                record_steering(event)
                if kind == "steering_delivered":
                    acknowledge = getattr(run, "acknowledge_steering", None)
                    if acknowledge is not None:
                        acknowledge(event["text"])
            elif kind in ("output", "finished"):
                if event.get("text") and not (kind == "finished" and event.get("response_shown")):
                    write(terminal_text(event["text"]))
                if kind == "finished" and event.get("usage"):
                    write(terminal_text(event["usage"]))
            elif kind == "plan":
                try:
                    rendered = terminal_plan(event.get("plan"))
                except ValueError:
                    continue
                write(rendered)
                if checkpoint:
                    try:
                        checkpoint(event)
                    except (OSError, ValueError, sqlite3.Error):
                        write("Could not save the plan update. The active run will continue.")
            elif kind == "goal_status":
                goal_detail = event["detail"]
                write(terminal_text(f"Goal {event['status']} (model reported): {event['detail']}"))
            elif kind == "goal_progress":
                write(f"Goal progress: {event['steps']} steps · {event['seconds']:.0f}s")
    except (KeyboardInterrupt, EOFError):
        if result:
            # A late interrupt must not rewrite a result already delivered by the worker.
            return completed_result(result)
        steering = worker.stop()
        write("\nStopping Code run…")
        if isinstance(steering, dict):
            for outcome in ("delivered", "uncertain", "undelivered"):
                for message in steering.get(outcome, ()):
                    record_steering({"kind": f"steering_{outcome}", "text": message})
        detail = ("Cancelled locally. A submitted request may still finish on its server. "
                  "Check the project before continuing. Agentnik will not replay the request.")
        write(detail)
        return completed_result({"status": "cancelled", "text": detail, "last_goal_detail": goal_detail})
    finally:
        worker.stop()
        worker.join()
