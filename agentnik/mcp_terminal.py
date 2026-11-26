"""Bounded local stdio MCP tool transport for headless Code sessions."""

import copy
import json
import os
import subprocess
from threading import Lock

from .mcp_content import normalize_tool_result
from .mcp_support import initialize_request, parse_initialize, resolve_environment_references, response_limit, rpc_error, server_timeout
from .mcp_tool_preview import MAX_DETAILS, MAX_PAGES, MAX_TOOLS, contains_secret, preview_tool
from .research import scrub
from .tools import LimitError


class TerminalMCPBridge:
    review_required = True

    def __init__(self, server):
        self.server = copy.deepcopy(server)
        self.environment_values = resolve_environment_references(server.get("env", {}))
        self.process = None
        self.closed = False
        self.next_id = 1
        self.details = None
        self.io_lock = Lock()

    def request(self, action, payload, runtime):
        if self.closed:
            return {"error": "MCP session is closed. An interrupted call is not retried."}
        if action not in ("discover", "verify", "call"):
            return {"error": "This terminal MCP transport supports tools only."}
        try:
            if action == "discover":
                runtime.check()
                if self.process is not None:
                    return {"error": "MCP server is already running."}
                cwd = self.server.get("working_directory", "")
                if cwd and not os.path.isabs(cwd):
                    return {"error": "MCP working directory must be absolute on this system."}
                self.process = subprocess.Popen(
                    [self.server["command"], *self.server["args"]], cwd=cwd or None,
                    env={**os.environ, **self.environment_values}, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            return runtime.wait(lambda: self._exchange(action, payload),
                                request_seconds=server_timeout(self.server))
        except LimitError:
            self.close_from_worker()
            raise
        except (OSError, ValueError, RecursionError):
            self.close_from_worker()
            return {"error": "Local MCP communication failed.", "call_uncertain": action == "call"}
        except BaseException:
            self.close_from_worker()
            raise

    def close_from_worker(self):
        self.closed = True
        process = self.process
        if process is None:
            return
        self.process = None
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            except ProcessLookupError:
                pass
        if self.io_lock.acquire(blocking=False):
            try:
                self._close_pipes(process)
            finally:
                self.io_lock.release()

    @staticmethod
    def _close_pipes(process):
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass

    def _exchange(self, action, payload):
        with self.io_lock:
            process = self.process
            if self.closed or process is None:
                return {"error": "MCP session is closed."}
            try:
                return self._request(action, payload)
            finally:
                if self.closed:
                    self._close_pipes(process)

    def _send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n")
        self.process.stdin.flush()

    def _reply(self, ident, phase):
        limit = response_limit(phase)
        for _ in range(40):
            line = self.process.stdout.readline(limit + 1)
            if not line or len(line) > limit or not line.endswith(b"\n"):
                raise ValueError("Incomplete or oversized MCP reply")
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError("Malformed MCP reply")
            if "id" not in message and isinstance(message.get("method"), str):
                if message["method"] == "notifications/tools/list_changed":
                    raise ValueError("The MCP tool catalog changed")
                continue
            if type(message.get("id")) is not int or message["id"] != ident or "method" in message:
                raise ValueError("Unexpected MCP reply")
            return message
        raise ValueError("Too many MCP notifications")

    def _rpc(self, method, params, phase):
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        return self._reply(self.next_id, phase)

    def _catalog(self):
        cursor = None
        details = []
        names = set()
        cursors = set()
        size = 0
        secrets = self.environment_values.values()
        for _ in range(MAX_PAGES):
            reply = self._rpc("tools/list", {"cursor": cursor} if cursor else {}, "tools")
            result = reply.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise ValueError("Invalid MCP tool catalog")
            for item in result["tools"]:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not name or len(name) > 128 or not name.isprintable() or name in names:
                    raise ValueError("Invalid MCP tool name")
                if any(contains_secret(item, secret) for secret in secrets):
                    raise ValueError("MCP catalog reflected a credential")
                names.add(name)
                detail = dict(preview_tool(item), name=name)
                size += len(json.dumps(detail, ensure_ascii=True))
                if size > MAX_DETAILS or len(details) >= MAX_TOOLS:
                    return details, True
                details.append(detail)
            cursor = result.get("nextCursor")
            if cursor is None:
                return details, False
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 1024 or cursor in cursors:
                raise ValueError("Invalid MCP cursor")
            cursors.add(cursor)
        return details, True

    def _request(self, action, payload):
        secrets = list(self.environment_values.values())
        if action == "discover":
            message = initialize_request()
            message["params"]["capabilities"] = {}
            self._send(message)
            reply = self._reply(1, "initialize")
            info = parse_initialize(json.dumps(reply), ("2025-11-25", "2025-06-18", "2025-03-26"))
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.details, more = self._catalog() if "tools" in info["capabilities"] else ([], False)
            return {**scrub(info, secrets), "tool_details": self.details, "more_tools": more,
                    "capabilities": ["tools"] if "tools" in info["capabilities"] else [],
                    "task_capabilities": {}}
        if self.details is None:
            return {"error": "Discover the MCP server before using a tool."}
        expected = payload["tool"]
        current, _ = self._catalog()
        if expected not in current or expected.get("schema_status") != "available" or expected.get("task_support") == "required":
            return {"error": "The MCP tool changed or requires unsupported task execution."}
        if action == "verify":
            return {"verified": True}
        reply = self._rpc("tools/call", {"name": expected["name"], "arguments": payload["arguments"]}, "call")
        if "error" in reply:
            return {"error": scrub(rpc_error(reply), secrets)}
        return {"call_result": scrub(normalize_tool_result(reply.get("result")), secrets)}
