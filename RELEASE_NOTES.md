# Agentnik v0.8.3

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.8.1

- **MCP in Chat:** select a configured server, use its tools during a conversation, and reconnect on follow-up requests. Activity shows the tool and outcome, and invalid requests can be returned to the model for correction without executing the batch.
- **MCP operation:** discovery and tool calls in Chat, Code and manual use run without approval, including write-capable tools. Server definitions and arguments are checked before calls; uncertain submitted calls are not automatically replayed. Local stdio framing and MCP content audience handling are more reliable.
- **Research and search:** configure per-chat research limits, including model request and total turn timeouts, and use improved search handling and diagnostics.
- **Connections and documentation:** an optional global relaxed-TLS setting supports TLS-inspecting networks. It weakens server identity verification and takes effect after restart. The README and feature guides were reorganized.

Offline tests use mocked providers and local fixtures. The local Parquet MCP server was exercised separately; no live-model compatibility is implied. Build-host startup evidence is recorded in BUILD-MANIFEST.json. Clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.8.1

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.8.0

- MCP server selections persist per Code session, with improved process cleanup, protocol negotiation, error handling, stream parsing, resource template support and schema validation.
- Parallel subagents can inspect approved file snapshots with bounded read, glob and grep tools. Confirmed model tool-calling rejections are remembered, with an option to forget them.
- Successful managed searches and eligible read-only MCP searches can be reused for 30 minutes, subject to their respective scope and approval checks.

Offline tests use mocked providers and local fixtures; no live model compatibility is implied. Build-host startup evidence is recorded in BUILD-MANIFEST.json. Clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.8.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.7.3

- **MCP servers:** configure local stdio servers and remote HTTPS servers, test connections, inspect discovered tools and make reviewed manual calls. Remote bearer tokens use the operating-system credential store. Local servers can map existing environment variable names without saving their values; local commands and arguments remain plaintext.
- **MCP in Code:** select up to five servers per run. Models can request tools, text resources, text prompts and supported resource templates. Each server has an independent session and connection approval. Approve each operation, or explicitly allow that server's later MCP operations, including writes and data access, for the current run. Shell approvals remain separate.
- **MCP boundaries:** tool inputs use bounded JSON Schema validation; definitions are rechecked before calls. Resource and prompt listings are bounded, and returned content is untrusted. Stateful remote servers retain their session during the run. OAuth, MCP task execution, binary resources, non-text prompt content, advanced URI-template expressions, and stream resumption remain unsupported.
- **Project tools:** move and rename regular files of any size or encoding, delete individual files, and move or rename directories within the project, subject to conflict and no-overwrite checks. Text read and edit capacities have increased.
- **Search handling:** Brave search omits individual results that fail public-address validation while retaining safe hits. A blocked coding search no longer requires discarding earlier sources; further searches in that run remain disabled.

MCP transport was exercised on Windows against Parallel and Microsoft postgres-mcp, including Parallel searches and a PostgreSQL temporary-table workflow. Live model-driven MCP use remains unqualified. Offline tests use mocked providers and local fixtures. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.7.3

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.7.2

- Code can find project files using glob patterns and search text using literal or time-limited regular expressions, with filename filters and case control. Rename and move previously read UTF-8 project files without overwriting existing destinations.
- Project file edits, individual deletions, renames, moves and directory creation no longer pause for per-file approval. Read-before-edit, project path restrictions and conflict checks remain; shell commands and structured Git mutations still require approval.
- Code activity follows new output when scrolled to the bottom and preserves your position when reading earlier output. Sessions retain up to 10,000 entries and 4 million text characters; expanded histories use a newer session format that older Agentnik versions preserve as unavailable.
- Independent requirements, design and readiness reviews can include up to three explicitly approved project evidence files, with source hashes and changed-file checks.
- Direct public page reads accept unverified TLS certificates and hostnames for TLS-inspecting networks. This allows intermediaries to impersonate sites or alter content. Eligible page-fetch fallback uses configured retrieval-capable providers, excluding Firecrawl Keyless; provider API connections retain TLS verification.

