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

Enable **Allow web research** to let Heavy read public pages without a search key. Agentnik returns page text and bounded same-host links, marked as not yet fetched. **Search settings…** manages ordered search profiles shared with Chat. Choose Brave Search, LangSearch, Firecrawl, Exa, or Parallel and enter its separate API key; these providers work with local inference, LiteLLM, and other tool-capable model connections. Environment alternatives are `BRAVE_SEARCH_API_KEY`, `LANGSEARCH_API_KEY`, `FIRECRAWL_API_KEY`, `EXA_API_KEY`, and `PARALLEL_API_KEY`. Profiles use the OS credential store or explicit plaintext fallback, with at most five saved/environment profiles participating. LangSearch and Firecrawl use search snippets without requesting full-text expansion or scraping. Exa uses auto search plus highlights, and Parallel uses basic search with bounded excerpts; provider search/content charges may apply.

Direct `https://ollama.com` coding connections may also use Ollama search profiles. Other coding connections exclude Ollama search credentials. Configured profiles run first, then Firecrawl Keyless, then legacy Google HTML search after eligible definite rejections. Without a configured provider, Firecrawl Keyless is the default. Select Firecrawl (keyless) explicitly to place it earlier in your saved order; its API key field is disabled. All fallback is recorded; access restrictions, timeout/cancellation, malformed replies, and uncertain outcomes stop it. Google can still be rate-limited or challenged. A Google challenge disables Google for that run while direct public page reads remain available. See [SEARCH_PROVIDERS.md](SEARCH_PROVIDERS.md).

Research is off by default and saved per pane. Page reads go directly to public websites. The Heavy connection's strict public-only navigation policy permits public page reads but disables search, because Agentnik cannot enforce that policy inside an external search service. Searches, page reads, and source IDs and URLs appear in Code activity. Use **Sources** to open or copy links for up to 32 sources from the most recent coding run; the list remains available when the pane is reopened and is cleared when another coding run starts. Search results and discovered links are labeled when their pages have not been fetched. Source IDs apply to that run; check the source material when evaluating the model's conclusions. Web content is untrusted, and file edits still require approval. Web calls share the coding run's limits; Light does not get web tools. Authorized live adapter checks returned results and snippets for Brave, Firecrawl Keyless, and LangSearch. A site-restricted LangSearch query returned official Qt documentation after a broader query returned casino-related pages. Provider/model coding integration has offline coverage; live coding research, keyed Firecrawl, Exa/Parallel, and Google scraping remain unverified.

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


## Structured Git tools — local preview

Agentnik uses Dulwich for local Git operations without shell commands. The coding agent can inspect tracked status, working-file diffs against HEAD, staged diffs against HEAD, recent history, and local branches. Status checks at most 128 tracked paths and does not enumerate untracked files; use project listing for those.

Every mutation has its own approval:

- `git_stage`: stage explicitly named UTF-8 files or tracked deletions; review the index-to-working-file diff. Ignored untracked files and sensitive/excluded project paths are rejected.
- `git_unstage`: restore selected index entries to HEAD without changing working files or other staged entries.
- `git_commit`: commit explicitly named working files from a clean index.
- `git_commit_staged`: commit the reviewed index snapshot; the explicit paths must name every staged change, so unrelated staged entries cannot slip in. Later working-file edits remain untouched.
- `git_create_branch`: create a local branch at the reviewed HEAD without switching branches or overwriting an existing branch.

Path lists are JSON arrays encoded as strings, limited to 32 files. Diffs and UTF-8 file reads are bounded. Commit approvals show the full diff, message, configured identity, and parent commit. Approvals bind to the branch reference, HEAD, index fingerprint, and applicable file snapshots; changed state requires a fresh proposal. Index writes are locked, and reference publication uses compare-and-swap. A rare failure publishing the index after a successful commit reports the commit hash and stops the coding run for inspection rather than repeating the commit.

This preview requires an existing HEAD and a registered repository root with a local `.git` directory. Unborn repositories, linked worktrees, in-progress merges/rebases/cherry-picks, hooks, signing, content filters/LFS, and remote operations are outside the supported slice. Files are staged as raw UTF-8 bytes; no attributes-based transformations or external programs run. External filesystem writers are not an OS-level transaction; avoid concurrent repository writes during execution. Korean approval framing is included; model-facing tool descriptions and activity remain English.

Next: credential-safe remote inspection, then fetch and push with explicit destination/branch/commit previews and transport qualification. Branch switching, merge/rebase, signing, submodules, worktrees, and LFS need separate design and compatibility checks. Current evidence is offline temporary-repository tests, mocked coding-loop approvals, and offscreen Qt checks; live-model Git execution and native visual review remain unverified.


## Local models and request timeouts

