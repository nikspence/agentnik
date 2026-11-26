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
            first = Mock()
            first.prompt.side_effect = ["/connection Fixture",
                                        *[f"/settings limits {key} 0" for key in
                                          ("rounds", "requests", "calls", "turn_seconds")],
                                        "Create a note", "/exit"]
            output = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdin.isatty", return_value=True), \
                    patch("agentnik.code_composer.create_composer", return_value=first), \
                    patch("builtins.input", side_effect=["y", "n"]) as approval, \
                    patch.object(core, "open_request", side_effect=[
                        Wire(chat(calls=[edit, delete], finish="tool_calls"), False),
                        Wire(chat("Created the note."), False),
                    ]) as transport, contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(transport.call_count, 2, output.getvalue())
            self.assertEqual(approval.call_count, 2, output.getvalue())
            self.assertEqual((root / "note.txt").read_text(), "reviewed\n")
            self.assertEqual(preserved.read_text(), "Keep me")
            store = Store(data)
            try:
                session_id, record = next(iter(CodeHistory(store, root).sessions().items()))
                self.assertEqual(record["coding_context"]["answer"], "Created the note.")
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
                self.assertFalse(saved["relaxed_tls"])
                self.assertEqual(saved["theme"], "Dark")
                self.assertEqual(saved["language"], "en")
                self.assertFalse(saved["history_visible"])
                configure_code(store, ["limits", "rounds", "default"])
                self.assertNotEqual(load_config(store.config_path)["settings"]["coding_limits"]["rounds"], 12)
            finally:
                store.db.close()

    def test_history_persists_only_completed_context_for_current_project(self):
        from agentnik.code_history import CodeHistory
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
                emit({"kind": "model_response", "stream_id": "1", "text": second})

            def stop(self):
                pass

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            drive_run(Run())
        self.assertEqual(output.getvalue(), second + "\n")

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