The Windows offline suite passed 373 tests, including mocked endpoints and offscreen Qt checks. No live-model qualification was performed for these changes. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.7.2

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.7.1

- Independent document review: request a comprehension, requirements, design or implementation-readiness pass using a configured Light or alternate model. Each pass needs explicit approval of its fixed instructions, document, destination and hashes.
- Each review sends a fresh document-only request without the drafting conversation, prior findings, selected Skills, project guidance or tools. Agentnik discards findings if the document changes before or during review, and cancellation discards late output. Findings are untrusted; the provider may retain its own context.
- Reviews run sequentially, within shared run budgets. Parallel passes, additional evidence files, durable finding dispositions and monitoring for later document changes remain planned.

The full Windows offline suite passed 350 tests, including mocked endpoints and offscreen Qt checks. No live-model qualification was performed for independent review. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.7.1

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.7.0

- Selected Skills retain their confirmed instruction revisions between runs. Changed or missing instructions must be reviewed and reconfirmed before use; changes during a run stop it.
- Light and parallel subagent requests count their full UTF-8 prompts against the shared context budget, including instructions, task and supplied project context.
- The roadmap describes an optional independent design review workflow; this feature is planned, not implemented.

The changes were tested offline with mocked endpoints and offscreen Qt checks. No live-model qualification was performed. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.7.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.6.0

- Parallel coding subagents: Heavy can delegate two or three independent analysis tasks to Light and up to two separately configured alternate models. Child requests share the run limits and cannot execute tools or make changes.
- Approved project snapshots: each child may receive up to three bounded project files. Each file transfer requires individual approval of the displayed text, task, model and destination; rejected or changed files stop the batch. Nested `AGENTS.md` guidance is loaded before delegation.
- Subagent activity and control: results appear as each child finishes, with elapsed time and available token counts. A collapsible view preserves bounded status and findings. Cancel individual children while siblings continue; late output is discarded and identical cancelled tasks cannot be retried in the same run. A provider may continue an already submitted request.
- Skills compatibility: bounded safe YAML frontmatter parsing, supporting-resource discovery, a visible revision history and checks for selected instruction changes during a run.
- The project license is now Apache License 2.0. A use disclaimer is included in the distribution.

The offline suite passed 339 tests. Subagent and Skills behavior was validated with mocked endpoints and offscreen Qt checks; no live-model qualification was performed for these changes. The Windows build-host startup result is recorded in BUILD-MANIFEST.json. Clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.6.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.5.0

- Code discovers repository `AGENTS.md` guidance by directory scope, defers affected proposals when guidance changes, and retains permission and approval checks.
- Code Skills support with explicit selection from repository `.agents/skills` and user `~/.agents/skills` libraries, previews, bounded references and scripts that continue to require command approval.
- Coding sessions retain skill source and instruction-file hashes for the latest 32 real runs.
- Common multiline `SKILL.md` descriptions are supported; this is not full YAML compatibility.

The full offline suite covers 314 tests, including scoped guidance, skill discovery, references, and skill revision validation. Live model adherence to repository guidance and selected Skills remains unqualified. Skills are provided as model instructions and cannot grant tool permissions. See VALIDATION.md for scope and qualification limits.

Windows build-host startup evidence is recorded in BUILD-MANIFEST.json. Clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.5.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.4.0

