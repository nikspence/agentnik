# Agentnik v0.10.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.3

- **Image generation and editing:** Chat and Code can use a separately selected OpenRouter-compatible image connection and model, including a configured LiteLLM passthrough. Chat retains generated images; Code creates or edits project assets. See the guides for setup, reference images, provider charges and uncertain outcomes.
- **Visual inspection:** Enable image inspection for a vision-capable Code model to inspect project images. Subagents can review approved image snapshots.
- **Subagent artifacts:** Assign separate output folders to parallel subagents to create text files and copy or crop approved images. Staged outputs publish only after successful completion and do not overwrite existing files.
- **Reliability:** Web page responses can be processed up to the configured limits, with clearer handling of larger responses.

Offline tests use mocked endpoints and offscreen Qt. Live observations are scoped in VALIDATION.md; an editable PowerPoint workflow has not been qualified end to end. Build-host startup evidence is recorded in BUILD-MANIFEST.json. This release has not been separately qualified on a clean machine. macOS/Linux validation, signing and a complete bundled-library license review remain open.

Earlier release notes are available in the corresponding Git tags and GitHub releases.
