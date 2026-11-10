# Controlled live checks and Windows development builds

## Compatibility CLI

`tools/live_compat.py` prints a plan by default. It does not read key files or make requests until you add `--execute`. Always select the exact URL, alias, protocol, and route. Use `chat`, `managed`, or `hosted`; managed currently requires `--backend ollama` and a separate Ollama search key. Hosted accepts only the official OpenAI Responses endpoint. There is no automatic model selection, retry, or route fallback. System One remains a separate test.

PowerShell example (planning only):

```powershell
.\.venv\Scripts\python.exe tools/live_compat.py --url https://gateway.example/v1 --model YOUR_ALIAS --protocol responses --route managed --backend ollama
```

When you choose to issue the displayed requests, add `--execute --key-file C:\keys\litellm.txt --search-key-file C:\keys\ollama.txt --output test-output\your-unique-report.json`. Create the output parent directory first. Reports will not overwrite existing files. Do not put credential files in the repository. `--no-stream` selects non-streamed requests. A chat check needs only the model key; omit search-key/backend flags. Local anonymous endpoints can omit the model key file.

Checks use the bounded protocol parsers and GUI research limits, with at most three model requests, two tool calls, 45 seconds per request and 120 seconds per turn. Ctrl+C requests cancellation; upstream work/billing may continue. Reports contain revision/dirty state, timestamp, selected scope, sanitized numeric metrics, failure category/status, tool/source/citation counts and continuation evidence. They omit transcripts, thinking, raw upstream errors, search content, and keys. They do not modify application settings or mark other models compatible. A completed answer without the requested real search/fetch is not a research pass. Citation link generation is checked headlessly; native UI behavior needs separate testing. Exit codes: 0 pass/plan, 1 failed or incomplete evidence, 2 invalid arguments/setup, 130 cancelled.

Unit tests mock endpoints and do not issue live requests. Use the manual application checklist in [MILESTONE_D_LIVE_TEST_PLAN.md](MILESTONE_D_LIVE_TEST_PLAN.md) for dialogs, actual streaming presentation, history, cancellation, and other native workflows.

## Dedicated Windows build environment

`tools/build_release.py` targets Windows x64 onedir ZIPs. It plans by default and never tags, pushes, publishes, signs, or replaces an existing build directory/archive. The label identifies a development artifact; it does not change the package version. Keep v0.1.0 artifacts/tag intact. A future actual release still needs an explicitly selected version synchronized across metadata, notes and tag.

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe tools/build_release.py --label dev-d2
.\.venv-build\Scripts\python.exe tools/build_release.py --label dev-d2 --build --smoke
```

The build refuses system-site-package environments and mismatched top-level build pins. It requires identifiable source and a clean working tree by default. Use `--allow-dirty` explicitly for an uncommitted development build; the manifest records that state. Every label gets a new `dist/build-LABEL` directory; choose another label for a repeat build instead of overwriting prior output. Failed builds remain available for diagnosis.

Assembly copies README, VALIDATION and the Apache 2.0 LICENSE alongside the executable, collects available installed distribution notices and Python's license, and records Python/OS/architecture, package versions, source revision and optional smoke result in `BUILD-MANIFEST.json`. Packaging checks the executable, documentation, all branding assets and Qt Windows plugin; checks ZIP integrity/contents; and writes a SHA-256 sidecar. The whole Agentnik directory must be distributed. The build environment has no user configuration or key files copied into it.

Packaging also checks that each compiled `.qm` translation catalog in the source tree is present in the frozen bundle with identical bytes before creating the archive. Missing or altered catalogs fail the build. This checks inclusion and identity; language rendering still requires a separate UI check.

`--smoke` uses `tools/frozen_smoke.py` (Windows API calls through Python, without changing PowerShell execution policy) to wait for the real process-owned Qt window and temporary SQLite database, request a graceful close and require exit code 0. This is a startup smoke check on the build host, not clean-machine, full native workflow, credential-store, TLS/provider, or macOS/Linux validation. It does not issue inference; normal startup may perform read-only local endpoint discovery.

Top-level build versions are pinned to the tested Windows environment. Transitive versions are recorded in each manifest rather than fully locked. Collected notices are not a completed license audit of every bundled library; that audit and per-platform signing/distribution requirements remain release gates.
