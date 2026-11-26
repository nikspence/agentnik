"""UI-independent worker startup for Code runners."""

from threading import Event, Lock, Thread
from weakref import ref


STEERING_OUTCOMES = {
    "steering_delivered": "Steering delivered",
    "steering_undelivered": "Steering not delivered",
    "steering_uncertain": "Steering delivery uncertain",
}


def approval_event_is_live(run, event):
    """Check a queued proposal immediately before a client renders it."""
    check = getattr(run, "approval_pending", None)
    return check is None or check(event["fingerprint"]) is not False


class CodeWorker:
    """A running Code job with a single cancellation snapshot and a joinable lifetime."""

    def __init__(self, run, thread, result_ready):
        self._run_ref = ref(run)
        self._thread = thread
        self._result_ready = result_ready
        self._stop_lock = Lock()
        self._stopped = False

    @property
    def run(self):
        return self._run_ref()

    def stop(self):
        """Request cancellation once and return any steering snapshot to the first caller."""
        with self._stop_lock:
            if self._stopped:
                return None
            run = self.run
            result = run.stop() if run is not None else None
            self._stopped = True
            return result

    @property
    def result_ready(self):
        return self._result_ready.is_set()

    def approval_pending(self, fingerprint):
        run = self.run
        return not (self._stopped or self.result_ready) and run is not None and approval_event_is_live(run, {"fingerprint": fingerprint})

    def decide(self, fingerprint, approved, scope="once", git_credentials=None):
        run = self.run
        if self._stopped or self.result_ready or run is None:
            return False
        if git_credentials is not None:
            return run.decide(fingerprint, approved, scope, git_credentials=git_credentials)
        if scope != "once":
            return run.decide(fingerprint, approved, scope)
        return run.decide(fingerprint, approved)

    def steer(self, message, *, approval_fingerprint=None):
        run = self.run
        if self._stopped or self.result_ready or run is None:
            return False
        if approval_fingerprint is None:
            return run.steer(message)
        return run.steer(message, approval_fingerprint=approval_fingerprint)

    def join(self, timeout=None):
        self._thread.join(timeout)

    def is_alive(self):
        return self._thread.is_alive()


def start_code_worker(run, emit, *, interruption_text, finished=None, daemon=False):
    """Deliver events in order, ending with one result before notifying completion."""
    result_ready = Event()

    def work():

        def forward(event):
            if result_ready.is_set():
                return
            if event.get("kind") == "finished":
                result_ready.set()
            emit(event)

        try:
            run.run(forward)
        except Exception:
            # Raw worker errors may contain provider details.
            pass
        finally:
            try:
                if not result_ready.is_set():
                    event = {"kind": "finished", "status": "interrupted", "text": interruption_text}
                    run_id = getattr(run, "run_id", None)
                    if run_id is not None:
                        event["run_id"] = run_id
                    forward(event)
            finally:
                if finished is not None:
                    finished()

    worker = Thread(target=work, daemon=daemon)
    worker.start()
    return CodeWorker(run, worker, result_ready)
