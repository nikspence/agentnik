"""Independent terminal sessions backed by the shared Code history store."""

from contextlib import closing
from dataclasses import dataclass
from itertools import chain, islice
import hashlib
import os
from pathlib import Path
from uuid import UUID

from .code_worker import STEERING_OUTCOMES
from .repositories import RepositoryRegistry
from .research import scrub
from .sessions import append_code_activity, coding_model_binding
from .storage import Store


def saved_session_metadata(data_dir, root):
    """Read client-safe project metadata without opening sessions or exposing their contents."""
    if not (Path(data_dir) / "history.sqlite3").exists():
        return []
    store = Store(data_dir, read_only_history=True)
    try:
        return [
            {"id": ident, "status": record.get("code_state", "idle"),
             "scope": record.get("coding_file_scope", "project"), "goal_status": goal,
             "updated_at": record["updated"]}
            for ident, (record, goal) in CodeHistory(store, root).session_summaries().items()
        ]
    finally:
        store.db.close()


def same_project(path, root):
    try:
        saved_root = Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        # One stale project path must not hide sessions for other projects.
        return False
    return os.path.normcase(str(saved_root)) == os.path.normcase(str(Path(root).resolve()))


def resolve_session_id(sessions, selector):
    """Resolve a full ID, a unique prefix, or the most recent saved session."""
    selector = selector.lower()
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
    scope = ["[Saved turn used machine scope]"] if record.get("coding_file_scope") == "machine" else []
    if len(activity) <= 20:
        return [*scope, *(entry["text"] for entry in activity)]
    earlier, tail = activity[:-20], activity[-20:]
    prompt = next((entry["text"] for entry in earlier if entry["kind"] == "prompt"), None)
    omitted = len(earlier) - (prompt is not None)
    lines = [*scope, prompt] if prompt is not None else scope
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


@dataclass(frozen=True)
class GoalContinuation:
    status: str
    connection: str | None = None
    scope: str | None = None
    context: dict | None = None
    model: str | None = None
    route: str | None = None


def coding_route_digest(connection):
    """Identify the request destination without storing the URL or credentials."""
    from .core import endpoint

    if not connection.get("url"):
        return None
    return hashlib.sha256(endpoint(connection).encode("utf-8")).hexdigest()


def prepare_goal_continuation(record, connection, scope):
    """Check a stopped goal's binding without exposing evidence on a mismatch."""
    context = goal_continuation(record)
    if context is None:
        return GoalContinuation("unavailable")
    binding = coding_model_binding(record)
    saved_connection = binding.get("connection")
    saved_scope = record.get("coding_file_scope", "project")
    if saved_connection != connection:
        return GoalContinuation("connection_mismatch", connection=saved_connection)
    if saved_scope != scope:
        return GoalContinuation("scope_mismatch", scope=saved_scope)
    return GoalContinuation("ready", connection=saved_connection, scope=saved_scope, context=context,
                            model=binding.get("model"), route=record.get("coding_run_route") or record.get("coding_goal_route"))


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


@dataclass(frozen=True)
class ResumeSnapshot:
    record: dict
    connection: str
    model: str
    project_context: dict | None
    skill_pins: dict
    prompt_history: tuple[str, ...]
    activity: tuple[str, ...]
    latest_goal_turn: dict | None
    project_context_route: str | None = None


def resume_snapshot(records):
    """Prepare saved state without starting a run or applying UI formatting."""
    records = iter(records)
    record = next(records, None)
    if record is None:
        raise ValueError("Choose a saved session before preparing resume state.")
    binding = coding_model_binding(record)
    prompts, preview = [], []
    latest_goal = context = context_route = None
    project_turn_seen = False
    for index, saved in enumerate(chain((record,), records)):
        if index < 20:
            preview.append(activity_preview(saved))
        if len(prompts) < 100:
            for entry in reversed(saved.get("code_activity", [])):
                if entry["kind"] == "prompt":
                    prompts.append(entry["text"])
                    if len(prompts) == 100:
                        break
        if latest_goal is None and "coding_goal" in saved:
            latest_goal = saved
        if not project_turn_seen and saved.get("coding_file_scope") != "machine":
            project_turn_seen = True
            if saved.get("code_state") == "completed" and coding_model_binding(saved) == binding:
                context = saved.get("coding_context")
                context_route = saved.get("coding_run_route") or saved.get("coding_goal_route")
        if index >= 19 and len(prompts) == 100 and latest_goal is not None and project_turn_seen:
            break
    return ResumeSnapshot(
        record, binding.get("connection", ""), binding.get("model", ""),
        context, dict(record.get("coding_skill_pins", {})), tuple(reversed(prompts)),
        tuple(line for turn in reversed(preview) for line in turn), latest_goal, context_route,
    )


