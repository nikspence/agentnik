# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.svg#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.svg#gh-dark-mode-only)

**Code, chat, and make structured decisions with your choice of local or cloud models.** Agentnik is a Python/Qt desktop application that brings your connections, conversations, projects, and research into one workspace. Use Ollama, LiteLLM gateways, and compatible provider endpoints; choose different models for different jobs.

See [DISCLAIMER.md](DISCLAIMER.md) for responsibility and use information.

## Code: a coding agent for your models

Register a local repository or ordinary folder in **Repositories**, then choose it from **＋ Code**. Each coding pane keeps its own working directory snapshot, task, model assignments, and activity. Removing a repository entry preserves its files and history.

Agentnik runs its own coding loop using your configured connections and models, with no Codex runtime dependency. Select models from the available list or enter an alias manually, including aliases exposed by LiteLLM.

- **Heavy and Light delegation:** Heavy leads the task, inspects the project, and proposes changes. Enable **Allow light model delegation** to let it delegate bounded routine analysis to a separately selected Light model within the same workflow. The roles can use different connections and providers. Heavy can also request two or three concurrent analysis tasks using Light and up to two optional alternate subagent models; these receive supplied context and have no tools. Each requested project file is reviewed and approved separately before its text is sent to the Light model. Activity shows results as they finish, with elapsed time and reported token usage.
The Code pane shows a collapsible Subagents view with the latest status and bounded findings for up to 32 children in the current real coding run. Select an active child and choose **Cancel subagent** to stop waiting for that child while its siblings continue. Heavy receives a cancelled result without the child’s late output. An identical task and file scope cannot be retried or reassigned during the same run; changed wording still depends on model compliance. Cancelled and interrupted children remain visible; reopening never resumes work. Starting a new real run clears the prior view, while simulation preserves it. Cancellation stops waiting and scheduling; a request already submitted to a model endpoint may continue remotely.

- **Independent document review:** ask Heavy for a comprehension, requirements, design, or implementation-readiness review with Light delegation enabled. Each review uses a fixed role and one project text file (up to 8 KB) with a configured Light or alternate model. Requirements, design and readiness reviews can include up to three explicitly approved project evidence files (8 KB each). The approval view shows the complete instructions, document and evidence, destination, and hashes. Approve each request or reject it to skip. Reviews run one at a time; each fresh request excludes the drafting conversation, earlier findings, selected Skills and project guidance, and the reviewer has no tools. Findings, failures and cancellation appear in Subagents and activity. If the document or evidence changes during a review, its findings are discarded. Findings are untrusted suggestions; a provider may retain its own context, and later file changes are not monitored.

