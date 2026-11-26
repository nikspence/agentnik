"""User-issued Git commands for the terminal client."""

from pathlib import Path
import shutil
import subprocess

from .code_terminal import terminal_text


def manual_git(root, argument, *, prompt=None, write=print):
    usage = "Use /git status, /git stage PATH, /git unstage PATH, /git commit MESSAGE, or /git push REMOTE BRANCH."
    action, _, value = argument.partition(" ")
    value = value.strip()
    if not action:
        write(usage)
        return
    if action not in ("status", "stage", "unstage", "commit", "push"):
        raise ValueError(usage)
    executable = shutil.which("git")
    if not executable:
        raise ValueError("Install Git and make it available on PATH to use /git.")
    prompt = prompt or input

    def run(*args, capture=False):
        return subprocess.run([executable, *args], cwd=root, check=False, text=True,
                              capture_output=capture)

    if action == "status" and not value:
        result = run("status", "--short", "--branch")
    elif action in ("stage", "unstage") and value:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        path = Path(value)
        if (not value or path.anchor or ".." in path.parts or not path.parts
                or any(ord(ch) < 32 for ch in value) or (root / path).is_dir()):
            raise ValueError("Choose one project-relative file, not a folder.")
        verb = "Stage" if action == "stage" else "Unstage"
        if prompt(f"{verb} {terminal_text(value)!r}? [y/N] ").strip().lower() != "y":
            return
        result = run("--literal-pathspecs", "add" if action == "stage" else "reset", "--", value)
    elif action == "commit" and value:
        write(f"Commit the staged changes in {terminal_text(root)} with message {terminal_text(value)!r}.")
        if prompt("Create commit? [y/N] ").strip().lower() != "y":
            return
        result = run("commit", "-m", value)
    elif action == "push" and len(value.split()) == 2:
        remote, branch = value.split()
        remotes = run("remote", capture=True)
        if remote.startswith("-") or remotes.returncode or remote not in remotes.stdout.splitlines():
            raise ValueError("Choose an existing named Git remote.")
        ref = f"refs/heads/{branch}"
        if branch.startswith("-") or run("check-ref-format", ref, capture=True).returncode:
            raise ValueError("Choose a valid destination branch name.")
        head = run("rev-parse", "--verify", "HEAD^{commit}", capture=True)
        if head.returncode:
            raise ValueError("There is no local commit to push.")
        commit = head.stdout.strip()
        write(f"Push {commit} to {terminal_text(remote)!r}, branch {terminal_text(branch)!r}.")
        if prompt("Push this commit? [y/N] ").strip().lower() != "y":
            return
        result = run("-c", f"remote.{remote}.mirror=false", "push", "--no-follow-tags",
                     "--recurse-submodules=no", "--", remote, f"{commit}:{ref}")
    else:
        raise ValueError(usage)
    if result.returncode:
        write(f"Git exited with status {result.returncode}. Check the output before retrying.")
