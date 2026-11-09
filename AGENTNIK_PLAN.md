# Agentnik implementation plan

Reviewed after the v0.2.0 release: 2026-11-08. This roadmap describes the current development tree and the remaining acceptance gates. Detailed historical evidence is in [VALIDATION.md](VALIDATION.md); installation and delivered behavior are in [README.md](README.md).

## Objective and preserved contracts

Agentnik is an independent Python/Qt desktop application for chat, Ollama System One decisions, bounded web research, and a repository-based Coding Agent workspace. Keep runtime dependencies small and support Windows, macOS, and Linux without claiming untested platform compatibility. Plan a localized interface without changing the language of user or model content.

- Preserve the robot geometry, red robot/`nik` branding, theme-sensitive `agent` wordmark, independent application identity/storage, and MIT license verbatim, including **Copyright (c) 2026 Nikolaus Spence**.
- Preserve independent tabs and histories, responsive background work, Markdown, inline thinking, images, statistics, accessibility, themes, saved prompts, and attachment cleanup.
- Preserve Responses, Chat Completions, Messages, and native Ollama chat. Bedrock support remains Mantle bearer-token endpoints. A protocol name does not establish model capability.
- Keep System One separate from chat/research: ordered questions and criteria, multiple images, and image-only state fallback remain supported.
- Keep secrets in the credential store or the existing explicit plaintext fallback. Exclude credentials from history, logs, tool records, screenshots, and exports by default. Preserve confirmation for destructive history actions.
- Ordinary tests remain offline. No background inference probes, paid requests, or live research requests during routine validation. Live checks require an authorized, explicit endpoint/model/route selection.

## 1. Current position and evidence

| Milestone | Current state | Remaining qualification |
| --- | --- | --- |
| A — Independent baseline | Established: standalone repository, identity/storage, red branding, baseline functionality and packaged assets | Preserve these contracts in every later slice |
| B — Managed research | Implemented preview: native Ollama tool loop, Ollama search, direct public page fetch, sources/activity, persistence, cancellation | Scoped live managed search/fetch passed through LiteLLM Responses; other combinations remain unverified |
| C — Hosted research and routing | Implemented preview: managed Responses, official OpenAI Responses hosted search, four policies, bounded fallback/accounting | Offline evidence; live research compatibility unverified |
| D — Hardening and release readiness | D0 complete; D1 harness delivered; isolated Windows v0.2.0 archive built and tagged | Native/clean-machine, additional live protocols, licensing and macOS/Linux gates remain open |
| E — Coding Agent | E1 registry/picker and an Agentnik-owned Heavy/Light coding and approved file-edit preview implemented after v0.2.0 | Live coding compatibility, role accounting, longer workflows, and a separate command execution boundary remain open |
| L — Localization | Planned; current interface text is English and largely embedded in Qt views | Extract user-facing strings, ship reviewed translations and validate locale behavior before claiming language support |
| F — MCP servers and Skills | Long-term planned | Optional extensions with explicit configuration, activation, permissions, and shared tool approvals |

The release baseline is **144 passing offline tests**, including protocol/transport mocks and offscreen Qt integration. The annotated **v0.2.0** tag points to **efffd07** and was pushed with the release commits. The unsigned Windows x64 archive was built from that clean revision in an isolated virtual environment, passed real Qt-window/temporary-database startup and graceful exit, and passed archive/checksum checks. It includes release notes, documentation/images, dependency notices and a build manifest. The archive is local under `dist/build-v0.2.0/`; pushing the Git tag did not upload the binary as a GitHub Release asset. v0.1.0 remains unchanged.

| Evidence | Confirmed scope | Still open |
| --- | --- | --- |
| Live chat | LiteLLM ChatGPT `chatgpt/gpt-6-luna` Responses; Ollama Cloud `ollama-cloud/gpt-oss:20b` Chat Completions; one Gemma gateway alias | Other aliases/accounts and direct-provider equivalence |
| Live tool continuation | ChatGPT Responses and Ollama Cloud Chat Completions using local fixtures | Successful live Messages and broader reasoning/multi-call variants |
| Real managed research | ChatGPT Responses through LiteLLM with separate Ollama search credentials and direct public page retrieval | Other model/protocol combinations and hosted search |
| Native distribution | v0.2.0 Windows build-host startup/database/clean exit | Clean-machine installation, complete interactive workflows, credential/TLS behavior, macOS/Linux |
| Source checks | 144 offline tests, compile and whitespace checks | These do not replace live/provider/platform evidence |

Anthropic aliases are advertised by the gateway but unavailable to the user's Mantle account. Do not keep probing them. Prioritize ChatGPT 6+ with DeepSeek or Kimi as additional targets when live checks are explicitly authorized. Do not scan all 115 advertised aliases or infer capability from listing success. Research remains a preview even though the Windows release is tagged.

### Next delivery decisions

