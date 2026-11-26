# Agentnik v0.13.0

This is the first public release with Agentnik Code in the terminal. The terminal interface is a preview and uses Agentnik's own coding engine with your configured model connection.

```sh
python -m pip install "agentnik[terminal]==0.13.0"
agentnik code
```

Run it from the folder you want to work in. Git and Qt are not required to start. Use `/help` to discover commands and `/connections add` to set up a model connection from the terminal.

- **Independent sessions:** recall prompts, inspect saved activity, and explicitly reopen a session without replaying work.
- **Review and scope:** choose when to approve project edits and commands, and switch between project and machine file scope. Shell commands run as your account and are not sandboxed.
- **Coding tools:** cancel runs, pursue goals, review changes, run manual Git commands, and optionally inspect or generate images with compatible connections.

The [terminal guide](https://github.com/nikspence/agentnik/blob/v0.13.0/TERMINAL_CODE.md) covers SSH setup, keyboard shortcuts, and the VS Code integrated terminal. This is not a native VS Code extension.

The Windows x64 ZIP is the unsigned **desktop** onedir build. Verify the SHA-256 sidecar, extract the entire ZIP, and run `Agentnik/Agentnik.exe` with `_internal` beside it. Use the PyPI terminal installation above for `agentnik code`. The build manifest describes its startup test and limitations. See [validation](https://github.com/nikspence/agentnik/blob/v0.13.0/VALIDATION.md) for preview evidence and remaining platform and provider checks.
