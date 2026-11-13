# Baseline validation

## Independent review output budget (2026-11-13)

Offline direct-review and scheduler tests check UTF-8 byte accounting against the shared context limit, including discarded over-budget output and the Heavy continuation path's separate serialized-result charge. Focused direct-review, independent-review, subagent and forced-process-stop recovery tests passed. No live model or endpoint was used.

## Independent review forced-stop recovery (2026-11-12)

On this Windows host, an offline offscreen test started separate Agentnik processes for direct and Heavy-requested independent-review batches with progress saving enabled. Each used a mocked reviewer that blocked after the pass manifest was committed; the test forcibly terminated its own child process, reopened the temporary SQLite session, and verified that all approved passes remained marked interrupted. Opening the saved session made no model request and did not resume the work. The test covers one forced process stop during a submitted mocked request for each route; it does not simulate power loss, storage failure, all crash points, remote cancellation, or other operating systems. No live endpoint was contacted.

## Chat MCP preview (2026-11-11)

Offline tests cover selection and save/reopen without server startup, Responses/native Ollama/Chat Completions/Messages continuations with mocked models, MCP tool calls without approval, stale configuration, strict navigation, batched argument validation, credential protection and user-only content. A separate offscreen check used a mocked Responses model and the user's real local Parquet MCP server for two consecutive one-row query turns, including reconnection when the model skipped discovery. Both turns completed under the earlier approval policy; the current policy no longer prompts for any MCP tool. No live inference or external service was used. Chat use with actual model/provider combinations and native interactive platforms remains unqualified.

An additional local Parquet check used a mocked Responses model to send an invalid query argument, receive validation feedback, correct the argument, and complete a one-row query. Offline tests cover rejecting an entire mixed valid/invalid batch before any call, both with an existing connection and after reconnection. No live model was used.

An offscreen Chat check with the local Parquet server and a mocked Responses model verified that the activity panel names the server and query tool and reports completion without including SQL or returned rows. Offline fixtures cover tool-reported errors and uncertain call outcomes without retrying the call.

Local stdio framing tests cover multiple valid messages delivered in one read whose combined size exceeds the per-message limit, plus oversized complete and incomplete messages. The saved Parquet profile also passed a local discovery and one-row query after this change; no live model was used.

## Local MCP working directories (2026-11-11)

Offline Windows fixtures cover saved absolute working directories, invalid and legacy configuration, Code selection fingerprints, startup approval, real subprocess working directory, local session cleanup, and a scrollable manager in a small offscreen window. The full offline suite ran 493 tests successfully with one skip; the directory browser and small-window checks passed separately after the suite. Compilation and whitespace checks passed. The user-provided Parquet server was initialized and its three tools listed again with the field left blank; no tools or data queries were run. Native macOS/Linux process behavior was not checked.

## Local Parquet MCP connection (2026-11-11)

Using `C:\Python315\python.exe` and `D:/dev/parquet_mcp/server.py`, Agentnik's local stdio session initialized the user-provided server and discovered `list_tables`, `describe_table`, and `query`. No tool calls or data queries were made. Offline Qt checks cover the saved-profile requirement, unsaved edits and Windows JSON path guidance. All 48 MCP tests and compilation passed on this Windows host.

## MCP content audiences (2026-11-11)

Offline tests cover unspecified, user-only, assistant-only, mixed and empty audience lists; invalid audience metadata; bounded user-directed activity; and exclusion of user-only blocks from model context on both fresh and cached results. Manual MCP results remain complete. The full offline suite ran 487 tests successfully with one skip; the additional invalid-audience cache regression passed separately. Compilation and whitespace checks passed. Audience annotations are server-provided per-block hints, and other fields may repeat the same data. No live server or model was used.

## MCP structured tool output (2026-11-11)

Offline fixtures cover bounded output-schema discovery, schema changes blocking local and remote calls before execution, structured-result validation, rejection of missing/invalid/unsupported output, tool-reported errors, exclusion of failed output from Code model context and the search cache, and offscreen approval/manager display. Validation uses the existing bounded schema subset and runs away from the Qt thread. The full offline suite ran 485 tests successfully with one skip; the updated approval and remote-schema-change checks also passed separately. Compilation and whitespace checks passed. No live MCP server or model was used for this slice.

## MCP HTTPS failure cleanup (2026-11-11)

Offline HTTP fixtures verify that manual remote discovery and tool-call failures attempt to terminate an established session and retain the original error, call uncertainty, and termination status. Tests cover changed identity/tool metadata, malformed and oversized replies, a timed-out submitted call without replay, rejected termination, and bearer/session headers. The full offline suite ran 480 tests successfully with one skip; the added timeout fixture passed separately. Compilation and whitespace checks passed. No external server or model was contacted, and a server may reject session termination or complete an already submitted call.

## MCP timeout configuration (2026-11-11)

Offline checks cover legacy and configured server profiles, timeout bounds and configuration fingerprints, the settings dialog, propagation to local and remote coding sessions and manual remote calls, and a local subprocess that receives a tool call but does not reply before the timeout. The timed-out call is reported as uncertain and is not replayed. The full offline suite ran 478 tests successfully with one skip on Windows; the added manual-call assertion was also rerun separately. Compilation and whitespace checks passed. No external MCP server or model was contacted for this change; real slow-server and other-platform behavior remain unverified.

## Research continuation and limits follow-up (2026-11-11)

The user reported that research works after the final-synthesis and configurable-limit changes, including managed Responses through their LiteLLM gateway. This is user-reported live evidence; the individual requests were not recorded or repeated in this validation run. An offline regression checks that a later tool batch exceeding the remaining call budget is skipped as a whole and that the model receives correlated tool results and can synthesize earlier evidence. Responses and Messages fixtures cover continuation; invalid calls still stop without execution. The Code workspace retains its separate 45-second web/shell deadline despite the longer default chat research request timeout.

The complete offline suite passed 474 tests with one skip on Windows, including offscreen Qt checks. Compilation and whitespace checks passed. No live inference, search requests, or native interactive platform validation were performed for this follow-up. Hosted-search and other endpoint/model/platform combinations retain their existing qualification limits.

Validated on Windows on 2026-11-08 using Python 3.15 and PySide6 6.12.0.

## Passed

