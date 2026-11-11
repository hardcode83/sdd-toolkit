# Design review (fresh-context "goldfish")

## Purpose

Before tasks are written, a reviewer with no memory of how `design.md` was
produced checks it against the real code base and steering. The author holds
the context and cannot see what they assumed but never wrote down; the
reviewer can. The review advises the author and the approver; it certifies
nothing and is not a core panel reviewer.

## Requirements

### Methodology

- THE SYSTEM SHALL ship `references/design-review.md` as the single methodology for design review, shared by Claude and Codex (neither keeps a copy), defining five passes: traceability, data availability, path completeness, consistency, verifiability & safety.
- THE methodology SHALL require every finding to cite design/proposal lines and the source lines that contradict or fail to support them, with a severity (`high|medium|low`), in the form `[sev] <pass#> <R#/D#> — <defect> | evidence: … | fix: …`.
- THE methodology SHALL end with exactly one last line: `VERDICT: PASS` (no `high` finding) or `VERDICT: REVISE`, or `VERDICT: UNAVAILABLE — <reason>` when inputs cannot be read. A reply whose last line is anything else (missing, unknown token, cut off by a budget) is `UNAVAILABLE`.
- THE methodology SHALL restrict the reviewer's inputs to the change's `proposal.md`, `design.md`, `BLOCKED.md`, steering whose `phases` include `design`, the specs the proposal lists, and the source files they name, and SHALL forbid any session conversation.

### Claude adapter

- THE SYSTEM SHALL ship `agents/design-goldfish.md` (`name: design-goldfish`, model `opus`) whose body defers to the methodology path given in the prompt instead of copying it.
- THE agent SHALL be read-only by construction: `tools` is a subset of `{Read, Grep, Glob}`; it has no shell and no edit tools.
- THE agent SHALL end with `VERDICT: UNAVAILABLE` if it exhausts its budget (~40 tool calls) before finishing the five passes.
- THE agent SHALL NOT match the core-reviewer glob `agents/sdd-*.md`, so the panel registry stays exactly the three core reviewers (see `reviewer-parity`).

### /sdd:design integration

- WHEN `/sdd:design` has written, amended or kept `design.md` and the change is not trivial, THE skill SHALL run one fresh-context design review before the gate (Claude: `sdd:design-goldfish`, foreground, `model: opus`, preceded by the Claude-only alias preflight; Codex: one native read-only subagent instructed with the methodology). The prompt carries only the feature name and document paths, never a summary of the conversation.
- WHEN the review returns `high` findings, THE skill SHALL amend `design.md` or surface them as open questions, and MAY re-review at most once, as a new launch.
- THE gate summary SHALL list the verdict and every unresolved finding; IF no fresh-context reviewer can be spawned THEN THE skill SHALL say so and SHALL NOT claim the review ran.
- THE step is advisory: it writes no receipt and blocks nothing by itself.

### Read-only guard

- THE skill SHALL take a worktree fingerprint (`scripts/worktree_fingerprint.py`: HEAD plus content of every tracked and non-ignored untracked file, symlinks by target, executable bit; snapshot stored in the git dir) before and after the review.
- IF `compare` reports any changed path (exit 1) or cannot verify (exit 2), or the snapshot failed, THEN THE review SHALL be treated as `UNAVAILABLE` and anything written discarded.
- Under Codex the child SHALL run in a read-only sandbox or not be launched.
- Accepted limits: the git dir and ignored paths are not covered by the fingerprint; the Claude reviewer cannot reach them without a shell, and the Codex sandbox covers them.

### /sdd:auto integration

- WHEN `/sdd:auto` runs the design phase, ITS approval substitute SHALL be this design review (replacing the `sdd-architect` review of the design document), with at most two rounds, model `opus` explicit.
- IF a `high` finding remains after the re-review THEN it SHALL be treated as an open question: with a recommendation → `assumed`, without one → BLOCK.
- IF the reviewer is `UNAVAILABLE` THEN auto SHALL BLOCK (no human gate follows, so this path is fail-closed).

### Validation

- `scripts/validate_toolkit.py` (`design-review`, included in `all`) SHALL fail when the agent or methodology is missing, when the agent's `name` is not `design-goldfish`, when its `tools` are not a non-empty subset of the read-only allowlist or its body lacks the read-only contract, when it does not reference `design-review.md`, or when the methodology lacks any of the five pass titles or the `VERDICT:` line.
- Both plugin manifests SHALL carry the same version.
