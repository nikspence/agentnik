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
