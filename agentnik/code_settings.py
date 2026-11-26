"""Terminal access to shared Code settings."""

from getpass import GetPassWarning, getpass
import json
import os
from uuid import uuid4
import warnings

from .code_limits import FIELDS, GOAL_FIELDS, UNLIMITED_FIELDS, coding_limits, goal_limits
from .localization import choices
from .image_settings import image_endpoint, validate_image_settings
from .search_providers import SEARCH_PROVIDERS
from .tools import CHAT_LIMIT_FIELDS, chat_limits


def configure_mcp_token(store, servers, name):
    from .mcp_support import validate_servers
    import keyring

    selected = next((item for item in servers if item["name"] == name and item.get("transport") == "http"), None)
    if selected is None:
        raise ValueError("Choose a saved HTTPS MCP server.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            token = getpass("Bearer token (blank to clear): ")
        if not token and input("Clear this server's saved credential? [y/N] ").strip().lower() != "y":
            return "MCP credential unchanged."
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        return "MCP credential setup cancelled."
    if token and (len(token) > 4096 or any(not 33 <= ord(ch) <= 126 for ch in token)):
        raise ValueError("Bearer token must be a single visible ASCII token.")

    credential = uuid4().hex if token else ""
    updated = dict(selected, credential_id=credential)
    updated.pop("auth_type", None)
    entries = validate_servers([updated if item is selected else item for item in servers])
    if credential:
        try:
            keyring.set_password("Agentnik", credential, token)
        except Exception:
            return "Could not save the MCP credential in the OS credential store."
    store.config["mcp_servers"] = entries
    try:
        store.flush()
    except OSError:
        store.config["mcp_servers"] = servers
        if credential:
            try:
                keyring.delete_password("Agentnik", credential)
            except Exception:
                pass
        raise
    if selected.get("credential_id"):
        try:
            keyring.delete_password("Agentnik", selected["credential_id"])
        except Exception:
            return "Updated MCP settings. The previous credential could not be removed from the OS store."
    return "Updated MCP credential. No server was contacted."


def configure_mcp_signin(store, name):
    from . import tls
    from .code_terminal import terminal_text
    from .mcp_oauth_record import write_record
    from .mcp_oauth_signin import sign_in
    from .mcp_support import validate_servers
    from .storage import load_config
    import keyring

    profiles = store.config.get("mcp_servers", [])
    server = next((item for item in profiles if item["name"] == name and item.get("transport") == "http"), None)
    if server is None:
        raise ValueError("Choose a saved HTTPS MCP profile.")
    tls.configure(store.config["settings"].get("relaxed_tls", False))

    def present(url, port):
        print(f"On SSH, forward this port from your browser machine: ssh -N -L 127.0.0.1:{port}:127.0.0.1:{port} HOST")
        print("Open this link in your browser within three minutes:")
        print(terminal_text(url), flush=True)

    try:
        client_id = input("Registered public OAuth client ID: ").strip()
        scope = input("Scopes (optional, space separated): ").strip()
        record = sign_in(server["url"], client_id, scope, present)
    except (EOFError, KeyboardInterrupt):
        return "OAuth sign-in stopped. No credential was changed."
    config = load_config(store.config_path)
    current = config.get("mcp_servers", [])
    if server not in current:
        raise ValueError("The selected MCP profile changed during sign-in. No credential was saved.")
    credential = uuid4().hex
    replacement = dict(server, credential_id=credential, auth_type="oauth")
    config["mcp_servers"] = validate_servers([replacement if item == server else item for item in current])
    try:
        write_record(credential, record)
    except Exception:
        raise ValueError("Could not save the OAuth sign-in in the OS credential store.") from None
    before, store.config = store.config, config
    try:
        store.flush()
    except OSError:
        store.config = before
        try:
            keyring.delete_password("Agentnik", credential)
        except Exception:
            pass
        raise
    if server.get("credential_id"):
        try:
            keyring.delete_password("Agentnik", server["credential_id"])
        except Exception:
            return "Saved OAuth sign-in. The old credential could not be removed from the OS store."
    return "Saved MCP OAuth sign-in in the OS credential store."


def configure_mcp(store, arguments):
    from .mcp_support import DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, server_timeout, validate_servers

    settings = store.config["settings"]
    servers = store.config.get("mcp_servers", [])
    if not arguments:
        return "\n".join([
            f"Desktop MCP access: {'on' if settings.get('mcp_access_enabled', True) else 'off'}",
            f"Conflicting tools: MCP {settings.get('mcp_priority', 'first')}",
            *(f"{item['name']!r} · {'HTTPS' if item.get('transport') == 'http' else 'local'}"
              f" · {'enabled' if item['enabled'] else 'disabled'} · {server_timeout(item)}s timeout" for item in servers),
            "Use /settings mcp on|off, priority first|last, or enable|disable NAME.",
            "Use /settings mcp add-https to save an HTTPS server without credentials.",
            "Use /settings mcp edit-https NAME to rename an HTTPS profile or change its URL.",
            "Use /settings mcp add-local to save a local executable or remove NAME to remove a server.",
            "Use /settings mcp edit-local NAME to edit a local server without starting it.",
            "Use /settings mcp token NAME to set, rotate, or clear an HTTPS bearer token.",
            "Use /settings mcp renew NAME to renew an existing OAuth sign-in.",
            "Use /settings mcp signin NAME with a registered public OAuth client.",
            f"Use /settings mcp timeout SECONDS NAME (1–{MAX_TIMEOUT_SECONDS}, or default).",
        ])
    if len(arguments) >= 2 and arguments[0] == "token":
        return configure_mcp_token(store, servers, " ".join(arguments[1:]))
    if len(arguments) >= 2 and arguments[0] == "signin":
        return configure_mcp_signin(store, " ".join(arguments[1:]))
    if len(arguments) >= 2 and arguments[0] == "edit-https":
        from .code_terminal import terminal_text

        name = " ".join(arguments[1:])
        selected = next((item for item in servers if item["name"] == name and item.get("transport") == "http"), None)
        if selected is None:
            raise ValueError("Choose a saved HTTPS MCP profile.")
        try:
            new_name = input(f"Server name [{terminal_text(name)!r}]: ").strip() or name
            old_url = selected["url"]
            url = input(f"Server HTTPS URL [{terminal_text(old_url)!r}]: ").strip() or old_url
        except (EOFError, KeyboardInterrupt):
            return "MCP setup cancelled."
        if url != old_url and selected.get("credential_id"):
            raise ValueError("Clear the saved credential before changing the HTTPS URL.")
        replacement = dict(selected, name=new_name, url=url)
        store.config["mcp_servers"] = validate_servers([replacement if item is selected else item for item in servers])
        store.flush()
        return "Updated HTTPS MCP profile. No server was contacted."
    if len(arguments) >= 2 and arguments[0] == "edit-local":
        from .code_terminal import terminal_text

        name = " ".join(arguments[1:])
        selected = next((item for item in servers if item["name"] == name and item.get("transport") != "http"), None)
        if selected is None:
            raise ValueError("Choose a saved local MCP profile.")
        try:
            new_name = input(f"Server name [{terminal_text(name)!r}]: ").strip() or name
            command = input(f"Local executable [{terminal_text(selected['command'])!r}]: ").strip()
            args = input("Arguments as a JSON list (blank keeps current, [] clears): ").strip()
            directory = input("Absolute working directory (blank keeps current, - clears): ").strip()
            env = input("Environment variable name mappings as JSON (blank keeps current, {} clears): ").strip()
        except (EOFError, KeyboardInterrupt):
            return "MCP setup cancelled."
        replacement = dict(selected, name=new_name, command=command or selected["command"])
        if args:
            replacement["args"] = json.loads(args)
        if directory:
            replacement["working_directory"] = "" if directory == "-" else directory
        if env:
            replacement["env"] = json.loads(env)
        store.config["mcp_servers"] = validate_servers([replacement if item is selected else item for item in servers])
        store.flush()
        return "Updated local MCP profile. No server was started."
    if len(arguments) >= 2 and arguments[0] == "renew":
        from . import tls
        from .code_terminal import terminal_text
        from .mcp_oauth_terminal import renew_mcp_credential

        name = " ".join(arguments[1:])
        server = next((item for item in servers if item["name"] == name and item.get("auth_type") == "oauth"), None)
        if server is None:
            raise ValueError("Choose a saved MCP OAuth profile.")
        tls.configure(settings.get("relaxed_tls", False))

        def confirm(endpoint):
            print("Send the saved refresh credential to " + terminal_text(endpoint) + ".")
            return input("Renew this sign-in? [y/N] ").strip().lower() == "y"

        try:
            return renew_mcp_credential(server, confirm)
        except (EOFError, KeyboardInterrupt):
            return "OAuth renewal stopped. If already sent, the request will not be retried."
    if arguments in (["on"], ["off"]):
        settings["mcp_access_enabled"] = arguments == ["on"]
    elif arguments in (["priority", "first"], ["priority", "last"]):
        settings["mcp_priority"] = arguments[1]
    elif len(arguments) >= 3 and arguments[0] == "timeout":
        name = " ".join(arguments[2:])
        if not any(item["name"] == name for item in servers):
            raise ValueError("No saved MCP server with that name.")
        try:
            seconds = DEFAULT_TIMEOUT_SECONDS if arguments[1] == "default" else int(arguments[1])
        except ValueError:
            raise ValueError("Use whole seconds or default.") from None
        if not 1 <= seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"MCP timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds.")
        updated = [dict(item, timeout_seconds=seconds) if item["name"] == name else item for item in servers]
        store.config["mcp_servers"] = validate_servers(updated)
    elif len(arguments) >= 2 and arguments[0] in ("enable", "disable", "remove"):
        name = " ".join(arguments[1:])
        selected = next((item for item in servers if item["name"] == name), None)
        if selected is None:
            raise ValueError("No saved MCP server with that name.")
        if arguments[0] == "remove":
            try:
                if input(f"Remove saved MCP server {name!r}? [y/N] ").strip().lower() != "y":
                    return "MCP server unchanged."
            except (EOFError, KeyboardInterrupt):
                return "MCP setup cancelled."
            store.config["mcp_servers"] = validate_servers([item for item in servers if item is not selected])
            store.flush()
            if selected.get("credential_id"):
                import keyring

                try:
                    keyring.delete_password("Agentnik", selected["credential_id"])
                except Exception:
                    return "Removed saved MCP server. Its credential could not be removed from the OS store."
            return "Removed saved MCP server. No server was contacted."
        updated = [dict(item, enabled=arguments[0] == "enable") if item["name"] == name else item
                   for item in servers]
        store.config["mcp_servers"] = validate_servers(updated)
    elif arguments in (["add-https"], ["add-local"]):
        try:
            name = input("New server name: ").strip()
            if arguments == ["add-https"]:
                url = input("Server HTTPS URL: ").strip()
                server = {"name": name, "url": url, "transport": "http", "credential_id": "", "enabled": False}
            else:
                command = input("Local executable: ").strip()
                args = json.loads(input('Arguments as a JSON list (blank for none): ').strip() or "[]")
                directory = input("Absolute working directory (optional): ").strip()
                environment = json.loads(
                    input('Environment variable name mappings as JSON (blank for none): ').strip() or "{}"
                )
                server = {"name": name, "command": command, "args": args, "enabled": False,
                          "working_directory": directory, "env": environment}
        except (EOFError, KeyboardInterrupt):
            return "MCP setup cancelled."
        store.config["mcp_servers"] = validate_servers([*servers, server])
    else:
        raise ValueError("Use /settings mcp to list supported operations.")
    store.flush()
    return "Saved desktop MCP settings. No server was contacted."


