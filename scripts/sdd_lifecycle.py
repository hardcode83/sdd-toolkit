#!/usr/bin/env python3
"""Minimal lifecycle state and merge gate for SDD changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable


STATES = {
    "ACTIVE",
    "LOCAL_VERIFIED",
    "READY_FOR_PR",
    "PR_OPEN",
    "MERGED",
    "ARCHIVED",
    "CANCELLED",
}
STATE_FIELDS = (
    "schema",
    "state",
    "local_review",
    "repository",
    "base_branch",
    "head_branch",
    "implementation_sha",
    "pr_number",
    "pr_url",
    "pr_state",
    "merge_evidence",
    "merge_sha",
)
# How a merge was proven. All three are objective facts, never agent narrative:
#   pr         — GitHub reports the associated Pull Request as MERGED.
#   ancestor   — git proves the reviewed implementation SHA is contained in the
#                base branch (trunk-based, local merges, non-GitHub remotes).
#   equivalent — the base carries the same change under a different SHA, because
#                it was squashed or rebased in. `merge_sha` is the base commit
#                that matched; for the other kinds it is the merge commit /
#                base tip.
MERGE_EVIDENCE_KINDS = {"pr", "ancestor", "equivalent"}
PR_FIELDS = (
    "repository",
    "base_branch",
    "head_branch",
    "implementation_sha",
    "pr_number",
    "pr_url",
)
TASK_RE = re.compile(r"^\s*-\s+\[([ xX])\]")
ROADMAP_ENTRY_RE = re.compile(r"^(?P<prefix>\s*-\s+)\[(?P<checked>[ xX])\](?P<body>.*)$")
CHANGE_POINTER_RE = re.compile(
    r"(?P<path>(?:sdd/)?changes/(?:archive/)?[A-Za-z0-9._-]+/?)"
)
PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<repository>[^/]+/[^/]+)/pull/(?P<number>\d+)/?$"
)
# Fixed diff rendering so the same change fingerprints identically wherever it
# landed: no color/external drivers, no rename detection, and zero context so
# unrelated edits near the change cannot alter the result.
DIFF_OPTIONS = ("--no-color", "--no-ext-diff", "--no-renames", "--unified=0")
# A squash or rebase lands among the commits that reached the base after the
# branch point. Scanning all of history would be unbounded; this cap keeps the
# check cheap, and a miss says explicitly how far back it looked.
EQUIVALENCE_SCAN_LIMIT = 200
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
FEATURE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LIFECYCLE_SUBJECT_RE = re.compile(
    r"^chore\(sdd\): lifecycle (?P<feature>[^ ]+) (?P<transition>[^ ]+)$"
)
# The one commit on a feature branch that is neither implementation nor a
# lifecycle transition: the base branch merged in, so an open PR stays mergeable
# while other features land. Merge and never rebase — `implementation_sha` is the
# reviewed anchor every later gate reads, and a rebase would rewrite it out of
# existence.
SYNC_SUBJECT_RE = re.compile(
    r"^chore\(sdd\): sync (?P<feature>[^ ]+) (?P<base>[^ @]+)@(?P<sha>[0-9a-f]{7,40})$"
)
# Files whose merge is decidable without judgement: append-only bookkeeping where
# each side only ever adds its own line, which is exactly what ADR 0001 shaped
# the roadmap for. Everything else — code, specs, docs — is resolved by whoever
# ran the command, never here.
UNION_MERGE_PATHS = ("sdd/roadmap.md", "sdd/metrics.md")
# A rebase resolves one commit at a time, so the loop is bounded by commits, not
# by attempts. The cap is a runaway backstop, never a real limit.
MAX_INTEGRATION_ROUNDS = 50
LIFECYCLE_TRANSITIONS = {
    ("ACTIVE", "LOCAL_VERIFIED"),
    ("LOCAL_VERIFIED", "READY_FOR_PR"),
    ("READY_FOR_PR", "PR_OPEN"),
    # A PR that was already merged can be recorded before the local state has
    # observed it as OPEN. It is still a lifecycle-only transition.
    ("READY_FOR_PR", "MERGED"),
    # Recertification: re-anchor the reviewed `implementation_sha` on the same
    # open PR after a functional fix. The canonical state stays PR_OPEN; the
    # transition is a self-loop authorized only by the dedicated branch in
    # `classify_lifecycle_commit` (D5 of post-pr-recertification).
    ("PR_OPEN", "PR_OPEN"),
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


class LifecycleError(RuntimeError):
    """Actionable lifecycle failure."""


def state_path(change: Path) -> Path:
    return change / "STATE.md"


def validate_feature_slug(feature: str) -> str:
    """Return a safe single-directory feature identifier."""
    if (
        not feature
        or feature in {".", ".."}
        or ".." in feature
        or "/" in feature
        or "\\" in feature
        or not FEATURE_RE.fullmatch(feature)
    ):
        raise LifecycleError(
            "Feature must be one safe directory name without traversal or aliases."
        )
    return feature


def repo_root(root: Path, runner: Runner = subprocess.run) -> Path:
    return Path(
        run_command(["git", "rev-parse", "--show-toplevel"], root, runner)
        .stdout.strip()
    )


def lifecycle_path(root: Path, feature: str, runner: Runner = subprocess.run) -> str:
    validate_feature_slug(feature)
    repository = repo_root(root, runner)
    expected = (repository / "sdd" / "changes" / feature / "STATE.md").resolve()
    return expected.relative_to(repository.resolve()).as_posix()


def status_paths(root: Path, runner: Runner = subprocess.run) -> list[tuple[str, str]]:
    result = run_command(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], root, runner
    )
    paths: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append((code, path))
    return paths


def ensure_clean_or_only_expected_state(
    root: Path, expected_path: str, runner: Runner = subprocess.run
) -> None:
    """Reject user changes before the helper takes ownership of STATE.md."""
    for code, path in status_paths(root, runner):
        if path != expected_path:
            raise LifecycleError(
                "Worktree or index contains changes outside the lifecycle STATE.md "
                f"allowlist: {path}."
            )
        # A staged STATE change belongs to the user (or an earlier operation),
        # so never silently replace it. The helper may consume only its own
        # canonical, unstaged state written by the preceding lifecycle command.
        if code[0] != " " and code[0] != "?":
            raise LifecycleError(
                "STATE.md already has staged changes; refusing to overwrite them."
            )


def state_from_text(text: str, label: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise LifecycleError(f"{label} must start with YAML-style frontmatter.")
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise LifecycleError(f"Invalid lifecycle metadata line in {label}: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if key in data:
            raise LifecycleError(f"Duplicate lifecycle key '{key}' in {label}.")
        data[key] = value.strip()
    raise LifecycleError(f"{label} has no closing frontmatter delimiter.")


def commit_state_text(
    root: Path, commit: str, path: str, runner: Runner = subprocess.run
) -> str:
    return run_command(["git", "show", f"{commit}:{path}"], root, runner).stdout


def lifecycle_commit(
    root: Path,
    feature: str,
    transition: str,
    data: dict[str, str],
    runner: Runner = subprocess.run,
    body_lines: list[str] | None = None,
) -> str:
    """Persist one lifecycle transition as one STATE-only commit.

    The helper owns only the canonical STATE bytes it is asked to write. It
    refuses unrelated dirty/staged paths, never rewrites history, and restores
    its temporary staging/bytes if the commit command fails.

    Optional `body_lines` are appended as additional `-m` paragraphs (e.g.
    `SDD-Prior-Implementation-SHA: <old>` for traceability); they are not
    classified by the lifecycle commit classifier — only the subject and the
    canonical `SDD-Lifecycle-Feature` trailer are.
    """
    expected_path = lifecycle_path(root, feature, runner)
    ensure_clean_or_only_expected_state(root, expected_path, runner)
    path = repo_root(root, runner) / expected_path
    original_exists = path.exists()
    original_bytes = path.read_bytes() if original_exists else b""
    parent = run_command(["git", "rev-parse", "HEAD"], root, runner).stdout.strip()
    write_state(path.parent, data)
    try:
        run_command(["git", "add", "--", expected_path], root, runner)
        subject = f"chore(sdd): lifecycle {feature} {transition}"
        commit_args: list[str] = [
            "git",
            "commit",
            "--only",
            "-m",
            subject,
            "-m",
            f"SDD-Lifecycle-Feature: {feature}",
        ]
        for line in body_lines or []:
            commit_args.extend(["-m", line])
        commit_args.append("--")
        commit_args.append(expected_path)
        result = runner(
            commit_args,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise LifecycleError(
                f"git commit failed: {detail or 'unknown error'}"
            )
    except Exception:
        run_command(["git", "restore", "--staged", "--", expected_path], root, runner)
        if original_exists:
            path.write_bytes(original_bytes)
        elif path.exists():
            path.unlink()
        raise
    child = run_command(["git", "rev-parse", "HEAD"], root, runner).stdout.strip()
    if child == parent:
        raise LifecycleError("Lifecycle commit did not advance HEAD.")
    return child


def read_state(change: Path) -> dict[str, str] | None:
    path = state_path(change)
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        raise LifecycleError(f"{path} must start with YAML-style frontmatter.")
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise LifecycleError(f"Invalid lifecycle metadata line in {path}: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if key in data:
            raise LifecycleError(f"Duplicate lifecycle key '{key}' in {path}.")
        data[key] = value.strip()
    else:
        raise LifecycleError(f"{path} has no closing frontmatter delimiter.")
    return data


def render_state(data: dict[str, str]) -> str:
    normalized = {field: data.get(field, "") for field in STATE_FIELDS}
    normalized["schema"] = normalized["schema"] or "1"
    lines = ["---"]
    lines.extend(f"{field}: {normalized[field]}" for field in STATE_FIELDS)
    lines.extend(
        [
            "---",
            "",
            "# Change lifecycle",
            "",
            "Managed by the SDD lifecycle commands. Do not infer remote state without",
            "checking the associated Pull Request.",
            "",
        ]
    )
    return "\n".join(lines)


def write_state(change: Path, data: dict[str, str]) -> bool:
    path = state_path(change)
    content = render_state(data)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def active_change(root: Path, feature: str) -> Path:
    validate_feature_slug(feature)
    change = root / "sdd" / "changes" / feature
    if not change.is_dir():
        raise LifecycleError(
            f"Active change '{feature}' was not found at sdd/changes/{feature}/."
        )
    return change


def archived_change(root: Path, feature: str) -> Path | None:
    archive = root / "sdd" / "changes" / "archive"
    matches = sorted(archive.glob(f"????-??-??-{feature}")) if archive.is_dir() else []
    if len(matches) > 1:
        raise LifecycleError(f"Multiple archives found for change '{feature}'.")
    return matches[0] if matches else None


def incomplete_tasks(change: Path) -> list[tuple[int, str]]:
    tasks = change / "tasks.md"
    if not tasks.is_file():
        raise LifecycleError(f"{tasks} is required before lifecycle verification.")
    pending: list[tuple[int, str]] = []
    for line_number, line in enumerate(
        tasks.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        match = TASK_RE.match(line)
        if match and match.group(1) == " ":
            pending.append((line_number, line.strip()))
    return pending


def ensure_local_gates(change: Path) -> None:
    pending = incomplete_tasks(change)
    if pending:
        lines = ", ".join(str(line) for line, _ in pending)
        raise LifecycleError(
            f"Change has {len(pending)} incomplete task(s) at tasks.md line(s) "
            f"{lines}. Complete and verify them before continuing."
        )
    blocked = change / "BLOCKED.md"
    if blocked.is_file() and blocked.read_text(
        encoding="utf-8", errors="replace"
    ).strip():
        raise LifecycleError(
            "BLOCKED.md contains unresolved work. Resolve it before continuing."
        )


def run_command(
    args: list[str], root: Path, runner: Runner = subprocess.run
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            args,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise LifecycleError(f"Could not execute '{args[0]}': {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise LifecycleError(f"{' '.join(args)} failed: {detail or 'unknown error'}")
    return result


def try_command(
    args: list[str], root: Path, runner: Runner = subprocess.run
) -> subprocess.CompletedProcess[str] | None:
    """Run a command, returning None instead of raising when it fails."""
    try:
        result = runner(args, cwd=root, check=False, capture_output=True, text=True)
    except OSError:
        return None
    return None if result.returncode else result


def resolve_base_ref(root: Path, base_branch: str, runner: Runner) -> str:
    """Prefer the published base branch: shared history is the real evidence."""
    for candidate in (f"origin/{base_branch}", base_branch):
        if try_command(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            root,
            runner,
        ):
            return candidate
    raise LifecycleError(
        f"Base branch '{base_branch}' does not exist locally or on origin. "
        "Fetch it or record the correct base with /sdd:review."
    )


def patch_fingerprint(diff: str) -> str:
    """Content identity of a diff, independent of where it landed.

    Mirrors what `git patch-id` does — drop blob hashes and hunk line numbers —
    so a squashed or rebased copy of the same change fingerprints identically.
    Done here instead of shelling out because `git patch-id` only reads stdin.
    """
    kept: list[str] = []
    for line in diff.splitlines():
        if line.startswith("index ") or line.startswith("similarity index "):
            continue
        kept.append("@@" if line.startswith("@@") else line)
    body = "\n".join(kept).strip()
    if not body:
        return ""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def range_fingerprint(root: Path, first: str, second: str, runner: Runner) -> str:
    diff = run_command(
        ["git", "diff", *DIFF_OPTIONS, first, second], root, runner
    ).stdout
    return patch_fingerprint(diff)


def commit_fingerprint(root: Path, commit: str, runner: Runner) -> str:
    """Fingerprint of what a single commit introduced; empty for root commits."""
    if not try_command(["git", "rev-parse", "--verify", "--quiet", f"{commit}^"], root, runner):
        return ""
    return range_fingerprint(root, f"{commit}^", commit, runner)


def base_fingerprints(
    root: Path, merge_base: str, base_ref: str, runner: Runner
) -> tuple[dict[str, str], bool]:
    """Map fingerprint → base commit for the commits base gained since branching.

    Returns the map and whether the scan hit `EQUIVALENCE_SCAN_LIMIT` (newest
    first), so a failure can state how far back it actually looked.
    """
    listed = run_command(
        [
            "git",
            "rev-list",
            "--no-merges",
            f"--max-count={EQUIVALENCE_SCAN_LIMIT}",
            f"{merge_base}..{base_ref}",
        ],
        root,
        runner,
    ).stdout.split()
    fingerprints: dict[str, str] = {}
    for commit in listed:
        fingerprint = commit_fingerprint(root, commit, runner)
        # First writer wins: with duplicates, the oldest landing is the merge.
        if fingerprint and fingerprint not in fingerprints:
            fingerprints[fingerprint] = commit
    return fingerprints, len(listed) == EQUIVALENCE_SCAN_LIMIT


def verify_equivalent_merge(
    root: Path,
    state: dict[str, str],
    base_ref: str,
    runner: Runner = subprocess.run,
) -> str:
    """Find the base commit carrying the reviewed change under a different SHA.

    Squash and rebase merges rewrite history, so the reviewed commit is never an
    ancestor of the base even though its content is fully merged. Returns the
    matching base commit SHA, or "" when the base carries no such change.
    """
    implementation_sha = state["implementation_sha"]
    branch_tip = implementation_sha
    if try_command(
        ["git", "rev-parse", "--verify", f"{state['head_branch']}^{{commit}}"],
        root,
        runner,
    ):
        branch_tip = run_command(
            ["git", "rev-parse", f"{state['head_branch']}^{{commit}}"], root, runner
        ).stdout.strip()
    # Two possible boundaries for "what this branch introduces", and which one
    # holds depends on how the branch met the base:
    #   * against the branch TIP — correct once the base was merged INTO the
    #     branch (sync-base), where the old branch point would carry every base
    #     commit the sync brought in and match no squash of this change;
    #   * against the reviewed COMMIT — correct when the branch was rebased and
    #     the base fast-forwarded onto it, where the tip is already contained in
    #     the base and the diff from there is empty.
    # With neither, they are the same commit. Take the first that describes
    # anything; only if both are empty does the branch really introduce nothing.
    merge_base = ""
    branch_total = ""
    for candidate in dict.fromkeys(
        (
            run_command(
                ["git", "merge-base", base_ref, branch_tip], root, runner
            ).stdout.strip(),
            run_command(
                ["git", "merge-base", base_ref, implementation_sha], root, runner
            ).stdout.strip(),
        )
    ):
        if not candidate:
            continue
        fingerprint = range_fingerprint(root, candidate, branch_tip, runner)
        if fingerprint:
            merge_base, branch_total = candidate, fingerprint
            break
    if not branch_total:
        raise LifecycleError(
            f"Reviewed commit {implementation_sha[:12]} changes nothing relative to "
            f"'{base_ref}', so nothing can be proven merged. Record the correct "
            "implementation SHA with /sdd:review."
        )
    candidates, truncated = base_fingerprints(root, merge_base, base_ref, runner)
    # A squash collapses the branch into one commit: its diff is the whole branch.
    if branch_total in candidates:
        return candidates[branch_total]
    # A rebase copies each commit: every one of them must be present in the base.
    branch_commits = run_command(
        ["git", "rev-list", "--no-merges", f"{merge_base}..{branch_tip}"],
        root,
        runner,
    ).stdout.split()
    matches = [
        candidates.get(commit_fingerprint(root, commit, runner), "")
        for commit in branch_commits
    ]
    if branch_commits and all(matches):
        return matches[0]
    if truncated:
        raise LifecycleError(
            f"Reviewed commit {implementation_sha[:12]} is not in '{base_ref}', and "
            f"the newest {EQUIVALENCE_SCAN_LIMIT} commits there carry no equivalent "
            "change. If it was merged further back, archive it through its PR "
            "(/sdd:review to record one) rather than local evidence."
        )
    return ""


def verify_local_merge(
    root: Path, state: dict[str, str], runner: Runner = subprocess.run
) -> tuple[str, str, str]:
    """Prove the reviewed implementation reached the base branch, without a PR.

    Returns (evidence_kind, base_ref, merge_sha): `ancestor` when the reviewed
    commit itself is contained in the base, `equivalent` when the base carries
    the same change squashed or rebased under another SHA. Raises when neither
    holds — that means the work is not merged, whatever anyone claims.
    """
    for field in ("base_branch", "head_branch", "implementation_sha"):
        if not state.get(field):
            raise LifecycleError(
                f"Incomplete local evidence in STATE.md: missing {field}. "
                "Run /sdd:review to record it."
            )
    implementation_sha = state["implementation_sha"]
    if not SHA_RE.match(implementation_sha):
        raise LifecycleError("Recorded implementation_sha is not a valid Git SHA.")
    if not try_command(
        ["git", "cat-file", "-e", f"{implementation_sha}^{{commit}}"], root, runner
    ):
        raise LifecycleError(
            f"Reviewed commit {implementation_sha[:12]} is unknown to this repository. "
            "Fetch the branch that contains it and retry."
        )
    base_ref = resolve_base_ref(root, state["base_branch"], runner)
    if try_command(
        ["git", "merge-base", "--is-ancestor", implementation_sha, base_ref],
        root,
        runner,
    ):
        base_sha = run_command(
            ["git", "rev-parse", f"{base_ref}^{{commit}}"], root, runner
        ).stdout.strip()
        return "ancestor", base_ref, base_sha
    equivalent_sha = verify_equivalent_merge(root, state, base_ref, runner)
    if equivalent_sha:
        return "equivalent", base_ref, equivalent_sha
    raise LifecycleError(
        f"Reviewed commit {implementation_sha[:12]} is not contained in "
        f"'{base_ref}', and no commit there carries the same change (squash or "
        "rebase). Merge the change into its base branch (or open and record a "
        "PR), then rerun /sdd:archive."
    )


def normalize_repository(remote: str) -> str:
    value = remote.strip().removesuffix(".git").rstrip("/")
    if value.startswith("git@github.com:"):
        return value.split(":", 1)[1]
    marker = "github.com/"
    if marker in value:
        return value.split(marker, 1)[1]
    raise LifecycleError(
        "origin must be a GitHub repository to use the merge-gated PR workflow."
    )


def git_context(root: Path, base_branch: str, runner: Runner = subprocess.run) -> dict[str, str]:
    head_branch = run_command(
        ["git", "branch", "--show-current"], root, runner
    ).stdout.strip()
    if not head_branch:
        raise LifecycleError("Cannot mark READY_FOR_PR from a detached HEAD.")
    implementation_sha = run_command(
        ["git", "rev-parse", "HEAD"], root, runner
    ).stdout.strip()
    # A GitHub remote is what makes PR evidence possible, but its absence is a
    # legitimate workflow (no remote, trunk-based, GitLab...), not an error:
    # those changes prove their merge through git ancestry instead.
    remote = try_command(["git", "remote", "get-url", "origin"], root, runner)
    try:
        repository = normalize_repository(remote.stdout) if remote else ""
    except LifecycleError:
        repository = ""
    if not base_branch.strip():
        raise LifecycleError("The target base branch must be explicit.")
    return {
        "repository": repository,
        "base_branch": base_branch.strip(),
        "head_branch": head_branch,
        "implementation_sha": implementation_sha,
    }


def classify_lifecycle_commit(
    root: Path,
    commit: str,
    feature: str,
    runner: Runner = subprocess.run,
) -> tuple[str, str]:
    """Validate one post-anchor commit and return (feature, transition)."""
    expected_path = lifecycle_path(root, feature, runner)
    parents = run_command(
        ["git", "show", "-s", "--format=%P", commit], root, runner
    ).stdout.split()
    if len(parents) != 1:
        raise LifecycleError(f"Commit {commit[:12]} is not a single-parent lifecycle commit.")
    parent = parents[0]
    subject = run_command(
        ["git", "show", "-s", "--format=%s", commit], root, runner
    ).stdout.strip()
    match = LIFECYCLE_SUBJECT_RE.fullmatch(subject)
    if not match:
        raise LifecycleError(f"Commit {commit[:12]} has an unauthorized lifecycle subject.")
    commit_feature = validate_feature_slug(match.group("feature"))
    if commit_feature != feature:
        raise LifecycleError(
            f"Commit {commit[:12]} targets lifecycle feature '{commit_feature}', "
            f"not '{feature}'."
        )
    transition = match.group("transition")
    try:
        before, after = transition.split("->", 1)
    except ValueError as error:
        raise LifecycleError(f"Commit {commit[:12]} has an invalid lifecycle transition.") from error
    if (before, after) not in LIFECYCLE_TRANSITIONS:
        raise LifecycleError(f"Commit {commit[:12]} has an invalid lifecycle transition.")
    body = run_command(["git", "show", "-s", "--format=%B", commit], root, runner).stdout
    trailer = f"SDD-Lifecycle-Feature: {feature}"
    if sum(line.strip() == trailer for line in body.splitlines()) != 1:
        raise LifecycleError(f"Commit {commit[:12]} is missing its exact lifecycle trailer.")
    paths = run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        root,
        runner,
    ).stdout.splitlines()
    if paths != [expected_path]:
        raise LifecycleError(
            f"Commit {commit[:12]} modifies paths outside the lifecycle allowlist: "
            f"{', '.join(paths) or '(none)'}."
        )
    parent_has_state = try_command(
        ["git", "cat-file", "-e", f"{parent}:{expected_path}"], root, runner
    )
    if not parent_has_state:
        raise LifecycleError(
            f"Commit {commit[:12]} has no valid parent STATE.md at {expected_path}."
        )
    parent_text = commit_state_text(root, parent, expected_path, runner)
    child_text = commit_state_text(root, commit, expected_path, runner)
    parent_state = state_from_text(parent_text, f"{parent}:{expected_path}")
    child_state = state_from_text(child_text, f"{commit}:{expected_path}")
    if commit in child_text:
        raise LifecycleError(f"Commit {commit[:12]} self-references its own SHA in STATE.md.")
    if (
        parent_state.get("state") != before
        or child_state.get("state") != after
    ):
        raise LifecycleError(
            f"Commit {commit[:12]} does not encode {before} -> {after} in STATE.md."
        )
    if after == "READY_FOR_PR":
        if child_state.get("implementation_sha") != parent_state.get("implementation_sha"):
            raise LifecycleError(
                "READY_FOR_PR lifecycle commit must preserve the stable implementation_sha anchor."
            )
    elif after == "LOCAL_VERIFIED":
        if child_state.get("implementation_sha") != parent:
            raise LifecycleError(
                "LOCAL_VERIFIED lifecycle commit must preserve its implementation parent."
            )
    elif before == "PR_OPEN" and after == "PR_OPEN":
        # Recertification: child.implementation_sha must equal the parent SHA
        # (the new reviewed HEAD, never the recertify commit's own SHA — see
        # the `commit in child_text` guard above), and the parent's recorded
        # anchor must differ (a real re-anchor happened).
        if child_state.get("implementation_sha") != parent:
            raise LifecycleError(
                "Recertification must record the reviewed HEAD (the parent of "
                "the recertify commit) as the new implementation_sha anchor."
            )
        if parent_state.get("implementation_sha") == parent:
            raise LifecycleError(
                "Recertification requires a new implementation_sha anchor; the "
                "parent STATE.md already points at the reviewed HEAD."
            )
    elif child_state.get("implementation_sha") != parent_state.get("implementation_sha"):
        raise LifecycleError("Lifecycle commit changed the stable implementation_sha anchor.")
    return commit_feature, transition


def validate_ship_suffix(
    root: Path,
    feature: str,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Validate every commit after implementation_sha before ship pushes.

    The lifecycle allowlist is exactly ``sdd/changes/<feature>/STATE.md``;
    generic observability such as ``sdd/metrics.md`` is deliberately excluded.

    Two shapes are authorized, and nothing else: a STATE-only lifecycle commit,
    and the base-sync merge `sync-base` records. The walk follows `--first-parent`
    for exactly that reason — a sync merge brings the base's whole history onto
    the branch, and validating those commits as if the flow had made them would
    fail every one of them.
    """
    change = active_change(root, feature)
    data = read_state(change)
    if not data or not data.get("implementation_sha"):
        raise LifecycleError("STATE.md has no implementation_sha anchor.")
    implementation_sha = data["implementation_sha"]
    if not SHA_RE.fullmatch(implementation_sha):
        raise LifecycleError("Recorded implementation_sha is not a valid Git SHA.")
    if not try_command(
        ["git", "cat-file", "-e", f"{implementation_sha}^{{commit}}"], root, runner
    ):
        raise LifecycleError("Recorded implementation_sha is unknown to this repository.")
    head = run_command(["git", "rev-parse", "HEAD"], root, runner).stdout.strip()
    if not try_command(
        ["git", "merge-base", "--is-ancestor", implementation_sha, head], root, runner
    ):
        raise LifecycleError("implementation_sha must be an ancestor of HEAD before ship.")
    if status_paths(root, runner):
        raise LifecycleError("Worktree must be clean before ship.")
    commits = run_command(
        ["git", "rev-list", "--reverse", "--first-parent", f"{implementation_sha}..{head}"],
        root,
        runner,
    ).stdout.split()
    for commit in commits:
        parents = run_command(
            ["git", "show", "-s", "--format=%P", commit], root, runner
        ).stdout.split()
        if len(parents) == 2:
            validate_sync_commit(root, commit, feature, data.get("base_branch", ""), runner)
        else:
            classify_lifecycle_commit(root, commit, feature, runner)
    return commits


