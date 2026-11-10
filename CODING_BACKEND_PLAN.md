# Agentnik-owned coding backend

Agentnik owns the coding loop and uses the same configured connections/models as chat. Codex is inspiration for interaction design only: no Codex executable, account, app-server, or CLI runtime is required. The abandoned external-protocol spike is preserved in Git history, not shipped as the active backend.

## Heavy and light models in one workflow

Each Code pane has independent Heavy and Light connection/model assignments. Select any alias supported by the connection, including LiteLLM coding models, or use Choose model to retrieve its model list. Listing does not establish tool capability. Start with a tool-capable heavy model; the light role is optional and is not automatically chosen.

The heavy model owns the task, repository tools and edit proposals. Its `delegate_light` tool sends a bounded task/context to the user-selected light model for routine analysis. The light model has no repository tools or execution rights; its result returns to the heavy model through the heavy protocol's correlated tool result. Heavy and light can use different providers/protocols. Opaque provider history remains in its original protocol; Agentnik exchanges plain bounded task/results between roles rather than replaying one provider's reasoning items to another.

Delegation is visible in activity and shares the run's request/time/context budgets. Each new model request is attributable to a configured role. No model/provider fallback, automatic model selection or background capability probes occur. Assigning a light model authorizes bounded delegated context to that endpoint. File content can therefore reach either selected service; only connection labels/model aliases are persisted, not credentials. Saved assignments do not start anything on reopen.

## First runnable coding slice

The model can list project directories, read bounded UTF-8 files and propose complete file content. Existing files must be read before editing. Each edit displays the full diff and waits for explicit one-shot approval bound to the run, path, original content hash and proposed content. Rejected proposals cannot silently become applied edits. Conflicting user edits cause the write to stop; already approved/applied changes are retained on cancellation or later failure. Optional managed web research, approved single-file deletion, directory creation and shell commands are available. Shell commands are not sandboxed and can access the network or run Git with the user's permissions.

Project operations reject traversal, absolute/drive paths, symlinks/junctions, hard-linked files, common credential locations and reserved paths. Reads and writes are limited to 32 KB per file. Changes use temporary files and atomic replacement/new-file publication, preserve existing permission bits, and recheck the original hash before committing. A process-local edit lock serializes Agentnik's own edits. These checks are not an OS sandbox or a guarantee against a hostile external process racing filesystem changes. User approval and a selected working directory do not grant broader execution rights.

The workflow shares limits of nine model requests (including light delegations), sixteen calls, 100 KB retained request context and five minutes per run, using the existing bounded protocol parsers. UI cancellation stops scheduling and invalidates approval; remote inference may still complete or be billed. Activity retains 32 bounded records; full pending diffs are for review and are not persisted as executable actions. Reopening a pending run marks interruption and never resumes requests or edits. An explicit per-run option sends the displayed, bounded last completed task and answer as plain messages; it does not replay provider-specific reasoning or tool exchanges. Each run creates fresh file observations and approvals.

## Approval and next steps

The earlier no-execution simulation remains available for trying the UI. Its approvals cannot authorize real edits. Optional System One advice applies to shell approvals only; other operations show **Not checked**. Heavy/light model outputs and advisory results are not execution authority.

Optional Decision advice sends the exact shell command, working directory, shell, and inherited environment variable names to the selected System One endpoint; environment values and file contents are not sent. The checkbox defaults off. A bounded asynchronous request validates known safety categories and optional confidence and displays an advisory badge tied to the pending shell approval. Unknown, malformed, failed, and timed-out responses remain unknown; a badge never approves a command. Cancellation invalidates late results. Offline fixtures cover the request and approval lifecycle; no real decision model has been verified for this feature.

Completed and failed runs report Heavy and Light request counts and provider-reported input/output tokens separately; missing counts are marked unknown or known usage only. Cancelled runs may lack a final summary. Next: validate more tool-capable models through explicitly authorized checks, improve task routing controls, and add tests for longer multi-file work.

## Filesystem and shell tools

Single-file deletion requires a prior read, shows a deletion diff, and rechecks the content hash after approval. Directory creation is limited to one directory with an existing parent. Each action uses a separate approval and project path checks; recursive deletion is not provided as a filesystem tool.

The shell executor binds approval to the exact command, shell, working directory and inherited environment snapshot. The preview discloses unrestricted user-level filesystem and network access; shell commands can execute Git or other programs. PowerShell on Windows runs in a kill-on-close process job; POSIX uses a process group, which does not contain detached processes. Command time and output are bounded, known keys are redacted, and cancellation retains completed effects. A Windows build-host smoke check covered PowerShell and child-process cancellation; POSIX and live model compatibility remain open. Stronger OS isolation, interactive command support, and MCP/Skills integration remain future work.

## Planned web research and adjustable run limits

