# Agentnik implementation plan

## Objective and ownership

Create Agentnik as a standalone, cross-platform Python/Qt desktop application for chat, structured decisions, and bounded agentic web research.

Agentnik will start in a clean new repository with a fresh initial commit. Do not import Git history, remotes, tags, branches, or repository metadata. Public documentation, source code, assets, application metadata, tests, and packaging must use Agentnik naming and contain no references to the predecessor application. Preserve the MIT license and its copyright notice: **Copyright (c) 2026 Nikolaus Spence**. Nikolaus Spence is the author and copyright holder.

This document is an implementation plan. Creating the repository, publishing it, and executing live endpoint requests are separate actions from writing this plan.

## 1. Establish a clean Agentnik baseline

1. Choose a separate destination directory and verify it is empty before populating it. Leave the current application and its user data untouched.
2. Copy only reviewed application source, tests, necessary tools, dependency declarations, and suitable assets. Exclude `.git`, virtual environments, caches, build products, local configuration, databases, attachments, credentials, key files, logs, and screenshots that expose private data.
3. Rename the Python package and launcher to `agentnik` and `agentnik.py`. Update imports, entry points, project metadata, commands, scripts, tests, and contributor instructions together.
4. Write an Agentnik README and AGENTS.md describing the actual baseline and planned work. Replace branding assets and screenshots with Agentnik material; inspect rendered images as well as filenames and text. Do not ship old branding while replacement assets are pending.
5. Use independent application identity, window titles, platform metadata, settings, credential-store service names, and data directories. Use `AGENTNIK_HOME` and retain an explicit `--data-dir` override. Never discover or modify another application's data automatically.
6. Preserve provider-standard environment variable discovery and endpoint compatibility. Remove predecessor-specific environment aliases, import labels, and compatibility documentation. Do not add a named legacy migration feature. Generic validated connection import/export may remain.
7. Retain the MIT LICENSE verbatim with Nikolaus Spence's copyright notice; identify Nikolaus Spence as author in project metadata.
8. Scan all tracked text and inspect assets for predecessor names, obsolete links, secrets, and machine-specific paths. Initialize a new Git repository with no inherited remote and create a fresh baseline commit after validation. Do not publish unless requested.

Baseline acceptance: Agentnik launches with independent storage, inherited functionality passes relevant tests, packaged assets resolve, and the new repository contains only intended files with no inherited history or predecessor references.

## 2. Preserve the baseline contracts

- Keep chat tabs and histories independent and network work off the GUI thread. Preserve Markdown, inline thinking, images, statistics, accessibility, themes, saved prompts, and attachment persistence/cleanup.
- Preserve Responses, Chat Completions, Messages, and native Ollama chat behavior. Keep Bedrock scoped to Mantle bearer-token endpoints.
- Preserve structured System One decisions, ordered questions and criteria, multiple images, and image-only state fallback. Web research initially applies to chat only.
- Keep secrets in the credential store or the existing explicit plaintext fallback. Exclude credentials from histories, logs, tool records, and exports by default.
- Preserve explicit confirmation for destructive history operations and validation of imported connections.
- Keep dependencies minimal and compatible with Windows, macOS, and Linux. Asset-build dependencies remain optional.

## 3. Define search routing and capability contracts

Support two distinct routes behind a common research interface:

| Route | Execution responsibility |
| --- | --- |
| Provider-hosted search | The connected model provider executes its supported search/retrieval tool inside the provider request. |
| Agentnik-managed tools | Agentnik executes validated search/fetch calls and supplies their results to the model in subsequent requests. |

Both routes must be implemented for the browsing milestone to be complete.

Offer four policies: **Provider first**, **Agentnik first**, **Provider only**, and **Agentnik only**. Save the default per connection and allow an override per chat. Web access starts off. A managed route can have an ordered list of search backends with independently stored credentials.

Track hosted-search and model tool-calling capabilities separately for each endpoint/model combination. Protocol compatibility is not evidence of capability. Represent unknown, configured, verified, and unsupported states distinctly; record when and how verification occurred. Do not issue background inference probes or claim compatibility without appropriate validation.

Keep the selected model and model connection unchanged during search-route fallback. Changing models or model providers is outside this policy. Disclose that managed searches may send queries to a separate service even when inference runs locally.

## 4. Build the tool foundation

- Introduce typed records for tool definitions, tool calls, results, source records, route attempts, and research events. Preserve provider-specific identifiers and required continuation state.
- Separate transport/protocol adapters from orchestration, route policy, and web-service adapters. Suggested modules: `agentnik/core.py`, `agentnik/tools.py`, `agentnik/web.py`, and `agentnik/research.py`; refine boundaries after inspecting the copied implementation.
- Add protocol-specific serialization and parsing for tool calls/results. Assemble streamed arguments before validating or executing a call; handle multiple calls and malformed arguments explicitly.
- Preserve structured assistant/tool exchanges for follow-up requests, including required reasoning/continuation blocks where applicable. Do not flatten everything into assistant text.
- Execute only registered, schema-validated tools. The initial registry contains `web_search(query)` and `web_fetch(url)`; it provides no arbitrary code, shell, file access, or state-changing web operations.
- Bound tool rounds, calls, result count, retrieved bytes, context contribution, per-request time, and total turn time. Make limits explicit and return understandable limit errors.
- Use cancellation tokens and run identifiers across every stage. Stop scheduling work immediately on cancellation and reject late worker results. Do not promise that remote computation or billing stops.

## 5. Implement both search routes

### Agentnik-managed tools

Implement a search backend interface returning titles, URLs, and bounded excerpts. Start with Ollama's documented search/fetch service, subject to verifying its current contract during implementation. Keep this adapter replaceable and permit additional configured backends without changing the model tool schemas.

