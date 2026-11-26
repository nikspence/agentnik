"""UI-independent worker startup for Code runners."""

from threading import Thread


def start_code_worker(run, emit, *, failed=None, finished=None, daemon=False):
    """Start one runner and notify clients without forwarding raw exceptions."""
    def work():
        try:
            run.run(emit)
        except Exception:
            if failed is not None:
                failed()
        finally:
            if finished is not None:
                finished()

    worker = Thread(target=work, daemon=daemon)
    worker.start()
    return worker
