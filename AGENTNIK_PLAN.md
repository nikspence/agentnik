# Agentnik implementation plan

Reviewed: 2026-11-08. This roadmap describes the current development tree and the remaining acceptance gates. Detailed historical evidence is in [VALIDATION.md](VALIDATION.md); installation and delivered behavior are in [README.md](README.md).

## Objective and preserved contracts

Agentnik is an independent Python/Qt desktop application for chat, Ollama System One decisions, bounded web research, and a future repository-based Coding Agent workspace. Keep runtime dependencies small and support Windows, macOS, and Linux without claiming untested platform compatibility.

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
| B — Managed research | Implemented preview: native Ollama tool loop, Ollama search, direct public page fetch, sources/activity, persistence, cancellation | Offline evidence; live research compatibility unverified |
| C — Hosted research and routing | Implemented preview: managed Responses, official OpenAI Responses hosted search, four policies, bounded fallback/accounting | Offline evidence; live research compatibility unverified |
| D — Hardening and release readiness | In progress: development tree adds Chat Completions/Messages managed adapters and a readiness-based frozen smoke script | D0 local hardening, D1 controlled compatibility evidence, D2 distribution/platform gates below |
| E — Coding Agent | Planned | Begin with passive repository registry/picker; execution needs a separate boundary/backend decision |
| F — MCP servers and Skills | Long-term planned | Optional extensions with explicit configuration, activation, permissions, and shared tool approvals |

The current offline baseline is **90 passing tests**, including offscreen Qt and mocked protocol/transport checks. This establishes contract coverage, not real provider compatibility. Existing screenshots use simulated responses. User testing has reported successful Windows use; that is useful feedback, not a completed native workflow matrix.

The **v0.1.0** tag and Windows onedir archive are an earlier source checkpoint. Its frozen executable passed actual Qt-window initialization, temporary SQLite creation, and graceful exit; it is unsigned. The current D development build passed a separate Windows startup smoke check. Neither proves live TLS/provider behavior, credential-store integration, complete native workflows, or macOS/Linux operation. Keep the historical tag/archive unchanged and use distinct development output directories. Current D changes remain development work until reviewed and committed; do not describe them as present in v0.1.0.

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

Default limits currently include four tool rounds, eight tool calls, five search results, 1 MB per web response, 3 MB retrieved per turn, 32 KB tool context, 4 KB arguments, 512 KB model response, six model requests, eight route attempts, 45-second request and 180-second turn deadlines, three redirects, and five-second maximum backoff. These are separate limits, not a guarantee that total retained session storage is 32 KB.

## 3. Lessons retained from implementation

- **Readiness needs application evidence.** The first frozen check was too impatient. Wait for a process-owned Qt window and temporary database within a deadline, then request a graceful close and verify exit status. Input-idle alone is insufficient; startup success is narrower than interactive success.
- **Protocol compatibility is narrower than capability.** Keep separate adapters, structured tool histories, opaque reasoning, identifiers, completion reasons, and missing-usage states. Do not infer hosted support from a Responses-shaped gateway.
- **Fallback can duplicate remote work.** Retry only eligible explicit outcomes within budgets. Stop on cancellation, access restriction, partial output/tool activity, or uncertain execution. Do not change model/provider or use alternate routes to bypass restrictions. Empty results are research evidence, not a transport failure.
- **Cancellation is cooperative.** Stop scheduling and reject late results immediately; remote computation/billing and outstanding local socket operations may continue until their own bounds. Test resource behavior across repeated cancellations, not just one late result.
- **External navigation needs honest disclosure.** Direct fetch has local controls; search services and hosted tools do not inherit those controls. Do not silently weaken strict policy or enable service-backed fetch.
- **Discovery should identify destinations without erasing user intent.** Environment-discovered `0.0.0.0` means connect to `127.0.0.1`. Merge matching environment/probe discoveries, retaining environment metadata and useful probe information. Preserve independently saved connections and avoid treating arbitrary DNS names or IPv6 destinations as equivalent.
- **Small asset defects affect runtime quality.** Empty SVG paths caused Qt warnings. Retain parser-warning coverage and inspect both themes. Editing/resending a historical prompt restores a draft and appends a new turn on Send; it does not rewrite history.
- **Build and release are distinct.** A wheel, source test suite, local frozen startup, and portable desktop release establish different evidence. The first release archive included documentation/license through manual assembly; automate that step before repeating releases.

