#!/usr/bin/env python3
"""Tiny local OTLP/HTTP (JSON) metrics sink for SDD usage tracking.

Claude Code exports OTel metrics (claude_code.token.usage, claude_code.cost.usage)
to this sink; we tag each datapoint with the active SDD task (feature/phase,
written by usage-mark.sh) and append it to .sdd-usage/otel.jsonl. Subagent
usage is included (query_source attribute). Stdlib only.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

USAGE_DIR = os.environ.get("SDD_USAGE_DIR") or os.path.join(os.getcwd(), ".sdd-usage")
OUT = os.path.join(USAGE_DIR, "otel.jsonl")
TASK = os.path.join(USAGE_DIR, "current-task")
STATE = os.path.join(USAGE_DIR, "sink-state.json")

METRICS = {"claude_code.token.usage": "tokens", "claude_code.cost.usage": "cost"}


def attr_map(attrs):
    out = {}
    for a in attrs or []:
        v = a.get("value", {})
        out[a.get("key")] = v.get("stringValue") or v.get("intValue") or v.get("doubleValue")
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n)
        if self.path.rstrip("/").endswith("/v1/metrics"):
            try:
                self.ingest(json.loads(body))
            except Exception:
                pass  # never break the exporter
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def ingest(self, payload):
        task = ""
        try:
            with open(TASK) as f:
                task = f.read().strip()
        except OSError:
            pass
        try:
            with open(STATE) as f:
                state = json.load(f)
        except Exception:
            state = {}
        rows = []
        for rm in payload.get("resourceMetrics", []):
            for sm in rm.get("scopeMetrics", []):
                for m in sm.get("metrics", []):
                    kind = METRICS.get(m.get("name"))
                    if not kind:
                        continue
                    s = m.get("sum", {})
                    cumulative = s.get("aggregationTemporality") == 2
                    for dp in s.get("dataPoints", []):
                        at = attr_map(dp.get("attributes"))
                        val = dp.get("asDouble")
                        if val is None:
                            val = float(dp.get("asInt", 0))
                        key = "|".join(str(x) for x in (
                            m.get("name"), at.get("session.id"), at.get("type"),
                            at.get("model"), at.get("query_source")))
                        if cumulative:
                            prev = state.get(key, 0)
                            delta = val - prev if val >= prev else val
                            state[key] = val
                        else:
                            delta = val
                        if delta <= 0:
                            continue
                        rows.append({
                            "ts": int(time.time()), "metric": kind,
                            "type": at.get("type"), "model": at.get("model"),
                            "session": at.get("session.id"),
                            "source": at.get("query_source"),
                            "value": delta, "task": task,
                        })
        if rows:
            os.makedirs(USAGE_DIR, exist_ok=True)
            with open(OUT, "a") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            with open(STATE, "w") as f:
                json.dump(state, f)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4318
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
