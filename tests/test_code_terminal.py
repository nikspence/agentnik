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
    def test_model_picker_filters_catalog_and_does_not_echo_reflected_credentials(self):
        from agentnik.code_terminal import choose_catalog_model

        with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output, \
                patch("agentnik.core.environment_connections", return_value={
                    "env:fixture": {"url": "https://gateway.example/v1", "api_key": "test-secret"},
                }), patch("agentnik.core.models", return_value=[
                    "a-model", "b-model", "a-test-secret", "a-\x1b[2J",
                ]) as catalog, patch("builtins.input", return_value="1"):
            self.assertEqual(choose_catalog_model(directory, "env:fixture", "a-"), "a-model")
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

    def test_terminal_composer_keeps_newlines_and_records_submitted_input(self):
        from importlib.util import find_spec

        if find_spec("prompt_toolkit") is None:
            self.skipTest("Terminal composer extra is not installed")
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from agentnik.code_composer import create_composer

        with create_pipe_input() as pipe:
            composer = create_composer(input=pipe, output=DummyOutput())
            pipe.send_text("first line\rsecond line\x1b\r")
            task = composer.prompt()
            self.assertEqual(task, "first line\nsecond line")
            self.assertEqual(composer.history.get_strings(), [task])

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
        import builtins
        from importlib.util import find_spec

        if find_spec("PIL") is None:
            self.skipTest("Terminal image extra is not installed")
        from PIL import Image
        from agentnik.code_image import convert
        from agentnik.image_generation import image_bytes
        from agentnik.code_agent import ProjectFiles
        from agentnik.code_vision import read_image, image_message

        raw = io.BytesIO()
        Image.new("RGBA", (32, 18), (255, 40, 0, 80)).save(raw, "PNG")
        real_import = builtins.__import__

        def no_qt(name, *args, **kwargs):
            if name.startswith("PySide6"):
                raise ModuleNotFoundError(name="PySide6")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=no_qt):
            self.assertEqual(image_bytes(raw.getvalue()), ("image/png", ".png"))
            result = convert(raw.getvalue(), ".webp")
            with self.assertRaisesRegex(ValueError, "transparency"):
                convert(raw.getvalue(), ".jpg")
        with Image.open(io.BytesIO(result)) as asset:
            self.assertEqual(asset.size, (32, 18))
            self.assertEqual(asset.getpixel((0, 0))[3], 80)
        with TemporaryDirectory() as directory, patch("builtins.__import__", side_effect=no_qt):
            root = Path(directory).resolve()
            (root / "asset.webp").write_bytes(result)
            data, mime = read_image(ProjectFiles(root), "asset.webp")
            message = image_message([("asset.webp", data, mime)], "chat")
            self.assertTrue(message["content"][1]["image_url"]["url"].startswith("data:image/webp;base64,"))

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
            first.prompt.side_effect = ["/connection Fixture", "/skills add notes",
                                        *[f"/settings limits {key} 0" for key in
                                          ("rounds", "requests", "calls", "turn_seconds")],
                                        "Create a note", "/permissions allow-all", "Create another note",
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
