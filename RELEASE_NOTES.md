# Agentnik v0.10.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.3

- **Image generation and editing:** Chat and Code can use a separately selected OpenRouter-compatible image connection and model, including a configured LiteLLM passthrough. Chat retains generated images; Code creates or edits project assets. See the guides for setup, reference images, provider charges and uncertain outcomes.
- **Visual inspection:** Enable image inspection for a vision-capable Code model to inspect project images. Subagents can review approved image snapshots.
- **Subagent artifacts:** Assign separate output folders to parallel subagents to create text files and copy or crop approved images. Staged outputs publish only after successful completion and do not overwrite existing files.
- **Reliability:** Web page responses can be processed up to the configured limits, with clearer handling of larger responses.

Offline tests use mocked endpoints and offscreen Qt. Live observations are scoped in VALIDATION.md; an editable PowerPoint workflow has not been qualified end to end. Build-host startup evidence is recorded in BUILD-MANIFEST.json. This release has not been separately qualified on a clean machine. macOS/Linux validation, signing and a complete bundled-library license review remain open.

## Earlier release: v0.9.3

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.2

- **Connections and coding:** OpenRouter service tier support and scoped Code validation across multiple providers, routes, and models. See VALIDATION.md for the specific observations and limitations.
- **Languages and Git:** Expanded language coverage and support for global or repository-based Git author settings.
- **Offline validation:** An isolated test runner blocks unexpected Python network access; cross-platform CI and Windows timing and process-cleanup checks were improved.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json. This release has not been separately qualified on a clean machine. macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.9.2

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.1

- **Code composer:** Run clears the submitted prompt and becomes Steer during a run. Unsent text stays in the composer when the run ends or a goal continues.
- **MCP and tools:** Enable and order multiple MCP servers, control tool conflict precedence, and use managed fetch as a fallback when MCP fetch fails. Improved Parallel MCP compatibility and tool error visibility; project memory no longer requires approval.
- **Global settings:** Centralized web access, search priority, run limits, appearance, and shell advice settings. TLS certificate verification is on by default, with relaxation applied globally.
- **Interface and cleanup:** Simplified model configuration, removed the Decision query builder and legacy review snapshots, adjusted the startup window size, and refreshed documentation and Korean coverage.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json. Windows clean-machine testing was reported complete for an unspecified build and workflow; this release has not been separately qualified on a clean machine. macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.9.1

Windows clean-machine testing was subsequently reported complete by the user; the exact build and workflow scope were not specified. Qualification notes below describe the evidence available at each release.

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.0

- **Responses streaming:** match reordered final function calls by unique call ID and verify their names and arguments; accept changed item IDs when the call itself matches. Conflicting calls are rejected, and diagnostics report structural details without exposing provider values.
- **Coding recovery:** malformed JSON tool calls reject the entire batch. Continuation history uses a valid placeholder for the malformed arguments so providers can process the corrective tool results.
- **Live observation:** one Inkling-2-Small task completed through LiteLLM after the fixes, recovering from two malformed batches. An unrelated Mistral Large 4 request received an upstream Ollama HTTP 500; broader compatibility remains unverified.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.9.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.8.10

- **One coding model:** Code uses one selected model for the parent request and its subagents. Light and alternate-model delegation and EGM-style independent review have been removed. Existing model settings remain available for reference.
- **Goals and steering:** Code can pursue a goal over successive steps and accept steering during goal and ordinary runs. Step budgets reset at each step; separate goal step and active-time limits can be unlimited, and continuing a stopped goal starts fresh limits. Completion is model-reported and should be reviewed.
- **Shell approval:** a switch can allow shell and test commands without individual approval. It is off by default and can be changed before or during a run; commands run with the user's account permissions.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json; live coding model compatibility, clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

Earlier release notes are available in the corresponding Git tags.
