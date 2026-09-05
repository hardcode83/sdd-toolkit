#!/usr/bin/env python3
"""Read-only consistency checks for an SDD project."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import sdd_roadmap
from sdd_session import (
    DEFAULT_ISOLATION_POLICY,
    ISOLATION_POLICIES,
    read_isolation_policy,
)
from sdd_lifecycle import (
    MANUAL_RE,
    PR_FIELDS,
    PR_URL_RE,
    SHA_RE,
    STATES,
    TASK_ID_RE,
    LifecycleError,
    blocked_entries,
    read_state,
)


# Merges proven by git itself, not by a Pull Request: these changes legitimately
# carry no PR fields, so PR-shaped checks must not fire on them.
LOCAL_MERGE_EVIDENCE = {"ancestor", "equivalent"}
# What a local-evidence merge must record instead of PR metadata.
LOCAL_EVIDENCE_FIELDS = ("base_branch", "head_branch", "implementation_sha")
ROADMAP_ENTRY_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
CHANGE_POINTER_RE = re.compile(
    r"(?P<path>(?:sdd/)?changes/(?:archive/)?[A-Za-z0-9._-]+/?)"
)
REQUIREMENT_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(R\d+)\b", re.IGNORECASE)
REQUIREMENT_REF_RE = re.compile(r"\bR\d+\b", re.IGNORECASE)
TASK_RE = re.compile(r"^\s*-\s+\[([ xX])\]")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
ARCHIVE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
LINE_SUFFIX_RE = re.compile(r":\d+(?::\d+)?$")
# Absolute paths worth checking: local checkouts. System paths (/var, /etc, /opt)
# usually describe a remote host or runtime, not a file this repository owns.
ABSOLUTE_REFERENCE_PREFIXES = ("/Users/", "/home/", "/private/")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    file: str
    line: int
    explanation: str
    action: str

    def render(self) -> str:
        location = f"{self.file}:{self.line}" if self.line else self.file
        return (
            f"{self.severity} {self.code} {location} — {self.explanation} "
            f"Suggested action: {self.action}"
        )


@dataclass(frozen=True)
class RoadmapEntry:
    line: int
    checked: bool
    feature: str
    pointer: str | None


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_archive_name(name: str) -> str:
    match = ARCHIVE_NAME_RE.match(name)
    return match.group(1) if match else name


def parse_roadmap(path: Path) -> list[RoadmapEntry]:
    entries: list[RoadmapEntry] = []
    for line_number, line in enumerate(read_lines(path), start=1):
        match = ROADMAP_ENTRY_RE.match(line)
        if not match:
            continue
        body = match.group(2)
        pointer_match = CHANGE_POINTER_RE.search(body)
        pointer = pointer_match.group("path").rstrip("/") if pointer_match else None
        feature_text = body.split("→", 1)[0]
        feature_text = re.split(r"\s+—\s+|\s+-\s+", feature_text, maxsplit=1)[0]
        feature = feature_text.strip().strip("`")
        entries.append(
            RoadmapEntry(
                line=line_number,
                checked=match.group(1).lower() == "x",
                feature=feature,
                pointer=pointer,
            )
        )
    return entries


def resolve_change_pointer(pointer: str, root: Path) -> Path:
    if pointer.startswith("sdd/"):
        return root / pointer
    return root / "sdd" / pointer


def requirement_definitions(proposal: Path) -> dict[str, int]:
    definitions: dict[str, int] = {}
    for line_number, line in enumerate(read_lines(proposal), start=1):
        match = REQUIREMENT_HEADING_RE.match(line)
        if match:
            definitions.setdefault(match.group(1).upper(), line_number)
    return definitions


def task_references(tasks: Path) -> dict[str, list[int]]:
    references: dict[str, list[int]] = {}
    in_task = False
    for line_number, line in enumerate(read_lines(tasks), start=1):
        if TASK_RE.match(line):
            in_task = True
        elif re.match(r"^\s{0,3}#{1,6}\s+", line):
            in_task = False
        if not in_task:
            continue
        for requirement in REQUIREMENT_REF_RE.findall(line):
            references.setdefault(requirement.upper(), []).append(line_number)
    return references


def pointer_checks(
    root: Path,
    roadmap: Path,
    entries: list[RoadmapEntry],
    archives_by_feature: dict[str, list[Path]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    roadmap_file = relative(roadmap, root)
    for entry in entries:
        archived = archives_by_feature.get(entry.feature, [])
        if archived and not entry.checked:
            archive_names = ", ".join(path.name for path in archived)
            diagnostics.append(
                Diagnostic(
                    "SDD001",
                    "ERROR",
                    roadmap_file,
                    entry.line,
                    (
                        f"Archived change '{entry.feature}' remains unchecked in the "
                        f"roadmap (archive: {archive_names})."
                    ),
                    "Mark the roadmap entry complete and point it at the archive.",
                )
            )
        if entry.pointer:
            target = resolve_change_pointer(entry.pointer, root)
            if not target.exists():
                diagnostics.append(
                    Diagnostic(
                        "SDD002",
                        "ERROR",
                        roadmap_file,
                        entry.line,
                        f"Roadmap entry points to missing path '{entry.pointer}'.",
                        "Update or remove the stale change pointer.",
                    )
                )
    return diagnostics


def path_is_ignored(root: Path, target: Path) -> bool:
    """Whether git ignores `target`, by every mechanism git honours.

    Asks git when `root` is the top level of a working tree, because
    `.gitignore` is only one of the sources: `.git/info/exclude` and a global
    `core.excludesFile` are equally valid places to ignore a machine-local
    directory, and reading only `.gitignore` reports a project that did it
    properly as broken.

    Falls back to a textual `.gitignore` scan when git is unavailable, or when
    `root` is not a repository top level — which is also what keeps this
    validator's own fixtures deterministic instead of dependent on whatever
    repository happens to contain them.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if not toplevel.returncode and Path(toplevel.stdout.strip()) == root:
            checked = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "-q", str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            return checked.returncode == 0
    except OSError:
        pass
    patterns = {
        line.strip().rstrip("/")
        for line in read_lines(root / ".gitignore")
        if line.strip() and not line.strip().startswith("#")
    }
    relative_target = target.relative_to(root).as_posix()
    return bool(
        patterns
        & {
            relative_target,
            f"/{relative_target}",
            f"{relative_target}/*",
            *{
                candidate
                for parent in (".claude",)
                for candidate in (parent, f"/{parent}", f"{parent}/*")
            },
        }
    )


