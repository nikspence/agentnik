# Validation and compatibility

The automated suite uses mocked endpoints, temporary data and offscreen Qt. It does not establish live model or platform compatibility. See [development and builds](DEVELOPMENT_VALIDATION.md) for commands and optional live checks; ordinary tests do not issue inference requests.

## Scoped observations

- A live terminal Code run with scripted input on Windows used GPT-6.1 Terra through OpenRouter Chat Completions to call `view_image` on a synthetic 16:9 PNG. The first request contained no image. The continuation carried the PNG and correctly identified both shapes and their positions. This qualifies inspection for that model and route, not live image generation or the full presentation-skill workflow.

- Authenticated loopback OpenSSH tests in disposable Linux containers verified plain Enter, the current non-Git project, and session-scoped permission changes. Interactive connection setup worked with an unavailable keyring and explicit consent to the local plaintext fallback. A loopback model fixture received the test credential and proposed a file edit that Agentnik applied after approval. A separate test verified that Ctrl+C returned to the prompt while the endpoint was withholding a response. Reconnecting resumed the same session without replay in both cases. These tests do not establish live-provider behavior over SSH or server-side cancellation.

- The Qt-free installed-wheel matrix passed on hosted Windows, macOS, and Ubuntu with Python 3.12 and on Ubuntu with Python 3.11 at `339869c`. A fresh Windows Python 3.11 install also passed the terminal suite outside the checkout. The tests include PDF text attachments, not OCR or page rendering. [Hosted wheel checks](https://github.com/nikspence/agentnik/actions/runs/45872604381)

- Build-only preview artifacts include the source commit and SHA-256 checksums. The wheel and source archive checksums were verified after downloading the `0edaf87` artifact. That run did not publish to PyPI. [Build-only artifact](https://github.com/nikspence/agentnik/actions/runs/45872209195)

- On Windows, a live terminal Code smoke test used OpenRouter GPT-6.1 Terra over streaming Chat Completions. With scripted prompt input in a temporary non-Git folder, the model proposed one file edit, waited for approval, wrote the expected bytes, and returned a final answer after two provider requests. The saved session reopened without replay. This qualifies that coding path, not native keyboard behavior, SSH, or LiteLLM.
- A separate Windows terminal Code smoke test used GPT-6.1 Terra through the G-Chat LiteLLM connection configured for Responses. Its catalog was reachable, the model proposed and completed one approved file write with the expected bytes, and it returned a final answer after two requests. Reopening the same session sent no provider request. Prompts were scripted and data was temporary, so this does not qualify native keyboard or SSH behavior.

- Selected Code, Chat and research tasks have completed through local Ollama, OpenRouter and LiteLLM routes. These observations cover individual models and tasks, not all tools or providers.
- OpenRouter and the configured LiteLLM image passthrough have generated and edited images. A live Code model inspected an image, and live subagents created sample slide files; the complete editable PowerPoint workflow remains unqualified.
- On Windows, the optional SDK smoke test passed against MCP Python SDK 2.3.0 using protocol 2025-11-25 over stdio and verified loopback HTTPS: discovery, a synthetic structured tool call, standalone and request-scoped server pings, a resource and template read, prompt retrieval and HTTPS session shutdown. In a separate HTTPS cancellation test, the server received a notification with the matching request ID and its synthetic operation ended. The HTTPS server enforced TLS 1.2 or newer and its temporary certificate was trusted only within the test process. Separate HTTPS tests confirmed response-stream resumption without repeating the synthetic call, and standalone-stream reconnection with replay of a notification sent during disconnection. Offline HTTP fixtures also check duplicate notification handling. Loopback HTTPS fixtures checked OAuth metadata discovery, an internal PKCE authorization-code exchange and refresh-token rotation. Synthetic settings-to-MCP sign-in flows, including dynamic client registration, were checked over loopback HTTPS with a simulated browser callback and mocked credential store. External OAuth providers, tasks, third-party servers, Internet deployment and model behavior remain unqualified.
- Windows clean-machine testing was reported complete, but its build and workflow scope were not specified. Each release's `BUILD-MANIFEST.json` records its build-host smoke result; that is not a separate clean-machine qualification.

## Remaining qualification

- Verify model and protocol combinations for coding, research, MCP, hosted search, image workflows and System One advice independently; model listings do not prove capability.
- Qualify native workflows, cancellation, credentials, TLS and accessibility by platform. macOS and Linux clean-machine testing remain outstanding.
- Complete signing and the bundled-library license audit. Release archives record their source revision, dependencies and smoke results.

See the [release notes](RELEASE_NOTES.md) and [roadmap](AGENTNIK_PLAN.md); historical test narratives remain available in Git.
