# Agentnik v0.6.0

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
