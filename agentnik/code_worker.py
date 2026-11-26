"""UI-independent worker startup for Code runners."""

from threading import Thread


def start_code_worker(run, emit, *, failed=None, finished=None, daemon=False):
    """Start one runner and notify clients without forwarding raw exceptions."""
    def work():
        reported = False

        def forward(event):
            nonlocal reported
            emit(event)
            if event.get("kind") == "finished":
                reported = True

        try:
            run.run(forward if failed is not None else emit)
        except Exception:
            # Raw worker errors may contain provider details.
            pass
        finally:
            try:
                if not reported and failed is not None:
                    failed()
            finally:
                if finished is not None:
                    finished()

    worker = Thread(target=work, daemon=daemon)
    worker.start()
    return worker