1. **E1 and the first E2/E3 slice are in the development tree:** repository/folder registry, manager, searchable + Code picker, project-bound Code panes, and an explicitly started owned coding loop with approved file edits. Selecting a project starts no command or inference. This work is not included in the v0.2.0 archive.
2. **Improve Code pane controls, then extend Agentnik-owned coding tools:** keep Light delegation and previous-task context controls visible on one row; group Heavy, Light, and Decision model selectors in a collapsed panel; show approval details only while an approval is pending. Then add approved file deletion and directory creation, followed by bounded shell execution through a dedicated executor. Keep operation scope, command, arguments, working directory, environment, network access, process lifetime and output limits visible and enforceable; proposals never execute without explicit approval. Do not treat a System One recommendation as authorization.
3. **Keep D evidence work parallel in priority, not automatic in execution:** the manual checklist and opt-in harness can qualify individual routes/platforms as access becomes available. Windows preview improvements and E1 need not wait for unavailable Anthropic/macOS/Linux environments. Do not mark all of D complete or call v0.2.0 cross-platform validated.
4. **Keep MCP/Skills as F:** use the execution/approval contracts established in E2. Preserve the shared tool interface now, but avoid building an extension framework before a working coding integration demonstrates what it needs.
5. **Add localization as a cross-cutting milestone L:** establish one translation path for existing and new UI text, then ship English, Korean, Spanish, German, French, and Chinese catalogs. Keep language coverage explicit and add further locales through the same workflow.

Earlier D0 subsections below preserve checkpoint counts and rationale; this section is the current status, and VALIDATION.md is the historical evidence record.

## 2. Delivered architecture and support boundaries

| Area | Implementation | Boundary |
| --- | --- | --- |
| Endpoint/protocol baseline | `core.py`, `storage.py`, `ui.py` | Existing provider discovery and saved connection compatibility remain contracts |
| Typed tools and budgets | `tools.py` | Only registered `web_search(query)` and `web_fetch(url)`; no shell/files/code tools in research |
| Managed orchestration | `research.py`, `ollama_tools.py`, `responses_tools.py`, `compat_tools.py` | Complete argument assembly and batch validation before execution; protocol-specific continuation preserved |
| Search/retrieval | `web.py` | Ollama search service; direct pinned HTTP(S) fetch, not Ollama service-backed fetch |
| Routing/failure handling | `routing.py`, `failures.py` | Same model/connection throughout fallback; shared turn budgets |
| Hosted search | `hosted.py` | Explicitly configured official OpenAI Responses endpoint only; other compatible gateways/providers are not implicitly supported |
| Sources and presentation | `citations.py`, `research_ui.py`, `ui.py` | Validated references and provider annotations; links do not establish semantic claim support |
| Release tooling | `Agentnik.spec`, `tools/smoke_frozen.ps1` | Current evidence is Windows onedir startup only |

Managed research has mocked streaming/non-streaming coverage for native Ollama, Responses, Chat Completions, and Messages. Messages preserves signed/redacted thinking and grouped tool results; Responses preserves opaque continuation items. Do not transfer provider-specific continuation state across incompatible protocols/accounts or flatten it into ordinary text. New provider variants require their own fixtures and compatibility evidence.

Web access starts off. Settings provide **Provider first**, **Agentnik first**, **Provider only**, and **Agentnik only**, with connection defaults and independent chat overrides. Capability records distinguish unknown, configured, verified, and unsupported, scoped to endpoint/protocol/model. Configuration and documentation alone must not mark a model verified.

The ordered managed backend list currently contains independently credentialed **profiles for one Ollama search service**, not multiple search-provider implementations. Missing credentials and eligible explicit failures can advance profiles without replaying model inference. Additional search providers remain an extension point.

Direct page fetch validates public destinations, pins approved DNS addresses, retains the original TLS hostname, and revalidates redirects. It uses a separate transport without model credentials/browser cookies. Both provider-hosted navigation and search-service internal navigation are outside Agentnik's transport controls. Consequently the current strict navigation policy disables **both current search routes before inference**; it does not provide a strict managed-search alternative.

Default limits currently include four tool rounds, eight tool calls, five search results, 1 MB per web response, 3 MB retrieved per turn, 32 KB tool context, 256 KB retained research metadata, 4 KB arguments, 512 KB model response, six model requests, eight route attempts, 45-second request and 180-second turn deadlines, three redirects, and five-second maximum backoff. These are separate limits, not a guarantee that total retained session storage is 32 KB.

## 3. Lessons retained from implementation

- **Readiness needs application evidence.** The first frozen check was too impatient. Wait for a process-owned Qt window and temporary database within a deadline, then request a graceful close and verify exit status. Input-idle alone is insufficient; startup success is narrower than interactive success.
- **Protocol compatibility is narrower than capability.** Keep separate adapters, structured tool histories, opaque reasoning, identifiers, completion reasons, and missing-usage states. Do not infer hosted support from a Responses-shaped gateway.
- **Fallback can duplicate remote work.** Retry only eligible explicit outcomes within budgets. Stop on cancellation, access restriction, partial output/tool activity, or uncertain execution. Do not change model/provider or use alternate routes to bypass restrictions. Empty results are research evidence, not a transport failure.
- **Cancellation is cooperative.** Stop scheduling and reject late results immediately; remote computation/billing and outstanding local socket operations may continue until their own bounds. Test resource behavior across repeated cancellations, not just one late result.
- **External navigation needs honest disclosure.** Direct fetch has local controls; search services and hosted tools do not inherit those controls. Do not silently weaken strict policy or enable service-backed fetch.
- **Discovery should identify destinations without erasing user intent.** Environment-discovered `0.0.0.0` means connect to `127.0.0.1`. Merge matching environment/probe discoveries, retaining environment metadata and useful probe information. Preserve independently saved connections and avoid treating arbitrary DNS names or IPv6 destinations as equivalent.
- **Small asset defects affect runtime quality.** Empty SVG paths caused Qt warnings. Retain parser-warning coverage and inspect both themes. Editing/resending a historical prompt restores a draft and appends a new turn on Send; it does not rewrite history.
- **Build and release are distinct.** A wheel, source test suite, local frozen startup, and portable desktop release establish different evidence. The first release archive included documentation/license through manual assembly; automate that step before repeating releases.

