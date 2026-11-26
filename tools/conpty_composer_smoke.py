"""Exercise the Windows composer through ConPTY. Requires optional pywinpty."""

from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
from time import monotonic


CHILD = """
from agentnik.code_composer import create_composer

composer = create_composer()
for index in range(2):
    print(f"READY-{index}", flush=True)
    draft = composer.prompt()
    print(f"SUBMITTED-{index}:{draft.encode().hex()}:END", flush=True)
"""


def main():
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires Windows ConPTY.")
    try:
        from winpty import Backend, PtyProcess
    except ImportError:
        raise SystemExit("Install pywinpty in the smoke-test environment first.") from None

    root = Path(__file__).resolve().parents[1]
    terminal = PtyProcess.spawn([sys.executable, "-u", "-c", CHILD], cwd=str(root), backend=Backend.ConPTY)
    output = Queue()
    seen = ""

    def read():
        try:
            while chunk := terminal.read(4096):
                output.put(chunk)
        except (EOFError, OSError):
            pass
        finally:
            output.put(None)

    def expect(marker):
        nonlocal seen
        end = monotonic() + 10
        while marker not in seen:
            try:
                chunk = output.get(timeout=max(0, end - monotonic()))
            except Empty:
                chunk = None
            if chunk is None:
                raise AssertionError(f"Missing {marker!r}. Console tail: {seen[-500:]!r}")
            seen = (seen + chunk)[-8192:]
            if monotonic() >= end and marker not in seen:
                raise AssertionError(f"Timed out waiting for {marker!r}.")

    Thread(target=read, daemon=True).start()
    try:
        expect("READY-0")
        terminal.write("first line\nsecond line\r")
        draft = b"first line\nsecond line".hex()
        expect(f"SUBMITTED-0:{draft}:END")
        expect("READY-1")
        terminal.write("\x1b[A\r")
        expect(f"SUBMITTED-1:{draft}:END")
    finally:
        terminal.close()
    print("ConPTY verified Ctrl+J multiline input, Enter submission, and Up history recall.")


if __name__ == "__main__":
    main()
