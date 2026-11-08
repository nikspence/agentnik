# Coding backend and approval contract

E2 begins with a backend-neutral controller and an explicitly selected simulation in each Code pane. The simulation proposes `git status --short`, requires approval, and shows a synthetic result/diff. It starts no process, edits no file, and makes no model or System One request. The normal Run control remains disabled. Simulation approvals do not authorize future real execution.

## Integration direction

Evaluate a structured coding CLI adapter first: reusing an established agent could provide process/session handling and its own authentication without recreating a coding loop. This is a direction for the next investigation, not a selected vendor or verified integration. Agentnik's supported chat protocols do not imply CLI compatibility.

A CLI is eligible only if its documented interface exposes structured events and an approval interception mechanism that prevents execution before Agentnik's decision. JSON transcript output alone is insufficient. Prove cancellation/child cleanup, resumable session identity without automatic command replay, project boundaries, credential isolation, diff provenance, platform support, distribution/license terms and failure behavior using temporary projects. A directory parameter is not a sandbox. If no CLI meets those requirements, evaluate an Agentnik-owned loop; that alternative would require an explicit file/command executor and permission boundary before real use.

Do not launch a real coding CLI, subprocess, or paid model request just to identify installed integrations. Installation/authentication and live integration checks are separate, explicit actions. E2 remains incomplete until a real backend is selected and its execution/permission boundaries are demonstrated.

## Current simulation contract

- Proposals are immutable argument tuples with run identity, command identity and exact working-directory snapshot. Approval references a fingerprint of the complete proposal, not a displayed shell string. Changed arguments, directory or identity require a fresh proposal.
- One-shot approval/rejection applies only while that run awaits its decision and before its deadline. Cancel invalidates pending approval. Late events are rejected by run ID. The worker uses a bounded wait and never accesses the UI directly.
- The pane shows the exact arguments/directory, an explicit **Not checked** safety recommendation, approval/rejection controls, plain-text activity and a separate simulated diff review. Approving a command is not approval of an unrelated diff or future file edits.
- The optional System One recommendation remains planned. It will be advisory, bound to the exact proposal, and shown with reasons and risk badges. A missing, invalid or timed-out check must not become a Safe recommendation. It never replaces execution policy or user approval.
- Activity keeps at most 32 records of 2,048 characters. Drafts survive cancellation. Reopening a running/awaiting-approval simulation records interruption and never restarts it. Schema version 4 remains compatible with passive E1 panes; no real execution state is embedded in old chat histories.

## Selected protocol candidate: Codex app-server

Codex app-server is the first integration candidate, not an enabled coding backend. The [official app-server documentation](https://developers.openai.com/codex/app-server/) describes initialization, structured item/turn events and server-initiated command/file approval requests. It also states approval depends on server settings. Therefore receiving approval events alone does not establish that every command or file change will wait for Agentnik approval.

The process-free `agentnik/codex_protocol.py` spike uses injected send/event functions. It handles initialization, explicit active-turn identity, bounded JSON parsing, command approval correlation, one-shot accept/decline and invalidation on resolution/completion/close. Command strings stay opaque; they are never split into invented argument arrays. The full request payload participates in its fingerprint. Network/additional-permission requests are not accepted as ordinary command approvals. Unknown server requests receive an unsupported-method error; malformed messages close the adapter and clear pending decisions.

The installed Codex launcher was identified through filesystem/command inventory only. It was not executed. This spike neither connects to it nor reads account tokens, starts inference, writes project files or provides process-tree cleanup. Fixtures validate client behavior; they cannot prove server-side enforcement.

Next implementation gates:

1. Build a bounded stdio transport against fake child-process fixtures: launch/exit/error handling, complete-line framing, stderr limits, backpressure, interruption and owned-child cleanup. No automatic reconnect/replay.
2. Review the installed version's supported configuration/schema before any explicit startup. Isolate inherited hooks, MCP servers, skills, user/project settings and environment credentials; startup itself must not silently activate extensions.
3. Establish the exact approval/sandbox policy. Require evidence that all intended commands/edits are intercepted, or keep execution disabled. A workspace path and a request notification are not enforcement.
4. Add explicit thread/turn start/resume/interrupt only after lifecycle and authentication contracts are selected. Persist identity without replaying commands on reopen. Treat CLI authentication/provider compatibility separately from Agentnik's LiteLLM chat connections.
5. Qualify a real backend on temporary projects with explicit authorization. Test pre-existing uncommitted changes, denial, cancellation, child cleanup and diff provenance before exposing real Run controls.

The native argument-tuple simulation and opaque-string Codex proposal are distinct representations. Future System One review must evaluate the exact native representation and permissions, never a lossy re-parsed command preview.
