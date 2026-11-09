# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.svg#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.svg#gh-dark-mode-only)

**Code, chat, and make structured decisions with your choice of local or cloud models.** Agentnik is a Python/Qt desktop application that brings your connections, conversations, projects, and research into one workspace. Use Ollama, LiteLLM gateways, and compatible provider endpoints; choose different models for different jobs.

## Code: a coding agent for your models

Register a local repository or ordinary folder in **Repositories**, then choose it from **＋ Code**. Each coding pane keeps its own working directory snapshot, task, model assignments, and activity. Removing a repository entry preserves its files and history.

Agentnik runs its own coding loop using your configured connections and models, with no Codex runtime dependency. Select models from the available list or enter an alias manually, including aliases exposed by LiteLLM.

- **Heavy and Light delegation:** Heavy leads the task, inspects the project, and proposes changes. Enable **Allow light model delegation** to let it delegate bounded routine analysis to a separately selected Light model within the same workflow. The roles can use different connections and providers.
- **File and shell tools:** inspect project files, propose UTF-8 edits, delete individual files, create directories, and run shell commands. Review the diff or exact operation and approve or reject each proposed change or command. Existing files must be read before modification; conflicting changes stop the operation.
- **Structured Git tools:** inspect tracked status, working and staged file diffs, recent commits, and local branches without shell commands. Stage or unstage explicit files, create a branch without switching, and commit selected working files or the reviewed staged snapshot. Each mutation requires approval; commits display the full diff, message, identity, and parent. Unstaging and staged commits preserve working-file edits. This local preview requires an existing repository with a commit and configured Git identity; hooks and signing are disabled. Remote Git tools remain planned.
- **Research while coding:** enable **Allow web research** to look up APIs, read documentation, and follow discovered public documentation links as part of the task. Sources and excerpts appear in the run activity and Sources view.
- **Adjustable run limits:** the **Limits…** dialog controls loop rounds, model requests, tool calls, elapsed time, and continuation context. Heavy, Light, and research share the run budget.
- **Compact workflow controls:** Run, Simulate, and Cancel sit above a collapsible Models panel containing Heavy, Light, and Decision assignments. Approval controls appear when a proposal needs review. Optionally include the bounded previous task and answer in a follow-up.
- **Cancellation and persistence:** cancel retains your draft and already approved changes. Reopening a saved coding session never restarts execution. Simulate lets you explore the workflow without executing a real coding task.

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
- Resize the composer; Agentnik remembers its height. Drafts and attachments remain available after failed or cancelled requests.
- Keep Web access controls beside session export at the bottom of the pane, with run status in the status bar.

## Research: web access for models that need it

Agentnik-managed research gives tool-capable models access to search and public page retrieval even when they have no built-in browsing service. The selected model requests a tool; Agentnik retrieves bounded evidence and returns it to the model. Research is opt-in, and endpoint/protocol/model compatibility must be configured rather than inferred from a model listing.

**Chat research** supports managed tools across native Ollama, Responses, Chat Completions, and Messages. Compatible models on the official OpenAI Responses endpoint can also use provider-hosted web search. Choose **Provider first**, **Agentnik first**, **Provider only**, or **Agentnik only**; eligible fallback is visible in the activity view and retains your model and connection. Chat search settings support up to five ordered, independently credentialed backend profiles.

**Coding research** uses Agentnik-managed Google HTML search and public page reads for LiteLLM and other connections. Direct Ollama Cloud can use a separately configured Ollama search key; using an Ollama model through LiteLLM does not select that direct-cloud route. Google HTML search needs no search API key, but can fail when Google requires a browser challenge or changes its page format. The coding loop can continue public page retrieval when Google search becomes unavailable.

Public page retrieval requires no search key and can read a known documentation URL directly. It extracts inert text and bounded same-host links for further reading; it does not execute JavaScript. URL, DNS, and redirect checks reject private/local destinations, embedded credentials, and ports outside 80/443. Page requests send no provider credentials, search keys, cookies, or proxies. Some sites are consequently unavailable. Strict public-only navigation disables external search while retaining permitted public page reads.

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

The [project plan](AGENTNIK_PLAN.md) tracks coding hardening, compatibility, localization, and distribution. MCP servers and reusable Skills are planned extensions. Branding and offline screenshot tools live in `tools/`; Pillow is needed only to rebuild branding assets.

## Packaging

The Windows x64 release is **v0.4.0**. Extract the complete `Agentnik-v0.4.0-windows-x64.zip` archive and run `Agentnik/Agentnik.exe`; keep its `_internal` folder beside it. Python is bundled. See [release notes](RELEASE_NOTES.md) and the bundled `BUILD-MANIFEST.json` for changes and build evidence. The build is unsigned. Research remains a preview with scoped live compatibility results; full native workflow, clean-machine, and macOS/Linux validation remain pending. Earlier release tags and archives are preserved.

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

MIT. Copyright (c) 2026 Nikolaus Spence. Author: Nikolaus Spence.
