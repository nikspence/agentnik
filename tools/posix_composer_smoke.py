"""Exercise terminal composer key handling through a POSIX PTY (requires pexpect)."""

import sys


CHILD = """
import sys
from agentnik.code_composer import create_composer

composer = create_composer(transcript=lambda: chr(10).join(f"Transcript row {i:03}" for i in range(100)),
                           session_ids=lambda: (sys.argv[1],))
print("CANCEL-READY", flush=True)
try:
    composer.prompt()
except KeyboardInterrupt:
    print("DRAFT-CANCELLED", flush=True)
else:
    raise AssertionError("Ctrl+C did not cancel the draft")
for index in range(5):
    print(f"READY-{index}", flush=True)
    draft = composer.prompt()
    print(f"SUBMITTED-{index}:{draft.encode().hex()}:END", flush=True)
"""


def main():
    try:
        import pexpect
    except ImportError:
        raise SystemExit("Install pexpect in the smoke-test environment first.") from None
    session_id = "abcd1234-0000-4000-a000-123456789abc"
    with pexpect.spawn(sys.executable, ["-u", "-c", CHILD, session_id], encoding="utf-8", timeout=10, dimensions=(24, 80)) as terminal:
        terminal.expect_exact("CANCEL-READY")
        terminal.expect_exact("code>")
        terminal.send("discard this draft")
        terminal.sendcontrol("c")
        terminal.expect_exact("DRAFT-CANCELLED")
        terminal.expect_exact("READY-0")
        terminal.expect_exact("code>")
        terminal.send("first line\nsecond line\x1b[13;5uthird line\x1b[27;5;13~fourth line\r")
        draft = b"first line\nsecond line\nthird line\nfourth line".hex()
        terminal.expect_exact(f"SUBMITTED-0:{draft}:END")
        terminal.expect_exact("READY-1")
        terminal.expect_exact("code>")
        terminal.send("\x1b[A\r")
        terminal.expect_exact(f"SUBMITTED-1:{draft}:END")
        terminal.expect_exact("READY-2")
        terminal.expect_exact("code>")
        terminal.send("draft kept across scrollback")
        terminal.sendcontrol("t")
        terminal.expect_exact("Transcript row 099")
        terminal.send("\x15" * 3)
        terminal.expect_exact("Transcript row 066")
        terminal.send("q")
        terminal.expect_exact("code>")
        terminal.send("\r")
        terminal.expect_exact(f"SUBMITTED-2:{b'draft kept across scrollback'.hex()}:END")
        terminal.expect_exact("READY-3")
        terminal.expect_exact("code>")
        paste = "literal \x1b[13;5u and \x1b[27;5;13~ bytes"
        terminal.send("\x1b[200~" + paste + "\x1b[201~")
        terminal.send("\r")
        terminal.expect_exact(f"SUBMITTED-3:{paste.encode().hex()}:END")
        terminal.expect_exact("READY-4")
        terminal.expect_exact("code>")
        terminal.send("/resume abcd\t")
        terminal.expect_exact(session_id[4:])
        assert terminal.expect_exact(["SUBMITTED-4:", pexpect.TIMEOUT], timeout=0.2) == 1
        terminal.send("\r")
        completed = ("/resume " + session_id).encode().hex()
        terminal.expect_exact(f"SUBMITTED-4:{completed}:END")
        terminal.expect(pexpect.EOF)
        terminal.close()
        if terminal.exitstatus != 0:
            raise SystemExit(f"Composer exited unexpectedly (status {terminal.exitstatus}).")
    print("POSIX PTY verified Ctrl+C draft cancellation, Ctrl+J, distinct Ctrl+Enter sequences, Enter, Up history recall, draft recovery after transcript scrollback, literal bracketed paste, and session ID completion.")


if __name__ == "__main__":
    main()