- **File and shell tools:** inspect and change UTF-8 project files, rename or move regular files of any size or encoding, delete individual files of any size or encoding, and create, rename, or move directories without per-file approval during a coding run. Moves stay within the project and never overwrite existing destinations. File moves support cross-filesystem copies; directory moves require the same filesystem and a safe no-overwrite rename. Activity records the changes. Content edits require a prior read; source metadata changes stop a move or deletion. Shell commands require approval.
- **Focused project tools:** get a bounded project overview, find filenames with glob patterns, search UTF-8 files for literal text or regular expressions with a glob filter and optional case-insensitivity, read numbered line ranges in files up to 10 MB, and apply exact-match patches to text already read. Search results identify incomplete scans, including regex timeouts. Patches preserve surrounding content and check the file version before applying.
- **Repository guidance:** automatically load root `AGENTS.md` before a coding run and nested rules when tools target their directories. Activity identifies loaded files and scopes. Deeper guidance applies within its subtree; user instructions and approval/security rules take priority. Newly discovered rules defer proposed mutations until the model can review them.
- **Repository Skills:** select up to five repository or user skills from `.agents/skills/<name>/SKILL.md` in the Code pane. User skills come from `~/.agents/skills`; matching names remain separate. Preview instructions before selecting them. Selected instructions are sent to the model when a run starts, with their SHA-256 revision shown in activity and the Skill history dialog; bounded text references can be read on demand. Scripts still require command approval. Skill frontmatter uses bounded safe YAML parsing. If a selected instruction file changes or disappears, review and reconfirm it in Skills before running; changes during a run stop the run. Older sessions acquire selection hashes when their Skills selection is confirmed.
- **MCP server preview:** use **MCP servers** to save local stdio commands or remote HTTPS server URLs and explicitly test them. Remote tests use a bearer token stored in the operating-system credential store, negotiate supported Streamable HTTP protocol versions (2025-03-26, 2025-06-18, or 2025-11-25), complete initialization, and show descriptions and input schemas for up to five pages or 100 tools; local tests keep a stdio session open and discover tools. You can manually call a discovered local or remote tool after reviewing its destination, description, schema, and JSON arguments; Agentnik checks that its definition has not changed before the call and never retries an uncertain call. Tools requiring MCP task execution cannot be called yet. Arguments are checked against a bounded JSON Schema subset, including local `$defs` or `definitions` references and limited `anyOf`, `oneOf`, and `allOf` combinations. Recursive or external references and unsupported features are rejected. In Code, select up to five enabled local or remote servers for a run; the model can request discovery and tool calls. Selections are remembered per Code session without starting servers when reopened. If a saved server configuration changes or becomes unavailable, reselect or remove it before running. Approve each operation individually, or choose **Allow this MCP server for this run** to permit that server’s later MCP operations without further prompts, including writes and data access. The choice ends with the run and does not approve other servers or shell commands. When multiple servers are selected, each request names its server and uses that server’s independent session. Tool metadata and results are untrusted and are sent to the selected model. For servers that advertise resources, Code can list up to five resource pages or 100 resources and read a listed text resource, subject to the same per-operation or per-server run approval. Resource listings are also capped at 200 KB of metadata and report when more may be available. Code can also list and retrieve text-only MCP prompts, subject to the same approval choices; prompt messages remain untrusted tool results. Code can also list resource templates and read text using scalar URI-template substitutions, including multiple variables and `/`, `?`, and `&` expressions; other URI-template forms are shown as unsupported. Variables may be supplied as strings; omitted or null variables are undefined and excluded from expansion. Each listing and expanded URI read follows the same approval choices. Binary resources and non-text prompt content are not yet supported. Local commands and arguments are stored as plaintext; do not put credentials in them. For local servers, **Environment names** accepts a JSON mapping such as `{"SERVER_TOKEN":"MY_EXISTING_TOKEN"}`: Agentnik reads the value of `MY_EXISTING_TOKEN` from its own environment and passes it to the server as `SERVER_TOKEN`. Only names are saved. Restart Agentnik after changing its environment; mapped values are captured for each coding run and treated as sensitive, and responses containing them are blocked. Local servers also inherit Agentnik’s environment. Local sessions answer bounded server-initiated ping requests and reject unsupported server requests. They remain open while the server is selected, allowing connection-oriented tools to work; closing the dialog or selecting another server ends the session. On Windows, Agentnik assigns the server process to a job object and closes the job on shutdown to terminate contained children. Processes started before assignment or allowed to break away may escape; other platforms currently terminate only the direct process. On Windows, `npx` uses the installed Node.js npm CLI. Coding runs keep remote HTTP sessions open across approved calls when the server issues a session ID; tool definitions are checked again before each call, and Agentnik attempts to close the session at the end. Manual remote calls use separate sessions. HTTP stream resumption, server-initiated HTTP requests, and unsolicited server notifications are not supported. OAuth is not yet supported.
- **Task plans:** Heavy can maintain a checklist with pending, in-progress, completed, and blocked steps. A collapsible panel shows progress and retains unfinished plans after cancellation or reopening. A new coding run starts a fresh plan.
- **Structured test results:** submit an approved test command and get reported counts and failure excerpts from unittest, pytest, Jest, or Vitest output. Unrecognized or truncated output stays explicitly uncertain; tests are never launched just by opening a project.
- **Structured Git tools:** inspect tracked status, working and staged file diffs, recent commits, and local branches without shell commands. Stage or unstage explicit files, create a branch without switching, and commit selected working files or the reviewed staged snapshot. Each mutation requires approval; commits display the full diff, message, identity, and parent. Unstaging and staged commits preserve working-file edits. This local preview requires an existing repository with a commit and configured Git identity; hooks and signing are disabled. Remote Git tools remain planned.
- **Research while coding:** enable **Allow web research** to look up APIs, read documentation, and follow discovered public documentation links as part of the task. Sources and excerpts appear in the run activity and Sources view.
- **Adjustable run limits:** the **Limits…** dialog controls loop rounds, model requests, tool calls, total elapsed time, model call timeout, and continuation context. Model calls default to 300 seconds; new runs default to 900 seconds overall. Heavy, Light, and research share the run budget.
- **Compact workflow controls:** Run, Simulate, and Cancel sit above a collapsible Models panel containing Heavy, Light, and Decision assignments. Approval controls appear when a proposal needs review. Optionally include the bounded previous task and answer in a follow-up.
- **Code activity:** output follows the bottom while you are reading the latest activity. Scroll up to pause following and return to the bottom to resume. Up to 10,000 entries and 4 million text characters are retained per coding session; oldest entries are trimmed when either limit is reached.
- **Cancellation and persistence:** cancel retains your draft and project changes already applied. Reopening a saved coding session never restarts execution. Simulate lets you explore the workflow without executing a real coding task.