- All 23 standard-library and offscreen Qt tests passed. Coverage includes protocol serialization/streaming, decisions, independent tabs, cancellation, prompts, attachments, themes, storage isolation, and Agentnik-scoped credential-store calls.
- Compile checks passed for `agentnik`, `tests`, and `tools`. Source launcher help passed.
- The light/dark wordmark and temporary-data welcome screenshots were visually inspected during baseline creation. The robot retains its geometry with red shading matching the wordmark; `agent` follows the theme and `nik` is warm red.
- `pip wheel . --no-deps --wheel-dir dist` built `agentnik-0.1.0-py3-none-any.whl`. The wheel installed into the local `.venv` without installing runtime dependencies again; existing PySide6/keyring dependencies are shared through system site packages.
- The installed package was imported with source-directory imports excluded. All seven packaged branding assets were present; SVG and PNG decoding passed.
- The installed application's entry point ran the offscreen event loop and exited successfully with temporary storage and mocked environment/endpoint discovery. Application/organization identity and the temporary history database were verified. The harness explicitly closed its database before deleting the temporary directory.
- Intended source files were audited for obsolete branding, private development endpoints, machine-specific paths, and common credential patterns. No matches were found. This is a targeted scan, not a guarantee against every possible secret format.
- The project uses the Apache License 2.0. Copyright 2026 Nikolaus Spence. Project metadata identifies Nikolaus Spence as sole author.
- This repository was initialized independently, with no inherited history or remote at baseline creation. The user subsequently configured origin and published the baseline.

## Limits

No live inference or provider compatibility checks were run. Native interactive Windows use, macOS/Linux runtime behavior, frozen PyInstaller distributions, installers, and signing remain unverified. A Python wheel is not a frozen desktop distribution.

The default sandbox process setup still failed after the trust restart. Checks completed through the approved escalation path; Git commands used a repository-scoped ownership trust override without changing global Git settings.

## Milestone B managed research preview

- At the milestone B checkpoint, 54 offline tests passed: the 23 baseline tests plus 29 research protocol, transport, credential, persistence, cancellation, and Qt checks, plus two edit/resend checks.
- Tests cover streamed/non-streamed native calls, multiple calls, argument assembly, thinking/identifiers in continuation, cross-turn citation provenance, aggregate/missing usage, malformed/unregistered calls, call/context/wire limits, time limits, cancellation and rejected late results, partial failed attempts, and narrow unsupported-tool classification.
- Transport mocks cover hostile IPv4/IPv6 URLs, mixed public/private DNS, pinned socket addresses with original TLS hostnames, redirect revalidation, credential isolation, content types, compression rejection, response/total byte caps, and readable text extraction. No real hostile destinations are contacted.
- The preview wheel builds and installs; source-directory imports were excluded when checking installed research modules, a mocked research turn, and an offscreen temporary-data Qt entry-point launch.
- Historical chat prompts expose an accessible pencil action. Offline tests verify text/image restoration without submission, draft replacement confirmation, persistence, running-request protection, and a mocked resend that appends a new turn while preserving prior history.
- Qt checks cover per-chat defaults, sources/links, credential-free exports, persisted research, interrupted reopen without execution, draft retention on cancellation, and rejection of late completions. Separate search credential-store calls and failed key replacement are tested with a fake keyring.
- Branding SVG loads are checked for Qt parser warnings. Eighteen empty paths were removed from each robot asset; regenerated PNG and ICO files remain byte-identical.
- Light/dark research screenshots were generated using temporary storage and explicitly simulated model/source responses, then visually inspected. They establish layout, not provider compatibility.

No live inference, search, or page-fetch requests were executed. Native interactive Windows checks, macOS/Linux, and frozen distributions remain unverified. The B checkpoint did not include hosted search/routing; see the milestone C validation below for the delivered extension.


## Milestone C hosted research and routing

- All 84 offline tests pass: the 54 prior tests plus 28 routing, Responses, hosted-search, backend, accounting, and Qt tests, plus environment wildcard-host normalization and environment/probe deduplication coverage. Compile checks cover application, tests, and tools.
- Hosted tests cover SSE and non-streamed JSON, web-search progress, annotation offsets/URLs, provider metadata without invented page timestamps/excerpts, unknown usage, partial failure/disconnection, wire limits, endpoint gating, and preserving stateless output/opaque reasoning items.
- Managed Responses tests cover fragmented/multiple calls, strict flat tool schemas, function-call identifiers/results, opaque reasoning continuation, and rejecting malformed, duplicate, or unregistered calls before execution.
- Routing tests cover all four orders and single-route behavior, capability scope/unknown skips, explicit unsupported/auth rejection, one bounded 429/503 retry, long Retry-After stopping, shared request budgets, unchanged connection/model during actual mocked hosted-to-managed fallback, usage from failed attempts, cancellation during waits, and no fallback after partial/uncertain/access-restricted outcomes.
- Ordered backend tests cover missing keys, independent credentials, eligible rejection/fallback without model replay, duplicate prevention, empty results, and blocked access. Qt tests cover profile ordering and key replacement without corrupting profile identifiers.
- Qt checks cover saved connection defaults, independent per-chat overrides, legacy managed-only settings, strict-policy blocking before requests, hosted operation without a managed key, separate capability updates, and clickable inline annotations both while streaming and after completion.
- The milestone C wheel builds and installs. With source-directory imports excluded, the installed package passed new-module imports, a mocked hosted route, an offscreen temporary-data Qt launch, and zero SVG parser warnings.
- Managed, hosted, fallback, and settings screenshots use temporary data and simulated responses only. Light/dark layouts and red inline links were visually inspected.

