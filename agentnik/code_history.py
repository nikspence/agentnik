"""Independent terminal sessions backed by the shared Code history store."""

import os
from pathlib import Path

from .repositories import RepositoryRegistry
from .research import scrub
from .sessions import append_code_activity
from .storage import Store


def same_project(path, root):
    return os.path.normcase(str(Path(path).resolve())) == os.path.normcase(str(root))


class CodeHistory:
    def __init__(self, store, root):
        self.store = store
        self.root = root

    def list(self, session_id=None):
        return [item for item in self.store.list_sessions()
                if item["mode"] == "code" and same_project(item["path_snapshot"], self.root)
                and (session_id is None or self.session_id(item) == session_id)]

    @staticmethod
    def session_id(record):
        return record.get("coding_terminal_session", record["id"])

    def sessions(self):
        latest = {}
        for record in self.list():
            latest.setdefault(self.session_id(record), record)
        return latest

    def start(self, name, connection, task, session_id=None):
        registry = RepositoryRegistry(self.store)
        project = next((row["id"] for row in registry.list() if same_project(row["path"], self.root)), None)
        if project is None:
            project = registry.put(self.root)
        record = registry.session(project)
        key = connection.get("api_key")
        task = scrub(task, [key])[:2048]
        record.update(code_state="running", coding_last_run_goal=False,
                      coding_models={"model": {"connection": name, "model": connection["model"]}})
        if session_id:
            record["coding_terminal_session"] = session_id
        append_code_activity(record, "prompt", task)
        self.store.save(record)
        return record, task

    def finish(self, record, task, result):
        state = "limited" if result.get("limited") else result.get("status")
        if state not in ("completed", "failed", "blocked", "limited", "cancelled"):
            state = "interrupted"
        answer = result.get("text", "")[:2048]
        record["code_state"] = state
        if answer:
            append_code_activity(record, "finished", answer)
        if state == "completed" and result.get("response_shown") and answer:
            record["coding_context"] = {"task": task, "answer": answer}
        self.store.save(record)
