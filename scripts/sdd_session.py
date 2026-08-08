#!/usr/bin/env python3
"""Session registry and worktree bindings for concurrent SDD work.

Several Claude Code sessions on the same clone share one working directory and
one HEAD, so a second `git checkout -b sdd/<other>` drags the first session's
dirty files onto the wrong branch — and `mark-ready` then records a
`head_branch` / `implementation_sha` that does not describe the work. That is
not merely a merge conflict: it corrupts the evidence the merge gate depends on
(ADR 0001).

This module answers three questions deterministically, so no phase has to guess:

  * is another session working this clone right now?  (`check`)
  * does this project isolate every feature anyway?   (`check` / `policy`)
  * which worktree is this feature bound to?          (`resolve`)

The second one exists because evidence alone answers the wrong question. A clone
with nothing in flight reports `CLEAR`, so the FIRST feature always stayed in the
main clone — and by staying it produced exactly the evidence (`HEAD` on someone
else's `sdd/` branch, in-flight change directories) that the check later reports
as `CONFLICT` to the second one. Projects that want a pristine base declare
`isolation: always` in `sdd/project.md`; the verdict keeps describing the
evidence, and the policy decides what to do about it (ADR 0002).

The registry lives in the repository's **common** git directory
(`git rev-parse --git-common-dir`), which every linked worktree shares and which
is never committed and never shows up in `git status`. Liveness comes from the
recorded pid, so a session that died takes its own claim with it: there are no
zombie locks to clear by hand.

Scope: this is the *machine* claim. The team claim is still the remote
`sdd/<feature>` branch, and the two compose — a colleague's branch and a
colleague's process are different facts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SCHEMA = 1
REGISTRY_NAME = "sessions.json"
# The project's isolation policy, declared in `sdd/project.md`. `on-conflict` is
# the default so a project that declares nothing behaves exactly as before.
ISOLATION_POLICIES = ("on-conflict", "always")
DEFAULT_ISOLATION_POLICY = "on-conflict"
POLICY_FILE = Path("sdd") / "project.md"
# Accepts `isolation: always`, `- isolation: always` and `**isolation**: always`,
# which are the three shapes the same line takes in a markdown document.
POLICY_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?isolation(?:\*\*)?[ \t]*:[ \t]*`?([A-Za-z][A-Za-z-]*)`?",
    re.IGNORECASE | re.MULTILINE,
)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Environment Claude Code exports into every Bash call. Absent under other
# runners (or a plain shell), which is why every read has a fallback: an
# unidentifiable session must degrade to "no claim", never to a wrong claim.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
PID_ENV = "CLAUDE_PID"
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class SessionError(RuntimeError):
    """Actionable session-registry failure."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_git(args: list[str], root: Path, runner: Runner = subprocess.run) -> str:
    try:
        result = runner(
            ["git", *args], cwd=root, check=False, capture_output=True, text=True
        )
    except OSError as error:
        raise SessionError(f"Could not execute git: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise SessionError(f"git {' '.join(args)} failed: {detail or 'unknown error'}")
    return result.stdout.strip()


def try_git(
    args: list[str], root: Path, runner: Runner = subprocess.run
) -> str | None:
    try:
        result = runner(
            ["git", *args], cwd=root, check=False, capture_output=True, text=True
        )
    except OSError:
        return None
    return None if result.returncode else result.stdout.strip()


def common_dir(root: Path, runner: Runner = subprocess.run) -> Path:
    """The shared `.git` directory of this repository.

    From the main worktree git answers with a relative path (`.git`); from a
    linked worktree, an absolute one. Resolving against `root` handles both, and
    is why the registry is the same file for every worktree of the repo.
    """
    answer = try_git(["rev-parse", "--git-common-dir"], root, runner)
    if answer is None:
        raise SessionError(
            f"{root} is not inside a git repository, so sessions cannot be tracked."
        )
    path = Path(answer)
    return path if path.is_absolute() else (root / path).resolve()


def registry_path(root: Path, runner: Runner = subprocess.run) -> Path:
    return common_dir(root, runner) / "sdd" / REGISTRY_NAME


def read_registry(path: Path) -> dict:
    if not path.is_file():
        return {"schema": SCHEMA, "sessions": {}, "worktrees": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # The registry is a cache of live facts, not a source of truth: a
        # corrupted one is rebuilt rather than turned into a blocking error.
        return {"schema": SCHEMA, "sessions": {}, "worktrees": {}}
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "sessions": {}, "worktrees": {}}
    data.setdefault("schema", SCHEMA)
    for key in ("sessions", "worktrees"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def write_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: two sessions can register at the same moment, and a
    # half-written registry would be read as "nobody is working here".
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def is_alive(pid: object) -> bool:
    """Whether a recorded pid is still running.

    PermissionError means the process exists but belongs to someone else, which
    still counts as alive — treating it as dead would hand its claim away.
    """
    if not isinstance(pid, (int, str)):
        return False
    try:
        number = int(pid)
    except ValueError:
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def current_session() -> str:
    return os.environ.get(SESSION_ENV, "").strip()


def current_pid() -> int:
    raw = os.environ.get(PID_ENV, "").strip()
    try:
        return int(raw)
    except ValueError:
        return os.getppid()


def prune(data: dict) -> list[str]:
    """Drop sessions whose process is gone. Returns the ids removed.

    Worktree bindings deliberately survive: the session that created one dies at
    the end of every conversation, but the worktree keeps the unfinished work and
    the next session for that feature has to find it.
    """
    dead = [
        session_id
        for session_id, entry in data["sessions"].items()
        if not is_alive(entry.get("pid"))
    ]
    for session_id in dead:
        del data["sessions"][session_id]
    return dead


def in_linked_worktree(root: Path, runner: Runner = subprocess.run) -> bool:
    git_dir = try_git(["rev-parse", "--absolute-git-dir"], root, runner)
    if git_dir is None:
        return False
    return Path(git_dir).resolve() != common_dir(root, runner)


def current_branch(root: Path, runner: Runner = subprocess.run) -> str:
    return try_git(["branch", "--show-current"], root, runner) or ""


def is_dirty(root: Path, runner: Runner = subprocess.run) -> bool:
    status = try_git(["status", "--porcelain"], root, runner)
    return bool(status)


def active_features(root: Path) -> list[str]:
    """Features with a change directory that is not archived.

    Read from disk rather than from the registry: a change left behind by a
    session that ended weeks ago is still in-flight work this clone holds.
    """
    changes = root / "sdd" / "changes"
    if not changes.is_dir():
        return []
    return sorted(
        path.name
        for path in changes.iterdir()
        if path.is_dir() and path.name != "archive"
    )


def feature_of_branch(branch: str) -> str:
    return branch[len("sdd/") :] if branch.startswith("sdd/") else ""


@dataclass(frozen=True)
class IsolationPolicy:
    """What the project decided about isolating features.

    `policy` is always one of `ISOLATION_POLICIES`: an unreadable or unrecognised
    declaration degrades to today's behaviour rather than to an error, because
    this is read on the hot path of every phase. `declared` keeps whatever the
    project actually wrote, so a typo can be *reported* (`SDD026`) instead of
    silently becoming the default.
    """

    policy: str
    declared: str
    source: str
    valid: bool

    @property
    def always(self) -> bool:
        return self.policy == "always"


def read_isolation_policy(root: Path) -> IsolationPolicy:
    """The isolation policy declared in `sdd/project.md`, or the default.

    Deliberately git-free: the policy is committed project state, so it answers
    the same outside a repository as inside one.
    """
    try:
        text = (root / POLICY_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return IsolationPolicy(DEFAULT_ISOLATION_POLICY, "", "", True)
    # A declaration inside an HTML comment is documentation, not a decision: the
    # scaffold template explains both values in one, and reading that as active
    # would turn a project's placeholder into a policy nobody chose.
    match = POLICY_RE.search(HTML_COMMENT_RE.sub("", text))
    if not match:
        return IsolationPolicy(DEFAULT_ISOLATION_POLICY, "", "", True)
    declared = match.group(1)
    source = str(POLICY_FILE)
    if declared.lower() in ISOLATION_POLICIES:
        return IsolationPolicy(declared.lower(), declared, source, True)
    return IsolationPolicy(DEFAULT_ISOLATION_POLICY, declared, source, False)


def default_branch(root: Path, runner: Runner = subprocess.run) -> str:
    """The branch this repository's work lands in.

    `origin/HEAD` is the published answer. Without a remote the current branch is
    the next best fact — unless it is an `sdd/` branch, which is a feature, not a
    base. `main` is the last resort, and only ever a guess.
    """
    head = try_git(
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root, runner
    )
    if head:
        return head.removeprefix("origin/")
    branch = current_branch(root, runner)
    if branch and not branch.startswith("sdd/"):
        return branch
    return "main"


def base_facts(root: Path, runner: Runner = subprocess.run) -> dict:
    """What a new worktree would actually branch from, and what that would lose.

    `EnterWorktree` defaults to `baseRef: fresh`, which branches from
    `origin/<default>`. Under `isolation: always` that default is on the hot path
    of every feature, so the two ways it goes wrong are reported up front rather
    than discovered afterwards: a base that was never published (nothing to
    branch from) and a local base that is ahead of it (commits silently left
    behind, and a `BASE` in `STATE.md` the worktree did not come from).
    """
    branch = default_branch(root, runner)
    remote_ref = f"origin/{branch}"
    published = (
        try_git(
            ["rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}"],
            root,
            runner,
        )
        is not None
    )
    local = (
        try_git(
            ["rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}"], root, runner
        )
        is not None
    )
    unpushed = 0
    if published and local:
        counted = try_git(
            ["rev-list", "--count", f"{remote_ref}..{branch}"], root, runner
        )
        unpushed = int(counted) if counted and counted.isdigit() else 0
    return {
        "default_branch": branch,
        "has_remote": bool(try_git(["remote"], root, runner)),
        "published": published,
        # What to branch from, in the order sdd_lifecycle.resolve_base_ref and
        # worktree_status already use: the published base first, the local one
        # second, and "" when the repository has neither (an empty repo).
        "base_ref": remote_ref if published else (branch if local else ""),
        "unpushed": unpushed,
    }


def check(
    root: Path, feature: str | None, runner: Runner = subprocess.run
) -> dict:
    """Evidence that another session is working this clone, plus what to do.

    The verdict (`conflict`) stays a description of the evidence — a policy that
    made it report a conflict nobody has would make every later reading of it a
    lie. `isolate` is the separate, actionable answer: it is true when there IS
    evidence, or when the project declared `isolation: always`.
    """
    data = read_registry(registry_path(root, runner))
    # Pruned in memory only: `check` is called by read-only phases (/sdd:status,
    # /sdd:doctor) whose contract is to change nothing. `claim`, `release` and the
    # explicit `prune` command are what persist it.
    prune(data)

    me = current_session()
    others = [
        {"session_id": session_id, **entry}
        for session_id, entry in sorted(data["sessions"].items())
        if session_id != me
    ]
    branch = current_branch(root, runner)
    branch_feature = feature_of_branch(branch)
    dirty = is_dirty(root, runner)
    active = active_features(root)
    other_active = [name for name in active if name != feature]

    reasons: list[str] = []
    if others:
        for entry in others:
            reasons.append(
                f"another live session ({entry.get('pid')}) holds "
                f"{entry.get('feature') or 'no feature'} at "
                f"{entry.get('worktree') or 'unknown path'}"
            )
    if branch_feature and feature and branch_feature != feature:
        reasons.append(
            f"HEAD is on sdd/{branch_feature}, a different feature than {feature}"
            + (" and the tree is dirty" if dirty else "")
        )
    if feature and other_active and not others:
        reasons.append(
            "this clone holds in-flight changes for "
            + ", ".join(other_active)
            + " — switching branches here would move their files"
        )

    policy = read_isolation_policy(root)
    return {
        "session_id": me,
        "worktree": str(root),
        # Where a new worktree has to be created from. A session already standing
        # in a linked worktree must not nest another one inside it.
        "main_worktree": str(common_dir(root, runner).parent.resolve()),
        "in_linked_worktree": in_linked_worktree(root, runner),
        "branch": branch,
        "dirty": dirty,
        "feature": feature or "",
        "bound_worktree": (data["worktrees"].get(feature) or {}).get("path", "")
        if feature
        else "",
        "live_sessions": others,
        "active_features": active,
        "conflict": bool(reasons),
        "reasons": reasons,
        "policy": policy.policy,
        "policy_declared": policy.declared,
        "policy_source": policy.source,
        "policy_valid": policy.valid,
        "isolate": bool(reasons) or policy.always,
        "base": base_facts(root, runner),
    }


def claim(
    root: Path,
    feature: str,
    worktree: Path | None = None,
    runner: Runner = subprocess.run,
) -> str:
    """Bind this session (and the given worktree) to a feature."""
    path = registry_path(root, runner)
    data = read_registry(path)
    prune(data)

    me = current_session()
    target = (worktree or root).resolve()

    holder = next(
        (
            (session_id, entry)
            for session_id, entry in data["sessions"].items()
            if entry.get("feature") == feature and session_id != me
        ),
        None,
    )
    if holder:
        session_id, entry = holder
        raise SessionError(
            f"Feature '{feature}' is claimed by live session {session_id} "
            f"(pid {entry.get('pid')}) at {entry.get('worktree')}. Work another "
            "feature, or let that session finish."
        )

    # A feature is bound to exactly one worktree. Re-binding silently is how half
    # the work would end up in one tree and half in another. A binding whose
    # directory is gone is stale, so that one is replaced rather than enforced.
    binding = data["worktrees"].get(feature) or {}
    bound = Path(binding["path"]) if binding.get("path") else None
    if bound and bound != target and bound.is_dir():
        raise SessionError(
            f"Feature '{feature}' is already bound to {bound}. "
            f"Enter that worktree instead of {target}, or release the binding."
        )

    if me:
        data["sessions"][me] = {
            "pid": current_pid(),
            # Where this SESSION is, which is not necessarily the feature's
            # worktree: `claim --worktree <p>` can bind a path the caller is not
            # standing in. Conflating the two made the occupancy check read a
            # binding as "somebody is in there".
            "worktree": str(root.resolve()),
            "branch": current_branch(root, runner),
            "feature": feature,
            "started": (data["sessions"].get(me) or {}).get("started", now()),
            "last_seen": now(),
        }
    data["worktrees"][feature] = {
        "path": str(target),
        "branch": current_branch(target, runner),
        "created": binding.get("created", now()),
    }
    write_registry(path, data)
    if not me:
        return (
            f"Bound '{feature}' to {target}. No {SESSION_ENV} in the environment, "
            "so no session was registered: conflict detection is degraded to "
            "on-disk evidence."
        )
    return f"Claimed '{feature}' for this session at {target}."


def resolve(root: Path, feature: str, runner: Runner = subprocess.run) -> str:
    """The worktree a feature lives in, or "" when it has none.

    Reports a binding whose directory has disappeared as unbound: a stale path
    would send the next phase into a directory that no longer exists.

    The registry answers first, and git answers when the registry cannot. That
    fallback is not redundancy: the registry is machine-local and only knows what
    was `claim`ed, so a worktree created by hand, one made on another machine, or
    one whose registry got rebuilt after corruption is invisible to it — while
    git has known about it all along. `worktrees`/`retire` already ask git for
    exactly this reason; `resolve` asking only the registry meant every phase
    concluded "this feature has no worktree, work here" and carried on in the
    main worktree, with HEAD on the base branch. That is survivable while the
    conversation still remembers where the work is. It stops being survivable
    once phases start in a fresh context (shared rule 11), which is why the
    fallback landed with it.
    """
    data = read_registry(registry_path(root, runner))
    binding = data["worktrees"].get(feature) or {}
    path = binding.get("path", "")
    if path and Path(path).is_dir():
        return path
    return worktree_of_branch(root, feature, runner)


def worktree_of_branch(
    root: Path, feature: str, runner: Runner = subprocess.run
) -> str:
    """The worktree git has checked out on `sdd/<feature>`, or "".

    Matches the branch exactly rather than through `feature_of_worktree`: an
    `sdd/<feature>-archive` worktree also belongs to the feature, but it is not
    where the feature's phases run.
    """
    if not feature:
        return ""
    for entry in git_worktrees(root, runner):
        if entry.get("branch") == f"sdd/{feature}" and Path(entry["path"]).is_dir():
            return entry["path"]
    return ""


def release(root: Path, feature: str, runner: Runner = subprocess.run) -> str:
    path = registry_path(root, runner)
    data = read_registry(path)
    prune(data)
    removed = data["worktrees"].pop(feature, None)
    for entry in data["sessions"].values():
        if entry.get("feature") == feature:
            entry["feature"] = ""
    write_registry(path, data)
    if not removed:
        return f"No worktree binding for '{feature}'."
    return f"Released '{feature}' (was {removed.get('path')})."


def git_worktrees(root: Path, runner: Runner = subprocess.run) -> list[dict]:
    """Every worktree git knows about, parsed from `--porcelain`.

    Git is the authority on what EXISTS; the registry only says whose it is. The
    cleanup used to ask the registry, so a worktree created by hand — before the
    registry existed, or outside the flow — was invisible and survived archive
    forever. Enumerating from git is what closes that hole.
    """
    listed = try_git(["worktree", "list", "--porcelain"], root, runner)
    if listed is None:
        return []
    found: list[dict] = []
    current: dict = {}
    for line in listed.splitlines() + [""]:
        if not line.strip():
            if current:
                found.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": value, "branch": "", "head": "", "locked": False}
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "HEAD":
            current["head"] = value
        elif key == "locked":
            current["locked"] = True
        elif key == "detached":
            current["branch"] = ""
    return found


def feature_of_worktree(entry: dict, bindings: dict) -> str:
    """Which feature a worktree belongs to.

    The registry is consulted first; failing that the branch name is the clue,
    since the flow names branches `sdd/<feature>`. A trailing `-archive` is
    stripped: archive work happens on `sdd/<feature>-archive`, and that worktree
    still belongs to `<feature>` — a real case, and the reason a naive lookup
    finds nothing.
    """
    for feature, binding in bindings.items():
        if binding.get("path") and Path(binding["path"]) == Path(entry["path"]):
            return feature
    feature = feature_of_branch(entry.get("branch", ""))
    return feature.removesuffix("-archive") if feature else ""


def archived_feature(root: Path, feature: str) -> bool:
    archive = root / "sdd" / "changes" / "archive"
    if not feature or not archive.is_dir():
        return False
    return any(
        path.is_dir() and path.name.split("-", 3)[-1] == feature
        for path in archive.iterdir()
    )


def base_branch_for(root: Path, feature: str, runner: Runner = subprocess.run) -> str:
    """The branch a worktree's work had to land in.

    Prefers what the change itself recorded — that is the base the merge gate
    already certified against — and only then falls back to the repository's
    default branch.
    """
    archive = root / "sdd" / "changes" / "archive"
    if feature and archive.is_dir():
        for path in sorted(archive.iterdir()):
            if path.is_dir() and path.name.split("-", 3)[-1] == feature:
                state = path / "STATE.md"
                if state.is_file():
                    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("base_branch:"):
                            recorded = line.split(":", 1)[1].strip()
                            if recorded:
                                return recorded
    return default_branch(root, runner)


@dataclass(frozen=True)
class WorktreeStatus:
    path: str
    branch: str
    feature: str
    is_main: bool
    registered: bool
    locked: bool
    archived: bool
    merged: bool
    clean: bool
    unpushed: int
    occupied_by: str
    blockers: tuple[str, ...]

    @property
    def retirable(self) -> bool:
        return not self.blockers and not self.is_main


def worktree_status(
    root: Path, runner: Runner = subprocess.run
) -> list[WorktreeStatus]:
    """Every worktree with the objective evidence for retiring it.

    Same standard as the merge gate: retirement is permitted by facts, never by
    assumption. Each unmet condition becomes a named blocker, so a refusal always
    says which one.
    """
    data = read_registry(registry_path(root, runner))
    prune(data)
    bindings = data["worktrees"]
    # Occupancy means SOMEBODY ELSE is in there. Counting the calling session
    # would make it block itself: /sdd:archive runs from the main worktree while
    # still holding the feature's claim, and would refuse to retire its own work.
    me = current_session()
    live = {
        str(entry.get("worktree", "")): session_id
        for session_id, entry in data["sessions"].items()
        if entry.get("worktree") and session_id != me
    }
    main = common_dir(root, runner).parent.resolve()
    here = root.resolve()

    out: list[WorktreeStatus] = []
    for entry in git_worktrees(root, runner):
        path = Path(entry["path"]).resolve()
        is_main = path == main
        feature = feature_of_worktree(entry, bindings)
        archived = archived_feature(root, feature)
        base = base_branch_for(root, feature, runner)
        branch = entry.get("branch", "")
        # Prefer the published base, fall back to the local one — same order as
        # sdd_lifecycle.resolve_base_ref, because a repo with no remote is a
        # legitimate workflow the merge gate already supports.
        base_ref = next(
            (
                candidate
                for candidate in (f"origin/{base}", base)
                if try_git(
                    ["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
                    root,
                    runner,
                )
                is not None
            ),
            "",
        )
        merged = bool(branch) and bool(base_ref) and (
            try_git(["merge-base", "--is-ancestor", branch, base_ref], root, runner)
            is not None
        )
        clean = not is_dirty(path, runner) if path.is_dir() else True
        ahead = try_git(["rev-list", "--count", "@{upstream}..HEAD"], path, runner)
        unpushed = int(ahead) if ahead and ahead.isdigit() else 0
        occupied = live.get(str(path), "")

        blockers: list[str] = []
        if is_main:
            blockers.append("this is the main worktree")
        else:
            if path == here:
                # Removing the directory you are standing in leaves the caller
                # with a cwd that no longer exists and a git that cannot answer.
                blockers.append("you are inside it — retire it from another worktree")
            if occupied:
                blockers.append(f"a live session ({occupied}) is working in it")
            if not feature:
                blockers.append("no feature could be determined (branch is not sdd/<feature>)")
            elif not archived:
                blockers.append(f"change '{feature}' is not archived yet")
            if branch and not merged:
                blockers.append(
                    f"branch '{branch}' is not contained in {base_ref or base}"
                )
            if not clean:
                blockers.append("the working tree has uncommitted changes")
            if unpushed:
                blockers.append(f"{unpushed} commit(s) never pushed")
            if entry.get("locked"):
                blockers.append("git has it locked (`git worktree unlock` first)")

        out.append(
            WorktreeStatus(
                path=str(path),
                branch=branch,
                feature=feature,
                is_main=is_main,
                registered=str(path) in {str(Path(b["path"])) for b in bindings.values() if b.get("path")},
                locked=bool(entry.get("locked")),
                archived=archived,
                merged=merged,
                clean=clean,
                unpushed=unpushed,
                occupied_by=occupied,
                blockers=tuple(blockers),
            )
        )
    return out


def retire(
    root: Path,
    feature: str | None = None,
    path: Path | None = None,
    force: bool = False,
    runner: Runner = subprocess.run,
) -> str:
    """Retire a worktree: remove it, delete its branch, drop its binding.

    Refuses on any unmet condition unless `force`, and NEVER reports success it
    cannot see: git unregisters the worktree before deleting the directory, so a
    failed deletion used to leave an orphan directory nobody would report again.
    This verifies the directory is actually gone and says so loudly when it is
    not, with the exact command to finish the job.
    """
    statuses = worktree_status(root, runner)
    target = None
    for status in statuses:
        if path and Path(status.path) == path.resolve():
            target = status
        elif feature and status.feature == feature and not status.is_main:
            target = status
    if target is None:
        raise SessionError(
            f"No worktree found for {'path ' + str(path) if path else 'feature ' + str(feature)}. "
            "`sdd_session.py worktrees` lists what git knows about."
        )
    if target.blockers and not force:
        listed = "; ".join(target.blockers)
        raise SessionError(
            f"Refusing to retire {target.path}: {listed}. Resolve it, or pass "
            "--force if you are certain the work is expendable."
        )

    messages: list[str] = []
    removal = ["worktree", "remove"] + (["--force"] if force else []) + [target.path]
    if try_git(removal, root, runner) is None:
        raise SessionError(
            f"`git worktree remove {target.path}` failed. Nothing was changed; "
            "check the path is writable and no process is inside it."
        )
    # The check that stops F3 from recurring: git may unregister and still leave
    # the tree behind, and a directory git no longer tracks is one nothing reports.
    if Path(target.path).exists():
        messages.append(
            f"WARNING: git unregistered the worktree but {target.path} still exists "
            "on disk and is no longer tracked by git — delete it by hand: "
            f"rm -rf {target.path}. If that fails with 'Permission denied' on "
            "directories that are EMPTY and yours (typically node_modules, .venv, "
            ".next — the mountpoints of named container volumes), the blocker is an "
            "ACL, not a mode: check `ls -lde <dir>` for a `deny delete` entry and "
            "drop it with `chmod -a# 0 <dir>` before retrying."
        )
    else:
        messages.append(f"Removed worktree {target.path}.")

    if target.branch:
        deletion = try_git(["branch", "-d", target.branch], root, runner)
        if deletion is None and force:
            deletion = try_git(["branch", "-D", target.branch], root, runner)
        messages.append(
            f"Deleted branch {target.branch}."
            if deletion is not None
            else f"Kept branch {target.branch} (git refused; it may hold unmerged work)."
        )
    if target.feature:
        release(root, target.feature, runner)
        messages.append(f"Released the binding for '{target.feature}'.")
    return " ".join(messages)


def orphan_bindings(root: Path, runner: Runner = subprocess.run) -> list[dict]:
    """Bindings whose worktree is gone, or whose change is already archived.

    These are what `/sdd:doctor` reports: a binding nobody will ever resolve, and
    a worktree still on disk for work that already shipped.
    """
    data = read_registry(registry_path(root, runner))
    archive = root / "sdd" / "changes" / "archive"
    archived = (
        {
            path.name.split("-", 3)[-1]
            for path in archive.iterdir()
            if path.is_dir()
        }
        if archive.is_dir()
        else set()
    )
    orphans: list[dict] = []
    for feature, binding in sorted(data["worktrees"].items()):
        path = Path(binding.get("path", ""))
        if not binding.get("path") or not path.is_dir():
            orphans.append({"feature": feature, "reason": "missing", **binding})
        elif feature in archived:
            orphans.append({"feature": feature, "reason": "archived", **binding})
    return orphans


def render_policy(report: dict) -> str:
    if not report["policy_valid"]:
        return (
            f"policy: {report['policy']} (ignored an unrecognised "
            f"'{report['policy_declared']}' in {report['policy_source']} — "
            "SDD026; expected 'always' or 'on-conflict')"
        )
    if report["policy_source"]:
        return f"policy: {report['policy']} (declared in {report['policy_source']})"
    return f"policy: {report['policy']} (default — no isolation declared)"


def render_base(base: dict) -> str:
    line = f"base: {base['default_branch']}"
    if not base["base_ref"]:
        return line + " — nothing to branch from yet (no commits on it)"
    line += f" → a new worktree branches from {base['base_ref']}"
    if not base["published"]:
        line += " (not published: EnterWorktree's 'fresh' default cannot resolve it)"
    if base["unpushed"]:
        line += f" · {base['unpushed']} local commit(s) NOT in origin"
    return line


def render_check(report: dict) -> str:
    lines = [
        f"session: {report['session_id'] or '(unidentified)'}",
        f"worktree: {report['worktree']}"
        + (" (linked)" if report["in_linked_worktree"] else " (main)"),
        f"branch: {report['branch'] or '(detached)'}"
        + (" · dirty" if report["dirty"] else " · clean"),
        render_policy(report),
        render_base(report["base"]),
    ]
    if report["feature"]:
        bound = report["bound_worktree"] or "(unbound)"
        lines.append(f"feature {report['feature']} → {bound}")
    lines.append("")
    if report["conflict"]:
        lines.append("CONFLICT — this clone is not free:")
        lines.extend(f"  - {reason}" for reason in report["reasons"])
    else:
        lines.append("CLEAR — no other session is working this clone.")
    # The verdict describes the evidence; this line is the decision. They are
    # printed apart because CLEAR + isolate is a real, and now common, combination.
    if report["isolate"]:
        because = (
            f"{report['policy_source']} declares isolation: always"
            if not report["conflict"]
            else "the evidence above"
        )
        lines.append(
            f"ISOLATE — give this feature its own worktree before creating its "
            f"branch ({because}). Protocol: references/isolation.md."
        )
    else:
        lines.append(
            "WORK HERE — no conflicting evidence, and this project does not "
            "declare isolation: always."
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)
    checker = subparsers.add_parser(
        "check", help="is another session working this clone? (exit 1 = conflict)"
    )
    checker.add_argument("--feature", default=None)
    claimer = subparsers.add_parser("claim", help="bind a feature to a worktree")
    claimer.add_argument("feature")
    claimer.add_argument("--worktree", type=Path, default=None)
    for name in ("resolve", "release"):
        command = subparsers.add_parser(name)
        command.add_argument("feature")
    subparsers.add_parser(
        "policy", help="the project's isolation policy (always | on-conflict)"
    )
    subparsers.add_parser("list", help="live sessions and worktree bindings")
    subparsers.add_parser("prune", help="drop sessions whose process is gone")
    subparsers.add_parser("orphans", help="bindings with no worktree, or already archived")
    subparsers.add_parser(
        "worktrees",
        help="every worktree git knows about, with whether it can be retired",
    )
    retirement = subparsers.add_parser(
        "retire", help="remove a finished worktree, its branch and its binding"
    )
    retirement.add_argument("feature", nargs="?", default=None)
    retirement.add_argument("--path", type=Path, default=None)
    retirement.add_argument(
        "--force",
        action="store_true",
        help="override the blockers — discards whatever the worktree still holds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "check":
            report = check(root, args.feature)
            print(json.dumps(report, indent=2) if args.json else render_check(report), end="")
            return 1 if report["conflict"] else 0
        if args.command == "policy":
            # Git-free on purpose: the policy is committed project state, and
            # /sdd:init reads it while the repository may still be a bare clone.
            policy = read_isolation_policy(root)
            if args.json:
                print(json.dumps(vars(policy), indent=2))
            else:
                print(policy.policy)
            if not policy.valid:
                print(
                    f"ERROR: {policy.source} declares isolation: "
                    f"'{policy.declared}', which is not one of "
                    f"{' | '.join(ISOLATION_POLICIES)}. Falling back to "
                    f"{DEFAULT_ISOLATION_POLICY}.",
                    file=sys.stderr,
                )
                return 2
            return 0
        if args.command == "claim":
            print(claim(root, args.feature, args.worktree))
        elif args.command == "resolve":
            path = resolve(root, args.feature)
            if path:
                print(path)
            return 0 if path else 1
        elif args.command == "release":
            print(release(root, args.feature))
        elif args.command == "prune":
            path = registry_path(root)
            data = read_registry(path)
            dead = prune(data)
            write_registry(path, data)
            print(f"Pruned {len(dead)} dead session(s).")
        elif args.command == "worktrees":
            statuses = worktree_status(root)
            if args.json:
                print(json.dumps([vars(s) for s in statuses], indent=2))
            else:
                for status in statuses:
                    mark = "RETIRABLE" if status.retirable else "en uso   "
                    label = status.feature or status.branch or "(detached)"
                    print(f"{mark}  {label}  {status.path}")
                    for blocker in status.blockers:
                        print(f"           · {blocker}")
            return 0
        elif args.command == "retire":
            if not args.feature and not args.path:
                print("ERROR: retire needs a feature or --path", file=sys.stderr)
                return 2
            print(retire(root, args.feature, args.path, args.force))
        elif args.command == "orphans":
            orphans = orphan_bindings(root)
            if args.json:
                print(json.dumps(orphans, indent=2))
            else:
                for orphan in orphans:
                    print(
                        f"{orphan['feature']} — {orphan['reason']} "
                        f"({orphan.get('path', 'no path')})"
                    )
            return 1 if orphans else 0
        else:
            data = read_registry(registry_path(root))
            prune(data)
            for session_id, entry in sorted(data["sessions"].items()):
                print(
                    f"session {session_id} pid {entry.get('pid')} "
                    f"{entry.get('feature') or '-'} {entry.get('worktree')}"
                )
            for feature, binding in sorted(data["worktrees"].items()):
                print(f"bound {feature} → {binding.get('path')}")
    except SessionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
