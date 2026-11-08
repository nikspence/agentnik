# Working on Agentnik

Agentnik is a cross-platform Python desktop client for chat and Ollama System One decisions. Read `README.md` and the relevant implementation before changing behavior. Preserve existing user data and connection compatibility.

## Project layout

- `agentnik/core.py`: endpoint discovery, request formats, streaming, and decision validation.
- `agentnik/storage.py`: local SQLite session history, attachments, connection settings, and credential-store integration.
- `agentnik/tools.py`, `agentnik/research.py`: bounded tool contracts and managed research orchestration.
- `agentnik/ollama_tools.py`, `agentnik/responses_tools.py`, `agentnik/compat_tools.py`: protocol-specific structured streaming and continuation.
- `agentnik/hosted.py`, `agentnik/routing.py`, `agentnik/failures.py`: hosted search, scoped eligibility, conservative fallback, and shared attempt accounting.
- `agentnik/citations.py`: inline citation formatting from recorded sources/annotations.
- `agentnik/web.py`: dedicated public-address transport and Ollama search adapter.
- `agentnik/research_ui.py`: per-chat research settings, activity, and source rendering.
- `agentnik/ui.py`: PySide6 interface, background jobs, chat, and decision forms.
- `assets/`: the reusable robot SVG and current screenshots. `agentnik/assets/` contains packaged logo and icon variants; `tools/build_branding.py` rebuilds those assets.
- `tests/`: standard-library unit tests and offscreen Qt integration tests. `tools/live_smoke.py` performs optional baseline endpoint checks; `tools/live_compat.py` plans explicit compatibility checks and requires `--execute` for live requests. `tools/build_release.py` automates isolated Windows development archives; see DEVELOPMENT_VALIDATION.md.

## Development

Python 3.11 or newer is required. Install `requirements.txt` into a virtual environment or the selected Python installation. On Windows, use PowerShell and the interpreter in `.venv\Scripts\python.exe` when that environment is available.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q agentnik tests
.\.venv\Scripts\python.exe agentnik.py
```

Tests set Qt to use its offscreen platform; PySide6 and keyring must be installed for GUI checks. Use a temporary `AGENTNIK_HOME` or `--data-dir` when testing changes that write application data. Run relevant tests for each change, and verify visual or interactive GUI changes with Qt where practical. Report checks that could not be run.

## Contracts to preserve

- Keep the GUI responsive during network requests and keep tabs and histories independent. Preserve Markdown, inline thinking, images, statistics, accessibility, and light/dark behavior when changing chat presentation.
- Support Responses, Chat Completions, and Messages; preserve provider-specific environment discovery and existing saved connections. Bedrock support is for Mantle bearer-token endpoints. Do not assume every model supports every protocol or capability.
- System One is a structured decision API, separate from chat. Preserve ordered questions and criteria, multiple image attachments, and the image-only state fallback. Verify model capability with a real request before claiming compatibility.
- Keep API keys out of session history, logs, test output, and project files. Use the existing credential-store and explicit plaintext fallback behavior. Never print supplied key files or include keys in exports by default.
- Preserve session and attachment persistence, shared-attachment cleanup, and explicit confirmation for destructive history actions. Treat imported connections and endpoint responses as untrusted input.
- Keep runtime dependencies minimal and compatible with Windows, macOS, and Linux. Pillow is only needed to rebuild branding assets, not to run the app. Include packaged assets when changing distribution configuration.
- Do not run paid or live endpoint requests as part of ordinary unit tests. Run `tools/live_smoke.py` or real-model checks only when appropriate and authorized; distinguish mock, offscreen, and live validation.

## Roadmap

Read `AGENTNIK_PLAN.md` before research work. Establish and validate milestone A before adding web tools. Milestones B/C implement native Ollama and Responses managed research, official OpenAI Responses hosted search, and four route policies with bounded fallback. Milestone D adds Chat Completions/Messages managed adapters with protocol-specific continuation. Live compatibility, cross-platform and full distribution validation remain outstanding. Never bypass access restrictions or automatically replay partial/uncertain submissions; do not infer capability from protocol compatibility. Preserve the explicit preview status and distinguish offline tests from live compatibility. Do not issue live inference requests during ordinary validation.
