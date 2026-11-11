#!/usr/bin/env python3
"""Worktree write guard for read-only reviewers (design-goldfish-review).

A reviewer that must not write is *verified*, not trusted: the orchestrator
takes a snapshot of the worktree before launching it and compares after the
reply. The snapshot covers what `git status` / `git diff HEAD` alone miss:

- HEAD, so a commit made by the reviewer is a change;
- every tracked file's content as it stands in the worktree;
- every untracked, non-ignored file's content (`design.md` is usually still
  untracked while it is being reviewed — the hole receipt 68ad6fed found).

Symlinks are recorded by target, never followed; a file's executable bit is
part of its digest. The whole repository is checked from its top level, so
running from a subdirectory never narrows the guard. The snapshot file lives
in the git dir (default `<git-dir>/sdd/worktree-fingerprint.json`), so writing
it never changes the worktree it describes, and `compare` deletes it after
reading, so a stale snapshot is never compared twice.

Accepted limits (the guard is the second layer; the first is that the
reviewer has no shell / runs in a read-only sandbox): the git dir itself
(hooks, config, index, refs) and gitignored paths are not covered.

    worktree_fingerprint.py snapshot [--root R] [--out FILE]
    worktree_fingerprint.py compare  [--root R] [--before FILE]

`compare` exits 0 when nothing changed, 1 when something did (changed paths on
stdout, one per line), 2 on a usage or git error. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCHEMA = 1


class GuardError(Exception):
    """A git or usage error: the guard cannot vouch for the worktree."""


def _git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError as error:
        raise GuardError(f"cannot run git: {error}") from error
    if result.returncode != 0:
        raise GuardError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _entry_digest(path: Path) -> str:
    try:
        if path.is_symlink():
            return "link:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
        if not path.exists():
            return "missing"
        if path.is_dir():  # a submodule or nested repo listed as one path
            return "dir"
        digest = hashlib.sha256()
        digest.update(b"x" if os.access(path, os.X_OK) else b"-")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        return "file:" + digest.hexdigest()
    except OSError as error:
        return f"unreadable:{error.errno}"


def snapshot(root: Path) -> dict[str, object]:
    """HEAD plus a digest of every tracked and untracked (non-ignored) path."""
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD").decode().strip() if _has_head(root) else ""
    listed = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = sorted({p for p in listed.decode("utf-8", errors="surrogateescape").split("\0") if p})
    entries = {p: _entry_digest(root / p) for p in paths}
    return {"schema": SCHEMA, "head": head, "entries": entries}


def _has_head(root: Path) -> bool:
    try:
        _git(root, "rev-parse", "--verify", "-q", "HEAD")
        return True
    except GuardError:
        return False


def changed_paths(before: dict[str, object], after: dict[str, object]) -> list[str]:
    """Paths whose state differs; `HEAD` when the commit moved."""
    if before.get("schema") != SCHEMA:
        raise GuardError("snapshot schema mismatch")
    changes: list[str] = []
    if before.get("head") != after.get("head"):
        changes.append("HEAD")
    old = before.get("entries")
    new = after.get("entries")
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise GuardError("malformed snapshot")
    for path in sorted(set(old) | set(new)):
        if old.get(path) != new.get(path):
            changes.append(path)
    return changes


def default_store(root: Path) -> Path:
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    return git_dir / "sdd" / "worktree-fingerprint.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, flag in (("snapshot", "--out"), ("compare", "--before")):
        command = sub.add_parser(name)
        command.add_argument("--root", default=".")
        command.add_argument(flag, dest="store")
    args = parser.parse_args(argv)
    try:
        root = Path(_git(Path(args.root).resolve(), "rev-parse", "--show-toplevel").decode().strip())
        store = Path(args.store) if args.store else default_store(root)
        if args.command == "snapshot":
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps(snapshot(root), sort_keys=True), encoding="utf-8")
            return 0
        try:
            before = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise GuardError(f"cannot read snapshot {store}: {error}") from error
        finally:
            store.unlink(missing_ok=True)
        changes = changed_paths(before, snapshot(root))
    except GuardError as error:
        print(f"worktree_fingerprint: {error}", file=sys.stderr)
        return 2
    for path in changes:
        print(path)
    return 1 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
