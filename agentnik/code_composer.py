"""Interactive prompt editing for the terminal Code client."""

COMMANDS = (
    "/help", "/status", "/connections", "/connections add", "/connection",
    "/model", "/exit",
)


def create_composer(**options):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory

    return PromptSession(
        "code> ",
        multiline=True,
        prompt_continuation=" ...> ",
        history=InMemoryHistory(),
        completer=WordCompleter(COMMANDS, sentence=True),
        complete_while_typing=False,
        enable_open_in_editor=False,
        **options,
    )
