"""UI-independent worker startup for Code runners."""

from threading import Thread


def approval_event_is_live(run, event):
    """Check a queued proposal immediately before a client renders it."""
    check = getattr(run, "approval_pending", None)
    return check is None or check(event["fingerprint"]) is not False


def start_code_worker(run, emit, *, interruption_text, finished=None, daemon=False):
    """Deliver events in order, ending with one result before notifying completion."""
    def work():
        reported = False

        def forward(event):
            nonlocal reported
            if reported:
                return
            if event.get("kind") == "finished":
                reported = True
            emit(event)

        try:
            run.run(forward)
        except Exception:
            # Raw worker errors may contain provider details.
            pass
        finally:
            try:
                if not reported:
                    event = {"kind": "finished", "status": "interrupted", "text": interruption_text}
                    run_id = getattr(run, "run_id", None)
                    if run_id is not None:
                        event["run_id"] = run_id
                    emit(event)
            finally:
                if finished is not None:
                    finished()

    worker = Thread(target=work, daemon=daemon)
    worker.start()
    return worker
