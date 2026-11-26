# Agentnik Code in the terminal

Agentnik Code is available as a terminal preview. It uses Agentnik's own coding engine and works on machines without a display or Qt. Install from the checkout:

```sh
python -m pip install ".[terminal]"
```

From the folder you want to work in, run `agentnik code`. A Git repository is optional. To work somewhere else, pass the folder as an argument. On a machine where you also use the desktop app, install `".[desktop,terminal]"` to use both. The clients share saved connections and application data. Use `--data-dir PATH` or `AGENTNIK_HOME` if you want a separate data store.

## First task

1. Run `/connections` to list saved and environment connections. Use `/connections add` to create one if needed. API keys are entered without echo and use the OS credential store by default. Plaintext storage is an explicit fallback.
2. Choose a connection with `/connection NAME`. Use `/models` to fetch its catalog and choose a model, or `/model NAME` to enter an ID manually.
3. Type a task. Enter inserts a new line with the terminal extra installed, and Alt+Enter submits. Use Ctrl+C to request cancellation.
4. In the default approval mode, review proposed changes and commands before allowing them. Enter without an affirmative response declines.

## Sessions and keyboard controls

Each launch starts a separate session, even in the same project. `/new` starts another session without leaving the terminal. `/history` shows the current session and `/sessions` lists saved sessions for the project. Use `/resume ID`, or launch with `agentnik code --resume ID`. Use `latest` in place of an ID to pick the most recent session. Reopening a session sends no model request and does not replay tool actions.

At the prompt, Up and Down recall input and Tab completes slash commands. Ctrl+T opens the transcript, and PageUp opens it and moves back. In the transcript, PageUp/PageDown or Ctrl+B/Ctrl+F move by a page, and Ctrl+U/Ctrl+D move by half a page. Ctrl+T or Q returns to the draft.

`/goal OBJECTIVE` starts an ongoing goal. To continue a stopped goal, use `/continue` and review the saved objective before starting a fresh run. The model receives saved evidence and is directed to inspect current state before acting.

## Settings and tools

| Command | What it does |
| --- | --- |
| `/connections edit NAME` | Change a saved connection's endpoint, protocol, or model. |
| `/connections options NAME` | Change reasoning effort, service tier, context limit, or streaming. |
| `/connections discover` | Check known loopback ports for local model services. Discovered connections last until the terminal exits. |
| `/connections key NAME` / `/connections remove NAME` | Rotate or clear a credential, or remove a connection. |
| `/permissions require` / `/permissions allow-all` | Require review or skip prompts for project edits and shell commands in this session. New and resumed sessions default to review. |
| `/settings` | Manage run and goal limits, TLS, desktop appearance, and other shared settings. Use `0` for unlimited rounds, requests, calls, turn time, goal steps, or goal time. Model request timeouts and retained context remain bounded. |
| `/skills` | List and preview available skills, then pin the ones you want to use. |
| `/web on` | Enable research for this session. Manage access policy, routing priority, and provider credentials under `/settings web`. |
| `/settings chat-limits` / `/settings web desktop on\|off` | Manage desktop Chat research limits and the default desktop Web switch. |
| `/settings image set` / `/settings image on` | Configure and enable generation or editing of PNG, JPEG, and WebP assets. Pillow handles raster files when Qt is absent. |
| `/vision on` | Let the selected vision-capable model inspect supported project images. |
| `/thinking on` | Show thinking returned by the provider, when available. |
| `/settings decision set` / `/settings decision on` | Configure optional System One advice. At a shell approval prompt, press `a` to review and send the proposal for advice. You still approve or decline the command. |
| `/settings mcp` | Manage desktop MCP profiles, access, tool priority, timeouts, and HTTPS bearer tokens. Setup does not start or contact a server. |
| `/mcp` / `/mcp use NAME` / `/mcp off` | List enabled local and HTTPS profiles, select one for the session, or disable it. Code asks before starting or connecting to a server, and before tool and resource requests. |
| `/status` | Show the project, session, model selection, and active switches. |
| `/context` | Inspect, clear, or toggle the previous task and answer carried into new turns. Explicit goal continuation uses its own saved evidence. |
| `/attach PATH` | Queue extracted text from a project text file, DOCX, XLSX, or PPTX for the next task. With `/vision on`, you can also queue PNG, JPEG, or WebP images. Use `/attachments` to inspect the queue and `/attachments clear` to empty it. |
| `/diff` / `/diff PATH` / `/diff --staged PATH` | List tracked changes or compare a file in the working tree or index against HEAD. |

The terminal MCP preview supports tools, resources, resource templates, and prompts. Local stdio tries 2025 initialization and can probe for 2026 discovery when the server rejects the legacy envelope or stays silent. HTTPS tries 2026 discovery, with 2025 fallback for eligible protocol rejections. HTTPS profiles can use a saved bearer token. OAuth, tasks, and interactive server requests remain desktop features. The [roadmap](AGENTNIK_PLAN.md) tracks the rest of the terminal work, native SSH and cross-platform validation, and later VS Code integration.
