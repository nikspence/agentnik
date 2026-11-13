# Agentnik project track format, version 1

Agentnik can inspect existing tracks and create new tracks from user-authored or explicitly applied Heavy-model draft proposals. Existing v1 tracks can be edited through per-file review; track execution and reconciliation are not implemented. Files stay in the project and remain authoritative; opening them does not call a model or execute project code. The existing session checklist remains independent and is never changed by the viewer.

## Layout

```text
agentnik-plans/
  context.md  (optional project context)
  tracks/
    <track-id>/
      track.json
      spec.md
      plan.md
```

Track IDs and task IDs are stable lowercase identifiers matching `[a-z][a-z0-9_-]{0,63}`. The directory and `track.json` ID must match. Use project-relative paths; the existing project protections reject traversal, protected paths, links, and hard-linked files. Each file is UTF-8, at most 128,000 bytes. Listing examines up to 200 directory entries and returns at most 100 track directories. Limit hits are reported. A project with no track directory is an ordinary empty project; old sessions require no migration.

`context.md` is an optional project context document. It can describe goals, conventions and validation expectations and should link to the existing README and applicable `AGENTS.md` files rather than override them. It is read-only, untrusted, subject to the same 128,000-byte and path limits, and is not automatically loaded into model requests.

## Metadata contract

`track.json` is a JSON object with exactly `version`, `id`, `title`, `explanation`, and `tasks`. Version is the integer `1`. Title is a nonempty single line of at most 160 characters. Explanation follows the existing checklist contract, up to 1,000 characters. Tasks are an ordered array of 1–20 objects with exactly:

- `id`: unique stable task ID; do not reuse an ID for a different task.
- `phase`: nonempty single line, at most 120 characters.
- `step`: nonempty single line, at most 200 characters.
- `status`: `pending`, `in_progress`, `completed`, or `blocked`; at most one may be `in_progress`.
- `evidence`: zero to eight objects, each with exactly `status` and `detail`. Evidence status is `passed`, `failed`, `unknown`, or `not_run`; detail is a nonempty single line of at most 500 characters.

Statuses are reported progress, not proof of completion. Evidence is also a claim, not independent verification. A `completed` task without passed evidence is not presented as verified. There is no implied authorization to run tools, tests, or commands. For example:

```json
{"version": 1, "id": "sample", "title": "Example", "explanation": "Inspect and validate.", "tasks": [{"id": "inspect", "phase": "Discovery", "step": "Inspect the existing contract", "status": "pending", "evidence": [{"status": "not_run", "detail": "Checks have not run."}]}]}
```

## Documents and projection

`spec.md` contains requirements, scope and acceptance criteria; `plan.md` contains the human-readable phased plan. Both are displayed as plain text, preserved byte-for-byte, and may contain Markdown unknown to Agentnik. Version 1 does not parse or reconcile checkboxes in these documents: task identity and durable status come from `track.json`. The bounded checklist projection maps each task's `step` and `status` in order. A selected-track run stores separate model-reported progress keyed by task ID in the coding session; it never automatically updates these documents. Review progress against current statuses and use the reviewed track editor for any desired changes. A changed source hash is flagged; evidence and progress are not independently verified.

The guided reconciliation view starts with existing statuses and evidence, and lets the user select statuses and optionally replace a task's evidence with a manually entered result and description. A newly completed task requires nonempty passed evidence with no failed, unknown or unrun entries. This does not verify the evidence. A complete metadata diff requires approval; unrelated JSON formatting is retained, and the specification and plan are not rewritten. The run's track and project-context hashes must still match, including at approval. Stale reports are retained for inspection but cannot be applied through this flow.

Invalid, duplicate, mismatched, unknown-field, or newer metadata is unavailable rather than rewritten. Missing, oversized, linked, or unreadable documents cannot be opened. The new-track publisher never overwrites an existing track. It requires separate approval for every directory and file, shows the complete proposed file diff, rechecks previously written files, and saves partial progress in the session after each operation. Rejection or failure leaves earlier approved changes in place; inspect them before retrying. Files are not a multi-file atomic transaction. Existing v1 tracks can also be edited through session-persisted drafts and individual full-diff approvals. Before each write, all three file contents are checked against the recorded hashes; an external change stops the review. Earlier approved writes remain in place, so a multi-file edit is not atomic. Unchanged files retain their original bytes, including line endings. Conflict reconciliation remains future work. This contract does not grant permission to run commands or change Git state.

## Relationship to Conductor

This format is Agentnik-specific, not a Conductor compatibility claim. The pinned [Conductor v0.4.1 README](https://github.com/gemini-cli-extensions/conductor/blob/conductor-v0.4.1/README.md) describes separate `spec.md`, `plan.md`, and `metadata.json` artifacts under `conductor/tracks/`. The [current upstream README](https://github.com/gemini-cli-extensions/conductor) describes a later plugin workflow. These descriptions do not establish a complete stable schema or prove Agentnik can execute the plugin. The fixture in this repository is synthetic and tests Agentnik's contract, not upstream compatibility. A future read-only adapter needs representative artifacts pinned to a verified upstream revision before import or mutation is considered.