Official references checked during implementation: [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search), [Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events), [function calling](https://developers.openai.com/api/docs/guides/function-calling), and [reasoning continuation](https://developers.openai.com/api/docs/guides/reasoning). Documentation and mocks establish contract coverage, not live endpoint/model compatibility.

No live model inference or research-service checks were run. Hosted navigation cannot be controlled inside the provider; strict navigation policy disables it and the current service-based managed search. Chat Completions/Messages research adapters, native interactive/platform checks, and frozen distributions remain unverified or pending.


## v0.1.0 Windows PyInstaller build

Built with PyInstaller 6.22.3, hooks 2026.9, Python 3.15.0 and PySide6 6.12.0 on Windows 11 x64 using `Agentnik.spec`. The onedir distribution includes Qt plugins, all seven branding images, and the Apache License 2.0. A ZIP integrity/contents check passed; a SHA-256 sidecar accompanies the archive in `dist/`.

The actual windowed executable initialized a Qt window titled Agentnik and created a history database under a dedicated test data directory. The startup check allowed up to 20 seconds and located the hidden window by its process-owned native handle, then requested a graceful close and verified exit code 0. The initial check ran too early; process input-idle alone was not sufficient evidence of application readiness.

This verifies Windows startup and clean exit, not live provider/TLS requests, credential-store writes, every dialog/clipboard workflow, or macOS/Linux distributions. The build is unsigned. Source tests previously passed (84 offline tests); no live inference was run for this build.


## Milestone D protocol matrix

All 90 offline tests pass, including six additional protocol matrix tests. Chat Completions and Messages now execute managed research through their own wire formats. Coverage includes streaming/non-streaming calls, multiple results and correlation IDs, fragmented JSON, signed/redacted thinking preservation, grouped Messages tool results, structured history follow-up, usage after completion, missing usage, duplicate/unknown calls, incomplete stop reasons and disconnection before execution. No new runtime dependencies were added.

References checked: [Chat Completions streaming](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events) and [Messages streaming](https://platform.claude.com/docs/en/build-with-claude/streaming). Protocol mocks do not establish live model compatibility. Milestone D remains incomplete pending live provider checks, full native workflows and macOS/Linux validation. Existing v0.1.0 release artifacts and tag are preserved; development builds use a separate output directory.

The isolated milestone D Windows development build passed actual frozen Qt window initialization, temporary SQLite creation, and graceful exit code 0. `tools/smoke_frozen.ps1` waits up to 30 seconds for real readiness instead of treating process input-idle as app readiness. This remains a startup smoke check, not full native workflow or live-provider validation.


## Initial authorized LiteLLM live checks

User-authorized live checks against the supplied LiteLLM gateway returned 115 model aliases. Streamed chat passed for `ollama-cloud/gpt-oss:20b` (Chat Completions), `chatgpt/gpt-6-luna` (Responses), and `us-west-2/google.gemma-3-4b-it` (Chat Completions). The Ollama and ChatGPT aliases also passed real model tool-call/result continuation with a synthetic local source through Agentnik's managed loop. This does not establish live web search or page-fetch compatibility. Two Claude aliases were rejected by Mantle as unavailable to the account; one older subscription alias was rejected as unsupported for the ChatGPT account route. No native GUI checks were part of this run. See [the scoped results](MILESTONE_D_LIVE_RESULTS.md) for the matrix and remaining gaps. Historical offline-only checkpoints above remain accurate for their original scope.


## Search content-type fix and successful live recheck

The authorized header inspection found HTTP 200 with `Content-Type: text/html; charset=utf-8`, no content encoding, and a valid JSON object containing `results`. Ollama search was labeling JSON as HTML. The transport now accepts that label only for a POST to the exact `https://ollama.com/api/web_search` URL with redirects disabled; JSON parsing and search-result schema checks still apply. Other endpoints and content-type checks remain restricted.

A real recheck using `chatgpt/gpt-6-luna` through LiteLLM Responses completed one Ollama search and one direct public-page fetch. It returned five search sources and one fetched source, then answered with citations to S1 and S6. Three model requests completed in about 18.6 seconds, with usage reported. This establishes end-to-end managed search/fetch compatibility for this exact route, not hosted search or native GUI validation. Detail is under ignored `test-output/litellm-real-web-fixed.json`.

All 91 offline tests and compile checks passed. Regression coverage accepts mislabeled valid results, rejects actual HTML and wrong JSON structure, and rejects the exception on other endpoints or with redirects enabled. Account feedback confirms Anthropic is unavailable despite its listed aliases; further live targets prioritize ChatGPT 6+, DeepSeek, or Kimi.


## D0.1 Chat Completions and Messages stream integrity

All 94 offline tests pass, including three additional protocol test groups with hostile event-order/fragment subcases and valid fragmented multi-call continuation. Messages now requires a coherent start, sequential closed content blocks, terminal message deltas, and a final stop. Duplicate/premature/late lifecycle events are rejected before tool dispatch. Non-streamed Messages and signed/redacted thinking remain covered. Chat Completions requires streamed tool indexes, rejects duplicate indexes within an event, validates fragment types, and rejects choice data after a finish reason while still accepting the usage-only tail. Valid fragmented names/arguments and multiple correlated results remain supported. No new runtime dependencies were introduced; compile checks passed.

This slice used mocks/offscreen Qt only and made no live inference requests. No GUI changes were made. Responses annotation/continuation edge cases and partial-record persistence review remain open within D0.1.


## D0.1 Responses and partial-history completion

All 99 offline tests pass, including new regression groups for incomplete/missing terminal Responses output, identity conflicts, argument fragments after closure, truncated streams without tool dispatch, empty final output replacing stale partial items, opaque reasoning retention, and citations bounded to their originating content block. Valid citations in subsequent blocks receive the correct concatenated offsets; malformed spans are counted as unverified instead of spilling into another block.

Managed and hosted results now record explicit continuation eligibility. Ordinary and native Ollama history builders exclude failed or unfinished research even if an imported message lacks an outer failure status. A temporary SQLite save/reopen check proves partial text and structured audit evidence remain stored without entering subsequent model requests. Legacy successful records without the new field remain compatible. No data migration or destructive cleanup was performed.

Compile and whitespace checks passed. This development slice made no live requests and changed no GUI layout. D0.1 local hardening is complete; D0.2 accounting/state recovery is next. Live Messages compatibility and platform/release gates remain outstanding.


## D0.2 usage accounting and configuration repair slice

All 106 offline tests pass. Seven additional test groups cover cache/reasoning normalization, invalid/non-finite/oversized counters and unknown fields, cumulative Messages usage in ordinary chat and managed research, per-request cache aggregation and sanitized snapshots, failed-attempt aggregation with missing usage, malformed/future-version configuration preservation with successful reopen after repair, and legacy configuration/credential-reference compatibility. Existing offscreen Qt and protocol checks also pass; compile checks passed. No live inference or new native interaction check was run.

Per-request usage is numeric and allowlisted; stream deltas update rather than add cumulative counters. Messages totals include uncached input plus cache creation/read, consistent with [the provider prompt-caching contract](https://platform.claude.com/docs/en/build-with-claude/prompt-caching). Cache/reasoning detail counters already included in other protocols' totals are preserved separately without adding them twice. These details remain reported subsets when not every request supplies them; they are not cost estimates.

Configuration loading validates primary shapes and versions before opening the history database and bounds the configuration file to 4 MB. Invalid input produces a secret-free repair message through the existing startup error path; original bytes are untouched and repair/restart is required. It does not automatically reset settings or create a credential-bearing backup. Valid legacy settings retain unknown extension fields and existing keyring references. Session schema recovery, deeper research-setting validation/capability invalidation, and total retained research-record bounds remain pending within D0.2.


## D0.2 session recovery and retained research records

All 115 offline tests pass, including nine additional regression groups covering malformed/future/mismatched-ID session preservation, legacy defaults without rewriting stored JSON, shared attachment retention with unreadable records, bounded managed/hosted/routed research snapshots, save/reopen of truncated metadata, valid opaque continuation below the budget, and an offscreen Qt recovery flow. The UI test confirms unavailable records show an error instead of opening and interrupted research reopens as failed history without outbound requests. Compile and whitespace checks pass. No live inference was performed in this slice.

Session loading accepts supported versions 1-3 and research records 1-2, validates primary message/form/run/connection shapes, and preserves unsupported or malformed rows as unavailable history entries. Saving an unavailable placeholder is rejected, preventing accidental overwrite. Attachment cleanup stops conservatively while any session's references cannot be inspected. No migration rewrites existing rows merely by listing history.

New detached research snapshots have a distinct 256,000-byte JSON metadata limit (configurable through Limits.record_bytes, minimum 2,048 bytes). Over-budget records omit complete continuation arrays rather than partially replaying them, reduce excerpts/activity, and fall back to a bounded summary if needed. Answers remain available under the existing model-response limits. Completion/activity notices explain the limitation, and continuation eligibility is disabled. Existing stored records are not retroactively trimmed. Deeper research-setting validation and capability invalidation remain pending in D0.2.


## D0.2 research settings and capability isolation

All 122 offline tests pass, including seven additional regression groups. Coverage includes malformed nested defaults/capabilities with byte-for-byte original configuration preservation, valid scoped configuration reopening, account isolation and conservative invalidation, same-key resaves/credential replacement/failed key-store writes, legacy unbound verification, offscreen environment and session credential changes, and a late completion after credential rotation. Existing hosted UI assertions now check the exact active credential scope. Compile and whitespace checks passed. No live inference was performed.

Capability keys can now include a secret-free opaque scope in addition to URL/protocol/model. Saved connections retain their scope across unchanged resaves and rotate it on settings/credential changes; new accounts receive separate scopes. Legacy saved connections get store-lifetime scopes until saved, while environment/discovered connections and session key overrides use application/session-lifetime scopes. Legacy explicit configured enablement may be inherited, but verified/unsupported evidence is not inherited across a new scope. Scoped changes downgrade affected prior verification rather than silently treating it as current. A late result still saves its answer but cannot mark changed credentials verified. No API keys or key fingerprints are persisted in capability records.

The loader validates research scope keys, default policy/access enums, supported capability fields/states, and evidence/timestamp types and sizes. Invalid files remain untouched through the existing repair error path. D0.2 local hardening is complete. Remote account/model mapping changes and credentials changed outside Agentnik cannot be inferred from a stable connection record; an explicit compatibility recheck remains necessary. D0.3 resource/cancellation/Qt work and live/platform release gates remain outstanding.


## D0.3 worker, transport, and Qt lifecycle

All 131 offline tests pass. Nine new test groups cover retained capacity across two cancelled workers and repeated restarts, nested waits with saturated admission, timeouts and thread-start failures without lost slots, vetted-address TCP failover with original TLS identity and no new DNS lookup, terminal certificate failures, shared connection deadlines and duplicate-address skipping, thinking visibility through completion/save/reopen in both themes, simultaneous research tabs with cancellation/restart/capacity/late-result isolation, and saved-profile independence from merged environment/probe discovery. Existing cancellation, strict-navigation no-request, edit/resend, citations, history, and theme checks also pass. Compile and whitespace checks passed.

Research Runtime waits share 16 slots globally. Slots remain reserved until the actual daemon worker exits, even after caller cancellation or timeout; admission is nonblocking to avoid deadlocking nested waits. This bounds research worker accumulation but cannot forcibly stop a blocked OS resolver or remote billing. Ordinary chat/discovery Job threads are outside this research-specific worker admission policy. Address failover occurs only during TCP establishment, across up to eight distinct already vetted addresses under one deadline; TLS failures stop, and no HTTP submission is automatically replayed.

The Qt completion path now persists the user's thinking expansion choice. All D0.3 UI checks used offscreen Qt and temporary data; no native interactive platform validation or live inference was performed. D0 local hardening is complete; D1 controlled compatibility tooling and D2 release automation/platform evidence remain outstanding.


## D1 compatibility tooling and D2 Windows build automation

All 143 offline tests pass. Twelve additional test groups cover compatibility CLI planning without key reads, network requests, or output creation; explicit route validation; existing report preservation; sanitized managed success/failure; bounded chat execution; cancellation without retry; rejecting a plain answer as search evidence; release planning without builds; shared-environment/version mismatch rejection; real ZIP/checksum integrity and overwrite prevention; and missing assets/plugins or local data rejection. Compile and whitespace checks pass. These tests use mocks and synthetic fixture bundles, not live model requests.

A dedicated `.venv-build` environment was created with system site packages disabled and requirements-build.txt installed. The full Windows x64 PyInstaller build and actual frozen Qt readiness/database/graceful-exit check passed. The first build's PowerShell smoke launcher was blocked by execution policy; a new Python ctypes Windows helper replaced that dependency without changing execution policy, and a fresh output label preserved the earlier attempt for diagnosis.

Successful artifact: `dist/build-dev-d1-d2-r2/Agentnik-dev-d1-d2-r2-windows-x64.zip`, about 56.0 MB, SHA-256 `9e47fd99748c8fc2d2e1eabdd7e86649327393e380cc19a66dc1348e68855cb7`. Archive integrity/contents and branding/Qt plugin checks passed. BUILD-MANIFEST.json records Python 3.15.0, PySide6 6.12.0, keyring 25.7.0, PyInstaller 6.22.3/hooks 2026.9, all installed dependency versions, OS/architecture, ab8b6bd plus dirty source state, unsigned status and smoke outcome. Assembly includes README, VALIDATION, the Apache License 2.0, 79 installed-distribution notice files, and Python's license.

This is a development artifact, not a new tagged/published release or replacement for v0.1.0. It verifies startup on this build host, not a clean Windows machine or complete dialogs/clipboard/keyring/TLS workflows. Dependency notices were collected, not fully audited for every bundled library. macOS/Linux, signing/distribution and final release/version gates remain pending. No live inference or search was issued in this development slice. D1 harness tooling is delivered; provider evidence remains scoped to earlier results or later explicitly authorized runs.


## v0.2.0 release source preparation

The release version is synchronized at 0.2.0 in package/project metadata and the web User-Agent uses the package version. All 144 offline tests passed in the isolated `.venv-build` environment, including a full mocked assembly regression for source metadata preservation while copying documentation images; compile and whitespace checks passed. Release assembly now includes release notes, linked validation/development/roadmap documents, and README image assets alongside the existing legal notices and build manifest. No live inference was issued for release preparation.

The Windows archive is built from the clean release-source commit with label v0.2.0. Its BUILD-MANIFEST.json records the exact source/environment and the actual frozen startup outcome; its SHA-256 sidecar verifies archive integrity. Historical v0.1.0 artifacts/tag remain unchanged. This release does not close the documented clean-machine, complete native workflow, macOS/Linux, signing, or full bundled-license review gates.


## E1 passive repositories and Code panes (post-v0.2.0 development)

All 148 offline tests pass, including four new registry/workspace test groups. Coverage includes ordinary/Git directories, canonical duplicate paths, stable IDs and persistence, rename/relocation/removal without file or history deletion, missing folder rejection/recovery, searchable picker cancellation, independent drafts, light/dark offscreen rendering, and reopening after removal or relocation without changing the saved directory. Tests assert no endpoint requests or subprocess launches for the workspace flow. Compile and whitespace checks passed; no live inference was run.

Repository entries occupy a separate SQLite table. Code sessions use version 4 and retain project/name/path snapshots and drafts; old chat/decision session versions remain compatible. The passive pane displays backend-not-connected state and disables Run. Existing history keeps its path snapshot after registry relocation; new panes use the newly selected location. These features are not part of the v0.2.0 release archive. E2 integration/permission decisions remain open.


## E2 simulation and approval contract

All 151 offline tests pass. Three new test groups cover immutable exact-proposal fingerprints, changed/duplicate/stale approval rejection, rejection/timeout/cancellation without execution output, and an offscreen Qt workflow exercising approval, simulated diff review, draft retention, late-event rejection and interrupted reopen. Tests assert no subprocess launch or model request. Compile and whitespace checks pass; no live inference or real coding CLI was used.

The explicit Code simulation proposes a fixed argument tuple and directory snapshot, waits for a one-shot run-bound decision for at most 60 seconds, and produces synthetic output/diff only when approved. Cancellation invalidates approval. Activity is bounded to 32 records of 2,048 characters, and interrupted history is recorded without restarting. The safety recommendation is explicitly Not checked; System One inference and real execution remain unavailable. E2 is partial: backend-neutral contracts and simulated presentation are delivered, while real CLI selection, approval interception, filesystem/network boundaries and child-process lifecycle validation remain gates in CODING_BACKEND_PLAN.md.


## E2 Codex app-server protocol spike

All 156 offline tests pass. Five new fixture groups cover initialization/acknowledgement and exact one-shot decisions; rejection of network/additional-permission requests as command approvals; stale/completed/closed turn handling and unsupported server requests; malformed/duplicate/oversized JSON with adapter closure; and wrong-directory rejection. Compile and whitespace checks pass.

The adapter uses injected send/event functions only: no subprocess transport, Codex launch, credential access, file edits or live inference occurred. A local Codex executable was identified by command inventory but was not executed. Official app-server documentation informed the candidate selection; fixtures establish client-side behavior, not server policy or sandbox guarantees. The real transport/lifecycle, isolated settings/extensions, approval enforcement and authentication gates remain open. The simulation UI still performs no real execution.


## Agentnik-owned multi-model coding preview (supersedes Codex integration direction)

Per user direction, Agentnik owns the coding loop and uses existing connections/models; Codex is interaction inspiration only. The process-free Codex adapter/tests were removed, and the uncommitted stdio experiment was discarded. No Codex process was launched. Historical protocol-spike evidence above remains historical, not a runtime dependency or planned integration.

All 162 offline tests pass. New coverage exercises real temporary-file edits only after explicit review, read-before-edit and conflict detection, traversal/sensitive/reserved/link policy, approval rejection/cancellation and run-bound non-replayable tokens, known-key redaction from file results, Messages/native tool-result correlation, heavy Responses-to-light Messages delegation, no tools for light tasks, no replay/fallback after light endpoint failure, and an offscreen end-to-end Code pane run with independently assigned models, full diff review, persisted key-free roles and reopen without execution. No live coding inference or shell execution occurred.

Heavy/light assignments can use different existing connections and model aliases. Heavy owns tools; light analysis returns bounded text through the heavy model's correlated result. Shared budgets are nine model requests, sixteen tool calls, 100 KB context and five minutes. UTF-8 files are limited to 32 KB. Edits use temporary files and atomic publication, preserve mode bits, recheck source hashes and serialize Agentnik's own commits; this is not an OS sandbox or a guarantee against malicious external filesystem races. No shell, deletion, new directories, automatic Git mutation or System One calls are enabled. Per-role usage reporting, broader live/multi-file qualification and cross-run conversation continuation remain open.


## v0.4.0 release source preparation

All 233 offline tests passed in the isolated `.venv-build` environment, including temporary-repository Dulwich staging/unstaging, explicit-file and staged-snapshot commits, preservation of later working edits and unrelated index entries, branch creation without checkout, stale branch/index/file approval rejection, ignored/sensitive path rejection, cancellation, and partial commit/index-publication reporting. Mocked model tests cover separate Git mutation approvals and rejection; offscreen Qt tests cover Git approval framing and panel visibility. Source compilation and whitespace checks passed. The final Korean catalog contains 352 compiled translations. No live inference or remote Git requests were made.

Version metadata is synchronized at 0.4.0. The release environment adds pinned Dulwich 0.25.2; release assembly includes FEATURES.md and dependency notices alongside existing documentation, branding, catalogs, checksums, and the build manifest. The Windows archive is built from the clean release-source commit. BUILD-MANIFEST.json records its actual source, dependencies, and frozen Qt-window/isolated-database/graceful-exit result. This source preparation does not itself establish frozen Git execution, live-model Git or decision-advice compatibility, clean-machine operation, full native workflow, macOS/Linux support, signing, or a complete bundled-library license audit.


## Managed search-provider adapters (2026-11-09)

Brave Search, LangSearch, and Firecrawl have offline request/response fixtures and provider-independent Chat/Code integration checks. The full suite passed 250 offline tests before a final credential-base cleanup; final focused checks cover the cleaned adapters. Coverage includes fixed endpoint/header/query shapes, separate credential storage and environment profiles, persisted provider identity on key replacement, bounded snippets, empty/malformed results, public destination checks, strict-policy exclusion, no fallback after access restrictions, eligible rate-limit fallback, and Qt provider selection. Korean provider controls are compiled.

One explicitly authorized live Brave query returned three public results with snippets, including Qt documentation. This check called only the Brave search API through Agentnik's adapter (plus DNS validation), made no model inference or fetched-page requests, and kept the supplied credential in process memory. LangSearch/Firecrawl live requests, full native UI review, and live-model research with the new adapters remain unverified. Exa and Parallel are researched roadmap candidates, not implemented adapters. See SEARCH_PROVIDERS.md for supported features and primary API references.


## Exa and Parallel managed search (2026-11-09)

All 257 offline tests passed after adding the two selectable adapters. Seven focused groups cover fixed URLs and x-api-key headers, exact explicit search modes (Exa auto/highlights and Parallel basic/bounded excerpts), local result/excerpt byte limits, metadata-only/empty/malformed responses, private/credential-bearing URLs, cancellation before submission, cross-provider fallback only after eligible definite rejection, provider identity and environment overrides, and mocked Chat/Code tool continuation without search-key disclosure. Existing offscreen profile-editor tests verify all six provider choices. Compilation and whitespace checks passed; the Korean catalog now contains 368 translations.

No Exa or Parallel API key was supplied or live request made. These providers therefore have offline API-contract and orchestration evidence, not live account/model compatibility. Their highlights/excerpts are explicitly disclosed provider retrieval features and may incur charges. The existing five-profile budget, no-replay rules, strict navigation exclusions, and direct-Ollama-only coding policy for Ollama search credentials remain intact. This entry supersedes the earlier roadmap-only status for Exa and Parallel.


## Keyless Firecrawl defaults, fallback, and LangSearch live checks (2026-11-09)

The full offline suite passed 264 tests. Afterward an additional regression was added and the eight focused keyless tests passed, including Code page reads after a keyless quota rejection followed by a Google challenge. Coverage includes no Authorization header or environment-key reuse in keyless mode, keyless profile creation without credential-store writes, default/configured chain ordering and duplicate suppression, eligible fallback after definite rejection, stopping on access/uncertain outcomes, strict-policy exclusion, and skipping a quota-rejected service for the remainder of the run. Compilation and whitespace checks pass; Korean catalogs include keyless controls and the default label.

One explicitly authorized keyless Firecrawl REST search returned three public results with snippets, including doc.qt.io. No API key, model inference, or fetched-page request was used. Two authorized LangSearch adapter requests used the supplied key only in memory: the broad Qt signals/slots query returned casino-related/off-topic domains, and the user identified the ambiguous word slots. A follow-up `site:doc.qt.io PySide6 signals slots` query returned three official Qt documentation pages with relevant snippets. These are adapter-level results, not a general search-quality benchmark or end-to-end live-model compatibility claim. Keyed Firecrawl, Exa/Parallel, and live Google fallback remain unverified.

Requested production behavior is configured search profiles followed by Firecrawl Keyless and Google scrape, or those two defaults when no profiles exist. Built-in entries do not consume the five configured-profile slots; each chain considers at most seven entries. Long Retry-After guidance prevents retrying that service but permits switching after a definite eligible rejection; access restrictions, ambiguous outcomes, cancellation, and malformed responses remain terminal. No supplied search keys were written to project files or application settings by these checks.


## Provider retrieval after filtered direct page reads (2026-11-09)

All 272 offline tests passed after the retrieval implementation. Seven focused groups cover direct success without a provider call, network-filter recognition versus ordinary documentation, branded HTTP 403 block responses, TLS/reset fallback and visible URL-disclosure events, strict mode and mixed/private DNS rejection, generic site denial/timeout non-fallback, fixed Firecrawl/Exa/Parallel/Ollama API request shapes, no Authorization for keyless retrieval, returned private/restricted-page rejection, and mocked Chat/Code continuation without repeating model inference. The settings notice and Code tooltip now disclose provider URL retrieval, external navigation and possible charges, with compiled Korean translations (374 catalog entries).

Provider retrieval is conditional on an eligible direct transport/filter failure. Initial and reported final URLs retain public validation; provider-internal navigation cannot be pinned and is excluded by strict mode. Retrieval remains bounded by existing response/time/context accounting and 8 KB source excerpts. No real network-filter appliance, paid provider retrieval request, or live model inference was used to validate this slice. Existing search-only live checks do not establish these page-retrieval APIs' compatibility.


## Focused coding tools (2026-11-09)

All 282 offline tests passed for the first project-tool slice. Focused tests additionally check framework failure-excerpt matching after the final parser refinement. Coverage includes bounded large-file range reads, sensitive/traversal/binary rejection, region-only edit permission, unique exact matches, CRLF and surrounding-content preservation, stale read/review rejection, cancellation with temporary-file cleanup, metadata inspection without execution, structured unittest/pytest/Jest/Vitest summaries and unknown/truncated output, mocked model patch/test approval and rejection, and offscreen Qt test-command framing. The compiled Korean catalog contains 375 translations.

An owned temporary unittest fixture was executed through the actual approved shell path on the Windows host and returned one passing test in the structured report. No paid or live model requests were issued. These results do not qualify live-model tool selection, other native platforms, or longer test suites. Tests retain the existing shell deadline and output bounds. Script bodies/metadata are never executed by project_overview, and parsed test counts remain untrusted reported evidence, not independent verification.


## Coding task plan/checklist (2026-11-09)

All 288 offline tests passed. Six plan-specific groups cover strict schema/size/status validation, copied state, multiple model updates and plan reads without execution, malformed/credential-bearing plan rejection, legacy session compatibility, persistent read-only Qt checklists, cancellation, late-run event rejection, reopen without inference/process execution, and clearing the prior plan for a new real coding run. Plan updates use existing tool budgets and known-key guards; completion is model-reported and never automatically inferred from run completion.

Both theme screenshots were rendered with temporary data and the project's explicit Windows screenshot font setup; the dark-theme expanded panel was inspected for status labels, checkboxes, explanation and remaining transcript space. The list height now follows short plans up to its 140-pixel cap; the checklist starts collapsed. The Korean catalog contains 381 compiled translations. No live model request was issued; native interactive behavior and live model planning quality remain unverified.


## Direct independent-review adapter checks

Mocked and offscreen tests cover single structured-review visibility, individual cancellation with late output discarded, valid/invalid/truncated finding records, and explicit session saving and reopening without a request. The Heavy progress-saving opt-in now also persists a single structured-review manifest before submission and updates the result; tests cover failed manifest acknowledgment, changed evidence after acknowledgment and forced-stop recovery. No live inference was used.

Offscreen Qt checks cover the three-pass preset, preservation of model and evidence selections, the document-only comprehension boundary, and the approval text about redaction and provider retention or charges. Selecting the preset does not issue a request. Visual inspection of an offscreen render was limited by missing fonts in this environment; native layout remains unverified.

An offscreen test holds one mocked same-endpoint reviewer while checking the second pass is queued and individually cancellable without submission. A saved-session test checks queued and running subagents reopen as interrupted; a forced-stop check covers interrupted manifests, where event delivery can lag worker dispatch. No live inference was used.

Offline and offscreen checks cover post-approval preflight failures for direct and Heavy-requested batches: changed sources yield stale records, unaffected passes are skipped, shared-budget failures skip the batch, no reviewer request is sent, and opted-in progress is updated from interrupted to the terminal state.

Offline and offscreen tests cover rejected direct and Heavy-requested batches: no reviewer requests are sent, each pass is recorded as skipped with its approval state explained, optional progress saving persists the records, and reopening does not submit a request. Rejected records do not claim a completed batch approval.

Offline and offscreen tests cover UTC batch-approval timestamps in direct and Heavy-requested saved progress, interrupted process recovery, project-history round-tripping, legacy snapshots and malformed timestamps. The timestamp uses the local system clock and does not establish when a provider received or completed a request.

Offline and offscreen tests check the transmitted-document hash against redacted text, display it in approval, bind it to batch preflight, and retain it in direct and Heavy-requested progress and project history. Legacy records without the hash remain readable.

Offline and offscreen checks cover origin-only endpoint attribution for direct and Heavy-requested review progress, known-secret omission, IPv6, unsupported host forms, invalid imported origins, legacy records and project-history round-tripping. The origin does not identify a particular account or URL path.

Offline and offscreen tests cover rubric-version attribution for direct and Heavy-requested saved review progress, project-history round-tripping, legacy snapshots, and invalid or unsupported versions. Tests pin the version 1 structured, drift and repository-fit instruction text alongside the other review rubrics.

Offline scheduler and offscreen session checks exercise non-completed review reasons, including failed and skipped same-endpoint passes, cancellation, stale input, safe omission of raw endpoint errors, and reopen without a request. Project-sidecar tests cover reason round-tripping; malformed and oversized reasons are rejected.

Offline mocked and offscreen tests also check completed-pass timing and provider usage retention in direct and Heavy-requested session snapshots, older-record compatibility, and rejection of malformed measurements. These are provider-reported counters, not cost estimates.

Offline adapter mocks exercise direct reviews through Chat Completions, Messages, Responses and native Ollama routing. They check the exact approved single-message input, selected evidence, exclusion of credentials and unselected project files, tool-free requests, Responses `store: false`, and failure without retry for unexpected tool calls. Existing mocked transport and offscreen tests cover approval, cancellation and persistence. These adapter checks do not exercise provider wire compatibility, live model behavior or provider-side isolation.

Simulated transport also runs the real direct-review adapters for all four routes with completed and incomplete non-streaming replies and successful streaming replies. Completed structured findings are parsed; incomplete replies fail without findings or automatic retry. These fixtures do not establish compatibility with live providers.

## Document Reader qualification

Offline generated fixtures cover bounded UTF-8 text, DOCX paragraphs, XLSX cached values, oversized archive rejection, PDF text extraction and PNG page rendering. Request serialization retains both extracted PDF text and images for Chat Completions, Responses, Messages and native Ollama. Qt tests cover draft storage, saved-prompt payloads, attachment removal and reader preview. Full suite: 292 passing tests; compileall and git diff --check passed. Offscreen reader and Chat layout screenshots were reviewed. No live multimodal model request, native manual trial, OCR, or release packaging qualification was performed.


## Calculator and Data Analysis qualification

The full offline suite passes 300 tests. New checks cover permitted arithmetic and function domains, forbidden AST constructs and resource bounds, malformed/oversized CSV and JSON, missing/nonnumeric/boolean handling, grouped summaries, recoverable arithmetic errors, explicit registry opt-in, local-only Chat without web tools, protocol continuation across Chat Completions/Responses/Messages/native Ollama, Heavy tool execution without research or approval, and Qt control persistence/reopen/busy state. Offscreen Chat layout was reviewed. Compilation and git diff --check passed. No live inference, remote data service, shell execution, new dependency, or release packaging validation was needed or performed. Float results are approximate and describe only supplied rows; these checks do not establish model data selection quality.


## Scoped repository guidance qualification

Full offline suite: 308 passing tests. Eight new guidance checks cover ancestor ordering and subtree discovery, refresh/removal, implicit-read permission isolation, invalid encoding/binary/oversized/hard-linked files, cumulative guidance bounds, initial instruction injection across Chat Completions/Messages/Responses/native Ollama, configured-secret redaction, new nested guidance deferral, approval-time changes, same-batch AGENTS.md edits invalidating later mutations, unchanged shell approval, Light context, and shared context budgets. Compilation and git diff --check passed. Activity uses the existing Code output-event path. No live model request was made; convention adherence and command target interpretation remain model-dependent. Shell guidance is scoped by working directory, not inferred from arbitrary command text.


## Skills YAML and resources

The isolated Windows build environment uses PyYAML 6.0.3 for bounded safe skill frontmatter parsing; aliases, quoted values and multiline descriptions are covered. Offline checks reject duplicate keys, unsafe object tags, excessive nesting, invalid metadata and escaping skill paths. Selected skills can list bounded resources without executing them. The full suite passed 317 tests; no live model request or frozen release build was run for this change. Cross-platform native validation and skill update behavior remain open.


## Parallel Light and skill updates

Offline mock tests cover genuinely concurrent Light requests, tool isolation, selected skill context, attributed partial failure, shared request limits, cancellation and stale skill changes during approval. The full suite passed 323 tests, including the post-response skill update check. No live model request, frozen build, or cross-platform native validation was performed for this slice.


## Approved subagent file snapshots

The full offline suite passed 327 tests. Mocked coding runs cover individual approval of file text and endpoint, configured-secret redaction, rejected and changed files, scoped repository guidance before delegation, concurrent Light requests and cancellation. An offscreen Qt check verifies that the transfer approval shows the file text, model and destination. No live model request or cross-platform native validation was performed.


## Parallel subagent progress and usage

The full offline suite passed 328 tests. A mocked concurrent run verifies that a fast child reports before a blocked child, that final results retain task order, and that missing provider token counts remain unknown. The existing tests cover approvals, shared budgets, cancellation, and partial failures. No live model request or native cross-platform validation was performed for this update.


## Alternate subagent model routing

The full offline suite passed 331 tests. Mocked concurrent runs verify per-task routing across Chat Completions and Messages, alternate endpoint/file approval, credential redaction, and no silent fallback when the alternate is unavailable. Offscreen Qt checks verify selection, launch and session persistence; the expanded model panel was visually reviewed offscreen. No live inference, frozen build or native macOS/Linux validation was performed.


## Subagent status view

The full offline suite passed 333 tests. Qt checks cover start/completion state, cancellation, interrupted session reopening, stale events, and bounded record validation. The collapsed and expanded status flow was reviewed offscreen; no live inference or native macOS/Linux validation was performed.


## Three-model parallel subagents

The complete offline suite passed 335 tests. Mocked parallel calls cover Light and two alternates using Chat Completions, Messages and Responses, including per-file destination approvals, cross-credential redaction, no silent fallback, and session compatibility. The expanded model panel was reviewed offscreen. No live inference, frozen release build, or native macOS/Linux validation was performed for this slice.


## Individual subagent cancellation

The full offline suite passed 339 tests. Mocked runs and offscreen Qt checks cover cancelling one child while its sibling completes, suppression of late output, rejection of identical retries or reassignment, unknown usage for cancelled requests, selection state and persistence. Request-construction failures remain isolated to their child. The Code control was reviewed offscreen. No live model request or native macOS/Linux validation was performed. Cancellation stops local waiting; an already submitted provider request may continue.

## Skill selections across runs

Offline tests cover selection fingerprint persistence, invalid fingerprints, changed and missing instructions, prevention of model requests, legacy sessions, and confirming an updated selection in the offscreen Qt picker. The full Windows test suite passed 342 tests. Native macOS and Linux validation and live model checks were not run.

## Independent document review preview

The Windows offline suite passed 348 tests. Mocked requests verify fresh document-only input across Chat Completions, Messages and Responses; exact preview and hashes; secret redaction; exclusion of drafting context, Skills and scoped guidance; approval rejection; changed documents; context limits; and cancellation with late output discarded. An offscreen Qt check covers the approval display. No live model, provider-side isolation, frozen build, or native macOS/Linux qualification was performed for this slice.

The subsequent fixed-role extension passed the full 350-test offline suite on Windows. Mocked sequential requirements, design and implementation-readiness reviews verify individual approvals, distinct fixed rubrics, attribution, and exclusion of prior review findings. Invalid roles do not trigger approval or inference. The offscreen approval check includes the role. Parallel review, external evidence, persistent dispositions and live-model qualification remain outstanding.

The project-evidence extension passed the full 354-test Windows offline suite. Mocked reviews cover exact approved input, evidence hashes and credential redaction, rejection, changes before and during review, invalid paths and scope, and discovery of nested guidance before approval. An offscreen Qt check verifies evidence paths and hashes in the approval view. Model behavior, provider-side isolation, frozen builds and native macOS/Linux remain unqualified; later changes to approved files are not monitored.

## Direct page TLS and configured retrieval fallback

The full Windows offline suite passed 357 tests. Tests verify that direct page transport disables certificate and hostname verification, while search and provider transports retain verification; configured retrieval-capable providers are selected without automatic or explicit Firecrawl Keyless page fallback. Mocked Chat and Code checks exercise provider continuation, URL-policy restrictions and terminal failures. A local TLS server using a self-signed, mismatched certificate was rejected by verified mode and accepted by direct-page mode. No external site, Zscaler deployment, provider retrieval API, live inference or macOS/Linux validation was exercised.

## Project search and automatic file changes

The Windows offline suite passed 363 tests. Temporary-project tests cover bounded recursive globbing, literal case-sensitive and case-insensitive search, Unicode, filename filters, excluded paths, hard links, oversized/binary files, cancellation and credential redaction. Mocked coding runs and offscreen Qt checks cover applying project file changes without per-file approval, stale-file and changed-guidance/skill protection, cancellation, and continued shell/Git approval. No live coding-model or native macOS/Linux checks were performed.

## Regex search and project file moves

The Windows offline suite passed 370 tests. Temporary-project and mocked coding tests cover regex matching, invalid patterns and bounded pathological expressions; read-before-move, source conflicts, destination collisions, project boundary checks, destination guidance, cancellation, and partial-move failure. A dirty Windows development build included the native regex module and passed its Qt window, isolated SQLite and graceful-exit startup smoke check. The smoke check did not run a frozen-app coding task; live-model and native macOS/Linux behavior remain unqualified.

## Code activity scrolling and retention

The Windows offline suite passed 373 tests. Offscreen Qt checks cover following the bottom, keeping the visible location while scrolled up, resuming at the bottom, preserving the view when old wrapped lines are trimmed, and reopening the enlarged saved history. Native visual review, frozen-build and macOS/Linux validation were not performed for this change.

## Unrestricted file-size and binary moves

The Windows offline suite passed 378 tests. Temporary-file tests cover large binary files without model content reads, metadata conflict checks, no-overwrite destination collisions, cancellation, simulated cross-filesystem and hard-link-unavailable fallbacks, exclusive publication, staging replacement, and partial failures. Cross-filesystem and unsupported-hard-link errors were simulated on the Windows host; actual separate filesystems, native macOS/Linux, and frozen-build coding behavior were not tested. Cross-filesystem metadata preservation is limited as described in CODING_GUIDE.md.