def worktree_checks(root: Path) -> list[Diagnostic]:
    """The worktree invariants that are properties of the committed project.

    Everything else about worktrees — stale bindings, a worktree still on disk for
    an archived change — is *machine* state living in the shared git directory,
    so it is reported by `sdd_session.py orphans` (which /sdd:doctor also runs)
    rather than here: this validator's fixtures are committed project trees, and
    machine state cannot be expressed as one. The isolation policy is not machine
    state: the project declares it in `sdd/project.md` and commits it.
    """
    diagnostics: list[Diagnostic] = []
    policy = read_isolation_policy(root)
    project = root / "sdd" / "project.md"
    if not policy.valid:
        diagnostics.append(
            Diagnostic(
                "SDD026",
                "ERROR",
                relative(project, root),
                policy_line(project, policy.declared),
                (
                    f"The isolation policy is declared as '{policy.declared}', "
                    f"which is not one of {' | '.join(ISOLATION_POLICIES)}, so it "
                    f"silently falls back to '{DEFAULT_ISOLATION_POLICY}' and "
                    "every feature keeps working in the main clone."
                ),
                (
                    "Write 'isolation: always' (every feature gets its own "
                    "worktree) or 'isolation: on-conflict' (the default: only "
                    "when the check finds evidence)."
                ),
            )
        )

    worktrees = root / ".claude" / "worktrees"
    ignore = root / ".gitignore"
    exists = worktrees.is_dir()
    # Under `always` the next /sdd:new creates one, so the warning has to arrive
    # BEFORE the directory does: afterwards the nested checkout is already there.
    if (exists or policy.always) and not path_is_ignored(root, worktrees):
        diagnostics.append(
            Diagnostic(
                "SDD024",
                "WARNING",
                relative(ignore, root),
                0,
                (
                    ".claude/worktrees/ holds git worktrees but git ignores it by "
                    "no rule, so they can be committed into the repository."
                    if exists
                    else "sdd/project.md declares 'isolation: always', so the next "
                    "/sdd:new creates .claude/worktrees/ — and git ignores it by "
                    "no rule, so the worktree can be committed into the repository."
                ),
                (
                    "Add '.claude/worktrees/' to .gitignore (or .git/info/exclude to "
                    "keep it machine-local) before committing anything."
                ),
            )
        )
    return diagnostics


def policy_line(project: Path, declared: str) -> int:
    """Where the bad declaration is, so the finding points at the line to fix."""
    for number, line in enumerate(read_lines(project), start=1):
        if declared and declared in line and "isolation" in line.lower():
            return number
    return 0


ROADMAP_INDEX_BUDGET = 32 * 1024


