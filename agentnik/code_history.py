"""Independent terminal sessions backed by the shared Code history store."""

import os
from pathlib import Path

from .repositories import RepositoryRegistry
from .research import scrub
from .sessions import append_code_activity
from .storage import Store


def same_project(path, root):
    return os.path.normcase(str(Path(path).resolve())) == os.path.normcase(str(root))


def goal_continuation(record):
    if not record or record.get("code_state") not in ("limited", "blocked", "cancelled", "interrupted", "failed"):
        return None
    goal = record.get("coding_goal")
    if not goal:
        return None
    return {
        "task": goal["objective"],
        "evidence": f"Previous run status: {record['code_state']}. "
                    "Inspect the project before taking action. Some actions may already have happened.\n"
                    + goal["detail"],
    }


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

    def recover_interrupted(self, record, lease):
        """Reconcile a terminal run only after exclusively reopening its session."""
        session_id = record.get("coding_terminal_session")
        if not session_id or lease.session_id != session_id or record.get("code_state") not in (
            "running", "awaiting_approval",
        ):
            return
        detail = "The previous terminal run ended without a saved result. Check the project before continuing."
        record["code_state"] = "interrupted"
        if record.get("coding_last_run_goal") and record.get("coding_goal", {}).get("status") == "active":
            record["coding_goal"].update(status="interrupted", detail=detail)
        append_code_activity(record, "interrupted", detail)
        self.store.save(record)

    def start(self, name, connection, task, session_id=None, *, goal=False, extra_secrets=(), skill_pins=None):
        registry = RepositoryRegistry(self.store)
        project = next((row["id"] for row in registry.list() if same_project(row["path"], self.root)), None)
        if project is None:
            project = registry.put(self.root)
        record = registry.session(project)
        key = connection.get("api_key")
        objective = scrub(task, [key, *extra_secrets])[:16000]
        task = objective[:2048]
        record.update(code_state="running", coding_last_run_goal=goal,
                      coding_models={"model": {"connection": name, "model": connection["model"]}})
        if goal:
            record["coding_goal"] = {"objective": objective, "status": "active", "detail": ""}
        if skill_pins:
            record.update(coding_skills=list(skill_pins), coding_skill_pins=dict(skill_pins))
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
        if record.get("coding_last_run_goal"):
            detail = "\n".join(dict.fromkeys(text for text in (answer, result.get("last_goal_detail", "")) if text))
            record["coding_goal"].update(status=state, detail=detail[:4000])
            if "goal_progress" in result:
                record["coding_goal_progress"] = result["goal_progress"]
        if answer:
            append_code_activity(record, "finished", answer)
        if state == "completed" and result.get("response_shown") and answer:
            record["coding_context"] = {"task": task, "answer": answer}
        self.store.save(record)
