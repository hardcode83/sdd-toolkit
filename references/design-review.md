# Design review — fresh-context ("goldfish") methodology

The canonical method for reviewing an SDD change's **design before tasks are
written**. Claude (`agents/design-goldfish.md`) and Codex (a native subagent
launched by the design skill) both follow this file; neither keeps a copy.

The reviewer has **no memory of how the design was produced**. That is the
point: the author holds the context and therefore cannot see what they assumed
but never wrote down. Nothing is implemented yet — this reviews a design, not
code, and it certifies nothing: it advises the author and whoever approves.

## Inputs — only these

- `sdd/changes/<feature>/proposal.md` (EARS requirements), `design.md`,
  `BLOCKED.md` if present.
- `sdd/steering/*.md` whose `phases` include `design`, and the `sdd/specs/`
  files the proposal lists as affected.
- The **current source files** the design names, modifies or reads from —
  read them. Most real design defects are a claim the code base cannot support.

Never use a session conversation, a chat summary, or anything the prompt
paraphrases about intent: if the documents do not say it, it is not decided.
Read-only: do not edit, create or run anything that writes.

## The five passes

Cite exact lines for every claim: the design/proposal line, and the source
line that contradicts it or fails to support it.

### 1. Traceability
- Every EARS requirement maps to a design decision **and** to a way it can be
  verified; every decision maps back to a requirement.
- Every configurable value has a stated owner, default, location and reader.
  A flag or setting that nothing reads is a finding.
- Every field a requirement says a record or decision must carry (permissions,
  limits, reasons, provenance) exists in the designed data model.

### 2. Data availability
- For every field, record, signal or input the design consumes, find where it
  exists **today** (type definitions, records, ledgers, ports, configs).
- Flag anything no current structure carries, or carries only in another form
  (hashed vs plain, aggregated vs per item, per run vs per attempt), and any
  port, adapter or config schema the design needs but does not list among the
  affected files.

### 3. Path completeness
- Enumerate every entry point, command, operator verb, terminal state and
  lifecycle transition of the touched code. For each one the new behaviour
  should apply to, check the design states it — not only the happy path. A
  side effect wired to one terminal path but not its siblings is a finding.
- Classifiers and decision tables: check empty, missing and never-evaluated
  inputs, first occurrence (no previous item), and success. Inputs that fall
  through to a wrong default are findings.
- State and counters: when are they reset or invalidated? Re-runs, replays
  and duplicate events: is there an idempotency key?

### 4. Consistency
- Contradictions between proposal, design decisions (D1…Dn), living specs and
  steering rules, and between decisions themselves (one decision stores X
  hashed, another reads X in plain text).

### 5. Verifiability & safety
- Acceptance criteria that cannot be tested as written; ambiguous terms.
- Evidence semantics: what counts as verified, backed or passed. Something
  unverified, missing or unknown must never count as support.
- Fail-open defaults; new external inputs (paths, ids, files) without the
  validation the code base applies to similar inputs.

## Output

Prefer fewer, concrete, evidenced findings. No style remarks, no redesigns:
one line of fix direction at most. One finding per line:

```
[high|medium|low] <pass#> <R#/D#> — <defect> | evidence: <doc file:line> vs <source file:line> | fix: <one line>
```

`high` = an EARS criterion would be unmet, or implementation would be forced
into a redesign. End with exactly one of:

```
VERDICT: PASS
VERDICT: REVISE
```

The verdict is the **last line**, exactly one of those two (or `UNAVAILABLE`
below), with nothing after it. `PASS` only when there is no `high` finding. If the methodology or the change's
`proposal.md`/`design.md` cannot be read, reply only
`VERDICT: UNAVAILABLE — <what is missing>`: a review that did not happen is
never reported as one. A reply whose last line is anything else — missing, an
unknown token, cut off by a budget — **is** `UNAVAILABLE` to whoever reads it.
