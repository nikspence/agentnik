# Agentnik

![Agentnik logo](agentnik/assets/agentnik-light.svg#gh-light-mode-only)
![Agentnik logo](agentnik/assets/agentnik-dark.svg#gh-dark-mode-only)

**Code, chat, research, and make structured decisions with your choice of local or cloud models.** Agentnik is a Python/Qt desktop application for Windows, macOS, and Linux. It brings model connections, conversations, projects, and research into one workspace, using Ollama, LiteLLM gateways, and compatible provider endpoints.

## What you can do

- **Code with your models:** work in local repositories or folders using Agentnik's own coding loop. Choose Heavy and Light models independently, delegate bounded analysis, inspect and edit files, run approved shell commands and tests, and use structured Git tools. [Coding features](CODE_FEATURES.md) · [Coding guide](CODING_GUIDE.md)
- **Plan with specifications and tracks:** the built-in **Spec & Plan** workflow follows a Conductor-style approach: draft requirements, a specification and a task plan, review project changes, then start a selected track. Persistent project context, editable drafts, task IDs and progress reconciliation keep larger changes organized. [Spec & Plan guide](CODING_GUIDE.md#spec--plan-track-preview) · [Track format](TRACK_FORMAT.md)
- **Review documents independently:** built-in reviews follow Elephant Goldfish Model-style discipline, using fresh requests with fixed comprehension, requirements, design, repository-fit, readiness or drift rubrics and explicitly selected evidence. Inspect attributed findings, resolve dispositions, save review history and see revision status before implementation. [Independent review guide](CODING_GUIDE.md#independent-document-review) · [Review features](CODE_FEATURES.md)
- **Extend workflows with Skills and MCP:** select repository or user Skills and connect local or remote MCP servers. Code can use supported tools, text resources, templates and prompts; Chat offers an opt-in MCP tool preview. MCP tools can write or perform external actions without approval. [Skills and MCP](CODE_FEATURES.md) · [Chat tools](CHAT_AND_DECISIONS.md)
- **Chat with images and documents:** keep conversations in independent tabs with Markdown, streaming, visible thinking, saved prompts, history and token statistics. Attach images and supported documents in Chat or Code, and use local calculator and data-analysis tools. [Chat and decisions](CHAT_AND_DECISIONS.md) · [Coding guide](CODING_GUIDE.md)
- **Research the web:** combine managed search and public-page retrieval, or use hosted search on eligible OpenAI Responses connections. Sources, citations, activity and fallback are visible; configured search providers can also supply place, image and entity results. [Research guide](RESEARCH_GUIDE.md) · [Search providers](SEARCH_PROVIDERS.md)
- **Make structured decisions:** use the separate Ollama System One API for yes/no, multiple-choice and ordered-score questions, with shared context and multiple images. Decision sessions preserve their own questions and criteria independently of ordinary chat. [Chat and decisions](CHAT_AND_DECISIONS.md)
- **Choose connections and keep local history:** use native Ollama or compatible Responses, Chat Completions and Messages endpoints, including LiteLLM gateways and supported cloud connections. Manage credentials, persistent sessions and attachments, prompt history, context compaction, themes and language settings. [Connections and local data](CONNECTIONS.md) · [Feature inventory](FEATURES.md)

Spec & Plan and independent reviews are native Agentnik features inspired by Conductor and Elephant Goldfish Model (EGM). They use Agentnik's own track format and configured models; upstream plugin or track compatibility is not claimed. Review findings and reported progress require user judgment, and source hashes identify the revision reviewed. Provider-side isolation and live review quality remain unverified.

Research and coding workflows include preview features. Model listings do not establish support for tools, images, research or System One. See [validation](VALIDATION.md) for observed behavior and remaining platform and compatibility checks.

## Get started

Agentnik requires Python 3.11 or newer. See [installation and launch](GETTING_STARTED.md) for Windows, macOS and Linux instructions, or use the Windows archive described below. Endpoint, credential and storage configuration is covered in [connections and local data](CONNECTIONS.md).

## Windows release

The **v0.8.5** Windows x64 build is an unsigned onedir ZIP. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. Verify the accompanying SHA-256 checksum. Build-host startup results are recorded in the archive; clean-machine, full native workflow, and macOS/Linux validation remain outstanding. See [release notes](RELEASE_NOTES.md) and the archive's `BUILD-MANIFEST.json` for details.

## Screenshots

![Agentnik light theme](assets/agentnik-light-welcome.png)
![Agentnik dark theme](assets/agentnik-dark-welcome.png)

These welcome screens were rendered offline with temporary data. Research screenshots below use simulated responses.

![Hosted research with inline citations](assets/agentnik-hosted-dark.png)
![Visible hosted-to-managed fallback](assets/agentnik-fallback-light.png)

## Documentation and development

- [Coding features](CODE_FEATURES.md) and [coding guide](CODING_GUIDE.md): model roles, project tools, Spec & Plan, independent reviews, Skills, and MCP.
- [Chat and decisions](CHAT_AND_DECISIONS.md): attachments, System One, prompts, history, and controls.
- [Research guide](RESEARCH_GUIDE.md) and [search providers](SEARCH_PROVIDERS.md): routes, configuration, sources, and limits.
- [Connections and local data](CONNECTIONS.md): endpoints, credentials, discovery, and storage.
- [Features](FEATURES.md), [validation](VALIDATION.md), and [development and builds](DEVELOPMENT_VALIDATION.md): feature inventory, evidence, offline checks, and release tooling.
- [Project plan](AGENTNIK_PLAN.md) and [coding backend plan](CODING_BACKEND_PLAN.md): historical decisions and remaining work. The plans include historical milestones; use the guides and validation records for current behavior and evidence.
- [Independent review implementation plan](INDEPENDENT_REVIEW_PLAN.md): implemented review previews, persistence contracts, and remaining validation steps.

Ordinary tests use temporary storage and do not issue live inference. Build and validate on each target OS. Pillow is needed to rebuild branding assets, not to run Agentnik. See [DISCLAIMER.md](DISCLAIMER.md) for responsibility and use information.

## License

Apache-2.0. Copyright 2026 Nikolaus Spence. Sole author: Nikolaus Spence.
