# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.svg#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.svg#gh-dark-mode-only)

A Python/Qt desktop client for LLM conversations and Ollama System One decisions. The initial desktop targets are Windows, macOS, and Linux.

## Screenshots

![Agentnik light theme](assets/agentnik-light-welcome.png)
![Agentnik dark theme](assets/agentnik-dark-welcome.png)

These welcome screens were rendered offline with temporary data.

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

## Project status

Milestone A establishes the independent Agentnik baseline. Chat, structured decisions, saved prompts, attachments, history, themes, and connection management are implemented. Bounded web research is planned in `AGENTNIK_PLAN.md`; web tools, citations, and route fallback are not implemented yet.

## Conversations

Use **＋ Chat** or **＋ Decision** to select a connection and open a session. Tabs are independent, including tabs that use the same connection. Changing the connection selector opens a new session. Models load automatically when a tab opens; use the refresh icon to reload them. A manually entered model works even when listing models is unavailable. New manually created connections default to Responses; discovered and saved connections retain their configured protocol.

Chat supports OpenAI-compatible Chat Completions, Responses, and Anthropic Messages. Streaming is enabled by default and can be turned off for endpoints that do not support it. Reasoning effort is optional and must be supported by the selected model. Unsupported parameters produce a visible endpoint error rather than a silent retry that might duplicate a billed request. Tool execution is not part of this release.

Chat uses rounded message cards: your prompts sit to the right and assistant replies to the left. Each card grows to hold the complete message, with one outer scrollbar for the conversation. Assistant Markdown renders during streaming as well as after completion, including wrapped code blocks. **Show thinking / Hide thinking** expands reasoning inline in the same card; streamed reasoning is initially visible and respects your toggle choice.

The composer starts at a compact height. Drag the divider above it to resize it; Agentnik remembers the chosen height. **A− / A+**, beside the **Theme** dropdown, decrease or increase the application's font size from 8 to 32 points. Font changes apply immediately to existing conversations, editors, and controls, and are remembered between launches. Hover over either font button to see the current size.

The toolbar, welcome screen, and window icon use the robot mark. The lowercase **agentnik** wordmark uses dark/light `agent` lettering and red `nik` lettering. Themes use matching red interface accents. Packaged SVGs contain paths, with transparent PNG fallbacks and a Windows ICO. `assets/robot.svg` is the reusable robot source; `tools/build_branding.py` builds the wordmarks using PySide6 and Pillow. Pillow is a build-only dependency. Generated assets require no installed font at runtime.

Select several images with **Attach images**, drop files onto the attachment area or composer, or paste an image into the composer. The attachment tray previews images in request order. Double-click a thumbnail to open its stored copy. PNG, JPEG, WebP, and GIF are accepted by the app; actual model/provider format support varies. **Ctrl+Enter** sends the prompt. The draft and attachments remain available if the request fails or is cancelled.

**Cancel** immediately stops accepting results for that request and releases the tab. Cancellation does not guarantee that the server stops computing or billing; a blocked transport worker can remain alive until its network timeout. Other tabs stay usable.

## System One query builder

Decision tabs use a form with shared state/context, an optional JSON-state toggle, images, and multiple named questions. Drop image files or paste clipboard images directly into the state field to add them to the attachment tray. Each question has instructions and one of three types:

- **Yes / No**: no choices required; displays the probability of yes and no.
- **Multiple choice**: 2–26 unique labels with descriptions.
- **Ordered score**: 2–10 descriptions entered from lowest to highest. Labels are not sent for this type.

All questions are sent in one `/v1/systemone` request. Images are encoded as bare base64, independently of the chat formats. For an image-only query, Agentnik supplies a short state describing the attached images because System One requires nonempty state. The endpoint must run a compatible decision model; ordinary chat models do not become decision models by selecting this tab.

Every completed run is preserved with its submitted form and raw response. **Restore query to form** makes an older query editable without deleting newer runs. Returned probabilities appear as horizontal bars. Multiple-choice results also offer a button to switch to a pie chart when the returned values form a probability distribution. Scoring levels use the model's returned legend when available. Confidence is shown separately from probability.

## Prompts

Use **☆ Save prompt** beside the composer or decision form to save the current draft. Star a past chat message or decision run to save its submitted prompt. The collapsible **Prompts** panel lists saved prompts for the active tab's type; search covers chat text or decision state, questions, and choice descriptions. Select a prompt and choose **Copy to tab**, or double-click it, to restore it to the active tab. If that tab already has a different draft, Agentnik asks before replacing it. Copying does not send a request or change the tab's connection or model.

Saved chat prompts include text and images. Saved decision prompts include the state, JSON mode, images, and ordered questions and criteria. They persist across restarts independently of conversation history; clearing history does not remove them. Images remain stored while any saved prompt or session references them. Click a filled star or use **Remove** in the panel to remove a saved prompt. The panel's visibility is remembered.

## History and statistics