- Chat Document Reader: attach UTF-8 text, Markdown, CSV, JSON, PDF, DOCX and XLSX with local preview, source references and persistent extracted snapshots. PDFs default to both page images and extracted text for multimodal models; select text-only mode when needed. Scanned PDFs can use page images; OCR is not included. Bounds include four documents per prompt, 10 MB per file and 12 PDF image pages per import.
- Calculator and Data Analysis tools: optional model-requested arithmetic and CSV/JSON summaries in Chat, and built-in Heavy tools in Code. Numeric statistics include missing/nonnumeric counts and optional grouping. Local tools execute no arbitrary code or shell commands; results use approximate float arithmetic and only explicitly supplied data. Web access remains independently controlled.
- Coding task checklists with persistent model-reported progress, a collapsible panel, and no automatic resumption after reopening.
- Focused project overview, numbered file-range reads, approved exact-match patches, and approved test commands with structured unittest/pytest/Jest/Vitest summaries.
- Managed search providers: Brave, LangSearch, Firecrawl, Exa and Parallel, independent credentials, Firecrawl Keyless defaults and eligible fallback to Google scraping. Public URL retrieval can fall back to retrieval-capable provider APIs after recognized network-filter blocks, TLS errors or connection resets; strict public-only navigation disables that external retrieval.
- Configurable per-model coding timeout (300 seconds by default), with shared loop and elapsed-time budgets suitable for slower local models.
- Clearer direct Amazon Bedrock Mantle catalog and inference endpoint handling; LiteLLM connections retain gateway routing.
- Updated feature documentation, Korean controls and offline validation.

The full offline suite covers 300 tests. Calculator, analysis, and multimodal document requests are qualified with generated fixtures and mocked models, not live model runs. Search-provider qualification varies by adapter; see VALIDATION.md. Original document binaries are not retained; extracted snapshots and rendered PDF pages are persisted and sent only when you send the prompt. Automatic full-dataset attachment retrieval, OCR, arbitrary analysis code, remote structured Git tools, MCP and Skills remain future work.

Build-host startup evidence is recorded in BUILD-MANIFEST.json. Clean-machine, full native workflow, macOS/Linux, signing and full bundled-library license review remain open.

## Earlier release: v0.4.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.3.2

- Agentnik-owned coding research with opt-in public documentation reads, bounded link discovery, and visible sources. LiteLLM and other connections use Google HTML search; direct Ollama Cloud can use a separately configured Ollama search key. Public fetch remains usable when Google requires a browser challenge.
- Adjustable coding-loop rounds, requests, tool calls, elapsed time, and context limits shared across Heavy, Light, and research.
- Approved file deletion, directory creation, and bounded shell execution. Commands run with your account permissions, including network and access outside the project; they are not sandboxed.
- Optional System One advice for shell approvals with category badges and reported confidence. Advice requires explicit enablement and a selected compatible Decision endpoint; the user still approves or rejects each command.
- Structured Dulwich Git tools for status, working/staged diffs, history, branches, reviewed staging/unstaging, explicit-file or staged-snapshot commits, and branch creation without switching. Commits bind approval to repository state and preserve later working edits. No Git subprocess, hooks, signing, filters, or remote Git tools are used by these structured operations.
- Compact Chat and Code layouts, named saved prompts, improved model-count placement, Korean approval translations, and a feature-focused README.

Git tools require an existing commit and a repository root with a local `.git` directory. Content filters/LFS, worktrees, in-progress history operations, and remote fetch/push remain outside the supported structured Git slice. Google HTML search availability depends on external page format and access policy. Live-model Git operations and the new shell-advice integration have not been qualified; offline and build-host evidence is recorded in VALIDATION.md and BUILD-MANIFEST.json. Clean-machine, full native workflow, macOS/Linux, signing, and full bundled-library license review remain open.

## Earlier release: v0.3.2

Windows x64 onedir release; extract the complete archive and run `Agentnik/Agentnik.exe`. The build is unsigned. Verify the SHA-256 sidecar.

## Changes since v0.3.1

- Compact Code pane with grouped model selectors and approval controls shown when needed.
- Decision model selection is available; System One safety checks are not yet connected.

## Earlier release: v0.3.1

Windows x64 onedir release. Extract the whole ZIP and launch `Agentnik/Agentnik.exe`, keeping `_internal` alongside it. Verify the SHA-256 sidecar. This build is unsigned.