### Additional lessons from v0.2.0

- Discovery is availability advertising, not account entitlement: explicit upstream rejections explain why some listed models cannot be tested. Capability evidence needs endpoint, protocol, alias and credential context; opaque scopes prevent one account's result from becoming another account's claim.
- Real service behavior can differ from headers. Ollama returned valid JSON labeled as HTML; the compatibility exception is confined to its fixed search POST and still requires valid JSON/results. Do not generalize this into permissive content sniffing.
- Partial evidence and executable continuation serve different purposes. Preserve interrupted work for inspection, but never replay incomplete tool exchanges. Size limits cover retained metadata separately from wire/model context, and reduction must be visible.
- Cancellation bounds client scheduling, not remote computation. Retain worker admission slots until workers actually exit; nested waits need nonblocking capacity handling to avoid deadlock. A global research limit does not also cap ordinary chat/discovery jobs.
- Release validation must exercise the entire assembly path. v0.2.0 exposed variable shadowing after image copying that broke manifest serialization despite successful freezing/startup. The new assembly regression covers source metadata, images and archive creation together.
- Keep startup checks independent of shell execution policy. The Python Windows helper checks the actual process-owned Qt window and database under a deadline, without changing PowerShell policy. Wait for readiness; input-idle alone is inadequate.
- Artifact provenance matters: build clean committed sources, check the final manifest matches the intended tag/version, verify ZIP/checksum, then tag/push. A local archive, pushed tag and uploaded GitHub Release are separate deliverables. Do not retrofit or overwrite older release artifacts.
- Favor small modules and explicit storage contracts as the UI grows. The new session, retention and research-settings modules isolate policy from presentation; continue that separation for repository management and code panes.

## 4. D0 — Completed local hardening

Complete these slices in order, with focused regression tests and corresponding validation notes. Findings below identify review targets; an untested edge case is not a claim of a demonstrated exploit.

### D0.1 Stream integrity and continuation

Audit `compat_tools.py` first. Enforce coherent message/block lifecycle and terminal states: missing/duplicate starts or stops, deltas after closure, conflicting call indexes/IDs/names, malformed argument types, interrupted streams, and unsupported stop reasons. Never execute tools from an incomplete or ambiguous response. Safely ignore documented non-semantic events without interpreting unknown tool-bearing content as permission to execute.

Preserve complete Responses output items, Messages thinking/signatures, and correlated results across follow-up turns. Define which partial exchanges may be persisted after failure without becoming executable continuation. Add multi-block/annotation-offset and truncated-stream fixtures where existing coverage is incomplete.

Acceptance: hostile event-order fixtures fail before tool execution; valid fragmented/multiple calls retain exact correlation and continuation; ordinary chat and all managed adapters still pass offline tests.

D0.1 progress: Chat Completions/Messages lifecycle hardening is implemented with offline rejection tests for missing/duplicate starts, premature/duplicate terminal events, content after closure/completion, ambiguous tool indexes, malformed identifiers/function fragments, and valid fragmented multi-call correlation. Messages retains signed/redacted thinking and grouped results; documented ping events remain harmless. The offline suite now has 94 passing tests. The Responses follow-up now validates terminal output and item identities, rejects argument fragments after closure, bounds citation spans to their original text blocks, and records explicit continuation eligibility. Failed/unfinished research remains auditable but is excluded from model history, including imported records with missing outer status. Save/reopen and malformed/truncated-response regressions pass in the 99-test offline suite. D0.1 is complete for this local hardening scope; next is D0.2 usage and durable state. This does not establish live Messages compatibility.

### D0.2 Usage and durable state

