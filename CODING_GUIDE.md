# Coding with Agentnik

Agentnik's Code pane uses your configured model connections to inspect a selected local project and propose file edits. This feature is available in the development tree after v0.2.0; it is not included in the v0.2.0 archive. Coding compatibility has offline test coverage but has not yet been established with live models.

## Start a task

1. Configure a connection in **Connections**. Choose an endpoint and model that support tool calling; an alias appearing in a model list does not establish compatibility.
2. Click **＋ Code**, choose **Add folder** if needed, select the project, and open it. A Git repository is optional. Opening a pane does not start inference.
3. Select the **Heavy model** connection and enter its model alias, or use **Choose model…**. Optionally configure a separate **Light model** in the same way. You can use different connections and providers.
4. Describe the task and select **Run coding task**. Activity appears in the pane. Review each complete file diff and use **Approve proposed step** or **Reject proposed step**.

The Heavy model plans, reads project files, and proposes edits. It may delegate bounded analysis to the configured Light model, which has no repository tools. Project contents read by Heavy can be sent to its endpoint, and delegated context can be sent to the Light endpoint. Choose services appropriate for the contents of your project.

For a practice run, **Try simulated workflow (no execution)** exercises the approval interface without inference or file changes. Simulation approval does not authorize a real edit.

## Review and limits

Each real edit requires approval. Existing files must first be read by the coding agent; Agentnik checks for changes since that read and again before applying the approved edit. If another change conflicts, the write stops. Review the entire diff and the displayed project and path before approving. The **Not checked** safety label means no System One safety request was made.

When a task changes several files, each proposed file is reviewed independently. Approving one does not approve the others; a rejected or conflicting edit does not undo earlier approved edits. After a conflict, the agent must explicitly read the current file before proposing another edit to it.

The current tools list directories, read UTF-8 files, and propose complete file content. Reads and writes are limited to 32 KB per file. The agent cannot create directories, delete files, run shell commands, make network calls through coding tools, commit, or push. It rejects traversal, links, and several common credential paths, but these checks are not an operating system sandbox or a guarantee against all external filesystem races.

Each run has shared request, tool, context, and time limits. Cancellation stops further scheduling and invalidates pending approval; edits already applied remain in the project. Remote inference may continue or incur charges after cancellation. Each new run starts a fresh model conversation, so include the relevant task context again.

Completed and failed runs show reported input and output token totals separately for Heavy and Light. Counts marked **known usage only** omit requests whose provider did not report that count; **unknown** means none of the role's requests reported it. These are reported tokens, not cost estimates. Cancelled runs may not have a final usage summary.

## Projects and history

The **Repositories** manager can rename entries, locate a moved folder, or remove an entry from the list. Removing an entry leaves its files and history intact. Each Code pane keeps a snapshot of its original working directory. After relocating an entry, open a new Code pane to use the new location; an existing pane keeps its original path.

Drafts, model assignments, and bounded activity are saved with the session. Reopening an interrupted run does not resume it or apply a pending edit. Connection credentials are managed through the existing connection settings rather than stored in role assignments.

## Troubleshooting

- If model listing fails, enter the alias manually. Listing success alone does not confirm tool support.
- If the run reports a model or protocol error, check the connection, selected alias, account access, and tool-calling support. Agentnik does not automatically switch models or providers.
- If a project is unavailable, use **Locate folder** in the repository manager and open a new pane. Check the working directory shown in the pane before running.
- If an edit conflicts, inspect the current file and start a new task so the agent can read the current content. Previously approved edits are not rolled back.

For implementation boundaries and upcoming work, see [CODING_BACKEND_PLAN.md](CODING_BACKEND_PLAN.md). For setup, connection settings, and the rest of the application, see [README.md](README.md).