## Changes since v0.3.0

- Release packaging now checks that every compiled translation catalog is present in the frozen application with identical contents. This prevents a build from silently omitting or altering the Korean catalog.

The catalog packaging check does not establish Korean rendering inside the frozen application. See VALIDATION.md and BUILD-MANIFEST.json for build evidence and remaining validation limits.

## Earlier release: v0.3.0

Windows x64 onedir release. Extract the whole ZIP and launch `Agentnik/Agentnik.exe`, keeping `_internal` alongside it. Verify the SHA-256 sidecar. This build is unsigned.

## Changes since v0.2.0

- Manage local repository or ordinary folder entries, and open independent Code panes with saved working-directory snapshots.
- Run Agentnik's own coding workflow with existing connections and independently selected Heavy and optional Light models. Review and approve each proposed file edit. Shell commands, deletion, directory creation, commits, and pushes are unavailable.
- Added a coding guide and a roadmap for interface localization. Localization, MCP, Skills, and System One safety recommendations remain planned.

Coding has offline protocol, file-operation, and Qt coverage; live coding compatibility has not been established. File contents and delegated context may be sent to the selected model endpoints. See CODING_GUIDE.md for limitations and privacy details.

The Windows build-host startup check does not establish clean-machine, full interactive, credential, TLS, macOS, or Linux compatibility. Signing and a full bundled-library license audit remain pending. See VALIDATION.md and BUILD-MANIFEST.json for evidence.

## Earlier release: v0.2.0

Windows x64 onedir release. Extract the whole ZIP, then launch `Agentnik/Agentnik.exe`; its `_internal` directory must stay beside it. Python is included. Verify the archive against its `.sha256` sidecar. The build is unsigned.

## Changes since v0.1.0

- Managed research across native Ollama, Responses, Chat Completions, and Messages, with protocol-specific tool continuation, thinking/signatures, and correlation IDs.
- Stricter stream lifecycle validation rejects incomplete or conflicting tool calls before execution. Partial research remains auditable without being replayed as successful model history.
- Real Ollama search handles the service's JSON response when mislabeled as HTML at its fixed endpoint, while keeping JSON/schema and public-fetch destination checks.
- Improved cumulative usage accounting with separate cache/reasoning details and sanitized per-request numeric snapshots.
- Safer saved settings and session recovery: malformed/future data is preserved, valid history remains usable, and attachments are retained when unreadable records may reference them.
- Research verification is isolated by opaque connection/account context; credential changes invalidate stale evidence.
- Bounded research worker accumulation, safe pre-request TCP address failover, a separate research-record retention budget, and preserved thinking visibility on completion.
- Explicit opt-in live compatibility CLI and isolated Windows build/archive tooling, with manifests, dependency notices, checksums and readiness-based frozen startup checks.

## Compatibility and scope

Scoped live LiteLLM evidence includes ChatGPT `chatgpt/gpt-6-luna` and Ollama Cloud `ollama-cloud/gpt-oss:20b` streamed chat/tool continuation, a Gemma chat check, and real managed search plus direct page retrieval using `chatgpt/gpt-6-luna`. These results apply to the exact tested aliases/protocols/routes, not all gateway models. Anthropic aliases were listed but unavailable to the tested Mantle account; live Messages compatibility remains unverified. Hosted search remains limited to the official OpenAI Responses endpoint.

See VALIDATION.md and MILESTONE_D_LIVE_RESULTS.md for evidence. BUILD-MANIFEST.json records this artifact's source revision, environment, dependencies and startup result. Startup success does not establish every dialog, clipboard, credential-store or TLS/provider workflow. Clean-machine and macOS/Linux validation, signing, and a full bundled-library license audit remain pending; installed dependency notices and Python's license are included.

No API keys, personal history, or runtime settings were included in v0.2.0. Existing Agentnik data remains in its normal independent application data directory.