Approved shell commands run with your operating-system account's permissions, including network access and paths outside the project. They can run Git commands; the executor is not an operating-system sandbox. File contents and delegated context are sent to the selected model endpoints.

### Optional Decision advice for shell approvals

Choose a compatible System One Decision connection and model, then enable **Check shell approvals with Decision model** in Models. Agentnik sends the exact proposed command, working directory, shell, and environment variable names (excluding their values) to that endpoint.

The approval view shows **SAFE**, **WARNING**, **RISKY**, **PRIVACY**, or **DANGER**, with confidence when supplied. Failed, invalid, or timed-out checks show **UNKNOWN**. The category guide explains the recommendation; you still approve or reject every command. Advice currently covers shell commands, and compatibility with a real decision model remains unverified for this integration.

See the [coding guide](CODING_GUIDE.md) for setup and operation, and the [coding backend plan](CODING_BACKEND_PLAN.md) for remaining work.

## Chat: independent conversations with local and cloud models

Open **＋ Chat** to start an independent session. Tabs remain separate even when they share a connection. Agentnik supports OpenAI-compatible **Responses**, **Chat Completions**, and **Anthropic Messages**, plus native Ollama chat. Actual model capabilities depend on the endpoint.

- Stream replies with Markdown and wrapped code blocks; turn streaming off when an endpoint requires it.
- Expand or hide inline thinking, and select reasoning effort for models that support it. Thinking uses smaller, subdued text to distinguish it from the response.
- Copy an assistant response with its original Markdown using the **⧉** icon, including text received so far during streaming.
- Edit and resend a previous prompt with **✎**, restoring its text and images to the composer while preserving earlier history.
- Attach multiple PNG, JPEG, WebP, or GIF images through the file picker, drag and drop, or clipboard paste. Preview them in request order and double-click to open a stored copy. Model image support varies.
- **Document Reader:** attach text/Markdown/CSV/JSON, PDF, DOCX, and XLSX with local preview. PDFs default to page images **and** extracted text for multimodal models; turn off page images for text-only models. Preview/remove document chips, drop documents into the composer, and restore them when editing a sent prompt. Extracted snapshots persist with drafts, history, saved prompts, and JSON exports. Original document binaries are not retained. Files stay local until Send. Limits: four documents per prompt, 10 MB each, 48,000 extracted characters, 100 PDF text pages or 12 image pages per import. Scanned PDFs work through page images; OCR and spreadsheet formula evaluation are not included.
- **Calculator / Data tools:** opt into model-requested local arithmetic and bounded CSV/JSON statistics without enabling Web access. Numeric summaries include missing values and optional groups. Code Heavy also has these tools. No arbitrary code executes; results use approximate floating-point arithmetic.
- Resize the composer; Agentnik remembers its height. Drafts and attachments remain available after failed or cancelled requests.
- Keep Web access controls beside session export at the bottom of the pane, with run status in the status bar.

