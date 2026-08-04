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
Runner = Callable[..., subprocess.CompletedProcess[str]]


class LifecycleError(RuntimeError):
    """Actionable lifecycle failure."""


def state_path(change: Path) -> Path:
    return change / "STATE.md"


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
    merge_base = run_command(
        ["git", "merge-base", base_ref, implementation_sha], root, runner
    ).stdout.strip()
    branch_total = range_fingerprint(root, merge_base, implementation_sha, runner)
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
        ["git", "rev-list", "--no-merges", f"{merge_base}..{implementation_sha}"],
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
    changed = write_state(change, data)
    return "LOCAL_VERIFIED recorded." if changed else "LOCAL_VERIFIED already recorded."


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
        # Idempotent at the same HEAD, but NOT a no-op once the branch has moved.
        # `implementation_sha` is not decoration: `verify-merge` fingerprints
        # `merge-base..implementation_sha`, so a stale value makes the merge gate
        # certify only the commits up to it. Re-running /sdd:review after fixing its
        # findings — the normal flow when the panel returns FAIL — used to leave the
        # field pointing at the unfixed commit, and archive would still pass.
        refreshed = git_context(root, base_branch, runner)
        if refreshed == {key: data.get(key) for key in refreshed}:
            return "READY_FOR_PR already recorded."
        previous = (data.get("implementation_sha") or "")[:12] or "(none)"
        data.update(refreshed)
        write_state(change, data)
        return (
            "READY_FOR_PR re-recorded: implementation_sha "
            f"{previous} -> {refreshed['implementation_sha'][:12]}."
        )
    if current not in {"LOCAL_VERIFIED", "READY_FOR_PR"}:
        raise LifecycleError(f"Cannot mark READY_FOR_PR from lifecycle state '{current}'.")
    data.update(git_context(root, base_branch, runner))
    data["state"] = "READY_FOR_PR"
    for field in ("pr_number", "pr_url", "pr_state", "merge_sha"):
        data[field] = ""
    changed = write_state(change, data)
    return "READY_FOR_PR recorded." if changed else "READY_FOR_PR already recorded."


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
    changed = write_state(change, prospective)
    recorded = prospective["state"]
    return f"{recorded} recorded." if changed else f"{recorded} already recorded."


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "mark-local-verified", "verify-merge"):
        command = subparsers.add_parser(name)
        command.add_argument("feature")
    ready = subparsers.add_parser("mark-ready")
    ready.add_argument("feature")
    ready.add_argument("--base", required=True)
    record = subparsers.add_parser("record-pr")
    record.add_argument("feature")
    record.add_argument("--url", required=True)
    finalize = subparsers.add_parser("finalize-archive")
    finalize.add_argument("feature")
    finalize.add_argument("--specs-confirmed", action="store_true")
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
        elif args.command == "record-pr":
            message = record_pr(root, args.feature, args.url)
        elif args.command == "verify-merge":
            data, _, changed = require_merge(root, args.feature)
            state = "recorded" if changed else "already recorded"
            # Name the evidence kind: how a merge was proven is part of the
            # answer, not an implementation detail.
            message = f"MERGED evidence {state} ({data.get('merge_evidence')})."
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