def roadmap_size_checks(root: Path, roadmap: Path) -> list[Diagnostic]:
    """`roadmap.md` is an index, and every phase reads it.

    Its size is therefore a cost paid on every run, not once: the phase skills
    load it to find the frontier, the entry and its metadata. A roadmap that grew
    to hold each feature's rationale stops being an index — and `/sdd:new` reads
    the long version anyway, from the per-entry note it is supposed to live in.
    """
    size = roadmap.stat().st_size
    if size <= ROADMAP_INDEX_BUDGET:
        return []
    return [
        Diagnostic(
            "SDD025",
            "WARNING",
            relative(roadmap, root),
            0,
            (
                f"roadmap.md is {size // 1024} KB; every phase reads it, so that "
                f"size is paid on every run (index budget: "
                f"{ROADMAP_INDEX_BUDGET // 1024} KB)."
            ),
            (
                "Move the entries' long rationale to sdd/roadmap/<feature>.md — "
                "read only by that entry's /sdd:new — and leave one scannable "
                "line per entry plus its metadata sub-line."
            ),
        )
    ]


STEERING_LINE_BUDGET = 150


def steering_size_checks(root: Path, sdd: Path) -> list[Diagnostic]:
    """A steering doc is loaded whole by every phase and reviewer it applies to.

    `references/steering.md` asks for focused docs of about 100 lines, because the
    selective loading rule can only leave out what is in a *different* file. A
    security guide that grew to 93 KB in a real project (~23k tokens) was read in
    full by `design`, by `run` and by the security reviewer of every panel — the
    single largest fixed cost per request after the conversation itself.
    """
    steering = sdd / "steering"
    if not steering.is_dir():
        return []
    diagnostics: list[Diagnostic] = []
    for doc in sorted(steering.glob("*.md")):
        lines = len(read_lines(doc))
        if lines <= STEERING_LINE_BUDGET:
            continue
        size = doc.stat().st_size
        diagnostics.append(
            Diagnostic(
                "SDD027",
                "WARNING",
                relative(doc, root),
                0,
                (
                    f"{doc.name} is {lines} lines ({size // 1024} KB, ~{size // 4000}k "
                    f"tokens); every phase and reviewer it applies to loads it whole "
                    f"on every run (budget: {STEERING_LINE_BUDGET} lines)."
                ),
                (
                    "Split it by scope into several docs with their own `applies_to` "
                    "/ `phases` frontmatter so the loading rule can leave most of it "
                    "out; see references/steering.md."
                ),
            )
        )
    return diagnostics


# MCP servers the init catalog once wrote that no longer work. The init writes
# `.mcp.json` when the entry is correct; nothing else ever tells the project that
# it stopped being so — a dead server just fails to connect, silently, on every
# session. Each row: a substring that identifies the entry in its `url` or
# `args`, why it is dead, and the catalog's current replacement.
DEAD_MCP_SERVERS = (
    (
        "mcp.atlassian.com/v1/sse",
        "Atlassian switched the legacy SSE endpoint off on 30 June 2026",
        'use `{"type": "http", "url": "https://mcp.atlassian.com/v2/mcp"}` '
        "(references/mcp-catalog.md, atlassian)",
    ),
    (
        "@modelcontextprotocol/server-postgres",
        "the reference Postgres server is archived upstream with no security "
        "guarantees",
        "use `npx -y @bytebase/dbhub --dsn <read-only DSN>` "
        "(references/mcp-catalog.md, postgres)",
    ),
)


def mcp_config_checks(root: Path) -> list[Diagnostic]:
    """A `.mcp.json` entry that points at a server switched off upstream."""
    config = root / ".mcp.json"
    if not config.is_file():
        return []
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    diagnostics: list[Diagnostic] = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        haystack = " ".join(
            [str(server.get("url", "")), str(server.get("command", ""))]
            + [str(item) for item in server.get("args", []) or []]
        )
        for needle, why, fix in DEAD_MCP_SERVERS:
            if needle in haystack:
                diagnostics.append(
                    Diagnostic(
                        "SDD029",
                        "WARNING",
                        relative(config, root),
                        next(
                            (
                                number
                                for number, text in enumerate(read_lines(config), start=1)
                                if needle in text
                            ),
                            0,
                        ),
                        f"MCP server `{name}` no longer works: {why}.",
                        f"Replace the entry — {fix} — or remove it; "
                        "re-running /sdd:init offers the replacement.",
                    )
                )
    return diagnostics


REVIEWER_FRONTMATTER_RE = re.compile(r"\A---\n(?P<head>.*?)\n---\n", re.DOTALL)


