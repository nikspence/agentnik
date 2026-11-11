# Agentnik Features

## Conversations
- Independent **＋ Chat** and **＋ Decision** tabs; each tab keeps its own session, even when tabs share a connection.
- Chat protocols: OpenAI-compatible Chat Completions, Responses, and Anthropic Messages.
- Streaming enabled by default; can be disabled per endpoint.
- Optional reasoning-effort control for models that support it.
- Assistant Markdown renders during streaming and after completion, including wrapped code blocks.
- **Show thinking / Hide thinking** expands reasoning inline in the message card.
- Copy an assistant response (with original Markdown) via the **⧉** icon, including partial text while streaming.
- Prompt edit and resend: the **✎** icon copies a past prompt back into the composer without altering history.

## Composer and UI
- Rounded message cards with one outer conversation scrollbar; cards grow to fit full messages.
- Resizable composer with a remembered height.
- **A− / A+** font size controls (8–32 points), applied immediately and remembered between launches.
- Light/dark/system themes with remembered sidebar visibility.
- Keyboard shortcuts: **Ctrl+Enter** to send, **Ctrl+B** to toggle history, **Ctrl+N** for a new chat.
- Korean localization preview selectable from the language selector.

## Image attachments
- Attach, drag-and-drop, or paste images into chat and decision forms.
- Preview tray in request order; double-click a thumbnail to open the stored copy.
- PNG, JPEG, WebP, and GIF accepted; files are copied into app storage and shared by content hash.
- Drafts and attachments survive a failed or cancelled request.

## Web research (preview)
- Opt-in **Web access** per chat, with four route policies: Provider first, Agentnik first, Provider only, Agentnik only.
- Provider-hosted **OpenAI web_search** on the official Responses endpoint.
- Agentnik-managed tools across native Ollama, Responses, Chat Completions, and Messages.
- Up to five independently credentialed ordered search-backend profiles, including Brave Search, LangSearch, Firecrawl, Exa, Parallel, and Ollama search. Brave, LangSearch, Firecrawl, Exa, and Parallel work independently of the model provider, including local and LiteLLM connections.
- Automatic search fallback: configured providers, then Firecrawl Keyless, then Google scrape after eligible failures; keyless Firecrawl is the default without configured providers.
- Public-only navigation boundaries: URL/DNS/redirect validation, vetted IPs, TLS hostname verification, and rejection of credentials, private/local addresses, and non-80/443 ports.
- Explicit, bounded fallback and retry rules (e.g., 429/503 retry with `Retry-After`, one retry per route).
- Bounded limits for tool rounds, requests, search results, response bytes, and turn duration.
- Collapsible **Research** view recording routes, reasons, retries, searches, page reads, errors, sources, and excerpts.
- Direct-first page retrieval with visible provider fallback for recognized network-filter/TLS/reset failures; strict navigation and private destination checks remain enforced.
- Inline clickable citations from provider annotations and validated managed `[S1]` references.

## System One query builder
- Form with shared state/context, optional JSON-state toggle, image attachments, and multiple named questions.
- Question types: **Yes/No**, **Multiple choice** (2–26 labels), and **Ordered score** (2–10 levels).
- All questions sent in one `/v1/systemone` request; image-only queries get a supplied short state.
- Results preserved with the submitted form and raw response; **Restore query to form** reopens older queries.
- Probability bars, optional pie chart for multiple choice, and confidence shown separately from probability.

## Saved prompts
- **★ Save prompt** for chat drafts and decision forms; star past messages or runs to save them.
- Collapsible, searchable **Prompts** panel per tab type; **Copy to tab** (or double-click) restores a prompt.
- Saved prompts persist across restarts independently of history and survive history clearing.

