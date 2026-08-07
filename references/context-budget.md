# Context budget — why terminal phases run in their own session

The flow's cost is dominated by **where** a phase runs, not by what it does.
This file is the measurement behind shared rule 11 and the instruction each
phase skill carries.

## What we measured

38 sessions of a real consumer project (27 features taken from `/sdd:new` to
archive over three weeks), read from the Claude Code transcripts:

| phase | requests | context read | share | **avg context per request** |
|---|---:|---:|---:|---:|
| `run` | 7,215 | 2.96 B | 39.9% | 411k |
| `review` | 3,314 | 1.89 B | 25.5% | **571k** |
| `auto` | 2,402 | 0.83 B | 11.2% | 345k |
| `archive` | 1,043 | 0.66 B | 8.9% | **634k** |
| `new` + `design` + `tasks` | 2,756 | 0.49 B | **6.6%** | 157–239k |

Read the last column, not the third. The phases that *think* cost 6.6% of the
total. `archive` — which moves directories, merges specs and ticks a roadmap —
burned 660M tokens at an average of 634k per request. Not because archiving is
expensive, but because it happens **last**, on top of everything the session
already accumulated.

Two more numbers from the same corpus:

- 15 of 26 substantive sessions touched **three or more features**, and those 15
  burned **5.09 B of the 7.42 B** total. Working feature four while carrying
  features one to three is pure overhead.
- Exact duplicate reads inside a session: **5%**. The waste is not repetition —
  the loops and fix-round caps hold. It is accumulation.

## Why a fresh context loses nothing

Shared rule 1 already says it: **state lives in `sdd/`, not in the session.**
Specs, proposal, design, tasks, `STATE.md`, `BLOCKED.md`, the metrics ledger —
everything a phase needs to start, and everything it must leave behind, is on
disk by construction.

So a phase that starts with an empty context is not a phase that lost
information. It is the design working. If a phase *would* break when run in a
fresh session, that is a bug in rule 1 compliance, not a reason to keep the
context.

## The three mechanisms

The model cannot clear its own context — `/clear` is a client command, not a
tool, and `--autocompact` only moves the compaction threshold. What exists:

1. **A fresh headless session** — `claude -p "/sdd:review <feature>"` from Bash.
   A real session: skills resolve, the per-phase model profile applies, hooks
   and MCP work, and the panel launches its agents normally. The caller gets
   only the final report back. This is what `/sdd:auto` uses.
2. **A subagent** (`Agent` tool) — isolated context, simpler, but a subagent
   launching a panel of subagents is not something to rely on. Fine for
   mechanical phases, not for `review`.
3. **Telling the user** — in interactive use the skill cannot clear anything,
   but the phase gate (shared rule 3) already stops there. Saying "`/clear`
   before the next phase" at the gate costs one line and captures most of it.

## Reading the result, not the prose

When a phase runs in a sub-session, do **not** parse its text to decide what
happened. Read the evidence it left: `STATE.md`, `BLOCKED.md`, the checkboxes in
`tasks.md`. That is the same rule the merge gate follows (shared rule 8) and it
is what makes delegation safe — the sub-session's report is a summary for the
human, its files are the fact.

## Metrics still add up

`.sdd-usage/` is one sink per repository (see `metrics.md` in this directory),
so a sub-session exports to the same log as its caller, and the phase it runs
marks itself as usual. Delegating a phase does not lose its spend — it just
stops paying for the context of the phases before it.