def configure_decision(store, arguments):
    from .core import base_url, environment_connections

    settings = store.config["settings"]
    binding = dict(settings.get("decision_model", {"connection": "", "model": ""}))
    enabled = settings.get("decision_advice_enabled", False)
    if not arguments:
        return (f"System One shell advice: {'on' if enabled else 'off'}\n"
                f"Connection: {binding['connection']!r} · Model: {binding['model']!r}\n"
                "Use /settings decision set to configure, or /settings decision on|off.")
    if arguments not in (["set"], ["on"], ["off"]):
        raise ValueError("Use /settings decision set, on, or off.")
    if arguments == ["set"]:
        try:
            name = input(f"Decision connection [{binding['connection']!r}]: ").strip()
            model = input(f"Decision model [{binding['model']!r}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "Decision setup cancelled."
        binding = {"connection": name or binding["connection"], "model": model or binding["model"]}
    else:
        enabled = arguments == ["on"]
    if arguments != ["off"]:
        connections = {**environment_connections(), **store.config["connections"]}
        connection = connections.get(binding["connection"])
        if not connection or not binding["model"] or any(len(value) > 512 for value in binding.values()):
            raise ValueError("Choose an available connection and a Decision model of at most 512 characters.")
        base_url(connection.get("url", ""))
    settings.update(decision_model=binding, decision_advice_enabled=enabled)
    store.flush()
    return "Saved shell advice settings. No model was contacted."


def configure_image(store, arguments):
    from .core import environment_connections

    settings = store.config["settings"]
    image = validate_image_settings(settings.get("image_generation"))
    if not arguments:
        return (f"Image tool: {'on' if image['enabled'] else 'off'}\n"
                f"Connection: {image['connection']!r} · Model: {image['model']!r}\n"
                "Use /settings image set to configure, or /settings image on|off.")
    if arguments not in (["set"], ["on"], ["off"]):
        raise ValueError("Use /settings image set, on, or off.")
    if arguments == ["set"]:
        try:
            name = input(f"Image connection [{image['connection']!r}]: ").strip() or image["connection"]
            model = input(f"Image model [{image['model']!r}]: ").strip() or image["model"]
            endpoint = input("Image endpoint override (blank for connection default): ").strip()
        except (EOFError, KeyboardInterrupt):
            return "Image setup cancelled."
        image.update(connection=name, model=model, endpoint=endpoint)
    else:
        image["enabled"] = arguments == ["on"]
    if arguments != ["off"]:
        connections = {**environment_connections(), **store.config["connections"]}
        connection = connections.get(image["connection"])
        if not connection or not image["model"]:
            raise ValueError("Choose an available connection and an image model.")
        image_endpoint(connection, image["endpoint"])
    settings["image_generation"] = validate_image_settings(image)
    store.flush()
    return "Saved image settings. They apply to the next run."


def web_providers(store, arguments):
    profiles = store.config.get("web_backends", [])
    if not arguments:
        lines = [f"{item['id']!r}: {item.get('kind', 'ollama')!r} (saved)" for item in profiles]
        ids = {item["id"] for item in profiles}
        lines.extend(f"{ident}: {kind} (environment)" for kind, (_, variable, ident) in SEARCH_PROVIDERS.items()
                     if ident not in ids and variable and os.getenv(variable))
        return "\n".join([
            *(lines or ["No saved or environment search providers."]),
            "Provider kinds: " + ", ".join(SEARCH_PROVIDERS) + ".",
            "Use /settings web providers set KIND to add a provider or rotate its key.",
            "Use /settings web providers remove ID to remove a saved provider.",
        ])
    if len(arguments) != 2:
        raise ValueError("Use /settings web providers to list available operations.")
    action, name = arguments
    try:
        if action == "remove":
            if not any(item["id"] == name for item in profiles):
                raise ValueError("No saved search provider with that ID.")
            if input(f"Remove saved search provider {name!r}? [y/N] ").strip().lower() != "y":
                return "Search provider unchanged."
            store.save_web_key(remove=True, ident=name)
            return "Removed saved search provider. Environment credentials can still be detected."
        if action != "set" or name not in SEARCH_PROVIDERS:
            raise ValueError("Choose a provider kind listed by /settings web providers.")
        label, _, ident = SEARCH_PROVIDERS[name]
        key = ""
        plaintext = False
        if name != "firecrawl-keyless":
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                key = getpass(f"{label} API key: ")
            if not key:
                return "Search provider unchanged."
            plaintext = input("Store key as plaintext on this machine? [y/N] ").strip().lower() == "y"
        try:
            store.save_web_key(key, plaintext=plaintext, ident=ident, name=label, kind=name)
        except ValueError:
            raise
        except Exception:
            return "Could not save search provider. Check storage and credential store availability."
        return f"Saved search provider {ident}."
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        return "Search provider setup cancelled."


APPEARANCE = {
    "theme": ("theme", "System"),
    "language": ("language", "system"),
    "font": ("font_size", "system default"),
    "composer": ("composer_height", 64),
    "prompts": ("prompts_visible", True),
    "history": ("history_visible", True),
}


def appearance(settings, arguments):
    languages = dict(choices())
    if not arguments:
        return "\n".join([
            *(f"{name}: {settings.get(key, default)!r}" for name, (key, default) in APPEARANCE.items()),
            "Use /settings appearance FIELD VALUE (or default).",
            "Themes: system, light, dark. Languages: " + ", ".join(languages) + ".",
            "Font: 8–32 points. Composer: positive pixel height. Prompts/history: show or hide.",
        ])
    if len(arguments) != 2 or arguments[0] not in APPEARANCE:
        raise ValueError("Use /settings appearance to list fields and values.")
    name, value = arguments
    key, _ = APPEARANCE[name]
    if value == "default":
        settings.pop(key, None)
    elif name == "theme" and value.lower() in ("system", "light", "dark"):
        settings[key] = value.title()
    elif name == "language" and value in languages:
        settings[key] = value
    elif name in ("prompts", "history") and value in ("show", "hide"):
        settings[key] = value == "show"
    elif name in ("font", "composer"):
        try:
            size = int(value)
        except ValueError:
            raise ValueError("Use a whole number or default.") from None
        if (name == "font" and not 8 <= size <= 32) or size < 1:
            raise ValueError("Font must be 8–32 points and composer height must be positive.")
        settings[key] = size
    else:
        raise ValueError("Invalid appearance value. Use /settings appearance to list choices.")
    return None


def configure_git_author(store, root, arguments):
    from .code_history import same_project
    from .repositories import RepositoryRegistry, validate_git_author

    if root is None:
        raise ValueError("Open a project to manage its Git author.")
    registry = RepositoryRegistry(store)
    ident = next((row["id"] for row in registry.list() if same_project(row["path"], root)), None)
    author = registry.git_author(ident) if ident else None
    if not arguments:
        current = f"{author['name']!r} <{author['email']}>" if author else "No project override."
        return current + "\nUse /settings git-author set or /settings git-author clear."
    if arguments == ["clear"]:
        if ident and author:
            registry.set_git_author(ident, None)
        return "Using the repository or user Git identity."
    if arguments != ["set"]:
        raise ValueError("Use /settings git-author set or /settings git-author clear.")
    try:
        name = input("Git author name: ")
        email = input("Git author email: ")
    except (EOFError, KeyboardInterrupt):
        return "Git author unchanged."
    author = validate_git_author({"name": name, "email": email})
    if not author:
        raise ValueError("Enter an author name and email, or use /settings git-author clear.")
    registry.set_git_author(ident or registry.put(root), author)
    return "Saved the Git author override for this project."


def configure_code(store, arguments, root=None):
    """Apply a single validated setting change or describe current values."""
    settings = store.config["settings"]
    limits = coding_limits(settings.get("coding_limits"))
    if not arguments:
        tls = "relaxed" if settings.get("relaxed_tls") else "strict"
        lines = [f"TLS verification: {tls}"]
        for key, (default, low, high) in FIELDS.items():
            optional = ", 0 means unlimited" if key in UNLIMITED_FIELDS else ""
            lines.append(f"{key}: {limits[key]} (range {low}–{high}, default {default}{optional})")
        goals = goal_limits(settings.get("coding_goal_limits"))
        for key, (_, low, high) in GOAL_FIELDS.items():
            lines.append(f"goal {key}: {goals[key]} (range {low}–{high}, 0 means unlimited)")
        lines.extend((
            "Use /settings limits NAME VALUE (or default, or unlimited where listed).",
            "Use /settings goal steps|seconds VALUE (or default or unlimited).",
            "Use /settings chat-limits to manage desktop Chat research budgets.",
            "Use /settings tls strict or /settings tls relaxed.",
            "Use /settings appearance to manage desktop appearance and layout.",
            "Use /settings web access public_fetch|strict_public or /settings web priority provider|managed.",
            "Use /settings web providers to manage search provider credentials.",
            "Use /settings image to configure the image model.",
            "Use /settings decision to configure System One shell advice.",
            "Use /settings git-author to manage the current project's Git author override.",
            "Use /settings mcp to manage desktop MCP preferences and saved servers.",
        ))
        return "\n".join(lines)

    if arguments[0] == "git-author":
        return configure_git_author(store, root, arguments[1:])
    if arguments[0] == "appearance":
        lines = appearance(settings, arguments[1:])
        if lines is not None:
            return lines
        store.flush()
        return "Saved desktop appearance setting. It applies when the desktop app next starts."
    if arguments[:2] == ["web", "providers"]:
        return web_providers(store, arguments[2:])
    if arguments == ["web"]:
        return "\n".join([
            f"Desktop web default: {'on' if settings.get('web_search_enabled', False) else 'off'}",
            f"Navigation policy: {settings.get('research_access_policy', 'public_fetch')}",
            f"Search priority: {settings.get('research_policy', 'Provider first')}",
            "Use /settings web desktop on|off, access public_fetch|strict_public, "
            "priority provider|managed, or providers.",
            "Terminal web access is selected per session with /web on or /web off.",
        ])
    if arguments[0] == "chat-limits":
        saved_limits = dict(settings.get("chat_research_limits") or {})
        if len(arguments) == 1:
            values = chat_limits(saved_limits)
            return "\n".join([
                *(f"{key}: {getattr(values, key)} (range {low}–{high})"
                  for key, (low, high) in CHAT_LIMIT_FIELDS.items()),
                "Use /settings chat-limits NAME VALUE (or default).",
            ])
        if len(arguments) != 3 or arguments[1] not in CHAT_LIMIT_FIELDS:
            raise ValueError("Use /settings chat-limits to see fields and ranges.")
        _, key, value = arguments
        if value == "default":
            saved_limits.pop(key, None)
        else:
            try:
                saved_limits[key] = int(value)
            except ValueError:
                raise ValueError("Use a whole number or default.") from None
        chat_limits(saved_limits)
        settings["chat_research_limits"] = saved_limits
        store.flush()
        return "Saved desktop Chat research limits."
    if arguments[0] == "image":
        return configure_image(store, arguments[1:])
    if arguments[0] == "decision":
        return configure_decision(store, arguments[1:])
    if arguments[0] == "mcp":
        return configure_mcp(store, arguments[1:])
    if len(arguments) == 3 and arguments[0] in ("limits", "goal"):
        section, key, value = arguments
        fields, validator, setting = (
            (GOAL_FIELDS, goal_limits, "coding_goal_limits") if section == "goal"
            else (FIELDS, coding_limits, "coding_limits")
        )
        if key not in fields:
            raise ValueError("Unknown limit. Use /settings to list limits.")
        values = validator(settings.get(setting))
        if value == "unlimited":
            if section != "goal" and key not in UNLIMITED_FIELDS:
                raise ValueError(f"{key} cannot be unlimited. Use /settings to see its range.")
            value = "0"
        try:
            values[key] = fields[key][0] if value == "default" else int(value)
        except ValueError:
            raise ValueError("Use a whole number or default.") from None
        settings[setting] = validator(values)
    elif arguments in (["tls", "strict"], ["tls", "relaxed"]):
        settings["relaxed_tls"] = arguments[1] == "relaxed"
    elif arguments[:2] == ["web", "access"] and arguments[2:] in (["public_fetch"], ["strict_public"]):
        settings["research_access_policy"] = arguments[2]
    elif arguments[:2] == ["web", "priority"] and arguments[2:] in (["provider"], ["managed"]):
        settings["research_policy"] = "Provider first" if arguments[2] == "provider" else "Agentnik first"
    elif arguments[:2] == ["web", "desktop"] and arguments[2:] in (["on"], ["off"]):
        settings["web_search_enabled"] = arguments[2] == "on"
    else:
        raise ValueError("Use /settings to see supported settings and syntax.")
    store.flush()
    return "Saved shared setting. It applies to the next terminal run."