class CodeHistory:
    def __init__(self, store, root):
        self.store = store
        self.root = root

    def list(self, session_id=None):
        with closing(self.iter_project_turns(session_id)) as records:
            return list(records)

    def iter_project_turns(self, session_id=None):
        matches = {}
        with closing(self.store.iter_sessions(mode="code", terminal_session=session_id)) as records:
            for record in records:
                path = record["path_snapshot"]
                if path not in matches:
                    matches[path] = same_project(path, self.root)
                if matches[path]:
                    yield record

    def turn_window(self, session_id, offset, count):
        """Read a bounded window of valid turns belonging to this project."""
        with closing(self.iter_project_turns(session_id)) as records:
            return list(islice(records, offset, offset + count))

    @staticmethod
    def session_id(record):
        return record.get("coding_terminal_session", record["id"])

    def sessions(self):
        latest = {}
        with closing(self.iter_project_turns()) as records:
            for record in records:
                latest.setdefault(self.session_id(record), record)
        return latest

    def session_summaries(self):
        """Summarize the latest turn and latest goal independently for each session."""
        latest, goals = {}, {}
        with closing(self.iter_project_turns()) as records:
            for record in records:
                ident = self.session_id(record)
                latest.setdefault(ident, record)
                if "coding_goal" in record:
                    goals.setdefault(ident, record["coding_goal"]["status"])
        return {ident: (record, goals.get(ident)) for ident, record in latest.items()}

    def resolve_session(self, selector):
        """Resolve non-exact selectors without retaining session payloads."""
        with closing(self.iter_project_turns()) as records:
            if selector == "latest":
                record = next(records, None)
                return self.session_id(record) if record is not None else ""
            if not selector:
                return ""
            candidates = dict.fromkeys(
                ident for record in records if (ident := self.session_id(record)).startswith(selector)
            )
        return resolve_session_id(candidates, selector)

    def lease_for_resume(self, selector, lease):
        """Resolve the session and acquire its lease before reading resume state."""
        selector = selector.lower()
        try:
            full_id = str(UUID(selector)) == selector
        except ValueError:
            full_id = False
        if full_id:
            # Check membership before taking the lease. Do not load a long
            # transcript twice, and do not reuse a pre-lease snapshot.
            with closing(self.store.iter_sessions(mode="code", terminal_session=selector)) as records:
                found = any(same_project(record["path_snapshot"], self.root) for record in records)
            ident = selector if found else ""
        else:
            ident = self.resolve_session(selector)
        if ident:
            lease.select(ident)
        return ident

    def prepare_resume(self, selector, lease):
        """Acquire the saved session and return its client-neutral resume state."""
        ident = self.lease_for_resume(selector, lease)
        if not ident:
            return "", None
        latest = self.turn_window(ident, 0, 1)
        if not latest:
            return ident, None
        # Keep the recovery write separate from an open SQLite read cursor.
        self.recover_interrupted(latest[0], lease)
        with closing(self.iter_project_turns(ident)) as records:
            return ident, resume_snapshot(records)

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
        kind = event["kind"]
        if kind in STEERING_OUTCOMES:
            message = event.get("text")
            if not isinstance(message, str) or not message:
                return
            detail = message[:1900] + (" [shortened]" if len(message) > 1900 else "")
            append_code_activity(record, kind, f"{STEERING_OUTCOMES[kind]}: {detail}")
            self.store.save(record)
        elif kind == "plan":
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
        route = coding_route_digest(connection)
        if route is not None:
            record["coding_run_route"] = route
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
        partial = result.get("partial_response")
        if state != "completed" and isinstance(partial, str) and partial:
            append_code_activity(record, "output", "[Incomplete model response]\n" + partial[:2000])
        if answer:
            append_code_activity(record, "finished", answer)
        if save_context and state == "completed" and result.get("response_shown") and answer:
            record["coding_context"] = {"task": task, "answer": answer}
        self.store.save(record)
