"""UI-independent settings shared by interactive Code clients."""

from .core import base_url
from .code_research import code_research_options
from .mcp_support import server_fingerprint
from .subagent_capabilities import unsupported


class CodeSelectionError(ValueError):
    """Missing connection or model selection, for client-specific guidance."""

    def __init__(self, field):
        self.field = field
        super().__init__(f"No {field} selected.")


def resolve_run_connection(connection, model=None):
    """Return a validated copy using the stored model only when no override was supplied."""
    if connection is None:
        raise CodeSelectionError("connection")
    resolved = dict(connection)
    if model is not None:
        resolved["model"] = model
    if not resolved.get("model"):
        raise CodeSelectionError("model")
    base_url(resolved.get("url", ""))
    return resolved


def resolve_mcp_profiles(config, refs):
    """Resolve ordered, enabled profiles only if their saved revisions still match."""
    if len(refs) > 5 or len({ref["name"] for ref in refs}) != len(refs):
        raise ValueError("Select at most five distinct MCP servers.")
    enabled = {server["name"]: server for server in config.get("mcp_servers", []) if server.get("enabled")}
    selected = []
    for ref in refs:
        profile = enabled.get(ref["name"])
        if profile is None or server_fingerprint(profile) != ref["sha256"]:
            raise ValueError("A selected MCP server changed or is unavailable. Reselect it or remove it.")
        selected.append(profile)
    return selected


def shared_run_options(store, name, connection, *, web_enabled, has_mcp, capability_connection, mcp_priority=None):
    """Resolve policy and budgets without opening a model request or MCP connection."""
    settings = store.config["settings"]
    if mcp_priority is None:
        mcp_priority = settings.get("mcp_priority", "first")
    if mcp_priority not in ("first", "last"):
        raise ValueError("MCP priority must be first or last.")
    options = code_research_options(
        store, name, connection, web_enabled, mcp_first=has_mcp and mcp_priority == "first",
    )
    options.update(
        limits=settings.get("coding_limits"), goal_budget=settings.get("coding_goal_limits"),
        mcp_priority=mcp_priority,
    )
    if unsupported(store.config, capability_connection):
        options["unsupported_subagent_roles"] = {"model"}
    return options
