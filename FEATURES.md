# Agentnik features

Agentnik is an interactive desktop client for chat, coding and research using configured local or cloud model connections. Feature availability depends on the selected endpoint and model; research and coding are previews.

## Chat and history

- Independent conversations support streamed Markdown, optional thinking, editing and resending prompts, saved prompts and reported usage.
- Attach images and supported documents, including PDF and Office files, for local preview and explicit submission. Local calculator and data-analysis tools are optional.
- Sessions and attachments persist locally. Earlier Decision sessions and saved prompts remain read-only; new System One query testing belongs in Promptnik. Code can optionally use a System One model for shell-command advice.
- Themes, font size and localization previews for Korean, Mexican Spanish, Canadian French, Simplified and Traditional Chinese, and German are available. See the [chat guide](CHAT_GUIDE.md) for controls, formats and limits.

## Code

- Register local repositories or folders, run coding tasks, pursue goals, send steering, and inspect tool activity. Each request uses one selected model; bounded subagents use the same model.
- Project tools support navigation, reads, edits, patches, plans, notes, memory, skills and optional research. File changes are subject to path and conflict checks. Shell/test commands follow the user-controlled approval switch; structured Git mutations have their own reviews.
- Code supports selected MCP servers, repository guidance, Spec & Plan tracks, configurable limits and explicit continuation. Reopening a session does not resume execution. See [coding features](CODE_FEATURES.md) and the [coding guide](CODING_GUIDE.md) for permissions and operational limits.

## Research and connections

- Chat supports managed research and eligible provider-hosted search; Code supports managed search and page retrieval. Sources, activity and bounded fallback are visible. See the [research guide](RESEARCH_GUIDE.md) and [search providers](SEARCH_PROVIDERS.md).
- Connections support native Ollama and compatible Responses, Chat Completions and Messages endpoints, including LiteLLM and Bedrock Mantle. Credentials use the OS keyring with an explicit plaintext fallback. See [connections](CONNECTIONS.md) for discovery, storage and configuration.
- MCP servers can perform external actions and are subject to the permissions described in the [coding](CODING_GUIDE.md) and [chat](CHAT_GUIDE.md) guides. Model and server descriptions are not evidence of capability or safety.

## Validation and distribution

The Python/Qt application targets Windows, macOS and Linux. An installable Python package and a Windows x64 archive build process are available. Offline tests do not establish live model or platform compatibility. See [validation](VALIDATION.md), [development and builds](DEVELOPMENT_VALIDATION.md), and the [roadmap](AGENTNIK_PLAN.md) for evidence and remaining gates.
