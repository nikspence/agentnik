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
                    configure_code(store, ["limits", "rounds", "0"])
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
