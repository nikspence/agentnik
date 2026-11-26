# Agentnik

Agentnik is a desktop client for chat and research and a terminal coding assistant. Connect it to your chosen model endpoint, including local Ollama and supported Responses, Chat Completions, and Messages endpoints. Tool and image support depend on the model and provider.

For terminal coding without Qt:

```sh
python -m pip install --pre "agentnik[terminal]"
agentnik code
```

Run from your project directory. Use `/connections add` to configure a connection, `/connection NAME` to select it, and `/help` to discover commands. The terminal preview includes session resume, file and shell approvals, goals, and optional image generation.

For the desktop app:

```sh
python -m pip install --pre "agentnik[desktop]"
agentnik-desktop
```

Use `"agentnik[desktop,terminal]"` for both clients. Python 3.11 or newer is required.

[Source and setup](https://github.com/nikspence/agentnik) · [Terminal guide](https://github.com/nikspence/agentnik/blob/master/TERMINAL_CODE.md) · [Report an issue](https://github.com/nikspence/agentnik/issues)
