# Milestone D live test plan

Use this checklist with real endpoints. Record results for the exact connection, alias, protocol, and route; results do not certify every model in the gateway. The v0.1.0 release predates D, so use a current development build. Start with short, low-cost prompts. Do not put credentials, private data, full transcripts, or raw config in notes or screenshots.

## Current target selection

Account feedback: Anthropic aliases are listed but unavailable; skip Anthropic live tests. Prioritize ChatGPT 6+ aliases, with DeepSeek or Kimi as additional targets. Do not mistake model discovery for account access. Messages live compatibility remains unverified until an accessible target supports that protocol.

## Setup

Create separate Agentnik connections so each result has a clear scope:

| Connection | Base URL | First protocol | Notes |
| --- | --- | --- | --- |
| LiteLLM Bedrock Mantle | `https://gchat.glovis.app:4000/` (or your configured API base) | Messages for a Claude alias | Anthropic models are served through LiteLLM on Mantle; you do not need to create a direct Anthropic key for this route if LiteLLM supplies upstream auth. |
| LiteLLM OpenAI subscription passthrough | Same gateway | Responses, then Chat Completions if enabled | This requires a distinct subscription-backed LiteLLM setup. A ChatGPT Plus login alone is not an API key. Confirm the gateway's client-auth and route configuration. |
| LiteLLM Ollama Cloud | Same gateway | Chat Completions first | Record the LiteLLM alias and underlying model/provider if visible. |
| Ollama Cloud direct (optional comparison) | Account's direct Ollama API base | Native Ollama if available; otherwise only a documented compatible protocol | Compare direct access with the gateway path. It still sends inference to a cloud service. |

Use exact model aliases from your LiteLLM dashboard/config; do not assume all 100+ aliases share capabilities. Save keys only in Agentnik's connection UI. LiteLLM may authenticate the client with a virtual key while separately using subscription or provider credentials upstream. Check usage before and after each optional research test. Keep Web access off for ordinary chat.

## 1. Basic chat and connection checks

For each connection and one inexpensive alias:

1. Run Test Connection if available. Record endpoint, protocol, alias, and sanitized error or success.
2. Send: `Reply with exactly: Agentnik live check passed.` Confirm one response, streaming, and a responsive UI.
3. Send a short follow-up question. Confirm the correct conversation and connection remain active.
4. Cancel one longer generation. Check that the UI stops waiting and other tabs remain usable. Cancellation may not stop upstream compute or billing.
5. Restart Agentnik and reopen the chat. Confirm history displays without resending the prompt.

Test the protocol actually configured for each alias first. Then, in a fresh chat, compare Responses, Chat Completions, and Messages only when LiteLLM says the alias supports them. Record whether text/thinking render, whether the stream completes, and whether usage is present. Missing usage is acceptable; don't infer costs from token counts. A generic gateway error does not prove a model lacks chat capability.

Claude on Bedrock Mantle is a useful Messages test. Recent LiteLLM versions document routing certain `bedrock_mantle/anthropic.claude-*` Chat Completions calls to Mantle's native Messages endpoint. Verify your deployed version and route; the public gateway address alone does not guarantee this behavior.

## 2. Managed research

This checks Agentnik tool calling plus the separate Ollama web-search service. A LiteLLM key does not automatically provide the Ollama search credential. Configure that credential in Agentnik first. Search queries and retrieved pages leave your machine; use non-sensitive queries.

For one model/protocol at a time:

1. With Web access off, ask a normal question and confirm no research activity appears.
2. Start a fresh chat, turn Web access on, choose **Agentnik only**, and ask: `Find the current official documentation page for LiteLLM Bedrock Mantle. Give me two short points and cite your sources.`
3. Watch Research activity. Confirm the tool call, source list, citations, and final answer appear. Open a source and check relevance.
4. Reopen the chat and confirm sources/activity persist without rerunning research.

Suggested order: a known tool-capable Chat Completions alias through LiteLLM; a Claude Bedrock alias using Messages; then one Ollama Cloud alias through LiteLLM. Ordinary chat success does not prove tool support. If the model or gateway rejects tools or reports unsupported capability, record the sanitized result and stop for that model/protocol.

## 3. Hosted search and routing (optional)

The current hosted-search adapter targets the official OpenAI Responses endpoint. A LiteLLM Responses-compatible endpoint does not automatically provide the OpenAI hosted web-search tool; subscription passthrough may not expose it. Do not select **Provider only** for LiteLLM unless your gateway administrator confirms that exact endpoint supports hosted search.

If you have an official OpenAI Responses connection and choose to test it, use a fresh chat, Web access on, and **Provider only**. Ask a short current factual question and verify source/progress rendering. Then test **Provider first** separately. Test **Agentnik first** only with a managed route already proven above. Confirm model/connection identity stays fixed.

Do not intentionally induce timeouts or ambiguous failures to force fallback; this can duplicate billed work. If a natural explicit unsupported-tool response occurs, record it before retrying. Your LiteLLM Mantle and Ollama Cloud paths should use **Agentnik only** unless hosted-search support is confirmed. The current strict navigation policy blocks both current research routes before inference, so it is not a search-test setting.

## 4. System One and UI checks

System One is a separate structured decision API. Chat success does not establish decision compatibility. Test only a model configured for this feature: submit one non-sensitive decision with two ordered questions and criteria; confirm order and structured results. If testing images, use a harmless public/test image. Cancel a decision and verify no stale result overwrites later work.

Also edit a prior prompt, confirm it restores as a draft without sending, then resend and verify both turns remain. Check light/dark themes, citations, activity, dialogs, and robot/wordmark readability.

## Record and report

Record one row per exact alias/protocol/route. Include build/revision, connection label, alias and underlying provider (if known), protocol, route, stage, pass/fail/unavailable/not attempted, sanitized behavior/error, whether usage appeared, and timestamp/request ID if useful. Never share keys, authorization headers, raw configs, private prompts, or full transcripts. Mark untested models **not tested**; do not generalize from one alias.

| Date/build | Connection + alias | Protocol | Route | Stage | Result / sanitized evidence |
| --- | --- | --- | --- | --- | --- |
| | | | | | |
| | | | | | |
| | | | | | |

## References

- [LiteLLM subscription setup](https://docs.litellm.ai/docs/subscriptions) and [client authentication overview](https://docs.litellm.ai/docs/proxy/client_setup/overview): subscription-backed routing is separate from ordinary gateway credentials.
- [LiteLLM Responses passthrough](https://docs.litellm.ai/docs/response_api_native_passthrough): endpoint behavior depends on the deployment; some providers are bridged through Chat Completions.
- [LiteLLM provider list](https://docs.litellm.ai/docs/providers): provider availability does not establish features for a specific alias.
- [Ollama Cloud models](https://ollama.com/blog/cloud-models) and [tool support](https://ollama.com/blog/tool-support): cloud inference is remote, and tool support is model-dependent.


## Automated headless companion

Use `tools/live_compat.py` for one exact endpoint/model/protocol/route at a time. It prints a plan by default and only reads keys/issues requests with `--execute`. It uses the real bounded protocol/research code, no automatic retries or route/model fallback, and sanitized evidence reports. Managed checks distinguish completed search, direct page retrieval, continuation, and citation link generation; a plain answer alone is not a search pass. Headless results do not replace the application checklist above. See [the CLI guide](DEVELOPMENT_VALIDATION.md) for commands, key-file handling, output paths, and exit codes.
