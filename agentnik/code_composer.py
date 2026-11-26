"""Interactive prompt editing for the terminal Code client."""

COMMANDS = (
    "/help", "/status", "/connections", "/connections add", "/connection",
    "/model", "/history", "/open", "/exit",
)


def create_composer(transcript=lambda: "", **options):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import in_terminal
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("c-t")
    @bindings.add("pageup")
    @bindings.add("pagedown")
    def open_transcript(event):
        text = transcript()
        if text:
            page_up = event.key_sequence[-1].key == "pageup"

            async def show():
                async with in_terminal():
                    await transcript_pager(text, page_up).run_async()

            event.app.create_background_task(show())

    return PromptSession(
        "code> ",
        multiline=True,
        prompt_continuation=" ...> ",
        history=InMemoryHistory(),
        completer=WordCompleter(COMMANDS, sentence=True),
        complete_while_typing=False,
        key_bindings=bindings,
        enable_open_in_editor=False,
        **options,
    )


def transcript_pager(text, page_up=False):
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import BufferControl, HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    buffer = Buffer(document=Document(text, len(text)), read_only=True)
    window = Window(BufferControl(buffer=buffer), wrap_lines=True)
    bindings = KeyBindings()

    def move(direction, fraction):
        height = window.render_info.window_height if window.render_info else 1
        count = max(1, int(height * fraction))
        (buffer.cursor_up if direction < 0 else buffer.cursor_down)(count)

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

    footer = Window(FormattedTextControl("Transcript · PageUp/PageDown · Ctrl+T or Q to return"), height=1)
    app = Application(layout=Layout(HSplit([window, footer]), focused_element=window),
                      key_bindings=bindings, full_screen=True)
    if page_up:
        def first_render(app):
            app.after_render -= first_render
            move(-1, 1)
            app.invalidate()

        app.after_render += first_render
    return app
