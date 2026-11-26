"""Terminal access to shared Code settings."""

from .code_limits import FIELDS, GOAL_FIELDS, UNLIMITED_FIELDS, coding_limits, goal_limits
from .localization import choices


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
        ))
        return "\n".join(lines)

    if arguments[0] == "appearance":
        lines = appearance(settings, arguments[1:])
        if lines is not None:
            return lines
        store.flush()
        return "Saved desktop appearance setting. It applies when the desktop app next starts."
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
    else:
        raise ValueError("Use /settings to see supported settings and syntax.")
    store.flush()
    return "Saved shared setting. It applies to the next terminal run."
