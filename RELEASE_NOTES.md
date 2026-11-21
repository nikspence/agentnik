# Agentnik v0.9.1

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.9.0

- **Responses streaming:** match reordered final function calls by unique call ID and verify their names and arguments; accept changed item IDs when the call itself matches. Conflicting calls are rejected, and diagnostics report structural details without exposing provider values.
- **Coding recovery:** malformed JSON tool calls reject the entire batch. Continuation history uses a valid placeholder for the malformed arguments so providers can process the corrective tool results.
- **Live observation:** one Inkling-2-Small task completed through LiteLLM after the fixes, recovering from two malformed batches. An unrelated Mistral Large 4 request received an upstream Ollama HTTP 500; broader compatibility remains unverified.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json; clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

## Earlier release: v0.9.0

Windows x64 onedir release. Extract the complete archive and run `Agentnik/Agentnik.exe`, keeping `_internal` beside it. Python is bundled. The build is unsigned; verify the SHA-256 sidecar.

## Changes since v0.8.10

- **One coding model:** Code uses one selected model for the parent request and its subagents. Light and alternate-model delegation and EGM-style independent review have been removed. Existing model settings and review records remain available for reference.
- **Goals and steering:** Code can pursue a goal over successive steps and accept steering during goal and ordinary runs. Step budgets reset at each step; separate goal step and active-time limits can be unlimited, and continuing a stopped goal starts fresh limits. Completion is model-reported and should be reviewed.
- **Shell approval:** a switch can allow shell and test commands without individual approval. It is off by default and can be changed before or during a run; commands run with the user's account permissions.

Offline tests use mocked endpoints and offscreen Qt. Build-host startup evidence is recorded in BUILD-MANIFEST.json; live coding model compatibility, clean-machine installation, full native workflows, macOS/Linux, signing and a complete bundled-library license review remain open.

Earlier release notes are available in the corresponding Git tags.
