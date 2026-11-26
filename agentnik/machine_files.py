"""Absolute-path file inspection under the current user's OS permissions."""

import os
from pathlib import Path
import stat

from .code_limits import FULL_TEXT_BYTES


def read_machine_text(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("Use an explicit absolute file path without traversal.")
    if not path.is_file():
        raise ValueError("Choose a readable regular file.")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > FULL_TEXT_BYTES:
            raise ValueError("File is not regular or exceeds the text read limit.")
        data = stream.read(FULL_TEXT_BYTES + 1)
    if len(data) > FULL_TEXT_BYTES or b"\x00" in data:
        raise ValueError("File is binary or exceeds the text read limit.")
    return data.decode("utf-8")
