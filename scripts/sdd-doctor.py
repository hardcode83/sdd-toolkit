#!/usr/bin/env python3
"""Read-only consistency checks for an SDD project."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


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


def archive_checks(root: Path, archived_changes: list[Path]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for change in archived_changes:
        tasks = change / "tasks.md"
        if tasks.is_file():
            pending: list[int] = []
            for line_number, line in enumerate(read_lines(tasks), start=1):
                match = TASK_RE.match(line)
                if match and match.group(1) == " ":
                    pending.append(line_number)
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
                        "Verify the work and document whether archive debt was explicitly accepted.",
                    )
                )
        blocked = change / "BLOCKED.md"
        if blocked.is_file() and blocked.read_text(
            encoding="utf-8", errors="replace"
        ).strip():
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
                    "Resolve the entries or document the explicit archive-with-debt override.",
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
    if roadmap.is_file():
        diagnostics.extend(
            pointer_checks(root, roadmap, parse_roadmap(roadmap), archives_by_feature)
        )
    diagnostics.extend(active_document_checks(root, active_changes))
    diagnostics.extend(requirement_checks(root, active_changes + archived_changes))
    diagnostics.extend(archive_checks(root, archived_changes))
    diagnostics.extend(reference_checks(root, sdd))
    diagnostics.extend(duplicate_checks(root, active_changes, archives_by_feature))

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
