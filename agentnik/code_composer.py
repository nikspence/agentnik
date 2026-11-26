"""Interactive prompt editing for the terminal Code client."""

COMMANDS = (
    "/git", "/git status", "/git stage", "/git unstage", "/git commit", "/git push",
    "/git diff", "/git diff --staged", "/git log", "/git remotes",
    "/help", "/keys", "/transcript", "/status", "/diff", "/diff --staged", "/connections", "/connections add", "/connections edit",
    "/connections show", "/connections copy", "/connections options", "/connections key",
    "/connections remove", "/connections import", "/connections export", "/connections discover", "/connection",
    "/model", "/models", "/goal", "/continue", "/web on", "/web off", "/vision", "/vision on", "/vision off",
    "/thinking on", "/thinking off", "/mcp", "/mcp use", "/mcp add", "/mcp remove", "/mcp off",
    "/permissions", "/permissions require",
    "/permissions allow-all", "/skills", "/skills show", "/skills add", "/skills remove", "/skills resources", "/skills read",
    "/scope", "/scope project", "/scope machine",
    "/context", "/context on", "/context off", "/context clear", "/attach", "/attachments", "/attachments clear",
    "/attachments remove",
    "/settings", "/settings appearance", "/settings desktop-code",
    "/settings desktop-code auto-compact on", "/settings desktop-code auto-compact off",
    "/settings desktop-code thinking on", "/settings desktop-code thinking off",
    "/settings desktop-code vision on", "/settings desktop-code vision off", "/settings chat-limits", "/settings decision",
    "/settings decision set", "/settings decision on", "/settings decision off",
    "/settings git-author", "/settings git-author set", "/settings git-author clear",
    "/settings goal", "/settings image", "/settings image set", "/settings image on",
    "/settings image off", "/settings limits", "/settings limits all unlimited", "/settings limits all default", "/settings mcp", "/settings mcp add-https",
    "/settings mcp add-local", "/settings mcp edit-https", "/settings mcp edit-local",
    "/settings mcp enable", "/settings mcp disable",
    "/settings mcp on", "/settings mcp off", "/settings mcp priority", "/settings mcp remove",
    "/settings mcp renew", "/settings mcp signin", "/settings mcp timeout", "/settings mcp token",
    "/settings subagents", "/settings subagents reset",
    "/settings tls", "/settings tls strict", "/settings tls relaxed", "/settings web", "/settings web access",
    "/settings web access public_fetch", "/settings web access strict_public",
    "/settings web desktop", "/settings web desktop on", "/settings web desktop off",
    "/settings web priority", "/settings web priority provider", "/settings web priority managed",
    "/settings web providers",
    "/settings web providers set", "/settings web providers remove",
    "/draft", "/history", "/history turn ", "/plan", "/memory", "/memory show", "/memory on", "/memory off", "/new", "/sessions", "/resume", "/resume latest", "/open", "/open latest", "/exit",
)

COMPOSER_KEYS = (
    "Enter submits. Ctrl+Enter (where supported) or Ctrl+J adds a line.",
    "Use Up/Down to recall input and Tab for slash commands.",
    "Ctrl+T or PageUp opens the transcript.",
)

TRANSCRIPT_KEYS = (
    "PageUp/PageDown or Ctrl+B/Ctrl+F scroll by a page.",
    "Ctrl+U/Ctrl+D scroll by half a page. Ctrl+T or Q returns to the draft.",
)


def create_composer(transcript=lambda: "", *, message="code> ", session_ids=None, **options):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import in_terminal
    from prompt_toolkit.completion import Completer, Completion, WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    from prompt_toolkit.keys import Keys
    from .code_settings import APPEARANCE, CHAT_LIMIT_FIELDS, FIELDS, GOAL_FIELDS, UNLIMITED_FIELDS

    setting_names = tuple(
        f"/settings {group} {name}"
        for group, fields in (("appearance", APPEARANCE), ("chat-limits", CHAT_LIMIT_FIELDS),
                              ("limits", FIELDS), ("goal", GOAL_FIELDS))
        for name in fields
    )
    unlimited = tuple(
        f"/settings {group} {name} unlimited"
        for group, fields, allowed in (("limits", FIELDS, UNLIMITED_FIELDS),
                                       ("goal", GOAL_FIELDS, GOAL_FIELDS))
        for name in fields if name in allowed
    )

    # prompt_toolkit already maps xterm's modified Enter to ControlM.
    # Add CSI-u, then distinguish modified Enter from plain CR by its raw data.
    modified_enter = ("\x1b[13;5u", "\x1b[27;5;13~")
    for sequence in modified_enter:
        ANSI_SEQUENCES.setdefault(sequence, Keys.ControlM)

    bindings = KeyBindings()

    @bindings.add("enter")
    def submit(event):
        if event.data in modified_enter:
            event.current_buffer.newline()
        else:
            event.current_buffer.validate_and_handle()

    @bindings.add("c-j")
    @bindings.add("escape", "c-j")
    def insert_newline(event):
        # The native Windows console adapter can deliver Ctrl+Enter as Esc LF.
        event.current_buffer.newline()

    @bindings.add("c-t")
    @bindings.add("pageup")
    @bindings.add("pagedown")
    def open_transcript(event):
        text = transcript()
        if text:
            page_up = event.key_sequence[-1].key == "pageup"

            async def show():
                async with in_terminal():
                    await transcript_pager(text, page_up, input=event.app.input,
                                           output=event.app.output).run_async()

            event.app.create_background_task(show())

    commands = WordCompleter((*COMMANDS, *setting_names, *unlimited,
                              *(f"{name} default" for name in setting_names)), sentence=True)

    class CodeCompleter(Completer):
        def get_completions(self, document, complete_event):
            yield from commands.get_completions(document, complete_event)
            if session_ids is None or not complete_event.completion_requested or document.text_after_cursor:
                return
            action, separator, prefix = document.text_before_cursor.partition(" ")
            if action not in ("/resume", "/open") or not separator or not prefix:
                return
            if any(char not in "0123456789abcdef-" for char in prefix.lower()):
                return
            matches = (ident for ident in session_ids() if ident.startswith(prefix.lower()))
            for index, ident in enumerate(matches):
                if index == 20:
                    break
                yield Completion(ident, start_position=-len(prefix), display_meta="saved session")

    # Tab may read SQLite history. Keep that work off the input event loop.
    options.setdefault("complete_in_thread", session_ids is not None)
    return PromptSession(
        message,
        multiline=True,
        prompt_continuation=" ...> ",
        history=InMemoryHistory(),
        completer=CodeCompleter(),
        complete_while_typing=False,
        key_bindings=bindings,
        enable_open_in_editor=False,
        **options,
    )


