"""Collect reviewer verdicts from Claude Code's own records (`--collect`).

The orchestrator never transcribes a verdict. It passes, per planned
reviewer, the id of the `Agent` call it made (the `agentId` the call's result
prints, or the call's `toolu_…` id); this module finds what the harness wrote
about that call and extracts the reviewer's JSON from it:

- `<projects>/<project>/<session>/subagents/agent-<agentId>.meta.json`, written
  by the harness at launch: `agentType` (the `subagent_type` of the call — the
  trusted identity), `toolUseId`, `parentAgentId`;
- the parent transcript (the main `<session>.jsonl`, or the orchestrating
  subagent's `agent-<parentAgentId>.jsonl`): the `Agent` tool_use itself (its
  `subagent_type` must agree with the meta, its prompt must carry the scope id)
  and its tool_result (an error or interruption is a failed reviewer);
- the reviewer's own `agent-<agentId>.jsonl`: its `SubagentHandback` call and
  the harness's `{"success": true}` answer to it, which is the delivered report.

Anything missing, duplicated, contradictory or unparseable is reported as a
failed or pending collection; the caller turns both into `unavailable`
results, so the gate fails closed. Nothing here writes anywhere.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

CONTRACT_KEYS = ("reviewer_id", "scope_id", "lens", "verdict", "findings", "evidence", "status")
AGENT_ID_RE = re.compile(r"^a[0-9a-f]{8,40}$")
TOOL_USE_ID_RE = re.compile(r"^toolu_[A-Za-z0-9]{8,64}$")
# The plugin namespace Claude Code puts in front of a plugin agent's name:
# the core reviewer `sdd-qa` is launched as `sdd:sdd-qa`.
PLUGIN_PREFIX = "sdd:"
AGENT_TOOLS = {"Agent", "Task"}
HANDBACK_TOOL = "SubagentHandback"
# Parent tool_result texts that are a pointer, not a report.
POINTER_MARKERS = ("Async agent launched successfully", "delivered to you as a message from")
INTERRUPT_MARKERS = ("[Request interrupted", "<tool_use_error>")
# Without a session id, a `toolu_` id is looked for only among recent metas.
RECENT_SECONDS = 2 * 86400

PENDING = "pending"
FAILED = "failed"
COMPLETE = "complete"


@dataclass
class Collected:
    reviewer_id: str
    invocation_id: str
    state: str
    payload: dict | None = None
    reason: str | None = None
    agent_id: str | None = None
    parent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"reviewer_id": self.reviewer_id, "invocation_id": self.invocation_id,
                "agent_id": self.agent_id, "state": self.state, "reason": self.reason}


@dataclass
class _Located:
    meta_path: Path
    meta: dict
    agent_id: str
    session_dir: Path
    extra: list[str] = field(default_factory=list)


def projects_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base).expanduser() / "projects"


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                # A torn last line is a transcript still being written; the
                # record it would have carried is simply not there yet.
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _blocks(row: dict) -> list[dict]:
    content = (row.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _locate(invocation_id: str, root: Path, session_id: str | None) -> list[_Located]:
    session = session_id or "*"
    if AGENT_ID_RE.match(invocation_id):
        metas = sorted(root.glob(f"*/{session}/subagents/agent-{invocation_id}.meta.json"))
    elif TOOL_USE_ID_RE.match(invocation_id):
        needle = f'"{invocation_id}"'
        horizon = time.time() - RECENT_SECONDS
        metas = []
        for meta in sorted(root.glob(f"*/{session}/subagents/agent-*.meta.json")):
            try:
                if session_id is None and meta.stat().st_mtime < horizon:
                    continue
                if needle in meta.read_text(encoding="utf-8"):
                    metas.append(meta)
            except OSError:
                continue
    else:
        raise ValueError(
            f"invocation id {invocation_id!r} is neither an agentId (the `agentId:` line of the "
            "Agent call's result) nor a toolu_ tool_use id"
        )
    found = []
    for meta_path in metas:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        agent_id = meta_path.name[len("agent-"):-len(".meta.json")]
        if TOOL_USE_ID_RE.match(invocation_id) and meta.get("toolUseId") != invocation_id:
            continue
        found.append(_Located(meta_path, meta, agent_id, meta_path.parent.parent))
    return found


def _parent_transcript(located: _Located) -> Path:
    parent = located.meta.get("parentAgentId")
    if parent:
        return located.session_dir / "subagents" / f"agent-{parent}.jsonl"
    return located.session_dir.parent / f"{located.session_dir.name}.jsonl"


def _handback_report(rows: Iterable[dict]) -> tuple[str | None, str | None]:
    """The delivered report, or (None, reason) when there is none or several.

    Several different delivered reports (a reviewer resumed with SendMessage
    hands back once per run) are ambiguous and fail closed: relaunch a fresh
    reviewer instead of resuming one whose verdict the gate must collect.
    """
    calls: dict[str, str] = {}
    delivered: list[str] = []
    for row in rows:
        for block in _blocks(row):
            if block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL:
                message = (block.get("input") or {}).get("message")
                if isinstance(message, str):
                    calls[str(block.get("id"))] = message
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                if block.get("is_error"):
                    continue
                try:
                    answer = json.loads(_text(block.get("content")))
                except ValueError:
                    continue
                if isinstance(answer, dict) and answer.get("success") is True:
                    delivered.append(calls[block["tool_use_id"]])
    if len(set(delivered)) > 1:
        return None, "the reviewer delivered more than one different report"
    return (delivered[0], None) if delivered else (None, None)


def extract_payload(text: str) -> tuple[dict | None, str | None]:
    """The single result object of the reviewer contract inside a report.

    Every JSON object in the text (raw or inside a ```json fence) that carries
    all the contract keys is a candidate. Exactly one distinct candidate is the
    payload; none, or two that differ, is a malformed report — never a guess.
    """
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    index = text.find("{")
    while index != -1:
        try:
            value, _end = decoder.raw_decode(text, index)
        except ValueError:
            value = None
        if isinstance(value, dict) and all(key in value for key in CONTRACT_KEYS):
            if value not in candidates:
                candidates.append(value)
        index = text.find("{", index + 1)
    if not candidates:
        return None, "the reviewer's report carries no JSON result object with the contract keys " + ", ".join(CONTRACT_KEYS)
    if len(candidates) > 1:
        return None, "the reviewer's report carries more than one different JSON result object"
    return candidates[0], None


def _identity_matches(agent_type: Any, reviewer_id: str) -> bool:
    return isinstance(agent_type, str) and agent_type in {reviewer_id, PLUGIN_PREFIX + reviewer_id}


def collect_one(reviewer_id: str, scope_id: str, invocation_id: str, root: Path,
                session_id: str | None) -> Collected:
    out = Collected(reviewer_id, invocation_id, FAILED)
    try:
        found = _locate(invocation_id, root, session_id)
    except ValueError as exc:
        out.reason = str(exc)
        return out
    if not found:
        out.reason = (f"no Claude Code record of invocation {invocation_id} under {root}"
                      + (f" for session {session_id}" if session_id else "")
                      + ": pass the agentId printed by that Agent call's result")
        return out
    if len(found) > 1:
        out.reason = f"invocation {invocation_id} is ambiguous: {len(found)} transcripts record it"
        return out
    located = found[0]
    out.agent_id = located.agent_id
    meta = located.meta
    # (a) trusted identity: what the harness recorded as the launched type.
    if not _identity_matches(meta.get("agentType"), reviewer_id):
        out.reason = (f"invocation {invocation_id} launched {meta.get('agentType')!r}, "
                      f"not the planned reviewer {reviewer_id!r}")
        return out
    tool_use_id = meta.get("toolUseId")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        out.reason = f"the record of invocation {invocation_id} names no Agent tool_use"
        return out
    parent_path = _parent_transcript(located)
    out.parent = str(parent_path)
    call = result = None
    for row in _read_jsonl(parent_path):
        for block in _blocks(row):
            if block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                if call is not None:
                    out.reason = f"tool_use {tool_use_id} appears twice in its parent transcript"
                    return out
                call = block
            elif block.get("type") == "tool_result" and block.get("tool_use_id") == tool_use_id:
                result = block
    if call is None:
        out.reason = f"the Agent call {tool_use_id} is not in its parent transcript {parent_path.name}"
        return out
    call_input = call.get("input") or {}
    if call.get("name") not in AGENT_TOOLS or not _identity_matches(call_input.get("subagent_type"), reviewer_id) \
            or call_input.get("subagent_type") != meta.get("agentType"):
        out.reason = (f"the call {tool_use_id} is {call.get('name')}({call_input.get('subagent_type')!r}), "
                      f"not an Agent call launching {reviewer_id!r}")
        return out
    if scope_id not in str(call_input.get("prompt", "")):
        out.reason = (f"the prompt of {reviewer_id}'s Agent call does not carry the exact scope id "
                      f"{scope_id!r}: it was launched for another scope")
        return out
    # (b) the call's own result: an error or an interruption is a dead reviewer.
    result_text = _text(result.get("content")) if result else ""
    if result is not None and (result.get("is_error") or any(m in result_text for m in INTERRUPT_MARKERS)):
        out.reason = f"the Agent call for {reviewer_id} ended in an error or interruption: " + result_text[:160]
        return out
    report, problem = _handback_report(_read_jsonl(located.session_dir / "subagents" / f"agent-{located.agent_id}.jsonl"))
    if problem:
        out.reason = problem
        return out
    if report is None and result is not None and result_text.strip() \
            and not any(m in result_text for m in POINTER_MARKERS):
        # A harness without SubagentHandback returns the report as the result.
        report = result_text
    if report is None:
        out.state = PENDING
        out.reason = (f"{reviewer_id} has not delivered its report yet (still running, or it ended "
                      "without SubagentHandback): re-run this same command, with --wait to block "
                      "until it arrives; never reconstruct the verdict by hand")
        return out
    # (c) the reviewer's JSON, extracted by rule — not chosen by anyone.
    payload, problem = extract_payload(report)
    if payload is None:
        out.reason = problem
        return out
    out.state, out.payload = COMPLETE, payload
    return out


def collect(invocations: Mapping[str, str], scopes: Mapping[str, str], *, root: Path,
            session_id: str | None, wait: float = 0, poll: float = 5.0) -> dict[str, Collected]:
    """Collect every reviewer of `invocations` ({planned_reviewer_id: id}).

    `scopes` maps each planned reviewer to its exact scope id. Polls while any
    reviewer is still pending and `wait` seconds have not elapsed.
    """
    ids = list(invocations.values())
    if len(set(ids)) != len(ids):
        raise ValueError("the same invocation id is given for two reviewers")
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        collected = {rid: collect_one(rid, scopes[rid], inv, root, session_id) for rid, inv in invocations.items()}
        agents = [c.agent_id for c in collected.values() if c.agent_id]
        if len(set(agents)) != len(agents):
            raise ValueError("two reviewers resolve to the same agent")
        if not any(c.state == PENDING for c in collected.values()) or time.monotonic() >= deadline:
            break
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
    parents = {c.parent for c in collected.values() if c.parent}
    if len(parents) > 1:
        # One panel is one orchestrator: reviewers launched by different
        # sessions or forks are not one caller's collection.
        raise ValueError("the reviewers were launched by different orchestrators: "
                         + ", ".join(sorted(Path(p).name for p in parents)))
    return collected