## 4. D0 — Next work: local hardening

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

### D0.3 Worker, transport, and Qt lifecycle

Test rapid cancel/restart and simultaneous tabs with stalled DNS, web, and model workers. Add an aggregate concurrency/resource bound if existing per-turn deadlines allow abandoned workers to accumulate; reject late results without compromising responsiveness. Keep remote-stop limitations explicit.

The pinned transport currently tries the first approved address. Consider bounded failover among already validated public addresses under the same deadline and TLS hostname; never re-resolve through an unvalidated path. Retain redirect, content-type, compression, and byte restrictions. Richer extraction/charset support is optional follow-up, not a reason to relax transport controls.

Check that research completion preserves the user's thinking expansion choice just as ordinary chat does. Exercise cancellation, draft retention, edit/resend, source links, independent tabs, interrupted reopen, and light/dark presentation. Expand discovery regressions for saved-profile independence and environment/probe precedence.

Acceptance: bounded worker behavior under repeated cancellation, no late history/UI mutations, no outbound requests for strict-policy research, and offscreen Qt regression coverage. Record any native checks separately.

**D0 exit:** all applicable offline tests and compile checks pass; focused Qt checks cover changed interaction; newly found issues are fixed or explicitly scoped with rationale. Update README/VALIDATION to describe delivered behavior. This is the next implementation target, not another new feature family.

## 5. D1 — Controlled compatibility evidence

The existing `tools/live_smoke.py` is useful for baseline endpoints/decisions but is not a research compatibility matrix. Add a separate opt-in harness or an explicit research mode before live research testing:

1. Require the exact endpoint, protocol, model, route, and managed backend/profile. No automatic model selection, hidden cross-provider fallback, or background paid probes.
2. Make the planned bounded request/query visible and use a small, public, non-sensitive task. Honor cancellation and the same limits as the GUI.
3. Record timestamp, application revision, selected scope, stop outcome, tool correlation/continuation result, citations, and available usage. Redact secrets; do not retain private transcripts or key files as fixtures.
4. Distinguish model tool-calling from successful external search/fetch and from final-answer citation rendering. Test routing errors with mocks; do not manufacture repeated live failures to exercise fallback.
5. Update only the capability actually demonstrated. Report unavailable credentials/models as not tested. Do not claim every model on a compatible server works.

Acceptance is per endpoint/model/protocol/route, not a global supported-provider label. No live requests are authorized merely by this plan review. Keep System One verification separate and require a substantive real request before claiming a model supports it.

## 6. D2 — Repeatable releases and platform gates

Automate clean build, documentation/license inclusion, archive creation, SHA-256 generation, and contents verification. `Agentnik.spec` currently bundles branding assets; root README/LICENSE and archive assembly still need an explicit repeatable release step. Record Python, Qt, PyInstaller/hooks, dependency versions, OS/architecture, source revision, and relevant third-party license notices. Validate a clean build environment without accidental system-site-package dependencies.

