# Shrinking a roadmap that stopped being an index

`sdd/roadmap.md` is read by **every** phase, so its size is a cost paid on every
run rather than once. When entries keep their whole rationale inside the file it
stops being an index, and `/sdd:doctor` says so (`SDD025`, budget 32 KB). The
mechanism that prevents this already exists — the long analysis belongs in
`sdd/roadmap/<feature>.md`, read only by that entry's `/sdd:new`
([ADR 0001](../docs/adr/0001-roadmap-structure-and-concurrency.md) D6) — so a
migration is a **relocation**, never a rewrite.

This is the procedure, and the three checks that prove it did no harm. It is one
mechanical pass: keep every judgement call out of it (see *What this pass does
not do*).

## 1. Measure before deciding the shape

The obvious assumption — "entries have long indented bodies, move those" — was
wrong on the first real roadmap this was run against, and acting on it would have
recovered almost nothing. Ask where the bytes actually are:

```python
import re
from pathlib import Path
ENTRY = re.compile(r"^\s*-\s+\[([ xX])\]\s+")
head = cont = 0
for line in Path("sdd/roadmap.md").read_text(encoding="utf-8").splitlines(True):
    if ENTRY.match(line):
        head += len(line.encode())
    else:
        cont += len(line.encode())
print(f"entry lines {head/1024:.1f} KB · everything else {cont/1024:.1f} KB")
```

Measured on a 110 KB roadmap of 64 entries: **97 KB were in the entry lines
themselves** (one of them 9.6 KB on a single line), 7.7 KB in continuation lines.
So the work is *splitting long lines*, not moving indented paragraphs. Check
which one you have before writing anything.

## 2. Do it somewhere safe

The main clone is frequently occupied — on a feature branch, dirty, with a live
session in it. `sdd_session.py --root . check` tells you. Work in a worktree off
the default branch instead (that is what shared rule 10 is for), and confirm the
in-flight branches will not collide:

```bash
git diff --stat origin/<default>...sdd/<feature> -- sdd/roadmap.md   # expect empty
```

Empty is the normal answer, and it is a property of the design, not luck: no
phase writes the roadmap during the cycle — only `/sdd:archive`, post-merge and
serialized (ADR 0001 D5). If a branch *does* touch it, land or park that first.

## 3. The transformation

Per entry:

- **The note gets the original text verbatim.** `sdd/roadmap/<feature>.md`, whose
  name is the same feature `/sdd:new` resolves. Never summarise into it — a
  summary is a second source of truth that quietly disagrees with the first.
- **The index line is a truncation of that text**, cut at the first full stop,
  ending in ` …` when it was cut. Do **not** cut at `:` or `;`: the result
  announces detail and then delivers none ("…para el entorno dev:").
- **Metadata sub-lines stay in the index, immediately under their entry.** The
  adjacency is load-bearing: the parser stops reading sub-lines at the first line
  that is not one, so a blank line or a stray paragraph between them silently
  detaches the whole graph edge.
- **Archive pointers survive on the index line.** ` → changes/archive/<date>-<feature>/`
  is structure, not prose, and `/sdd:doctor` validates it (`SDD001`/`SDD002`).
  Truncation eats it if you do not lift it out first.
- **Leave short entries alone.** A note holding one sentence is a file nobody
  opens. Roughly: skip anything already under ~300 B.

Reuse the toolkit's own parsing rather than re-implementing it — importing
`ENTRY_RE`, `META_LINE_RE`, `entry_feature` and `is_metadata` from
`scripts/sdd_roadmap.py` is what makes "what is an entry" have one definition
instead of two that drift.

## 4. Prove it did no harm

Three checks, in this order. The first two are the ones that matter; a diff of
the rendered `report` is **not** one of them, because that view truncates long
entries anyway and will differ for reasons that are purely cosmetic.

**No text was lost.** Every term of the original must still appear, in the index
line or in that entry's note:

```python
words = re.findall(r"[\w`/§.-]{4,}", original_body)
missing = [w for w in words if w not in index_line + note_text]
```

Expect zero. This is the check that catches a truncation you thought was safe.

**The graph did not move.** Parse both versions with `sdd_roadmap.parse_roadmap`
and compare each entry field by field — `feature`, `checked`, `stage`, the four
edge keys, `size`, `kind`, `pointer` — ignoring `body` and the line numbers,
which are *supposed* to change.

Expect zero differences, with one exception worth predicting: an **open** entry
whose prose merely mentions another feature's archive path is parsed as *having*
that pointer, and moving the prose to its note correctly drops it. That is a
correction, not a regression — but confirm the entry is open and that the path
belonged to a different feature before accepting it.

**The tools still agree.**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_roadmap.py" --root . validate   # consistent
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd-doctor.py" --root .             # 0 errors, no SDD025
```

Pre-existing warnings about other files stay pre-existing: `git status` should
show only `sdd/roadmap.md` and `sdd/roadmap/`.

## What this pass does not do

Two improvements sit right next to this one, and doing them in the same pass is
how a mechanical, verifiable change becomes an unreviewable one:

- **Grouping entries into `## Stage N — <outcome>`** (ADR 0001 D3). That is a
  judgement about the project's plan, and getting it wrong hides the chains the
  stages exist to show.
- **Declaring the relations the prose already states** (`needs:`, `completes:`,
  `informs-from:`, `inherits-from:`). Genuinely valuable — a flat graph means
  `/sdd:auto N` still picks by file order — and the moment you read all 64 bodies
  is the cheap moment to spot them. `sdd_roadmap.py suggest --feature <f>` lists
  candidates with the sentence that suggested each. But a mention is not a
  dependency: inventing an edge is worse than leaving the graph flat, because a
  flat entry is simply always workable, which is correct when nothing is known.

Offer both as follow-ups, with the size fix already merged and verified. Neither
of them can be checked the way the three above can.

## Also worth fixing while you are there

A roadmap old enough to need this often carries a header comment describing how
it is maintained, written before the flow changed. The common stale claim is that
`/sdd:new` annotates `→ changes/<feature>/` when it starts an entry: it does not,
and has not since ADR 0001 D5 — in-flight state is derived from
`sdd/changes/<feature>/STATE.md`, precisely so two adjacent entries stop
conflicting when worked in parallel. Correct it in the same commit; it is
documentation of the file you are already rewriting.
