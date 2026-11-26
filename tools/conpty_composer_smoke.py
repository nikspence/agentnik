"""Exercise the Windows composer through ConPTY. Requires optional pywinpty."""

from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
from time import monotonic, sleep


CHILD = """
from agentnik.code_composer import create_composer

composer = create_composer()
for index in range(3):
    changes = []
    observe = lambda buffer: changes.append(buffer.text)
    composer.default_buffer.on_text_changed += observe
    print(f"READY-{index}", flush=True)
    try:
        draft = composer.prompt()
    finally:
        composer.default_buffer.on_text_changed -= observe
    if index == 2:
        expected = ["current draft", "first line" + chr(10) + "second line", "current draft"]
        for value in changes:
            if expected and value == expected[0]:
                expected.pop(0)
        if expected:
            raise AssertionError("Draft did not enter and leave history in order")
    print(f"SUBMITTED-{index}:{draft.encode().hex()}:END", flush=True)
"""


def main():
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires Windows ConPTY.")
    try:
        from winpty import Backend, PtyProcess
    except ImportError:
        raise SystemExit("Install pywinpty in the smoke-test environment first.") from None

    terminal = PtyProcess.spawn([sys.executable, "-u", "-c", CHILD], cwd=str(Path.cwd()), backend=Backend.ConPTY)
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
        expect("READY-0\r\n")
        seen = seen.split("READY-0\r\n", 1)[1]
        expect("code> ")
        terminal.write("first line\nsecond line\r")
        draft = b"first line\nsecond line".hex()
        expect(f"SUBMITTED-0:{draft}:END")
        expect("READY-1\r\n")
        seen = seen.split("READY-1\r\n", 1)[1]
        expect("code> ")
        terminal.write("\x1b[A\r")
        expect(f"SUBMITTED-1:{draft}:END")
        expect("READY-2\r\n")
        seen = seen.split("READY-2\r\n", 1)[1]
        expect("code> ")
        # Space out the history keys as separate gestures on the console.
        terminal.write("current draft")
        sleep(0.15)
        terminal.write("\x1b[A")
        sleep(0.15)
        terminal.write("\x1b[B\r")
        expect(f"SUBMITTED-2:{b'current draft'.hex()}:END")
    finally:
        terminal.close()
    print("ConPTY verified Ctrl+J, Enter, Up history recall, and Down draft restoration.")


if __name__ == "__main__":
    main()