Routing direction requested: reserve Ollama-key-backed search for direct Ollama Cloud connections, identified by their actual configured endpoint rather than a model alias. LiteLLM and other gateways must not be treated as direct Ollama merely because a model name contains Ollama. For other connections, use a supported, explicitly configured provider-hosted search capability when available; otherwise use Agentnik-managed search and public-page fetch. Coding now uses Google HTML search for non-direct connections and credential-free public page reads with bounded same-host link discovery. Direct Ollama Cloud uses a configured Ollama profile or Google when no profile is available. Strict navigation disables search but permits direct public page reads. Provider-hosted search is not yet integrated into the Code loop. Google HTML may change or block automated access, and Google restricts automated searches without permission; do not bypass challenges. Preserve explicit opt-in, capability evidence, disclosure, and budgets.

An opt-in per-pane checkbox gives Heavy public page fetch and, where navigation policy permits, Google or direct Ollama search. The Code pane can manage shared Ollama profiles directly. If Google returns a block, challenge, or unrecognized response, search is unavailable for the remainder of the run without another search attempt; the model receives a bounded error and may continue reading known public URLs. Activity shows searches, backend progress, and source IDs and URLs; results are marked untrusted and the model is asked to identify sources in its final answer. A Sources dialog can open or copy up to 32 public links from the latest coding run, persisted with the pane. IDs are scoped to one run and do not establish that a source supports a claim. Calls share coding budgets and Light retains bounded delegation without tools. Offline fixtures cover search, fetch, source labels, the source dialog, and failure handling; live coding research, live Google HTML behavior, and native source-dialog review remain to be validated. Hosted search and chat research routing policies are not yet available to the coding loop.

The **Limits…** dialog provides bounded per-pane settings for tool rounds, model requests, tool calls, elapsed seconds, and context bytes, with defaults and reset. The run snapshots these values and shares budgets across Heavy, Light, and web work. Limit failures identify the exhausted budget and retain approved changes. Native layout and live model behavior remain to be checked.

Acceptance: cover disabled and enabled research, source attribution, untrusted page content, cancellation, and shared budget exhaustion with offline fixtures. Verify default and custom limits, validation, persistence, per-pane independence, and clear limit-reached messages; separately qualify live model and provider combinations when authorized.

## Planned Code pane controls and approval layout

Keep the **Allow Light model delegation** checkbox visible in the normal Code pane. Place **Send previous task and answer with next run** on the same row. Put the Heavy, Light, and Decision model connection/alias selectors together in a collapsed-by-default panel that opens when clicked; preserve the current saved assignments and make it clear which Decision model is used for the optional System One safety recommendation.

Hide the command/operation approval preview, approve/reject buttons, and content below them while there is no pending approval. Show that review area only for the current pending approval, and clear or hide it immediately after approval, rejection, cancellation, or run completion. Keep run cancellation available while a run is active; it is a run control rather than an approval action. Do not make the ordinary activity feed, task composer, or always-visible delegation/context controls depend on approval state.

Acceptance: verify initial collapsed state, expand/collapse behavior, persistence of model assignments, optional Decision model selection, and the paired delegation/context row in offscreen Qt. Verify approval content appears only during a pending approval and disappears after every resolution path, including cancellation and interruption/reopen. Confirm the active-run cancel control remains reachable without a pending approval.


## Structured Git tools — local preview

Agentnik uses Dulwich for local Git operations without shell commands. The coding agent can inspect tracked status, working-file diffs against HEAD, staged diffs against HEAD, recent history, and local branches. Status checks at most 128 tracked paths and does not enumerate untracked files; use project listing for those.

Every mutation has its own approval:

- `git_stage`: stage explicitly named UTF-8 files or tracked deletions; review the index-to-working-file diff. Ignored untracked files and sensitive/excluded project paths are rejected.
- `git_unstage`: restore selected index entries to HEAD without changing working files or other staged entries.
- `git_commit`: commit explicitly named working files from a clean index.
- `git_commit_staged`: commit the reviewed index snapshot; the explicit paths must name every staged change, so unrelated staged entries cannot slip in. Later working-file edits remain untouched.
- `git_create_branch`: create a local branch at the reviewed HEAD without switching branches or overwriting an existing branch.

Path lists are JSON arrays encoded as strings, limited to 32 files. Diffs and UTF-8 file reads are bounded. Commit approvals show the full diff, message, configured identity, and parent commit. Approvals bind to the branch reference, HEAD, index fingerprint, and applicable file snapshots; changed state requires a fresh proposal. Index writes are locked, and reference publication uses compare-and-swap. A rare failure publishing the index after a successful commit reports the commit hash and stops the coding run for inspection rather than repeating the commit.

This preview requires an existing HEAD and a registered repository root with a local `.git` directory. Unborn repositories, linked worktrees, in-progress merges/rebases/cherry-picks, hooks, signing, content filters/LFS, and remote operations are outside the supported slice. Files are staged as raw UTF-8 bytes; no attributes-based transformations or external programs run. External filesystem writers are not an OS-level transaction; avoid concurrent repository writes during execution. Korean approval framing is included; model-facing tool descriptions and activity remain English.

