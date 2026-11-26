"""Terminal access to shared Code settings."""

from getpass import GetPassWarning, getpass
import os
import warnings

from .code_limits import FIELDS, GOAL_FIELDS, UNLIMITED_FIELDS, coding_limits, goal_limits
from .localization import choices
from .image_settings import image_endpoint, validate_image_settings
from .search_providers import SEARCH_PROVIDERS


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


def configure_code(store, arguments):
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
            "Use /settings limits NAME VALUE (or default).",
            "Use /settings goal steps|seconds VALUE (or default).",
            "Use /settings tls strict or /settings tls relaxed.",
            "Use /settings appearance to manage desktop appearance and layout.",
            "Use /settings web access public_fetch|strict_public or /settings web priority provider|managed.",
            "Use /settings web providers to manage search provider credentials.",
            "Use /settings image to configure the image model.",
            "Use /settings decision to configure System One shell advice.",
        ))
        return "\n".join(lines)

    if arguments[0] == "appearance":
        lines = appearance(settings, arguments[1:])
        if lines is not None:
            return lines
        store.flush()
        return "Saved desktop appearance setting. It applies when the desktop app next starts."
    if arguments[:2] == ["web", "providers"]:
        return web_providers(store, arguments[2:])
    if arguments[0] == "image":
        return configure_image(store, arguments[1:])
    if arguments[0] == "decision":
        return configure_decision(store, arguments[1:])
    if len(arguments) == 3 and arguments[0] in ("limits", "goal"):
        section, key, value = arguments
        fields, validator, setting = (
            (GOAL_FIELDS, goal_limits, "coding_goal_limits") if section == "goal"
            else (FIELDS, coding_limits, "coding_limits")
        )
        if key not in fields:
            raise ValueError("Unknown limit. Use /settings to list limits.")
        values = validator(settings.get(setting))
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
    else:
        raise ValueError("Use /settings to see supported settings and syntax.")
    store.flush()
    return "Saved shared setting. It applies to the next terminal run."
