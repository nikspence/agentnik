"""UI-independent settings shared by interactive Code clients."""

from .core import base_url
from .code_research import code_research_options
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


def shared_run_options(store, name, connection, *, web_enabled, has_mcp, capability_connection):
    """Resolve policy and budgets without opening a model request or MCP connection."""
    settings = store.config["settings"]
    mcp_priority = settings.get("mcp_priority", "first")
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
