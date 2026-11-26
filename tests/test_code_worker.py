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

    def test_worker_returns_one_cancellation_snapshot_across_cleanup_calls(self):
        from threading import Event
        from unittest.mock import Mock

        run = Mock()
        stopped = Event()
        run.run.side_effect = lambda emit: stopped.wait(2)
        snapshot = {"undelivered": ["Queued"], "uncertain": [], "delivered": []}

        def stop():
            stopped.set()
            return snapshot

        run.stop.side_effect = stop
        worker = start_code_worker(run, lambda event: None, interruption_text="Stopped")
        try:
            self.assertIs(worker.run, run)
            self.assertTrue(worker.approval_pending("proposal"))
            worker.decide("proposal", False)
            worker.steer("Review first", approval_fingerprint="proposal")
            self.assertEqual(worker.stop(), snapshot)
            self.assertFalse(worker.approval_pending("proposal"))
            self.assertFalse(worker.decide("proposal", True))
            self.assertFalse(worker.steer("Too late"))
            run.decide.assert_called_once_with("proposal", False)
            run.steer.assert_called_once_with("Review first", approval_fingerprint="proposal")
            self.assertIsNone(worker.stop())
            run.stop.assert_called_once()
        finally:
            stopped.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_final_result_closes_controls_even_while_worker_is_cleaning_up(self):
        from threading import Event
        from unittest.mock import Mock

        release = Event()
        result_seen = Event()
        run = Mock()

        def work(emit):
            emit({"kind": "finished", "status": "completed"})
            release.wait(2)

        run.run.side_effect = work
        worker = start_code_worker(run, lambda event: result_seen.set(), interruption_text="Interrupted")
        try:
            self.assertTrue(result_seen.wait(2))
            self.assertTrue(worker.is_alive())
            self.assertTrue(worker.result_ready)
            self.assertFalse(worker.approval_pending("proposal"))
            self.assertFalse(worker.decide("proposal", True))
            self.assertFalse(worker.steer("Too late"))
            run.approval_pending.assert_not_called()
            run.decide.assert_not_called()
            run.steer.assert_not_called()
        finally:
            release.set()
            worker.join(timeout=2)

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
