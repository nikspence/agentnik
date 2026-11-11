# Managed search providers

Agentnik runs search as an application tool, independently of the model's inference provider. A local or gateway model can use these tools if it supports Agentnik's configured managed tool protocol. Chat requires Web access and explicit managed-tool enablement for that endpoint/model; Code requires Allow web research. System One Decision queries do not acquire search tools.

## Setup

Open **Search settings…** in Code, or **Web settings… → Manage ordered search backends…** in Chat. Add a named profile, choose its provider, and enter the provider's API key. Saved keys use the **Agentnik Web** OS credential store; plaintext storage is an explicit fallback. Editing a profile preserves its provider and credential when the key is blank; create a new profile to change providers. The separate key field in Chat Web settings updates the first profile while preserving its provider.

| Provider | Environment alternative | Implemented API |
| --- | --- | --- |
| Brave Search | `BRAVE_SEARCH_API_KEY` | `GET https://api.search.brave.com/res/v1/web/search`; query and result count; ranked web snippets |
| LangSearch | `LANGSEARCH_API_KEY` | `POST https://api.langsearch.com/v1/web-search`; query/count, `contents.text=false`; search snippets |
| Firecrawl | `FIRECRAWL_API_KEY` | `POST https://api.firecrawl.dev/v2/search`; query/limit and web source only; no scrape options |
| Firecrawl (keyless) | None | Same `/v2/search` REST endpoint, with no Authorization header |
| Exa | `EXA_API_KEY` | `POST https://api.exa.ai/search`; explicit `auto` mode with highlights, bounded `numResults` |
| Parallel | `PARALLEL_API_KEY` | `POST https://api.parallel.ai/v1/search`; explicit `basic` mode and bounded `max_chars_total` |
| Ollama search | `OLLAMA_WEB_API_KEY` | Existing search adapter; Code limits eligibility to direct Ollama Cloud connections |

Choose any of the supported providers or keyless mode; up to five configured profiles participate, in saved order followed by environment profiles (Brave, LangSearch, Firecrawl, Exa, Parallel, Ollama) when space remains. A saved canonical environment profile overrides that environment entry. Removing a saved profile does not unset an environment variable. Keys are not inferred from model credentials or copied into model context, session history, or ordinary exports. The key supplied for development testing was not saved by that test.

