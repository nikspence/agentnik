"""Independent terminal sessions backed by the shared Code history store."""

import os
from pathlib import Path

from .repositories import RepositoryRegistry
from .research import scrub
from .sessions import append_code_activity, coding_model_binding
from .storage import Store


def same_project(path, root):
    return os.path.normcase(str(Path(path).resolve())) == os.path.normcase(str(root))


def resolve_session_id(sessions, selector):
    """Resolve a full ID, a unique prefix, or the most recent saved session."""
    if selector == "latest":
        return next(iter(sessions), "")
    if selector in sessions:
        return selector
    if not selector:
        return ""
    matches = [ident for ident in sessions if ident.startswith(selector)]
    if len(matches) > 1:
        raise ValueError("That session ID prefix matches multiple sessions. Enter more characters or use /sessions.")
    return matches[0] if matches else ""


def activity_preview(record):
    """Keep the saved task visible alongside a bounded tail of run activity."""
    activity = record.get("code_activity", [])
    if len(activity) <= 20:
        return [entry["text"] for entry in activity]
    earlier, tail = activity[:-20], activity[-20:]
    prompt = next((entry["text"] for entry in earlier if entry["kind"] == "prompt"), None)
    omitted = len(earlier) - (prompt is not None)
    lines = [prompt] if prompt is not None else []
    if omitted:
        lines.append(f"[{omitted} earlier activity entries omitted from this preview.]")
    return [*lines, *(entry["text"] for entry in tail)]


def goal_continuation(record):
    if not record or record.get("code_state") not in ("limited", "blocked", "cancelled", "interrupted", "failed"):
        return None
    goal = record.get("coding_goal")
    if not goal:
        return None
    changes = [entry["text"][:400] for entry in record.get("code_activity", [])
               if entry["kind"] == "project_change"][-8:]
    return {
        "task": goal["objective"],
        "evidence": f"Previous run status: {record['code_state']}. "
                    "Inspect the project before taking action. Some actions may already have happened.\n"
                    + goal["detail"]
                    + (f"\nRecorded goal steps: {record['coding_goal_progress']['steps']}."
                       if "coding_goal_progress" in record else "")
                    + ("\nRecent confirmed project changes from the previous run:\n"
                       + "\n".join(f"- {change}" for change in changes) if changes else ""),
    }


def project_context_for_resume(records):
    """Restore the latest project turn only for the resumed model binding."""
    if not records:
        return None
    binding = coding_model_binding(records[0])
    for record in records:
        if record.get("coding_file_scope") == "machine":
            continue
        if record.get("code_state") == "completed" and coding_model_binding(record) == binding:
            return record.get("coding_context")
        break
    return None


class CodeHistory:
    def __init__(self, store, root):
        self.store = store
        self.root = root

    def list(self, session_id=None):
        return [item for item in self.store.list_sessions(mode="code", terminal_session=session_id)
                if same_project(item["path_snapshot"], self.root)]

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
            goal = record["coding_goal"]
            previous = goal.get("detail")
            goal.update(status="interrupted", detail=(detail + ("\n" + previous if previous else ""))[:4000])
        append_code_activity(record, "interrupted", detail)
        self.store.save(record)

    def checkpoint_goal(self, record, event):
        goal = record.get("coding_goal")
        if not goal or record.get("code_state") != "running":
            return
        if event["kind"] == "goal_status":
            goal["detail"] = event["detail"][:4000]
        elif event["kind"] == "goal_progress":
            record["coding_goal_progress"] = {"steps": event["steps"], "seconds": event["seconds"]}
        else:
            return
        self.store.save(record)

    def checkpoint(self, record, event):
        if event["kind"] == "plan":
            from .task_plan import validate_plan

            record["coding_plan"] = validate_plan(event.get("plan"))
            self.store.save(record)
        elif event["kind"] in ("project_change", "image_generated"):
            path = event.get("path")
            if not isinstance(path, str):
                return
            if event["kind"] == "image_generated":
                detail = f"Generated image: {path}"
            else:
                detail = f"Applied project {event['label']}: {path}"
            append_code_activity(record, "project_change", detail[:2048])
            self.store.save(record)
        else:
            self.checkpoint_goal(record, event)

    def start(self, name, connection, task, session_id=None, *, goal=False, extra_secrets=(), skill_pins=None,
              machine_scope=False):
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
            if machine_scope:
                record["coding_file_scope"] = "machine"
        append_code_activity(record, "prompt", task)
        self.store.save(record)
        return record, task

    def finish(self, record, task, result, *, save_context=True):
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
        if save_context and state == "completed" and result.get("response_shown") and answer:
            record["coding_context"] = {"task": task, "answer": answer}
        self.store.save(record)
