#!/bin/sh
# Run only in a disposable Debian-based Python container with /preview mounted.
set -eu

wheel=${1:?Pass the absolute path to the Agentnik preview wheel.}
test -f "$wheel"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -qy openssh-client openssh-server >/tmp/agentnik-ssh-packages.log 2>&1 ||
    { cat /tmp/agentnik-ssh-packages.log; exit 1; }
python -m venv /opt/agentnik-smoke
/opt/agentnik-smoke/bin/python -m pip --disable-pip-version-check -q install pexpect "$wheel[terminal]"

useradd -m -s /bin/sh agentnik-smoke
passwd -d agentnik-smoke >/dev/null
home=/home/agentnik-smoke
install -d -m 700 -o agentnik-smoke -g agentnik-smoke "$home/.ssh" "$home/project"
install -d /run/sshd
ssh-keygen -q -t ed25519 -N '' -f /tmp/agentnik-smoke-key
install -m 600 -o agentnik-smoke -g agentnik-smoke /tmp/agentnik-smoke-key.pub "$home/.ssh/authorized_keys"
/usr/sbin/sshd -o ListenAddress=127.0.0.1 -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no -o PermitRootLogin=no -p 2222

/opt/agentnik-smoke/bin/python - <<'PY'
from importlib.util import find_spec
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
from threading import Event, Thread
import pexpect

assert find_spec("PySide6") is None
requests = []
waiting = Event()
release = Event()
project = Path("/home/agentnik-smoke/project")
machine_folder = project.parent / "diagnostics"


