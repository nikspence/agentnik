"""Terminal access to shared Code settings."""

from .code_limits import FIELDS, coding_limits


def configure_code(store, arguments):
    """Apply a single validated setting change or describe current values."""
    settings = store.config["settings"]
    limits = coding_limits(settings.get("coding_limits"))
    if not arguments:
        tls = "relaxed" if settings.get("relaxed_tls") else "strict"
        lines = [f"TLS verification: {tls}"]
        for key, (default, low, high) in FIELDS.items():
            lines.append(f"{key}: {limits[key]} (range {low}–{high}, default {default})")
        lines.extend((
            "Use /settings limits NAME VALUE (or default).",
            "Use /settings tls strict or /settings tls relaxed.",
        ))
        return "\n".join(lines)

    if len(arguments) == 3 and arguments[0] == "limits":
        _, key, value = arguments
        if key not in FIELDS:
            raise ValueError("Unknown coding limit. Use /settings to list limits.")
        try:
            limits[key] = FIELDS[key][0] if value == "default" else int(value)
        except ValueError:
            raise ValueError("Use a whole number or default.") from None
        settings["coding_limits"] = coding_limits(limits)
    elif arguments in (["tls", "strict"], ["tls", "relaxed"]):
        settings["relaxed_tls"] = arguments[1] == "relaxed"
    else:
        raise ValueError("Use /settings to see supported settings and syntax.")
    store.flush()
    return "Saved shared setting. It applies to the next terminal run."
