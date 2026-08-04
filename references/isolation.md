# Worktree isolation — the protocol every phase follows

Shared rule 10 states the invariant: one feature, one branch, one working
directory. This is how to honour it. Background and the measured evidence:
[ADR 0001](../docs/adr/0001-roadmap-structure-and-concurrency.md), D1-D2.

## When to isolate

Ask, then act on the answer — never on a guess:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . check --feature <feature>
```

Exit `0` prints `CLEAR`, exit `1` prints `CONFLICT` with one line per piece of
evidence. It is deliberately read-only, so any phase may call it.

| Verdict | Interactive phases | `/sdd:auto` |
|---|---|---|
| `CLEAR` | Continue in the current directory. Still `claim` the feature. | Same. |
| `CONFLICT` | **Offer** the worktree (AskUserQuestion, recommend yes) and say which evidence triggered it. If the user declines, say plainly what can go wrong and continue where you are — it's their call. | **Apply** it without asking: auto never asks (its gate-conversion rule). |

Conflict evidence, in the order it matters:

1. **Another live session** holds this clone (a registered session whose process
   is still running). This is the case the user hits when they open two sessions
   to work two roadmap entries.
2. **HEAD is on another feature's branch** (`sdd/<other>`), especially with a
   dirty tree — switching now moves someone else's uncommitted files.
3. **This clone holds in-flight changes for other features** (`sdd/changes/<other>/`
   with no archive). Evidence that outlives the session that produced it.

## Creating the worktree

1. **Check the base first.** `EnterWorktree`'s default `worktree.baseRef` is
   `fresh`, which branches from `origin/<default-branch>` — so local commits that
   were never pushed are silently left behind. Compare before creating:

   ```bash
   git rev-list --count origin/<base>..<base>
   ```

   Non-zero means the local base is ahead. Say so and let the user choose:
   push the base first, or accept branching from the remote. Never record a BASE
   in `STATE.md` that the worktree did not actually branch from.

2. **Create and enter it** with the `EnterWorktree` tool, named after the feature
   (`sdd/<feature>`). It switches the session's working directory, which is the
   whole point — prefixing paths by hand leaves the harness pinned to the old
   directory. The worktree lands under `.claude/worktrees/`, which must be
   gitignored (`/sdd:init` adds it; `SDD024` reports it missing).
   Do not assume the directory name: the tool flattens the `/`, so the name
   `sdd/<feature>` becomes `.claude/worktrees/sdd+<feature>`. That is precisely
   why the path is recorded in step 4 and read back with `resolve` — never
   reconstructed.

3. **Bootstrap what git does not carry.** A fresh worktree has no `.env`, no
   `.venv`, no `node_modules`, no local database — so the project's own
   verification will fail there, and that failure is not a code problem. Read the
   **Worktree bootstrap** section of `sdd/project.md` and run exactly what it
   says. If the project declares nothing and its verification then fails on a
   missing local file, that is the finding: report it, offer to record the
   bootstrap steps in `project.md`, and do not paper over it by guessing which
   files to copy.

4. **Record the binding** so later phases can find it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . claim <feature>
   ```

   Run it from inside the worktree, so the recorded path is the worktree's. It
   refuses if another **live** session already holds the feature — that refusal
   is the answer, not an obstacle to work around.

## Re-entering in a later phase

Every phase after `new` asks where the feature lives, instead of assuming it is
the current directory:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>
```

- Prints a path (exit `0`) → if it is not the current directory, enter it with
  `EnterWorktree` passing `path`.
- Prints nothing (exit `1`) → the feature has no worktree: work where you are,
  after running `check` as above.

`resolve` reports a binding whose directory has disappeared as unbound, so a
deleted worktree degrades to "work here" rather than sending a phase into a path
that no longer exists.

**Before the first edit of `/sdd:run`**, verify the branch — this is the guard
that protects the merge evidence:

```bash
git branch --show-current    # must be sdd/<feature>
```

If it is not, stop. Do not "fix" it with a checkout that could carry someone
else's files.

## Cleanup

After `/sdd:archive` proves the merge, the worktree and its branch have no
further use. Archive offers to remove them:

```bash
path=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>)
git worktree remove "$path"
git branch -d sdd/<feature>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . release <feature>
```

**Always take the path from `resolve`, never build it.** `EnterWorktree` flattens
the `/` in a worktree name, so `sdd/<feature>` lands in
`.claude/worktrees/sdd+<feature>` — a hardcoded `.claude/worktrees/sdd/<feature>`
does not exist. The registry holds the real path; use it.

Use plain git, not `ExitWorktree`: that tool only touches worktrees created by
`EnterWorktree` **in the same session**, and archive normally runs in a different
one. `git worktree remove` refuses when the tree is dirty, which is the right
default — surface that instead of forcing it.

`sdd_session.py --root . orphans` lists bindings whose worktree is gone and
worktrees whose change is already archived; `/sdd:doctor` reports both.

## Where the registry lives, and why

`$(git rev-parse --git-common-dir)/sdd/sessions.json` — the *common* git
directory, which every linked worktree of the repository shares, and which is
never committed and never appears in `git status`. Liveness comes from the
recorded pid, so a session that ended takes its claim with it and there is
nothing to unlock by hand.

It holds two different things on purpose: **sessions** (pruned by liveness) and
**worktree bindings** (they outlive the session, because the unfinished work
does).

## Limits worth stating

- This is the **machine** claim. The team claim is still the remote
  `sdd/<feature>` branch, checked by `/sdd:new` and `/sdd:auto`. A colleague's
  branch and a colleague's process are different facts, and both checks run.
- Without `CLAUDE_CODE_SESSION_ID` in the environment (a non-Claude runner, a
  plain shell) no session is registered, and detection degrades to the on-disk
  evidence — branch, dirtiness, change directories. It never degrades to a
  *wrong* claim.
- The Codex adapter has no `EnterWorktree`. There, isolation is manual
  (`git worktree add` plus running the phase from that directory); the scripts
  themselves are plain Python 3 and work unchanged.