def reviewer_metadata_checks(root: Path) -> list[Diagnostic]:
    """A project reviewer without `applies_to`/`phases` runs on every panel.

    The shared planner (`skills/reviewer-panel/reviewer_plan.py`) can skip a
    project reviewer only on a definitive NO MATCH; without metadata the answer
    is UNKNOWN and the reviewer is launched for every section of every change. In
    a real project four such reviewers turned a 13-section run into 91 reviewer
    launches, most of them on files their lens had nothing to say about.
    """
    directory = root / ".claude" / "agents"
    if not directory.is_dir():
        return []
    diagnostics: list[Diagnostic] = []
    for path in sorted(directory.glob("sdd-review-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        match = REVIEWER_FRONTMATTER_RE.match(text)
        keys: set[str] = set()
        if match:
            for line in match.group("head").splitlines():
                if ":" in line:
                    keys.add(line.split(":", 1)[0].strip())
        missing = [key for key in ("phases", "applies_to") if key not in keys]
        if not missing:
            continue
        diagnostics.append(
            Diagnostic(
                "SDD028",
                "WARNING",
                relative(path, root),
                0,
                (
                    f"{path.name} declares no {' / '.join(missing)}: the panel "
                    f"cannot exclude it, so it runs on every section of every "
                    f"change, whatever files the section touched."
                ),
                (
                    "Add `phases: [run, review, auto]` and `applies_to: [\"<globs of "
                    "the files this lens is about>\"]` to its frontmatter; see "
                    "templates/reviewer-template.md."
                ),
            )
        )
    return diagnostics


def graph_checks(root: Path, roadmap: Path) -> list[Diagnostic]:
    """Dependency-graph consistency, delegated to the roadmap module.

    The graph lives in sdd_roadmap.py because the phase skills need the same
    answers (frontier, waves) that validation is derived from — duplicating the
    parser here is how the two would drift apart.
    """
    try:
        entries = sdd_roadmap.parse_roadmap(roadmap)
    except sdd_roadmap.RoadmapError:
        return []
    graph = sdd_roadmap.Graph(root, entries)
    roadmap_file = relative(roadmap, root)
    return [
        Diagnostic(
            finding.code,
            finding.severity,
            roadmap_file,
            finding.line,
            finding.explanation,
            finding.action,
        )
        for finding in graph.validate()
    ]


def active_document_checks(root: Path, active_changes: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for change in active_changes:
        proposal = change / "proposal.md"
        if not proposal.is_file():
            diagnostics.append(
                Diagnostic(
                    "SDD003",
                    "ERROR",
                    relative(change, root),
                    0,
                    f"Active change '{change.name}' has no mandatory proposal.md.",
                    f"Create sdd/changes/{change.name}/proposal.md via /sdd:new.",
                )
            )
        diagnostics.extend(blocked_queue_checks(root, change))
    return diagnostics


def blocked_queue_checks(root: Path, change: Path) -> list[Diagnostic]:
    """SDD030/SDD031 — the pending queue has to be readable by the gates.

    `mark-local-verified` lets `deferred`/`assumed` entries and `<!-- manual -->`
    tasks travel with the PR, and stops on `decision` entries — so an entry
    whose type cannot be read is treated as a decision (fail closed), and an
    open manual task that no `deferred` entry names still blocks. Both are
    things the doctor can say before the gate refuses (ADR 0006).
    """
    diagnostics: list[Diagnostic] = []
    entries = blocked_entries(change)
    blocked = change / "BLOCKED.md"
    for entry in entries:
        if entry.kind == "unknown":
            diagnostics.append(
                Diagnostic(
                    "SDD030",
                    "WARNING",
                    relative(blocked, root),
                    entry.line,
                    (
                        f"BLOCKED entry '{entry.title[:60]}' has no readable type "
                        "(decision / deferred / assumed); the gates treat it as a decision."
                    ),
                    "Add a `- **type**: …` line, or rewrite it with `sdd_lifecycle.py block`.",
                )
            )
    deferred_tasks = {
        task for entry in entries if entry.kind == "deferred" for task in entry.tasks
    }
    tasks = change / "tasks.md"
    for line_number, line in enumerate(read_lines(tasks), start=1):
        match = TASK_RE.match(line)
        if not (match and match.group(1) == " " and MANUAL_RE.search(line)):
            continue
        task = TASK_ID_RE.match(line)
        task_id = task.group("id") if task else None
        if task_id in deferred_tasks:
            continue
        diagnostics.append(
            Diagnostic(
                "SDD031",
                "WARNING",
                relative(tasks, root),
                line_number,
                (
                    f"Manual task {task_id or '?'} is open and no `deferred` BLOCKED "
                    "entry names it; READY_FOR_PR will refuse."
                ),
                (
                    f"Do it, or record it: `sdd_lifecycle.py block {change.name} "
                    f"--type deferred --task {task_id or 'N.M'} …`."
                ),
            )
        )
    return diagnostics


def requirement_checks(root: Path, change_dirs: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for change in change_dirs:
        proposal = change / "proposal.md"
        tasks = change / "tasks.md"
        if not proposal.is_file() or not tasks.is_file():
            continue
        definitions = requirement_definitions(proposal)
        references = task_references(tasks)
        for requirement in sorted(references, key=requirement_sort_key):
            if requirement in definitions:
                continue
            for line_number in references[requirement]:
                diagnostics.append(
                    Diagnostic(
                        "SDD004",
                        "ERROR",
                        relative(tasks, root),
                        line_number,
                        (
                            f"Task cites undefined requirement '{requirement}' in "
                            f"{relative(proposal, root)}."
                        ),
                        "Correct the task reference or define the requirement in proposal.md.",
                    )
                )
        for requirement in sorted(definitions, key=requirement_sort_key):
            if requirement in references:
                continue
            diagnostics.append(
                Diagnostic(
                    "SDD005",
                    "ERROR",
                    relative(proposal, root),
                    definitions[requirement],
                    f"Requirement '{requirement}' has no associated task.",
                    f"Add at least one checkbox task citing [{requirement}].",
                )
            )
    return diagnostics


def requirement_sort_key(requirement: str) -> tuple[int, str]:
    match = re.search(r"\d+", requirement)
    return (int(match.group()) if match else sys.maxsize, requirement)


def unchecked_tasks(change: Path) -> list[int]:
    """Line numbers of tasks still open in a change's tasks.md."""
    return [
        line_number
        for line_number, line in enumerate(read_lines(change / "tasks.md"), start=1)
        if (match := TASK_RE.match(line)) and match.group(1) == " "
    ]


def open_tasks_not_carried(change: Path) -> list[int]:
    """Open task lines, minus `<!-- manual -->` tasks a `deferred` entry names:
    those legitimately stay open through READY_FOR_PR/PR_OPEN (ADR 0006)."""
    deferred_tasks = {
        task for entry in blocked_entries(change) if entry.kind == "deferred" for task in entry.tasks
    }
    lines: list[int] = []
    for line_number, line in enumerate(read_lines(change / "tasks.md"), start=1):
        match = TASK_RE.match(line)
        if not (match and match.group(1) == " "):
            continue
        task = TASK_ID_RE.match(line)
        if MANUAL_RE.search(line) and task and task.group("id") in deferred_tasks:
            continue
        lines.append(line_number)
    return lines


def active_blocked_file(change: Path) -> Path | None:
    """The change's BLOCKED.md when it still holds unresolved content."""
    blocked = change / "BLOCKED.md"
    if blocked.is_file() and blocked.read_text(
        encoding="utf-8", errors="replace"
    ).strip():
        return blocked
    return None


def archive_checks(root: Path, archived_changes: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for change in archived_changes:
        tasks = change / "tasks.md"
        if tasks.is_file():
            pending = unchecked_tasks(change)
            if pending:
                diagnostics.append(
                    Diagnostic(
                        "SDD006",
                        "WARNING",
                        relative(tasks, root),
                        pending[0],
                        (
                            f"Archived change '{canonical_archive_name(change.name)}' "
                            f"contains {len(pending)} unchecked task(s)."
                        ),
                        "Confirm the work actually shipped; the merge gate refuses to archive with pending tasks.",
                    )
                )
        blocked = active_blocked_file(change)
        if blocked:
            diagnostics.append(
                Diagnostic(
                    "SDD007",
                    "WARNING",
                    relative(blocked, root),
                    1,
                    (
                        f"Archived change '{canonical_archive_name(change.name)}' "
                        "still contains an active BLOCKED.md."
                    ),
                    "Confirm the entries were handled; the merge gate refuses to archive with unresolved ones.",
                )
            )
    return diagnostics


def clean_reference(raw: str) -> str | None:
    candidate = unquote(raw.strip())
    if candidate.startswith("<") and candidate.endswith(">"):
        candidate = candidate[1:-1]
    if " " in candidate:
        candidate = candidate.split(" ", 1)[0]
    candidate = candidate.split("#", 1)[0].strip().rstrip(".,;")
    candidate = LINE_SUFFIX_RE.sub("", candidate)
    if not candidate:
        return None
    if (
        candidate.startswith(("#", "/sdd:", "$"))
        or URL_RE.match(candidate)
        or candidate.startswith(("mailto:", "data:"))
        or any(char in candidate for char in "*?[]{}")
        or "<" in candidate
        or ">" in candidate
    ):
        return None
    if candidate.startswith("/") and not candidate.startswith(
        ABSOLUTE_REFERENCE_PREFIXES
    ):
        return None
    return candidate


def resolve_reference(candidate: str, source: Path, root: Path, markdown: bool) -> Path:
    path = Path(candidate)
    if path.is_absolute():
        return path
    if markdown:
        return source.parent / path
    return root / path


def is_archived_document(source: Path, root: Path) -> bool:
    """Archived changes are frozen history, so their references are frozen too."""
    return relative(source, root).startswith("sdd/changes/archive/")


def should_scan_inline(source: Path, root: Path) -> bool:
    relative_source = relative(source, root)
    return relative_source == "sdd/project.md" or relative_source.startswith(
        "sdd/specs/"
    )


def is_explicit_inline_path(candidate: str, root: Path) -> bool:
    if candidate.startswith("sdd/"):
        return True
    if candidate.startswith(ABSOLUTE_REFERENCE_PREFIXES):
        return True
    first_component = candidate.removeprefix("./").split("/", 1)[0]
    return "/" in candidate and (root / first_component).exists()


def reference_checks(root: Path, sdd: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int, str]] = set()
    for source in sorted(sdd.rglob("*.md")):
        if source == sdd / "roadmap.md":
            continue
        if is_archived_document(source, root):
            # An archived change is history and must not be rewritten, so a
            # reference that rotted after archiving has no available fix: the
            # suggested action would contradict the lifecycle rules.
            continue
        for line_number, line in enumerate(read_lines(source), start=1):
            if re.search(r"no existe|se crear[áa]|will be created", line, re.IGNORECASE):
                continue
            candidates: list[tuple[str, bool]] = [
                (match.group(1), True) for match in MARKDOWN_LINK_RE.finditer(line)
            ]
            if should_scan_inline(source, root):
                candidates.extend(
                    (match.group(1), False) for match in INLINE_CODE_RE.finditer(line)
                )
            for raw, markdown in candidates:
                candidate = clean_reference(raw)
                if not candidate:
                    continue
                if not markdown and not is_explicit_inline_path(candidate, root):
                    continue
                target = resolve_reference(candidate, source, root, markdown)
                key = (relative(source, root), line_number, candidate)
                if key in seen or target.exists():
                    continue
                seen.add(key)
                diagnostics.append(
                    Diagnostic(
                        "SDD008",
                        "WARNING",
                        relative(source, root),
                        line_number,
                        f"Local reference '{candidate}' does not exist.",
                        "Update the reference or restore the referenced path.",
                    )
                )
    return diagnostics


def duplicate_checks(
    root: Path,
    active_changes: list[Path],
    archives_by_feature: dict[str, list[Path]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for active in active_changes:
        archives = archives_by_feature.get(active.name, [])
        if not archives:
            continue
        archive_names = ", ".join(relative(path, root) for path in archives)
        diagnostics.append(
            Diagnostic(
                "SDD009",
                "ERROR",
                relative(active, root),
                0,
                (
                    f"Change '{active.name}' exists as both active and archived "
                    f"({archive_names})."
                ),
                "Keep exactly one representation and repair the roadmap pointer.",
            )
        )
    return diagnostics


def metadata_line(change: Path, key: str) -> int:
    for line_number, line in enumerate(read_lines(change / "STATE.md"), start=1):
        if line.startswith(f"{key}:"):
            return line_number
    return 1


def lifecycle_checks(
    root: Path,
    entries: list[RoadmapEntry],
    active_changes: list[Path],
    archived_changes: list[Path],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    checked_features = {entry.feature: entry for entry in entries if entry.checked}

    for change in active_changes:
        state_file = change / "STATE.md"
        if change.name in checked_features:
            entry = checked_features[change.name]
            diagnostics.append(
                Diagnostic(
                    "SDD012",
                    "ERROR",
                    "sdd/roadmap.md",
                    entry.line,
                    (
                        f"Active change '{change.name}' is marked definitively "
                        "complete in the roadmap."
                    ),
                    "Leave the roadmap unchecked until merge-gated archive completes.",
                )
            )
        if not state_file.is_file():
            continue
        try:
            data = read_state(change) or {}
        except LifecycleError as error:
            diagnostics.append(
                Diagnostic(
                    "SDD013",
                    "ERROR",
                    relative(state_file, root),
                    1,
                    f"Lifecycle metadata cannot be parsed: {error}",
                    "Repair STATE.md using the documented lifecycle fields.",
                )
            )
            continue

        state = data.get("state", "")
        if state not in STATES or state == "ARCHIVED":
            diagnostics.append(
                Diagnostic(
                    "SDD014",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "state"),
                    f"Lifecycle state '{state}' is incompatible with an active change.",
                    "Use a valid active state or complete the merge-gated archive.",
                )
            )

        # PR_OPEN asserts a Pull Request exists, so it always needs PR metadata.
        # MERGED/ARCHIVED may instead be proven by local git evidence.
        requires_pr = state == "PR_OPEN" or (
            state in {"MERGED", "ARCHIVED"}
            and data.get("merge_evidence") not in LOCAL_MERGE_EVIDENCE
        )
        missing = [field for field in PR_FIELDS if not data.get(field)]
        valid_url = bool(PR_URL_RE.match(data.get("pr_url", "")))
        valid_number = data.get("pr_number", "").isdigit()
        if requires_pr and (missing or not valid_url or not valid_number):
            detail = f"missing {', '.join(missing)}" if missing else "invalid PR URL/number"
            diagnostics.append(
                Diagnostic(
                    "SDD013",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "pr_url"),
                    f"PR evidence is incomplete or invalid ({detail}).",
                    "Record the PR again from objective gh output.",
                )
            )
        elif state in {"MERGED", "ARCHIVED"} and data.get(
            "merge_evidence"
        ) in LOCAL_MERGE_EVIDENCE:
            absent = [
                field for field in LOCAL_EVIDENCE_FIELDS if not data.get(field)
            ]
            if absent:
                diagnostics.append(
                    Diagnostic(
                        "SDD013",
                        "ERROR",
                        relative(state_file, root),
                        metadata_line(change, "implementation_sha"),
                        (
                            "Local merge evidence is incomplete "
                            f"(missing {', '.join(absent)})."
                        ),
                        "Re-verify the merge with /sdd:archive; never fill it in by hand.",
                    )
                )

        has_pr_evidence = any(
            data.get(field) for field in ("pr_url", "pr_number", "pr_state", "merge_sha")
        )
        # A GitHub repository is not required to be ready: repos with no remote,
        # or a non-GitHub one, prove their merge through git instead. What must
        # always be recorded is the branch identity and the reviewed commit.
        ready_identity_missing = state == "READY_FOR_PR" and any(
            not data.get(field) for field in LOCAL_EVIDENCE_FIELDS
        )
        incompatible = (
            data.get("schema") != "1"
            or (
                state in {"ACTIVE", "LOCAL_VERIFIED", "READY_FOR_PR"}
                and has_pr_evidence
            )
            or ready_identity_missing
            or (state == "ACTIVE" and data.get("local_review") != "PENDING")
            or (state == "LOCAL_VERIFIED" and data.get("local_review") != "APPROVED")
            or (state == "READY_FOR_PR" and data.get("local_review") != "APPROVED")
            or (state == "PR_OPEN" and data.get("pr_state") not in {"", "OPEN"})
            or (
                state == "MERGED"
                and (
                    # Merge is proven either by a MERGED PR or by local git
                    # evidence (merge_evidence: ancestor / equivalent), which
                    # has no PR fields at all.
                    (
                        bool(data.get("pr_url") or data.get("pr_state"))
                        if data.get("merge_evidence") in {"ancestor", "equivalent"}
                        else data.get("pr_state") != "MERGED"
                    )
                    or not SHA_RE.match(data.get("merge_sha", ""))
                )
            )
        )
        if incompatible:
            diagnostics.append(
                Diagnostic(
                    "SDD014",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "state"),
                    f"Lifecycle fields are incompatible with state '{state}'.",
                    "Re-run the appropriate lifecycle command; do not edit remote evidence by hand.",
                )
            )
        if state == "PR_OPEN" and (
            data.get("pr_state") == "MERGED" or data.get("merge_sha")
        ):
            diagnostics.append(
                Diagnostic(
                    "SDD015",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "state"),
                    "Merge evidence exists while the change remains PR_OPEN.",
                    "Run /sdd:archive to verify merge and advance the lifecycle.",
                )
            )

        # Everything from READY_FOR_PR onwards asserts the local gates passed.
        # The lifecycle enforces them when it writes the state and never looks
        # again, so a task unchecked later — or a blocker raised after review —
        # leaves STATE.md claiming something that stopped being true.
        if state in {"READY_FOR_PR", "PR_OPEN", "MERGED"}:
            tasks = change / "tasks.md"
            if not tasks.is_file():
                diagnostics.append(
                    Diagnostic(
                        "SDD016",
                        "ERROR",
                        relative(change, root),
                        0,
                        f"State '{state}' asserts completed tasks, but tasks.md is missing.",
                        "Restore tasks.md, or move the change back with the lifecycle commands.",
                    )
                )
            else:
                pending = open_tasks_not_carried(change)
                if pending:
                    diagnostics.append(
                        Diagnostic(
                            "SDD016",
                            "ERROR",
                            relative(tasks, root),
                            pending[0],
                            (
                                f"State '{state}' asserts every task is complete, but "
                                f"{len(pending)} remain unchecked."
                            ),
                            "Finish the work and re-run /sdd:review, or correct tasks.md.",
                        )
                    )
            # `deferred` and `assumed` entries travel with the PR (ADR 0006); only
            # an entry that needs a human contradicts a certified state.
            blocked = active_blocked_file(change)
            if blocked and any(entry.blocks_locally for entry in blocked_entries(change)):
                diagnostics.append(
                    Diagnostic(
                        "SDD017",
                        "ERROR",
                        relative(blocked, root),
                        1,
                        (
                            f"State '{state}' coexists with unresolved entries in "
                            "BLOCKED.md."
                        ),
                        "Resolve the queue entries before the change advances any further.",
                    )
                )

    for change in archived_changes:
        state_file = change / "STATE.md"
        if not state_file.is_file():
            continue
        try:
            data = read_state(change) or {}
        except LifecycleError as error:
            diagnostics.append(
                Diagnostic(
                    "SDD013",
                    "ERROR",
                    relative(state_file, root),
                    1,
                    f"Lifecycle metadata cannot be parsed: {error}",
                    "Repair STATE.md without inventing merge evidence.",
                )
            )
            continue
        state = data.get("state", "")
        if state == "READY_FOR_PR":
            diagnostics.append(
                Diagnostic(
                    "SDD011",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "state"),
                    "READY_FOR_PR change is already located in archive.",
                    "Restore it to active changes until its PR is merged.",
                )
            )
        elif state != "ARCHIVED":
            diagnostics.append(
                Diagnostic(
                    "SDD014",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "state"),
                    f"Archived change has incompatible lifecycle state '{state}'.",
                    "Restore the active change or record a verified ARCHIVED state.",
                )
            )
        missing = [field for field in PR_FIELDS if not data.get(field)]
        if data.get("merge_evidence") in LOCAL_MERGE_EVIDENCE:
            # Archived through git evidence: the proof is the recorded base/head/
            # implementation SHA plus the base commit that carried the change.
            proven = all(data.get(field) for field in LOCAL_EVIDENCE_FIELDS) and not (
                data.get("pr_url") or data.get("pr_state")
            )
        else:
            proven = (
                data.get("pr_state") == "MERGED"
                and not missing
                and bool(PR_URL_RE.match(data.get("pr_url", "")))
            )
        complete_merge = (
            data.get("local_review") == "APPROVED"
            and bool(SHA_RE.match(data.get("merge_sha", "")))
            and proven
        )
        if state_file.is_file() and not complete_merge:
            diagnostics.append(
                Diagnostic(
                    "SDD010",
                    "ERROR",
                    relative(state_file, root),
                    metadata_line(change, "merge_sha"),
                    "Archived lifecycle-managed change lacks complete merge evidence.",
                    "Restore it and complete merge-gated archive; never invent evidence.",
                )
            )
    return diagnostics


def diagnose(root: Path) -> list[Diagnostic]:
    root = root.resolve()
    sdd = root / "sdd"
    if not sdd.is_dir():
        return [
            Diagnostic(
                "SDD000",
                "ERROR",
                "sdd",
                0,
                "No SDD state directory was found.",
                "Run /sdd:init or pass --root for an initialized project.",
            )
        ]

    changes = sdd / "changes"
    archive = changes / "archive"
    active_changes = (
        sorted(
            path
            for path in changes.iterdir()
            if path.is_dir() and path.name != "archive"
        )
        if changes.is_dir()
        else []
    )
    archived_changes = (
        sorted(path for path in archive.iterdir() if path.is_dir())
        if archive.is_dir()
        else []
    )
    archives_by_feature: dict[str, list[Path]] = {}
    for archived in archived_changes:
        archives_by_feature.setdefault(
            canonical_archive_name(archived.name), []
        ).append(archived)

    diagnostics: list[Diagnostic] = []
    roadmap = sdd / "roadmap.md"
    roadmap_entries = parse_roadmap(roadmap) if roadmap.is_file() else []
    if roadmap_entries:
        diagnostics.extend(
            pointer_checks(root, roadmap, roadmap_entries, archives_by_feature)
        )
        diagnostics.extend(graph_checks(root, roadmap))
        diagnostics.extend(roadmap_size_checks(root, roadmap))
    diagnostics.extend(steering_size_checks(root, sdd))
    diagnostics.extend(reviewer_metadata_checks(root))
    diagnostics.extend(mcp_config_checks(root))
    diagnostics.extend(worktree_checks(root))
    diagnostics.extend(active_document_checks(root, active_changes))
    diagnostics.extend(requirement_checks(root, active_changes + archived_changes))
    diagnostics.extend(archive_checks(root, archived_changes))
    diagnostics.extend(reference_checks(root, sdd))
    diagnostics.extend(duplicate_checks(root, active_changes, archives_by_feature))
    diagnostics.extend(
        lifecycle_checks(root, roadmap_entries, active_changes, archived_changes)
    )

    severity_order = {"ERROR": 0, "WARNING": 1}
    return sorted(
        diagnostics,
        key=lambda item: (
            severity_order[item.severity],
            item.code,
            item.file,
            item.line,
            item.explanation,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate SDD state without modifying the project."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing sdd/ (default: current directory).",
    )
    args = parser.parse_args(argv)

    diagnostics = diagnose(args.root)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = sum(item.severity == "ERROR" for item in diagnostics)
    warnings = sum(item.severity == "WARNING" for item in diagnostics)
    print(f"sdd doctor: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
