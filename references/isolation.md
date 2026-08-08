# Worktree isolation — the protocol every phase follows

Shared rule 10 states the invariant: one feature, one branch, one working
directory. This is how to honour it. Background and the measured evidence:
[ADR 0001](../docs/adr/0001-roadmap-structure-and-concurrency.md) D1-D2, revised
by [ADR 0002](../docs/adr/0002-isolation-policy.md).

## When to isolate

Two different questions, asked with one command and answered separately:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . check --feature <feature>
```

- The **verdict** describes the clone. Exit `0` prints `CLEAR`, exit `1` prints
  `CONFLICT` with one line per piece of evidence. It is deliberately read-only,
  so any phase may call it, and the policy never moves it: a check that reported
  a conflict nobody has would make every later reading of it a lie.
- The **action** is the last line — `ISOLATE` or `WORK HERE` — and that is what
  the phase obeys. It combines the verdict with the project's isolation policy.

| Policy in `sdd/project.md` | On `CLEAR` | On `CONFLICT` |
|---|---|---|
| `on-conflict` (the default; a project that declares nothing) | `WORK HERE` — continue in the current directory. Still `claim` the feature. | `ISOLATE` |
| `always` | `ISOLATE` — every feature gets its own worktree, the first one included. | `ISOLATE` |

`ISOLATE` is one instruction with two temperaments, depending on what produced it:

| | Interactive phases | `/sdd:auto` |
|---|---|---|
| From **evidence** (`CONFLICT`) | **Offer** it (AskUserQuestion, recommend yes), naming the evidence the check reported. If the user declines, say plainly what can go wrong and continue where you are — it's their call. | **Apply** it without asking: auto never asks (its gate-conversion rule). |
| From **policy** (`CLEAR` + `always`) | **Apply** it and say so. The project already made this decision; re-asking once per feature is exactly the question the policy exists to remove. State the bootstrap cost at creation (step 3), don't re-open the choice. | **Apply** it. Same path. |

Conflict evidence, in the order it matters:

1. **Another live session** holds this clone (a registered session whose process
   is still running). This is the case the user hits when they open two sessions
   to work two roadmap entries.
2. **HEAD is on another feature's branch** (`sdd/<other>`), especially with a
   dirty tree — switching now moves someone else's uncommitted files.
3. **This clone holds in-flight changes for other features** (`sdd/changes/<other>/`
   with no archive). Evidence that outlives the session that produced it.

### Why `CLEAR` stopped meaning "work here"

Evidence #2 and #3 are not accidents of the environment: **the `CLEAR` path
manufactures them.** A clone with nothing in flight is always `CLEAR`, so the
first feature stayed where it was, moved HEAD to `sdd/<first>` and left the tree
dirty — which is precisely what the second feature is then told about. The rule
detected a state the flow itself had created one feature earlier, and the main
clone ended up pinned to somebody else's branch with uncommitted files: every new
shell there starts on the wrong branch, and anything expecting the clone to sit on
the default branch breaks until that session finishes.

`isolation: always` removes the first-feature exception. Sessions become uniform —
"open N sessions, each starting from the default branch" becomes expressible —
and the main clone stays a pristine base. The cost is real and lands on every
feature (step 3), which is why it is the project's decision and not the default.

### Declaring the policy

One line in `sdd/project.md`, in its **Worktree bootstrap** section:

```markdown
isolation: always
```

`always` or `on-conflict`; nothing declared means `on-conflict`, so existing
projects are untouched. `/sdd:init` offers it, `/sdd:doctor` reports it, and a
value that is neither is an error (`SDD026`) rather than a silent fallback. To
read it without the rest of the check:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . policy
```

## Creating the worktree

**Before anything else is written.** Isolation comes before the branch exists and
before `sdd/changes/<feature>/` does, so the proposal is written *inside* the
worktree, on the feature branch — never in the main clone to be moved later. In
`/sdd:new` that means the order is: remote claim check → `check` → isolate →
`claim` → then the proposal.

1. **Read the base from the check.** Its `base:` line already answers what
   `EnterWorktree` would branch from and what that would cost, because its
   default `worktree.baseRef` is `fresh` — a branch from
   `origin/<default-branch>`, so local commits that were never pushed are
   silently left behind. Under `always` this is on the hot path of *every*
   feature, not a rare one.

   - `N local commit(s) NOT in origin` → the local base is ahead. Say so and let
     the user choose: push the base first, or accept branching from the remote.
   - `not published` → `fresh` has nothing to resolve; see the degenerate cases
     below.

   Never record a BASE in `STATE.md` that the worktree did not actually branch
   from. (The equivalent by hand is `git rev-list --count origin/<base>..<base>`.)