Next: credential-safe remote inspection, then fetch and push with explicit destination/branch/commit previews and transport qualification. Branch switching, merge/rebase, signing, submodules, worktrees, and LFS need separate design and compatibility checks. Current evidence is offline temporary-repository tests, mocked coding-loop approvals, and offscreen Qt checks; live-model Git execution and native visual review remain unverified.


### Model-call timeout control (post-v0.4.0)

Coding requests now have a model-only timeout, configurable in Limits from 10–3,600 seconds with a 300-second default for both Heavy and Light. It bounds the whole request (first-token wait plus generation), while the original run deadline remains shared. New run budgets default to 900 seconds; legacy saved total budgets are preserved and acquire the new model timeout without rewriting user choices. Request-scoped runtimes retain the original run start and cancellation token, reject late results, and leave web/shell/Decision deadlines unchanged. Offline tests simulate a 70-second local-model delay and verify shorter model/total deadlines, role assignment, no replay, and saved-setting compatibility. No live inference was needed.


## Focused coding tools — first slice

Delivered: non-executing project overview, bounded line-range reads, approved exact-match patches, and approved test commands with structured reported results. Ranges cover up to 200 lines/16 KB within a 2 MB UTF-8 file. Patches require a unique previously seen span at the current snapshot, preserve surrounding content, and recheck the hash before atomic application. Range reads do not grant full-file rewrite/deletion permission. Overview is a bounded inventory and manifest summary, never an import or script execution.

Test commands reuse shell approval and execution policies, including optional System One advice. Parsers cover unittest, pytest, Jest, and Vitest; unknown/truncated output remains explicit and only the last recognized summary is reported. Initial native validation uses an owned temporary unittest fixture, while model behavior is mocked. Dedicated longer-running test jobs, richer diagnostics, symbol lookup, task tracking, Chat document reading/calculation, browser preview, and MCP remain later slices. See CODING_GUIDE.md for operational limits.


## Task plan/checklist slice

Implemented Heavy-owned `update_plan` and `get_plan` tools with bounded explanation and ordered steps (pending/in_progress/completed/blocked, at most one active). The Code pane presents completion counts and a collapsible read-only checklist. Optional session state preserves the last model-reported plan after interruption/cancellation and reopen without resuming execution. A new real coding task clears the prior plan; simulation preserves it. Updates are run-bound, validated, key-scrubbed, and never grant tool execution permission or silently mark completion. Light remains a bounded analysis delegate. Offline model/storage and offscreen Qt tests cover updates, invalid/secret data, old sessions, persistence, late events, and reset behavior. Live-model plan quality remains a separate qualification step.


## Scoped AGENTS.md guidance

Code now loads the selected project root's `AGENTS.md` before the first Heavy request. Ancestor `AGENTS.md` files within that root are loaded lazily when a tool targets a file/directory, including explicit Git path lists. `get_project_instructions(path)` lets Heavy discover rules before planning a change. Files outside the selected root, unrelated subtrees, other instruction filenames and user-global instructions are not automatically read. An instruction file applies to its parent directory and descendants; deeper rules take precedence only within their subtree. Explicit user instructions and Agentnik's fixed permission/security rules retain priority. This is model guidance, not a guarantee that every generated change follows a convention.

Activity reports loaded/removed instruction paths and scopes without copying raw guidance into activity logs. Heavy receives the current scoped guidance with its protocol-specific instructions; Light receives the same loaded scope map as bounded task context while remaining tool-free. Configured credentials are redacted. Automatic guidance reads do not authorize editing or deleting those files; the existing read-before-edit rules still apply.

If a tool batch discovers new/changed guidance, inspection tools may continue, but mutations, shell/test commands and delegation are deferred until a subsequent model turn can consider the updated instructions. Loaded scopes are refreshed between rounds. Changes detected before/during approval invalidate the proposal; the model must reconsider and submit it again. Ordinary diff/operation approval and state checks remain mandatory. Filesystem writers remain concurrent; these checks are not an OS-level transaction. Shell scope uses the supplied working directory; Agentnik does not parse commands to infer every affected path, so the model is instructed to inspect affected paths first.

Guidance must be regular, unlinked UTF-8 files: up to 8 KB per file, 24 KB total, 16 loaded files, 24 directory levels and 256 discovered scopes, plus the shared run context/time budgets. Missing files are allowed; unsafe, unreadable or oversized guidance fails closed rather than silently truncating rules. New runs reload current files; reopening a saved session does not execute or load guidance by itself. Offline tests cover scope discovery, refresh/removal, path/link/encoding/size rejection, first-request protocol injection, credential redaction, mutation deferral, stale approval invalidation, unchanged shell approval, Light context and run-budget enforcement. Live model instruction adherence remains unqualified.