The collapsible sidebar contains persistent chat and decision sessions. It supports search, rename, delete, and **Clear all** with confirmation. Closing a tab keeps its history. Deleting history closes the affected tabs and removes images that are no longer referenced by another saved session. Saved connections remain available. **Ctrl+B** toggles history; **Ctrl+N** opens a new chat.

Images are copied into application storage and shared by content hash. History stays usable when original image files move. Drafts and decision form edits are saved automatically. Session export produces JSON containing messages, submitted forms, results, and local attachment paths; it does not bundle image files or credentials.

The bottom status bar shows the active session's latest reported input-context token count, effective context limit when known, and cumulative reported input/output tokens. Local Ollama's loaded-model metadata is queried for its effective context length after a chat response. Other connections can supply a limit in the connection editor; unknown limits display **—**. This is not a tokenizer estimate or a claim that the model's entire advertised window is configured on the server. For native Ollama chat, a configured limit is also sent as `options.num_ctx`.

Each response/run shows prompt and generated token counts, total elapsed time, prompt-processing rate, generation rate, and thinking time when meaningful. Local Ollama and direct Ollama Cloud chat use `/api/chat` to obtain native timing/count fields. When a stage rate is unavailable, **Overall tok/s** shows `(input tokens + output tokens) / elapsed seconds`, provided both counts and a positive elapsed time are known. This includes the full request time and is labeled separately from generation speed; unavailable measurements display **—**. The fallback also works for previously saved responses. Thinking time is explicitly labeled as an estimate based on streamed reasoning arrival; hidden reasoning and non-streaming responses do not expose reliable thinking duration. Zero generated tokens is a valid System One result.

## Connections and discovery

**Connections** combines saved connections, environment settings, and local server candidates. **Refresh discovery** rescans these loopback ports, trying IPv4 and IPv6:

| Candidate | Ports |
| --- | --- |
| Ollama | 11434 |
| llama.cpp | 9931, 8080 |
| FastFlowLM | 52625 |
| LiteLLM | 4000 |

An open port appears even if its API requires authentication. Model-list probes distinguish compatible APIs from unverified open ports. Service names derived from port numbers are candidates; Ollama's version endpoint is used to confirm Ollama. Discovery does not scan the LAN or automatically issue inference requests. Custom addresses and ports can be entered manually.

Environment discovery supports: OpenAI, Anthropic, LiteLLM, Ollama, llama.cpp, OpenRouter, Groq, Together, Mistral, DeepSeek, xAI, and Bedrock Mantle. It recognizes their API-key, base-URL, and model settings. Mantle uses bearer API keys, not AWS Runtime signing. Environment connections are saved only when explicitly copied through the connection manager.

**Import** accepts validated JSON files with a top-level `connections` mapping. Imports are validated and previewed before saving; duplicate names can be skipped, replaced, or renamed. **Export** exports selected entries, or all entries when none are selected. API keys are excluded by default; including them requires an explicit choice. Credential-store references are never exported.

Saved API keys use `keyring` and the OS credential store. The editor offers explicit plaintext storage if needed. History contains a connection name and settings snapshot, not an API key. If a saved connection's URL changes, old sessions do not silently receive its key. Endpoint redirects are rejected so credentials are not automatically forwarded to a different address.

Default local data directories:

- Windows: `%LOCALAPPDATA%\Agentnik`
- macOS: `~/Library/Application Support/Agentnik`
- Linux: `$XDG_DATA_HOME/agentnik`, or `~/.local/share/agentnik`

`--data-dir PATH` or `AGENTNIK_HOME` overrides the directory. Connections use JSON; session history uses Python's built-in SQLite. Light/dark/system theme and sidebar visibility are remembered.

## Validation

```powershell
python -m unittest discover -s tests -v
python -m compileall -q agentnik tests tools
```

Ordinary tests are offline and use temporary storage. They cover provider wire formats, streaming, cancellation, decisions, credentials, attachment cleanup, independent tabs, saved prompts, font controls, theme switching, and packaged branding. `tools/live_smoke.py` is an optional endpoint check; running it lists models, and `--generate` or `--decision-model MODEL` issues inference. Run live checks only when authorized. No live endpoint compatibility is claimed for this baseline.

Windows source and offscreen Qt checks are recorded in `VALIDATION.md`. macOS/Linux runtime behavior and frozen distributions remain unverified.

## Packaging

The Python wheel has been built and installed locally; see [validation results](VALIDATION.md). To build a wheel without resolving runtime dependencies:

```powershell
python -m pip wheel . --no-deps --wheel-dir dist
```

Build and test on each target OS; a Windows build does not produce a macOS or Linux application. For an initial distributable, install PyInstaller as a build-only dependency and run:

```powershell
python -m PyInstaller --noconfirm --windowed --name Agentnik --icon agentnik/assets/agentnik-icon.ico --add-data "agentnik/assets:agentnik/assets" --collect-submodules keyring.backends agentnik.py
```

Verify credential storage, TLS access, file dialogs, clipboard images, history, and Qt platform plugins in each packaged build. Signed installers and automatic updates are future distribution work.

## License

MIT. Copyright (c) 2026 Nikolaus Spence. Author: Nikolaus Spence.
