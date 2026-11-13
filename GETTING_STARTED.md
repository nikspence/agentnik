# Install and launch

Use Python 3.11 or newer with matching Qt wheels for your OS and architecture. A virtual environment is recommended for dependency isolation, but is optional.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe agentnik.py
```

After installation, `./start.ps1` opens the desktop app without leaving a console window. Run the Python command above when troubleshooting so startup errors remain visible.

To use your existing Python installation directly instead:

```powershell
python -m pip install -r requirements.txt
python agentnik.py
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python agentnik.py
```

Alternatively, `python -m pip install .` installs the `agentnik` desktop entry point. Linux still requires the system libraries used by Qt's platform plugin; the exact packages depend on the distribution.

Optional key files can be supplied with `--litellm-key-file PATH` and `--ollama-key-file PATH`; use `--litellm-url URL` for a custom LiteLLM endpoint. Keys are read into the process environment and are saved only when you explicitly save a connection. Do not commit key files.

See [connections and local data](CONNECTIONS.md) for endpoint and credential configuration, and the [coding guide](CODING_GUIDE.md) for project workflows.
