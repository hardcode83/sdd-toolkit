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

## Second measurement (September 2026)

80 features of the same project, 398k OTel datapoints, ~12.3k USD estimated, read
from `.sdd-usage/otel.jsonl` — so this one counts subagents and models too:

| where | share of spend | avg context / request |
|---|---:|---:|
| main conversation, all phases | **75%** | 189k–444k |
| `run`, main conversation | 42% | **444k** (sessions peaking at 526–694k) |
| panel subagents (`run` + `review`) | 17% | 105k–140k |
| auxiliary (titles, compaction summaries) | 6% | — |

79% of `run`'s main-conversation cost was cache *reads*: re-reading the
accumulated context on every request. Opus was 77% of all spend although the
skills asked for Sonnet — an inline skill's `model:` does not govern the
session. And 62% of sessions touched more than one feature: the `/clear` advice
at the gate was not being followed. The panel is not the problem; where the
phase runs is.

## Why a fresh context loses nothing

Shared rule 1 already says it: **state lives in `sdd/`, not in the session.**
Specs, proposal, design, tasks, `STATE.md`, `BLOCKED.md`, the metrics ledger —
everything a phase needs to start, and everything it must leave behind, is on
disk by construction.

So a phase that starts with an empty context is not a phase that lost
information. It is the design working. If a phase *would* break when run in a
fresh session, that is a bug in rule 1 compliance, not a reason to keep the
context.

## The four mechanisms

The model cannot clear its own context — `/clear` is a client command, not a
tool, and `--autocompact` only moves the compaction threshold. What exists:

1. **A forked skill** — `context: fork` in the skill's frontmatter. Claude Code
   runs the skill in a subagent with **no conversation history**; the skill text
   is its prompt, `model:` and `effort:` from the frontmatter apply to that
   subagent (they do not apply to an inline skill), and `background: false`
   makes the caller wait for the result in the same turn. A subagent can spawn
   subagents up to three layers deep by default, so a forked `review` still
   launches its panel. Two limits shape the skills: no subagent has
   `AskUserQuestion` (hence the `HANDOFF` block of shared rule 11), and `cd`
   does not persist between Bash calls (hence `cd <path> &&` per command).
   This is what `review`, `ship`, `archive`, `status` and `history` use.
2. **A fresh headless session** — `claude -p "/sdd:review <feature>"` from Bash.
   A real session: skills resolve, hooks and MCP work, and the panel launches
   its agents normally. The caller gets only the final report back. This is
   what `/sdd:auto` uses; a forked skill invoked inside `-p` simply waits.
3. **A plain subagent** (`Agent` tool) — isolated context for one delegated
   task. A phase is better expressed as (1); `run` uses it the other way round:
   it stays inline (its gates converse with the user) and delegates each
   section to a fresh implementer, so the orchestrator's context stays flat
   while the diffs, test output and reviewer JSON live and die in subagents.
4. **Telling the user** — for the phases that stay inline (`new`, `design`,
   `tasks`, `run`) the gate (shared rule 3) already stops there. Saying
   "`/clear` before the next phase" costs one line; the measurement above says
   it is followed about a third of the time, which is why (1) exists.

## What still costs on every request

Tool Search (Claude Code ≥ 2.1.215) discovers MCP tool schemas on demand, so the
"every server adds its schemas to every request" cost that the 42k-token
preamble measurement captured has largely moved. What remains fixed per request
is what hooks inject, one description line per skill, and MCP server
instructions; what grows is tool *output* once a server is used. That is the
order in which `/sdd:init` weighs extras: a hook or an always-on skill needs a
stronger reason than an MCP server, and the rtk hook this plugin used to ship
was retired on exactly that reasoning (see the FAQ).

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
