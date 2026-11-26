"""Offline checks for the Code worker contract used by both clients."""

import unittest

from agentnik.code_worker import approval_event_is_live, start_code_worker


class CodeWorkerTests(unittest.TestCase):
    def collect(self, work):
        class Run:
            run_id = "fixture"

            def run(self, emit):
                work(emit)

        events = []
        thread = start_code_worker(
            Run(), events.append, interruption_text="Check the workspace.",
            finished=lambda: events.append("done"),
        )
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        return events

    def test_client_checks_a_queued_approval_against_the_current_run(self):
        from unittest.mock import Mock

        run = Mock()
        event = {"kind": "edit_proposal", "fingerprint": "fixture"}
        run.approval_pending.side_effect = [True, False]
        self.assertTrue(approval_event_is_live(run, event))
        self.assertFalse(approval_event_is_live(run, event))
        self.assertTrue(approval_event_is_live(object(), event))
        self.assertEqual([call.args for call in run.approval_pending.call_args_list],
                         [("fixture",), ("fixture",)])

    def test_first_terminal_result_wins_and_is_last_event(self):
        output = {"kind": "output", "text": "Working"}
        result = {"kind": "finished", "status": "completed"}

        def work(emit):
            emit(output)
            emit(result)
            emit({"kind": "finished", "status": "failed"})
            emit(output)
            raise RuntimeError("Private error after completion")

        self.assertEqual(self.collect(work), [output, result, "done"])

    def test_unexpected_worker_error_reports_one_scrubbed_interruption(self):
        def work(emit):
            raise RuntimeError("Private provider error")

        self.assertEqual(self.collect(work), [
            {"kind": "finished", "status": "interrupted", "run_id": "fixture",
             "text": "Check the workspace."},
            "done",
        ])
