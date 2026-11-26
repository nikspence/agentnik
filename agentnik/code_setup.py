"""UI-independent settings shared by interactive Code clients."""

from .code_research import code_research_options
from .subagent_capabilities import unsupported


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
