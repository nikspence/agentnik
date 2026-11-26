# Agentnik Code in the terminal

Agentnik Code is available as a terminal preview. It uses Agentnik's own coding engine and works on machines without a display or Qt. Install it from PyPI with Python 3.11 or newer:

```sh
python -m pip install "agentnik[terminal]>=0.13.0"
agentnik code --version
```

For development, install from a checkout with `python -m pip install ".[terminal]"`. For a build-only wheel, dispatch the [distribution workflow](https://github.com/nikspence/agentnik/actions/workflows/publish-to-pypi.yml) with both options unchecked and use the wheel and checksums from its artifact.

From the folder you want to work in, run `agentnik code`. A Git repository is optional. To work somewhere else, pass the folder as an argument. On a machine where you also use the desktop app, install `".[desktop,terminal]"` to use both. The clients share saved connections and application data. Use `--data-dir PATH` or `AGENTNIK_HOME` if you want a separate data store.

While a run is waiting for an approval, enter `/steer MESSAGE` at the approval prompt to redirect it without approving the proposed action. This does not accept steering while the model is streaming.

## Launch from VS Code

Open the project folder in VS Code and run `agentnik code` in its integrated terminal. For Remote SSH, install Agentnik on the remote host and run it from the remote terminal.

If you want a launcher in **Terminal → Run Task**, add this example to the workspace's `.vscode/tasks.json` or merge the `tasks` and `inputs` entries into the existing file. This assumes `agentnik` is available on the task's PATH. For a virtual environment that isn't on PATH, use its Agentnik executable as `command`.

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Agentnik Code",
      "type": "process",
      "command": "agentnik",
      "args": ["code"],
      "options": {"cwd": "${workspaceFolder}"},
      "presentation": {"reveal": "always", "focus": true, "panel": "new"},
      "problemMatcher": []
    },
    {
      "label": "Agentnik Code: Resume Session",
      "type": "process",
      "command": "agentnik",
      "args": ["code", "--resume", "${input:agentnikSession}"],
      "options": {"cwd": "${workspaceFolder}"},
      "presentation": {"reveal": "always", "focus": true, "panel": "new"},
      "problemMatcher": []
    }
  ],
  "inputs": [
    {
      "id": "agentnikSession",
      "type": "promptString",
      "description": "Saved Agentnik session ID, unique prefix, or latest",
      "default": "latest"
    }
  ]
}
```

The first task starts a fresh session. The second asks for a saved session ID or unique prefix and defaults to `latest`. It reopens the selected workspace session without sending a model request. If it is already open in another terminal, use that terminal or close it before resuming. It does not install an extension or provide editor-native diffs. [VS Code task input variables](https://code.visualstudio.com/docs/reference/variables-reference#_input-variables)

If VS Code opens the folder in Restricted Mode and doesn't allow tasks, leave its trust setting unchanged. In a separate terminal, change to the workspace directory and run `agentnik code`, or run `agentnik code --resume ID` to reopen a specific session. Use `agentnik code --list-sessions` first if you need the ID.

For editor integrations or scripts, `agentnik code --list-sessions` prints a JSON array of saved sessions in the current project, newest first. It returns the session ID, saved turn status, file scope, goal status, and last update time (`updated_at` in Unix seconds) without opening the composer or resuming a run. Pass a project folder to list sessions for a different workspace.

## First task

1. Run `/connections` to list saved and environment connections. Use `/connections add` to create one if needed. API keys are entered without echo and use the OS credential store by default. If that store is unavailable, the terminal offers to save the key unencrypted in the local Agentnik config. Declining leaves the connection unchanged.
2. Choose a connection with `/connection NAME`. Use `/models` to fetch its catalog and choose a model, or `/model NAME` to enter an ID manually. Use `/model` with no name to return to the connection's default model.
3. Type a task and press Enter to submit. Use Ctrl+Enter to insert a line where your terminal sends it as a distinct key. Otherwise use Ctrl+J. Use Ctrl+C to cancel locally. A request already sent to a server may still finish there. Check the project before continuing. Agentnik does not replay the request.
4. In the default approval mode, review proposed changes and commands before allowing them. Enter without an affirmative response declines.

## Sessions and keyboard controls

Each launch starts a separate session, even in the same project. `/new` starts another session without leaving the terminal. A session appears in `/sessions` after its first task starts. Connection and shared settings changes are saved separately, so they are still available if you exit during setup. Use `/history` to preview turns in the current session. Use `/history turn N` to read all retained activity for a turn, with turn 1 being the newest. Use `/resume` to list saved sessions. Use `/resume ID` (or `/open ID`), or launch with `agentnik code --resume ID`. Use `latest` in place of an ID to pick the most recent saved session. Type part of an ID after `/resume` or `/open` and press Tab to complete it from this project’s saved sessions. Reopening a session sends no model request and does not replay tool actions. The Up key can recall up to 100 saved prompts from the reopened session, independent of the shorter transcript preview.

At the prompt, Up and Down recall input and Tab completes slash commands. Ctrl+T or `/transcript` opens the transcript, and PageUp opens it and moves back. In the transcript, PageUp/PageDown or Ctrl+B/Ctrl+F move by a page, and Ctrl+U/Ctrl+D move by half a page. Ctrl+T or Q returns to the composer. Run `/keys` to see these shortcuts in the terminal.

Unrecognized slash commands are not sent to the model. If your task starts with a literal slash, such as an absolute Unix path, type an extra slash at the start. Agentnik removes the first slash before submitting the task.

Use `/sessions 2`, `/sessions 3`, and so on to find older sessions. Listing a page does not reopen any session. Both `/resume` and `agentnik code --resume` accept a unique ID prefix, so you only need to type enough characters to identify one session in the current project.

Use `/plan` to read the current session's most recent saved checklist. It is model-reported and does not send a new request or authorize any action.

Use `/history 2`, `/history 3`, and so on to inspect older saved turns in the current session without changing prompt recall.

Two terminals can work in the same project using separate sessions. If another terminal already has a session open, trying to resume it leaves your current session and prompt history intact.

## Testing over SSH

Connect with a terminal attached. If you launch Agentnik as part of the SSH command, use `ssh -t HOST` so the remote process gets a terminal. For a clean preview test, use a disposable project folder and a separate Agentnik data directory with `agentnik code --data-dir PATH`.

1. Confirm that `/status` shows the directory you launched from. Add or select a connection and choose a model as above. If the machine has no keyring, use an environment connection or explicitly choose the local plaintext fallback for a saved model credential.
2. Ask for a small new file with known contents. In `require` mode, inspect the proposed edit, then approve it and verify the file on disk.
3. Start another task and press Ctrl+C while it is running. Check the project for already-applied changes before continuing.
4. Note the session ID from `/status`, exit, and reconnect. Run `agentnik code --data-dir PATH --resume ID` from the same project. Confirm the ID and that reopening does not send a request.

The [validation notes](VALIDATION.md) distinguish what was tested over OpenSSH from the separate live model checks.

### Manage shared settings without the desktop

Use `/connections` for saved endpoints and credentials, `/connection` and `/model` for the active session, and `/settings` for shared preferences. `/settings appearance` and `/settings chat-limits` can configure desktop behavior from SSH, even though the terminal does not display the desktop UI. Use `/permissions`, `/scope`, `/skills`, `/mcp`, and `/vision` for choices that apply to the current session.

Use `/connections add` for a new connection, `/connections copy NAME` to start from saved settings, or `/connections import PATH` to bring in settings from a desktop or terminal JSON export. Use `/connections export PATH` to write saved settings to a new file. Copies, imports, and exports do not include API keys. Use `/connections key NAME` to set credentials.

`/goal OBJECTIVE` starts an ongoing goal. Use `/goal` with no argument to see the most recent saved objective and outcome in this session without sending a request. To continue a stopped goal, use `/continue` and review the saved objective, connection, model, file scope, and approval mode before starting a fresh run. The model receives saved evidence and is directed to inspect current state before acting.

## Generate and inspect project images

The image tool can make any project raster asset, including slide artwork, icons, logos, and illustrations. Generation and inspection are separate choices, and neither requires Qt.

1. Select a vision-capable coding model, then run `/vision on`. This lets the coding model request a project image with `view_image`. It does not enable generation.
2. Run `/settings image set` to choose the image connection and model, then `/settings image on`. The image model can be different from the coding model.
3. In a project with a `slides` folder, ask for one test slide. For example, use “Generate a 16:9 slide at `slides/slide-01.png`. Then use `view_image` to check the title for spelling and clipping.” In review mode, approve the proposed image request if it matches what you intended.

Agentnik saves the generated image in the project. With vision enabled, the coding model receives image bytes only when it requests inspection or you attach an image. Use `/vision off` to turn off inspection for later tasks without disabling generation. The terminal tool handoff is tested with mocked providers, and a separate live test qualified image inspection on one model and route. Full compatibility with external skills, including editable PowerPoint reconstruction, depends on the skill's tool requirements and has not been qualified. See the [validation notes](VALIDATION.md).

Run `/skills` to find installed skills. A user-installed skill at `~/.agents/skills/codex-ppt/SKILL.md` appears as `user:codex-ppt`. Enable it for this session with `/skills add user:codex-ppt`. For a project copy under `.agents/skills/codex-ppt/`, use `/skills add codex-ppt`. On SSH, Agentnik looks on the remote machine, not the machine running your SSH client. Use `/skills resources ID` to list supporting files and `/skills read ID PATH` to view a small UTF-8 resource. Enter the skill-relative path as listed, including any spaces, without quotes. Neither command executes files or sends their contents to a model.

## Settings and tools

| Command | What it does |
| --- | --- |
| `/connections show NAME` | Inspect a saved connection's protocol, model, and request options without editing. The endpoint URL and credentials are not shown. |
| `/connections edit NAME` | Change a saved connection's endpoint, protocol, or model. |
| `/connections copy NAME` | Save settings from a saved, environment, or discovered connection under a new name without copying its API key. |
| `/connections options NAME` | Change reasoning effort, service tier, context limit, or streaming. |
| `/connections discover` | Check known loopback ports for local model services. Discovered connections last until the terminal exits. |
| `/connections key NAME` / `/connections remove NAME` | Rotate or clear a credential, or remove a connection. |
| `/check` | Validate the active session’s local run settings and show its effective model and enabled tools without contacting the model. Does not verify credentials or provider capabilities. |
| `/draft` | Open the most recent task rejected before startup for editing. The draft stays in memory for this session and is never automatically submitted. |
| `/permissions require` / `/permissions allow-all` | Require review or skip prompts for file changes, ordinary shell commands, and configured image generation in this session. With allow-all, an image request can send reference images to the configured image provider without a separate prompt. The prompt displays `allow-all` when active. MCP requests and commands that need separate review still prompt. New and resumed sessions default to review. |
| `/scope project` / `/scope machine` | Set the next run's file scope. The prompt shows `code [machine]>` when machine scope is active. Machine scope adds absolute-path directory listing, file metadata, UTF-8 text reads, exact replacements in previously read text files, and creation of new text files without overwriting. Changes follow `/permissions` and your OS account's permissions. Shell commands are not sandboxed. New and resumed sessions start in project scope. |
| `/settings` | Manage run and goal limits, TLS, desktop appearance, and other shared settings. Use `unlimited` or `0` for rounds, requests, calls, turn time, goal steps, or goal time. Use `/settings limits all unlimited` to uncap the four run budgets together, and `/settings limits all default` to restore those budgets. Individual model requests, shell commands, and retained context remain bounded. |
| `/settings limits [NAME]` / `/settings goal [NAME]` | Show effective run or goal limits without changing them. Add a name to inspect one limit and its default. |
| `/settings tls` | Show the saved TLS verification mode without changing it. Use `/settings tls strict` or `/settings tls relaxed` to change it. |
| `/skills` | List and preview available skills, including changed or unavailable selections. Review a changed skill with `/skills show ID` and select its new revision with `/skills add ID`. |
| `/web on` | Enable research for this session. Manage access policy, routing priority, and provider credentials under `/settings web`. |
| `/settings desktop-code auto-compact on\|off` | Set the desktop Code default for sessions without an explicit auto-compaction choice. Does not enable compaction in the TUI. |
| `/settings desktop-code vision on\|off` | Set the desktop Code image inspection default. Use only with a vision-capable connection, as requested project images are sent to that connection. Explicit session choices and terminal `/vision` are unchanged. |
| `/settings desktop-code thinking on\|off` | Set whether desktop Code shows and saves provider-returned thinking by default. Existing session choices and the terminal `/thinking` switch are unchanged. |
| `/settings chat-limits` / `/settings web desktop on\|off` | Manage desktop Chat research limits and the default desktop Web switch. |
| `/settings image set` / `/settings image on` | Configure and enable generation or editing of PNG, JPEG, and WebP assets. Pillow handles raster files when Qt is absent. |
| `/vision` / `/vision on` | Check the current session's inspection setting or let the selected vision-capable model inspect supported project images. Generation is configured separately. |
| `/thinking on` | Show thinking returned by the provider, when available. |
| `/settings decision set` / `/settings decision on` | Configure optional System One advice. At a shell approval prompt, press `a` to review and send the proposal for advice. You still approve or decline the command. |
| `/settings git-author set` / `/settings git-author clear` | Set or clear this project's Agentnik Git author override without changing Git configuration files. |
| `/settings mcp` | Manage desktop MCP profiles, access, tool priority, timeouts, and HTTPS bearer tokens. Setup does not start or contact a server. |
| `/settings mcp edit-https NAME` | Rename an HTTPS MCP profile or change its URL after clearing its saved credential. |
| `/settings mcp edit-local NAME` | Change a local MCP profile's name, executable, arguments, working directory, or environment mappings without starting it. |
| `/mcp` / `/mcp use NAME` / `/mcp add NAME` | List enabled local and HTTPS profiles and select up to five in priority order. Use `/mcp add NAME` to refresh a changed profile without dropping other selected servers. Use `/mcp remove NAME` or `/mcp off` to deselect. Code asks before starting or connecting to a server and before tool and resource requests. |
| `/status` | Show the project, session, model selection, and active switches. |
| `/context` | Inspect, clear, or toggle the previous task and answer carried into new turns. Changing the selected model clears automatic previous-turn context without deleting history. For turns saved with a destination fingerprint, changing the destination also prevents automatic context from being sent. Explicit goal continuation uses its own saved evidence. |
| `/memory` / `/memory show ID` | Read this project's shared desktop Code memory locally. It does not change session history or send a model request. |
| `/memory on` / `/memory off` | Allow the coding model to request saved project memory for this session. Terminal model access is read-only and resets when you switch model, connection, or session. |
| `/attach PATH` | Queue extracted text from a project text file, PDF, DOCX, XLSX, or PPTX for the next task. Terminal PDF support extracts text only, without page rendering or OCR, and does not accept encrypted files. Paste a relative or absolute path inside the project, with optional surrounding quotes. With `/vision on`, you can also queue PNG, JPEG, or WebP images. Use `/attachments` to inspect the queue and `/attachments clear` to empty it. |
| `/diff` / `/diff PATH` / `/diff --staged [PATH]` | List tracked changes, compare one file, or preview up to 12 staged patches without native Git. |
| `/attachments remove NUMBER` | Remove one queued file by its number in `/attachments`. The original file stays in the project. |

Project scope limits the built-in file tools. Project commands such as builds and tests still run in your normal user environment, and the shell is not sandboxed. The model is instructed to ask for machine scope when it needs to inspect or edit outside files directly.

For large UTF-8 logs, machine scope can inspect up to 200 recent lines from a bounded window at the end of an absolute path. Reading the tail does not make the file eligible for an edit. The model can also create a single new directory under an existing absolute parent, following the current approval mode.

Switching to machine scope pauses automatic project context. Switching back restores the previous project turn if context is enabled. Resuming after a machine turn also restores a completed project turn when its connection and model match the resumed session. Machine turns remain visible in history, but their answers are not used as automatic previous-turn context.

To continue a goal recorded in machine scope, reselect `/scope machine` before running `/continue`. Resuming the session itself does not re-enable machine scope.

To change scope during a running task, press Ctrl+C to return to the prompt, check for changes that already took effect, then set the scope and submit a new task. Scope changes do not alter a request already sent to the model or undo an applied edit.

Structured local Git operations such as staging, creating a branch, and committing always require review. The terminal shows the branch or files, diff, and commit identity and message where applicable. Structured remote Git operations are not available in this preview.

When a subagent needs a project file, the terminal shows the destination model and endpoint, the task, and the text snapshot or image summary. Each transfer needs explicit approval, even in `allow-all` mode.

Use `/settings subagents` to see how many explicit tool rejections Agentnik remembers. After a provider or model upgrade, `/settings subagents reset` clears those records for future desktop and terminal runs. It does not change connections or session history.

With Git installed, you can run `/git status`, `/git stage PATH`, `/git unstage PATH`, `/git commit MESSAGE`, and `/git push REMOTE BRANCH` yourself without turning the command into a model prompt. Stage and unstage take one project-relative file at a time. Commit uses the staged changes and your native Git identity. Push sends the current commit to the named branch on a configured remote without force. Changes ask for confirmation and use your normal Git configuration, hooks, and credential helpers. The commit prompt lists staged paths from the whole repository, even if you launched from a subfolder. Review the full patch with `/git diff --staged`. If HEAD, its branch, or the staged snapshot changes during confirmation, Agentnik stops before committing. A push also stops if the named remote’s configured push destination changes during confirmation.

Without native Git, you can still use `/diff` for a repository status summary or `/diff PATH` for a file diff. Paths with spaces can be quoted. Those commands and the model's structured Git tools use Dulwich. The manual `/git` commands use the Git executable.

Use `/git log` to see up to ten recent commits without a pager. Use `/git diff` to review all unstaged tracked changes, or `/git diff --staged` to see what the next commit would contain. The diff commands use Git's normal terminal output and pager.

Use `/git remotes` to list the remote names you can pass to `/git push`. It does not display remote URLs or contact any remote.

The terminal MCP preview supports tools, resources, resource templates, and prompts. Local stdio tries 2025 initialization and can probe for 2026 discovery when the server rejects the legacy envelope or stays silent. HTTPS tries 2026 discovery, with 2025 fallback for eligible protocol rejections. HTTPS profiles can use a saved bearer token or an active desktop OAuth sign-in. Use `/settings mcp signin NAME` to sign in with a registered public client or leave the client ID blank to register with an issuer that supports it. Sign-in requires S256 PKCE and a loopback redirect at `http://127.0.0.1:<port>/callback`. Open the displayed link in a browser. Over SSH, run the displayed port-forwarding command on your browser machine first. Use `/settings mcp renew NAME` to renew a saved OAuth credential. Tasks and interactive server requests remain desktop features. The [roadmap](AGENTNIK_PLAN.md) tracks the rest of the terminal work, native SSH and cross-platform validation, and later VS Code integration.
