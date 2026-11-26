# Agentnik Code in the terminal

Agentnik Code is available as a terminal preview. It uses Agentnik's own coding engine and works on machines without a display or Qt. Install from the checkout:

```sh
python -m pip install ".[terminal]"
```

To test a built wheel without using PyPI, download and extract the `python-distributions` artifact from a successful [build-only GitHub Actions run](https://github.com/nikspence/agentnik/actions/workflows/publish-to-pypi.yml). Create and activate a fresh virtual environment, then install the wheel with the terminal extra:

```sh
python -m pip install "./agentnik-0.12.0rc1-py3-none-any.whl[terminal]"
agentnik code --help
```

Use the wheel filename from the artifact if its version differs. To request a fresh build, run the workflow with both `publish` and `legacy_0_11_1` unchecked.

From the folder you want to work in, run `agentnik code`. A Git repository is optional. To work somewhere else, pass the folder as an argument. On a machine where you also use the desktop app, install `".[desktop,terminal]"` to use both. The clients share saved connections and application data. Use `--data-dir PATH` or `AGENTNIK_HOME` if you want a separate data store.

## First task

1. Run `/connections` to list saved and environment connections. Use `/connections add` to create one if needed. API keys are entered without echo and use the OS credential store by default. If that store is unavailable, the terminal offers to save the key unencrypted in the local Agentnik config. Declining leaves the connection unchanged.
2. Choose a connection with `/connection NAME`. Use `/models` to fetch its catalog and choose a model, or `/model NAME` to enter an ID manually. Use `/model` with no name to return to the connection's default model.
3. Type a task and press Enter to submit. Use Ctrl+Enter to insert a line where your terminal sends it as a distinct key. Otherwise use Ctrl+J. Use Ctrl+C to cancel locally. A request already sent to a server may still finish there. Check the project before continuing. Agentnik does not replay the request.
4. In the default approval mode, review proposed changes and commands before allowing them. Enter without an affirmative response declines.

## Sessions and keyboard controls

Each launch starts a separate session, even in the same project. `/new` starts another session without leaving the terminal. A session appears in `/sessions` after its first task starts. Connection and shared settings changes are saved separately, so they are still available if you exit during setup. Use `/history` to view the current session. Use `/resume ID`, or launch with `agentnik code --resume ID`. Use `latest` in place of an ID to pick the most recent saved session. Reopening a session sends no model request and does not replay tool actions. The Up key can recall up to 100 saved prompts from the reopened session, independent of the shorter transcript preview.

At the prompt, Up and Down recall input and Tab completes slash commands. Ctrl+T opens the transcript, and PageUp opens it and moves back. In the transcript, PageUp/PageDown or Ctrl+B/Ctrl+F move by a page, and Ctrl+U/Ctrl+D move by half a page. Ctrl+T or Q returns to the draft.

Unrecognized slash commands are not sent to the model. If your task starts with a literal slash, such as an absolute Unix path, type an extra slash at the start. Agentnik removes the first slash before submitting the task.

Use `/sessions 2`, `/sessions 3`, and so on to find older sessions. Listing a page does not reopen any session. Both `/resume` and `agentnik code --resume` accept a unique ID prefix, so you only need to type enough characters to identify one session in the current project.

Two terminals can work in the same project using separate sessions. If another terminal already has a session open, trying to resume it leaves your current session and prompt history intact.

`/goal OBJECTIVE` starts an ongoing goal. To continue a stopped goal, use `/continue` and review the saved objective before starting a fresh run. The model receives saved evidence and is directed to inspect current state before acting.

## Settings and tools

| Command | What it does |
| --- | --- |
| `/connections edit NAME` | Change a saved connection's endpoint, protocol, or model. |
| `/connections options NAME` | Change reasoning effort, service tier, context limit, or streaming. |
| `/connections discover` | Check known loopback ports for local model services. Discovered connections last until the terminal exits. |
| `/connections key NAME` / `/connections remove NAME` | Rotate or clear a credential, or remove a connection. |
| `/permissions require` / `/permissions allow-all` | Require review or skip prompts for project edits and ordinary shell commands in this session. MCP requests and commands that need separate review still prompt. New and resumed sessions default to review. |
| `/settings` | Manage run and goal limits, TLS, desktop appearance, and other shared settings. Use `unlimited` or `0` for rounds, requests, calls, turn time, goal steps, or goal time. Model request timeouts and retained context remain bounded. |
| `/settings limits` / `/settings goal` | Show effective run or goal limits without changing them. |
| `/skills` | List and preview available skills, then pin the ones you want to use. |
| `/web on` | Enable research for this session. Manage access policy, routing priority, and provider credentials under `/settings web`. |
| `/settings chat-limits` / `/settings web desktop on\|off` | Manage desktop Chat research limits and the default desktop Web switch. |
| `/settings image set` / `/settings image on` | Configure and enable generation or editing of PNG, JPEG, and WebP assets. Pillow handles raster files when Qt is absent. |
| `/vision on` | Let the selected vision-capable model inspect supported project images. |
| `/thinking on` | Show thinking returned by the provider, when available. |
| `/settings decision set` / `/settings decision on` | Configure optional System One advice. At a shell approval prompt, press `a` to review and send the proposal for advice. You still approve or decline the command. |
| `/settings git-author set` / `/settings git-author clear` | Set or clear this project's Agentnik Git author override without changing Git configuration files. |
| `/settings mcp` | Manage desktop MCP profiles, access, tool priority, timeouts, and HTTPS bearer tokens. Setup does not start or contact a server. |
| `/settings mcp edit-https NAME` | Rename an HTTPS MCP profile or change its URL after clearing its saved credential. |
| `/settings mcp edit-local NAME` | Change a local MCP profile's name, executable, arguments, working directory, or environment mappings without starting it. |
| `/mcp` / `/mcp use NAME` / `/mcp add NAME` | List enabled local and HTTPS profiles and select up to five in priority order. Use `/mcp remove NAME` or `/mcp off` to deselect. Code asks before starting or connecting to a server and before tool and resource requests. |
| `/status` | Show the project, session, model selection, and active switches. |
| `/context` | Inspect, clear, or toggle the previous task and answer carried into new turns. Explicit goal continuation uses its own saved evidence. |
| `/attach PATH` | Queue extracted text from a project text file, PDF, DOCX, XLSX, or PPTX for the next task. Terminal PDF support extracts text only, without page rendering or OCR, and does not accept encrypted files. Paste a relative or absolute path inside the project, with optional surrounding quotes. With `/vision on`, you can also queue PNG, JPEG, or WebP images. Use `/attachments` to inspect the queue and `/attachments clear` to empty it. |
| `/diff` / `/diff PATH` / `/diff --staged PATH` | List tracked changes or compare a file in the working tree or index against HEAD. |
| `/attachments remove NUMBER` | Remove one queued file by its number in `/attachments`. The original file stays in the project. |

Structured local Git operations such as staging, creating a branch, and committing always require review. The terminal shows the branch or files, diff, and commit identity and message where applicable. Structured remote Git operations are not available in this preview.

With Git installed, you can run `/git status`, `/git stage PATH`, `/git unstage PATH`, `/git commit MESSAGE`, and `/git push REMOTE BRANCH` yourself without turning the command into a model prompt. Stage and unstage take one project-relative file at a time. Commit uses the staged changes and your native Git identity. Push sends the current commit to the named branch on a configured remote without force. Changes ask for confirmation and use your normal Git configuration, hooks, and credential helpers.

Use `/git diff` to review all unstaged tracked changes, or `/git diff --staged` to see what the next commit would contain. These read-only commands use Git's normal terminal output and pager.

Use `/git remotes` to list the remote names you can pass to `/git push`. It does not display remote URLs or contact any remote.

The terminal MCP preview supports tools, resources, resource templates, and prompts. Local stdio tries 2025 initialization and can probe for 2026 discovery when the server rejects the legacy envelope or stays silent. HTTPS tries 2026 discovery, with 2025 fallback for eligible protocol rejections. HTTPS profiles can use a saved bearer token or an active desktop OAuth sign-in. Use `/settings mcp signin NAME` to sign in with a registered public client that supports S256 PKCE and a loopback redirect at `http://127.0.0.1:<port>/callback`. Open the displayed link in a browser. Over SSH, run the displayed port-forwarding command on your browser machine first. Use `/settings mcp renew NAME` to renew a saved OAuth credential. Dynamic client registration, tasks, and interactive server requests remain desktop features. The [roadmap](AGENTNIK_PLAN.md) tracks the rest of the terminal work, native SSH and cross-platform validation, and later VS Code integration.
