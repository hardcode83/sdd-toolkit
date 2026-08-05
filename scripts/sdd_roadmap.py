#!/usr/bin/env python3
"""Roadmap graph: parse the index, validate it, and derive execution order.

The roadmap is a hand-edited markdown index (see templates/roadmap-template.md):
one `- [ ]` line per entry, optionally followed by an indented metadata sub-line
declaring its relations to other entries. Everything this module produces —
frontier, waves, critical path, diagrams — is *derived*: nothing here is ever
written back to the roadmap, because derived state duplicated into a shared file
is what made concurrent work conflict in the first place (ADR 0001, D5/D7).

Legacy flat roadmaps (no stages, no metadata) parse fine and simply produce a
single wave: with no declared edges, every open entry is in the frontier.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from sdd_lifecycle import LifecycleError, read_state


# Same shape both other parsers accept, so a roadmap stays readable by all three.
ENTRY_RE = re.compile(r"^\s*-\s+\[(?P<checked>[ xX])\]\s+(?P<body>.+?)\s*$")
STAGE_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
# A metadata sub-line is indented and does NOT open a list item. Requiring the
# indent is what keeps prose paragraphs from being read as metadata.
META_LINE_RE = re.compile(r"^\s+(?P<body>\S.*?)\s*$")
META_FIELD_RE = re.compile(r"^(?P<key>[a-z][a-z-]*)\s*:\s*(?P<value>.*)$")
CHANGE_POINTER_RE = re.compile(
    r"(?P<path>(?:sdd/)?changes/(?:archive/)?[A-Za-z0-9._-]+/?)"
)
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
# Fields separated by a middle dot. `,` is reserved for lists inside one field
# and `:` for the key, so free text (deferred-until) survives both.
FIELD_SEPARATOR = "·"

# Relations that order two entries: the referenced entry must close first. They
# differ only in what they mean to the reader, so all four constrain the graph.
EDGE_KEYS = ("needs", "completes", "informs-from", "inherits-from")
# `needs` is a hard dependency (it needs something the other creates); the rest
# are ordering relations. Rendered differently, treated the same for ordering.
HARD_EDGE_KEYS = ("needs",)
CLASSIFIER_KEYS = ("size", "kind")
# Free text, not an edge: an external trigger, not another entry.
TEXT_KEYS = ("deferred-until",)
KNOWN_KEYS = frozenset(EDGE_KEYS + CLASSIFIER_KEYS + TEXT_KEYS)
SIZES = ("S", "M", "L")
KINDS = ("feature", "fix", "spike", "infra", "tech", "adr")
# Critical path weights. An absent size counts as M so one unlabelled entry
# cannot make a chain look cheaper than it is.
SIZE_WEIGHT = {"S": 1, "M": 2, "L": 3}
DEFAULT_WEIGHT = 2
# Views stay scannable: the full text lives in the roadmap and its per-entry note.
SUMMARY_LIMIT = 110

# Lifecycle state → the symbol /sdd:status already uses for it.
STATE_SYMBOL = {
    "ARCHIVED": "✔",
    "MERGED": "✔",
    "PR_OPEN": "PR",
    "READY_FOR_PR": "✓",
    "LOCAL_VERIFIED": "✓",
    "ACTIVE": "▶",
    "CANCELLED": "✗",
}
PENDING_SYMBOL = "·"
BLOCKED_SYMBOL = "⛔"
ARCHIVE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<feature>.+)$")


class RoadmapError(RuntimeError):
    """Actionable roadmap failure."""


@dataclass
class Entry:
    feature: str
    line: int
    checked: bool
    body: str
    stage: str = ""
    stage_line: int = 0
    meta_line: int = 0
    edges: dict[str, tuple[str, ...]] = field(default_factory=dict)
    size: str = ""
    kind: str = ""
    deferred_until: str = ""
    unknown_keys: tuple[str, ...] = ()
    pointer: str | None = None

    @property
    def summary(self) -> str:
        """The entry's one-line description, without the feature name."""
        text = self.body.split("→", 1)[0]
        parts = re.split(r"\s+—\s+", text, maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    @property
    def predecessors(self) -> tuple[str, ...]:
        seen: list[str] = []
        for key in EDGE_KEYS:
            for target in self.edges.get(key, ()):
                if target not in seen:
                    seen.append(target)
        return tuple(seen)

    @property
    def weight(self) -> int:
        return SIZE_WEIGHT.get(self.size, DEFAULT_WEIGHT)


@dataclass(frozen=True)
class Finding:
    """A roadmap problem, in the shape sdd-doctor.py turns into a Diagnostic."""

    code: str
    severity: str
    line: int
    explanation: str
    action: str


def entry_feature(body: str) -> str:
    """The feature name: everything before the pointer or the summary dash.

    Mirrors sdd_lifecycle.roadmap_feature so all three parsers agree on identity.
    """
    text = body.split("→", 1)[0]
    text = re.split(r"\s+—\s+|\s+-\s+", text, maxsplit=1)[0]
    return text.strip().strip("`")


def parse_metadata(entry: Entry, body: str) -> None:
    """Fill an entry from its metadata sub-line. Unknown keys are recorded, never
    guessed at: a silent typo (`need:`) would park an entry forever."""
    unknown: list[str] = []
    separator = FIELD_SEPARATOR if FIELD_SEPARATOR in body else ";"
    for chunk in body.split(separator):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = META_FIELD_RE.match(chunk)
        if not match:
            continue
        key = match.group("key")
        value = match.group("value").strip()
        if key in EDGE_KEYS:
            targets = tuple(
                item.strip().strip("`") for item in value.split(",") if item.strip()
            )
            if targets:
                entry.edges[key] = entry.edges.get(key, ()) + targets
        elif key == "size":
            entry.size = value.strip().upper()
        elif key == "kind":
            entry.kind = value.strip().lower()
        elif key == "deferred-until":
            entry.deferred_until = value
        else:
            unknown.append(key)
    if unknown:
        entry.unknown_keys = entry.unknown_keys + tuple(unknown)


def metadata_like(key: str) -> bool:
    """A known key, or a near miss of one (`need`, `sizes`, `deferred`).

    Near misses have to count, or the typo-protection warning could never fire:
    a sub-line whose only key is misspelled would be classified as prose and
    skipped, which is exactly the silent no-op the check exists to catch.
    """
    return any(
        key == known or known.startswith(key) or key.startswith(known)
        for known in KNOWN_KEYS
    )


def is_metadata(body: str) -> bool:
    """True when an indented line declares roadmap metadata rather than prose.

    Two conditions, both needed: every field is shaped `key: value`, and at least
    one key is recognisable. The first rejects prose; the second stops an
    incidental `https://…` or `nota: …` from being read as metadata.
    """
    separator = FIELD_SEPARATOR if FIELD_SEPARATOR in body else ";"
    chunks = [chunk.strip() for chunk in body.split(separator) if chunk.strip()]
    if not chunks:
        return False
    matches = [META_FIELD_RE.match(chunk) for chunk in chunks]
    if not all(matches):
        return False
    return any(metadata_like(match.group("key")) for match in matches if match)


def parse_roadmap(path: Path) -> list[Entry]:
    """Parse the roadmap index. Tolerant by design: anything that is not an entry,
    a stage heading or a metadata sub-line is prose and gets skipped."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise RoadmapError(f"Could not read {path}: {error}") from error

    entries: list[Entry] = []
    stage = ""
    stage_line = 0
    current: Entry | None = None
    in_comment = False

    for number, line in enumerate(lines, start=1):
        # HTML comments carry the template's own legend, which looks exactly like
        # metadata. Skipping them is what lets the template ship its own docs.
        if in_comment:
            if COMMENT_CLOSE in line:
                in_comment = False
            continue
        if COMMENT_OPEN in line and COMMENT_CLOSE not in line:
            in_comment = True
            continue

        stage_match = STAGE_RE.match(line)
        if stage_match:
            stage = stage_match.group("title").strip()
            stage_line = number
            current = None
            continue

        entry_match = ENTRY_RE.match(line)
        if entry_match:
            body = entry_match.group("body")
            pointer_match = CHANGE_POINTER_RE.search(body)
            current = Entry(
                feature=entry_feature(body),
                line=number,
                checked=entry_match.group("checked").lower() == "x",
                body=body,
                stage=stage,
                stage_line=stage_line,
                pointer=(
                    pointer_match.group("path").rstrip("/") if pointer_match else None
                ),
            )
            entries.append(current)
            continue

        meta_match = META_LINE_RE.match(line)
        if current is not None and meta_match and is_metadata(meta_match.group("body")):
            parse_metadata(current, meta_match.group("body"))
            if not current.meta_line:
                current.meta_line = number
            continue

        # Anything else (blank line, prose, a new heading level) closes the
        # window in which a sub-line can still belong to the previous entry.
        current = None

    return entries


def stage_goal(stage: str) -> str:
    """The outcome half of a `Stage N — <goal>` heading, empty when absent."""
    parts = re.split(r"\s+—\s+", stage, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def archived_features(root: Path) -> set[str]:
    archive = root / "sdd" / "changes" / "archive"
    if not archive.is_dir():
        return set()
    found: set[str] = set()
    for path in archive.iterdir():
        if not path.is_dir():
            continue
        match = ARCHIVE_NAME_RE.match(path.name)
        found.add(match.group("feature") if match else path.name)
    return found


def entry_status(root: Path, entry: Entry, archived: set[str]) -> str:
    """Derived state for an entry — never read from the roadmap itself (D5).

    Precedence: an archive on disk outranks a stale STATE.md, and a non-empty
    BLOCKED.md outranks the lifecycle state because it is what needs a human.
    """
    if entry.feature in archived:
        return "ARCHIVED"
    change = root / "sdd" / "changes" / entry.feature
    if not change.is_dir():
        return "ARCHIVED" if entry.checked else "PENDING"
    blocked = change / "BLOCKED.md"
    if blocked.is_file() and blocked.read_text(encoding="utf-8", errors="replace").strip():
        return "BLOCKED"
    try:
        state = read_state(change)
    except LifecycleError:
        state = None
    if state and state.get("state"):
        return state["state"]
    return "ACTIVE"


def status_symbol(status: str) -> str:
    if status == "BLOCKED":
        return BLOCKED_SYMBOL
    return STATE_SYMBOL.get(status, PENDING_SYMBOL)


def is_closed(status: str, entry: Entry) -> bool:
    """Closed = it can no longer block a successor. Only an archived (or merged)
    change qualifies: READY_FOR_PR still has no merged code behind it."""
    return status in {"ARCHIVED", "MERGED"} or entry.checked


class Graph:
    """The roadmap as a DAG, with the derived views built on top of it."""

    def __init__(self, root: Path, entries: list[Entry]) -> None:
        self.root = root
        self.entries = entries
        self.by_feature: dict[str, Entry] = {}
        self.duplicates: list[Entry] = []
        for entry in entries:
            if entry.feature in self.by_feature:
                self.duplicates.append(entry)
            else:
                self.by_feature[entry.feature] = entry
        archived = archived_features(root)
        # Keyed by feature over the DEDUPED set, so a duplicate entry can never
        # make the views disagree with the graph: `by_feature` keeps the first
        # occurrence, and so does everything derived from it. The duplicate is a
        # validation error (SDD018), not a second node.
        self.status = {
            entry.feature: entry_status(root, entry, archived)
            for entry in self.by_feature.values()
        }
        self.closed = {
            entry.feature: is_closed(self.status[entry.feature], entry)
            for entry in self.by_feature.values()
        }

    # --- structure -----------------------------------------------------------

    def nodes(self) -> list[Entry]:
        """The graph's entries, one per feature, in roadmap order."""
        return list(self.by_feature.values())

    def known_predecessors(self, entry: Entry) -> tuple[str, ...]:
        return tuple(t for t in entry.predecessors if t in self.by_feature)

    def unknown_predecessors(self, entry: Entry) -> tuple[str, ...]:
        return tuple(t for t in entry.predecessors if t not in self.by_feature)

    def open_entries(self) -> list[Entry]:
        return [e for e in self.nodes() if not self.closed[e.feature]]

    def cancelled(self) -> list[Entry]:
        return [e for e in self.open_entries() if self.status[e.feature] == "CANCELLED"]

    def schedulable(self) -> list[Entry]:
        """Open entries that are candidates for ordering.

        Two exclusions, both because scheduling them would be a false claim:
        deferred entries wait on an external condition, and cancelled ones are
        not going to be built at all. Note that neither counts as *closed*
        either — a cancelled predecessor keeps blocking its successors, since
        whatever it was going to create still will not exist. If the dependency
        turned out to be unnecessary, the fix is the metadata.
        """
        return [
            e
            for e in self.open_entries()
            if not e.deferred_until and self.status[e.feature] != "CANCELLED"
        ]

    def in_stage(self, entry: Entry, stage: str | None) -> bool:
        """Substring match so `--stage 2` finds `## Stage 2 — <goal>`."""
        if stage is None:
            return True
        return stage.lower() in entry.stage.lower()

    def cycles(self) -> list[tuple[str, ...]]:
        """Every dependency cycle in the graph.

        Iterative DFS with an explicit stack and the classic white/grey/black
        colouring: a roadmap is hand-edited, so a recursion limit must never be
        what reports the problem. Each cycle is rotated to start at its smallest
        feature name, so the same cycle reported from two entry points dedupes.
        """
        white, grey, black = 0, 1, 2
        colour = {feature: white for feature in self.by_feature}
        found: list[tuple[str, ...]] = []
        for start in self.by_feature:
            if colour[start] != white:
                continue
            colour[start] = grey
            stack: list[list] = [[start, 0]]
            path: list[str] = [start]
            while stack:
                node, index = stack[-1]
                targets = self.known_predecessors(self.by_feature[node])
                if index < len(targets):
                    stack[-1][1] += 1
                    target = targets[index]
                    if colour[target] == grey:
                        cycle = path[path.index(target):]
                        pivot = cycle.index(min(cycle))
                        rotated = tuple(cycle[pivot:] + cycle[:pivot])
                        if rotated not in found:
                            found.append(rotated)
                    elif colour[target] == white:
                        colour[target] = grey
                        stack.append([target, 0])
                        path.append(target)
                else:
                    colour[node] = black
                    stack.pop()
                    path.pop()
        return found

    def topological(self, scope: list[Entry]) -> list[Entry]:
        """`scope` in dependency-first order, then whatever a cycle left over.

        Needed because a dependency may be declared *later* in the file than the
        entry that needs it: file order is not a valid order for the DP below.
        """
        pending = {e.feature: e for e in scope}
        placed: set[str] = set()
        ordered: list[Entry] = []
        while pending:
            level = [
                entry
                for entry in pending.values()
                if all(
                    t in placed
                    for t in self.known_predecessors(entry)
                    if t in pending or t in placed
                )
            ]
            if not level:
                break
            level.sort(key=lambda e: e.line)
            for entry in level:
                del pending[entry.feature]
                placed.add(entry.feature)
                ordered.append(entry)
        ordered.extend(sorted(pending.values(), key=lambda e: e.line))
        return ordered

    # --- derived views -------------------------------------------------------

    def frontier(self) -> list[Entry]:
        """Open entries with every predecessor closed and no deferral.

        This is the set that can be worked in parallel — the input /sdd:auto and
        worktree isolation need. An unknown predecessor blocks conservatively:
        silently ignoring a typo would be worse than parking the entry visibly.
        """
        ready: list[Entry] = []
        for entry in self.schedulable():
            if self.unknown_predecessors(entry):
                continue
            if all(self.closed.get(t, False) for t in self.known_predecessors(entry)):
                ready.append(entry)
        return ready

    def deferred(self) -> list[Entry]:
        return [e for e in self.open_entries() if e.deferred_until]

    def waves(self) -> list[list[Entry]]:
        """Schedulable entries in topological levels: wave N needs wave N-1 closed.

        Wave 1 is exactly `frontier()` — that invariant is what makes the view
        trustworthy. Entries left over after the last wave are in a cycle or
        blocked by an unknown predecessor; `validate` reports those, so they are
        deliberately not scheduled here rather than being silently placed.
        """
        pending = {e.feature: e for e in self.schedulable()}
        resolved = {f for f, closed in self.closed.items() if closed}
        levels: list[list[Entry]] = []
        while pending:
            level = [
                entry
                for entry in pending.values()
                if not self.unknown_predecessors(entry)
                and all(t in resolved for t in self.known_predecessors(entry))
            ]
            if not level:
                break
            level.sort(key=lambda e: e.line)
            levels.append(level)
            for entry in level:
                del pending[entry.feature]
                resolved.add(entry.feature)
        return levels

    def successors(self, feature: str) -> tuple[str, ...]:
        """Open entries waiting on this one — what closing it would unblock."""
        return tuple(
            entry.feature
            for entry in self.open_entries()
            if feature in entry.predecessors
        )

    def leaves(self) -> list[Entry]:
        """Schedulable entries with no edges in either direction — order is free.

        Kept as its own view because drawing a one-level tree over these would
        fake information that does not exist (ADR 0001, D7). In the report it
        surfaces as an `independiente` annotation rather than a second list, so
        the same entry is never printed twice.
        """
        return [
            entry
            for entry in self.schedulable()
            if not entry.predecessors and not self.successors(entry.feature)
        ]

    def critical_path(self, stage: str | None = None) -> list[Entry]:
        """The heaviest chain of open entries, weighted by `size`.

        Answers "what is the long pole to finishing this stage" — the chain that
        cannot be shortened by working in parallel.
        """
        scope = [e for e in self.schedulable() if self.in_stage(e, stage)]
        allowed = {e.feature for e in scope}
        best_cost: dict[str, int] = {}
        best_path: dict[str, list[Entry]] = {}

        # Dependency-first order, not file order: a predecessor may be declared
        # further down the roadmap than the entry that needs it.
        for entry in self.topological(scope):
            cost = entry.weight
            path = [entry]
            for target in self.known_predecessors(entry):
                if target not in allowed or target not in best_cost:
                    continue
                if best_cost[target] + entry.weight > cost:
                    cost = best_cost[target] + entry.weight
                    path = best_path[target] + [entry]
            best_cost[entry.feature] = cost
            best_path[entry.feature] = path

        if not best_cost:
            return []
        heaviest = max(best_cost, key=lambda f: (best_cost[f], -best_path[f][0].line))
        return best_path[heaviest]

    def stages(self) -> list[str]:
        seen: list[str] = []
        for entry in self.nodes():
            if entry.stage not in seen:
                seen.append(entry.stage)
        return seen

    def has_edges(self, stage: str | None = None) -> bool:
        return any(
            self.known_predecessors(e)
            for e in self.nodes()
            if self.in_stage(e, stage)
        )

    # --- validation ----------------------------------------------------------

    def validate(self) -> list[Finding]:
        findings: list[Finding] = []

        for entry in self.duplicates:
            findings.append(
                Finding(
                    "SDD018",
                    "ERROR",
                    entry.line,
                    f"Roadmap declares '{entry.feature}' more than once.",
                    "Keep one entry per feature; merge or rename the duplicate.",
                )
            )

        # Graph-shaped findings iterate the deduped nodes, so a duplicated entry
        # does not report the same broken edge twice; the per-line findings below
        # iterate every parsed line, because a typo is a property of the line.
        for entry in self.nodes():
            for target in self.unknown_predecessors(entry):
                findings.append(
                    Finding(
                        "SDD019",
                        "ERROR",
                        entry.meta_line or entry.line,
                        (
                            f"Entry '{entry.feature}' depends on '{target}', which is "
                            "not a roadmap entry."
                        ),
                        "Fix the feature name or add the missing entry.",
                    )
                )

        for cycle in self.cycles():
            findings.append(
                Finding(
                    "SDD020",
                    "ERROR",
                    self.by_feature[cycle[0]].line,
                    f"Dependency cycle between: {' → '.join(cycle)}.",
                    "Break the cycle: split one entry or drop the weaker relation.",
                )
            )

        # The check that catches real mistakes: something shipped before what it
        # declared it depended on. Either the order was wrong or the metadata is.
        for entry in self.nodes():
            if not self.closed[entry.feature]:
                continue
            for target in self.known_predecessors(entry):
                if self.closed.get(target):
                    continue
                findings.append(
                    Finding(
                        "SDD021",
                        "ERROR",
                        entry.line,
                        (
                            f"'{entry.feature}' is closed but its dependency "
                            f"'{target}' is still open."
                        ),
                        "Close the dependency, or correct the declared relation.",
                    )
                )

        for entry in self.entries:
            for key in entry.unknown_keys:
                findings.append(
                    Finding(
                        "SDD022",
                        "WARNING",
                        entry.meta_line or entry.line,
                        f"Entry '{entry.feature}' declares unknown metadata '{key}'.",
                        f"Use one of: {', '.join(sorted(KNOWN_KEYS))}.",
                    )
                )
            if entry.size and entry.size not in SIZES:
                findings.append(
                    Finding(
                        "SDD022",
                        "WARNING",
                        entry.meta_line or entry.line,
                        f"Entry '{entry.feature}' has invalid size '{entry.size}'.",
                        f"Use one of: {', '.join(SIZES)}.",
                    )
                )
            if entry.kind and entry.kind not in KINDS:
                findings.append(
                    Finding(
                        "SDD022",
                        "WARNING",
                        entry.meta_line or entry.line,
                        f"Entry '{entry.feature}' has invalid kind '{entry.kind}'.",
                        f"Use one of: {', '.join(KINDS)}.",
                    )
                )

        # A stage is an outcome to reach; without a goal it is just a bucket.
        reported: set[int] = set()
        for entry in self.entries:
            if not entry.stage or entry.stage_line in reported:
                continue
            if not stage_goal(entry.stage):
                reported.add(entry.stage_line)
                findings.append(
                    Finding(
                        "SDD023",
                        "WARNING",
                        entry.stage_line,
                        f"Stage '{entry.stage}' declares no outcome.",
                        "Name what exists once the stage closes: `## Stage N — <goal>`.",
                    )
                )

        return sorted(findings, key=lambda f: (f.line, f.code))


# --- rendering ---------------------------------------------------------------


def diagram_nodes(
    graph: Graph, stage: str | None = None, include_all: bool = False
) -> list[Entry]:
    """What the diagram should show: open work, plus the closed entries it waits on.

    A mature roadmap is mostly history — in a real project this was 52 nodes of
    which 31 were archived, carrying 5 edges. Dumping all of it buries the part
    that is still actionable, so closed entries appear only when an open one
    still points at them (useful: it says the blocker is already done).
    `include_all` restores the full picture for auditing.
    """
    scoped = [e for e in graph.nodes() if graph.in_stage(e, stage)]
    if include_all:
        return scoped
    open_scoped = [e for e in scoped if not graph.closed[e.feature]]
    keep = {e.feature for e in open_scoped}
    for entry in open_scoped:
        keep.update(graph.known_predecessors(entry))
    return [e for e in scoped if e.feature in keep]


def mermaid_link(diagram: str) -> str:
    """A mermaid.live URL that renders `diagram`.

    The whole diagram travels inside the URL fragment (deflated, then
    base64url) — mermaid.live decodes it client-side, so nothing is uploaded by
    generating the link. Opening it does send it to that site, which is why the
    caller is told the link carries the content.
    """
    state = json.dumps(
        {"code": diagram, "mermaid": {"theme": "default"}, "autoSync": True},
        ensure_ascii=False,
    )
    packed = zlib.compress(state.encode("utf-8"), 9)
    return "https://mermaid.live/edit#pako:" + base64.urlsafe_b64encode(
        packed
    ).decode("ascii").rstrip("=")


def render_text_graph(graph: Graph, stage: str | None = None) -> list[str]:
    """The dependency graph as terminal text, laid out by wave.

    Deliberately not ASCII art: the graph is a DAG, and drawing crossing edges
    in characters is unreadable well before it is useful. Instead each entry
    names what it waits on and what it unblocks, which is the same information
    an arrow would carry and survives any number of parents.
    """
    waves = graph.waves()
    scoped = [[e for e in level if graph.in_stage(e, stage)] for level in waves]
    scoped = [level for level in scoped if level]
    if not scoped:
        return []

    width = max(len(e.feature) for level in scoped for e in level)
    out: list[str] = []
    for index, level in enumerate(scoped, start=1):
        header = "se puede empezar ya" if index == 1 else f"tras la ola {index - 1}"
        out.append(f"Ola {index} · {header}")
        for entry in level:
            tags = " · ".join(t for t in (entry.size, entry.kind) if t)
            label = f"  {status_symbol(graph.status[entry.feature])} {entry.feature:<{width}}"
            if tags:
                label += f"  ({tags})"
            out.append(label)
            waiting = [
                f"{target}{' ✔' if graph.closed.get(target) else ''}"
                for target in graph.known_predecessors(entry)
            ]
            if waiting:
                out.append(f"      ◂ necesita  {', '.join(waiting)}")
            unblocks = graph.successors(entry.feature)
            if unblocks:
                out.append(f"      ▸ desbloquea {', '.join(unblocks)}")
        out.append("")
    return out


def mermaid(
    graph: Graph, stage: str | None = None, include_all: bool = False
) -> str:
    """A flowchart of the open graph. Emitted as source, not a rendered image:
    a fenced ```mermaid block renders in GitHub and markdown viewers with zero
    dependencies, which is what makes it usable inside an unattended run."""
    scope = diagram_nodes(graph, stage, include_all)
    if not scope:
        return ""
    lines = ["flowchart TD"]
    ids = {e.feature: f"n{index}" for index, e in enumerate(scope)}
    for entry in scope:
        status = graph.status[entry.feature]
        label = f"{status_symbol(status)} {entry.feature}"
        if entry.size:
            label += f" ({entry.size})"
        shape = f'["{label}"]' if not entry.deferred_until else f'("{label}")'
        lines.append(f"    {ids[entry.feature]}{shape}")
    for entry in scope:
        for key in EDGE_KEYS:
            for target in entry.edges.get(key, ()):
                if target not in ids:
                    continue
                # Hard dependencies solid, ordering relations dashed and labelled.
                arrow = "-->" if key in HARD_EDGE_KEYS else f"-.->|{key}|"
                lines.append(f"    {ids[target]} {arrow} {ids[entry.feature]}")
    return "\n".join(lines)


def shorten(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """One scannable line. Legacy roadmaps carry multi-KB bodies in this field,
    and a view that reprints them is a view nobody reads."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def render_entry(graph: Graph, entry: Entry, annotate: bool = False) -> str:
    parts = [f"{status_symbol(graph.status[entry.feature])} {entry.feature}"]
    tags = [t for t in (entry.size, entry.kind) if t]
    if tags:
        parts.append(f"({' · '.join(tags)})")
    summary = shorten(entry.summary)
    if summary:
        parts.append(f"— {summary}")
    if annotate:
        # What closing this entry buys. The point of the frontier is choosing
        # among several workable entries, and "unblocks 2" is the deciding fact.
        unblocks = len(graph.successors(entry.feature))
        parts.append(f"[desbloquea {unblocks}]" if unblocks else "[independiente]")
    return " ".join(parts)


def render_report(graph: Graph, stage: str | None = None) -> str:
    out: list[str] = []
    findings = graph.validate()

    frontier = graph.frontier()
    out.append("## Frontera — se puede atacar ya, en paralelo")
    out.append("")
    if frontier:
        for entry in frontier:
            out.append(f"- {render_entry(graph, entry, annotate=graph.has_edges())}")
    else:
        open_count = len(graph.open_entries())
        out.append(
            "- (vacía) — no hay entradas abiertas."
            if not open_count
            else "- (vacía) — todas las entradas abiertas esperan una dependencia."
        )
    out.append("")

    waves = graph.waves()
    if len(waves) > 1:
        out.append("## Olas")
        out.append("")
        for index, level in enumerate(waves, start=1):
            names = ", ".join(e.feature for e in level)
            out.append(f"{index}. {names}")
        out.append("")

    # One critical path per named stage; a roadmap with no stages gets a single
    # global one, rather than a chain mislabelled as belonging to "no stage".
    if stage is not None:
        scopes: list[tuple[str, str | None]] = [(stage, stage)]
    else:
        named = [title for title in graph.stages() if title]
        scopes = [(title, title) for title in named] or [("global", None)]
    for title, selector in scopes:
        path = graph.critical_path(selector)
        if len(path) < 2:
            continue
        cost = sum(e.weight for e in path)
        chain = " → ".join(e.feature for e in path)
        out.append(f"## Camino crítico — {stage_goal(title) or title}")
        out.append("")
        out.append(f"{chain}  (peso {cost})")
        out.append("")

    deferred = graph.deferred()
    if deferred:
        out.append("## Aplazadas — esperan una condición externa")
        out.append("")
        for entry in deferred:
            out.append(f"- {entry.feature} — {shorten(entry.deferred_until)}")
        out.append("")

    # Never scheduled and never closed, so they would otherwise vanish from every
    # view — and a successor still waiting on one needs to be told why.
    cancelled = graph.cancelled()
    if cancelled:
        out.append("## Canceladas — no se van a construir")
        out.append("")
        for entry in cancelled:
            blocked = graph.successors(entry.feature)
            tail = f" (bloquea: {', '.join(blocked)})" if blocked else ""
            out.append(f"- {entry.feature}{tail}")
        out.append("")

    if graph.has_edges(stage):
        text = render_text_graph(graph, stage)
        if text:
            out.append("## Grafo")
            out.append("")
            out.extend(text)
        diagram = mermaid(graph, stage)
        if diagram:
            # A link, not a fenced block: the terminal cannot render mermaid, and
            # the text view above already answered the question. The diagram
            # travels inside the URL fragment, so say so — opening it hands the
            # feature names to that site.
            out.append(f"Ver dibujado (el enlace lleva el diagrama dentro): {mermaid_link(diagram)}")
            out.append("Fuente mermaid para pegar en GitHub: `sdd_roadmap.py mermaid`")
            out.append("")
    else:
        out.append("(Sin dependencias declaradas: no hay grafo que dibujar.)")
        out.append("")

    if findings:
        out.append("## Problemas")
        out.append("")
        for finding in findings:
            out.append(
                f"- {finding.severity} {finding.code} roadmap.md:{finding.line} — "
                f"{finding.explanation} {finding.action}"
            )
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def as_json(graph: Graph) -> str:
    return json.dumps(
        {
            "entries": [
                {
                    "feature": e.feature,
                    "line": e.line,
                    "stage": e.stage,
                    "stage_goal": stage_goal(e.stage),
                    "checked": e.checked,
                    "status": graph.status[e.feature],
                    "closed": graph.closed[e.feature],
                    "size": e.size,
                    "kind": e.kind,
                    "deferred_until": e.deferred_until,
                    "edges": {k: list(v) for k, v in e.edges.items()},
                    "summary": e.summary,
                }
                for e in graph.nodes()
            ],
            "frontier": [e.feature for e in graph.frontier()],
            "waves": [[e.feature for e in level] for level in graph.waves()],
            "leaves": [e.feature for e in graph.leaves()],
            "deferred": [e.feature for e in graph.deferred()],
            "cancelled": [e.feature for e in graph.cancelled()],
            "critical_path": [e.feature for e in graph.critical_path()],
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "line": f.line,
                    "explanation": f.explanation,
                    "action": f.action,
                }
                for f in graph.validate()
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def load(root: Path) -> Graph:
    roadmap = root / "sdd" / "roadmap.md"
    if not roadmap.is_file():
        raise RoadmapError(
            f"No roadmap at {roadmap}. Create it from the template or run /sdd:init."
        )
    return Graph(root, parse_roadmap(roadmap))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "dump every view as one JSON object, whatever the subcommand "
            "(entries, frontier, waves, leaves, deferred, critical_path, findings)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("report", help="frontier, waves, critical path and graph")
    subparsers.add_parser("validate", help="graph problems only")
    subparsers.add_parser("frontier", help="entries workable right now")
    subparsers.add_parser("waves", help="topological levels of open entries")
    subparsers.add_parser("leaves", help="open entries with no relations")
    critical = subparsers.add_parser("critical-path")
    critical.add_argument("--stage", default=None)
    text_graph = subparsers.add_parser(
        "graph", help="the dependency graph as terminal text, by wave"
    )
    text_graph.add_argument("--stage", default=None)
    diagram = subparsers.add_parser("mermaid", help="mermaid source for the graph")
    diagram.add_argument("--stage", default=None)
    diagram.add_argument(
        "--link",
        action="store_true",
        help="print a mermaid.live URL instead of the source (carries the diagram)",
    )
    diagram.add_argument(
        "--all",
        action="store_true",
        dest="include_all",
        help="include closed entries nothing open waits on (default: omit them)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        graph = load(args.root.resolve())
    except RoadmapError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(as_json(graph))
        return 1 if any(f.severity == "ERROR" for f in graph.validate()) else 0

    if args.command == "report":
        print(render_report(graph), end="")
    elif args.command == "validate":
        findings = graph.validate()
        if not findings:
            print("Roadmap graph is consistent.")
        for finding in findings:
            print(
                f"{finding.severity} {finding.code} roadmap.md:{finding.line} — "
                f"{finding.explanation} {finding.action}"
            )
    elif args.command == "frontier":
        for entry in graph.frontier():
            print(render_entry(graph, entry))
    elif args.command == "waves":
        for index, level in enumerate(graph.waves(), start=1):
            print(f"{index}. {', '.join(e.feature for e in level)}")
    elif args.command == "leaves":
        for entry in graph.leaves():
            print(render_entry(graph, entry))
    elif args.command == "critical-path":
        path = graph.critical_path(args.stage)
        if path:
            print(" → ".join(e.feature for e in path))
    elif args.command == "graph":
        text = render_text_graph(graph, args.stage)
        if text:
            print("\n".join(text).rstrip() + "\n", end="")
        else:
            print("Sin dependencias declaradas: no hay grafo que dibujar.")
    elif args.command == "mermaid":
        diagram = mermaid(graph, args.stage, args.include_all)
        if diagram:
            print(mermaid_link(diagram) if args.link else diagram)

    return 1 if any(f.severity == "ERROR" for f in graph.validate()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