Implement bounded page retrieval and readable-text extraction with provenance, retrieval timestamps, content type, truncation indicators, and structured errors. Prefer service-provided extraction where suitable. Add dependencies only when a concrete extraction requirement justifies them.

Support native Ollama tool execution first, then the supported Chat Completions, Responses, and Messages adapters. Each adapter requires its own contract tests; do not assume one wire format works across protocols.

### Provider-hosted search

Start with a documented OpenAI Responses web-search adapter. Verify the current API, model restrictions, usage fields, citation annotations, and continuation requirements before implementation. Enable it only for appropriately configured endpoints/models; do not send provider-specific tools indiscriminately to compatible gateways.

Parse search progress, source annotations, completion/failure events, and available usage. Preserve source references through streaming and final rendering. Other hosted providers need separate adapters and validation.

Normalize both routes into shared UI events and source records while preserving their distinct execution and accounting semantics.

## 6. Make fallback explicit and bounded

| Outcome | Planned handling |
| --- | --- |
| Capability known unsupported or required backend absent | Skip to the next eligible route; show the reason. |
| Explicit unsupported-tool rejection | Mark scoped capability accordingly and fall back when policy permits. |
| Authentication failure | Surface the configuration issue; fall back only if enabled by the selected policy. |
| Rate limit or temporary failure | Respect bounded retry/backoff and provider retry guidance; use the next eligible route when policy permits. |
| Timeout/disconnection after submission with uncertain execution | Surface the uncertain outcome; require explicit user action before another potentially billed attempt. |
| Failure after partial tool activity or output | Preserve the partial attempt and show its status; require explicit restart rather than silently replaying the turn. |
| Cancellation, access restriction, or blocked URL | Stop the affected operation; never use another route to bypass a restriction. |
| Empty or irrelevant results | Return that result to the research loop; another query is a bounded research step, not automatic transport fallback. |

Track attempted routes/backends to prevent cycles and duplicate execution. Never reinterpret an unrelated API error as proof that tools are unsupported. Explain route switches in the UI. A single-route policy never silently changes route.

## 7. Web access boundaries

- Treat retrieved content as untrusted evidence, not instructions or permission to invoke other capabilities.
- Restrict managed fetches to public HTTP(S) resources. Reject embedded credentials and local/private/link-local/reserved destinations. Revalidate every redirect and address resolution, including IPv6, and address DNS-rebinding risks in the transport design.
- Use a dedicated web transport. Never forward model-provider authorization headers, application credentials, or browser cookies to retrieved sites.
- Apply the same destination restrictions to service-backed fetch requests. Where a hosted service's internal navigation cannot be controlled, disclose that limitation and disable that route when it cannot honor the selected access policy.
- Limit content types, redirects, compressed/decompressed sizes, and extraction work. Render retrieved text without executing page scripts or active HTML.
- Keep query transmission and backend credentials visible in settings. Do not attach full conversations or images to search requests unless explicitly required and authorized.

## 8. UI, persistence, and accounting

- Add the per-chat Web access toggle and route preference controls, with clear unavailable/unknown capability states.
- Show searching, reading, retries, route switches, limits, and failures in a collapsible activity view. Continue streaming the final answer without blocking other tabs.
- Render clickable citations and a sources panel using recorded source identifiers and URLs. Validate model-generated citation references against retrieved sources; do not present invented references as verified citations. A valid source link alone does not prove a claim is supported.
- Persist sources, retrieval timestamps, bounded excerpts, tool exchanges, route attempts, and completion/cancellation state in versioned session payloads. Maintain defaults for baseline sessions and keep credentials out of persistence and exports.
- Bound retained tool context and storage. Distinguish a saved excerpt from a complete page or a fresh retrieval.
- Aggregate reported token usage across all model requests in a turn. Show total elapsed time separately from generation timing and tool latency; include reported usage from failed attempts when available. Do not fabricate missing usage or costs.

## 9. Verification and delivery gates

1. Validate the renamed baseline before adding browsing: standard-library tests, offscreen Qt checks, compile checks, launch with temporary application data, and branding inspection.
2. Add mocked protocol tests for streamed/non-streamed tool calls, multiple calls, continuation state, citations, and multi-request usage aggregation.
3. Test route ordering, single-route policies, capability scope, retries, credential failures, uncertain outcomes, partial results, limits, and prevention of fallback loops.
4. Test hostile URLs, redirects, address resolution, oversized/compressed responses, malformed tool arguments, credential isolation, and untrusted page content.
5. Verify persistence/reopening, exports, cancellation, late results, independent tabs, clickable sources, and light/dark rendering with temporary data and offscreen Qt where practical.
6. Keep ordinary tests offline and free of paid requests. Run narrowly scoped live checks only when authorized, with separate results for each endpoint/model/route. Treat documentation, mocks, offscreen validation, and live compatibility as distinct evidence.
7. Refresh documentation and screenshots to match delivered behavior. Run packaging/asset checks and report any untested platforms or providers explicitly.

## Milestones and scope

- **A — Independent baseline:** clean repository, Agentnik identity, MIT ownership, isolated storage, inherited behavior verified.
- **B — Managed research:** bounded tool loop, initial managed backend, sources, persistence, and cancellation.
- **C — Hosted research and routing:** initial hosted adapter, all four policies, visible bounded fallback, shared accounting and citations.
- **D — Release readiness:** remaining protocol adapters in the stated support matrix, security/GUI checks, documentation, and distribution validation.

The first browsing release requires both routes and tested priority/fallback behavior. Full browser automation, JavaScript interaction, login sessions, form submission, purchases, arbitrary code execution, autonomous background tasks, model-provider failover, and research inside System One are deferred.
