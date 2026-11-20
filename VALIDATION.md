# Validation and compatibility

Agentnik's automated suite uses mocked endpoints, temporary data and offscreen Qt. It checks application contracts, but does not establish live model compatibility or substitute for native interactive testing. Run the current checks and use the opt-in compatibility and build tools described in [development and builds](DEVELOPMENT_VALIDATION.md).

## Previously observed live behavior

These narrowly scoped observations are historical, not guarantees for current accounts, versions or other models:

- The user reports completing live multi-file coding tasks with Qwen3-Coder-Next, Kimi V3.1 Pro, Qwen3.5 9B, Gemma 4 12B and DeepSeek V4.1 Flash, including tool calls and recovery from invalid arguments. Improved tool argument descriptions reduced errors for some models. These are user-reported results; endpoint details and transcripts were not available for independent verification.
- On 2026-11-20, an Inkling-2-Small Code request through LiteLLM Responses reproduced an output-item identity conflict. After matching reordered calls and avoiding replay of malformed arguments, one live research-and-report task completed while recovering from two invalid batches. Gateway logs showed concatenated tool-call arguments; an earlier continuation failed in LiteLLM's Ollama transformation. These observations do not establish general model compatibility. A separate Mistral Large 4 continuation returned an upstream Ollama HTTP 500.

- An authorized LiteLLM gateway check completed streamed chat with `ollama-cloud/gpt-oss:20b` using Chat Completions, `chatgpt/gpt-6-luna` using Responses, and `us-west-2/google.gemma-3-4b-it` using Chat Completions. The first two also completed tool-call continuation with a synthetic local source.
- A separate LiteLLM Responses check with `chatgpt/gpt-6-luna` completed managed research using Ollama search and a direct public-page fetch, then returned citations. It did not test hosted search or the native GUI.
- Authorized adapter-only searches returned results from Brave, Firecrawl Keyless and LangSearch. These were not end-to-end model research or provider page-retrieval tests; one ambiguous LangSearch query returned irrelevant results, while a site-restricted follow-up returned relevant Qt pages.
- The user reported managed Responses research working through LiteLLM after subsequent continuation and limit changes; those individual requests were not recorded or repeated as part of that validation.

Some advertised Anthropic aliases were unavailable to the tested Mantle account. Model listings and protocol names do not establish support; avoid repeated probes of unavailable routes. Check any new model, endpoint and capability individually when live testing is explicitly authorized.

## Remaining qualification

- Live compatibility for additional models, protocols and routes, including hosted search, coding, MCP, provider page retrieval and System One with actual image input. Output quality is not established by mocks.
- Native interactive workflows, cancellation, credentials, TLS and accessibility on each supported platform; clean-machine Windows installation and macOS/Linux distribution testing.
- Full frozen-app workflows, signing and a complete bundled-library license audit. A build-host startup smoke check only establishes window startup, temporary database creation and graceful exit for that build.

Release-specific build evidence belongs in the archive's `BUILD-MANIFEST.json`; [release notes](RELEASE_NOTES.md) describe released changes. The project plans retain design constraints and future work, not a substitute for new validation evidence.