## History and statistics
- Persistent chat and decision sessions with search, rename, delete, and confirmed **Clear all**.
- Graceful handling of malformed or newer-version records (**Unavailable saved session**) while preserving their payload.
- Automatic saving of drafts and form edits; session export to JSON (no bundled images or credentials).
- Status bar with latest input-context tokens, effective context limit, and cumulative reported tokens.
- Per-response statistics: prompt/generated token counts, elapsed time, prompt-processing and generation rates, and estimated thinking time.
- Shared background-worker limit (16) and bounded public fetch behavior with visible capacity errors.

## Connections and discovery
- Saved connections, environment-discovered settings, and loopback port candidates (Ollama 11434, llama.cpp 9931/8080, FastFlowLM 52625, LiteLLM 4000).
- Environment discovery for OpenAI, Anthropic, LiteLLM, Ollama, llama.cpp, OpenRouter, Groq, Together, Mistral, DeepSeek, xAI, and Bedrock Mantle.
- Manual custom addresses and ports; model-list probes distinguish compatible APIs from open ports.
- Validated connection **Import/Export** in JSON, with duplicate handling and optional explicit key export.
- API keys stored via `keyring` and the OS credential store, with explicit plaintext fallback; history never contains keys.
- Endpoint redirects rejected so credentials are never silently forwarded.
- Scoped research verification per endpoint/protocol/model/connection; explicit rechecks on edits.
- `--litellm-key-file`, `--ollama-key-file`, `--litellm-url`, `--data-dir PATH`, and `AGENTNIK_HOME` options.

## Repositories and coding loop
- **Repositories** registry for local Git repositories or ordinary folders; removing an entry preserves files and history.
- Searchable **＋ Code** picker and independent coding panes with remembered directory snapshots.
- Coding runs use your existing connections: Heavy plans and proposes edits, and can delegate bounded routine analysis to an independent Light model.
- **Run coding task** inspects and changes UTF-8 project files without per-file approval; activity reports applied changes and bounded diff excerpts.
- Bounded project overview, glob, literal grep and time-limited regex tools, numbered file-range reads (up to 10 MB files), and snapshot-bound exact patches.
- Model-maintained task plans with pending/in-progress/completed/blocked steps, a collapsible checklist, and persisted last-reported progress.
- Approved test commands return reported unittest/pytest/Jest/Vitest counts, failure excerpts, and explicit unknown/truncated states.
- Read-before-write enforced; conflicting changes stop the write; cancellation retains drafts and applied changes.
- Regular files, including binary and large files, can be renamed or moved within the project without overwriting, including across filesystems; regular-file deletion and directory creation, rename, and move also proceed without per-operation approval. Directory moves require the same filesystem, a safe no-overwrite rename, and a tree of at most 10,000 permitted entries. Shell commands require approval. Reopening never restarts a run.
- Structured Dulwich Git tools: status, working/staged diffs, recent history, local branches, reviewed staging/unstaging, explicit-file or staged-snapshot commits, and branch creation without switching. Remote Git tools remain planned.
- Optional **Try simulated workflow (no execution)** mode.

## Validation and build tooling
- Offline unit test suite and `compileall` checks covering wire formats, streaming, cancellation, decisions, credentials, attachments, tabs, prompts, fonts, themes, and branding.
- Opt-in live compatibility CLI (`--execute`) and repeatable Windows development archives (`--build`).
- Branding build tooling (`tools/build_branding.py`) and offline screenshot regeneration (`tools/capture_routing.py`, `tools/capture_research.py`).
- Optional live smoke test (`tools/live_smoke.py`) for listing models and authorized inference checks.

## Packaging
- Windows, macOS, and Linux desktop targets from a single Python/Qt codebase (Python 3.11+).
- Windows x64 frozen release (v0.3.1) with bundled Python; PyInstaller build instructions included.
- Installable Python wheel; `pip install .` provides the `agentnik` desktop entry point.
- Default data directories per OS with optional overrides.


## Document Reader — Chat attachment slice

