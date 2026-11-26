import contextlib
import io
import unittest
from unittest.mock import patch

from agentnik.code_terminal import drive_run
from agentnik.code_stream import visible_prefix


class TerminalRunTests(unittest.TestCase):
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
