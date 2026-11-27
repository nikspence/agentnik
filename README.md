# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.png#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.png#gh-dark-mode-only)

**Code in your terminal, or use the desktop app for coding, chat, and research.** Agentnik runs on Windows, macOS, and Linux and works with your choice of local or cloud model connections, including Ollama, LiteLLM gateways, and compatible provider endpoints.

## Install from PyPI

Python 3.11 or newer is required. Choose which interface you want to install.

**Terminal coding (no Qt):**

```sh
python -m pip install "agentnik[terminal]"
agentnik code
```

Run `agentnik code` from the folder you want to work in. Git is optional. Use `/connections add` to set up a model connection and `/help` to discover commands. The terminal is a preview and works over SSH and in the VS Code integrated terminal. [Terminal guide](TERMINAL_CODE.md)

**Desktop app:**

```sh
python -m pip install "agentnik[desktop]"
agentnik-desktop
```

To install both interfaces in the same environment, run `python -m pip install "agentnik[desktop,terminal]"`. [PyPI package](https://pypi.org/project/agentnik/) · [Source installation and troubleshooting](GETTING_STARTED.md)

## Windows download without Python

Download the [v0.13.1 Windows x64 ZIP](https://github.com/nikspence/agentnik/releases/tag/v0.13.1), verify the SHA-256 sidecar, and extract the entire archive. Open `Agentnik.exe` for the desktop. To start Code from a project folder, invoke the console launcher by its full path in PowerShell:

```powershell
& "C:\path\to\Agentnik\Agentnik-Terminal.exe" code
```

Keep the `_internal` directory next to both executables. The bundle is unsigned and has been tested on the build host, not separately on a clean machine. [Release notes](RELEASE_NOTES.md)

## What you can do

- **Code with your model:** work in local repositories or folders from the terminal or desktop. Review edits and shell commands, inspect changes, and resume independent sessions without replaying tool actions. The terminal also supports manual Git commands, project and machine file scopes, and optional image generation and inspection. [Terminal guide](TERMINAL_CODE.md) · [Coding features](CODE_FEATURES.md)
- **Plan with specifications and tracks:** the built-in **Spec & Plan** workflow follows a Conductor-style approach: draft requirements, a specification and a task plan, review project changes, then start a selected track. Persistent project context, editable drafts, task IDs and progress reconciliation keep larger changes organized. [Spec & Plan guide](CODING_GUIDE.md#spec--plan-track-preview) · [Track format](TRACK_FORMAT.md)
- **Extend workflows with Skills and MCP:** select repository or user Skills and connect local or remote MCP servers, including OAuth with a pre-registered public client or supported dynamic registration. Code can use supported tools, text resources, templates and prompts; Chat offers an opt-in preview for MCP tools, resources and prompts. MCP tools can write or perform external actions without approval. [Skills and MCP](CODE_FEATURES.md) · [Chat tools](CHAT_GUIDE.md)
- **Chat with images and documents:** keep conversations in independent tabs with Markdown, streaming, visible thinking, saved prompts, history and token statistics. Attach images and supported documents in Chat or Code, optionally generate or edit images using an image provider, and use local calculator and data-analysis tools. [Chat and history](CHAT_GUIDE.md) · [Coding guide](CODING_GUIDE.md)
- **Research the web:** combine managed search and public-page retrieval, or use hosted search on eligible OpenAI Responses connections. Sources, citations, activity and fallback are visible; configured search providers can also supply place, image and entity results. [Research guide](RESEARCH_GUIDE.md) · [Search providers](SEARCH_PROVIDERS.md)
- **Get shell command advice:** optionally use an Ollama System One decision model to advise on shell-command approvals in Code. [Coding guide](CODING_GUIDE.md)
- **Choose connections and keep local history:** use native Ollama or compatible Responses, Chat Completions and Messages endpoints, including LiteLLM gateways and supported cloud connections. Manage credentials, persistent sessions and attachments, prompt history, context compaction, themes and language settings. [Connections and local data](CONNECTIONS.md) · [Feature inventory](FEATURES.md)

Spec & Plan is a native Agentnik feature inspired by Conductor. It uses Agentnik's own track format and configured models; upstream plugin or track compatibility is not claimed. Reported progress requires user judgment.

For testing System One Decision models with varying states, images, and questions, we recommend [Promptnik](https://github.com/nikspence/promptnik).

Research and coding workflows include preview features. Model listings do not establish support for tools, images, research or System One. See [validation](VALIDATION.md) for observed behavior and remaining platform and compatibility checks.

## What Agentnik is not

Agentnik is not a remotely controlled or unattended automated agent. You start and direct work in the terminal or desktop app. Code can work through the steps of a goal while the client is running, and subagents perform bounded work within a user-started run.

## Screenshots

![Agentnik light theme](assets/agentnik-light-welcome.png)
![Agentnik dark theme](assets/agentnik-dark-welcome.png)

These welcome screens were rendered offline with temporary data. Research screenshots below use simulated responses.

![Hosted research with inline citations](assets/agentnik-hosted-dark.png)
![Visible hosted-to-managed fallback](assets/agentnik-fallback-light.png)

## Documentation and development

- [Coding features](CODE_FEATURES.md) and [coding guide](CODING_GUIDE.md): model selection, project tools, Spec & Plan, Skills, and MCP.
- [Chat and history](CHAT_GUIDE.md): attachments, prompts, history, and controls.
- [Research guide](RESEARCH_GUIDE.md) and [search providers](SEARCH_PROVIDERS.md): routes, configuration, sources, and limits.
- [Connections and local data](CONNECTIONS.md): endpoints, credentials, discovery, and storage.
- [Features](FEATURES.md), [validation](VALIDATION.md), and [development and builds](DEVELOPMENT_VALIDATION.md): feature inventory, evidence, offline checks, and release tooling.
- [Project roadmap](AGENTNIK_PLAN.md): remaining work and qualification priorities.

Ordinary tests use temporary storage and do not issue live inference. Build and validate on each target OS. Pillow is used to rebuild branding assets and for image generation on terminal-only installations. See [DISCLAIMER.md](DISCLAIMER.md) for responsibility and use information.

The toolbar **Web** and **MCP** switches apply to new Chat and Code runs. **Settings** controls which tool wins a name conflict. Use **Settings** for shared search priority and providers, research and coding limits, optional Decision-model shell advice, and TLS verification. Select the Code model at the top of each Code pane. Settings changed during a run apply to the next run. Web defaults off.

## License

Apache-2.0. Copyright 2026 Nikolaus Spence. Sole author: Nikolaus Spence.