Delivered local preview and attachment of UTF-8 text, Markdown, CSV, JSON, PDF, DOCX and XLSX. Extracted text includes page/paragraph/sheet-row/line references. PDF imports default to text plus rendered page images through existing multimodal image serialization; text-only mode is selectable. Scanned PDFs retain images with an explicit no-text notice. Four documents per prompt; 10 MB files, 48,000 extracted characters, 100 text pages or 12 image pages per PDF. XML archive expansion is bounded; macros, external relationships and formulas never execute. Extracted snapshots and page images persist with drafts/history/prompts, independent of original files. Explicit Send shares contents with the selected endpoint; document text is untrusted evidence. Original binaries, OCR, legacy Office formats, semantic retrieval and Code document tools remain future work. Qualification uses offline generated fixtures and Qt checks, with no live model request.


## Calculator and Data Analysis — local tools

Calculator and Data Analysis tools run locally without Python eval, shell execution, filesystem access, or network calls. Calculator supports numeric arithmetic, pi/e, and common math functions; floating-point results are approximate. Data Analysis accepts explicitly supplied CSV/JSON row objects and reports missing/nonnumeric counts, numeric min/max/sum/mean/median/sample standard deviation, and optional grouping. Bounds: 1,000 rows, 32 columns, 10 groups, a 16 KB data request and 24 KB output, further constrained by shared tool argument/context budgets (Chat defaults to a 4 KB argument budget). Group keys preserve typed JSON values; missing values are excluded from numeric statistics. No formulas, SQL, arbitrary Python, charts or implicit file reads run. Code Heavy has both tools without enabling research; Light has no tools. Chat requires the separate **Calculator / Data tools** opt-in and a tool-capable model. Web access stays independently controlled; enabling both uses the configured Agentnik-managed route and its capability/access checks. Inputs sent by the user are already shared with the selected model; results return to that endpoint and retained tool activity/history. Attached CSV/JSON text can supply data; automatic full-dataset attachment retrieval remains future work.


## Scoped AGENTS.md guidance

Code now loads the selected project root's `AGENTS.md` before the first Heavy request. Ancestor `AGENTS.md` files within that root are loaded lazily when a tool targets a file/directory, including explicit Git path lists. `get_project_instructions(path)` lets Heavy discover rules before planning a change. Files outside the selected root, unrelated subtrees, other instruction filenames and user-global instructions are not automatically read. An instruction file applies to its parent directory and descendants; deeper rules take precedence only within their subtree. Explicit user instructions and Agentnik's fixed permission/security rules retain priority. This is model guidance, not a guarantee that every generated change follows a convention.

Activity reports loaded/removed instruction paths and scopes without copying raw guidance into activity logs. Heavy receives the current scoped guidance with its protocol-specific instructions; Light receives the same loaded scope map as bounded task context while remaining tool-free. Configured credentials are redacted. Automatic guidance reads do not authorize editing those files; the existing read-before-edit rules still apply.

If a tool batch discovers new/changed guidance, inspection tools may continue, but mutations, shell/test commands and delegation are deferred until a subsequent model turn can consider the updated instructions. Loaded scopes are refreshed between rounds. Changes detected before a file operation or during an approval invalidate the operation; the model must reconsider and submit it again. Project file changes retain conflict checks; shell commands and Git mutations require approval. Filesystem writers remain concurrent; these checks are not an OS-level transaction. Shell scope uses the supplied working directory; Agentnik does not parse commands to infer every affected path, so the model is instructed to inspect affected paths first.

Guidance must be regular, unlinked UTF-8 files: up to 8 KB per file, 24 KB total, 16 loaded files, 24 directory levels and 256 discovered scopes, plus the shared run context/time budgets. Missing files are allowed; unsafe, unreadable or oversized guidance fails closed rather than silently truncating rules. New runs reload current files; reopening a saved session does not execute or load guidance by itself. Offline tests cover scope discovery, refresh/removal, path/link/encoding/size rejection, first-request protocol injection, credential redaction, mutation deferral, stale approval invalidation, unchanged shell approval, Light context and run-budget enforcement. Live model instruction adherence remains unqualified.
