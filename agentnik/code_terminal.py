"""Terminal adapter for Agentnik's existing Code run and approval contract."""

from queue import Empty, Queue
from threading import Thread
import unicodedata


def terminal_text(text):
    return "".join(
        ch if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
        else repr(ch)[1:-1]
        for ch in str(text)
    )


def load_run_settings(data_dir, name, model):
    from . import core, tls
    from .storage import Store

    store = Store(data_dir)
    try:
        connections = {**core.environment_connections(), **store.connections()}
        connection = connections.get(name)
        if connection is None:
            raise ValueError("Unknown connection. Use /connections to list names.")
        connection = dict(connection)
        core.base_url(connection.get("url", ""))
        if model:
            connection["model"] = model
        if not connection.get("model"):
            raise ValueError("No model selected. Use /model to specify one.")
        settings = store.config["settings"]
        tls.configure(settings.get("relaxed_tls", False))
        return connection, settings.get("coding_limits")
    finally:
        store.db.close()


def drive_run(run):
    events = Queue()
    done = object()

    def worker():
        try:
            run.run(events.put)
        except Exception:
            events.put({"kind": "finished", "text": "Coding run failed to start or stopped unexpectedly."})
        finally:
            events.put(done)

    thread = Thread(target=worker)
    thread.start()
    try:
        while True:
            try:
                event = events.get(timeout=0.1)
            except Empty:
                continue
            if event is done:
                return
            kind = event["kind"]
            if kind in ("edit_proposal", "operation_proposal"):
                proposal = event["proposal"]
                if kind == "edit_proposal":
                    fields = ("cwd", "path", "diff")
                elif proposal.get("operation") == "run_shell":
                    fields = ("cwd", "shell", "command", "max_seconds")
                else:
                    print("This operation cannot be reviewed in the terminal preview. Rejected.")
                    run.decide(event["fingerprint"], False)
                    continue
                for field in fields:
                    print(f"{field}: {terminal_text(proposal[field])}")
                approved = input("Approve once? [y/N] ").strip().lower() == "y"
                run.decide(event["fingerprint"], approved)
            elif kind in ("output", "model_response", "finished"):
                if event.get("text") and not (kind == "finished" and event.get("response_shown")):
                    print(terminal_text(event["text"]))
                if kind == "finished" and event.get("usage"):
                    print(terminal_text(event["usage"]))
    except (KeyboardInterrupt, EOFError):
        run.stop()
        print("\nStopping Code run…")
    finally:
        run.stop()
        thread.join()
