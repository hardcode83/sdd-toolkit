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
import shutil
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
# The project's teardown command, declared next to the bootstrap it undoes. Same
# three markdown shapes as the policy line, but the value is a whole command, so
# it runs to the end of the line instead of matching a word.
TEARDOWN_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?teardown(?:\*\*)?[ \t]*:[ \t]*`?([^`\n]+?)`?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
TEARDOWN_FILE = POLICY_FILE
# Compose records where a project was started from. Attribution reads THAT label
# instead of deriving the project name from the path: `sdd+seed-data-demo`
# becomes the project `sddseed-data-demo` through a sanitisation that is docker's
# to define, and a wrong guess would either miss the residue or claim another
# worktree's.
COMPOSE_WORKDIR_LABEL = "com.docker.compose.project.working_dir"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
# `worktrees` reports this blocker and `retire` recognises it by its prefix, so
# that the flags which answer it (--teardown, --skip-teardown) can drop exactly
# this one and leave every other blocker standing.
RESIDUE_BLOCKER = "it still owns"
SIZE_UNITS = {
    "B": 1,
    "KB": 10**3,
    "MB": 10**6,
    "GB": 10**9,
    "TB": 10**12,
    "KIB": 2**10,
    "MIB": 2**20,
    "GIB": 2**30,
    "TIB": 2**40,
}
# Environment Claude Code exports into every Bash call. Absent under other
# runners (or a plain shell), which is why every read has a fallback: an
# unidentifiable session must degrade to "no claim", never to a wrong claim.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
PID_ENV = "CLAUDE_PID"
# Where Claude Code records which plugins are installed for which project. A
# worktree that installed one leaves an entry behind pointing at its directory,
# and the file is global to the user, so the residue of one repo accumulates in
# the whole environment. Honours CLAUDE_CONFIG_DIR the same way the CLI does.
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
PLUGIN_REGISTRY = ("plugins", "installed_plugins.json")
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class SessionError(RuntimeError):
    """Actionable session-registry failure."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def jsonable(value: object) -> object:
    """Dataclasses and tuples, as JSON sees them."""
    if hasattr(value, "__dataclass_fields__"):
        return vars(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return str(value)


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


def empty_registry() -> dict:
    return {"schema": SCHEMA, "sessions": {}, "worktrees": {}, "leftovers": []}


def read_registry(path: Path) -> dict:
    if not path.is_file():
        return empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # The registry is a cache of live facts, not a source of truth: a
        # corrupted one is rebuilt rather than turned into a blocking error.
        return empty_registry()
    if not isinstance(data, dict):
        return empty_registry()
    data.setdefault("schema", SCHEMA)
    for key in ("sessions", "worktrees"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    # Leftovers are the one entry that is not a cache: a directory git has already
    # forgotten has no other trace, so it is a list of facts to keep, not to
    # rebuild.
    if not isinstance(data.get("leftovers"), list):
        data["leftovers"] = []
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


def resolve_base_ref(root: Path, base: str, runner: Runner = subprocess.run) -> str:
    """The ref that actually exists for `base`, published one first.

    Prefer the published base, fall back to the local one — same order as
    sdd_lifecycle.resolve_base_ref, because a repo with no remote is a
    legitimate workflow the merge gate already supports.
    """
    return next(
        (
            candidate
            for candidate in (f"origin/{base}", base)
            if candidate
            and try_git(
                ["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
                root,
                runner,
            )
            is not None
        ),
        "",
    )


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
    # Only worth asking docker when the project declared no way to stop a stack:
    # with a `teardown:` there is no blocker to find, and this keeps `worktrees`
    # (which /sdd:doctor and /sdd:status both run) from paying for it every time.
    teardown = read_teardown(root)

    out: list[WorktreeStatus] = []
    for entry in git_worktrees(root, runner):
        path = Path(entry["path"]).resolve()
        is_main = path == main
        feature = feature_of_worktree(entry, bindings)
        archived = archived_feature(root, feature)
        base = base_branch_for(root, feature, runner)
        branch = entry.get("branch", "")
        base_ref = resolve_base_ref(root, base, runner)
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
            if not teardown and path.is_dir():
                # Reported here so `RETIRABLE` keeps meaning "retire will do it":
                # the same condition refuses inside `retire`, and finding out
                # there instead would make this listing a lie.
                residue = residue_of(path, runner)
                if not residue.empty:
                    blockers.append(
                        f"{RESIDUE_BLOCKER} {residue.describe()} and sdd/project.md "
                        "declares no teardown"
                    )

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


def try_docker(
    args: list[str], root: Path | None = None, runner: Runner = subprocess.run
) -> str | None:
    """Ask docker, and treat every failure as "no answer".

    Docker is optional infrastructure: a project without it, a daemon that is not
    running, a CI runner with no socket. None of those is an error here — they
    mean the residue cannot be measured, which is reported as such rather than
    turned into a blocked retirement.
    """
    try:
        result = runner(
            ["docker", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return None if result.returncode else result.stdout.strip()


def parse_docker_size(raw: object) -> int:
    """`935MB` → bytes. Unknown shapes are 0, never a guess."""
    text = str(raw or "").strip().upper().replace(" ", "")
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)([A-Z]*)", text)
    if not match:
        return 0
    unit = SIZE_UNITS.get(match.group(2) or "B")
    return int(float(match.group(1)) * unit) if unit else 0


def human_size(size: int) -> str:
    for unit, factor in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if size >= factor:
            return f"{size / factor:.1f} {unit}"
    return f"{size} B"


@dataclass(frozen=True)
class Residue:
    """What a worktree still owns outside git, attributed by evidence."""

    available: bool
    projects: tuple[str, ...]
    containers: tuple[str, ...]
    running: int
    volumes: tuple[str, ...]
    images: tuple[str, ...]
    size: int

    @property
    def empty(self) -> bool:
        return not (self.projects or self.containers or self.volumes or self.images)

    def describe(self) -> str:
        if not self.available:
            return "docker did not answer (not installed, or the daemon is down)"
        if self.empty:
            return "no container residue attributed to it"
        parts = []
        if self.projects:
            parts.append(f"{len(self.projects)} compose project(s) ({', '.join(self.projects)})")
        if self.containers:
            state = f", {self.running} running" if self.running else ""
            parts.append(f"{len(self.containers)} container(s){state}")
        if self.volumes:
            parts.append(f"{len(self.volumes)} volume(s)")
        if self.images:
            parts.append(f"{len(self.images)} image(s)")
        listed = ", ".join(parts)
        return f"{listed} — {human_size(self.size)}" if self.size else listed


def residue_of(path: Path, runner: Runner = subprocess.run) -> Residue:
    """Every container resource that belongs to one worktree, by evidence.

    Attribution is the whole problem. Compose derives its project name from the
    directory through a sanitisation this must never reimplement — a worktree at
    `.claude/worktrees/sdd+seed-data-demo` becomes the project
    `sddseed-data-demo` — so the link is read from what docker recorded, never
    reconstructed: the `com.docker.compose.project.working_dir` label on the
    containers, and the config-file paths `docker compose ls` reports. Both point
    at an absolute directory, which is exactly the fact we have.

    It matters that this runs BEFORE anything is deleted: a container removed
    without its volumes leaves those volumes with no project label at all, and a
    dangling volume can never be attributed to the worktree that created it
    again. Measured on this machine: 56 dangling volumes, 5.1 GB, unattributable.
    """
    if try_docker(["version", "--format", "{{.Server.Version}}"], None, runner) is None:
        return Residue(False, (), (), 0, (), (), 0)

    target = str(path)
    projects: set[str] = set()
    listing = try_docker(["compose", "ls", "--all", "--format", "json"], None, runner)
    if listing:
        try:
            entries = json.loads(listing)
        except json.JSONDecodeError:
            entries = []
        for entry in entries if isinstance(entries, list) else []:
            configs = str(entry.get("ConfigFiles") or "").split(",")
            if any(is_within(Path(config.strip()), path) for config in configs if config.strip()):
                if entry.get("Name"):
                    projects.add(str(entry["Name"]))

    containers: list[str] = []
    running = 0
    by_workdir = try_docker(
        [
            "ps",
            "--all",
            "--filter",
            f"label={COMPOSE_WORKDIR_LABEL}={target}",
            "--format",
            "{{.Names}}\t{{.State}}\t{{.Label \"" + COMPOSE_PROJECT_LABEL + "\"}}",
        ],
        None,
        runner,
    )
    for line in (by_workdir or "").splitlines():
        fields = line.split("\t")
        if not fields[0]:
            continue
        containers.append(fields[0])
        if len(fields) > 1 and fields[1] == "running":
            running += 1
        if len(fields) > 2 and fields[2]:
            projects.add(fields[2])

    volumes: list[str] = []
    images: list[str] = []
    for project in sorted(projects):
        listed = try_docker(
            [
                "volume",
                "ls",
                "--filter",
                f"label={COMPOSE_PROJECT_LABEL}={project}",
                "--format",
                "{{.Name}}",
            ],
            None,
            runner,
        )
        volumes.extend(name for name in (listed or "").splitlines() if name)
        # Compose names what it builds `<project>-<service>`, and does not label
        # it reliably — so images are matched by that naming and reported, never
        # deleted here. Removing them is the project's declared teardown's call
        # (`--rmi local`), because a tag may be shared with something else.
        built = try_docker(
            ["images", "--format", "{{.Repository}}:{{.Tag}}"], None, runner
        )
        images.extend(
            name
            for name in (built or "").splitlines()
            if name.split(":", 1)[0].startswith(f"{project}-")
        )

    return Residue(
        available=True,
        projects=tuple(sorted(projects)),
        containers=tuple(sorted(containers)),
        running=running,
        volumes=tuple(sorted(set(volumes))),
        images=tuple(sorted(set(images))),
        size=reclaimable_size(set(volumes), set(images), runner),
    )


def reclaimable_size(
    volumes: set[str], images: set[str], runner: Runner = subprocess.run
) -> int:
    """How much disk the named resources hold, or 0 when docker will not say.

    `docker system df -v` is the only place the daemon reports per-volume size;
    when it is unavailable the count is still reported without a size, because a
    missing number must not turn into an invented one.
    """
    if not volumes and not images:
        return 0
    raw = try_docker(["system", "df", "-v", "--format", "json"], None, runner)
    if not raw:
        return 0
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(report, dict):
        return 0
    total = 0
    for entry in report.get("Volumes") or []:
        if isinstance(entry, dict) and entry.get("Name") in volumes:
            total += parse_docker_size(entry.get("Size"))
    for entry in report.get("Images") or []:
        if not isinstance(entry, dict):
            continue
        tag = f"{entry.get('Repository')}:{entry.get('Tag')}"
        if tag in images:
            total += parse_docker_size(entry.get("Size"))
    return total


def is_within(candidate: Path, directory: Path) -> bool:
    try:
        candidate.resolve().relative_to(directory.resolve())
    except (ValueError, OSError):
        return False
    return True


def read_teardown(root: Path) -> str:
    """The project's declared teardown command, or "" if it declares none.

    Symmetrical to the bootstrap it undoes, and project-owned for the same reason
    (shared rule 9): only the project knows whether its stack can be taken down
    with `docker compose down --volumes`, whether that would destroy seed data
    somebody needs, or whether the command is `make clean`. The toolkit owns the
    question.
    """
    document = root / TEARDOWN_FILE
    if not document.is_file():
        return ""
    text = HTML_COMMENT_RE.sub("", document.read_text(encoding="utf-8", errors="replace"))
    match = TEARDOWN_RE.search(text)
    return match.group(1).strip() if match else ""


def run_teardown(command: str, cwd: Path, runner: Runner = subprocess.run) -> tuple[bool, str]:
    """Run the project's teardown inside the worktree it belongs to.

    `cwd` is the point: compose resolves its project name from the working
    directory, so the same command run from the main clone would take down the
    main clone's stack. That is also why this runs before git removes anything —
    once the directory is gone, the command has nowhere to run.
    """
    try:
        result = runner(
            command,
            cwd=cwd,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return False, str(error)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return not result.returncode, output


def remove_directory(path: Path, runner: Runner = subprocess.run) -> tuple[bool, str]:
    """Delete what git left behind, including the ACL that usually blocks it.

    On macOS the leftover is almost always `Permission denied` on directories
    that are EMPTY and owned by you — `node_modules`, `.venv`, `.next`, the
    mountpoints of named volumes. Docker Desktop puts a `deny delete` ACL on them
    when it creates the mountpoint, and it survives the container, the volume and
    the compose project. Neither `chmod -R` nor `sudo` touches it: the fix is to
    strip the ACL (`chmod -R -N`), which is mechanical enough to do rather than
    print. Measured on a real cleanup: three empty directories, 52 KB, that
    refused to go for half an hour.
    """
    if not path.exists():
        return True, ""
    note = ""
    try:
        shutil.rmtree(path)
    except OSError as error:
        note = str(error)
    if not path.exists():
        return True, note
    if sys.platform == "darwin":
        stripped = runner(
            ["chmod", "-R", "-N", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if stripped.returncode == 0:
            try:
                shutil.rmtree(path)
            except OSError as error:
                note = str(error)
            if not path.exists():
                return True, "removed after stripping a deny-delete ACL"
    return False, note


@dataclass(frozen=True)
class SurvivingBranch:
    """A ref that carries the feature's name and outlives its worktree."""

    ref: str
    remote: bool
    contained: bool

    def describe(self) -> str:
        where = "remote" if self.remote else "local"
        return f"{self.ref} ({where}, {'contained' if self.contained else 'NOT contained'})"


def surviving_branches(
    root: Path,
    feature: str,
    branch: str,
    base_ref: str,
    runner: Runner = subprocess.run,
) -> tuple[SurvivingBranch, ...]:
    """Refs named after the feature that retiring does not touch.

    `git branch -d` is local and only knows the worktree's own branch, so two
    kinds of ref outlive a retirement with nothing left to report them: the
    published counterpart (`origin/sdd/<feature>`) and whatever else the change
    created along the way — evidence branches, restore branches, stray fixes.

    Discovery is by name, over refs the repository already has: remote-tracking
    refs answer for the published side without touching the network, so this
    stays as offline and deterministic as every other retirement check. Matching
    on the feature substring is deliberately generous — these are only ever
    listed, never deleted (shared rule 9: whose branch it is, is not the
    toolkit's call), so a false positive costs a line of output and a missed one
    costs a ref nobody ever mentions again.
    """
    if not feature:
        return ()
    listing = try_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"],
        root,
        runner,
    )
    if not listing:
        return ()
    base_names = {base_ref, base_ref.split("/", 1)[-1] if base_ref else ""}
    remotes = try_git(["remote"], root, runner)
    prefixes = tuple(f"{name}/" for name in (remotes or "").splitlines() if name)
    found: list[SurvivingBranch] = []
    for ref in sorted({line.strip() for line in listing.splitlines()}):
        # The worktree's own local branch is deleted by then; its published
        # counterpart is precisely what this exists to surface.
        if not ref or ref.endswith("/HEAD") or ref in base_names or ref == branch:
            continue
        if feature not in ref:
            continue
        contained = bool(base_ref) and (
            try_git(["merge-base", "--is-ancestor", ref, base_ref], root, runner) is not None
        )
        found.append(
            SurvivingBranch(ref=ref, remote=ref.startswith(prefixes), contained=contained)
        )
    return tuple(found)


def plugin_registry_path() -> Path:
    """Claude Code's per-user record of which plugins belong to which project."""
    configured = os.environ.get(CONFIG_DIR_ENV)
    base = Path(configured) if configured else Path.home() / ".claude"
    return base.joinpath(*PLUGIN_REGISTRY)


def prune_plugin_entries(under: Path, registry: Path | None = None) -> int:
    """Drop plugin entries whose projectPath no longer exists, under `under`.

    An entry pointing at a directory that is gone is not recoverable and does
    not mean anything: the project it was scoped to cannot be opened again. So
    unlike a branch, there is no judgement to defer to the user — it is dead
    weight, and it accumulates one entry per plugin per retired worktree.

    Scoped to the repository being retired from rather than the exact worktree.
    The exact worktree would leave every earlier retirement's entries behind
    forever (they are only ever discoverable from the repo that made them), and
    widening it further would have one project silently rewriting another's
    records. Never raises: a malformed or absent registry is Claude Code's file,
    not a reason to fail a retirement that already happened.
    """
    path = registry or plugin_registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        plugins = data["plugins"]
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if not isinstance(plugins, dict):
        return 0
    root = under.resolve()
    removed = 0
    for name in list(plugins):
        entries = plugins[name]
        if not isinstance(entries, list):
            continue
        keep = []
        for entry in entries:
            project = isinstance(entry, dict) and entry.get("projectPath")
            if project and not Path(str(project)).exists():
                candidate = Path(str(project))
                if candidate == root or root in candidate.parents:
                    removed += 1
                    continue
            keep.append(entry)
        if keep:
            plugins[name] = keep
        else:
            del plugins[name]
    if removed:
        try:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return 0
    return removed


@dataclass(frozen=True)
class RetireOutcome:
    """What retiring actually did, per layer. Never a claim about a layer."""

    path: str
    feature: str
    branch: str
    residue_before: Residue
    residue_after: Residue
    teardown: str
    teardown_ok: bool | None
    skipped: bool
    unregistered: bool
    directory_gone: bool
    branch_deleted: bool
    binding_released: bool
    surviving: tuple[SurvivingBranch, ...]
    plugin_entries_pruned: int
    notes: tuple[str, ...]

    def render(self) -> str:
        lines = [f"retire {self.feature or self.branch or self.path}"]
        if self.teardown:
            verdict = "ok" if self.teardown_ok else "FAILED"
            lines.append(f"  runtime: `{self.teardown}` → {verdict}")
            lines.append(f"           before: {self.residue_before.describe()}")
            lines.append(f"           after:  {self.residue_after.describe()}")
        elif self.skipped:
            lines.append(f"  runtime: {self.residue_before.describe()} — KEPT on purpose")
        else:
            lines.append(f"  runtime: {self.residue_before.describe()} (no teardown declared)")
        lines.append(
            "  git:     "
            + ("unregistered" if self.unregistered else "NOT unregistered")
            + (f", branch {self.branch} deleted" if self.branch_deleted else "")
            + (", binding released" if self.binding_released else "")
        )
        if self.plugin_entries_pruned:
            lines.append(
                f"  plugins: {self.plugin_entries_pruned} dead entr"
                f"{'y' if self.plugin_entries_pruned == 1 else 'ies'} dropped from "
                "Claude Code's plugin registry"
            )
        lines.append(
            "  disk:    " + ("clean" if self.directory_gone else f"LEFTOVER at {self.path}")
        )
        if self.directory_gone:
            # The directory had to go, but a shell sitting in it is left with a
            # cwd that no longer resolves, and the getcwd errors that follow name
            # neither the worktree nor the retirement. One line here is cheaper
            # than diagnosing that from scratch.
            lines.append(f"           any shell still inside it must `cd` out: {self.path}")
        if self.surviving:
            lines.append("  branches: retire does not delete these — yours to judge:")
            lines.extend(f"           {found.describe()}" for found in self.surviving)
        lines.extend(f"  ! {note}" for note in self.notes)
        return "\n".join(lines)


def retire(
    root: Path,
    feature: str | None = None,
    path: Path | None = None,
    force: bool = False,
    teardown: str | None = None,
    skip_teardown: bool = False,
    runner: Runner = subprocess.run,
) -> RetireOutcome:
    """Decommission a worktree: its stack, its directory, its branch, its binding.

    The order is the fix. Git used to go first, which is why retirement kept
    failing: the mountpoints of the named volumes the stack still owned were what
    made the directory undeletable, so `git worktree remove` unregistered the
    worktree and then could not delete it — leaving files git no longer tracked,
    a released binding, and therefore nothing that would ever report the leftover
    again. Three changes of that, ~30 GB.

    So: runtime first (the project's declared teardown, run inside the worktree),
    then git, then the directory, and whatever survives is RECORDED rather than
    printed once and forgotten.
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
    worktree = Path(target.path)
    command = "" if skip_teardown else (teardown or read_teardown(root))
    # The residue blocker `worktrees` reports is answered by the flags, so it is
    # dropped here when the caller brought one. Every other blocker stands.
    remaining = [
        blocker
        for blocker in target.blockers
        if not (blocker.startswith(RESIDUE_BLOCKER) and (command or skip_teardown))
    ]
    # A stack nobody declared how to stop is a question for the project, not a
    # guess for the toolkit (shared rule 9). Refusing keeps the residue
    # attributable: after git deletes the directory, the volumes are dangling and
    # no command can tell whose they were.
    if not force:
        stranded = next(
            (b for b in remaining if b.startswith(RESIDUE_BLOCKER)), ""
        )
        if stranded:
            raise SessionError(
                f"Refusing to retire {target.path}: {stranded}, so retiring now "
                "would leave that on disk with no way left to attribute it. "
                "Declare it in the 'Worktree bootstrap' section of "
                "sdd/project.md, e.g.\n"
                "    teardown: docker compose down --volumes --remove-orphans\n"
                "or pass it once with --teardown '<command>'. `--skip-teardown` "
                "keeps the resources deliberately; --force retires anyway."
            )
        if remaining:
            listed = "; ".join(remaining)
            raise SessionError(
                f"Refusing to retire {target.path}: {listed}. Resolve it, or pass "
                "--force if you are certain the work is expendable."
            )

    notes: list[str] = []
    before = residue_of(worktree, runner)
    teardown_ok: bool | None = None
    if command:
        teardown_ok, output = run_teardown(command, worktree, runner)
        if not teardown_ok and not force:
            raise SessionError(
                f"Refusing to retire {target.path}: the declared teardown "
                f"(`{command}`) failed, so nothing was removed and the stack is "
                f"still attributable. Fix it there and re-run.\n{output}".rstrip()
            )
        if not teardown_ok:
            notes.append(f"teardown `{command}` failed and --force continued anyway")

    # Re-inventory only when something was actually run: otherwise the answer is
    # the one already measured, and asking docker twice buys nothing.
    after = residue_of(worktree, runner) if command else before
    if command and teardown_ok and not after.empty:
        notes.append(
            f"the teardown left {after.describe()} — widen it (e.g. add "
            "--volumes / --remove-orphans / --rmi local)"
        )

    removal = ["worktree", "remove"] + (["--force"] if force else []) + [target.path]
    unregistered = try_git(removal, root, runner) is not None
    if not unregistered:
        raise SessionError(
            f"`git worktree remove {target.path}` failed. The teardown above did "
            "run; git changed nothing. Check the path is writable and no process "
            "is inside it."
        )

    gone, note = remove_directory(worktree, runner)
    if note:
        notes.append(note)

    branch_deleted = False
    if target.branch:
        deletion = try_git(["branch", "-d", target.branch], root, runner)
        if deletion is None and force:
            deletion = try_git(["branch", "-D", target.branch], root, runner)
        branch_deleted = deletion is not None
        if not branch_deleted:
            notes.append(
                f"kept branch {target.branch} (git refused; it may hold unmerged work)"
            )

    binding_released = False
    if target.feature:
        release(root, target.feature, runner)
        binding_released = True

    # Asked after the branch deletion above, so what it reports is exactly what
    # survived it. Nothing is excluded by name: a deleted branch is already gone
    # from the ref listing, and one git refused to delete is precisely a survivor.
    survivors = surviving_branches(
        root,
        target.feature,
        "",
        resolve_base_ref(root, base_branch_for(root, target.feature, runner), runner),
        runner,
    )
    pruned = prune_plugin_entries(root)

    # The leak this closes: git no longer knows the path and the binding is gone,
    # so without a record NOTHING would ever mention this directory again.
    if not gone:
        record_leftover(root, worktree, target.feature, after, runner)
        notes.append(
            f"{target.path} survived deletion and is now recorded as a leftover: "
            "`sdd_session.py orphans` and /sdd:doctor will keep reporting it until "
            "it is gone"
        )

    return RetireOutcome(
        path=str(worktree),
        feature=target.feature,
        branch=target.branch,
        residue_before=before,
        residue_after=after,
        teardown=command,
        teardown_ok=teardown_ok,
        skipped=skip_teardown,
        unregistered=unregistered,
        directory_gone=gone,
        branch_deleted=branch_deleted,
        binding_released=binding_released,
        surviving=survivors,
        plugin_entries_pruned=pruned,
        notes=tuple(notes),
    )


def record_leftover(
    root: Path,
    path: Path,
    feature: str,
    residue: Residue,
    runner: Runner = subprocess.run,
) -> None:
    """Remember a directory that refused to go, so it stays reportable."""
    registry = registry_path(root, runner)
    data = read_registry(registry)
    data["leftovers"] = [
        entry
        for entry in data["leftovers"]
        if str(entry.get("path", "")) != str(path)
    ]
    data["leftovers"].append(
        {
            "path": str(path),
            "feature": feature,
            "since": now(),
            "residue": residue.describe(),
        }
    )
    write_registry(registry, data)


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


def stray_directories(root: Path, runner: Runner = subprocess.run) -> list[dict]:
    """Directories under `.claude/worktrees/` that git does not know about.

    Structural, so it needs nothing to have been recorded: a failed retirement
    that never wrote a leftover, a worktree removed with `git worktree remove`
    by hand, a directory from a clone that no longer exists — all of them look
    the same from here, which is a directory git never mentions. This is the
    detector that does not depend on the flow having behaved.
    """
    main = common_dir(root, runner).parent.resolve()
    container = main / ".claude" / "worktrees"
    if not container.is_dir():
        return []
    known = {Path(entry["path"]).resolve() for entry in git_worktrees(root, runner)}
    strays: list[dict] = []
    for candidate in sorted(container.iterdir()):
        if not candidate.is_dir() or candidate.resolve() in known:
            continue
        residue = residue_of(candidate, runner)
        strays.append(
            {
                "path": str(candidate),
                "feature": candidate.name.replace("sdd+", "", 1),
                "reason": "stray",
                "residue": residue.describe() if residue.available else "",
            }
        )
    return strays


def recorded_leftovers(root: Path, runner: Runner = subprocess.run) -> list[dict]:
    """Leftovers a previous retirement recorded, forgetting the ones now gone.

    Self-purging on read: once the user finishes the deletion, the entry
    disappears by itself, so the report never nags about something already fixed
    and nobody has to remember a `forget` command.
    """
    registry = registry_path(root, runner)
    data = read_registry(registry)
    alive = [
        entry
        for entry in data["leftovers"]
        if entry.get("path") and Path(str(entry["path"])).exists()
    ]
    if len(alive) != len(data["leftovers"]):
        data["leftovers"] = alive
        write_registry(registry, data)
    return [{**entry, "reason": "leftover"} for entry in alive]


def all_orphans(root: Path, runner: Runner = subprocess.run) -> list[dict]:
    """Everything machine-local that outlived the work: bindings, dirs, residue.

    One command, because they are one problem seen from three angles — and
    because whichever angle is missing is the one that made ~30 GB invisible.
    Strays are deduplicated against recorded leftovers: a directory can be both.
    """
    leftovers = recorded_leftovers(root, runner)
    recorded = {str(entry.get("path")) for entry in leftovers}
    strays = [
        entry for entry in stray_directories(root, runner) if entry["path"] not in recorded
    ]
    return orphan_bindings(root, runner) + leftovers + strays


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
    subparsers.add_parser(
        "orphans",
        help="stale bindings, leftover directories and container residue nobody owns",
    )
    subparsers.add_parser(
        "worktrees",
        help="every worktree git knows about, with whether it can be retired",
    )
    residue = subparsers.add_parser(
        "residue",
        help="what a worktree still owns outside git (read-only)",
    )
    residue.add_argument("feature", nargs="?", default=None)
    residue.add_argument("--path", type=Path, default=None)
    retirement = subparsers.add_parser(
        "retire",
        help="decommission a worktree: its stack, directory, branch and binding",
    )
    retirement.add_argument("feature", nargs="?", default=None)
    retirement.add_argument("--path", type=Path, default=None)
    retirement.add_argument(
        "--force",
        action="store_true",
        help="override the blockers — discards whatever the worktree still holds",
    )
    retirement.add_argument(
        "--teardown",
        default=None,
        help="teardown command for this run, when sdd/project.md declares none",
    )
    retirement.add_argument(
        "--skip-teardown",
        action="store_true",
        help="keep the containers, volumes and images on purpose",
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
        elif args.command == "residue":
            if not args.feature and not args.path:
                print("ERROR: residue needs a feature or --path", file=sys.stderr)
                return 2
            where = args.path.resolve() if args.path else Path(resolve(root, args.feature) or "")
            if not str(where):
                print(
                    f"ERROR: no worktree is bound to '{args.feature}'; pass --path",
                    file=sys.stderr,
                )
                return 2
            found = residue_of(where)
            if args.json:
                print(json.dumps(vars(found) | {"path": str(where)}, indent=2, default=list))
            else:
                print(f"{where}: {found.describe()}")
            return 0
        elif args.command == "retire":
            if not args.feature and not args.path:
                print("ERROR: retire needs a feature or --path", file=sys.stderr)
                return 2
            outcome = retire(
                root,
                args.feature,
                args.path,
                args.force,
                args.teardown,
                args.skip_teardown,
            )
            if args.json:
                print(json.dumps(vars(outcome), indent=2, default=jsonable))
            else:
                print(outcome.render())
            # A leftover is not a success: the caller must be able to notice.
            return 0 if outcome.directory_gone else 1
        elif args.command == "orphans":
            orphans = all_orphans(root)
            if args.json:
                print(json.dumps(orphans, indent=2))
            else:
                for orphan in orphans:
                    detail = f" — {orphan['residue']}" if orphan.get("residue") else ""
                    print(
                        f"{orphan.get('feature') or '(unknown)'} — {orphan['reason']} "
                        f"({orphan.get('path', 'no path')}){detail}"
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