2. **Create and enter it** with the `EnterWorktree` tool, named after the feature
   (`sdd/<feature>`) — unless one of the rows in *Repositories where
   `EnterWorktree`'s defaults do not apply* (below) matches, and then it is
   `git worktree add` followed by `EnterWorktree` with `path`. Either way the tool
   switches the session's working directory, which is the whole point —
   prefixing paths by hand leaves the harness pinned to the old directory. The worktree lands under `.claude/worktrees/`, which must be
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

   **Say the cost once, here, before bringing anything up.** A worktree starts
   with an **empty database**, reinstalls its dependencies, and costs its own
   disk (the "two worktrees" section below explains why). Under `isolation:
   always` every feature pays it, including the first — the one that used to dodge
   it entirely by working in the main clone. State it at creation, in one line,
   naming what `project.md` declares; later phases re-enter a worktree that is
   already bootstrapped and must not repeat it.

   **And check what the project cannot have twice.** Bootstrap has a second
   dimension that "copy these files" does not cover: *exclusive resources*. A
   project can need nothing copied and still be unable to run two dev stacks,
   because something in it can only exist once on the machine — a published port,
   a fixed container name, a daemon on a known socket, a database with a fixed
   name, a lockfile. The failure looks nothing like a missing file: it is
   `address already in use`, or a suite that passes alone and fails when a
   sibling worktree is up. If `project.md` declares such a constraint, say it
   **before** the user runs the tests, not after they debug the collision.

4. **Record the binding** so later phases can find it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . claim <feature>
   ```

   Run it from inside the worktree, so the recorded path is the worktree's. It
   refuses if another **live** session already holds the feature — that refusal
   is the answer, not an obstacle to work around.

### Repositories where `EnterWorktree`'s defaults do not apply

Under `on-conflict` these were rare. Under `always` every feature meets them, so
each one has a decided behaviour rather than a discovered one. `check` reports
the facts that pick the row (`base:`, `worktree: … (linked)`, `main_worktree`):

| Situation | What the check shows | What to do |
|---|---|---|
| **No remote** | `base: main → … (not published: …)` | `fresh` has no `origin/<default>` to branch from. Create it explicitly and enter it by path: `git worktree add .claude/worktrees/sdd+<feature> -b sdd/<feature> <default>`, then `EnterWorktree` with `path`. The tool documents entering a worktree made this way; it is not a workaround. |
| **Detached HEAD** | `branch: (detached)` | The commit you are standing on is not a base. `check` falls back to `origin/HEAD`, then to the current branch, then to `main` — the last one is a guess. Confirm the base branch with the user before creating anything; in `/sdd:auto`, BLOCK: its BASE precondition needs a branch, and inventing one records false merge evidence. |
| **You are already in a linked worktree** | `worktree: … (linked)` | Do not nest. Create the new one under the **main** clone's `.claude/worktrees/` (`main_worktree` in the check's JSON) with `git worktree add`, then `EnterWorktree` with `path`. Nesting works in git and then makes the parent unretirable while the child lives inside it. |
| **Empty repository** (no commits) | `base: … — nothing to branch from yet` | There is no base. Say so and stop: this is a repository that has not started, not a case to guess a branch for. |

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

### It asks the registry, and then it asks git

The registry is machine-local and only knows what was `claim`ed. So it does not
know about a worktree created by hand, one made on another machine, or one whose
registry was rebuilt after corruption (`read_registry` rebuilds rather than
failing — it is a cache of live facts, not a source of truth). Git has known
about all of them the whole time, which is why `worktrees` and `retire` ask git.

`resolve` now does the same: registry first, then the worktree git has checked
out on `sdd/<feature>` — matched exactly, since an `sdd/<feature>-archive`
worktree belongs to the feature but is not where its phases run.

This matters more than it used to. While every phase ran in the same session,
the conversation carried the directory over from `run` and a silent registry
cost nothing. Once phases start in a fresh context (shared rule 11), `resolve`
is the *only* thing that knows where the work is — and answering "" there does
not degrade to "work here", it degrades to **working on the base branch in the
main worktree**, which is a different change.

### The branch guard belongs to every phase that touches the change

**Before the first edit of `/sdd:run`, and before `/sdd:review` reads a diff**:

```bash
git branch --show-current    # must be sdd/<feature>
```

If it is not, stop. Do not "fix" it with a checkout that could carry someone
else's files. Run needs it because it *writes*; review needs it because it
*certifies* — `mark-ready` records `head_branch` and `implementation_sha` as the
merge gate's evidence, and a review run from the wrong directory signs a range
that is not the change. `/sdd:ship` is covered by construction: it refuses to
publish when HEAD no longer matches the recorded `implementation_sha`.

## Cleanup

After `/sdd:archive` proves the merge, the worktree and its branch have no
further use. Archive offers to remove them:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . worktrees   # what exists, and what can go
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . retire <feature>
```

**Never build the path by hand.** `EnterWorktree` flattens the `/` in a worktree
name, so `sdd/<feature>` lands in `.claude/worktrees/sdd+<feature>` — a hardcoded
`.claude/worktrees/sdd/<feature>` does not exist. `worktrees` and `retire` take
the real path from git.

### What "retirable" means

Retirement follows the same standard as the merge gate: permitted by facts, never
by assumption. `worktrees` marks an entry `RETIRABLE` only when all of these hold,
and names every one that does not:

| Condition | Why it blocks |
|---|---|
| Its change is `ARCHIVED` | Work still in flight has nowhere else to live |
| Its branch is contained in its base | Commits not in the base would be discarded |
| The tree is clean | Uncommitted work never reached the merge |
| Nothing unpushed | Same, one step later |
| **No other live session inside** | Removing a worktree under a running session leaves it with a cwd git cannot read — its `.git` points at metadata git just pruned |
| You are not standing in it | Same failure, applied to yourself |
| Git has not locked it | `git worktree unlock` is a deliberate decision, not an obstacle |

Enumeration comes from `git worktree list`, **not** from the registry: git is the
authority on what exists, and a worktree created by hand never registered. The
feature is recovered from the binding or, failing that, from the branch name —
including `sdd/<feature>-archive`, which still belongs to `<feature>`.

`retire` also **verifies the directory is gone**. Git unregisters the worktree
before deleting it, so a failed deletion leaves files git no longer tracks and
nothing would report again; when that happens the command says so and prints the
`rm -rf` that finishes the job.

**When `rm -rf` is not enough (macOS + container volumes).** If the deletion fails
with `Permission denied` on directories that are **empty and owned by you** —
typically `node_modules`, `.venv`, `.next`, the mountpoints of named container
volumes — the blocker is an **ACL, not a mode**, so neither `chmod -R` nor `sudo`
is the answer and no amount of staring at `rwx` explains it:

```bash
ls -lde <dir>          # look for:  0: user:<you> deny delete
chmod -a# 0 <dir>      # drop that ACL entry, then retry the rm -rf
```

Docker Desktop sets it when it creates the mountpoint, and it **survives the
container, the volume and the compose project**. Worth knowing before spending
half an hour on permissions: measured on a real cleanup, the leftover was 52 KB of
three empty directories that refused to go.

`--force` exists and discards whatever the blockers were protecting. It is the
user's call, never the flow's.

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

## When two worktrees cannot both run the app

The most common blocker after the first worktree works is a **dev stack that only
binds once**: `make up` in the second worktree hits `address already in use`, so
concurrent sessions cannot run tests and the whole point of isolating is lost.

Reaching for per-worktree ports is the obvious move, and it may not be the
cheapest one. Three questions decide it, and every one is answered by
**measuring**, not by discussing — "I don't know" is the normal starting state,
and none of these can be settled by reading this file:

1. **Do the tests need published host ports at all?** A suite that runs *inside*
   the stack (`docker compose exec …`, `kubectl exec`, a test container on the
   same network) reaches services by name, and then the second worktree needs to
   publish nothing — the collision disappears instead of being managed. Whether
   that holds for a given project is a **hypothesis to test, not a safe
   assumption**: bring the stack up without publishing, run the suite, and look
   for the one test that pokes `localhost` (an integration probe against an
   external API is the usual culprit).
2. **Are the data services shareable?** If the runner already isolates per
   process — a database name per pid, a queue prefix per run, a temp dir per
   worker — one Postgres can serve every worktree. Check whether that isolation
   already exists before duplicating the service; projects often built it for
   concurrent CI and never noticed it solves this too.
3. **What does the container runtime already isolate?** Compose derives its
   project name from the directory, so containers, networks and named volumes are
   *already* per worktree. Usually the only thing left colliding is the host port
   binding — a much smaller problem than it first looks, and worth confirming
   before designing around it.

Two consequences worth stating up front, because they surprise people: per-project
named volumes mean each worktree starts with an **empty database** and reinstalls
dependencies (slow first run, no seed data), and N stacks cost N sets of volumes
on disk.

Under `isolation: always` this question arrives on the first feature instead of
the second, so a project that has an exclusive resource should either declare the
operational rule before turning the policy on, or leave the policy at
`on-conflict` until it can. The policy does not create the constraint; it stops
postponing it.

Whatever the project decides goes in its **Worktree bootstrap** section — the
decision is the project's (shared rule 9), and a change this shape usually
deserves its own roadmap entry with a design phase: it touches the compose file,
the task runner, and possibly CI, and getting it wrong breaks the path to
production. What the toolkit owns is the questions, not the answer.

## Limits worth stating

- This is the **machine** claim. The team claim is still the remote
  `sdd/<feature>` branch, checked by `/sdd:new` and `/sdd:auto`. A colleague's
  branch and a colleague's process are different facts, and both checks run.
- Without `CLAUDE_CODE_SESSION_ID` in the environment (a non-Claude runner, a
  plain shell) no session is registered, and detection degrades to the on-disk
  evidence — branch, dirtiness, change directories. It never degrades to a
  *wrong* claim.
- The Codex adapter has no `EnterWorktree`, so nothing can switch the session's
  working directory. There, isolation is manual — and under `isolation: always`
  it **degrades to a handoff, never to a no-op**: create the worktree
  (`git worktree add .claude/worktrees/sdd+<feature> -b sdd/<feature> <base>`),
  bind it (`sdd_session.py --root . claim <feature> --worktree <path>`), then
  **stop** and tell the user to run the phase from that directory. Continuing in
  the main clone would silently ignore a policy the project declared, which is
  the one outcome that is not allowed. Under `/sdd:auto` on Codex, that is a
  BLOCKED entry with the resume command, not a skipped step. The scripts
  themselves are plain Python 3 and work unchanged.
