"""Headless 2025 Streamable HTTP transport for explicitly selected MCP servers."""

import json
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, Request, build_opener

from . import tls
from .core import NoRedirect
from .mcp_http_response import response_message
from .mcp_2026 import PROTOCOL as MODERN_PROTOCOL, parse_discovery, prepare_request
from .mcp_support import initialize_request, parse_initialize, response_limit, server_timeout
from .mcp_terminal import TerminalMCPBridge, terminal_modern_reply
from .tools import LimitError


class TerminalHTTPMCPBridge(TerminalMCPBridge):
    def __init__(self, server, token=""):
        super().__init__(server)
        self.environment_values = {"mcp-token": token} if token else {}
        self.token = token
        self.session_id = None
        self.runtime = None

    def request(self, action, payload, runtime):
        if self.closed:
            return {"error": "MCP session is closed. Interrupted requests are not retried."}
        if action not in self.supported_actions:
            return {"error": "This operation is not supported by the terminal MCP transport."}
        if action == "discover" and self.protocol:
            return {"error": "MCP session is already initialized."}
        self.runtime = runtime
        try:
            return runtime.wait(lambda: self._request(action, payload), request_seconds=server_timeout(self.server))
        except (LimitError, InterruptedError):
            self.closed = True
            raise
        except HTTPError as exc:
            self.closed = True
            status = exc.code
            exc.close()
            return {"error": f"MCP endpoint returned HTTP {status}. No request was retried.",
                    "call_uncertain": action == "call"}
        except (OSError, ValueError, RecursionError):
            self.closed = True
            return {"error": "MCP HTTPS communication failed. No request was retried.",
                    "call_uncertain": action == "call"}

    def _open(self, method, message, timeout, routing_headers=None):
        headers = {"Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.session_id:
            headers["MCP-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        if routing_headers:
            headers.update(routing_headers)
        content = None
        if message is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(message, ensure_ascii=True, allow_nan=False).encode("ascii")
        request = Request(self.server["url"], data=content, headers=headers, method=method)
        return build_opener(NoRedirect(), HTTPSHandler(context=tls.context())).open(request, timeout=timeout)

    def _post(self, message, phase, routing_headers=None):
        if self.closed:
            raise InterruptedError("MCP session is closed.")
        self.runtime.check()
        timeout = min(server_timeout(self.server), self.runtime.timeout())
        with self._open("POST", message, timeout, routing_headers) as response:
            if "id" not in message:
                if response.status != 202:
                    raise ValueError("MCP notification was not accepted")
                return None
            if response.status != 200:
                raise ValueError("Unexpected MCP HTTP response status")
            limit = response_limit(phase)
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("MCP response exceeded the output limit")
            result = response_message(data, response.headers.get_content_type(), message["id"])
            if phase == "initialize":
                session_id = response.headers.get("MCP-Session-Id")
                if session_id is not None and (not 0 < len(session_id) <= 512 or
                                               any(not 33 <= ord(ch) <= 126 for ch in session_id)):
                    raise ValueError("Invalid MCP session ID")
                self.session_id = session_id
                if session_id:
                    self.environment_values["mcp-session"] = session_id
            return result

    def _initialize(self):
        discovery, headers = prepare_request({"jsonrpc": "2.0", "id": 0, "method": "server/discover", "params": {}})
        try:
            reply = self._post(discovery, "modern_discovery", headers)
        except HTTPError as exc:
            if exc.code not in (400, 404, 405):
                raise
            if exc.code == 400:
                raw = exc.read(response_limit("initialize") + 1)
                if self.token and self.token.encode("ascii") in raw:
                    exc.close()
                    raise ValueError("MCP response reflected a credential")
                try:
                    candidate = response_message(raw, exc.headers.get_content_type(), 0)
                except (AttributeError, ValueError, RecursionError):
                    candidate = {}
                error = candidate.get("error")
                if isinstance(error, dict) and error.get("code") in (-32020, -32021, -32022):
                    raise
            exc.close()
        else:
            error = reply.get("error")
            if not isinstance(error, dict) or error.get("code") not in (-32600, -32601, -32602):
                info = parse_discovery(reply.get("result"))
                self.protocol = MODERN_PROTOCOL
                return info
        message = initialize_request()
        message["params"]["capabilities"] = {}
        reply = self._post(message, "initialize")
        info = parse_initialize(json.dumps(reply), ("2025-11-25", "2025-06-18", "2025-03-26"))
        self.protocol = info["protocol"]
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, "initialize")
        return info

    def _rpc(self, method, params, phase, schema=None):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        routing = None
        if self.protocol == MODERN_PROTOCOL:
            message, routing = prepare_request(message, schema)
        reply = self._post(message, phase, routing)
        return terminal_modern_reply(reply) if self.protocol == MODERN_PROTOCOL else reply

    def _tool_call(self, tool, arguments):
        return self._rpc("tools/call", {"name": tool["name"], "arguments": arguments}, "call", tool["schema"])

    def close_from_worker(self):
        if self.closed:
            return
        self.closed = True
        if self.session_id:
            try:
                self._open("DELETE", None, 2).close()
            except HTTPError as exc:
                exc.close()
            except (OSError, ValueError):
                pass
