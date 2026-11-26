"""Absolute-path file operations under the current user's OS permissions."""

from contextlib import contextmanager
from difflib import unified_diff
import hashlib
import os
from pathlib import Path
import stat

from .code_limits import FULL_TEXT_BYTES


def absolute_machine_path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("Use an explicit absolute path without traversal.")
    if os.name == "nt" and (path.drive.startswith(("\\\\?\\", "\\\\.\\"))
                            or any(":" in part for part in path.parts[1:])):
        raise ValueError("Windows device namespaces and alternate data streams are not supported.")
    return path


def list_machine_directory(value):
    entries = []
    truncated = False
    with os.scandir(absolute_machine_path(value)) as iterator:
        for entry in iterator:
            if len(entries) == 100:
                truncated = True
                break
            kind = ("link" if entry.is_symlink() else
                    "directory" if entry.is_dir(follow_symlinks=False) else
                    "file" if entry.is_file(follow_symlinks=False) else "other")
            entries.append({"name": entry.name, "kind": kind})
    return {"entries": sorted(entries, key=lambda item: item["name"]), "truncated": truncated}


@contextmanager
def open_machine_text(value, write=False):
    path = absolute_machine_path(value)
    if not path.is_file():
        raise ValueError("Choose a readable regular file.")
    flags = os.O_RDWR if write else os.O_RDONLY
    fd = os.open(path, flags | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "r+b" if write else "rb", buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > FULL_TEXT_BYTES:
            raise ValueError("File is not regular or exceeds the text read limit.")
        data = stream.read(FULL_TEXT_BYTES + 1)
        if len(data) > FULL_TEXT_BYTES or b"\x00" in data:
            raise ValueError("File is binary or exceeds the text read limit.")
        signature = (info.st_dev, info.st_ino, hashlib.sha256(data).hexdigest())
        yield stream, data.decode("utf-8"), signature


def machine_patch_preview(value, observed, old, new):
    with open_machine_text(value) as (_, before, signature):
        if observed != signature:
            raise ValueError("Read the current file with machine_read_file before editing.")
    if not old or before.count(old) != 1 or old == new:
        raise ValueError("The exact old text must occur once and the replacement must differ.")
    after = before.replace(old, new, 1)
    if "\x00" in after or len(after.encode("utf-8")) > FULL_TEXT_BYTES:
        raise ValueError("The updated file exceeds the UTF-8 text limit.")
    diff = "".join(unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                fromfile="before", tofile="after"))
    if len(diff.encode("utf-8")) > FULL_TEXT_BYTES:
        raise ValueError("The diff exceeds the review limit.")
    return after, diff


def apply_machine_patch(value, observed, after, check):
    data = after.encode("utf-8")
    with open_machine_text(value, write=True) as (stream, _, signature):
        if signature != observed:
            raise ValueError("The file changed after it was read. No edit was made.")
        check()
        stream.seek(0)
        if stream.write(data) != len(data):
            raise OSError("Incomplete file write")
        stream.truncate()


def machine_create_preview(value, text):
    path = absolute_machine_path(value)
    if not path.name or not path.parent.is_dir():
        raise ValueError("Choose a new file in an existing directory.")
    if os.path.lexists(path):
        raise ValueError("The destination already exists. No file was changed.")
    data = text.encode("utf-8")
    if b"\x00" in data or len(data) > FULL_TEXT_BYTES:
        raise ValueError("The new file must be bounded UTF-8 text.")
    return data


def create_machine_file(value, data, check):
    path = absolute_machine_path(value)
    check()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    with os.fdopen(fd, "wb", buffering=0) as stream:
        if stream.write(data) != len(data):
            raise OSError("Incomplete file write")
