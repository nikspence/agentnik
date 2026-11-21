# Validation and compatibility

The automated suite uses mocked endpoints, temporary data and offscreen Qt. It verifies application behavior but does not establish live model or platform compatibility. Run the current checks using [development and builds](DEVELOPMENT_VALIDATION.md); ordinary tests do not issue live inference requests.

## Scoped live observations

These observations apply only to the tested configurations and do not guarantee other models, accounts or versions:

- The user reported successful multi-file coding with several models. A later Inkling-2-Small task through LiteLLM Responses completed after recovery from malformed tool calls; a separate Mistral Large 4 continuation received an upstream Ollama HTTP 500.
- The user reports clean-machine testing is complete on Windows. The exact build and workflows were not specified; this does not establish macOS or Linux validation.
- Selected LiteLLM chat and managed-research routes completed, including tool continuation and public-page retrieval. Selected search providers also returned adapter-only results. These checks do not establish general coding, hosted-search or provider compatibility.
- Some Anthropic aliases were unavailable to the tested Mantle account. Do not repeatedly probe unavailable routes or infer support from model listings.

## Outstanding qualification

- Live model/protocol combinations for coding, research, MCP, hosted search and System One advice remain independently scoped; output quality and model adherence require review.
- Native workflow, cancellation, credentials, TLS and accessibility coverage still needs to be recorded by platform and scope. macOS and Linux clean-machine testing remain outstanding.
- Signing and a complete bundled-library license audit remain open. The build-host smoke checks startup, an isolated database and graceful exit; it is separate from the user-reported Windows clean-machine testing.

Each release archive's `BUILD-MANIFEST.json` records its own source revision, dependencies and smoke result. [Release notes](RELEASE_NOTES.md) describe the current release; older evidence is in Git history.
