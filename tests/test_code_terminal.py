import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from agentnik.code_terminal import drive_run
from agentnik.code_stream import visible_prefix


class TerminalRunTests(unittest.TestCase):
    def test_oauth_renewal_marks_uncertainty_and_never_retries_an_unfinished_exchange(self):
        from contextlib import nullcontext
        from email.message import Message
        import json
        from unittest.mock import Mock
        from agentnik.mcp_oauth_terminal import renew_mcp_credential

        server = {"url": "https://example.org/mcp", "credential_id": "fixture"}
        record = {"version": 1, "resource_url": server["url"], "issuer": "https://auth.example.org",
                  "token_endpoint": "https://auth.example.org/token", "client_id": "client",
                  "access_token": "old", "refresh_token": "old-refresh", "expires_at": 1, "refresh_pending": False}
        stored = [record]

        def write(service, ident, value):
            stored[0] = json.loads(value)

        def response(request, timeout):
            self.assertTrue(stored[0]["refresh_pending"])
            self.assertEqual(request.full_url, record["token_endpoint"])
            reply = io.BytesIO(b'{"token_type":"Bearer","access_token":"new","expires_in":3600}')
            reply.status = 200
            reply.headers = Message()
            reply.headers["Content-Type"] = "application/json"
            return reply

        with patch("agentnik.mcp_oauth_terminal.oauth_refresh_lease", side_effect=lambda _: nullcontext()), \
                patch("keyring.get_password", side_effect=lambda *_: json.dumps(stored[0])), \
                patch("keyring.set_password", side_effect=write), \
                patch("agentnik.mcp_oauth_terminal.build_opener") as opener:
            renew_mcp_credential(server, lambda _: False)
            opener.assert_not_called()
            opener.return_value = Mock(open=response)
            self.assertEqual(renew_mcp_credential(server, lambda _: True), "Renewed MCP OAuth sign-in.")
            self.assertEqual(stored[0]["access_token"], "new")
            self.assertFalse(stored[0]["refresh_pending"])
            stored[0] = record
            opener.return_value = Mock(open=Mock(side_effect=OSError("offline")))
            with self.assertRaisesRegex(ValueError, "not retried"):
                renew_mcp_credential(server, lambda _: True)
            with self.assertRaisesRegex(ValueError, "cannot be renewed"):
                renew_mcp_credential(server, lambda _: True)
            opener.return_value.open.assert_called_once()

    def test_terminal_mcp_reuses_only_ready_oauth_records_for_the_selected_server(self):
        import json
        from agentnik.code_terminal import terminal_mcp_bridges

        profile = {"name": "OAuth", "transport": "http", "url": "https://example.org/mcp",
                   "credential_id": "fixture", "enabled": True, "auth_type": "oauth"}
        config = {"settings": {}, "mcp_servers": [profile]}
        record = {"version": 1, "resource_url": profile["url"], "issuer": "https://auth.example.org",
                  "token_endpoint": "https://auth.example.org/token", "client_id": "client",
                  "access_token": "access-fixture", "refresh_token": "refresh-fixture",
                  "expires_at": None, "refresh_pending": False}
        with patch("keyring.get_password", return_value=json.dumps(record)) as get:
            bridge, = terminal_mcp_bridges(config, [profile])
            self.assertEqual(bridge.token, "access-fixture")
            get.assert_called_once_with("Agentnik", "fixture")
        with patch("keyring.get_password", return_value=json.dumps(dict(record, refresh_pending=True))):
            with self.assertRaisesRegex(ValueError, "needs renewal"):
                terminal_mcp_bridges(config, [profile])
        with patch("keyring.get_password", return_value=json.dumps(dict(record, resource_url="https://other.example.org/mcp"))):
            with self.assertRaisesRegex(ValueError, "sign-in is unavailable"):
                terminal_mcp_bridges(config, [profile])

    def test_terminal_mcp_keeps_selection_order_and_rejects_stale_profiles(self):
        from agentnik.code_terminal import terminal_mcp_bridges

        local = {"name": "Local", "command": "fixture", "args": [], "enabled": True}
        https = {"name": "HTTPS", "transport": "http", "url": "https://example.org/mcp",
                 "credential_id": "", "enabled": True}
        config = {"settings": {}, "mcp_servers": [local, https]}
        bridges = terminal_mcp_bridges(config, [https, local])
        self.assertEqual([bridge.server["name"] for bridge in bridges], ["HTTPS", "Local"])
        for bridge in bridges:
            bridge.close_from_worker()
        config["mcp_servers"] = [local, dict(https, enabled=False)]
        with self.assertRaisesRegex(ValueError, "changed or is unavailable"):
            terminal_mcp_bridges(config, [https, local])

    def test_stdio_probe_handles_silent_modern_and_delayed_legacy_servers(self):
        import sys
        from textwrap import dedent
        from agentnik.mcp_terminal import TerminalMCPBridge
        from agentnik.tools import Runtime

        fixture = dedent("""
            import json, sys
            legacy = sys.argv[1] == "legacy"
            def send(ident, **payload):
                print(json.dumps(dict(jsonrpc="2.0", id=ident, **payload)), flush=True)
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                if method == "server/discover":
                    if legacy:
                        send(1, result={"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "fixture", "version": "1"}})
                        send(0, error={"code": -32601, "message": "Method not found"})
                    else:
                        send(0, result={"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}})
                elif method == "tools/list":
                    send(message["id"], result={"tools": [{"name": "fixture", "inputSchema": {"type": "object"}}]})
        """)
        for mode, protocol in (("modern", "2026-07-28"), ("legacy", "2025-11-25")):
            with self.subTest(mode=mode), patch("agentnik.mcp_terminal.STARTUP_PROBE_SECONDS", 0.05):
                bridge = TerminalMCPBridge({"name": "Fixture", "command": sys.executable,
                                            "args": ["-u", "-c", fixture, mode]})
                try:
                    catalog = bridge.request("discover", {}, Runtime())
                    self.assertEqual(catalog.get("protocol"), protocol, catalog)
                    self.assertEqual(catalog["tool_details"][0]["name"], "fixture")
                finally:
                    bridge.close_from_worker()

    def test_local_mcp_negotiates_2026_after_legacy_envelope_rejection(self):
        import sys
        from textwrap import dedent
        from agentnik.mcp_terminal import TerminalMCPBridge
        from agentnik.tools import Runtime

        fixture = dedent("""
            import json, sys
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                response = {"jsonrpc": "2.0", "id": message["id"]}
                if method == "initialize":
                    response["error"] = {"code": -32601, "message": "Use discovery"}
                else:
                    assert message["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
                    if method == "server/discover":
                        result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
                    elif method == "tools/list":
                        result = {"tools": [{"name": "fixture", "inputSchema": {"type": "object"}}]}
                    else:
                        result = {"resultType": "input_required", "private": "not exposed"}
                    response["result"] = result
                print(json.dumps(response), flush=True)
        """)
        bridge = TerminalMCPBridge({"name": "Modern", "command": sys.executable, "args": ["-u", "-c", fixture]})
        try:
            catalog = bridge.request("discover", {}, Runtime())
            self.assertEqual(catalog["protocol"], "2026-07-28", catalog)
            outcome = bridge.request("call", {"tool": catalog["tool_details"][0], "arguments": {}}, Runtime())
            self.assertIn("not continued", outcome["error"])
            self.assertNotIn("not exposed", str(outcome))
        finally:
            bridge.close_from_worker()

    def test_remote_mcp_carries_session_headers_and_handles_sse_without_qt(self):
        from email.message import Message
        import json
        from unittest.mock import Mock
        from agentnik.mcp_terminal_http import TerminalHTTPMCPBridge
        from agentnik.tools import Runtime

        class Reply(io.BytesIO):
            def __init__(self, payload=b"", status=200, content_type="application/json", session=None):
                super().__init__(payload)
                self.status = status
                self.headers = Message()
                self.headers["Content-Type"] = content_type
                if session:
                    self.headers["MCP-Session-Id"] = session

        requests = []

        def open_request(request, timeout):
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["authorization"], "Bearer fixture-key")
            body = json.loads(request.data) if request.data else None
            requests.append((request.get_method(), body, headers))
            if body is None:
                return Reply(status=204)
            method = body["method"]
            if method == "notifications/initialized":
                return Reply(status=202)
            if method == "server/discover":
                return Reply(json.dumps({"jsonrpc": "2.0", "id": 0,
                                        "error": {"code": -32601, "message": "Method not found"}}).encode())
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "fixture", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": "hello", "inputSchema": {"type": "object"}}]}
            else:
                result = {"content": [{"type": "text", "text": "Hello over HTTPS"}]}
            envelope = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            if method == "tools/call":
                return Reply(b"data: " + envelope + b"\n\n", content_type="text/event-stream")
            return Reply(envelope, session="fixture-session" if method == "initialize" else None)

        bridge = TerminalHTTPMCPBridge({"name": "Remote", "url": "https://example.org/mcp"}, "fixture-key")
        with patch("agentnik.mcp_terminal_http.build_opener", return_value=Mock(open=open_request)):
            try:
                catalog = bridge.request("discover", {}, Runtime())
                answer = bridge.request("call", {"tool": catalog["tool_details"][0], "arguments": {}}, Runtime())
                self.assertEqual(answer["call_result"]["content"][0]["text"], "Hello over HTTPS")
            finally:
                bridge.close_from_worker()
        self.assertEqual(requests[-1][0], "DELETE")
        self.assertEqual(requests[0][1]["method"], "server/discover")
        self.assertNotIn("mcp-session-id", requests[1][2])
        for _, _, headers in requests[2:]:
            self.assertEqual(headers["mcp-session-id"], "fixture-session")
            self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")

    def test_remote_mcp_negotiates_2026_and_does_not_fallback_on_auth_errors(self):
        from email.message import Message
        import json
        from urllib.error import HTTPError
        from agentnik.mcp_terminal_http import TerminalHTTPMCPBridge
        from agentnik.tools import Runtime

        profile = {"name": "Remote", "url": "https://example.org/mcp"}
        bridge = TerminalHTTPMCPBridge(profile)
        requests = []

        def reply(method, message, timeout, headers):
            self.assertEqual(method, "POST")
            requests.append(message["method"])
            self.assertEqual(headers["MCP-Protocol-Version"], "2026-07-28")
            self.assertEqual(headers["Mcp-Method"], message["method"])
            if message["method"] == "server/discover":
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
            elif message["method"] == "tools/list":
                result = {"tools": [{"name": "greet", "inputSchema": {
                    "type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "region"}},
                }}]}
            else:
                self.assertEqual(headers["Mcp-Name"], "greet")
                self.assertEqual(headers["Mcp-Param-region"], "west")
                result = {"resultType": "complete", "content": [{"type": "text", "text": "Modern hello"}]}
            response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode())
            response.status = 200
            response.headers = Message()
            response.headers["Content-Type"] = "application/json"
            return response

        with patch.object(bridge, "_open", side_effect=reply):
            try:
                catalog = bridge.request("discover", {}, Runtime())
                result = bridge.request("call", {"tool": catalog["tool_details"][0],
                                                  "arguments": {"region": "west"}}, Runtime())
            finally:
                bridge.close_from_worker()
        self.assertEqual(result["call_result"]["content"][0]["text"], "Modern hello")
        self.assertEqual(requests, ["server/discover", "tools/list", "tools/list", "tools/call"])
        bridge = TerminalHTTPMCPBridge(profile)
        with patch.object(bridge, "_open", side_effect=HTTPError(profile["url"], 401, "", Message(), None)) as open_request:
            self.assertIn("HTTP 401", bridge.request("discover", {}, Runtime())["error"])
            open_request.assert_called_once()

    def test_headless_local_mcp_checks_approvals_for_tools_and_resources(self):
        import sys
        from textwrap import dedent
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        server_code = dedent("""
            import json, sys
            for line in sys.stdin:
                message = json.loads(line)
                method = message["method"]
                if method == "initialize":
                    result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "completions": {}},
                              "serverInfo": {"name": "fixture", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "hello", "description": "Return a greeting",
                                         "inputSchema": {"type": "object"}}]}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": "Hello from the local fixture"}]}
                elif method == "resources/list":
                    result = {"resources": [{"uri": "fixture://notes", "name": "Notes"}]}
                elif method == "resources/read":
                    uri = message["params"]["uri"]
                    result = {"contents": [{"uri": uri, "text": "Fixture resource content for " + uri}]}
                elif method == "resources/templates/list":
                    result = {"resourceTemplates": [{"uriTemplate": "fixture://items/{id}", "name": "Item"}]}
                elif method == "prompts/list":
                    result = {"prompts": [{"name": "greeting", "arguments": [{"name": "name"}]}]}
                elif method == "completion/complete":
                    assert message["params"]["argument"] == {"name": "name", "value": "fi"}
                    result = {"completion": {"values": ["fixture-suggestion"]}}
                elif method == "prompts/get":
                    result = {"messages": [{"role": "user", "content": {"type": "text", "text": "Fixture prompt content"}}]}
                else:
                    continue
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
        """)
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            store = Store(root / "data")
            try:
                store.save_connection("Fixture", {"url": "https://gateway.example/v1", "model": "test",
                                                  "protocol": "chat", "stream": False})
                store.config["mcp_servers"] = [{"name": "Local Fixture", "command": sys.executable,
                                                 "args": ["-u", "-c", server_code], "enabled": True}]
                store.flush()
            finally:
                store.db.close()
            composer = Mock()
            composer.prompt.side_effect = ["/connection Fixture", "/mcp use Local Fixture", "Run greeting", "/exit"]
            output = io.StringIO()
            with patch("sys.argv", ["agentnik", "code", str(root), "--data-dir", str(root / "data")]), \
                    patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=composer), \
                    patch("builtins.input", side_effect=["y"] * 9) as approval, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[call("mcp_discover", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_call", {"tool": "hello", "arguments": "{}"})],
                                  finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_resources", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_read_resource", {"uri": "fixture://notes"})],
                                  finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_resource_templates", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_read_resource_template", {
                            "template": "fixture://items/{id}", "variables": '{"id":"17"}',
                        })], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_list_prompts", {})], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_complete_argument", {
                            "request": '{"kind":"prompt","target":"greeting","argument":"name","value":"fi","context":{}}',
                        })], finish="tool_calls"), False),
                        Wire(chat(calls=[call("mcp_get_prompt", {"name": "greeting", "arguments": "{}"})],
                                  finish="tool_calls"), False),
                        Wire(chat("Done"), False),
                    ]) as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(approval.call_count, 9, output.getvalue())
            self.assertEqual(transport.call_count, 10, output.getvalue())
            self.assertIn("Hello from the local fixture", str(transport.call_args_list[2].args[2]))
            self.assertIn("Fixture resource content", str(transport.call_args_list[4].args[2]))
            self.assertIn("Fixture resource content for fixture://items/17", str(transport.call_args_list[6].args[2]))
            self.assertIn("fixture-suggestion", str(transport.call_args_list[8].args[2]))
            self.assertIn("Fixture prompt content", str(transport.call_args_list[9].args[2]))

    def test_only_lease_owner_can_recover_an_interrupted_goal(self):
        from agentnik.code_history import CodeHistory, goal_continuation
        from agentnik.code_lease import SessionLease
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            data = root / "data"
            store = Store(data)
            try:
                history = CodeHistory(store, root)
                session = str(uuid4())
                history.start("fixture", {"model": "test"}, "Finish project", session, goal=True)
                with SessionLease(data) as lease:
                    record = history.list(session)[0]
                    history.checkpoint_goal(record, {"kind": "goal_status", "status": "active",
                                                     "detail": "Draft was created."})
                    history.checkpoint_goal(record, {"kind": "goal_progress", "steps": 2, "seconds": 3.0})
                    record = history.list(session)[0]
                    history.recover_interrupted(record, lease)
                    self.assertEqual(record["code_state"], "running")
                    lease.select(session)
                    history.recover_interrupted(record, lease)
                    saved = history.list(session)[0]
                    self.assertEqual(saved["coding_goal"]["status"], "interrupted")
                    self.assertEqual(goal_continuation(saved)["task"], "Finish project")
                    self.assertIn("Draft was created.", goal_continuation(saved)["evidence"])
                    self.assertIn("Recorded goal steps: 2.", goal_continuation(saved)["evidence"])
            finally:
                store.db.close()

    def test_session_lease_rejects_duplicate_attachment_and_releases_on_close(self):
        from agentnik.code_lease import SessionLease

        with TemporaryDirectory() as directory, SessionLease(directory) as left, SessionLease(directory) as right:
            first, second = str(uuid4()), str(uuid4())
            left.select(first)
            right.select(second)
            with self.assertRaisesRegex(ValueError, "already open"):
                right.select(first)
            self.assertEqual(right.session_id, second)
            left.close()
            right.select(first)
            self.assertEqual(right.session_id, first)

    def test_model_picker_filters_catalog_and_does_not_echo_reflected_credentials(self):
        from agentnik.code_terminal import choose_catalog_model, load_run_settings

        discovered = {"local:fixture": {"url": "http://localhost:11434/v1", "api_key": "test-secret"}}
        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output, \
                patch("agentnik.core.models", return_value=[
                    "a-model", "b-model", "a-test-secret", "a-\x1b[2J",
                ]) as catalog, patch("builtins.input", return_value="1"):
            self.assertEqual(choose_catalog_model(directory, "local:fixture", "a-", discovered), "a-model")
            connection, *_ = load_run_settings(directory, "local:fixture", "a-model", discovered=discovered)
            self.assertEqual(connection["model"], "a-model")
        catalog.assert_called_once()
        self.assertNotIn("test-secret", output.getvalue())
        self.assertNotIn("b-model", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())

    def test_project_diff_distinguishes_worktree_from_index(self):
        from dulwich import porcelain
        from agentnik.code_terminal import project_diff

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "some note.txt"
            with porcelain.init(root) as repo:
                path.write_text("base\n")
                porcelain.add(repo, [path.name])
                porcelain.commit(repo, message=b" fixture", author=b"Test <test@example.org>",
                                 committer=b"Test <test@example.org>", no_verify=True, sign=False)
                path.write_text("staged\n")
                porcelain.add(repo, [path.name])
                path.write_text("working\n")
                self.assertIn("+working", project_diff(root, path.name))
                self.assertIn("+staged", project_diff(root, "--staged " + path.name))
                self.assertIn("Unstaged", project_diff(root, ""))

    def test_mcp_signin_persists_only_the_credential_reference(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                with patch("builtins.input", side_effect=["Fixture Server", "https://example.org/mcp"]):
                    configure_code(store, ["mcp", "add-https"])
                record = {"access_token": "fixture-secret-token"}
                with patch("builtins.input", side_effect=["fixture-client", "read"]), \
                        patch("agentnik.mcp_oauth_signin.sign_in", return_value=record) as signin, \
                        patch("agentnik.mcp_oauth_record.write_record") as save:
                    configure_code(store, ["mcp", "signin", "Fixture", "Server"])
                profile = load_config(store.config_path)["mcp_servers"][0]
                self.assertEqual(profile["auth_type"], "oauth")
                self.assertFalse(profile["enabled"])
                save.assert_called_once_with(profile["credential_id"], record)
                self.assertEqual(signin.call_args.args[:3], ("https://example.org/mcp", "fixture-client", "read"))
                self.assertNotIn("fixture-secret-token", store.config_path.read_text())
            finally:
                store.db.close()

    def test_mcp_preferences_and_disabled_https_server_are_saved_without_contact(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                with patch("builtins.input", side_effect=["Fixture Server", "https://example.org/mcp"]):
                    configure_code(store, ["mcp", "add-https"])
                self.assertFalse(load_config(store.config_path)["mcp_servers"][0]["enabled"])
                with patch("agentnik.code_settings.getpass", return_value="fixture-token"), \
                        patch("keyring.set_password") as save:
                    configure_code(store, ["mcp", "token", "Fixture", "Server"])
                credential = load_config(store.config_path)["mcp_servers"][0]["credential_id"]
                save.assert_called_once_with("Agentnik", credential, "fixture-token")
                self.assertNotIn("fixture-token", store.config_path.read_text())
                with patch("agentnik.code_settings.getpass", return_value=""), \
                        patch("builtins.input", return_value="y"), patch("keyring.delete_password") as remove:
                    configure_code(store, ["mcp", "token", "Fixture", "Server"])
                remove.assert_called_once_with("Agentnik", credential)
                self.assertEqual(load_config(store.config_path)["mcp_servers"][0]["credential_id"], "")
                configure_code(store, ["mcp", "enable", "Fixture", "Server"])
                configure_code(store, ["mcp", "priority", "last"])
                configure_code(store, ["mcp", "timeout", "120", "Fixture", "Server"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["mcp", "timeout", "0", "Fixture", "Server"])
                configure_code(store, ["mcp", "off"])
                saved = load_config(store.config_path)
                self.assertTrue(saved["mcp_servers"][0]["enabled"])
                self.assertEqual(saved["mcp_servers"][0]["timeout_seconds"], 120)
                self.assertEqual(saved["settings"]["mcp_priority"], "last")
                self.assertFalse(saved["settings"]["mcp_access_enabled"])
                with patch("builtins.input", side_effect=[
                    "Local Fixture", "python", '["-m", "fixture"]', "", '{"TOKEN":"MCP_TOKEN"}',
                ]):
                    configure_code(store, ["mcp", "add-local"])
                local = load_config(store.config_path)["mcp_servers"][1]
                self.assertFalse(local["enabled"])
                self.assertEqual(local["args"], ["-m", "fixture"])
                self.assertEqual(local["env"], {"TOKEN": "MCP_TOKEN"})
                with patch("builtins.input", return_value="y"):
                    configure_code(store, ["mcp", "remove", "Local", "Fixture"])
                self.assertEqual(len(load_config(store.config_path)["mcp_servers"]), 1)
            finally:
                store.db.close()

    def test_terminal_composer_completes_nested_settings_commands(self):
        from importlib.util import find_spec

        if find_spec("prompt_toolkit") is None:
            self.skipTest("Terminal composer extra is not installed")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from agentnik.code_composer import create_composer

        with create_pipe_input() as pipe:
            composer = create_composer(input=pipe, output=DummyOutput())
            for partial, expected in (
                ("/settings mcp sig", "/settings mcp signin"),
                ("/settings web providers s", "/settings web providers set"),
                ("/settings image s", "/settings image set"),
            ):
                with self.subTest(partial=partial):
                    completions = composer.completer.get_completions(
                        Document(partial), CompleteEvent(completion_requested=True))
                    self.assertIn(expected, [item.text for item in completions])

    def test_terminal_composer_keeps_newlines_and_records_submitted_input(self):
        from importlib.util import find_spec
        import subprocess
        import sys
        from textwrap import dedent

        if find_spec("prompt_toolkit") is None:
            self.skipTest("Terminal composer extra is not installed")
        script = dedent(r"""
            from threading import Timer
            from prompt_toolkit.input import create_pipe_input
            from prompt_toolkit.output import DummyOutput
            from agentnik.code_composer import create_composer, transcript_pager

            with create_pipe_input() as pipe:
                composer = create_composer(input=pipe, output=DummyOutput())
                pipe.send_text("first line\rsecond line\x1b\r")
                task = composer.prompt()
                assert task == "first line\nsecond line"
                assert composer.history.get_strings() == [task]
                for keys, expected in (("\x1b[A\x1b\r", task),
                                       ("draft\x1b[A\x1b[B\x1b\r", "draft")):
                    timer = Timer(0.2, pipe.send_text, args=(keys,))
                    timer.start()
                    actual = composer.prompt()
                    timer.join()
                    assert actual == expected, repr(actual)

            transcript = "\n".join(f"line {i}" for i in range(100))
            for keys, at_end in (("\x1b[5~q", False), ("\x1b[5~\x1b[6~q", True),
                                 ("\x02\x06\x14", True)):
                with create_pipe_input() as pipe:
                    pager = transcript_pager(transcript, input=pipe, output=DummyOutput())
                    pipe.send_text(keys)
                    pager.run()
                    assert (pager.current_buffer.cursor_position == len(transcript)) == at_end
        """)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shell_advice_requires_disclosure_consent_and_skips_credentials(self):
        from threading import Event
        from agentnik.code_terminal import show_shell_advice

        connection = {"url": "http://localhost:11434/v1", "model": "fixture", "api_key": "secret-key"}
        proposal = {"command": "echo OK", "cwd": ".", "shell": "pwsh", "environment_keys": ["PATH"]}
        messages = []
        with patch("agentnik.decision_advice.request", return_value={
            "answers": {"risk": {"choice": "safe", "confidence": 0.8}},
        }) as request:
            with patch("builtins.input", return_value=""):
                show_shell_advice(connection, proposal, Event(), messages.append)
            show_shell_advice(connection, dict(proposal, command="echo secret-key"), Event(), messages.append)
            request.assert_not_called()
            with patch("builtins.input", return_value="y"):
                show_shell_advice(connection, proposal, Event(), messages.append)
            request.assert_called_once()
        self.assertIn("System One advice: SAFE · 80% confidence. You still decide.", messages)

    def test_decision_settings_require_a_binding_and_make_no_requests(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory, patch("agentnik.core.open_request") as request:
            store = Store(directory)
            try:
                with self.assertRaises(ValueError):
                    configure_code(store, ["decision", "on"])
                store.save_connection("Fixture", {"url": "http://localhost:11434/v1"})
                with patch("builtins.input", side_effect=["Fixture", "decision-model"]):
                    configure_code(store, ["decision", "set"])
                configure_code(store, ["decision", "on"])
                settings = load_config(store.config_path)["settings"]
                self.assertTrue(settings["decision_advice_enabled"])
                self.assertEqual(settings["decision_model"], {"connection": "Fixture", "model": "decision-model"})
                request.assert_not_called()
            finally:
                store.db.close()

    def test_headless_image_codec_preserves_transparency_without_qt(self):
        from importlib.util import find_spec
        import subprocess
        import sys
        from textwrap import dedent

        if find_spec("PIL") is None:
            self.skipTest("Terminal image extra is not installed")
        script = dedent("""
            import io
            from importlib.abc import MetaPathFinder
            from pathlib import Path
            import sys
            from tempfile import TemporaryDirectory

            class NoQt(MetaPathFinder):
                def find_spec(self, fullname, path, target=None):
                    if fullname == "PySide6":
                        raise ModuleNotFoundError(name=fullname)
                    return None

            sys.meta_path.insert(0, NoQt())
            from PIL import Image
            from agentnik.code_image import convert
            from agentnik.image_generation import image_bytes
            from agentnik.code_agent import ProjectFiles
            from agentnik.code_vision import read_image, image_message

            raw = io.BytesIO()
            Image.new("RGBA", (32, 18), (255, 40, 0, 80)).save(raw, "PNG")
            assert image_bytes(raw.getvalue()) == ("image/png", ".png")
            result = convert(raw.getvalue(), ".webp")
            try:
                convert(raw.getvalue(), ".jpg")
            except ValueError as exc:
                assert "transparency" in str(exc)
            else:
                raise AssertionError("JPEG conversion discarded transparency")
            with Image.open(io.BytesIO(result)) as asset:
                assert asset.size == (32, 18)
                assert asset.getpixel((0, 0))[3] == 80
            with TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                (root / "asset.webp").write_bytes(result)
                data, mime = read_image(ProjectFiles(root), "asset.webp")
                message = image_message([("asset.webp", data, mime)], "chat")
                assert message["content"][1]["image_url"]["url"].startswith("data:image/webp;base64,")
        """)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_image_settings_reject_an_override_on_another_host(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.save_connection("Fixture", {"url": "https://gateway.example/v1", "protocol": "chat"})
                with patch("builtins.input", side_effect=["Fixture", "image-model", "https://other.example/images"]):
                    with self.assertRaises(ValueError):
                        configure_code(store, ["image", "set"])
                with patch("builtins.input", side_effect=["Fixture", "image-model", ""]):
                    configure_code(store, ["image", "set"])
                configure_code(store, ["image", "on"])
                settings = load_config(store.config_path)["settings"]["image_generation"]
                self.assertEqual(settings, {
                    "enabled": True, "connection": "Fixture", "model": "image-model", "endpoint": "",
                })
            finally:
                store.db.close()

    def test_search_credentials_are_saved_in_keyring_and_not_listed(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                prefix = ["web", "providers"]
                with patch("agentnik.code_settings.getpass", return_value="fixture-key"), \
                        patch("builtins.input", return_value=""), patch("keyring.set_password") as save:
                    configure_code(store, [*prefix, "set", "brave"])
                profile = load_config(store.config_path)["web_backends"][0]
                save.assert_called_once_with("Agentnik Web", profile["credential_id"], "fixture-key")
                self.assertNotIn("api_key", profile)
                self.assertNotIn("fixture-key", configure_code(store, prefix))
                with patch("builtins.input", return_value="y"), patch("keyring.delete_password") as delete:
                    configure_code(store, [*prefix, "remove", "brave-search"])
                delete.assert_called_once_with("Agentnik Web", profile["credential_id"])
                self.assertEqual(load_config(store.config_path)["web_backends"], [])
            finally:
                store.db.close()

    def test_web_opt_in_honors_strict_navigation_without_loading_search_keys(self):
        from unittest.mock import Mock
        from agentnik.code_research import code_research_options

        store = Mock()
        store.config = {"settings": {"research_access_policy": "strict_public"}}
        connection = {"url": "https://gateway.example/v1", "protocol": "chat", "model": "test"}
        self.assertFalse(code_research_options(store, "Fixture", connection, False)["web_enabled"])
        options = code_research_options(store, "Fixture", connection, True)
        self.assertTrue(options["web_enabled"])
        self.assertEqual(options["search_provider"], "none")
        self.assertFalse(options["hosted_search"])
        store.web_backend_specs.assert_not_called()
        store.config["settings"]["research_access_policy"] = "public_fetch"
        store.web_backend_specs.return_value = [{"kind": "ollama"}, {"kind": "brave"}]
        options = code_research_options(store, "Fixture", connection, True)
        self.assertEqual(options["search_provider"], "managed")
        self.assertEqual(options["web_backends"], [{"kind": "brave"}])

    def test_full_cli_turn_applies_reviewed_edit_and_resumes_without_replay(self):
        from unittest.mock import Mock
        from agentnik import cli, core
        from agentnik.code_history import CodeHistory
        from agentnik.storage import Store
        from test_code_agent import call
        from test_compat_tools import chat
        from test_routing import Wire

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, data = base / "project", base / "data"
            root.mkdir()
            asset = Path(cli.__file__).parent / "assets" / "agentnik-icon.png"
            (root / "visual.png").write_bytes(asset.read_bytes())
            from zipfile import ZipFile

            with ZipFile(root / "brief.pptx", "w") as archive:
                archive.writestr("ppt/slides/slide1.xml",
                                 '<a:root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                                 '<a:t>Presentation fixture brief.</a:t></a:root>')
            skill = root / ".agents" / "skills" / "notes" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: notes\ndescription: Note formatting\n---\nFixture note style.\n")
            preserved = root / "keep.txt"
            preserved.write_text("Keep me")
            connection = {"url": "https://gateway.example/v1", "model": "test",
                          "protocol": "chat", "stream": False}
            store = Store(data)
            try:
                store.save_connection("Fixture", connection)
            finally:
                store.db.close()
            argv = ["agentnik", "code", str(root), "--data-dir", str(data)]
            edit = call("write_file", {"path": "note.txt", "content": "reviewed\n"})
            delete = call("delete_file", {"path": "keep.txt"}, ident="call-2")
            auto_edit = call("write_file", {"path": "auto.txt", "content": "automatic\n"})
            shell = call("run_shell", {"path": ".", "command": "echo fixture"}, ident="call-shell")
            first = Mock()
            first.prompt.side_effect = ["/connection Fixture", "/skills add notes", "/attach brief.pptx",
                                        "/vision on", "/attach visual.png",
                                        *[f"/settings limits {key} 0" for key in
                                          ("rounds", "requests", "calls", "turn_seconds")],
                                        "Create a note", "/context", "/context clear",
                                        "/permissions allow-all", "Create another note",
                                        "/new", "/status", "/history", "/exit"]
            output = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=first), \
                    patch("builtins.input", side_effect=["y", "n"]) as approval, \
                    patch("agentnik.shell.execute", return_value={
                        "exit_code": 0, "output": "fixture", "truncated": False,
                    }) as execute, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[edit, delete], finish="tool_calls"), False),
                        Wire(chat("Created the note."), False),
                        Wire(chat(calls=[auto_edit, shell], finish="tool_calls"), False),
                        Wire(chat("Created another note."), False),
                    ]) as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(transport.call_count, 4, output.getvalue())
            self.assertIn("Fixture note style.", str(transport.call_args_list[0].args[2]))
            self.assertIn("Presentation fixture brief.", str(transport.call_args_list[0].args[2]))
            self.assertNotIn("Presentation fixture brief.", str(transport.call_args_list[2].args[2]))
            self.assertIn("data:image/png;base64,", str(transport.call_args_list[0].args[2]))
            self.assertNotIn("data:image/png;base64,", str(transport.call_args_list[2].args[2]))
            self.assertIn("Answer:\nCreated the note.", output.getvalue())
            self.assertNotIn("Created the note.", str(transport.call_args_list[2].args[2]))
            execute.assert_called_once()
            self.assertIn("No saved history for this session.", output.getvalue())
            self.assertIn("Permissions: require", output.getvalue())
            self.assertEqual(approval.call_count, 2, output.getvalue())
            self.assertEqual((root / "note.txt").read_text(), "reviewed\n")
            self.assertEqual((root / "auto.txt").read_text(), "automatic\n")
            self.assertEqual(preserved.read_text(), "Keep me")
            store = Store(data)
            try:
                session_id, record = next(iter(CodeHistory(store, root).sessions().items()))
                self.assertEqual(record["coding_context"]["answer"], "Created another note.")
                self.assertIn("notes", record["coding_skill_pins"])
                from agentnik.sessions import append_code_activity

                for index in range(21):
                    append_code_activity(record, "tool", f"Activity {index}")
                store.save(record)
            finally:
                store.db.close()
            reopened = Mock()
            reopened.prompt.return_value = "/exit"
            with patch("sys.argv", [*argv, "--resume", session_id]), \
                    patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=reopened), \
                    patch.object(core, "open_request") as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            transport.assert_not_called()
            self.assertIn(f"Resumed session {session_id}", output.getvalue())
            reopened.history.append_string.assert_any_call("Create another note")

    def test_connection_keyring_fallback_requires_explicit_consent(self):
        from keyring.errors import NoKeyringError
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        for answer in ("", "y"):
            with self.subTest(answer=answer), TemporaryDirectory() as directory:
                with patch("builtins.input", side_effect=["https://example.org/v1", "", "fixture-model", "", answer]) as prompt, \
                        patch("agentnik.cli.getpass", return_value="fixture-secret"), \
                        patch("keyring.set_password", side_effect=NoKeyringError()) as keyring, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    connection_menu(directory, "add", "Fixture")
                keyring.assert_called_once()
                self.assertIn("without encryption", prompt.call_args.args[0])
                self.assertNotIn("fixture-secret", output.getvalue())
                store = Store(directory)
                try:
                    saved = load_config(store.config_path)["connections"]
                    if answer:
                        self.assertEqual(saved["Fixture"]["api_key"], "fixture-secret")
                    else:
                        self.assertNotIn("Fixture", saved)
                finally:
                    store.db.close()

    def test_connection_edit_preserves_credential_and_refuses_to_move_it(self):
        from agentnik.cli import connection_menu
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            store = Store(directory)
            try:
                store.config["connections"]["Local"] = {
                    "url": "http://localhost:11434/v1", "model": "before",
                    "protocol": "chat", "credential_id": "test-item",
                }
                store.flush()
                with patch("builtins.input", side_effect=["", "", "after"]):
                    connection_menu(directory, "edit", "Local")
                with patch("builtins.input", side_effect=["https://example.org/v1", "", "other"]), \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    connection_menu(directory, "edit", "Local")
                self.assertIn("authenticated endpoint", errors.getvalue())
                updated = load_config(store.config_path)["connections"]["Local"]
                self.assertEqual(updated["model"], "after")
                self.assertEqual(updated["credential_id"], "test-item")
                self.assertEqual(updated["url"], "http://localhost:11434/v1")
                with patch("builtins.input", side_effect=["high", "flex", "8192", "off"]):
                    connection_menu(directory, "options", "Local")
                updated = load_config(store.config_path)["connections"]["Local"]
                self.assertEqual(updated["reasoning"], "high")
                self.assertEqual(updated["service_tier"], "flex")
                self.assertEqual(updated["context_limit"], 8192)
                self.assertFalse(updated["stream"])
                self.assertEqual(updated["credential_id"], "test-item")
            finally:
                store.db.close()

    def test_terminal_settings_share_validated_limits_and_tls(self):
        from agentnik.code_settings import configure_code
        from agentnik.storage import Store, load_config

        with TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                configure_code(store, ["limits", "rounds", "12"])
                configure_code(store, ["goal", "steps", "3"])
                configure_code(store, ["web", "desktop", "on"])
                configure_code(store, ["chat-limits", "rounds", "5"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["chat-limits", "rounds", "0"])
                configure_code(store, ["tls", "strict"])
                configure_code(store, ["appearance", "theme", "dark"])
                configure_code(store, ["appearance", "language", "en"])
                configure_code(store, ["appearance", "history", "hide"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["appearance", "font", "100"])
                with self.assertRaises(ValueError):
                    configure_code(store, ["limits", "rounds", "-1"])
                saved = load_config(store.config_path)["settings"]
                self.assertEqual(saved["coding_limits"]["rounds"], 12)
                self.assertEqual(saved["coding_goal_limits"]["steps"], 3)
                self.assertTrue(saved["web_search_enabled"])
                self.assertEqual(saved["chat_research_limits"], {"rounds": 5})
                self.assertFalse(saved["relaxed_tls"])
                self.assertEqual(saved["theme"], "Dark")
                self.assertEqual(saved["language"], "en")
                self.assertFalse(saved["history_visible"])
                configure_code(store, ["limits", "rounds", "default"])
                self.assertNotEqual(load_config(store.config_path)["settings"]["coding_limits"]["rounds"], 12)
            finally:
                store.db.close()

    def test_history_persists_only_completed_context_for_current_project(self):
        from agentnik.code_history import CodeHistory, goal_continuation
        from agentnik.storage import Store

        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            store = Store(base / "settings")
            history = CodeHistory(store, root)
            connection = {"model": "model", "api_key": "synthetic-secret"}
            first, second = str(uuid4()), str(uuid4())
            record, task = history.start("example", connection, "Find synthetic-secret", first)
            self.assertNotIn("coding_context", history.list()[0])
            history.finish(record, task, {"status": "completed", "response_shown": True, "text": "Done"})
            goal, task = history.start("example", connection, "Different task", second, goal=True)
            history.finish(goal, task, {"status": "failed", "limited": True,
                                        "last_goal_detail": "Project state changed before limit.",
                                        "goal_progress": {"steps": 3, "seconds": 2}})
            store.db.close()
            store = Store(base / "settings")
            try:
                history = CodeHistory(store, root)
                restored = history.list(first)[0]
                self.assertEqual(restored["coding_context"], {"task": "Find [redacted]", "answer": "Done"})
                self.assertEqual(set(history.sessions()), {first, second})
                self.assertNotIn("coding_context", history.list(second)[0])
                self.assertEqual(history.list(second)[0]["coding_goal"]["status"], "limited")
                self.assertEqual(history.list(second)[0]["coding_goal_progress"]["steps"], 3)
                continuation = goal_continuation(history.list(second)[0])
                self.assertEqual(continuation["task"], "Different task")
                self.assertIn("Project state changed before limit.", continuation["evidence"])
                self.assertIsNone(goal_continuation(restored))
                self.assertEqual(CodeHistory(store, base).list(), [])
            finally:
                store.db.close()

    def test_stream_holds_partial_credentials_and_renders_once(self):
        key = "test-credential"
        first = visible_prefix("Hello test-cre", [key])
        second = visible_prefix("Hello test-credential!", [key])
        self.assertEqual(first, "Hello ")
        self.assertEqual(second, "Hello [redacted]!")
        self.assertEqual(visible_prefix("aaaa", ["aaa"]), "[redacted]")

        class Run:
            def run(self, emit):
                emit({"kind": "model_delta", "stream_id": "1", "text": first})
                emit({"kind": "model_delta", "stream_id": "1", "text": second[len(first):]})
                emit({"kind": "model_response", "stream_id": "1", "text": second,
                      "thinking": "Provider detail"})

            def stop(self):
                pass

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            drive_run(Run())
        self.assertEqual(output.getvalue(), second + "\nModel thinking:\nProvider detail\n")

    def test_review_requires_explicit_input_and_escapes_terminal_controls(self):
        class Run:
            decisions = []

            def run(self, emit):
                emit({"kind": "edit_proposal", "fingerprint": "edit",
                      "proposal": {"cwd": "project", "path": "file", "diff": "+\x1b[2J"}})
                emit({"kind": "operation_proposal", "fingerprint": "push",
                      "proposal": {"operation": "git_push_connect"}})

            def decide(self, fingerprint, approved):
                self.decisions.append((fingerprint, approved))

            def stop(self):
                pass

        output = io.StringIO()
        run = Run()
        with contextlib.redirect_stdout(output), patch("builtins.input", return_value="y") as prompt:
            drive_run(run)
        self.assertEqual(run.decisions, [("edit", True), ("push", False)])
        prompt.assert_called_once()
        self.assertIn(r"+\x1b[2J", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())
