# Validation and compatibility

Agentnik's automated suite uses mocked endpoints, temporary data and offscreen Qt. It checks application contracts, but does not establish live model compatibility or substitute for native interactive testing. Run the current checks and use the opt-in compatibility and build tools described in [development and builds](DEVELOPMENT_VALIDATION.md).

## Previously observed live behavior

These narrowly scoped observations are historical, not guarantees for current accounts, versions or other models:

- An authorized LiteLLM gateway check completed streamed chat with `ollama-cloud/gpt-oss:20b` using Chat Completions, `chatgpt/gpt-6-luna` using Responses, and `us-west-2/google.gemma-3-4b-it` using Chat Completions. The first two also completed tool-call continuation with a synthetic local source.
- A separate LiteLLM Responses check with `chatgpt/gpt-6-luna` completed managed research using Ollama search and a direct public-page fetch, then returned citations. It did not test hosted search or the native GUI.
- Authorized adapter-only searches returned results from Brave, Firecrawl Keyless and LangSearch. These were not end-to-end model research or provider page-retrieval tests; one ambiguous LangSearch query returned irrelevant results, while a site-restricted follow-up returned relevant Qt pages.
- The user reported managed Responses research working through LiteLLM after subsequent continuation and limit changes; those individual requests were not recorded or repeated as part of that validation.

Some advertised Anthropic aliases were unavailable to the tested Mantle account. Model listings and protocol names do not establish support; avoid repeated probes of unavailable routes. Check any new model, endpoint and capability individually when live testing is explicitly authorized.

## Remaining qualification

- Live compatibility for additional models, protocols and routes, including hosted search, coding, independent review, MCP, provider page retrieval and System One with actual image input. Provider-side review isolation and output quality are not established by mocks.
- Native interactive workflows, cancellation, credentials, TLS and accessibility on each supported platform; clean-machine Windows installation and macOS/Linux distribution testing.
- Full frozen-app workflows, signing and a complete bundled-library license audit. A build-host startup smoke check only establishes window startup, temporary database creation and graceful exit for that build.

Release-specific build evidence belongs in the archive's `BUILD-MANIFEST.json`; [release notes](RELEASE_NOTES.md) describe released changes. The project plans retain design constraints and future work, not a substitute for new validation evidence.
