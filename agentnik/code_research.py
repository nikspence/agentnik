"""Shared desktop and terminal Code research setup."""

from urllib.parse import urlsplit

from . import hosted, research, routing
from .search_providers import SEARCH_KINDS


def code_research_options(store, name, connection, enabled, mcp_first=False):
    options = dict(web_enabled=enabled, web_backends=[], search_provider="none", hosted_search=False)
    if not enabled:
        return options
    if routing.connection_defaults(store.config, name, connection)["access_policy"] == "strict_public":
        return options
    parsed = urlsplit(connection["url"])
    direct = parsed.scheme == "https" and parsed.hostname == "ollama.com" and parsed.port in (None, 443)
    options["search_provider"] = "managed"
    options["web_backends"] = [
        item for item in store.web_backend_specs()
        if item.get("kind") in SEARCH_KINDS and (item["kind"] != "ollama" or direct)
    ]
    options["hosted_search"] = (
        not mcp_first
        and store.config["settings"].get("research_policy", "Provider first") == "Provider first"
        and hosted.supported_endpoint(connection)
        and research.capability(store.config, connection, "hosted_search").state != "unsupported"
    )
    return options
