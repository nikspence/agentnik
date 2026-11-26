"""Transport contract used by the coding engine, independent of any UI."""

from typing import Protocol

from .tools import Runtime


class CodeMCPBridge(Protocol):
    server: dict
    environment_values: dict

    def request(self, action: str, payload: dict, runtime: Runtime) -> dict:
        """Perform one operation under the supplied cancellation and time limits."""
        ...

    def close_from_worker(self) -> None:
        """Release run resources or schedule cleanup on the owning thread."""
        ...