## Research: web access for models that need it

Agentnik-managed research gives tool-capable models access to search and public page retrieval even when they have no built-in browsing service. The selected model requests a tool; Agentnik retrieves bounded evidence and returns it to the model. Research is opt-in, and endpoint/protocol/model compatibility must be configured rather than inferred from a model listing.

**Chat research** supports managed tools across native Ollama, Responses, Chat Completions, and Messages. Compatible models on the official OpenAI Responses endpoint can also use provider-hosted web search. Choose **Provider first**, **Agentnik first**, **Provider only**, or **Agentnik only**; eligible fallback is visible in the activity view and retains your model and connection. Chat search settings support up to five ordered, independently credentialed backend profiles.

**Managed search providers:** configure **Brave Search**, **LangSearch**, **Firecrawl**, **Exa**, or **Parallel** in **Search settings…** (Code), or **Web settings… → Manage ordered search backends…** (Chat). Choose a provider, enter its separate API key when required, and order your profiles. **Firecrawl (keyless)** requires no account key. These providers work across supported model connections, including local models and LiteLLM, when the model can call research tools. Exa uses `auto` search with highlights; Parallel uses `basic` search with bounded excerpts. Provider search/content charges may apply. Keys use the OS credential store with explicit plaintext fallback. Alternatively set `BRAVE_SEARCH_API_KEY`, `LANGSEARCH_API_KEY`, `FIRECRAWL_API_KEY`, `EXA_API_KEY`, or `PARALLEL_API_KEY`; environment profiles follow saved profiles within the five-profile limit. See the [search provider guide](SEARCH_PROVIDERS.md) for setup, API scope, validation, and Exa/Parallel search modes.

**Coding research** uses your configured search profiles and direct public page reads. Ollama search profiles remain eligible only for direct Ollama Cloud coding connections; an Ollama model through LiteLLM uses the other managed providers. Configured search providers run first, followed by **Firecrawl Keyless**, then **Google scrape** after eligible failures. With no provider configured, Firecrawl Keyless is the default. Fallback is visible in research activity and stops on access restrictions, timeouts, cancellation, or uncertain outcomes. Google can still be rate-limited or challenged. Direct page retrieval can read known URLs without a search key.

Public page retrieval requires no search key and can read a known documentation URL directly. To work with TLS-inspecting networks, direct page reads do not verify TLS certificates or hostnames. A network intermediary can therefore impersonate a site or modify its content; treat retrieved text as untrusted. URL, DNS, and redirect checks reject private/local destinations, embedded credentials, and ports outside 80/443. Direct page requests send no provider credentials, search keys, cookies, or proxies. Search and retrieval provider API connections still verify TLS. Strict public-only navigation disables external search while retaining permitted public page reads.

If a direct page read is recognized as a network-filter block (such as a Zscaler block page), or encounters an eligible connection, TLS, or HTTP failure, Agentnik can ask a configured retrieval-capable provider to read the public URL. Keyed Firecrawl, Exa, Parallel, and eligible Ollama profiles support this; Firecrawl Keyless is not used for page-fetch fallback. The URL is disclosed to that service, provider navigation is external, and charges may apply. Activity identifies the fallback and returned source. Private destinations/redirects, generic site access denials, timeouts, cancellation, and strict public-only navigation do not use this fallback. No browser login, cookies, or local proxy credentials are forwarded.

Brave search omits individual results that fail public-address checks while retaining safe results. If a search is blocked by an access restriction during a coding run, Agentnik stops further searches for that run and lets the model continue with existing sources; activity identifies HTTP status when available.

Research activity exposes searches, page reads, route/backend choices, recovery, errors, sources, and excerpts. Chat supports clickable provider citations and validated managed `[S1]` references. Retrieved text and search results are untrusted evidence; a source link alone does not establish that a claim is correct. Requests, tool rounds, bytes, context, retries, and time are bounded. Partial or ambiguous failures do not silently replay inference.

