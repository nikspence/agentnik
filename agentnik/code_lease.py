"""Process-held leases for terminal sessions; the OS releases locks on exit."""

import errno
import os
from pathlib import Path
from uuid import UUID


class SessionLease:
    def __init__(self, data_dir, namespace="terminal-locks", contention_message=None):
        from .storage import default_home

        self.directory = (Path(data_dir) if data_dir else default_home()) / namespace
        self.stream = None
        self.session_id = None
        self.contention_message = contention_message or "This session is already open in another terminal. Use /new or choose another session."

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self.session_id = None

    def select(self, session_id):
        if self.session_id == session_id:
            return
        # Derive the filename only from a validated local session ID.
        filename = str(UUID(session_id))
        self.directory.mkdir(parents=True, exist_ok=True)
        stream = (self.directory / (filename + ".lock")).open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                from fcntl import flock, LOCK_EX, LOCK_NB

                flock(stream.fileno(), LOCK_EX | LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ValueError(self.contention_message) from None
            raise
        self.close()
        self.stream = stream
        self.session_id = session_id