class Fixture(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append((self.path, self.headers.get("Authorization"), body))
        if len(requests) == 6:
            waiting.set()
            release.wait(timeout=15)
            return
        message = {"role": "assistant", "content": "SSH fixture completed the edit."}
        finish = "stop"
        if len(requests) == 1:
            message.update(content="", tool_calls=[{"id": "fixture-edit", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "note.txt", "content": "reviewed\n"}),
            }}])
            finish = "tool_calls"
        elif len(requests) == 2:
            message.update(content="", tool_calls=[{"id": "fixture-edited-note", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "note.txt", "content": "reviewed\n"}),
            }}])
            finish = "tool_calls"
        elif len(requests) == 4:
            message.update(content="", tool_calls=[{"id": "fixture-directory", "type": "function", "function": {
                "name": "machine_create_directory", "arguments": json.dumps({"path": str(machine_folder)}),
            }}])
            finish = "tool_calls"
        elif len(requests) == 5:
            message["content"] = "SSH fixture completed the directory."
        data = json.dumps({"choices": [{"message": message, "finish_reason": finish}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
Thread(target=server.serve_forever, daemon=True).start()
args = ["-tt", "-p", "2222", "-i", "/tmp/agentnik-smoke-key", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new", "agentnik-smoke@127.0.0.1",
        "cd project && export TERM=xterm PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring && "
        "exec /opt/agentnik-smoke/bin/agentnik code --data-dir ../test-data"]
with pexpect.spawn("ssh", args, encoding="utf-8", timeout=12) as session:
    session.expect_exact("code>")
    task = "Create the SSH fixture note.\nUse the reviewed content."
    session.send(task.replace("\n", "\x1b[13;5u") + "\r")
    session.expect_exact("Select a connection with /connection NAME first.")
    session.expect_exact("Use /draft to edit the unsent task.")
    session.expect_exact("code>")
    assert not requests
    session.send("/connections add SSH Fixture\r")
    for prompt, value in (("Endpoint URL", f"http://127.0.0.1:{server.server_port}/v1"),
                          ("Protocol (", "chat"), ("Model [", "fixture-model")):
        session.expect_exact(prompt)
        session.send(value + "\r")
    session.expect_exact("API key (blank for none):")
    session.send("synthetic-ssh-key\r")
    session.expect_exact("Store API key as plaintext")
    assert "synthetic-ssh-key" not in session.before
    session.send("\r")
    session.expect_exact("Credential store unavailable.")
    session.expect_exact("without encryption?")
    session.send("y\r")
    session.expect_exact("Saved connection 'SSH Fixture'.")
    session.expect_exact("code>")
    session.send("/connections show SSH Fixture\r")
    session.expect_exact("Model: 'fixture-model'")
    session.expect_exact("Endpoint URL and credentials are not displayed.")
    session.expect_exact("code>")
    session.send("/connections options SSH Fixture\r")
    for prompt in ("Reasoning effort", "Service tier", "Context tokens"):
        session.expect_exact(prompt)
        session.send("\r")
    session.expect_exact("Streaming (on/off)")
    session.send("off\r")
    session.expect_exact("Saved connection 'SSH Fixture'.")
    session.expect_exact("code>")
    session.send('/connections export "portable settings.json"\r')
    session.expect_exact("Exported 1 saved connection(s) without API keys.")
    session.expect_exact("code>")
    session.send("/connection SSH Fixture\r")
    session.expect_exact("Selected connection 'SSH Fixture'.")
    session.expect_exact("code>")
    session.send("/keys\r")
    session.expect_exact("Ctrl+U/Ctrl+D")
    session.expect_exact("code>")
    session.send("/scope machine\r")
    session.expect_exact("code [machine]>")
    session.send("/permissions allow-all\r")
    session.expect_exact("code [machine, allow-all]>")
    session.send("/transcript\r")
    session.expect_exact("No transcript for this session yet.")
    session.expect_exact("code [machine, allow-all]>")
    session.send("/scope project\r")
    session.expect_exact("code [allow-all]>")
    session.send("/permissions require\r")
    session.expect_exact("code>")
    session.send("/settings limits all unlimited\r")
    session.expect_exact("rounds=unlimited, requests=unlimited, calls=unlimited, turn_seconds=unlimited.")
    session.expect_exact("code>")
    session.send("/settings limits all default\r")
    session.expect_exact("rounds=48, requests=50, calls=96, turn_seconds=3600.")
    session.expect_exact("code>")
    assert not requests
    session.send("/draft\r")
    session.expect_exact("code>")
    assert not requests, "Opening the recovered draft submitted it"
    session.send("\r")
    session.expect_exact("Approve once?")
    assert len(requests) == 1
    assert any(message.get("role") == "user" and message.get("content") == task
               for message in requests[0][2]["messages"])
    assert not (project / "note.txt").exists()
    session.send("/steer Reconsider before writing.\r")
    session.expect_exact("Steering queued. The pending proposal was not approved.")
    session.expect_exact("Steering delivered: Reconsider before writing.")
    session.expect_exact("Approve once?")
    assert len(requests) == 2
    assert not (project / "note.txt").exists(), "Steering approved the first edit"
    assert "Reconsider before writing." in json.dumps(requests[1][2]["messages"])
    session.send("y\r")
    session.expect_exact("SSH fixture completed the edit.")
    session.expect_exact("code>")
    session.send("/scope machine\r")
    session.expect_exact("code [machine]>")
    session.send("Create the diagnostics directory outside the project.\r")
    session.expect_exact("operation: machine_create_directory")
    session.expect_exact("Approve once?")
    assert not machine_folder.exists()
    session.send("y\r")
    session.expect_exact("SSH fixture completed the directory.")
    session.expect_exact("code [machine]>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
assert (project / "note.txt").read_bytes() == b"reviewed\n"
assert machine_folder.is_dir()
assert len(requests) == 5
assert all(path == "/v1/chat/completions" and key == "Bearer synthetic-ssh-key"
           and body["model"] == "fixture-model" for path, key, body in requests)
assert any(item.get("role") == "tool" and item.get("tool_call_id") == "fixture-edit"
           for item in requests[1][2]["messages"])
with pexpect.spawn("ssh", [*args[:-1], args[-1] + " --resume latest"], encoding="utf-8", timeout=12) as session:
    session.expect_exact("Steering delivered: Reconsider before writing.")
    session.expect_exact("SSH fixture completed the directory.")
    session.expect_exact("New tasks start in project scope.")
    session.expect_exact("code>")
    session.send("/status\r")
    session.expect(r"Session: ([a-f0-9-]{36})")
    original_session = session.match.group(1)
    session.expect_exact("code>")
    assert len(requests) == 5, "Resuming sent an unexpected request"
    session.send("Wait for a response that will be cancelled.\r")
    assert waiting.wait(timeout=8), "The fixture did not receive the cancellation test request"
    session.sendcontrol("c")
    session.expect_exact("Cancelled locally.")
    session.expect_exact("code>")
    release.set()
    session.send("/new\r")
    session.expect(r"Started session ([a-f0-9-]{36})")
    newer_session = session.match.group(1)
    assert newer_session != original_session
    session.expect_exact("code>")
    session.send("Separate session marker.\r")
    session.expect_exact("SSH fixture completed the edit.")
    session.expect_exact("code>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
discovery = subprocess.run(["ssh", "-T", *args[1:-1], args[-1] + " --list-sessions"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=12)
listed = json.loads(discovery.stdout)
assert [(row["id"], row["status"]) for row in listed] == [
    (newer_session, "completed"), (original_session, "cancelled"),
]
assert len(requests) == 7, "Session discovery sent an unexpected request"
with pexpect.spawn("ssh", [*args[:-1], args[-1] + " --resume " + original_session],
                   encoding="utf-8", timeout=12) as session:
    session.expect_exact("Cancelled locally.")
    session.expect_exact(f"Resumed session {original_session}.")
    session.expect_exact("code>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
assert len(requests) == 7, "Reopening the cancelled session sent an unexpected request"
assert (project / "note.txt").read_bytes() == b"reviewed\n"
portable = json.loads((project / "portable settings.json").read_text(encoding="utf-8"))
assert "api_key" not in portable["connections"]["SSH Fixture"]
assert "credential_id" not in portable["connections"]["SSH Fixture"]
import_args = [*args[:-1], args[-1].replace("../test-data", "../imported-data")]
with pexpect.spawn("ssh", import_args, encoding="utf-8", timeout=12) as session:
    session.expect_exact("code>")
    session.send('/connections import "portable settings.json"\r')
    session.expect_exact("Import these settings?")
    session.send("y\r")
    session.expect_exact("Imported 1 connection(s).")
    session.expect_exact("code>")
    session.send("/connections show SSH Fixture\r")
    session.expect_exact("Model: 'fixture-model'")
    session.expect_exact("Streaming: False")
    session.expect_exact("code>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
imported = json.loads((project.parent / "imported-data/connections.json").read_text(encoding="utf-8"))
assert "api_key" not in imported["connections"]["SSH Fixture"]
assert "credential_id" not in imported["connections"]["SSH Fixture"]
assert len(requests) == 7, "Connection transfer sent an unexpected model request"
assert "machine_create_directory" not in {tool["function"]["name"] for tool in requests[5][2]["tools"]}
print("Qt-free preview passed SSH setup, steering, reviewed project and machine changes, cancellation, and no-replay resume.")
PY
