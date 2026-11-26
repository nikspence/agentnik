"""UI-independent worker startup for Code runners."""

from threading import Thread


def start_code_worker(run, emit, *, interruption_text, finished=None, daemon=False):
    """Start one runner and notify clients without forwarding raw exceptions."""
    def work():
        reported = False

        def forward(event):
            nonlocal reported
            emit(event)
            if event.get("kind") == "finished":
                reported = True

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
