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
