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
from threading import Thread
import pexpect

assert find_spec("PySide6") is None
requests = []
project = Path("/home/agentnik-smoke/project")


class Fixture(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append((self.path, self.headers.get("Authorization"), body))
        message = {"role": "assistant", "content": "SSH fixture completed the edit."}
        finish = "stop"
        if len(requests) == 1:
            message.update(content="", tool_calls=[{"id": "fixture-edit", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "note.txt", "content": "reviewed\n"}),
            }}])
            finish = "tool_calls"
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
        "cd project && TERM=xterm /opt/agentnik-smoke/bin/agentnik code --data-dir ../test-data"]
with pexpect.spawn("ssh", args, encoding="utf-8", timeout=12) as session:
    session.expect_exact("code>")
    session.send("/connections add SSH Fixture\r")
    for prompt, value in (("Endpoint URL", f"http://127.0.0.1:{server.server_port}/v1"),
                          ("Protocol (", "chat"), ("Model [", "fixture-model")):
        session.expect_exact(prompt)
        session.send(value + "\r")
    session.expect_exact("API key (blank for none):")
    session.send("synthetic-ssh-key\r")
    session.expect_exact("Store API key as plaintext")
    assert "synthetic-ssh-key" not in session.before
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
    session.send("Create the SSH fixture note.\r")
    session.expect_exact("Approve once?")
    assert not (project / "note.txt").exists()
    session.send("y\r")
    session.expect_exact("SSH fixture completed the edit.")
    session.expect_exact("code>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
assert (project / "note.txt").read_bytes() == b"reviewed\n"
assert len(requests) == 2
assert all(path == "/v1/chat/completions" and key == "Bearer synthetic-ssh-key"
           and body["model"] == "fixture-model" for path, key, body in requests)
assert any(item.get("role") == "tool" and item.get("tool_call_id") == "fixture-edit"
           for item in requests[1][2]["messages"])
with pexpect.spawn("ssh", [*args[:-1], args[-1] + " --resume latest"], encoding="utf-8", timeout=12) as session:
    session.expect_exact("SSH fixture completed the edit.")
    session.expect_exact("code>")
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
assert len(requests) == 2, "Resuming sent an unexpected request"
print("Qt-free preview passed SSH connection setup, reviewed edit, and resume without replay.")
PY
