"""Exercise the Windows composer through ConPTY. Requires optional pywinpty."""

from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
from time import monotonic, sleep


CHILD = """
import sys
from agentnik.code_composer import create_composer
import agentnik.code_composer as impl
original_pager = impl.transcript_pager
def observe_pager(*args, **kwargs):
    pager = original_pager(*args, **kwargs)
    start = pager.current_buffer.cursor_position
    seen = set()
    def rendered(app):
        state = "AT-END" if app.current_buffer.cursor_position == start else "SCROLLED"
        if state not in seen:
            seen.add(state)
            print(f"PAGER-{state}", flush=True)
    pager.after_render += rendered
    return pager
impl.transcript_pager = observe_pager
composer = create_composer(transcript=lambda: chr(10).join(f"Transcript row {i:03}" for i in range(100)),
                           session_ids=lambda: (sys.argv[1],))
print("CANCEL-READY", flush=True)
try:
    composer.prompt()
except KeyboardInterrupt:
    print("DRAFT-CANCELLED", flush=True)
else:
    raise AssertionError("Ctrl+C did not cancel the draft")
for index in range(6):
    changes = []
    def observe(buffer):
        changes.append(buffer.text)
        if index == 4 and buffer.text == "/resume " + sys.argv[1]:
            print("SESSION-ID-COMPLETED", flush=True)
    composer.default_buffer.on_text_changed += observe
    print(f"READY-{index}", flush=True)
    try:
        draft = composer.prompt(default="recovered draft") if index == 5 else composer.prompt()
    finally:
        composer.default_buffer.on_text_changed -= observe
    if index == 2:
        expected = ["current draft", chr(10).join(("first line", "second line", "third line")), "current draft"]
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

    session_id = "abcd1234-0000-4000-a000-123456789abc"
    terminal = PtyProcess.spawn([sys.executable, "-u", "-c", CHILD, session_id], cwd=str(Path.cwd()), backend=Backend.ConPTY)
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
        expect("CANCEL-READY\r\n")
        seen = seen.split("CANCEL-READY\r\n", 1)[1]
        expect("code>")
        terminal.write("discard this draft")
        sleep(0.15)
        terminal.write("\x03")
        expect("DRAFT-CANCELLED")
        expect("READY-0\r\n")
        seen = seen.split("READY-0\r\n", 1)[1]
        # VT output may reset formatting between the label and its trailing space.
        expect("code>")
        terminal.write("first line\nsecond line\x1b\nthird line\r")
        draft = b"first line\nsecond line\nthird line".hex()
        expect(f"SUBMITTED-0:{draft}:END")
        expect("READY-1\r\n")
        seen = seen.split("READY-1\r\n", 1)[1]
        expect("code>")
        terminal.write("\x1b[A\r")
        expect(f"SUBMITTED-1:{draft}:END")
        expect("READY-2\r\n")
        seen = seen.split("READY-2\r\n", 1)[1]
        expect("code>")
        # Space out the history keys as separate gestures on the console.
        terminal.write("current draft")
        sleep(0.15)
        terminal.write("\x1b[A")
        sleep(0.15)
        terminal.write("\x1b[B\r")
        expect(f"SUBMITTED-2:{b'current draft'.hex()}:END")
        expect("READY-3\r\n")
        seen = seen.split("READY-3\r\n", 1)[1]
        expect("code>")
        terminal.write("draft kept across scrollback")
        sleep(0.25)
        terminal.write("\x14")
        expect("PAGER-AT-END")
        terminal.write("\x15")
        expect("PAGER-SCROLLED")
        terminal.write("q")
        sleep(0.25)
        terminal.write("\r")
        expect(f"SUBMITTED-3:{b'draft kept across scrollback'.hex()}:END")
        expect("READY-4\r\n")
        seen = seen.split("READY-4\r\n", 1)[1]
        expect("code>")
        terminal.write("/resume abcd\t")
        expect("SESSION-ID-COMPLETED")
        terminal.write("\r")
        completed = ("/resume " + session_id).encode().hex()
        expect(f"SUBMITTED-4:{completed}:END")
        expect("READY-5")
        expect("code>")
        sleep(0.15)
        terminal.write(" edited\r")
        revised = b"recovered draft edited".hex()
        expect(f"SUBMITTED-5:{revised}:END")
    finally:
        terminal.close()
    print("ConPTY verified Ctrl+C draft cancellation, Ctrl+J, Esc-LF modified Enter, Enter, Up/Down history, draft recovery after transcript scrollback, session ID completion, and editing a preloaded draft.")


if __name__ == "__main__":
    main()
