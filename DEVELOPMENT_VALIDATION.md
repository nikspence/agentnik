# Controlled live checks and Windows development builds

## Offline tests

Run `python tools/run_offline_tests.py` with the project dependencies installed. The runner uses a temporary profile, removes inherited provider credentials and proxy settings, and blocks unexpected Python DNS and network connections. Tests may connect to loopback servers they create in the same process; blocked attempts fail the run even if application code catches the error. The guard also loads in ordinary Python child processes. It is not an operating-system firewall and cannot prevent network access by native libraries or arbitrary non-Python child processes; do not run untrusted code as part of the test suite. Use an isolated virtual environment to keep dependencies separate from user-installed packages.

For an optional real-server interoperability check, run `python tools/mcp_sdk_smoke.py` in an environment with MCP Python SDK 2.x installed separately. It starts a disposable SDK stdio server with synthetic in-memory data and checks discovery, a structured tool call, standalone and request-scoped server pings, a resource, a resource template, and a prompt. Add `--https` to exercise a loopback Streamable HTTP server over TLS 1.2 or newer with a temporary certificate trusted only by the test process, `--https-cancel` to check a stopped call's cancellation notification and server-side termination, `--https-resume` to verify response resumption after SDK-initiated stream closure without repeating the call, or `--https-standalone-resume` to verify standalone stream reconnection and notification replay. Use --https-oauth-discovery for metadata, --https-oauth-flow for the internal PKCE exchange, --https-oauth-refresh for token rotation, and --https-oauth-ui for the settings-to-MCP path, and --https-oauth-dynamic for dynamic registration, using a simulated browser callback and mocked credential store over verified loopback HTTPS. HTTPS also requires `cryptography` and `uvicorn`. These modes make no inference or Internet requests, and these packages are not Agentnik runtime dependencies. The check is separate from the hermetic test suite and does not qualify arbitrary servers or Internet deployments.

## Qt-free SSH smoke test

From the checkout, set `PREVIEW_DIR` to the absolute directory containing the extracted preview wheel and run the following in a POSIX shell. Use the fixture from the wheel's source revision, or build a wheel from the current checkout before running the current fixture. Substitute the wheel filename if it differs.

```sh
docker run --rm \
  --mount "type=bind,src=$PREVIEW_DIR,dst=/preview,readonly" \
  --mount "type=bind,src=$PWD/tools,dst=/tools,readonly" \
  python:3.12-slim sh -c 'tr -d "\015" </tools/ssh_terminal_smoke.sh | sh -s -- /preview/agentnik-0.12.0rc7-py3-none-any.whl'
```

The fixture installs dependencies in the disposable container, then uses a fresh non-root account and a throwaway key over loopback OpenSSH. It checks the installed launcher without Qt, credential-free connection transfer, bulk run-budget changes, a CSI-u Ctrl+Enter sequence producing one multiline request, a reviewed project edit and machine-scope directory creation, Ctrl+C cancellation, noninteractive session discovery, and exact-ID resume without replay. Reopening a machine-scope session starts in project scope. It checks that a synthetic API key does not echo and opts into plaintext storage only inside the disposable test profile. Model responses come from a loopback fixture. No live inference is used.

## Compatibility CLI

`tools/live_compat.py` prints a plan by default. It does not read key files or make requests until you add `--execute`. Always select the exact URL, alias, protocol, and route. Use `chat`, `managed`, or `hosted`; managed currently requires `--backend ollama` and a separate Ollama search key. Hosted accepts only the official OpenAI Responses endpoint. There is no automatic model selection, retry, or route fallback. System One remains a separate test.

PowerShell example (planning only):

```powershell
.\.venv\Scripts\python.exe tools/live_compat.py --url https://gateway.example/v1 --model YOUR_ALIAS --protocol responses --route managed --backend ollama
```

When you choose to issue the displayed requests, add `--execute --key-file C:\keys\litellm.txt --search-key-file C:\keys\ollama.txt --output test-output\your-unique-report.json`. Create the output parent directory first. Reports will not overwrite existing files. Do not put credential files in the repository. `--no-stream` selects non-streamed requests. A chat check needs only the model key; omit search-key/backend flags. Local anonymous endpoints can omit the model key file.

