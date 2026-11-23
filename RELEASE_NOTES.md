# Agentnik v0.11.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.10.0

- **MCP support:** Expanded local and remote protocol support, including prompts and resources, progress and cancellation, selected task and elicitation workflows, OAuth authorization, event streams, and compatibility with newer MCP servers. Chat and Code can use MCP images with compatible models and retain larger results for inspection.
- **Research and tools:** Chat can fall back to Agentnik-managed web fetching when an MCP fetch fails. Server guidance and validation errors provide more context during tool use.
- **Chat and Code:** Generated Chat images can be previewed and saved; Code activity renders Markdown, and skill discovery and image workflows have been improved.
- **Reliability:** Improved background job cancellation, MCP response handling, and offline test isolation across Windows, macOS, and Linux.

Offline tests use mocked endpoints and offscreen Qt. MCP capabilities depend on the server and negotiated protocol; see the guides and VALIDATION.md for the scope of testing. Build-host startup evidence is recorded in BUILD-MANIFEST.json. This release has not been separately qualified on a clean machine. macOS/Linux distribution validation, signing, and a complete bundled-library license review remain open.

Earlier release notes are available in the corresponding Git tags and GitHub releases.
