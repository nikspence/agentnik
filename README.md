# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.svg#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.svg#gh-dark-mode-only)

**Code, chat, research, and make structured decisions with your choice of local or cloud models.** Agentnik is a Python/Qt desktop application for Windows, macOS, and Linux. It brings model connections, conversations, projects, and research into one workspace, using Ollama, LiteLLM gateways, and compatible provider endpoints.

## What you can do

- **Code with your models:** register a repository or folder and run Agentnik's own coding loop. Choose Heavy and Light models independently, delegate bounded analysis, use project tools, maintain a task plan, and inspect activity. File changes are applied during the run; shell commands and structured Git mutations require approval. [Coding features](CODE_FEATURES.md) · [Coding guide](CODING_GUIDE.md)
- **Connect MCP servers and Skills:** configure local stdio or remote HTTPS MCP servers, inspect and call tools, and use supported tools, text resources and prompts in Code. An opt-in Chat preview supports one selected server's tools. MCP tools run without approval, including tools that can write or perform external actions. Select repository or user Skills for a coding run. [Chat](CHAT_AND_DECISIONS.md) · [MCP and coding](CODE_FEATURES.md)
- **Chat with documents and images:** use independent tabs with streaming, Markdown, thinking, history, saved prompts, and token statistics. Attach images and supported documents, and opt into local calculator and data tools. [Chat and decisions](CHAT_AND_DECISIONS.md)
- **Research the web:** enable managed search and public-page retrieval for compatible tool-capable models, or use hosted search on eligible OpenAI Responses connections. A configured Parallel profile also provides place, image and entity search on the managed route. Sources, activity, and fallback are visible. Research is a preview; compatibility is specific to the endpoint, protocol, model and route. [Research guide](RESEARCH_GUIDE.md) · [Search providers](SEARCH_PROVIDERS.md)
- **Make structured decisions:** use the separate Ollama System One API for yes/no, multiple-choice, and ordered-score questions, with shared context and optional images. A compatible decision model and endpoint are required. [Chat and decisions](CHAT_AND_DECISIONS.md)

Agentnik supports native Ollama chat and compatible Responses, Chat Completions, and Messages endpoints. Model listings do not establish support for tools, images, research, or System One. See [connections and local data](CONNECTIONS.md) for discovery, credentials, storage, Bedrock Mantle routing, and the optional global TLS setting.

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

## Windows release

The **v0.8.3** Windows x64 build is an unsigned onedir ZIP. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. Verify the accompanying SHA-256 checksum. Build-host startup results are recorded in the archive; clean-machine, full native workflow, and macOS/Linux validation remain outstanding. See [release notes](RELEASE_NOTES.md) and the archive's `BUILD-MANIFEST.json` for details.

## Screenshots

![Agentnik light theme](assets/agentnik-light-welcome.png)
![Agentnik dark theme](assets/agentnik-dark-welcome.png)

These welcome screens were rendered offline with temporary data. Research screenshots below use simulated responses.

![Hosted research with inline citations](assets/agentnik-hosted-dark.png)
![Visible hosted-to-managed fallback](assets/agentnik-fallback-light.png)

## Documentation and development

- [Coding features](CODE_FEATURES.md) and [coding guide](CODING_GUIDE.md): model roles, project tools, approvals, Skills, MCP, and workflows.
- [Chat and decisions](CHAT_AND_DECISIONS.md): attachments, System One, prompts, history, and controls.
- [Research guide](RESEARCH_GUIDE.md) and [search providers](SEARCH_PROVIDERS.md): routes, configuration, sources, and limits.
- [Connections and local data](CONNECTIONS.md): endpoints, credentials, discovery, and storage.
- [Features](FEATURES.md), [validation](VALIDATION.md), and [development and builds](DEVELOPMENT_VALIDATION.md): feature inventory, evidence, offline checks, and release tooling.
- [Project plan](AGENTNIK_PLAN.md) and [coding backend plan](CODING_BACKEND_PLAN.md): historical decisions and remaining work. The plans include historical milestones; use the guides and validation records for current behavior and evidence.

Ordinary tests use temporary storage and do not issue live inference. Build and validate on each target OS. Pillow is needed to rebuild branding assets, not to run Agentnik. See [DISCLAIMER.md](DISCLAIMER.md) for responsibility and use information.

## License

Apache-2.0. Copyright 2026 Nikolaus Spence. Sole author: Nikolaus Spence.