Checks use the bounded protocol parsers and GUI research limits, with at most three model requests, two tool calls, 45 seconds per request and 120 seconds per turn. Ctrl+C requests cancellation; upstream work/billing may continue. Reports contain revision/dirty state, timestamp, selected scope, sanitized numeric metrics, failure category/status, tool/source/citation counts and continuation evidence. They omit transcripts, thinking, raw upstream errors, search content, and keys. They do not modify application settings or mark other models compatible. A completed answer without the requested real search/fetch is not a research pass. Citation link generation is checked headlessly; native UI behavior needs separate testing. Exit codes: 0 pass/plan, 1 failed or incomplete evidence, 2 invalid arguments/setup, 130 cancelled.

Unit tests mock endpoints and do not issue live requests. Separately check native dialogs, streaming presentation, history, cancellation, credentials and other workflows on each target platform. Record the exact environment and scope; see [validation](VALIDATION.md) for remaining gaps.

## Dedicated Windows build environment

`tools/build_release.py` targets Windows x64 onedir ZIPs. It plans by default and never tags, pushes, publishes, signs, or replaces an existing build directory/archive. The label identifies a development artifact; it does not change the package version. A release needs an explicitly selected version synchronized across metadata, notes and tag.

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe tools/build_release.py --label dev-d2
.\.venv-build\Scripts\python.exe tools/build_release.py --label dev-d2 --build --smoke
```

The build refuses system-site-package environments and mismatched top-level build pins. It requires identifiable source and a clean working tree by default. Use `--allow-dirty` explicitly for an uncommitted development build; the manifest records that state. Every label gets a new `dist/build-LABEL` directory; choose another label for a repeat build instead of overwriting prior output. Failed builds remain available for diagnosis.

Assembly copies README, VALIDATION and the Apache 2.0 LICENSE alongside the executable, collects available installed distribution notices and Python's license, and records Python/OS/architecture, package versions, source revision and optional smoke result in `BUILD-MANIFEST.json`. Packaging checks the executable, documentation, all branding assets and Qt Windows plugin; checks ZIP integrity/contents; and writes a SHA-256 sidecar. The whole Agentnik directory must be distributed. The build environment has no user configuration or key files copied into it.

Packaging also checks that each compiled `.qm` translation catalog in the source tree is present in the frozen bundle with identical bytes before creating the archive. Missing or altered catalogs fail the build. This checks inclusion and identity; language rendering still requires a separate UI check.

Packaging also requires the native `regex` module used for time-limited Code searches and the Tree-sitter core, JavaScript, TypeScript, Go, Rust, C#, and Java grammar modules used for code outlines. Their versions are pinned in the build environment; release assembly checks that all native modules are present.

`--smoke` uses `tools/frozen_smoke.py` (Windows API calls through Python, without changing PowerShell execution policy) to wait for the real process-owned Qt window and temporary SQLite database, request a graceful close and require exit code 0. This is a startup smoke check on the build host, not clean-machine, full native workflow, credential-store, TLS/provider, or macOS/Linux validation. It does not issue inference; normal startup may perform read-only local endpoint discovery.

Top-level build versions are pinned to the tested Windows environment. Transitive versions are recorded in each manifest rather than fully locked. Collected notices are not a completed license audit of every bundled library; that audit and per-platform signing/distribution requirements remain release gates.


## Native terminal keyboard check

Use a preview wheel in a disposable profile and open a nonempty saved session in the terminal emulator you want to qualify. No provider request is needed. Note the OS, emulator and version, whether the session is local or over SSH, and whether the keys came from a physical keyboard or a macro.

1. Type a two-line draft. Verify that Ctrl+Enter inserts a newline if the emulator sends it distinctly. If it does not, verify Ctrl+J. Enter should submit and Alt+Enter should not be needed.
2. With a draft still in the composer, press Up to recall a prior prompt and Down to restore the draft.
3. Press Ctrl+T to open the transcript. Verify Ctrl+U and Ctrl+D move by half a page and PageUp and PageDown move by a page. Use enough existing output to see the difference.
4. Press Q to return. Confirm that the draft is unmodified, then press Ctrl+C to discard it without starting a request.

To test Enter without sending a request, submit a multiline draft whose first line is an unknown slash command. The terminal should report the unknown command and return to the prompt. Use a saved session that already has past prompts for the Up and Down check.