def unmerged_paths(root: Path, runner: Runner = subprocess.run) -> list[str]:
    """The paths git itself reports as unresolved — the only authority on that."""
    return sorted(
        {
            line.strip()
            for line in run_command(
                ["git", "diff", "--name-only", "--diff-filter=U"], root, runner
            ).stdout.splitlines()
            if line.strip()
        }
    )


def merge_in_progress(root: Path, runner: Runner = subprocess.run) -> bool:
    return (
        try_command(
            ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"], root, runner
        )
        is not None
    )


def leftover_conflict_markers(
    root: Path, runner: Runner = subprocess.run
) -> list[str]:
    """Staged paths that still carry conflict markers.

    `git diff --cached --check` is git's own detector, which is the point: a
    resolution is not judged by whether it looks tidy, and "I resolved it" is a
    claim until git stops finding markers in it.
    """
    try:
        result = runner(
            ["git", "diff", "--cached", "--check"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:  # pragma: no cover - git is present everywhere here
        raise LifecycleError(f"Could not execute 'git': {error}") from error
    if not result.returncode:
        return []
    found = {
        line.split(":", 1)[0].strip()
        for line in (result.stdout or "").splitlines()
        if "conflict marker" in line and ":" in line
    }
    return sorted(found)


def recorded_conflicts(root: Path, runner: Runner = subprocess.run) -> list[str]:
    """The files git listed as conflicted in MERGE_MSG.

    Read from git's own message instead of remembered by the caller: the
    resolution spans two commands — one starts the merge, another records it —
    and what the caller remembers in between is not evidence.
    """
    located = try_command(["git", "rev-parse", "--git-path", "MERGE_MSG"], root, runner)
    if located is None:
        return []
    path = Path(located.stdout.strip())
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return []
    listed: list[str] = []
    collecting = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.lstrip("#").strip()
        if stripped.lower().startswith("conflicts:"):
            collecting = True
            continue
        if collecting and stripped:
            listed.append(stripped)
        elif collecting:
            break
    return listed


def duplicate_bookkeeping_keys(path: str, text: str) -> list[str]:
    """Keys a union merge duplicated, which is where a union stops being safe.

    Union keeps both sides' lines, and that is exactly right while each side only
    adds its own. If both sides touched the SAME entry — a roadmap tick against
    an edit of the same line, two rows for one feature in the metrics table — the
    result holds two copies of it, and two copies is not a resolution. Detecting
    it is what keeps the automatic path honest rather than merely quiet.
    """
    seen: dict[str, int] = {}
    name = path.rsplit("/", 1)[-1]
    for line in text.splitlines():
        key = ""
        if name == "roadmap.md":
            entry = ROADMAP_ENTRY_RE.match(line)
            if entry:
                body = entry.group("body")
                key = roadmap_feature(body) or body.strip()
        elif name == "metrics.md" and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            candidate = cells[0] if cells else ""
            # A table separator (|---|---|) is not a row.
            if candidate and set(candidate) - set("-: "):
                key = candidate
        if key:
            seen[key] = seen.get(key, 0) + 1
    return sorted(key for key, count in seen.items() if count > 1)


def union_resolve(
    root: Path, path: str, runner: Runner = subprocess.run
) -> tuple[bool, str]:
    """Resolve one append-only bookkeeping file by keeping both sides' lines.

    `git merge-file --union` is the same union git applies to a `merge=union`
    attribute, so this adds no merge semantics of its own. What it adds is the
    check afterwards, and the refusal to touch anything else: returns
    ``(False, why)`` without staging anything, so the caller reports the file
    instead of pretending it was handled.
    """
    if path not in UNION_MERGE_PATHS:
        return False, "not an append-only bookkeeping file"
    ours = try_command(["git", "show", f":2:{path}"], root, runner)
    theirs = try_command(["git", "show", f":3:{path}"], root, runner)
    if ours is None or theirs is None:
        # One side deleted it. Which side wins is a decision, not a union.
        return False, "one side deleted it"
    ancestor = try_command(["git", "show", f":1:{path}"], root, runner)
    with tempfile.TemporaryDirectory() as scratch:
        stages: dict[int, str] = {}
        for stage, blob in ((1, ancestor), (2, ours), (3, theirs)):
            handle = Path(scratch) / f"stage{stage}"
            handle.write_text(blob.stdout if blob else "", encoding="utf-8")
            stages[stage] = str(handle)
        merged = try_command(
            ["git", "merge-file", "--union", "-p", stages[2], stages[1], stages[3]],
            root,
            runner,
        )
        content = merged.stdout if merged else ""
    if merged is None:
        return False, "git merge-file could not union it"
    duplicates = duplicate_bookkeeping_keys(path, content)
    if duplicates:
        return False, f"a union would duplicate {', '.join(duplicates)}"
    (repo_root(root, runner) / path).write_text(content, encoding="utf-8")
    run_command(["git", "add", "--", path], root, runner)
    return True, ""


def resolve_bookkeeping(
    root: Path, runner: Runner = subprocess.run
) -> tuple[list[str], list[str]]:
    """Union-resolve every conflicted bookkeeping file. Returns (resolved, why).

    Everything it cannot decide is left conflicted on purpose: an unresolved path
    is visible to git, to the caller and to the next command, while a guessed one
    is visible to nobody.
    """
    resolved: list[str] = []
    notes: list[str] = []
    for path in unmerged_paths(root, runner):
        if path not in UNION_MERGE_PATHS:
            continue
        ok, why = union_resolve(root, path, runner)
        if ok:
            resolved.append(path)
        else:
            notes.append(f"{path}: {why}")
    return resolved, notes


def validate_sync_commit(
    root: Path,
    commit: str,
    feature: str,
    base_branch: str,
    runner: Runner = subprocess.run,
) -> str:
    """Authorize one base-sync merge on the feature branch.

    A merge commit is the one two-parent commit the flow makes, and it is
    authorized by facts rather than by its message alone: its second parent must
    be contained in the base branch (so what came in is the base and nothing
    else), and it must not touch STATE.md — a sync integrates code, it never
    rewrites the lifecycle anchor the merge gate reads.
    """
    parents = run_command(
        ["git", "show", "-s", "--format=%P", commit], root, runner
    ).stdout.split()
    if len(parents) != 2:
        raise LifecycleError(
            f"Commit {commit[:12]} is a merge with {len(parents)} parents; only a "
            "two-parent base sync is authorized."
        )
    subject = run_command(
        ["git", "show", "-s", "--format=%s", commit], root, runner
    ).stdout.strip()
    match = SYNC_SUBJECT_RE.fullmatch(subject)
    if not match:
        raise LifecycleError(
            f"Commit {commit[:12]} is a merge with an unauthorized subject "
            f"('{subject}'). Only `sync-base` may merge into a feature branch."
        )
    if validate_feature_slug(match.group("feature")) != feature:
        raise LifecycleError(
            f"Merge {commit[:12]} targets sync feature '{match.group('feature')}', "
            f"not '{feature}'."
        )
    body = run_command(["git", "show", "-s", "--format=%B", commit], root, runner).stdout
    trailer = f"SDD-Lifecycle-Feature: {feature}"
    if sum(line.strip() == trailer for line in body.splitlines()) != 1:
        raise LifecycleError(f"Merge {commit[:12]} is missing its exact lifecycle trailer.")
    if not base_branch:
        raise LifecycleError(
            f"Merge {commit[:12]} cannot be authorized: STATE.md records no "
            "base_branch to check its second parent against."
        )
    base_ref = resolve_base_ref(root, base_branch, runner)
    if not try_command(
        ["git", "merge-base", "--is-ancestor", parents[1], base_ref], root, runner
    ):
        raise LifecycleError(
            f"Merge {commit[:12]} brought in {parents[1][:12]}, which is not "
            f"contained in '{base_ref}': that is not a base sync."
        )
    expected_path = lifecycle_path(root, feature, runner)
    touched = run_command(
        ["git", "diff", "--name-only", f"{commit}^1", commit, "--", expected_path],
        root,
        runner,
    ).stdout.strip()
    if touched:
        raise LifecycleError(
            f"Merge {commit[:12]} modifies {expected_path}. A base sync integrates "
            "code; the lifecycle anchor is written only by lifecycle commits."
        )
    return "sync"


def commit_sync(
    root: Path,
    feature: str,
    verification: str = "",
    failed: bool = False,
    runner: Runner = subprocess.run,
) -> tuple[str, list[str]]:
    """Record the merge in progress as the branch's authorized sync commit."""
    change = active_change(root, feature)
    data = read_state(change)
    if not data:
        raise LifecycleError(f"'{feature}' has no STATE.md to sync against.")
    base = data.get("base_branch", "").strip()
    if not base:
        raise LifecycleError("STATE.md records no base_branch, so there is no base to sync from.")
    if not merge_in_progress(root, runner):
        raise LifecycleError(
            "No merge is in progress, so there is nothing to record. Start one with "
            f"sync-base {feature}."
        )
    pending = unmerged_paths(root, runner)
    if pending:
        raise LifecycleError(
            "These paths are still unresolved, so the sync cannot be recorded: "
            + ", ".join(pending)
        )
    markers = leftover_conflict_markers(root, runner)
    if markers:
        raise LifecycleError(
            "git still finds conflict markers in the resolution: "
            + ", ".join(markers)
            + ". Fix them before recording the sync."
        )
    merged_sha = run_command(
        ["git", "rev-parse", "MERGE_HEAD"], root, runner
    ).stdout.strip()
    base_ref = resolve_base_ref(root, base, runner)
    if not try_command(
        ["git", "merge-base", "--is-ancestor", merged_sha, base_ref], root, runner
    ):
        raise LifecycleError(
            f"The merge in progress brings in {merged_sha[:12]}, which is not "
            f"contained in '{base_ref}'. Only the base branch may be synced in."
        )
    conflicts = recorded_conflicts(root, runner)
    subject = f"chore(sdd): sync {feature} {base}@{merged_sha[:12]}"
    verified = "not run"
    if verification:
        verified = f"{verification} -> {'FAILED' if failed else 'ok'}"
    body = "\n".join(
        [
            f"SDD-Sync-Base: {base_ref}@{merged_sha}",
            f"SDD-Sync-Resolved: {', '.join(conflicts) if conflicts else 'none'}",
            f"SDD-Sync-Verified: {verified}",
            f"SDD-Lifecycle-Feature: {feature}",
        ]
    )
    result = runner(
        ["git", "commit", "-m", subject, "-m", body],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise LifecycleError(f"Recording the sync commit failed: {detail or 'unknown error'}")
    commit = run_command(["git", "rev-parse", "HEAD"], root, runner).stdout.strip()
    # Fail here rather than at ship's next gate: a sync the ship validator would
    # reject is worse than no sync, because it blocks the branch permanently.
    validate_sync_commit(root, commit, feature, base, runner)
    return commit, conflicts


def sync_base(
    root: Path,
    feature: str,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    """Bring the base branch into the feature branch, before the PR is judged.

    Why this exists: with several features in flight the base moves under every
    open PR, and "the PR has conflicts" was the one stretch of the flow nothing
    owned — review stops at READY_FOR_PR, ship published, archive refuses to
    start before the merge, so the integration happened by hand in between and
    left no record.

    Why merge and never rebase: `implementation_sha` is the reviewed anchor every
    later gate reads, and a rebase rewrites it out of existence — the merge gate
    would have nothing left to prove. A merge keeps it an ancestor of HEAD, which
    is exactly what validate-ship asserts.

    Bookkeeping conflicts are resolved here because their merge is decidable;
    everything else is left conflicted, in the working tree, for whoever ran the
    command to resolve and then record with `record-sync`. It never pushes.
    """
    change = active_change(root, feature)
    data = read_state(change)
    if not data:
        raise LifecycleError(f"'{feature}' has no STATE.md.")
    state = data.get("state")
    if state not in {"READY_FOR_PR", "PR_OPEN"}:
        raise LifecycleError(
            f"Syncing the base applies to a change being published, and '{feature}' "
            f"is {state}. Nothing was touched."
        )
    for field in ("base_branch", "head_branch", "implementation_sha"):
        if not data.get(field):
            raise LifecycleError(f"STATE.md is missing {field}; run /sdd:review to record it.")
    base = data["base_branch"]
    head = data["head_branch"]
    current = run_command(["git", "branch", "--show-current"], root, runner).stdout.strip()
    if current != head:
        raise LifecycleError(
            f"The base is synced into the feature branch '{head}', and HEAD is on "
            f"'{current or '(detached)'}'."
        )
    if merge_in_progress(root, runner):
        raise LifecycleError(
            "A merge is already in progress here. Finish it (resolve the paths and "
            f"run record-sync {feature}) or abandon it (git merge --abort)."
        )
    dirty = status_paths(root, runner)
    if dirty:
        raise LifecycleError(
            "The worktree must be clean before merging the base into it: "
            + ", ".join(path for _, path in dirty[:5])
        )
    if try_command(["git", "remote", "get-url", "origin"], root, runner):
        if not try_command(["git", "fetch", "origin", base], root, runner):
            raise LifecycleError(
                f"`git fetch origin {base}` failed, so what the base holds is "
                "unknown. Nothing was merged."
            )
    base_ref = resolve_base_ref(root, base, runner)
    base_sha = run_command(
        ["git", "rev-parse", f"{base_ref}^{{commit}}"], root, runner
    ).stdout.strip()
    report: dict[str, object] = {
        "feature": feature,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "synced": False,
        "commit": "",
        "resolved": [],
        "pending": [],
        "notes": [],
        "behind": 0,
    }
    if try_command(
        ["git", "merge-base", "--is-ancestor", base_ref, "HEAD"], root, runner
    ):
        report["reason"] = f"'{head}' already contains {base_ref} ({base_sha[:8]})."
        return report
    report["behind"] = len(
        run_command(
            ["git", "rev-list", f"HEAD..{base_ref}"], root, runner
        ).stdout.split()
    )
    merge = runner(
        ["git", "merge", "--no-ff", "--no-commit", base_ref],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    pending = unmerged_paths(root, runner)
    if merge.returncode and not pending:
        try_command(["git", "merge", "--abort"], root, runner)
        detail = (merge.stderr or merge.stdout).strip()
        raise LifecycleError(
            f"`git merge {base_ref}` failed without leaving conflicts to resolve, "
            f"so nothing was changed: {detail or 'unknown error'}"
        )
    resolved, notes = resolve_bookkeeping(root, runner)
    report["resolved"] = resolved
    report["notes"] = notes
    pending = unmerged_paths(root, runner)
    if pending:
        # Deliberately left in progress: the resolution is the caller's, and an
        # aborted merge would throw away the part already done.
        report["pending"] = pending
        report["reason"] = (
            f"{len(pending)} path(s) need a decision. Resolve them, then run "
            f"record-sync {feature}."
        )
        return report
    commit, conflicts = commit_sync(root, feature, runner=runner)
    report["synced"] = True
    report["commit"] = commit
    report["resolved"] = conflicts or resolved
    report["reason"] = f"Merged {base_ref} ({base_sha[:8]}) into '{head}'."
    return report


def render_sync(report: dict[str, object]) -> str:
    lines = [f"sync {report['feature']} <- {report['base_ref']}@{str(report['base_sha'])[:12]}"]
    if report.get("commit"):
        lines.append(f"  merged:   {str(report['commit'])[:12]}")
    resolved = report.get("resolved") or []
    if resolved:
        lines.append(f"  resolved: {', '.join(resolved)}")
    for note in report.get("notes") or []:
        lines.append(f"  ! {note}")
    pending = report.get("pending") or []
    if pending:
        lines.append(f"  PENDING:  {', '.join(pending)}")
    lines.append(f"  {report.get('reason', '')}")
    return "\n".join(lines)


def unpushed_bookkeeping(
    root: Path, range_spec: str, runner: Runner = subprocess.run
) -> tuple[list[str], list[str]]:
    """The commits in a range and whatever they touch outside `sdd/`.

    Asked before pushing AND before integrating, because both answer the same
    question — what exactly is in these commits — and unrelated local work on the
    base is not archive's to move either way.
    """
    commits = [
        line
        for line in run_command(
            ["git", "log", "--format=%h %s", range_spec], root, runner
        ).stdout.splitlines()
        if line.strip()
    ]
    touched = [
        path
        for path in run_command(
            ["git", "diff", "--name-only", range_spec], root, runner
        ).stdout.splitlines()
        if path.strip()
    ]
    outside = sorted({path for path in touched if not path.startswith("sdd/")})
    return commits, outside


def integrate_base(
    root: Path,
    base: str,
    remote_ref: str,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Rebase the local bookkeeping commits onto a base that moved on.

    The archive commit is the only commit the flow makes directly on the base, so
    two archives running in parallel diverge from origin by construction — and
    the files they collide on (`sdd/metrics.md`, `sdd/roadmap.md`) are append-only
    by design (ADR 0001). Integrating them is decidable; anything else is not, and
    then this restores the branch and refuses exactly as before.

    Returns the paths it resolved. Never force-pushes, never drops a commit.
    """
    dirty = status_paths(root, runner)
    if dirty:
        raise LifecycleError(
            f"'{remote_ref}' moved on and integrating it needs a clean tree, but "
            "these paths are not committed: "
            + ", ".join(path for _, path in dirty[:5])
        )
    resolved: list[str] = []
    attempt = runner(
        ["git", "-c", "core.editor=true", "rebase", remote_ref],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    rounds = 0
    while attempt.returncode:
        rounds += 1
        pending = unmerged_paths(root, runner)
        detail = (attempt.stderr or attempt.stdout).strip()
        if not pending and rounds <= MAX_INTEGRATION_ROUNDS and "--skip" in detail:
            # The commit became empty: the base already carries what it did — two
            # archives ticking the same roadmap entry, typically. Dropping it is
            # what `git rebase` itself proposes, and it loses nothing.
            attempt = runner(
                ["git", "-c", "core.editor=true", "rebase", "--skip"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            continue
        if not pending or rounds > MAX_INTEGRATION_ROUNDS:
            try_command(["git", "rebase", "--abort"], root, runner)
            raise LifecycleError(
                f"Integrating '{remote_ref}' failed and the branch was restored "
                f"unchanged: {detail or 'unknown error'}"
            )
        done, notes = resolve_bookkeeping(root, runner)
        resolved.extend(done)
        left = unmerged_paths(root, runner)
        if left:
            try_command(["git", "rebase", "--abort"], root, runner)
            listed = ", ".join(left)
            because = ("; ".join(notes) + ". ") if notes else ""
            raise LifecycleError(
                f"'{remote_ref}' moved on and these paths need a decision: "
                f"{listed}. {because}The branch was restored unchanged — integrate "
                f"it yourself (git pull --rebase origin {base}) and re-run. Never "
                "force-push a shared base."
            )
        attempt = runner(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    if not try_command(
        ["git", "merge-base", "--is-ancestor", remote_ref, base], root, runner
    ):
        raise LifecycleError(
            f"After integrating, '{base}' still does not contain '{remote_ref}'. "
            "Stopping rather than pushing an unknown state."
        )
    return sorted(set(resolved))


def query_pr(url: str, root: Path, runner: Runner = subprocess.run) -> dict[str, object]:
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            url,
            "--json",
            (
                "number,url,state,mergedAt,mergeCommit,baseRefName,headRefName,"
                "headRefOid,commits"
            ),
        ],
        root,
        runner,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LifecycleError("gh returned invalid JSON for the Pull Request.") from error
    if not isinstance(payload, dict):
        raise LifecycleError("gh returned an unexpected Pull Request payload.")
    return payload


def pr_identity(url: str) -> tuple[str, str]:
    match = PR_URL_RE.match(url)
    if not match:
        raise LifecycleError(
            "Pull Request URL must use https://github.com/<owner>/<repo>/pull/<number>."
        )
    return match.group("repository"), match.group("number")


def commit_oids(payload: dict[str, object]) -> set[str]:
    commits = payload.get("commits")
    if not isinstance(commits, list):
        return set()
    return {
        str(item.get("oid", ""))
        for item in commits
        if isinstance(item, dict) and item.get("oid")
    }


def validate_pr_metadata(state: dict[str, str]) -> None:
    missing = [field for field in PR_FIELDS if not state.get(field)]
    if missing:
        raise LifecycleError(
            f"Incomplete PR evidence in STATE.md: missing {', '.join(missing)}."
        )
    repository, number = pr_identity(state["pr_url"])
    if repository.lower() != state["repository"].lower():
        raise LifecycleError("PR URL repository does not match STATE.md repository.")
    if number != state["pr_number"]:
        raise LifecycleError("PR URL number does not match STATE.md pr_number.")


def validate_pr_identity(state: dict[str, str], payload: dict[str, object]) -> None:
    validate_pr_metadata(state)
    checks = {
        "url": state["pr_url"].rstrip("/"),
        "number": int(state["pr_number"]),
        "baseRefName": state["base_branch"],
        "headRefName": state["head_branch"],
    }
    for field, expected in checks.items():
        actual = payload.get(field)
        normalized = actual.rstrip("/") if field == "url" and isinstance(actual, str) else actual
        if normalized != expected:
            raise LifecycleError(
                f"PR {field} mismatch: expected '{expected}', got '{actual}'."
            )
    if state["implementation_sha"] not in commit_oids(payload):
        raise LifecycleError(
            "The recorded implementation SHA is not present in the Pull Request commits."
        )


def initial_state() -> dict[str, str]:
    return {
        "schema": "1",
        "state": "ACTIVE",
        "local_review": "PENDING",
    }


def start_change(root: Path, feature: str) -> str:
    change = active_change(root, feature)
    data = read_state(change)
    if data:
        return f"Lifecycle already initialized at state {data.get('state', 'UNKNOWN')}."
    write_state(change, initial_state())
    return "ACTIVE recorded."


def mark_local_verified(root: Path, feature: str) -> str:
    change = active_change(root, feature)
    ensure_local_gates(change)
    data = read_state(change) or initial_state()
    current = data.get("state", "ACTIVE")
    if (
        current in {"READY_FOR_PR", "PR_OPEN", "MERGED"}
        and data.get("local_review") == "APPROVED"
    ):
        return f"Local verification already recorded; lifecycle is {current}."
    if current not in {"ACTIVE", "LOCAL_VERIFIED"}:
        raise LifecycleError(
            f"Cannot mark local verification from lifecycle state '{current}'."
        )
    data["state"] = "LOCAL_VERIFIED"
    data["local_review"] = "APPROVED"
    if current == "LOCAL_VERIFIED":
        return "LOCAL_VERIFIED already recorded."
    data["implementation_sha"] = run_command(
        ["git", "rev-parse", "HEAD"], root
    ).stdout.strip()
    lifecycle = lifecycle_commit(root, feature, "ACTIVE->LOCAL_VERIFIED", data)
    classify_lifecycle_commit(root, lifecycle, feature)
    return "LOCAL_VERIFIED recorded."


def mark_ready(
    root: Path, feature: str, base_branch: str, runner: Runner = subprocess.run
) -> str:
    change = active_change(root, feature)
    ensure_local_gates(change)
    data = read_state(change)
    if not data or data.get("local_review") != "APPROVED":
        raise LifecycleError(
            "Local review is not approved. Run /sdd:review before READY_FOR_PR."
        )
    current = data.get("state")
    if current in {"PR_OPEN", "MERGED"}:
        return f"READY_FOR_PR already passed; lifecycle is {current}."
    if current == "READY_FOR_PR":
        validate_ship_suffix(root, feature, runner)
        return "READY_FOR_PR already recorded."
    if current != "LOCAL_VERIFIED":
        raise LifecycleError(f"Cannot mark READY_FOR_PR from lifecycle state '{current}'.")
    expected_path = lifecycle_path(root, feature, runner)
    ensure_clean_or_only_expected_state(root, expected_path, runner)
    if (change / "STATE.md").read_text(encoding="utf-8") != render_state(data):
        raise LifecycleError(
            "STATE.md has pre-existing edits; refusing to overwrite lifecycle metadata."
        )
    context = git_context(root, base_branch, runner)
    if not data.get("implementation_sha"):
        raise LifecycleError("LOCAL_VERIFIED metadata has no stable implementation_sha anchor.")
    context["implementation_sha"] = data["implementation_sha"]
    data.update(context)
    data["state"] = "READY_FOR_PR"
    for field in ("pr_number", "pr_url", "pr_state", "merge_sha"):
        data[field] = ""
    lifecycle = lifecycle_commit(
        root, feature, "LOCAL_VERIFIED->READY_FOR_PR", data, runner
    )
    classify_lifecycle_commit(root, lifecycle, feature, runner)
    return "READY_FOR_PR recorded."


def mark_recertified(
    root: Path,
    feature: str,
    runner: Runner = subprocess.run,
) -> str:
    """Re-anchor `implementation_sha` on the same open PR after a functional fix.

    The canonical state stays `PR_OPEN`; the transition is the self-loop
    `PR_OPEN -> PR_OPEN` whose new commit's `implementation_sha` equals the
    parent SHA (the new reviewed HEAD) — never the commit's own SHA. The
    previous helpers `ensure_clean_or_only_expected_state` and
    `ensure_local_gates` cover the working tree, BLOCKED.md, incomplete
    tasks and staged STATE.md; this function only adds the recertification-
    specific preconditions (state, branch, local_review) and the
    `gh pr view` validation that the same PR still exists and that the new
    HEAD is among its commits (i.e. the user has pushed the fix). It does
    not push.
    """
    change = active_change(root, feature)
    expected_path = lifecycle_path(root, feature, runner)
    ensure_clean_or_only_expected_state(root, expected_path, runner)
    ensure_local_gates(change)
    data = read_state(change)
    if not data:
        raise LifecycleError(
            f"'{feature}' has no STATE.md to recertify against."
        )
    current = data.get("state", "")
    if current != "PR_OPEN":
        raise LifecycleError(
            f"mark-recertified requires state PR_OPEN; found '{current}'. "
            "Walk the change through /sdd:review and /sdd:ship first."
        )
    if data.get("local_review") != "APPROVED":
        raise LifecycleError("Local review is not approved in STATE.md.")
    head_branch = data.get("head_branch", "")
    current_branch = run_command(
        ["git", "branch", "--show-current"], root, runner
    ).stdout.strip()
    if current_branch != head_branch:
        raise LifecycleError(
            f"Recertification must run on '{head_branch}'; HEAD is on "
            f"'{current_branch or '(detached)'}'. Switch first."
        )
    head = run_command(["git", "rev-parse", "HEAD"], root, runner).stdout.strip()
    if head == data.get("implementation_sha", ""):
        return "Recertification is current; nothing to do."
    pr_url = data.get("pr_url", "").strip()
    if not pr_url:
        raise LifecycleError(
            f"STATE.md has no recorded pr_url; record the PR with "
            f"/sdd:ship {feature} first."
        )
    payload = query_pr(pr_url, root, runner)
    prospective = dict(data)
    prospective["pr_url"] = pr_url.rstrip("/")
    validate_pr_identity(prospective, payload)
    github_state = payload.get("state")
    if github_state == "MERGED":
        raise LifecycleError(
            f"PR #{prospective.get('pr_number')} is MERGED on GitHub; "
            f"run /sdd:archive {feature} instead."
        )
    if github_state == "CLOSED":
        raise LifecycleError(
            f"PR #{prospective.get('pr_number')} was CLOSED without merge. "
            f"Reopen it or open a new PR with /sdd:ship {feature}."
        )
    if github_state != "OPEN":
        raise LifecycleError(f"Unsupported GitHub PR state '{github_state}'.")
    commits = commit_oids(payload)
    if head not in commits:
        raise LifecycleError(
            f"HEAD {head[:12]} is not in the Pull Request commits; "
            f"the user must `git push origin {head_branch}` before "
            f"recertifying."
        )
    new_data = dict(data)
    new_data["implementation_sha"] = head  # parent SHA, never the commit's own
    old_anchor = data.get("implementation_sha", "")
    lifecycle = lifecycle_commit(
        root,
        feature,
        "PR_OPEN->PR_OPEN",
        new_data,
        body_lines=[f"SDD-Prior-Implementation-SHA: {old_anchor}"],
        runner=runner,
    )
    classify_lifecycle_commit(root, lifecycle, feature, runner)
    return f"PR_OPEN re-anchored at {head[:12]}."


def record_pr(
    root: Path,
    feature: str,
    url: str,
    runner: Runner = subprocess.run,
) -> str:
    change = active_change(root, feature)
    ensure_local_gates(change)
    data = read_state(change)
    if not data or data.get("state") not in {"READY_FOR_PR", "PR_OPEN", "MERGED"}:
        raise LifecycleError("Change must be READY_FOR_PR before recording a PR.")
    repository, number = pr_identity(url)
    if repository.lower() != data.get("repository", "").lower():
        raise LifecycleError("PR repository does not match READY_FOR_PR metadata.")
    payload = query_pr(url, root, runner)
    prospective = dict(data)
    prospective.update({"pr_url": url.rstrip("/"), "pr_number": number})
    validate_pr_identity(prospective, payload)
    github_state = payload.get("state")
    if github_state == "CLOSED" and not payload.get("mergedAt"):
        raise LifecycleError(
            "Associated PR was CLOSED without merge. Reopen it or use the correct PR."
        )
    if github_state == "MERGED":
        merge_commit = payload.get("mergeCommit")
        merge_sha = (
            str(merge_commit.get("oid", ""))
            if isinstance(merge_commit, dict)
            else ""
        )
        if not payload.get("mergedAt") or not SHA_RE.match(merge_sha):
            raise LifecycleError("Merged PR has incomplete merge evidence.")
        prospective["state"] = "MERGED"
        prospective["pr_state"] = "MERGED"
        prospective["merge_evidence"] = "pr"
        prospective["merge_sha"] = merge_sha
    elif github_state == "OPEN":
        prospective["state"] = "PR_OPEN"
        prospective["pr_state"] = "OPEN"
        prospective["merge_sha"] = ""
    else:
        raise LifecycleError(f"Unsupported GitHub PR state '{github_state}'.")
    if data.get("state") in {"PR_OPEN", "MERGED"}:
        return f"{data['state']} already recorded."
    expected_path = lifecycle_path(root, feature, runner)
    ensure_clean_or_only_expected_state(root, expected_path, runner)
    if (change / "STATE.md").read_text(encoding="utf-8") != render_state(data):
        raise LifecycleError(
            "STATE.md has pre-existing edits; refusing to overwrite lifecycle metadata."
        )
    transition = "READY_FOR_PR->MERGED" if prospective["state"] == "MERGED" else "READY_FOR_PR->PR_OPEN"
    lifecycle = lifecycle_commit(root, feature, transition, prospective, runner)
    classify_lifecycle_commit(root, lifecycle, feature, runner)
    recorded = prospective["state"]
    return f"{recorded} recorded."


def require_merge(
    root: Path,
    feature: str,
    runner: Runner = subprocess.run,
    write: bool = True,
) -> tuple[dict[str, str], dict[str, object], bool]:
    change = active_change(root, feature)
    ensure_local_gates(change)
    data = read_state(change)
    if not data:
        raise LifecycleError(
            "Legacy active change has no STATE.md. Run /sdd:review, associate its "
            "real PR, and retry; merge evidence is never inferred."
        )
    if data.get("local_review") != "APPROVED":
        raise LifecycleError("Local review is not approved in STATE.md.")

    # Two evidence paths, both objective. A recorded PR is the authority when it
    # exists; otherwise git itself proves the merge — the reviewed commit
    # contained in the base, or the base carrying the same change squashed or
    # rebased — so workflows without GitHub PRs (no remote, trunk-based, GitLab,
    # local merges) can still close the loop instead of being stuck at
    # READY_FOR_PR forever.
    # PR_OPEN asserts a Pull Request exists, so it is always judged on PR
    # evidence — missing metadata there is an error, not a fallback.
    use_local_evidence = (
        not data.get("pr_url")
        and data.get("state") in {"READY_FOR_PR", "MERGED"}
        and data.get("merge_evidence", "") in {"", "ancestor", "equivalent"}
    )
    if use_local_evidence:
        kind, base_ref, merge_sha = verify_local_merge(root, data, runner)
        data["state"] = "MERGED"
        data["pr_state"] = ""
        data["merge_evidence"] = kind
        data["merge_sha"] = merge_sha
        changed = write_state(change, data) if write else False
        return data, {"evidence": kind, "base_ref": base_ref}, changed

    if data.get("state") not in {"PR_OPEN", "MERGED"}:
        raise LifecycleError(
            f"Change must be PR_OPEN or MERGED before archive; found '{data.get('state')}'."
        )
    validate_pr_metadata(data)
    payload = query_pr(data["pr_url"], root, runner)
    validate_pr_identity(data, payload)
    github_state = payload.get("state")
    merged_at = payload.get("mergedAt")
    merge_commit = payload.get("mergeCommit")
    merge_sha = (
        str(merge_commit.get("oid", ""))
        if isinstance(merge_commit, dict)
        else ""
    )
    if github_state == "OPEN":
        raise LifecycleError(
            f"PR #{data.get('pr_number')} is still OPEN. Merge it, then rerun /sdd:archive."
        )
    if github_state == "CLOSED" and not merged_at:
        raise LifecycleError(
            f"PR #{data.get('pr_number')} was CLOSED without merge. Reopen or replace it."
        )
    if github_state != "MERGED" or not merged_at or not SHA_RE.match(merge_sha):
        raise LifecycleError(
            "GitHub did not provide complete MERGED evidence and a merge commit SHA."
        )
    data["state"] = "MERGED"
    data["pr_state"] = "MERGED"
    data["merge_evidence"] = "pr"
    data["merge_sha"] = merge_sha
    changed = write_state(change, data) if write else False
    return data, payload, changed


def roadmap_feature(body: str) -> str:
    text = body.split("→", 1)[0]
    text = re.split(r"\s+—\s+|\s+-\s+", text, maxsplit=1)[0]
    return text.strip().strip("`")


def update_roadmap(root: Path, feature: str, archive_relative: str) -> str:
    """Tick the feature's roadmap entry.

    Returns `ticked` (updated), `current` (matched, already correct), `unmatched`
    (no entry names this feature) or `absent` (no roadmap at all). The caller
    reports `unmatched`: a silent no-op would let archive claim a roadmap tick
    that never happened.
    """
    roadmap = root / "sdd" / "roadmap.md"
    if not roadmap.is_file():
        return "absent"
    original = roadmap.read_text(encoding="utf-8")
    output: list[str] = []
    changed = False
    matched = False
    for line in original.splitlines(keepends=True):
        match = ROADMAP_ENTRY_RE.match(line.rstrip("\n"))
        if not match or roadmap_feature(match.group("body")) != feature:
            output.append(line)
            continue
        matched = True
        body = match.group("body")
        pointer = CHANGE_POINTER_RE.search(body)
        if pointer:
            body = (
                body[: pointer.start("path")]
                + archive_relative
                + body[pointer.end("path") :]
            )
        else:
            # No pointer to rewrite: /sdd:new stopped annotating in-flight changes
            # (ADR 0001, D5), because that annotation was derived state duplicated
            # into a shared file and it conflicted on merge between adjacent
            # entries. Archive is post-merge and serialized, so it is the right
            # place to record where the change ended up — append it here, or the
            # roadmap would tick without leaving any trace of the archive.
            body = f"{body.rstrip()} → {archive_relative}"
        newline = "\n" if line.endswith("\n") else ""
        updated = f"{match.group('prefix')}[x]{body}{newline}"
        output.append(updated)
        changed = changed or updated != line
    if changed:
        roadmap.write_text("".join(output), encoding="utf-8")
    if not matched:
        return "unmatched"
    return "ticked" if changed else "current"


def stage_archive_move(
    root: Path,
    change: Path,
    destination: Path,
    runner: Runner = subprocess.run,
) -> None:
    """Reflect the archive move in the git index.

    `shutil.move` is a filesystem move, invisible to git: the deletion of the
    active change is left unstaged. A commit that stages explicit paths — rather
    than `git add -A sdd/` — then keeps the old directory in HEAD, and the next
    checkout materializes it again as an orphan that `sdd-doctor` reads as an
    active change (SDD003 + SDD009 + SDD012 + SDD016, all four from that single
    dropped deletion). Staging both sides here makes the move atomic for whatever
    the caller commits afterwards.

    Deliberately scoped to the two paths of the move: living specs, the roadmap
    and the metrics stay unstaged, because those are the files the human is
    supposed to read before committing. Each side is staged on its own so a
    never-tracked source (nothing to delete, an unmatched pathspec for `git add`)
    cannot stop the destination from being staged. Nothing here is fatal — the
    archive already succeeded on disk, and a repository this fails in is one
    where the caller stages by hand anyway.
    """
    inside = try_command(
        ["git", "rev-parse", "--is-inside-work-tree"], root, runner
    )
    if not inside or inside.stdout.strip() != "true":
        return
    for path in (change, destination):
        try_command(["git", "add", "-A", "--", str(path)], root, runner)


def finalize_archive(
    root: Path,
    feature: str,
    specs_confirmed: bool,
    runner: Runner = subprocess.run,
    today: date | None = None,
) -> str:
    existing_archive = archived_change(root, feature)
    if existing_archive:
        data = read_state(existing_archive)
        if data and data.get("state") == "ARCHIVED":
            return f"Already archived at {existing_archive.relative_to(root)}."
        raise LifecycleError(
            f"Archive already exists at {existing_archive.relative_to(root)} "
            "without valid ARCHIVED metadata."
        )
    if not specs_confirmed:
        raise LifecycleError(
            "Refusing final archive until living specs have been updated after merge."
        )
    change = active_change(root, feature)
    data, _, _ = require_merge(root, feature, runner, write=False)
    if data.get("state") != "MERGED":
        raise LifecycleError("Merge evidence was not recorded before final archive.")
    archive_date = (today or date.today()).isoformat()
    destination = change.parent / "archive" / f"{archive_date}-{feature}"
    if destination.exists():
        raise LifecycleError(f"Archive destination already exists: {destination}")
    data["state"] = "ARCHIVED"
    write_state(change, data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(change), str(destination))
    stage_archive_move(root, change, destination, runner)
    archive_relative = f"changes/archive/{destination.name}/"
    roadmap_result = update_roadmap(root, feature, archive_relative)
    message = f"Archived at {destination.relative_to(root)}."
    if roadmap_result == "unmatched":
        message += (
            f" WARNING: no roadmap entry names '{feature}', so nothing was ticked "
            "— check sdd/roadmap.md by hand."
        )
    return message


def publish_archive(
    root: Path,
    feature: str,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
) -> str:
    """Publish the archive's bookkeeping commit on the base branch.

    Why archive publishes at all, when ship owns publishing feature branches:
    the archive commit is the *only* commit the flow creates directly on the base,
    and leaving it local makes the base diverge from origin permanently. Every
    later feature branches from `origin/<base>` (EnterWorktree's `fresh` default),
    so it branches from a base that does not contain the archive — the check
    reports "N local commit(s) NOT in origin" on every feature from then on, the
    roadmap tick is invisible to every other clone, and a colleague's `/sdd:doctor`
    still sees the change as active. The bookkeeping is not closed until it is
    shared.

    Every guard here answers "what exactly am I about to push?", because that is
    the question that makes pushing to a shared branch safe:

    - the change must be ARCHIVED, and HEAD must be on its recorded base;
    - `sdd/` must be committed, or the push would publish half an archive;
    - the local base must end up a fast-forward of `origin/<base>`. When the
      remote moved on — the normal case with features closing in parallel — the
      local archive commits are rebased onto it, resolving only the append-only
      bookkeeping files (`sdd/metrics.md`, `sdd/roadmap.md`) whose merge is
      decidable. Anything else restores the branch untouched and refuses: it is
      the user's to integrate, and never a force-push;
    - every commit about to be pushed must touch `sdd/` only. Unrelated local work
      on the base is not archive's to publish, and stopping is the answer.
    """
    archive = archived_change(root, feature)
    if archive is None:
        raise LifecycleError(
            f"'{feature}' has no archive yet — run finalize-archive first."
        )
    data = read_state(archive)
    if not data or data.get("state") != "ARCHIVED":
        raise LifecycleError(
            f"{archive.relative_to(root)} is not recorded as ARCHIVED, so there is "
            "nothing to publish."
        )
    base = data.get("base_branch", "").strip()
    if not base:
        raise LifecycleError(
            f"{archive.relative_to(root)} records no base_branch, so where to "
            "publish is unknown. Fix STATE.md rather than guessing a branch."
        )
    current = run_command(["git", "branch", "--show-current"], root, runner).stdout.strip()
    if current != base:
        raise LifecycleError(
            f"Publishing the archive must happen on '{base}' (shared rule 10), and "
            f"HEAD is on '{current or '(detached)'}'."
        )
    pending = run_command(
        ["git", "status", "--porcelain", "--", "sdd"], root, runner
    ).stdout.strip()
    if pending:
        raise LifecycleError(
            "sdd/ has uncommitted changes, so the archive commit is not complete "
            f"yet — commit it before publishing:\n{pending}"
        )
    if not try_command(["git", "rev-parse", "--verify", "--quiet", "origin"], root, runner) \
            and not try_command(["git", "remote", "get-url", "origin"], root, runner):
        return (
            "No 'origin' remote: the archive stays local, which is a supported "
            "workflow (the merge gate proves merges without a remote too). Nothing "
            "to publish."
        )
    if not try_command(["git", "fetch", "origin", base], root, runner):
        raise LifecycleError(
            f"`git fetch origin {base}` failed, so what the remote holds is "
            "unknown. Nothing was pushed."
        )
    remote_ref = f"origin/{base}"
    if not try_command(
        ["git", "rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}"],
        root,
        runner,
    ):
        raise LifecycleError(
            f"'{remote_ref}' does not exist after fetching. Publish the base branch "
            f"first: git push -u origin {base}."
        )
    integrated: list[str] = []
    diverged = False
    if not try_command(
        ["git", "merge-base", "--is-ancestor", remote_ref, base], root, runner
    ):
        # The remote moved on. With features closing in parallel this is the
        # normal case, not an exception: the archive commit is the only commit the
        # flow makes on the base, so two archives diverge by construction — and
        # they collide on files that are append-only by design.
        fork = run_command(
            ["git", "merge-base", remote_ref, base], root, runner
        ).stdout.strip()
        local, outside = unpushed_bookkeeping(root, f"{fork}..{base}", runner)
        if outside:
            listed = ", ".join(outside[:5]) + (" …" if len(outside) > 5 else "")
            raise LifecycleError(
                f"'{remote_ref}' moved on, and your local '{base}' carries "
                f"{len(local)} commit(s) touching files outside sdd/ ({listed}). "
                "Integrating them is not archive's call — rebase them deliberately, "
                "then re-run."
            )
        if dry_run:
            return (
                f"Would integrate {remote_ref} under {len(local)} local archive "
                f"commit(s), then push: {'; '.join(local)}"
            )
        integrated = integrate_base(root, base, remote_ref, runner)
        diverged = True
    range_spec = f"{remote_ref}..{base}"
    commits, outside = unpushed_bookkeeping(root, range_spec, runner)
    if not commits:
        return f"'{base}' already matches {remote_ref}: the archive is published."
    if outside:
        listed = ", ".join(outside[:5]) + (" …" if len(outside) > 5 else "")
        raise LifecycleError(
            f"'{base}' carries {len(commits)} unpushed commit(s) touching files "
            f"outside sdd/ ({listed}). Publishing them is not archive's call — push "
            "them deliberately, then re-run."
        )
    listed = "; ".join(commits)
    prefix = ""
    if diverged:
        detail = f", resolving {', '.join(integrated)}" if integrated else ""
        prefix = f"Integrated {remote_ref} under the local archive commit(s){detail}. "
    if dry_run:
        return f"Would push {len(commits)} archive commit(s) to {remote_ref}: {listed}"
    if not try_command(["git", "push", "origin", base], root, runner):
        raise LifecycleError(
            f"`git push origin {base}` was refused (a protected branch, or no "
            "permission). The archive is committed locally and correct; publish it "
            "the way this repository requires — e.g. a bookkeeping branch and PR: "
            f"git switch -c sdd/archive-{feature} && git push -u origin "
            f"sdd/archive-{feature}."
        )
    local_sha = run_command(["git", "rev-parse", base], root, runner).stdout.strip()
    run_command(["git", "fetch", "origin", base], root, runner)
    remote_sha = run_command(["git", "rev-parse", remote_ref], root, runner).stdout.strip()
    if local_sha != remote_sha:
        raise LifecycleError(
            f"The push reported success but {remote_ref} is at {remote_sha[:8]} "
            f"instead of {local_sha[:8]}. Check the remote before reporting a "
            "closed loop."
        )
    return (
        f"{prefix}Published {len(commits)} archive commit(s) to {remote_ref} "
        f"({local_sha[:8]}): {listed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "mark-local-verified", "verify-merge"):
        command = subparsers.add_parser(name)
        command.add_argument("feature")
    ship = subparsers.add_parser("validate-ship")
    ship.add_argument("feature")
    ready = subparsers.add_parser("mark-ready")
    ready.add_argument("feature")
    ready.add_argument("--base", required=True)
    recertify = subparsers.add_parser(
        "mark-recertified",
        help="re-anchor implementation_sha on the same open PR after a fix",
    )
    recertify.add_argument("feature")
    record = subparsers.add_parser("record-pr")
    record.add_argument("feature")
    record.add_argument("--url", required=True)
    sync = subparsers.add_parser(
        "sync-base",
        help="merge the base branch into the feature branch (exit 2 = conflicts left)",
    )
    sync.add_argument("feature")
    sync.add_argument("--json", action="store_true", help="machine-readable output")
    record_sync = subparsers.add_parser(
        "record-sync",
        help="record a resolved base sync as the branch's authorized merge commit",
    )
    record_sync.add_argument("feature")
    record_sync.add_argument(
        "--verification",
        default="",
        help="the project's verification command that was run on the resolution",
    )
    record_sync.add_argument(
        "--failed",
        action="store_true",
        help="record that the verification command failed (nothing is hidden)",
    )
    finalize = subparsers.add_parser("finalize-archive")
    finalize.add_argument("feature")
    finalize.add_argument("--specs-confirmed", action="store_true")
    publish = subparsers.add_parser(
        "publish-archive",
        help="push the archive's bookkeeping commit to the base branch",
    )
    publish.add_argument("feature")
    publish.add_argument(
        "--dry-run",
        action="store_true",
        help="run every guard and report what would be pushed, without pushing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "start":
            message = start_change(root, args.feature)
        elif args.command == "mark-local-verified":
            message = mark_local_verified(root, args.feature)
        elif args.command == "mark-ready":
            message = mark_ready(root, args.feature, args.base)
        elif args.command == "mark-recertified":
            message = mark_recertified(root, args.feature)
        elif args.command == "record-pr":
            message = record_pr(root, args.feature, args.url)
        elif args.command == "sync-base":
            report = sync_base(root, args.feature)
            print(json.dumps(report, indent=2) if args.json else render_sync(report))
            # Exit 2 is the actionable outcome, not a failure: the merge is in
            # progress and the paths it names need a decision. A distinct code is
            # what lets the caller branch on it without parsing prose.
            return 2 if report["pending"] else 0
        elif args.command == "record-sync":
            commit, conflicts = commit_sync(
                root, args.feature, args.verification, args.failed
            )
            listed = ", ".join(conflicts) if conflicts else "no conflicts"
            message = f"Sync recorded as {commit[:12]} ({listed})."
            if args.failed:
                message += (
                    " The verification FAILED and that is recorded in the commit: "
                    "do not publish this as verified."
                )
        elif args.command == "validate-ship":
            commits = validate_ship_suffix(root, args.feature)
            message = f"Ship lifecycle gates passed ({len(commits)} suffix commit(s))."
        elif args.command == "verify-merge":
            data, _, changed = require_merge(root, args.feature)
            state = "recorded" if changed else "already recorded"
            # Name the evidence kind: how a merge was proven is part of the
            # answer, not an implementation detail.
            message = f"MERGED evidence {state} ({data.get('merge_evidence')})."
        elif args.command == "publish-archive":
            message = publish_archive(root, args.feature, dry_run=args.dry_run)
        else:
            message = finalize_archive(
                root, args.feature, specs_confirmed=args.specs_confirmed
            )
    except LifecycleError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
