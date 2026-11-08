# Milestone D initial LiteLLM live results

Recorded: 2026-11-08T20:37:02+00:00. Source checkpoint: c85ba94 plus documentation-only working changes. Windows source environment; Agentnik transport, request builders, streaming parsers, and managed loop exercised headlessly. No native GUI interaction was tested.

Gateway model discovery returned **115 aliases**. The supplied C-drive key path was absent; the matching file on D: was used. Credentials were loaded only in memory and were not included in application storage or this report.

## Ordinary streamed chat

| Alias | Protocol | Result | Elapsed |
| --- | --- | --- | --- |
| `us-west-2/anthropic.claude-haiku-4-5` | messages | HTTP 403: upstream Mantle account does not have this Claude model available | 0.98 s |
| `chatgpt/gpt-5.1-codex-mini` | responses | HTTP 400: upstream rejects this model for the ChatGPT account route | 5.3 s |
| `ollama-cloud/gpt-oss:20b` | chat | Pass: exact expected reply after trimming whitespace | 0.92 s |
| `us-east-1/anthropic.claude-sonnet-5` | messages | HTTP 403: upstream Mantle account does not have this Claude model available | 1.16 s |
| `chatgpt/gpt-6-luna` | responses | Pass: exact expected reply after trimming whitespace | 4.41 s |
| `us-west-2/google.gemma-3-4b-it` | chat | Pass: exact expected reply after trimming whitespace | 2.03 s |

No retries or automatic model/route fallback were used. Alternative aliases were separate explicit checks. Alias listing does not establish account availability. The successful Gemma alias validates its LiteLLM path, not direct Mantle API compatibility or independently verified upstream mapping.

## Real model calls with a local tool fixture

| Alias | Protocol | Result | Model requests |
| --- | --- | --- | --- |
| `ollama-cloud/gpt-oss:20b` | chat | ok; 1 fixture call; 1 source; returned check value with `[S1]` | 2 |
| `chatgpt/gpt-6-luna` | responses | ok; 1 fixture call; 1 source; returned check value with `[S1]` | 2 |

Each model requested `web_search`, received a synthetic local source containing a check value, and completed using that value with a matching citation. These checks used the actual Agentnik managed loop and protocol adapters. Search/fetch handlers did not contact external websites or the Ollama search service. This is live model tool-calling/continuation evidence, not end-to-end web-research evidence. Usage was reported for both model requests in each fixture turn.

## Scope and remaining checks

- Six standalone streamed-chat submissions and four model submissions across two fixture turns: ten model requests total, plus model discovery. No spending total is inferred from tokens.
- Messages requests reached the gateway/upstream error path but did not complete successfully; Messages streaming and tool continuation remain live-unverified.
- Real Ollama search/page fetch, hosted search, multi-call tools, reasoning continuation, follow-up persistence, cancellation, GUI workflows, and frozen distribution behavior were not tested here.
- No System One inference, direct Ollama Cloud requests, credential writes, or broad scan of all aliases was performed.
- Local sanitized detail files are under ignored `test-output/`; they contain only test prompts/results/metrics and sanitized errors. Keep raw gateway errors private if they include deployment details.

Next: resolve Claude model availability in the gateway/account, then run a successful Messages chat and tool-continuation check. End-to-end research additionally needs a separately configured Ollama search credential; this LiteLLM key has not been treated as a search-service key.

## Authorized real web search attempt

Using the separately supplied Ollama Cloud/search key, `ollama-cloud/gpt-oss:20b` through LiteLLM requested `web_search` for official Ollama API documentation. The actual search-service request failed with `Unsupported web content type`. Agentnik rejected the response at its transport content-type check before parsing search results. No sources or final answer were produced; page fetching was not reached. There was one model request, no retry or fallback, and elapsed time was about 4.1 seconds. This is a failed end-to-end search check, not a successful credential or search compatibility claim. Next step: inspect the returned response status/content-type safely and determine whether the service contract or an intermediary caused the mismatch; retain strict response validation. Sanitized run detail is in ignored `test-output/litellm-real-web.json`.


## Search content-type fix and successful live recheck

The authorized header inspection found HTTP 200 with `Content-Type: text/html; charset=utf-8`, no content encoding, and a valid JSON object containing `results`. Ollama search was labeling JSON as HTML. The transport now accepts that label only for a POST to the exact `https://ollama.com/api/web_search` URL with redirects disabled; JSON parsing and search-result schema checks still apply. Other endpoints and content-type checks remain restricted.

A real recheck using `chatgpt/gpt-6-luna` through LiteLLM Responses completed one Ollama search and one direct public-page fetch. It returned five search sources and one fetched source, then answered with citations to S1 and S6. Three model requests completed in about 18.6 seconds, with usage reported. This establishes end-to-end managed search/fetch compatibility for this exact route, not hosted search or native GUI validation. Detail is under ignored `test-output/litellm-real-web-fixed.json`.

All 91 offline tests and compile checks passed. Regression coverage accepts mislabeled valid results, rejects actual HTML and wrong JSON structure, and rejects the exception on other endpoints or with redirects enabled. Account feedback confirms Anthropic is unavailable despite its listed aliases; further live targets prioritize ChatGPT 6+, DeepSeek, or Kimi.
