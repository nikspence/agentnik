# Baseline validation

Validated on Windows on 2026-11-08 using Python 3.15 and PySide6 6.12.0.

## Passed

- All 23 standard-library and offscreen Qt tests passed. Coverage includes protocol serialization/streaming, decisions, independent tabs, cancellation, prompts, attachments, themes, storage isolation, and Agentnik-scoped credential-store calls.
- Compile checks passed for `agentnik`, `tests`, and `tools`. Source launcher help passed.
- The light/dark wordmark and temporary-data welcome screenshots were visually inspected during baseline creation. The robot retains its geometry with red shading matching the wordmark; `agent` follows the theme and `nik` is warm red.
- `pip wheel . --no-deps --wheel-dir dist` built `agentnik-0.1.0-py3-none-any.whl`. The wheel installed into the local `.venv` without installing runtime dependencies again; existing PySide6/keyring dependencies are shared through system site packages.
- The installed package was imported with source-directory imports excluded. All seven packaged branding assets were present; SVG and PNG decoding passed.
- The installed application's entry point ran the offscreen event loop and exited successfully with temporary storage and mocked environment/endpoint discovery. Application/organization identity and the temporary history database were verified. The harness explicitly closed its database before deleting the temporary directory.
- Intended source files were audited for obsolete branding, private development endpoints, machine-specific paths, and common credential patterns. No matches were found. This is a targeted scan, not a guarantee against every possible secret format.
- The MIT license matches the supplied source verbatim, including Copyright (c) 2026 Nikolaus Spence. Project metadata identifies Nikolaus Spence as author.
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

Built with PyInstaller 6.22.3, hooks 2026.9, Python 3.15.0 and PySide6 6.12.0 on Windows 11 x64 using `Agentnik.spec`. The onedir distribution includes Qt plugins, all seven branding images, and the MIT license. A ZIP integrity/contents check passed; a SHA-256 sidecar accompanies the archive in `dist/`.

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

Successful artifact: `dist/build-dev-d1-d2-r2/Agentnik-dev-d1-d2-r2-windows-x64.zip`, about 56.0 MB, SHA-256 `9e47fd99748c8fc2d2e1eabdd7e86649327393e380cc19a66dc1348e68855cb7`. Archive integrity/contents and branding/Qt plugin checks passed. BUILD-MANIFEST.json records Python 3.15.0, PySide6 6.12.0, keyring 25.7.0, PyInstaller 6.22.3/hooks 2026.9, all installed dependency versions, OS/architecture, ab8b6bd plus dirty source state, unsigned status and smoke outcome. Assembly includes README, VALIDATION, the MIT license, 79 installed-distribution notice files, and Python's license.

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