Search queries can contain information derived from your task. Inference credentials are not reused as search credentials; configured search keys use the credential store with explicit plaintext fallback. Research remains a preview with compatibility recorded for specific models and routes in [VALIDATION.md](VALIDATION.md).

## Decision: structured System One queries

Open **＋ Decision** to use Ollama's structured `/v1/systemone` API with a compatible decision model. Build one request containing shared state/context, optional JSON state, multiple images, and multiple named questions:

| Question | Configuration and display |
| --- | --- |
| Yes / No | Probability of yes and no |
| Multiple choice | 2–26 unique labels with descriptions; probability bars and an optional pie chart |
| Ordered score | 2–10 descriptions ordered from lowest to highest; returned scoring legend when available |

Images can be attached, dropped, or pasted into the state field. Image-only queries receive a short supplied state. Completed runs preserve the submitted form and raw response; **Restore query to form** makes an older query editable. Confidence is displayed separately from probability. Selecting a Decision tab requires a compatible decision model and endpoint.

## Prompts, history, and everyday controls

- Save chat drafts or complete decision forms with **Save prompt**, or star a past message/run. Give the prompt a name or accept the default. Search the collapsible Prompts panel and restore a prompt with **Copy to tab** or a double-click. Saved prompts survive restarts and history clearing.
- Search, rename, delete, and export saved sessions. Clear all history requires confirmation. Drafts and form edits save automatically; malformed or newer-version records remain preserved as unavailable sessions.
- Images are copied into application storage and shared by content hash, so history survives moved originals. JSON session exports include local attachment paths rather than bundled image files or credentials.
- View reported input/output tokens, current input context, effective context limit when known, elapsed time, and available processing/generation rates. Missing measurements remain unknown; thinking time is an estimate when available.
- Choose light, dark, or system theme; adjust font size from 8–32 points with **A− / A+**. Sidebar visibility and composer sizing are remembered.
- Use **Ctrl+Enter** to send, **Ctrl+B** to toggle history, and **Ctrl+N** for a new chat.
- Select the **Korean preview** and restart to try translated controls. English remains the fallback; other planned languages and full Korean coverage are still in progress.

Background requests keep the interface responsive and tabs independent. Cancellation stops accepting results and scheduling more work; remote processing or billing may continue until the server stops. A shared worker limit bounds background work.

## Connections and local data

Use saved connections, environment discovery, or custom URLs and ports. Models load automatically and can be refreshed; manual aliases work when model listing is unavailable. Import and export validated connection JSON with duplicate handling and an explicit choice to include keys.

Environment discovery recognizes OpenAI, Anthropic, LiteLLM, Ollama, llama.cpp, OpenRouter, Groq, Together, Mistral, DeepSeek, xAI, and Bedrock Mantle settings. Mantle uses bearer tokens. Local candidates include Ollama (11434), llama.cpp (9931/8080), FastFlowLM (52625), and LiteLLM (4000). Environment wildcard hosts normalize from `0.0.0.0` to `127.0.0.1`, and matching environment/probed connections merge. Discovery lists candidates without issuing inference requests.