LangSearch currently advertises a free plan with account/token/rate allowances. Firecrawl offers free access with limits as well as paid plans. Select **Firecrawl (keyless)** to use search with no API key. It is also the automatic fallback after configured profiles, or the default when none are configured. Its daily quota is shared by public IP. Selecting keyless mode never consumes a saved or environment Firecrawl key. Self-hosted Firecrawl is not part of this adapter. Check current [LangSearch pricing](https://langsearch.com/pricing) and [Firecrawl pricing](https://www.firecrawl.dev/pricing) before choosing a plan. Free access does not remove rate limits.

Brave Search omits individual result URLs that fail public-address validation; it never fetches or displays them. In Code, an access-blocked search disables further searches for the run, reports an HTTP status when available, and permits work with sources already obtained. It does not retry the blocked search or bypass access controls.

## Routing, limits, and disclosure

Chat and Code use **configured profiles → Firecrawl Keyless → Google scrape**. With no configured profiles, keyless Firecrawl is first. If an explicit keyless profile is present, its chosen position is preserved and no duplicate is appended. The five configured-profile budget is unchanged; at most two built-in fallback entries can extend the chain, so each logical search considers at most seven entries. These defaults do not persist new settings or start requests by themselves: Web access/Allow web research and the model's tool call are still required.

Eligible explicit rejections (authentication, rate/quota limits, known unsupported operations, or temporary HTTP 503) can advance services. Access restrictions, malformed replies, timeout/disconnection, cancellation, and uncertain submissions stop fallback. Empty results are passed back without another service call. A rate-limited or authentication-rejected profile is skipped for the rest of that run. Short Retry-After guidance can be honored within the wait budget; long guidance prevents retrying that service but does not prevent moving to a different configured/fallback provider. Google challenges stop automatic search; Code can still read known public URLs. Fallback events and source provenance are visible; Chat retains its configured hosted/managed route policy and inference model.

Only generated queries and bounded result options are submitted, not full conversations, project files, model identities, or image attachments. Queries can still reveal task-derived information. Keyed credentials travel in headers only to fixed HTTPS provider endpoints; keyless Firecrawl and Google receive no search API key; redirects are rejected. Requests and results retain the existing time/byte/context limits. Brave queries are limited to 600 characters/75 words; LangSearch and Firecrawl queries are limited to 500 characters; Exa and Parallel use the existing 1,000-character tool query bound. Parallel may return more results than requested locally; Agentnik retains at most the configured result count and requests at most the smaller of the context budget or 3,000 characters per configured result in total excerpts.

Result URLs pass public-address validation before they become sources. Search service internal navigation is outside Agentnik's direct transport controls, so strict public-only navigation disables these services. Known public URLs remain available through Code's credential-free page reader. Firecrawl crawling/browser and LangSearch full-text modes remain unavailable. A filtered direct page read can use the separate provider retrieval fallback described below. Snippets are evidence excerpts rather than proof that the complete page was fetched by Agentnik.

## Evidence

One authorized Brave request on 2026-11-09 returned three results and snippets, including `doc.qt.io`. No model inference was submitted during that check and the supplied key remained in memory. Offline fixtures cover request/auth shapes, response validation, private destinations, profile persistence, ordered fallback, strict-policy exclusion, Qt provider selection, and Chat/Code continuation without credential disclosure. Firecrawl Keyless was also tested live without an Authorization header and returned three public results with snippets, including Qt documentation. LangSearch was tested with two queries: the initial query returned off-topic casino-related domains (the term “slots” was ambiguous), while `site:doc.qt.io PySide6 signals slots` returned three Qt documentation pages and snippets. Keys were not saved. Keyed Firecrawl, Exa, and Parallel still have offline contract checks only; end-to-end live model compatibility remains unverified.

API references: [Brave Web Search](https://api-dashboard.search.brave.com/api-reference/web/search/get), [LangSearch Web Search](https://docs.langsearch.com/api/web-search-api), [Firecrawl Search](https://docs.firecrawl.dev/api-reference/endpoint/search).

## Exa and Parallel

Both providers are selectable in Chat and Code search profiles and use the same separate credential store, ordered fallback policy, fixed HTTPS transport, public-result checks, and Source records as the other providers. No SDK dependencies were added. API keys use `EXA_API_KEY` and `PARALLEL_API_KEY`, or saved profiles.

- **Exa:** `POST https://api.exa.ai/search`, `x-api-key`, `query`, bounded `numResults`, explicit `type=auto`, and `contents.highlights=true`. Returned `highlights` become excerpts, retained at up to 3,000 UTF-8 bytes per source. Highlight retrieval is a provider content feature and may affect charges; selecting this profile enables it. Search requests do not ask for full text, summaries, agents, or deep-search modes. Filtered direct page reads may separately use its Contents API for page text.
- **Parallel:** `POST https://api.parallel.ai/v1/search`, `x-api-key`, one generated `search_queries` entry, explicit `mode=basic`, and `max_chars_total`. Returned `excerpts` become bounded Sources. No conversation-derived objective beyond the generated query, client-model identity, or session ID is sent. A filtered direct page read may separately use its Extract API for bounded excerpts; no task workflows are launched; the advanced default is not used. Results are locally capped even if the service returns more.

Missing excerpt fields yield metadata-only sources, with an empty excerpt rather than fabricated page content. Invalid excerpt shapes fail validation. Both adapters have offline API-contract, credential, public-address, cancellation, fallback, and model-continuation tests, but no live requests have been made. Provider rate limits and charges still apply. The five configured-profile budget includes both saved and environment profiles; if all six provider environment variables are present, the last one has no slot unless you change configuration or unset another variable.

API references: [Exa Search](https://exa.ai/docs/reference/search), [Parallel Search](https://docs.parallel.ai/api-reference/search/search).


## Provider page retrieval after a filtered direct read

Page reads remain direct first and accept unverified TLS certificates and hostnames to support TLS-inspecting networks. An intermediary can impersonate a site or modify its content; direct page content is untrusted. Provider API connections verify TLS by default; the optional global relaxed TLS setting also disables verification for these connections. Recognized branded block pages (including Zscaler), TLS errors, connection resets or refusals, and HTTP 404, 410, 429 or 503 can trigger provider retrieval. Initial URL and DNS addresses must be public before the URL is sent externally. URL-policy failures, private redirect destinations, generic HTTP 401/403/451 site denials without a recognizable network-filter page, timeout, cancellation, and strict public-only mode do not trigger fallback. Filter detection is deliberately narrow and is not a guarantee of recognizing every gateway.

Only configured, credentialed retrieval-capable profiles are considered, in order. Firecrawl Keyless is never used for page-fetch fallback, including when explicitly configured for search. Brave, LangSearch, and Google are skipped because Agentnik has no URL-retrieval adapter for them. At most five configured profiles can be considered. Only definite eligible provider rejections permit switching; ambiguous outcomes and access restrictions remain terminal. If no eligible provider exists, the original direct-fetch failure is reported.

| Provider | Retrieval request |
| --- | --- |
| Firecrawl | `/v2/scrape`, one `url`, markdown and main content only; requires a configured API key |
| Exa | `/contents`, one URL and page text |
| Parallel | `/v1/extract`, one URL, excerpts capped by `max_chars_total=8000` |
| Ollama | `/api/web_fetch`, one URL; Code retains direct-Ollama-only eligibility |

The public page URL (including its query string) is sent to the chosen service; full conversation, project files, model identity, browser cookies, and local proxy credentials are not. API keys go only to the fixed provider API endpoint, never the target site. Provider-internal redirects cannot be pinned by Agentnik, so strict navigation disables this path. Returned final URLs, when reported, are validated again. API content is bounded by the shared transport/time/context budgets and clipped to 8,000 UTF-8 bytes. Sources identify provider retrieval rather than claiming a direct page read. Code's direct page path still discovers bounded same-host links; provider fallback returns content without fabricating link discovery.

This is offline-qualified using filter/TLS fixtures and mock provider/model responses. No real Zscaler deployment or live provider retrieval request has been tested. See [Firecrawl Scrape](https://docs.firecrawl.dev/api-reference/endpoint/scrape), [Exa Contents](https://exa.ai/docs/reference/get-contents), [Parallel Extract](https://docs.parallel.ai/api-reference/extract/extract), and [Ollama web fetch](https://docs.ollama.com/capabilities/web-search).
