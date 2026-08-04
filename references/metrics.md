# Usage metrics — per-feature token/cost tracking

Optional. When enabled, every SDD phase records what it consumed — **real
token counts** (input/output/cache, per model, **subagents included**) plus
estimated USD cost — so each archived change carries its full cost from
conception to archive.

## Where it lives

- `sdd/changes/<feature>/metrics.md` — the ledger: one row per phase
  (date, phase, models, tokens in/out/cache, cost). Travels with the change
  into `changes/archive/`.
- `sdd/metrics.md` — global summary: one row per feature, upserted (never
  duplicated) from `READY_FOR_PR` onwards, with `archived` filled in when the
  change is archived. A feature waiting for its merge already has its row.
- `.sdd-usage/` — runtime data (gitignored, machine-local): `otel.jsonl`
  (raw datapoints), `tasks/<session-id>` (one attribution marker per session),
  `current-task` (the fallback marker, see below), `sink.pid`.
  **One per repository**, next to the main worktree: every session of a project
  exports to the same port, so there is exactly one sink and one log even when
  features are isolated in separate worktrees. Resolved by
  `scripts/usage-dir.sh` (and `usage_dir()` in `usage-sync.py`).

## How it works

Claude Code's built-in OpenTelemetry export is the data source — the
documented, stable interface for usage (`claude_code.token.usage` and
`claude_code.cost.usage`, with `type`, `model`, `session.id` and
`query_source: main|subagent|auxiliary` attributes).

1. `/sdd:init` sets the project env (`.claude/settings.json` → `env`):
   telemetry on, OTLP metrics over `http/json` to `http://127.0.0.1:<port>`,
   10 s export interval.
2. `${CLAUDE_PLUGIN_ROOT}/scripts/usage-sink.py` — a ~100-line stdlib-Python
   OTLP receiver — runs locally on that port and appends every datapoint to
   the project's `.sdd-usage/otel.jsonl`, tagged with the task
   (`<feature>/<phase>`) **of the session that produced it**: every datapoint
   carries `session.id`, so the sink resolves `tasks/<session-id>`.
3. Each phase marks itself active at start (`usage-mark.sh <feature> <phase>`,
   which writes that per-session marker and autostarts the sink) and writes its
   ledger row at the gate
   (`usage-phase.sh <feature> <phase>`, which aggregates all rows for that
   task — across sessions and subagents — and replaces the row idempotently).
4. `usage-sync.py --root . sync <feature>` rebuilds the **whole** ledger from
   the log and upserts the consolidated row in `sdd/metrics.md`. `/sdd:review`
   runs it when it records `READY_FOR_PR`, and `/sdd:archive` runs it after the
   change is moved. This is what makes the ledger complete rather than
   best-effort — see below.

## Why the log is the source of truth, not the gate

`usage-phase.sh` only writes when a phase asks it to, so three things used to
disappear from the ledger while remaining in the log:

- a phase interrupted before its gate (nobody ever called it);
- a phase whose skill had no metrics call at all (`review` was uninstrumented
  until it became a lifecycle phase);
- the spend that arrives *after* the gate wrote its row — in `archive`, that
  meant everything `finalize-archive` and the summary consumed.

`usage-sync.py` recomputes every row from `.sdd-usage/otel.jsonl`, so those
cases self-heal, and it works on archived changes too — that makes it the
recovery path for history recorded before a phase was instrumented:

```bash
python3 scripts/usage-sync.py --root /path/to/project report          # what is missing
python3 scripts/usage-sync.py --root /path/to/project sync <feature>  # rebuild it
```

It is deliberately conservative: a phase the log knows nothing about keeps its
recorded row, and a row already holding **more** than the log accounts for is
kept and reported with a `WARNING` instead of being lowered. Syncing never
destroys a number it cannot reproduce.

One thing no rebuild can fix retroactively: attribution. The sink tags each
datapoint with whatever its session's marker said at that moment, so a phase
that never marks itself has its spend filed under that session's previous
phase. That is why every phase skill marks itself, and why the test suite
asserts it.

## Properties and limits

- **Multi-agent**: subagent usage carries `query_source=subagent` and is
  counted (the ledger notes `incl. subagents`).
- **Multi-session**: attribution is **per session**, so two sessions working
  two features concurrently are each billed to their own feature. A phase
  spanning several sessions still aggregates correctly, because rows are
  aggregated by task, not by session.
  This was the assumption that used to be baked in — *one active feature per
  project at a time* — and it was wrong in both directions: a single global
  marker was last-writer-wins, and because the OTLP port lives in the versioned
  `settings.json` (read at session start), every session and every worktree
  exports to the same one, so per-worktree ledgers would have silently collected
  everything in whichever worktree bound the port first. Hence: one sink and one
  log per repository, attribution by `session.id`.
  `current-task` remains as the fallback for datapoints whose session cannot be
  identified (no `session.id`, or a session that never marked a phase), so
  nothing that used to be attributed stops being attributed.
- **Export lag**: metrics flush every ~10 s; a gate that records immediately
  after the last action may miss the tail (the script says so and can be
  re-run — rows are recomputed, not duplicated).
- Cost is the API-equivalent estimate; on subscription plans treat it as a
  relative measure.
- Requires `jq` and `python3`. Sessions must restart once after enabling
  (env changes apply at session start).
