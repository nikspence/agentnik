"""Terminal adapter for Agentnik's existing Code run and approval contract."""

from queue import Empty, Queue
import sqlite3
from threading import Thread
import unicodedata


def terminal_text(text):
    return "".join(
        ch if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
        else repr(ch)[1:-1]
        for ch in str(text)
    )


def project_diff(root, argument):
    from .code_agent import ProjectFiles
    from .git_service import GitService

    git = GitService(ProjectFiles(root))
    if not argument:
        status = git.inspect("git_status")
        return "\n".join([
            *(f"Staged: {path!r}" for path in status["staged"]),
            *(f"Unstaged: {path!r}" for path in status["unstaged"]),
            status["scope"],
            "Use /diff PATH to compare with HEAD or /diff --staged PATH to review the index.",
        ])
    staged = argument == "--staged" or argument.startswith("--staged ")
    path = argument.partition(" ")[2].strip() if staged else argument
    if not path:
        raise ValueError("Provide a project-relative file after --staged.")
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


def load_run_settings(data_dir, name, model, web_enabled=False, discovered=None, mcp_selection=(), root=None):
    from importlib.util import find_spec
    from . import core, tls
    from .code_research import code_research_options
    from .image_settings import image_endpoint, validate_image_settings
    from .storage import Store

    store = Store(data_dir)
    try:
        connections = {**(discovered or {}), **core.environment_connections(), **store.connections()}
        connection = connections.get(name)
        if connection is None:
            raise ValueError("Unknown connection. Use /connections to list names.")
        connection = dict(connection)
        core.base_url(connection.get("url", ""))
        if model:
            connection["model"] = model
        if not connection.get("model"):
            raise ValueError("No model selected. Use /model to specify one.")
        settings = store.config["settings"]
        tls.configure(settings.get("relaxed_tls", False))
        options = code_research_options(store, name, connection, web_enabled,
                                        mcp_first=bool(mcp_selection) and settings.get("mcp_priority", "first") == "first")
        if mcp_selection:
            options.update(mcp_bridges=terminal_mcp_bridges(store.config, mcp_selection),
                           mcp_priority=settings.get("mcp_priority", "first"))
        image = validate_image_settings(settings.get("image_generation"))
        if image["enabled"]:
            if find_spec("PySide6") is None and find_spec("PIL") is None:
                raise ValueError("Install the Agentnik terminal extra for headless image generation.")
            image_connection = connections.get(image["connection"])
            if not image_connection or not image["model"]:
                raise ValueError("The configured image connection or model is unavailable.")
            image_endpoint(image_connection, image["endpoint"])
            options["image_config"] = {
                "connection": image_connection, "model": image["model"], "endpoint": image["endpoint"],
            }
        binding = settings.get("decision_model", {})
        advisor = connections.get(binding.get("connection")) if settings.get("decision_advice_enabled") else None
        advice = dict(advisor, model=binding["model"]) if advisor and binding.get("model") else None
        if root is not None:
            from .code_history import same_project
            from .repositories import RepositoryRegistry

            registry = RepositoryRegistry(store)
            ident = next((row["id"] for row in registry.list() if same_project(row["path"], root)), None)
            if ident:
                options["git_author"] = registry.git_author(ident)
        return connection, settings.get("coding_limits"), settings.get("coding_goal_limits"), options, advice
    finally:
        store.db.close()


def show_shell_advice(connection, proposal, cancel, write):
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
    try:
        result = decision_advice.parse_advice(decision_advice.request(connection, proposal, cancel))
    except Exception:
        write("System One advice unavailable. Review the command yourself.")
        return
    confidence = result["confidence"]
    suffix = "" if confidence is None else f" · {confidence:.0%} confidence"
    write(f"System One advice: {result['category'].upper()}{suffix}. You still decide.")


def drive_run(run, write=print, advice=None, checkpoint=None):
    events = Queue()
    done = object()

    def worker():
        try:
            run.run(events.put)
        except Exception:
            events.put({"kind": "finished", "text": "Coding run failed to start or stopped unexpectedly."})
        finally:
            events.put(done)

    thread = Thread(target=worker)
    thread.start()
    streamed = {}
    partial_line = False
    result = {}
    goal_detail = ""
    try:
        while True:
            try:
                event = events.get(timeout=0.1)
            except Empty:
                continue
            if event is done:
                if partial_line:
                    write()
                return dict(result, last_goal_detail=goal_detail) if goal_detail else result
            kind = event["kind"]
            if checkpoint and kind in ("goal_status", "goal_progress"):
                try:
                    checkpoint(event)
                except (OSError, ValueError, sqlite3.Error):
                    write("Could not save goal progress. The active run will continue.")
                    checkpoint = None
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
                if partial_line and prefix and response.startswith(prefix):
                    write(terminal_text(response[len(prefix):]))
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
                proposal = event["proposal"]
                if kind == "edit_proposal":
                    fields = ("cwd", "path", "diff")
                elif proposal.get("operation") == "run_shell":
                    fields = ("cwd", "shell", "command", "max_seconds")
                elif proposal.get("operation") in ("delete_file", "create_directory", "move_file", "move_directory"):
                    fields = ("operation", "cwd", "path", "destination", "entries")
                elif proposal.get("operation") == "image_gen":
                    fields = ("operation", "endpoint", "model", "prompt", "references",
                              "aspect_ratio", "background", "cwd", "path")
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
                    run.decide(event["fingerprint"], False)
                    continue
                for field in fields:
                    if field in proposal:
                        write(f"{field}: {terminal_text(proposal[field])}")
                if advice and proposal.get("operation") == "run_shell":
                    response = input("Approve once? [y/N/a for System One advice] ").strip().lower()
                    if response == "a":
                        show_shell_advice(advice, proposal, run.cancel, write)
                        response = input("Approve once? [y/N] ").strip().lower()
                else:
                    response = input("Approve once? [y/N] ").strip().lower()
                approved = response == "y"
                run.decide(event["fingerprint"], approved)
            elif kind in ("output", "finished"):
                if event.get("text") and not (kind == "finished" and event.get("response_shown")):
                    write(terminal_text(event["text"]))
                if kind == "finished" and event.get("usage"):
                    write(terminal_text(event["usage"]))
            elif kind == "goal_status":
                goal_detail = event["detail"]
                write(terminal_text(f"Goal {event['status']} (model reported): {event['detail']}"))
            elif kind == "goal_progress":
                write(f"Goal progress: {event['steps']} steps · {event['seconds']:.0f}s")
    except (KeyboardInterrupt, EOFError):
        run.stop()
        write("\nStopping Code run…")
        detail = ("Cancelled locally. A submitted request may still finish on its server. "
                  "Check the project before continuing. Agentnik will not replay the request.")
        write(detail)
        return {"status": "cancelled", "text": detail, "last_goal_detail": goal_detail}
    finally:
        run.stop()
        thread.join()
