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
import pexpect

assert find_spec("PySide6") is None
args = ["-tt", "-p", "2222", "-i", "/tmp/agentnik-smoke-key", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new", "agentnik-smoke@127.0.0.1",
        "cd project && TERM=xterm /opt/agentnik-smoke/bin/agentnik code --data-dir ../test-data"]
with pexpect.spawn("ssh", args, encoding="utf-8", timeout=12) as session:
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
    session.send("/exit\r")
    session.expect(pexpect.EOF)
    session.close()
    assert session.exitstatus == 0, session.exitstatus
print("Qt-free preview passed the authenticated SSH terminal smoke test.")
PY
