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


def drive_run(run, write=print):
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
    streamed = {}
    partial_line = False
    try:
        while True:
            try:
                event = events.get(timeout=0.1)
            except Empty:
                continue
            if event is done:
                if partial_line:
                    write()
                return
            kind = event["kind"]
            if kind == "model_delta":
                key = event["stream_id"]
                streamed[key] = streamed.get(key, "") + event["text"]
                write(terminal_text(event["text"]), end="", flush=True)
                partial_line = True
                continue
            if kind == "model_response":
                prefix = streamed.pop(event.get("stream_id"), "")
                response = event.get("text", "")
                if partial_line and prefix and response.startswith(prefix):
                    write(terminal_text(response[len(prefix):]))
                    partial_line = False
                    continue
            if partial_line:
                write()
                partial_line = False
            if kind in ("edit_proposal", "operation_proposal"):
                proposal = event["proposal"]
                if kind == "edit_proposal":
                    fields = ("cwd", "path", "diff")
                elif proposal.get("operation") == "run_shell":
                    fields = ("cwd", "shell", "command", "max_seconds")
                else:
                    write("This operation cannot be reviewed in the terminal preview. Rejected.")
                    run.decide(event["fingerprint"], False)
                    continue
                for field in fields:
                    write(f"{field}: {terminal_text(proposal[field])}")
                approved = input("Approve once? [y/N] ").strip().lower() == "y"
                run.decide(event["fingerprint"], approved)
            elif kind in ("output", "model_response", "finished"):
                if event.get("text") and not (kind == "finished" and event.get("response_shown")):
                    write(terminal_text(event["text"]))
                if kind == "finished" and event.get("usage"):
                    write(terminal_text(event["usage"]))
    except (KeyboardInterrupt, EOFError):
        run.stop()
        write("\nStopping Code run…")
    finally:
        run.stop()
        thread.join()
