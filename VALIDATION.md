# Validation and compatibility

The automated suite uses mocked endpoints, temporary data and offscreen Qt. It does not establish live model or platform compatibility. See [development and builds](DEVELOPMENT_VALIDATION.md) for commands and optional live checks; ordinary tests do not issue inference requests.

## Scoped observations

- Selected Code, Chat and research tasks have completed through local Ollama, OpenRouter and LiteLLM routes. These observations cover individual models and tasks, not all tools or providers.
- OpenRouter and the configured LiteLLM image passthrough have generated and edited images. A live Code model inspected an image, and live subagents created sample slide files; the complete editable PowerPoint workflow remains unqualified.
- On Windows, the optional SDK smoke test passed against MCP Python SDK 2.3.0 using protocol 2025-11-25: stdio discovery, a synthetic structured tool call, a resource and template read, and prompt retrieval. It does not qualify remote HTTP, OAuth, tasks, third-party servers or model behavior.
- Windows clean-machine testing was reported complete, but its build and workflow scope were not specified. Each release's `BUILD-MANIFEST.json` records its build-host smoke result; that is not a separate clean-machine qualification.

## Remaining qualification

- Verify model and protocol combinations for coding, research, MCP, hosted search, image workflows and System One advice independently; model listings do not prove capability.
- Qualify native workflows, cancellation, credentials, TLS and accessibility by platform. macOS and Linux clean-machine testing remain outstanding.
- Complete signing and the bundled-library license audit. Release archives record their source revision, dependencies and smoke results.

See the [release notes](RELEASE_NOTES.md) and [roadmap](AGENTNIK_PLAN.md); historical test narratives remain available in Git.
