# Agentnik v0.13.1

Agentnik Code now has a Windows console launcher in the onedir ZIP. No separate Python installation is needed. Extract the complete archive and keep the `_internal` folder next to both executables. Open `Agentnik.exe` for the desktop, or invoke `Agentnik-Terminal.exe code` from your project terminal using the executable's full path. The ZIP is unsigned and includes a SHA-256 sidecar.

For a Qt-free install on Windows, macOS, or Linux:

```sh
python -m pip install "agentnik[terminal]==0.13.1"
agentnik code
```

- Press F6 during a run to stop it and choose the next run's project or machine file scope. Use `/scope project` or `/scope machine` at an approval prompt to change scope without approving the pending action. Agentnik does not replay the task.
- Use `/steer MESSAGE` at an approval prompt to redirect a run without approving the proposal.
- Reopened sessions restore saved MCP profile choices, not approval grants. Reviewed Git and MCP grants are limited to the current run.
- Desktop-only settings are grouped under `/settings desktop`. Existing settings commands still work over SSH.

The terminal remains a preview. The [terminal guide](https://github.com/nikspence/agentnik/blob/v0.13.1/TERMINAL_CODE.md) covers keyboard shortcuts, SSH setup, and the VS Code integrated terminal. There is no native VS Code extension yet.
