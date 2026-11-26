"""Temporary project image snapshots for one terminal prompt."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .image_generation import image_bytes

IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp"}
MAX_QUEUED_IMAGE_BYTES = 8 * 1024 * 1024


def project_attachment_path(root, value):
    """Accept pasted local paths without relaxing the project file boundary."""
    from .code_agent import ProjectFiles

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    files = ProjectFiles(root)
    path = Path(value)
    if path.is_absolute():
        try:
            value = str(path.relative_to(files.root))
        except ValueError:
            raise ValueError("Choose an attachment inside the current project.") from None
    target = files.path(value)
    if not target.is_file():
        raise ValueError("Choose a regular file inside the current project.")
    return target


class ImageQueue:
    def __init__(self):
        self.directory = None
        self.items = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.clear()

    def clear(self):
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
        self.items.clear()

    def paths(self):
        return [str(path) for _, path, _ in self.items]

    def names(self):
        return [name for name, _, _ in self.items]

    def add(self, path):
        if len(self.items) >= 4:
            raise ValueError("Attach up to four images per task.")
        remaining = MAX_QUEUED_IMAGE_BYTES - sum(size for _, _, size in self.items)
        with path.open("rb") as source:
            data = source.read(remaining + 1)
        if len(data) > remaining:
            raise ValueError("Queued images exceed 8 MB in total.")
        _, suffix = image_bytes(data)
        if self.directory is None:
            self.directory = TemporaryDirectory(prefix="agentnik-code-images-")
        snapshot = Path(self.directory.name) / (uuid4().hex + suffix)
        snapshot.write_bytes(data)
        self.items.append((path.name, snapshot, len(data)))
