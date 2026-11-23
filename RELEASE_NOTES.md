# Agentnik v0.11.1

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.11.0

- **Shell environment:** Code commands inherit Agentnik's user environment, including profile paths and Python configuration. This enables user-installed and system Python packages to be found by the selected interpreter. Commands can access credentials present in inherited environment variables.
- **MCP reliability:** Server event streams use a separate connection pool from ordinary requests, preventing a declined or aborted event stream from interrupting discovery or other requests.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json. This release has not been separately qualified on a clean machine. macOS/Linux distribution validation, signing, and a complete bundled-library license review remain open.

Earlier release notes are available in the corresponding Git tags and GitHub releases.