For **direct Bedrock Mantle**, configure the inference base URL and protocol from the model card's **Programmatic Access** table. Depending on the model, OpenAI-compatible inference uses `/v1` or `/openai/v1`; Messages uses its documented base such as `/anthropic/v1` (the complete `/anthropic/v1/messages` URL is accepted too). Agentnik preserves that route and lists models separately at the same origin's `/v1/models`, using bearer authentication for discovery even when inference uses the Messages protocol. The connection editor displays both URLs. A catalog entry does not establish route compatibility or account access; save separate connections for models requiring different routes. Agentnik does not guess from the model name or retry inference on another route. LiteLLM connections continue using their configured gateway URLs. See [AWS model discovery](https://docs.aws.amazon.com/bedrock/latest/userguide/models-get-info.html), [Chat Completions routing](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html), and [Messages routing](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html).

API keys use `keyring` and the OS credential store, with explicit plaintext fallback. Keys are excluded from session history and ordinary exports. Endpoint redirects are rejected to prevent silent credential forwarding. Capability verification is scoped to the connection, endpoint, protocol, and model; listing a model does not prove tool or decision compatibility.

Sessions use local SQLite storage. Default data directories are `%LOCALAPPDATA%\Agentnik` on Windows, `~/Library/Application Support/Agentnik` on macOS, and `$XDG_DATA_HOME/agentnik` (or `~/.local/share/agentnik`) on Linux. Override with `--data-dir PATH` or `AGENTNIK_HOME`.

## Screenshots

![Agentnik light theme](assets/agentnik-light-welcome.png)
![Agentnik dark theme](assets/agentnik-dark-welcome.png)

These welcome screens were rendered offline with temporary data. Research screenshots below use simulated responses.

![Hosted research with inline citations](assets/agentnik-hosted-dark.png)
![Visible hosted-to-managed fallback](assets/agentnik-fallback-light.png)

## Install and launch

Use Python 3.11 or newer with matching Qt wheels for your OS and architecture. A virtual environment is recommended for dependency isolation, but is optional.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe agentnik.py
```

After installation, `./start.ps1` opens the desktop app without leaving a console window. Run the Python command above when troubleshooting so startup errors remain visible.

To use your existing Python installation directly instead:

```powershell
python -m pip install -r requirements.txt
python agentnik.py
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python agentnik.py
```

Alternatively, `python -m pip install .` installs the `agentnik` desktop entry point. Linux still requires the system libraries used by Qt's platform plugin; the exact packages depend on the distribution.

Optional key files can be supplied with `--litellm-key-file PATH` and `--ollama-key-file PATH`; use `--litellm-url URL` for a custom LiteLLM endpoint. Keys are read into the process environment and are saved only when you explicitly save a connection. Do not commit key files.

## Development and roadmap

See [DEVELOPMENT_VALIDATION.md](DEVELOPMENT_VALIDATION.md) for offline checks, opt-in live compatibility tools, and repeatable builds; [VALIDATION.md](VALIDATION.md) records evidence and limitations. Ordinary tests use temporary storage and do not issue live inference. Windows source and frozen startup checks are recorded; macOS/Linux native validation remains outstanding.

The [project plan](AGENTNIK_PLAN.md) tracks coding hardening, compatibility, localization, and distribution. MCP server discovery, manually reviewed calls, and model-requested local and remote calls in Code are available in preview. Explicit repository and user Skills are available in Code. Branding and offline screenshot tools live in `tools/`; Pillow is needed only to rebuild branding assets.

## Packaging

The Windows x64 release is **v0.7.3**. Extract the complete `Agentnik-v0.7.3-windows-x64.zip` archive and run `Agentnik/Agentnik.exe`; keep its `_internal` folder beside it. Python is bundled. See [release notes](RELEASE_NOTES.md) and the bundled `BUILD-MANIFEST.json` for changes and build evidence. The build is unsigned. Research remains a preview with scoped live compatibility results; full native workflow, clean-machine, and macOS/Linux validation remain pending. Earlier release tags and archives are preserved.

The Python wheel has been built and installed locally; see [validation results](VALIDATION.md). To build a wheel without resolving runtime dependencies:

```powershell
python -m pip wheel . --no-deps --wheel-dir dist
```

Build and test on each target OS; a Windows build does not produce a macOS or Linux application. For an initial distributable, install PyInstaller as a build-only dependency and run:

```powershell
python -m PyInstaller --noconfirm --windowed --name Agentnik --icon agentnik/assets/agentnik-icon.ico --add-data "agentnik/assets:agentnik/assets" --add-data "agentnik/translations:agentnik/translations" --collect-submodules keyring.backends agentnik.py
```

Verify credential storage, TLS access, file dialogs, clipboard images, history, and Qt platform plugins in each packaged build. Signed installers and automatic updates are future distribution work.

## License

Apache-2.0. Copyright 2026 Nikolaus Spence. Sole author: Nikolaus Spence.