Keep onedir as the initial Windows format. Distribute the whole directory. PyInstaller builds are platform-specific; Windows success does not establish Linux/macOS portability. See [PyInstaller operating mode and distribution requirements](https://pyinstaller.org/en/stable/operating-mode.html).

For each claimed platform/artifact, record:

- Clean-machine launch without development Python, packaged assets/plugins, readiness-based temporary-data startup and graceful exit.
- Native chat/decision/research forms, file dialogs, clipboard, links, cancellation, themes, attachment/history reopen, and keyring success/unavailable/explicit-fallback behavior.
- TLS/certificate behavior with an appropriate authorized check, distinguishing transport success from inference compatibility.
- Required platform libraries, signing/notarization status, installation/update behavior, and known limitations.

A Windows preview may ship with clearly documented model/platform limits after its applicable gates pass. Full D completion requires the declared cross-platform and compatibility matrix; unavailable macOS/Linux hosts remain explicit pending evidence. They need not prevent passive E1 development after D0. Signing, installers, and automatic updates are separate scope decisions, not implied by an unsigned ZIP.

Before another release, explicitly choose and synchronize the version in package metadata, artifacts, release notes, and tag. Do not overwrite v0.1.0 or silently retag it. Committing, pushing, tagging, and publishing remain separate requested actions.

## 7. E — Repository-based Coding Agent

### E1: Passive repository registry and picker

After D0, this is the first feature slice, even if external D1/D2 evidence is awaiting suitable providers/platforms.

- Persist a **Repositories** list (Repos for short) of local working directories. Git is optional. Use stable identifiers, display names, and paths; provide Add folder, rename, remove-from-list, and relocate-missing-folder actions. Removing an entry never deletes files.
- Detect duplicates with platform-appropriate path/case/alias handling. Validate accessibility and show missing paths without losing the entry. Do not scan the computer or import other applications' registries. Exclude absolute local paths from portable exports by default.
- **＋ Code** opens a searchable repository picker with Add folder. Cancelling starts no session or process. Selecting a project opens an independent Code pane with the repository/working directory visible and a clear backend-not-connected state until E2 is implemented.
- Use temporary ordinary folders/Git repositories to test persistence, duplicates, unavailable paths, cancellation, independent tabs, and reopen without execution.

### E2: Decide and enforce the execution contract

Choose deliberately between integrating an existing coding CLI and implementing an Agentnik-owned coding loop. Evaluate process/session APIs, structured output, authentication, cancellation and child cleanup, licensing/distribution, platform support, and how edits/diffs are reviewed. Do not assume terminal emulation alone provides a reliable integration.

A selected directory is not a filesystem sandbox. Define enforceable file/command/network boundaries, approvals, operations outside the project, and destructive-action handling before enabling execution. Keep coding tools/credentials separate from chat/research. Preserve pre-existing uncommitted changes; no automatic reset, clean, commit, push, or publish.

### Optional System One command safety recommendation

When the Coding Agent is ready to request approval for a proposed command, optionally run a configured System One decision model against that command and a deliberately limited context (for example, working-directory scope and the intended operation). Show the result alongside the exact command in the approval view as a concise recommendation with reason text and one or more clear badges. Suggested categories include **Safe**, **Risky**, **Privacy**, **Warning**, and **Danger**; define the structured decision schema and mapping so labels are consistent and explainable. Multiple badges may apply, and an uncertain or incomplete result must be shown as **Unknown** or **Review needed**, not silently treated as safe.

This check is opt-in and advisory. It never grants approval, suppresses the normal user approval step, or replaces enforced execution boundaries. The user sees what command and context will be sent, which configured decision endpoint/model will receive it, and the result before approving or rejecting. If the check is disabled, unavailable, times out, or returns invalid output, present that status plainly and continue only through the ordinary approval policy; do not represent missing review as a safety pass. Do not send secrets or unrelated conversation history. Preserve the recommendation and its scope in the session's bounded audit record without storing credentials.

Acceptance: tests cover badge mapping, mixed categories, explanation and uncertainty display, opt-in/offline/error states, context minimization, and the fact that every command still requires the established approval and enforcement path. Validate that the proposed command shown for approval is the same command evaluated; any modification requires a fresh review.

### E3: CLI-style coding sessions

Provide the requested composer, streaming transcript, command/output activity, run/cancel state, and changed-file/diff review. Sanitize terminal controls rather than interpreting them as HTML/application commands. Keep processes off the GUI thread, bound output/time, and handle launch failure and platform-specific child-process cleanup.

Bind each session to its project; never silently change a running working directory. Persist a distinct versioned coding-session type with bounded activity and run state. Reopen does not rerun commands. Validate fake backends and temporary projects first; native execution/platform checks are separate gates.

## 8. F — MCP servers and Skills (long term)

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

## 9. Deferred scope and review discipline

Defer additional hosted/search providers until an adapter and evidence justify them. Full browser automation, JavaScript interaction, login/cookie sessions, forms/purchases, arbitrary execution in research, autonomous background tasks, model-provider failover, and research inside System One remain outside this roadmap's delivered scope.

For each slice: inspect the relevant implementation, preserve user data, add tests for meaningful behavioral risks, run relevant offline/Qt checks, and update evidence without erasing historical limitations. Do not substitute test counts, documentation, or a startup screenshot for compatibility evidence.

Immediate order (D0.1 local hardening complete): **D0.2 accounting/state → D0.3 lifecycle/Qt → D1 harness and D2 release automation → E1 registry/picker**. Authorized live/provider and available platform checks proceed as their prerequisites become available; coding execution remains gated by E2.
