# Validation and compatibility

The automated suite uses mocked endpoints, temporary data and offscreen Qt. It verifies application behavior but does not establish live model or platform compatibility. Run the current checks using [development and builds](DEVELOPMENT_VALIDATION.md); ordinary tests do not issue live inference requests.

## Scoped live observations

These observations apply only to the tested configurations and do not guarantee other models, accounts or versions:

- The user reported successful multi-file coding with several models. A later Inkling-2-Small task through LiteLLM Responses completed after recovery from malformed tool calls; a separate Mistral Large 4 continuation received an upstream Ollama HTTP 500.
- Selected LiteLLM chat and managed-research routes completed, including tool continuation and public-page retrieval. Selected search providers also returned adapter-only results. These checks do not establish general coding, hosted-search or provider compatibility.
- Some Anthropic aliases were unavailable to the tested Mantle account. Do not repeatedly probe unavailable routes or infer support from model listings.

## Outstanding qualification

- Live model/protocol combinations for coding, research, MCP, hosted search and System One advice remain independently scoped; output quality and model adherence require review.
- Native workflows, cancellation, credentials, TLS and accessibility need platform-specific checks. Clean-machine Windows installation and macOS/Linux distributions remain unqualified.
- Signing and a complete bundled-library license audit remain open. The build-host smoke checks startup, an isolated database and graceful exit; it does not qualify full workflows or installation on a clean machine.

Each release archive's `BUILD-MANIFEST.json` records its own source revision, dependencies and smoke result. [Release notes](RELEASE_NOTES.md) describe the current release; older evidence is in Git history.
