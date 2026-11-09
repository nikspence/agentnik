# Coding with Agentnik

Agentnik's Code pane uses your configured model connections to inspect a selected local project and propose file edits. This feature is available in the development tree after v0.2.0; it is not included in the v0.2.0 archive. Coding compatibility has offline test coverage but has not yet been established with live models.

## Start a task

1. Configure a connection in **Connections**. Choose an endpoint and model that support tool calling; an alias appearing in a model list does not establish compatibility.
2. Click **＋ Code**, choose **Add folder** if needed, select the project, and open it. A Git repository is optional. Opening a pane does not start inference.
3. Select the **Heavy model** connection and enter its model alias, or use **Choose model…**. Optionally configure a separate **Light model** in the same way. You can use different connections and providers.
4. Describe the task and select **Run coding task**. Activity appears in the pane. Review each complete file diff and use **Approve proposed step** or **Reject proposed step**.

The Heavy model plans, reads project files, and proposes edits. It may delegate bounded analysis to the configured Light model, which has no repository tools. Project contents read by Heavy can be sent to its endpoint, and delegated context can be sent to the Light endpoint. Choose services appropriate for the contents of your project.

Turn off **Allow Light model delegation** to run with Heavy alone while keeping the Light assignment for later. The setting is saved per Code pane and cannot be changed during a run.

For a practice run, **Try simulated workflow (no execution)** exercises the approval interface without inference or file changes. Simulation approval does not authorize a real edit.

## Review and limits

Each real edit requires approval. Existing files must first be read by the coding agent; Agentnik checks for changes since that read and again before applying the approved edit. If another change conflicts, the write stops. Review the entire diff and the displayed project and path before approving. The **Not checked** safety label means no System One safety request was made.

When a task changes several files, each proposed file is reviewed independently. Approving one does not approve the others; a rejected or conflicting edit does not undo earlier approved edits. After a conflict, the agent must explicitly read the current file before proposing another edit to it.

The current tools list directories, read or search UTF-8 files, search within a project directory, propose complete file content, delete a previously read UTF-8 file, and create one directory with an existing parent. Each mutation needs separate approval. Search returns bounded literal matches with line numbers; it does not replace a full file read before editing or deletion. Project search checks at most 500 directory entries, eight directory levels and 512 KB of file data, returning at most 40 matches within 8 KB. It flags incomplete results when limits or inaccessible files prevent a complete search. Reads and writes are limited to 32 KB per file. Filesystem tools reject traversal, links, and several common credential paths, but these checks are not an operating system sandbox or a guarantee against all external filesystem races.

The agent can also propose a shell command. Review the entire command, shell, working directory, environment variable names, and scope before approving. Commands run under your account with network access and access outside the project; they can run Git or other programs and change files without separate file approvals. Agentnik uses PowerShell on Windows and `/bin/sh` on macOS/Linux, passes a limited basic system environment, captures at most 32,000 output bytes, and limits each command to 45 seconds or the remaining run time, whichever is less. Windows uses a process job to stop descendants; POSIX uses a process group, which cannot contain processes that detach themselves. Cancellation cannot undo completed effects. Shell output can be sent to the selected model; known connection keys are redacted, but arbitrary secrets cannot be guaranteed to be detected. Shell execution has Windows build-host smoke coverage and offline approval tests; macOS/Linux native execution and live-model use remain unverified.

For optional shell safety advice, open **Models**, choose a Decision connection and System One model, and enable **Check shell approvals with Decision model** before starting a run. Each proposed shell command sends its exact command, working directory, shell, and inherited environment variable names to that endpoint; it does not send environment values or file contents. These details may still be sensitive. The approval view identifies the endpoint and shows the returned category and any confidence; the category guide is fixed explanatory text, not a model-generated reason. You still approve or reject. A failed, malformed, or timed-out check shows **UNKNOWN** and permits ordinary manual review. File and directory proposals are not checked. Cancellation stops accepting the result but may not stop remote computation. System One compatibility has not been verified live for this feature.

Enable **Allow web research** to let Heavy read public pages without a search key. Agentnik returns the page text and a bounded selection of links on the same host; discovered links are marked as not yet fetched. For non-direct connections, including LiteLLM, web searches use Google's public HTML search page. Direct `https://ollama.com` connections use a configured Ollama search profile, or Google if none is configured. **Search settings…** manages the Ollama profiles shared with Chat; an Ollama key is never sent to Google. Google may block automated requests, require a browser challenge, or change its page format. If that happens, Agentnik reports that search is unavailable for the rest of the run, without retrying or silently changing routes; the agent can still read known public URLs. Google's terms may restrict automated queries.

Research is off by default and saved per pane. Page reads go directly to public websites. The Heavy connection's strict public-only navigation policy permits public page reads but disables search, because Agentnik cannot enforce that policy inside an external search service. Searches, page reads, and source IDs and URLs appear in Code activity. Use **Sources** to open or copy links for up to 32 sources from the most recent coding run; the list remains available when the pane is reopened and is cleared when another coding run starts. Search results and discovered links are labeled when their pages have not been fetched. Source IDs apply to that run; check the source material when evaluating the model's conclusions. Web content is untrusted, and file edits still require approval. Web calls share the coding run's limits; Light does not get web tools. This integration has offline coverage and has not yet been validated with a live coding model or live Google search.

Each run has shared request, tool, context, and time limits. Cancellation stops further scheduling and invalidates pending approval; edits already applied remain in the project. Remote inference may continue or incur charges after cancellation. The pane shows the last completed task and answer, each limited to 2,048 characters. Select **Send previous task and answer with next run** to include that displayed text in a follow-up request to the currently selected Heavy endpoint. The option resets after a successful run. Failed, canceled, and simulated runs do not replace this context. Provider-specific tool exchanges and reasoning are not replayed, and file edits still require a fresh read and approval.

Use **Limits…** beside the delegation and web controls to adjust tool rounds, model requests, tool calls, elapsed seconds, and retained context bytes for the Code pane. Defaults are 8 rounds, 9 requests, 16 calls, 300 seconds, and 100,000 bytes. The context budget counts previous-task context, assistant continuation, and tool results; it is not the model's total context window and does not include the initial task. Requests from Heavy and Light and calls to project and web tools share the same run budgets. Changes apply to the next run; **Restore Defaults** resets the dialog. The time limit includes time spent reviewing an approval.

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
