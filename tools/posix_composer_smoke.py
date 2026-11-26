"""Exercise terminal composer key handling through a POSIX PTY (requires pexpect)."""

import sys


CHILD = """
from agentnik.code_composer import create_composer

composer = create_composer()
print("CANCEL-READY", flush=True)
try:
    composer.prompt()
except KeyboardInterrupt:
    print("DRAFT-CANCELLED", flush=True)
else:
    raise AssertionError("Ctrl+C did not cancel the draft")
for index in range(2):
    print(f"READY-{index}", flush=True)
    draft = composer.prompt()
    print(f"SUBMITTED-{index}:{draft.encode().hex()}:END", flush=True)
"""


def main():
    try:
        import pexpect
    except ImportError:
        raise SystemExit("Install pexpect in the smoke-test environment first.") from None
    with pexpect.spawn(sys.executable, ["-u", "-c", CHILD], encoding="utf-8", timeout=10) as terminal:
        terminal.expect_exact("CANCEL-READY")
        terminal.expect_exact("code>")
        terminal.send("discard this draft")
        terminal.sendcontrol("c")
        terminal.expect_exact("DRAFT-CANCELLED")
        terminal.expect_exact("READY-0")
        terminal.expect_exact("code>")
        terminal.send("first line\nsecond line\r")
        draft = b"first line\nsecond line".hex()
        terminal.expect_exact(f"SUBMITTED-0:{draft}:END")
        terminal.expect_exact("READY-1")
        terminal.expect_exact("code>")
        terminal.send("\x1b[A\r")
        terminal.expect_exact(f"SUBMITTED-1:{draft}:END")
        terminal.expect(pexpect.EOF)
        terminal.close()
        if terminal.exitstatus != 0:
            raise SystemExit(f"Composer exited unexpectedly (status {terminal.exitstatus}).")
    print("POSIX PTY verified Ctrl+C draft cancellation, Ctrl+J, Enter, and Up history recall.")


if __name__ == "__main__":
    main()
