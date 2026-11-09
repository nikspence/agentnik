# Agentnik-owned coding backend

Agentnik owns the coding loop and uses the same configured connections/models as chat. Codex is inspiration for interaction design only: no Codex executable, account, app-server, or CLI runtime is required. The abandoned external-protocol spike is preserved in Git history, not shipped as the active backend.

## Heavy and light models in one workflow

Each Code pane has independent Heavy and Light connection/model assignments. Select any alias supported by the connection, including LiteLLM coding models, or use Choose model to retrieve its model list. Listing does not establish tool capability. Start with a tool-capable heavy model; the light role is optional and is not automatically chosen.

The heavy model owns the task, repository tools and edit proposals. Its `delegate_light` tool sends a bounded task/context to the user-selected light model for routine analysis. The light model has no repository tools or execution rights; its result returns to the heavy model through the heavy protocol's correlated tool result. Heavy and light can use different providers/protocols. Opaque provider history remains in its original protocol; Agentnik exchanges plain bounded task/results between roles rather than replaying one provider's reasoning items to another.

Delegation is visible in activity and shares the run's request/time/context budgets. Each new model request is attributable to a configured role. No model/provider fallback, automatic model selection or background capability probes occur. Assigning a light model authorizes bounded delegated context to that endpoint. File content can therefore reach either selected service; only connection labels/model aliases are persisted, not credentials. Saved assignments do not start anything on reopen.

## First runnable coding slice

The model can list project directories, read bounded UTF-8 files and propose complete file content. Existing files must be read before editing. Each edit displays the full diff and waits for explicit one-shot approval bound to the run, path, original content hash and proposed content. Rejected proposals cannot silently become applied edits. Conflicting user edits cause the write to stop; already approved/applied changes are retained on cancellation or later failure. Optional managed web research is available; reset, clean, commit, push, deletion, directory creation and shell tools are unavailable.

Project operations reject traversal, absolute/drive paths, symlinks/junctions, hard-linked files, common credential locations and reserved paths. Reads and writes are limited to 32 KB per file. Changes use temporary files and atomic replacement/new-file publication, preserve existing permission bits, and recheck the original hash before committing. A process-local edit lock serializes Agentnik's own edits. These checks are not an OS sandbox or a guarantee against a hostile external process racing filesystem changes. User approval and a selected working directory do not grant broader execution rights.

The workflow shares limits of nine model requests (including light delegations), sixteen calls, 100 KB retained request context and five minutes per run, using the existing bounded protocol parsers. UI cancellation stops scheduling and invalidates approval; remote inference may still complete or be billed. Activity retains 32 bounded records; full pending diffs are for review and are not persisted as executable actions. Reopening a pending run marks interruption and never resumes requests or edits. An explicit per-run option sends the displayed, bounded last completed task and answer as plain messages; it does not replay provider-specific reasoning or tool exchanges. Each run creates fresh file observations and approvals.

## Approval and next steps

The earlier no-execution simulation remains available for trying the UI. Its approvals cannot authorize real edits. Real edits show **Not checked** for safety recommendations; optional System One review is not yet connected and cannot grant approval. Heavy/light model outputs are untrusted proposals, not execution authority.

Completed and failed runs report Heavy and Light request counts and provider-reported input/output tokens separately; missing counts are marked unknown or known usage only. Cancelled runs may lack a final summary. Next: validate more tool-capable models through explicitly authorized checks, improve task routing controls, and add tests for longer multi-file work.

## Planned filesystem and shell tools

Add approved single-file deletion and workspace-contained directory creation, with exact path previews and separate approvals. Recursive deletion, if supported, needs its own conspicuous scope review and must not follow links outside the selected project.

Shell tools require a dedicated executor that displays and binds approval to the exact command, arguments, working directory, environment, and network policy. Bound execution time, process trees, output, and concurrency; redact credentials from UI, model context, logs, and stored activity. Test a fake executor before native execution and validate platform-specific process cleanup. Application path checks do not constitute an OS sandbox, so investigate stronger isolation before accepting untrusted projects or arbitrary commands. System One may provide an advisory about the exact command but never supplies authorization. Any scope or command change requires fresh approval. Git commit/push and other remote-changing actions are excluded unless separately planned. MCP and Skills must use the same execution and approval boundaries.

## Planned web research and adjustable run limits

Routing direction requested: reserve Ollama-key-backed search for direct Ollama Cloud connections, identified by their actual configured endpoint rather than a model alias. LiteLLM and other gateways must not be treated as direct Ollama merely because a model name contains Ollama. For other connections, use a supported, explicitly configured provider-hosted search capability when available; otherwise use Agentnik-managed search and public-page fetch. Coding now uses Google HTML search for non-direct connections and credential-free public page reads with bounded same-host link discovery. Direct Ollama Cloud uses a configured Ollama profile or Google when no profile is available. Strict navigation disables search but permits direct public page reads. Provider-hosted search is not yet integrated into the Code loop. Google HTML may change or block automated access, and Google restricts automated searches without permission; do not bypass challenges. Preserve explicit opt-in, capability evidence, disclosure, and budgets.

An opt-in per-pane checkbox gives Heavy public page fetch and, where navigation policy permits, Google or direct Ollama search. The Code pane can manage shared Ollama profiles directly. Activity shows searches, backend progress, and source IDs and URLs; results are marked untrusted and the model is asked to identify sources in its final answer. A Sources dialog can open or copy up to 32 public links from the latest coding run, persisted with the pane. IDs are scoped to one run and do not establish that a source supports a claim. Calls share coding budgets and Light retains bounded delegation without tools. Offline fixtures cover search, fetch, source labels, the source dialog, and failure handling; live coding research, live Google HTML behavior, and native source-dialog review remain to be validated. Hosted search and chat research routing policies are not yet available to the coding loop.

The **Limits…** dialog provides bounded per-pane settings for tool rounds, model requests, tool calls, elapsed seconds, and context bytes, with defaults and reset. The run snapshots these values and shares budgets across Heavy, Light, and web work. Limit failures identify the exhausted budget and retain approved changes. Native layout and live model behavior remain to be checked.

Acceptance: cover disabled and enabled research, source attribution, untrusted page content, cancellation, and shared budget exhaustion with offline fixtures. Verify default and custom limits, validation, persistence, per-pane independence, and clear limit-reached messages; separately qualify live model and provider combinations when authorized.

## Planned Code pane controls and approval layout

Keep the **Allow Light model delegation** checkbox visible in the normal Code pane. Place **Send previous task and answer with next run** on the same row. Put the Heavy, Light, and Decision model connection/alias selectors together in a collapsed-by-default panel that opens when clicked; preserve the current saved assignments and make it clear which Decision model is used for the optional System One safety recommendation.

Hide the command/operation approval preview, approve/reject buttons, and content below them while there is no pending approval. Show that review area only for the current pending approval, and clear or hide it immediately after approval, rejection, cancellation, or run completion. Keep run cancellation available while a run is active; it is a run control rather than an approval action. Do not make the ordinary activity feed, task composer, or always-visible delegation/context controls depend on approval state.

Acceptance: verify initial collapsed state, expand/collapse behavior, persistence of model assignments, optional Decision model selection, and the paired delegation/context row in offscreen Qt. Verify approval content appears only during a pending approval and disappears after every resolution path, including cancellation and interruption/reopen. Confirm the active-run cancel control remains reachable without a pending approval.
