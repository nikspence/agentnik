# Validation and compatibility

The automated suite uses mocked endpoints, temporary data and offscreen Qt. It verifies application behavior but does not establish live model or platform compatibility. Run the current checks using [development and builds](DEVELOPMENT_VALIDATION.md); ordinary tests do not issue live inference requests.

## Scoped live observations

On 2026-11-21, a live Code run using OpenRouter Responses and `openai/gpt-6.2-sol` called `view_image` on a generated image and correctly described a red triangle on a white background. This is one model and image, not general verification of visual accuracy or other providers.

These observations apply only to the tested configurations and do not guarantee other models, accounts or versions:

- On 2026-11-21, OpenRouter's Image API and the configured G-Chat/LiteLLM image passthrough each generated and edited images with `black-forest-labs/flux.2-klein-4b`; the returned images were visually checked. The actual Code image tool also generated an image with `openai/gpt-image-2` on each route. A Chat image-tool edit using `openai/gpt-image-2` through G-Chat produced the requested blue circle. Those tool-loop checks used simulated text-model replies and real image requests. A separate live Chat run through OpenRouter used `openai/gpt-6.2-sol` to call the image tool and `openai/gpt-image-2` to create a red triangle; the result was visually checked. These observations do not qualify the full GUI workflow, cancellation, or every provider/model combination.

- On 2026-11-21, a bounded live Code backend check used Responses streaming and a separate temporary Python fixture for each route. Each model had to inspect and fix a tag-normalization function; independent local tests checked the result. The task did not exercise Code UI interaction, shell commands, Git, web, MCP, images, goals or cancellation. All nine routes eventually completed with passing fixture tests: Desktop Ollama `gemma4:12b`; OpenRouter `qwen/qwen3.8-flash`, `thinkingmachines/inkling-2-mini`, and `openai/gpt-6.2-sol`; and the same three OpenRouter routes through G-Chat LiteLLM, plus `ollama-cloud/kimi-k3.1-pro` and Bedrock `us-west-2/qwen.qwen3-coder-next` through G-Chat. Both Qwen routes and G-Chat Inkling hit an initial eight-round cap; each passed a fresh follow-up with a 24-round cap. The initial G-Chat Inkling run also returned malformed tool arguments and patch mismatches; its follow-up recovered from a patch mismatch. Other successful routes also recovered from patch mismatches. These are single, small-task observations, not broad compatibility guarantees.

- The user reported successful multi-file coding with several models. A later Inkling-2-Small task through LiteLLM Responses completed after recovery from malformed tool calls; a separate Mistral Large 4 continuation received an upstream Ollama HTTP 500.
- The user reports clean-machine testing is complete on Windows. The exact build and workflows were not specified; this does not establish macOS or Linux validation.
- Selected LiteLLM chat and managed-research routes completed, including tool continuation and public-page retrieval. Selected search providers also returned adapter-only results. These checks do not establish general coding, hosted-search or provider compatibility.
- Some Anthropic aliases were unavailable to the tested Mantle account. Do not repeatedly probe unavailable routes or infer support from model listings.

## Outstanding qualification

- Live model/protocol combinations for coding, research, MCP, hosted search and System One advice remain independently scoped; output quality and model adherence require review.
- Native workflow, cancellation, credentials, TLS and accessibility coverage still needs to be recorded by platform and scope. macOS and Linux clean-machine testing remain outstanding.
- Signing and a complete bundled-library license audit remain open. The build-host smoke checks startup, an isolated database and graceful exit; it is separate from the user-reported Windows clean-machine testing.

Each release archive's `BUILD-MANIFEST.json` records its own source revision, dependencies and smoke result. [Release notes](RELEASE_NOTES.md) describe the current release; older evidence is in Git history.