`core.usage_metrics` normalizes primary input/output counts but does not yet model cache-related provider detail. Define per-request usage snapshots and preserve bounded, sanitized provider details where useful. Messages `message_delta` usage is cumulative: update the request snapshot rather than summing deltas. Define cache read/write semantics before aggregating; missing values stay unknown, failed-attempt usage remains included, and no cost is invented. The [Messages streaming contract](https://platform.claude.com/docs/en/build-with-claude/streaming) documents event ordering and cumulative usage.

Validate saved connection/backend settings and versioned session shapes before use. Specify recovery for corrupt/truncated configuration, safe defaults for old sessions, and rejection of unsupported future versions without destroying the original file. Retain atomic configuration writes and shared attachment cleanup. Review capability invalidation when connection credentials/configuration change; verification evidence needs scope, date, and method.

Set an explicit total retained research-record limit covering sources, activity, partial exchanges, annotations, and metadata, separately from model-context limits. Test large failures and interrupted reopen. Reopening history must never restart tools or requests.

Acceptance: cumulative/cache/missing usage fixtures reconcile without double-counting; malformed settings produce recoverable errors; bounded persistence survives save/reopen and excludes credentials.

D0.2 progress: sanitized per-request usage snapshots now preserve cache and reasoning counters, update cumulative deltas without summing them, and aggregate once across model requests/route attempts. Messages total input includes its separately reported uncached/cache-read/cache-write tokens; detail counters already included in other protocol totals are not added again. Saved configuration loading now validates supported versions, connection/settings/backend shapes and duplicate backend IDs before opening the history database. Invalid files are preserved and produce an actionable repair/restart message; legacy valid configuration and credential references remain compatible. The offline suite has 106 passing tests. Versioned session validation/recovery and retained-record limits are now implemented: unreadable/future records remain visible without rewriting their stored payload, valid legacy records gain in-memory defaults, uncertain attachment references prevent cleanup, and new research snapshots have a separate 256 KB metadata budget with visible truncation and disabled incomplete continuation. The offline suite now has 115 passing tests, including offscreen interrupted reopen without requests. Nested research defaults/capabilities are now validated, and opaque credential-context scopes prevent accounts on one endpoint from sharing verification. Saved connection changes invalidate prior evidence; observed environment changes rotate in-memory scopes, and late completions cannot re-verify a changed request context. Legacy explicit enablement can carry forward, while unbound verification requires a fresh scoped check. The 122-test offline suite covers these behaviors. D0.2 local hardening is complete; next is D0.3 worker/transport/Qt lifecycle validation. No live compatibility evidence was added by this slice.

### D0.3 Worker, transport, and Qt lifecycle

Test rapid cancel/restart and simultaneous tabs with stalled DNS, web, and model workers. Add an aggregate concurrency/resource bound if existing per-turn deadlines allow abandoned workers to accumulate; reject late results without compromising responsiveness. Keep remote-stop limitations explicit.

The pinned transport now attempts up to eight distinct approved addresses for TCP connection establishment under one deadline and the original TLS hostname. No second DNS lookup is performed. TLS failures are terminal; HTTP submissions are not replayed for address failover. Retain redirect, content-type, compression, and byte restrictions. Richer extraction/charset support is optional follow-up, not a reason to relax transport controls.

Check that research completion preserves the user's thinking expansion choice just as ordinary chat does. Exercise cancellation, draft retention, edit/resend, source links, independent tabs, interrupted reopen, and light/dark presentation. Expand discovery regressions for saved-profile independence and environment/probe precedence.

Acceptance: bounded worker behavior under repeated cancellation, no late history/UI mutations, no outbound requests for strict-policy research, and offscreen Qt regression coverage. Record any native checks separately.

D0.3 local checks are complete: research Runtime waits share a 16-worker process-wide limit, including nested DNS/backend waits and cancelled operations that have not yet returned. Saturated work fails without spawning another worker; slots are released only on actual worker exit, including exception/start-failure paths. TCP failover is bounded to approved addresses and stops on TLS errors. Research completion retains thinking visibility across save/reopen. The 131-test offline suite covers repeated cancellation/restart, nested waits/timeouts, two-tab isolation and late results, both themes, saved-profile/discovery precedence, plus existing strict-policy, citation, prompt, and interrupted-history checks. No live/native platform compatibility claim is added. D0 local hardening is complete; next are D1 explicit compatibility tooling and D2 release automation/platform evidence.

**D0 exit:** all applicable offline tests and compile checks pass; focused Qt checks cover changed interaction; newly found issues are fixed or explicitly scoped with rationale. Update README/VALIDATION to describe delivered behavior. This is the next implementation target, not another new feature family.

## 5. D1 — Controlled compatibility evidence

Delivered: `tools/live_compat.py` is the separate explicit compatibility harness; `tools/live_smoke.py` remains the baseline endpoint/decision helper. The new CLI plans by default, requires `--execute` for live requests, and selects one URL/model/protocol/route/backend without automatic retries or fallback. Sanitized reports distinguish successful chat, managed search, direct fetch, continuation, and citation link generation. CLI use is documented in [DEVELOPMENT_VALIDATION.md](DEVELOPMENT_VALIDATION.md). Maintain these contracts:

1. Require the exact endpoint, protocol, model, route, and managed backend/profile. No automatic model selection, hidden cross-provider fallback, or background paid probes.
2. Make the planned bounded request/query visible and use a small, public, non-sensitive task. Honor cancellation and the same limits as the GUI.
3. Record timestamp, application revision, selected scope, stop outcome, tool correlation/continuation result, citations, and available usage. Redact secrets; do not retain private transcripts or key files as fixtures.
4. Distinguish model tool-calling from successful external search/fetch and from final-answer citation rendering. Test routing errors with mocks; do not manufacture repeated live failures to exercise fallback.
5. Update only the capability actually demonstrated. Report unavailable credentials/models as not tested. Do not claim every model on a compatible server works.

D1 tooling has offline coverage for planning without key reads/requests/writes, invalid scope rejection, report overwrite prevention, bounded chat parsing, cancellation, sanitized error/report output, and distinguishing an answer from real search evidence. No live checks were issued in this tooling slice; prior scoped live results remain in MILESTONE_D_LIVE_RESULTS.md.

Acceptance is per endpoint/model/protocol/route, not a global supported-provider label. No live requests are authorized merely by this plan review. Keep System One verification separate and require a substantive real request before claiming a model supports it.

## 6. D2 — Repeatable releases and platform gates

Delivered tooling: `tools/build_release.py` plans by default and requires `--build` to create a fresh labeled Windows x64 onedir archive. It rejects existing output, requires an isolated environment and pinned top-level build tools, copies root README/VALIDATION/LICENSE, collects available installed dependency/Python notices, records source/environment/dependency metadata, verifies packaged assets/Qt plugin and ZIP contents/integrity, and creates a SHA-256 sidecar. `--smoke` uses `tools/frozen_smoke.py` for actual Qt-window/database readiness and graceful exit without changing PowerShell execution policy. A clean-source build is the default; explicit `--allow-dirty` creates a labeled development artifact with that state recorded.

The isolated `.venv-build` environment (system site packages disabled) successfully produced the unsigned `dist/build-dev-d1-d2-r2/Agentnik-dev-d1-d2-r2-windows-x64.zip`, about 56 MB, with 79 installed-distribution notice files plus the Python license. Frozen startup and graceful exit passed on this Windows build host; ZIP/checksum validation passed. This is a development build of package version 0.1.0, not a replacement for the historical v0.1.0 tag/archive or a newly published release. The manifest identifies ab8b6bd plus uncommitted tooling/docs changes.

D2 remains partial: full bundled-library license review, clean-machine/native workflows, credential/TLS checks, macOS/Linux evidence, signing decisions and final release/version selection remain outstanding. Top-level versions are pinned in requirements-build.txt; transitive versions are recorded per manifest rather than fully locked.

Keep onedir as the initial Windows format. Distribute the whole directory. PyInstaller builds are platform-specific; Windows success does not establish Linux/macOS portability. See [PyInstaller operating mode and distribution requirements](https://pyinstaller.org/en/stable/operating-mode.html).

For each claimed platform/artifact, record:

- Clean-machine launch without development Python, packaged assets/plugins, readiness-based temporary-data startup and graceful exit.
- Native chat/decision/research forms, file dialogs, clipboard, links, cancellation, themes, attachment/history reopen, and keyring success/unavailable/explicit-fallback behavior.
- TLS/certificate behavior with an appropriate authorized check, distinguishing transport success from inference compatibility.
- Required platform libraries, signing/notarization status, installation/update behavior, and known limitations.

A Windows preview may ship with clearly documented model/platform limits after its applicable gates pass. Full D completion requires the declared cross-platform and compatibility matrix; unavailable macOS/Linux hosts remain explicit pending evidence. They need not prevent passive E1 development after D0. Signing, installers, and automatic updates are separate scope decisions, not implied by an unsigned ZIP.

The user selected v0.2.0 as the next Windows release. Package/project metadata and release notes are synchronized at 0.2.0; the archive manifest records clean source and frozen-startup evidence. Preserve outstanding platform/native/license gates. For later releases, explicitly choose and synchronize the version in package metadata, artifacts, release notes, and tag. Do not overwrite v0.1.0 or silently retag it. Committing, pushing, tagging, and publishing remain separate requested actions.

## 7. E — Repository-based Coding Agent

### E1: Passive repository registry and picker

After D0, this is the first feature slice, even if external D1/D2 evidence is awaiting suitable providers/platforms.

- Persist a **Repositories** list (Repos for short) of local working directories. Git is optional. Use stable identifiers, display names, and paths; provide Add folder, rename, remove-from-list, and relocate-missing-folder actions. Removing an entry never deletes files.
- Detect duplicates with platform-appropriate path/case/alias handling. Validate accessibility and show missing paths without losing the entry. Do not scan the computer or import other applications' registries. Exclude absolute local paths from portable exports by default.
- **＋ Code** opens a searchable repository picker with Add folder. Cancelling starts no session or process. Selecting a project opens an independent Code pane with the repository/working directory visible and a clear backend-not-connected state until E2 is implemented.
- Use temporary ordinary folders/Git repositories to test persistence, duplicates, unavailable paths, cancellation, independent tabs, and reopen without execution.

E1 implementation guidance: put path/registry operations behind a dedicated store-facing module and keep picker/Code presentation separate from the already large chat UI. Persist stable project IDs; bind Code history to the ID plus a path snapshot, and handle relocation explicitly. Decide the new session schema/version before writing Code records so older applications preserve them as unavailable instead of misreading them as chat. Use temporary project directories and offscreen Qt to verify add/rename/remove/relocate, aliases/missing paths, cancellation, persistence and independent panes. No subprocess/backend is part of E1 acceptance.

E1 evidence: registry data lives in its own SQLite table with stable IDs; ordinary folders and Git folders are accepted, aliases are resolved for duplicates, and missing folders can be renamed/relocated. Code sessions use schema version 4 with project ID/name/path snapshots and saved drafts. Older chat/decision schemas remain supported; older applications preserve Code records as unavailable. Offscreen Qt covers picker cancellation/search, independent light/dark panes, remove/relocate/reopen and no command/model execution.

### E2: Decide and enforce the execution contract

The user selected an Agentnik-owned coding loop using available connections/models, with no Codex dependency. The Codex protocol/transport direction is retired; its exploratory code is removed and retained only in Git history. Inspiration from coding CLIs concerns interaction patterns, not runtime architecture.

E2/E3 first runnable slice: select Heavy and optional Light connections/models in each Code pane, using a saved default, manually entered alias or explicit model-list picker. Heavy owns repository tools and approved edits; `delegate_light` performs bounded routine analysis using a different model/provider/protocol within the same workflow. Light has no tools. Delegation shares request/time/context budgets and is visible in activity. No automatic model/provider fallback occurs. Stored assignments contain labels/aliases, not keys; old opaque provider continuation is not replayed across roles.

Post-v0.3.0: completed and failed coding runs report Heavy and Light request counts and provider-reported input/output tokens separately. Missing counts are identified as unknown or partial; cancellation may leave no final summary. Routing controls and richer accounting remain future work.

Multi-file hardening: offline coverage exercises separate approvals within one tool batch, including an approved edit followed by a rejected one. Conflict checks do not update the model's recorded file read; a new explicit read is required before another proposal. Longer workflows and live coding qualification remain open.

File navigation: the coding agent can search a bounded UTF-8 file or project subtree for literal text and receive line numbers with explicit incompleteness. Search is not a full read and does not authorize edits. Live model qualification remains open.

Routing control: each Code pane can disable Light delegation while retaining its saved model assignment. A Heavy-only run does not advertise or accept the delegation tool. The choice persists per session and is fixed during a run.

Follow-up context: a Code pane retains the last completed task and answer (bounded to 2,048 characters each) and displays them for optional inclusion in the next run. This is explicit for each successful follow-up, uses plain messages across providers, and never reuses file observations or approvals. Failed, canceled, and simulated runs do not replace it.

Lifecycle hardening: closing the application now checks running coding jobs as well as chat jobs. Declining the close leaves the coding run and pending approval active; confirming cancels the run and saves its state. The Code status bar reports ready or running instead of claiming the backend is disconnected. Offline Qt tests cover both close choices.

Agentnik can list directories, read bounded UTF-8 project files and propose/create/replace files after full diff review and one-shot run-bound approval. Existing files require a prior read and unchanged content hash; conflicting edits stop rather than overwrite unseen user changes. Known credentials are redacted from tool results. Path traversal, links, reserved/sensitive paths and hard-linked files are rejected by filesystem tools. Approved single-file deletion, directory creation, shell commands, and opt-in web research are now available. Shell commands are not sandboxed and can access the network and paths outside the project, including Git commands. Cancellation invalidates pending review and stops scheduling; already applied approved changes are retained.

The owned coding backend has mocked coverage across native Ollama, Responses, Chat Completions and Messages, cross-protocol heavy/light delegation, real temporary-file changes only after approval, conflict/rejection/cancellation, known-key redaction, and offscreen role assignment/diff/reopen behavior. All 162 offline tests pass; this does not establish live coding compatibility for any alias. The simulation remains a separate no-execution UI exercise. E2/E3 remain partial: improve per-role accounting/routing controls, longer multi-file workflows and cross-run conversation semantics, then define a separately reviewed command executor before allowing subprocesses. Details are in [CODING_BACKEND_PLAN.md](CODING_BACKEND_PLAN.md).

### Optional System One command safety recommendation

Implemented preview: an opt-in Code-pane setting checks shell proposals with the selected Decision connection/model. The request contains the exact command, working directory, shell and inherited environment variable names, not environment values or file contents. The UI shows the decision endpoint and an advisory category and confidence, or UNKNOWN on invalid/failing/timeout results; manual approval remains required. The request has a 15-second bound and stale or cancelled results are ignored. The category descriptions are fixed guidance, not model-generated reasons. Offline fixtures cover the request and approval lifecycle; real-model compatibility remains unverified.

When the Coding Agent is ready to request approval for a proposed command, optionally run a configured System One decision model against that command and a deliberately limited context (for example, working-directory scope and the intended operation). Show the result alongside the exact command in the approval view as a concise recommendation with reason text and one or more clear badges. Suggested categories include **Safe**, **Risky**, **Privacy**, **Warning**, and **Danger**; define the structured decision schema and mapping so labels are consistent and explainable. Multiple badges may apply, and an uncertain or incomplete result must be shown as **Unknown** or **Review needed**, not silently treated as safe.

This check is opt-in and advisory. It never grants approval, suppresses the normal user approval step, or replaces enforced execution boundaries. The user sees what command and context will be sent, which configured decision endpoint/model will receive it, and the result before approving or rejecting. If the check is disabled, unavailable, times out, or returns invalid output, present that status plainly and continue only through the ordinary approval policy; do not represent missing review as a safety pass. Do not send secrets or unrelated conversation history. Preserve the recommendation and its scope in the session's bounded audit record without storing credentials.

Acceptance: tests cover badge mapping, mixed categories, explanation and uncertainty display, opt-in/offline/error states, context minimization, and the fact that every command still requires the established approval and enforcement path. Validate that the proposed command shown for approval is the same command evaluated; any modification requires a fresh review.

### E3: CLI-style coding sessions

Provide the requested composer, streaming transcript, command/output activity, run/cancel state, and changed-file/diff review. Sanitize terminal controls rather than interpreting them as HTML/application commands. Keep processes off the GUI thread, bound output/time, and handle launch failure and platform-specific child-process cleanup.

Bind each session to its project; never silently change a running working directory. Persist a distinct versioned coding-session type with bounded activity and run state. Reopen does not rerun commands. Validate fake backends and temporary projects first; native execution/platform checks are separate gates.

### E4: Approved filesystem and shell tools

Implemented first slice: separate approvals for single-file deletion, single-directory creation, and shell commands. Windows PowerShell uses a kill-on-close job object; POSIX shell execution uses a process group. Commands run with the user's operating-system permissions, including network and paths outside the project, and may run Git. Output and execution time are bounded. Windows command and child-cancellation smoke checks passed on the build host; live-model use, macOS/Linux native checks, stronger isolation, and System One review remain open.

Also plan opt-in web research within the coding loop and per-pane controls for rounds, requests, tool calls, time, and context. A compact Limits control may share the Light delegation row; see [CODING_BACKEND_PLAN.md](CODING_BACKEND_PLAN.md) for routing, shared-budget, disclosure, and acceptance requirements.

Extend the coding backend with file deletion, directory creation, and shell-command tools. Implement filesystem operations first, each with an exact path preview, workspace containment checks, link/traversal defenses, and a separate explicit approval. Deletion should default to a single file; recursive deletion requires a distinct, clearly scoped review and must never follow links outside the selected project. Directory creation must remain inside the selected project and report existing-path conflicts without modifying them.

Add shell execution only through a dedicated executor, never by invoking a shell inline from the UI or trusting model-generated commands. Show the exact command and arguments, working directory, inherited/selected environment, and network policy before each approval. Enforce per-run and per-command time, process-tree, output, and concurrency limits; cancellation must stop scheduling and terminate the owned process tree where the platform permits. Keep credentials out of command display, logs, model context, and persisted activity. Network access and access outside the selected project require separate explicit policy and approval. Explain that application checks are not an operating-system sandbox; investigate stronger platform isolation before allowing untrusted projects or commands.

The System One safety recommendation may assess the exact displayed command as advisory context, but cannot approve, rewrite, or authorize it. Any change to the command or its execution scope invalidates approval and requires a fresh review. Preserve the existing rule that model output is untrusted and cancellation does not undo already completed approved actions. There are no dedicated Git tools; approved shell commands can perform Git or remote-changing operations.

Acceptance gates: test delete and create operations against temporary projects, including rejection, conflicts, links, traversal, and cancellation. Exercise the executor with fake commands before native commands; verify exact approval binding, output/time bounds, secret redaction, process-tree cancellation, restart behavior, and that no command resumes after reopening. Validate platform-specific enforcement separately and do not claim a sandbox where only path checks exist.

## 8. L — Interface localization

Localize the desktop interface across chat, decisions, research, repository and coding panes, connections, settings, dialogs, approvals, activity, errors, accessibility labels, and packaged startup flows. The first supported set is **English (`en`)**, **Korean (`ko`)**, **Spanish (`es`)**, **German (`de`)**, **French (`fr`)**, and **Chinese in Simplified (`zh-Hans`) and Traditional (`zh-Hant`) scripts**. English is the source language and fallback. Further languages should use the same documented contribution and review process; do not advertise a locale until its catalog and UI checks pass.

### L1: Translation foundation

Started: the repository picker uses Qt's `tr()` for its application-owned labels and dialog framing. Qt's `pyside6-lupdate` extracted 16 source strings in the `RepositoryPicker` context, and an offscreen test checked a translator, English fallback, and unchanged project names. This is an extraction pilot; translated catalogs, remaining UI strings, translated backend errors, and release validation are not yet implemented.

Next foundation slice: a saved language choice loads packaged Qt catalogs at startup with English fallback when absent or invalid. Changes require a restart. Wheel and PyInstaller configurations include the catalog directory. An initial Korean preview covers the main window, repository picker, common chat and attachment controls, coding controls and file approval view, core decision form and result controls, connection controls, and parts of web research settings; it has not undergone full language review or packaged release validation. Much of chat and coding activity, settings, confirmations, and errors remains English. Prioritize Korean coverage and review before expanding other locales.

- Choose a maintainable Python/Qt catalog and extraction workflow after a short implementation spike. Centralize application-owned display strings, including dynamically assembled status, tool, validation, and safety-badge text. Keep stable internal IDs, protocol fields, model aliases, file paths, and persisted session data independent of translated labels.
- Add an explicit language setting with a **System default** option, locale-code persistence, and English fallback for missing translations. Define startup loading, runtime switch behavior (immediate update or clearly marked restart), and packaged catalog lookup on Windows, macOS, and Linux. A missing or corrupt catalog must leave the application usable in English without losing settings or history.
- Use named placeholders and locale-aware numbers, dates, times, and plural forms where displayed. Keep user prompts, model output, repository content, tool payloads, citations, and imported data in their original language. Translate application framing around those values without treating untrusted text as a format string.

### L2: Language coverage and review

Korean catalog maintenance: extract with `pyside6-lupdate agentnik/ui.py agentnik/code_ui.py agentnik/research_ui.py -ts agentnik/translations/agentnik_ko.ts`, review translations and unfinished entries, then compile with `pyside6-lrelease agentnik/translations/agentnik_ko.ts -qm agentnik/translations/agentnik_ko.qm`. Commit both source and compiled catalog. The current preview contains 304 translated strings, including coding model and approval activity and usage summaries, research completion and recovery messages, usage and timing labels, session and authentication dialogs, image attachment labels, accessibility labels and recovery guidance, saved-prompt actions, coding setup and simulation review, connection import choices, research routing, capability and limit disclosures, source attribution, search backend management, key confirmations, and selected chat/coding statuses; translation quality, broader coverage, native visual review, and packaged startup remain open.

Catalog packaging gate: the Windows archive builder rejects missing or altered compiled source catalogs. Offline tests verify rejection and ZIP contents. A dirty-source development archive passed build-host window/database startup and graceful exit; Qt also loaded the bundled Korean catalog and translated a picker string in a separate source-Python check. This does not establish Korean rendering inside the frozen application, clean-machine behavior, or other platforms.

- Extract and translate all visible application strings for the initial locale set, including dialogs and error paths. Give translators context for ambiguous short labels and keep technical terms consistent across chat, research, decisions, and coding. Review Chinese scripts separately rather than labeling one translation simply “Chinese.”
- Provide contributor instructions for updating source strings, catalogs, translator notes, and release assets. Track missing, stale, and unreviewed entries; avoid silently calling a partially translated interface complete. Add new locales by contribution and review without changing the stored data format.
- Review layout expansion, clipping, line wrapping, shortcuts, screen-reader names, input methods, font fallback, and mixed-language text in light/dark themes. Verify Korean and both Chinese scripts render correctly in the packaged application. Preserve the brand wordmark and robot artwork as brand assets.

### L3: Acceptance and release gates

Offline tests cover locale selection/persistence, fallback and corrupt catalogs, placeholders/plurals/formatting, translated safety and approval text, and stable saved data across language changes. Offscreen Qt checks exercise representative dialogs and all major panes in every advertised locale, with visual review for long labels and CJK text. Release checks verify catalogs are bundled and startup succeeds under a non-English system locale on each claimed platform. Document the languages actually reviewed for a release and any remaining untranslated strings. No live inference is needed for localization validation.

Sequence **L1 foundation → L2 reviewed catalogs → L3 release validation**. New UI work should use the translation path once L1 lands; localization can advance alongside coding and D evidence work without implying that untranslated current builds support these languages.

## 9. F — MCP servers and Skills (long term)

Add optional extensibility through **Model Context Protocol (MCP) servers** and reusable **Skills** after the core execution and approval contracts are established. Support chat and coding where appropriate, with capabilities explicitly enabled for each session/project. Do not automatically expose extensions to System One decisions or bypass research navigation policy.

### F1: MCP server configuration and connections

- Provide a server manager to add, edit, enable/disable, remove, and test configured servers. Plan for local process-based and remote HTTP connections; select supported transports, protocol versions, and authentication flows against the official MCP specification during implementation.
- Show server identity, connection status, discovered capabilities, and the permissions/data exposure involved. Store credentials through the existing credential mechanism and exclude them from exports. Review local launch commands and remote destinations before connecting; discovery of a server is not authorization to launch or use it.
- Start with a small explicit capability set, then add tools, resources, and prompts in reviewed slices. Namespace identifiers by server, validate schemas and payloads, handle capability changes, and preserve source provenance. Server descriptions and returned content are untrusted input.
- Run connections off the GUI thread with bounded requests/output, cancellation, reconnect behavior, and local child-process cleanup. Reopening a session does not replay tool calls or silently launch a server.

### F2: Shared tool permissions and activity

Route MCP tool calls through the same reviewed execution/approval policy as built-in tools, with per-server/tool and per-session/project controls. Clearly identify the server, operation, arguments, and affected data in approval and activity views. Read-only hints or server-supplied safety descriptions do not grant permissions. A skill cannot grant them either.

Where a tool proposes command execution, the optional System One command safety recommendation can appear in its approval view under the same advisory rules as E2. It must evaluate the actual command and scope; do not apply command-line badges to opaque remote tools as though their effects were known. Preserve bounded, credential-free activity and results in session history.

### F3: Reusable Skills

- Define a documented, versioned skill format based on a `SKILL.md` entry point plus optional supporting resources/scripts. Evaluate compatibility with established skill formats before choosing Agentnik-specific metadata; do not promise universal format compatibility.
- Support user-level and repository-level skill libraries with explicit discovery roots, stable identity, source/version information, duplicate resolution, and enable/disable controls. Do not scan arbitrary directories or execute installation hooks while discovering skills.
- Let users select a skill explicitly first; later consider suggested activation with visible reasons and user controls. Show active skills in the session and load only the instructions/resources needed within context limits.
- Review a skill's source and requested capabilities before enabling it. Treat instructions, references, and scripts as untrusted; prevent path traversal and access outside approved roots. Scripts use the established command execution/approval path. Installing or selecting a skill never grants file, network, tool, or credential access by itself.
- Keep secrets out of skill files and exports. Define update/removal behavior and record which skill revision informed a session without rerunning anything on reopen. Skill-generated MCP requests remain subject to F2.

### Delivery and acceptance

Sequence **F1 server manager and explicit connections → F2 limited tool integration → F3 explicit skill activation**, then expand resources/prompts and suggested activation when evidence supports them. Keep dependencies optional where practical and validate Windows/macOS/Linux separately.

Use fake servers and temporary skill libraries for ordinary tests. Cover disabled/missing servers, malformed/changing schemas, tool-name collisions, credential isolation, approval denial, cancellation/late responses, reconnect and process cleanup, hostile resource paths, bounded context/output, skill updates, and reopen without execution. Live server compatibility is recorded separately by server/version/transport/capability. MCP and Skills remain planned features until these slices are implemented and validated.

## 10. Deferred scope and review discipline

Defer additional hosted/search providers until an adapter and evidence justify them. Full browser automation, JavaScript interaction, login/cookie sessions, forms/purchases, arbitrary execution in research, autonomous background tasks, model-provider failover, and research inside System One remain outside this roadmap's delivered scope.

For each slice: inspect the relevant implementation, preserve user data, add tests for meaningful behavioral risks, run relevant offline/Qt checks, and update evidence without erasing historical limitations. Do not substitute test counts, documentation, or a startup screenshot for compatibility evidence.

Immediate order (Agentnik-owned coding/file-edit preview implemented): **multi-model coding qualification, per-role accounting and multi-file workflow hardening**, with L1 translation foundation as a parallel UI preparation slice, alongside remaining D1 provider and D2 platform/release evidence as authorized and available. Authorized live/provider and available platform checks proceed as their prerequisites become available; command execution remains gated by E2.
