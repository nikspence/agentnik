# Agentnik v0.2.0

Windows x64 onedir release. Extract the whole ZIP, then launch `Agentnik/Agentnik.exe`; its `_internal` directory must stay beside it. Python is included. Verify the archive against its `.sha256` sidecar. The build is unsigned.

## Changes since v0.1.0

- Managed research across native Ollama, Responses, Chat Completions, and Messages, with protocol-specific tool continuation, thinking/signatures, and correlation IDs.
- Stricter stream lifecycle validation rejects incomplete or conflicting tool calls before execution. Partial research remains auditable without being replayed as successful model history.
- Real Ollama search handles the service's JSON response when mislabeled as HTML at its fixed endpoint, while keeping JSON/schema and public-fetch destination checks.
- Improved cumulative usage accounting with separate cache/reasoning details and sanitized per-request numeric snapshots.
- Safer saved settings and session recovery: malformed/future data is preserved, valid history remains usable, and attachments are retained when unreadable records may reference them.
- Research verification is isolated by opaque connection/account context; credential changes invalidate stale evidence.
- Bounded research worker accumulation, safe pre-request TCP address failover, a separate research-record retention budget, and preserved thinking visibility on completion.
- Explicit opt-in live compatibility CLI and isolated Windows build/archive tooling, with manifests, dependency notices, checksums and readiness-based frozen startup checks.

## Compatibility and scope

Scoped live LiteLLM evidence includes ChatGPT `chatgpt/gpt-6-luna` and Ollama Cloud `ollama-cloud/gpt-oss:20b` streamed chat/tool continuation, a Gemma chat check, and real managed search plus direct page retrieval using `chatgpt/gpt-6-luna`. These results apply to the exact tested aliases/protocols/routes, not all gateway models. Anthropic aliases were listed but unavailable to the tested Mantle account; live Messages compatibility remains unverified. Hosted search remains limited to the official OpenAI Responses endpoint.

See VALIDATION.md and MILESTONE_D_LIVE_RESULTS.md for evidence. BUILD-MANIFEST.json records this artifact's source revision, environment, dependencies and startup result. Startup success does not establish every dialog, clipboard, credential-store or TLS/provider workflow. Clean-machine and macOS/Linux validation, signing, and a full bundled-library license audit remain pending; installed dependency notices and Python's license are included.

No API keys, personal history, or runtime settings are included. Existing Agentnik data remains in its normal independent application data directory. Repositories/Coding Agent, MCP servers, Skills, and the optional System One command safety recommendation remain planned features.