In the Code pane, open **Limits…** and adjust **Model call timeout (seconds)** for slow local models. The default is 300 seconds (five minutes), configurable from 10 to 3,600 seconds, for each Heavy or Light request. This bounds the complete request, including waiting for the first token and generation; it is not a streaming inactivity timer. **Total run time (seconds)** is a separate shared deadline and can end a model request sooner. New runs default to 900 seconds overall. Existing saved total limits are preserved; increase that limit too if needed. Older saved limits without the new field inherit the 300-second model timeout. Changes apply to the next run, and cancellation still discards late responses without replaying a request. This setting does not lengthen web fetch/search, shell-command, or Decision-advice deadlines.


## Filtered page reads

If a direct public page read encounters a recognized network-filter page, TLS failure, or connection reset, Code can use configured Firecrawl, Exa, Parallel, or eligible direct-Ollama retrieval APIs, with Firecrawl Keyless last. This sends the page URL to that provider and may incur provider charges. Activity records the fallback and Sources retain provider provenance. It does not forward browser/proxy credentials. Strict public-only mode, private or policy-blocked destinations, generic site denials, and timeouts do not use this path. See SEARCH_PROVIDERS.md for scope and validation limits.


## Focused project tools and test reports

Heavy can call `project_overview` to inspect a bounded inventory (500 entries and four directory levels), common manifest names, languages, dependency names, script/entry-point names, and test configuration. Metadata is read rather than executed; dependency URLs and script bodies are not included. Results flag incomplete traversal or metadata. This is an orientation aid, not a complete dependency graph or validated test configuration.

`read_file_range(path, start_line, end_line)` reads inclusive 1-based line numbers, expressed as decimal strings. Files may be up to 2 MB of UTF-8 text; each call returns at most 200 lines and 16 KB of source text, with line numbers, a content snapshot, total line count, and next-line information. An individual oversized line is rejected. Range reads do not authorize whole-file replacement or deletion; ordinary full `read_file` remains limited to 32 KB.

`apply_patch(path, old_text, new_text)` proposes one exact replacement. Old text must be nonempty, unique in the entire file, and contained in a currently read range (or a full file read). Both arguments are limited to 16 KB and the resulting file to 2 MB. Ambiguous matches and stale reads are rejected. Review the diff before approving; the file hash is rechecked at application and surrounding content is preserved. Read the changed region again before another patch. New files and full replacements still use `write_file` and its existing limits.

`run_tests(path, command, format)` uses the shell executor and the same explicit approval, optional Decision advice, environment filtering, process cleanup, output budget and time bounds. The preview identifies a test run and its report format. It executes project code with your account permissions and is not sandboxed. Supported formats are `auto`, `unittest`, `pytest`, `jest`, and `vitest`; the model selects a command appropriate to your project. The result contains the exit code, bounded output, the last recognized summary's reported counts, and bounded failure excerpts. A zero exit code without a recognizable summary is not claimed to verify passing tests. Truncated output is flagged and may leave the outcome unknown. Counts are parsed from untrusted test output rather than independently verified, and multiple summaries are not aggregated. Long suites remain subject to the existing shell/tool deadline (normally at most 45 seconds), separate from the model-call timeout. Use a focused command for this first slice.

These tools have offline project/model fixtures, an approved native temporary unittest check on the Windows host, and offscreen Qt approval checks. No live coding-model compatibility is implied. File access remains subject to the established sensitive-path, traversal, link, and project-containment checks.


## Task plan and checklist

For multi-step tasks, Heavy can create or replace a checklist with `update_plan(explanation, steps)` and read it with `get_plan()`. The `steps` argument is a JSON array encoded as a string, with objects such as `{"step":"Inspect the project","status":"in_progress"}`. Supported statuses are `pending`, `in_progress`, `completed`, and `blocked`. Plans contain 1–20 steps, each a single line of at most 200 characters, and at most one step may be in progress. The explanation is limited to 1,000 characters. Plan calls use the normal tool-call/context budgets and require no approval because they change only task metadata.

The Code pane shows a compact **Task plan** button with completion counts when a plan exists. Click to expand a read-only checklist and explanation; it starts collapsed to preserve transcript space. Plans are isolated per pane and saved independently of the bounded activity transcript. Cancellation, failure, and reopening retain the last reported steps; reopening never restarts work. Starting a new real coding run clears the previous task's plan. The simulation does not create or replace a coding plan.

Progress is model-reported, not proof that a step succeeded. Agentnik does not automatically mark unfinished steps complete when a run ends. Plans never authorize edits, commands, tests, or Git actions: each still follows its existing approval path. Heavy owns the checklist; Light receives only the delegated context Heavy provides and cannot directly update the plan. Invalid or stale-run updates do not replace the visible saved plan. The interface framing is translated in the Korean preview; user/model step text stays in its original language.
