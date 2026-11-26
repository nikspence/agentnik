"""Check the installed launcher with no terminal and a synthetic saved session."""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from agentnik.code_history import CodeHistory
from agentnik.code_lease import SessionLease
from agentnik.storage import Store


def main():
    with TemporaryDirectory(prefix="agentnik workspace ") as directory:
        project = Path(directory)
        profile = project / "unused profile"

        def discover():
            result = subprocess.run(
                ["agentnik", "code", str(project), "--data-dir", str(profile), "--list-sessions"],
                cwd=project, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=20,
            )
            assert not result.stderr, result.stderr
            return json.loads(result.stdout)

        assert discover() == [] and not profile.exists()
        session = str(uuid4())
        store = Store(profile)
        try:
            history = CodeHistory(store, project)
            with SessionLease(profile) as owner:
                owner.select(session)
                history.start("Fixture", {"model": "fixture"}, "Synthetic prompt", session, goal=True)
                saved, = history.list(session)
                assert discover() == [{
                    "id": session, "status": "running", "scope": "project",
                    "goal_status": "active", "updated_at": saved["updated"],
                }]
                assert history.list(session)[0]["code_state"] == "running"
        finally:
            store.db.close()
    print("Installed launcher listed empty and active saved sessions without a terminal.")


if __name__ == "__main__":
    main()
