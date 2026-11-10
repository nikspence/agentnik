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
- **Run coding task** inspects project files and proposes UTF-8 file edits; review the full diff, then approve or reject each edit.
- Read-before-write enforced; conflicting changes stop the write; cancellation retains drafts and applied approvals.
- Approved single-file deletion, directory creation, and bounded shell commands; reopening never restarts a run.
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