def run_keyboard_check():
    """Exercise the actual composer with no profile or model connection."""
    sample = "Saved keyboard-check prompt"
    transcript = "\n".join(f"Sample transcript line {index:03}" for index in range(1, 101))
    try:
        composer = create_composer(transcript=lambda: transcript, message="keys> ")
    except ModuleNotFoundError as exc:
        if exc.name != "prompt_toolkit":
            raise
        print("Install agentnik[terminal] to run the keyboard check.")
        return 1
    composer.history.append_string(sample)
    print("Offline keyboard check. No session is opened or saved.")
    print("Type a draft. Try Ctrl+Enter or Ctrl+J for a second line, and Up/Down at the draft boundary.")
    print("Use Ctrl+T to open the sample transcript, scroll with Ctrl+U/Ctrl+D, then press Q to return.")
    print("Press Enter to report the draft's line count, or Ctrl+C to cancel.")
    try:
        draft = composer.prompt()
    except (KeyboardInterrupt, EOFError):
        print("\nKeyboard check ended without submission.")
    else:
        lines = draft.count("\n") + 1 if draft else 0
        print(f"Enter submitted {lines} line(s). No model request was sent.")
    return 0


def transcript_pager(text, page_up=False, **terminal):
    from bisect import bisect_right
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import BufferControl, HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.utils import get_cwidth

    buffer = Buffer(document=Document(text, len(text)), read_only=True)
    window = Window(BufferControl(buffer=buffer), wrap_lines=True)
    bindings = KeyBindings()

    def move(direction, fraction):
        info = window.render_info
        if not info or info.window_width < 2:
            return
        height = info.window_height
        count = max(1, int(height * fraction))
        doc = buffer.document
        row = doc.cursor_position_row
        width = info.window_width

        def wrapped_starts(line):
            starts, cells = [0], 0
            for column, character in enumerate(line):
                size = get_cwidth(character)
                if size and cells + size > width:
                    starts.append(column)
                    cells = 0
                cells += size
            return starts

        starts = wrapped_starts(doc.lines[row])
        segment = bisect_right(starts, doc.cursor_position_col) - 1
        for _ in range(count):
            segment += direction
            if segment < 0 or segment >= len(starts):
                row += direction
                if row < 0:
                    buffer.cursor_position = 0
                    return
                if row >= len(doc.lines):
                    buffer.cursor_position = len(text)
                    return
                starts = wrapped_starts(doc.lines[row])
                segment = len(starts) - 1 if direction < 0 else 0
        if direction > 0 and row == len(doc.lines) - 1 and segment == len(starts) - 1:
            buffer.cursor_position = len(text)
        else:
            buffer.cursor_position = doc.translate_row_col_to_index(row, starts[segment])

    for keys, direction, fraction in (
        (("up", "k"), -1, 0), (("down", "j"), 1, 0),
        (("pageup", "c-b"), -1, 1), (("pagedown", " ", "c-f"), 1, 1),
        (("c-u",), -1, .5), (("c-d",), 1, .5),
    ):
        def scroll(event, direction=direction, fraction=fraction):
            move(direction, fraction)

        for key in keys:
            bindings.add(key)(scroll)

    @bindings.add("home")
    def top(event):
        buffer.cursor_position = 0

    @bindings.add("end")
    def bottom(event):
        buffer.cursor_position = len(text)

    @bindings.add("q")
    @bindings.add("c-c")
    @bindings.add("c-t")
    def close(event):
        event.app.exit()

    footer = Window(FormattedTextControl("Transcript · PageUp/Down or ^B/^F · Half-page ^U/^D · ^T or Q to return"),
                    height=1)
    app = Application(layout=Layout(HSplit([window, footer]), focused_element=window),
                      key_bindings=bindings, full_screen=True, **terminal)
    if page_up:
        def first_render(app):
            app.after_render -= first_render
            move(-1, 1)
            app.invalidate()

        app.after_render += first_render
    return app
