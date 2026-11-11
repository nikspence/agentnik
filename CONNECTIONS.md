# Connections and local data

## Connections and local data

Use saved connections, environment discovery, or custom URLs and ports. Models load automatically and can be refreshed; manual aliases work when model listing is unavailable. Import and export validated connection JSON with duplicate handling and an explicit choice to include keys.

Environment discovery recognizes OpenAI, Anthropic, LiteLLM, Ollama, llama.cpp, OpenRouter, Groq, Together, Mistral, DeepSeek, xAI, and Bedrock Mantle settings. Mantle uses bearer tokens. Local candidates include Ollama (11434), llama.cpp (9931/8080), FastFlowLM (52625), and LiteLLM (4000). Environment wildcard hosts normalize from `0.0.0.0` to `127.0.0.1`, and matching environment/probed connections merge. Discovery lists candidates without issuing inference requests.

For **direct Bedrock Mantle**, configure the inference base URL and protocol from the model card's **Programmatic Access** table. Depending on the model, OpenAI-compatible inference uses `/v1` or `/openai/v1`; Messages uses its documented base such as `/anthropic/v1` (the complete `/anthropic/v1/messages` URL is accepted too). Agentnik preserves that route and lists models separately at the same origin's `/v1/models`, using bearer authentication for discovery even when inference uses the Messages protocol. The connection editor displays both URLs. A catalog entry does not establish route compatibility or account access; save separate connections for models requiring different routes. Agentnik does not guess from the model name or retry inference on another route. LiteLLM connections continue using their configured gateway URLs. See [AWS model discovery](https://docs.aws.amazon.com/bedrock/latest/userguide/models-get-info.html), [Chat Completions routing](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html), and [Messages routing](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html).

API keys use `keyring` and the OS credential store, with explicit plaintext fallback. Keys are excluded from session history and ordinary exports. Endpoint redirects are rejected to prevent silent credential forwarding. Capability verification is scoped to the connection, endpoint, protocol, and model; listing a model does not prove tool or decision compatibility.

Sessions use local SQLite storage. Default data directories are `%LOCALAPPDATA%\Agentnik` on Windows, `~/Library/Application Support/Agentnik` on macOS, and `$XDG_DATA_HOME/agentnik` (or `~/.local/share/agentnik`) on Linux. Override with `--data-dir PATH` or `AGENTNIK_HOME`.

## TLS settings

By default, model endpoints, search and retrieval provider APIs, and remote MCP servers verify TLS certificates and hostnames. **TLS settings** in the main toolbar offers **Relax TLS verification globally** for networks that intercept TLS. Save the setting and restart Agentnik to apply it; the toolbar shows **TLS: relaxed** while it is active. Turning it off and restarting restores verification. Direct public-page reads already use relaxed TLS independently of this setting.

Relaxed TLS permits a network intermediary to impersonate services, read API keys, prompts and other traffic, and alter responses. Public-address checks, redirect policies, and other request limits still apply. The setting affects Agentnik network transports, not external processes launched by approved shell commands or local MCP servers, nor browsing inside hosted providers.
