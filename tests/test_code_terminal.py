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
            history.start("example", connection, "Different task", second)
            store.db.close()
            store = Store(base / "settings")
            try:
                history = CodeHistory(store, root)
                restored = history.list(first)[0]
                self.assertEqual(restored["coding_context"], {"task": "Find [redacted]", "answer": "Done"})
                self.assertEqual(set(history.sessions()), {first, second})
                self.assertNotIn("coding_context", history.list(second)[0])
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
