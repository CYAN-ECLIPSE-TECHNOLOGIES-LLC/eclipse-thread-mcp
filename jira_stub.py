#!/usr/bin/env python3
"""Jira Data Center STUB (simulator) — Eclipse Thread.

Powered by Cyan Eclipse Technologies (cetech.ai).

A stdlib http.server that serves the shipped fixture export over REAL
HTTP in the Jira Data Center REST v2 shape, so the bridge client can be
exercised end-to-end without a Jira license or a network enclave. This
is a simulator: it proves the bridge's HTTP path, not a real instance.
[verify on a real Data Center instance] per the family spec.

Endpoints (subset of the DC REST v2 surface the bridge uses):
  GET /thread/meta            -> bridge provenance meta (simulator extra)
  GET /rest/api/2/search      -> {"issues": [...]} (JQL accepted, ignored)
  GET /rest/api/2/issue/{key} -> one issue, or 404

Run standalone:  python3 jira_stub.py --port 8931
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

FIXTURE = Path(__file__).parent / "fixtures" / "jira-dc-export.json"
EXPORT = json.loads(FIXTURE.read_text(encoding="utf-8"))
ISSUES = {i["key"]: i for i in EXPORT["issues"]}
META = EXPORT["export_meta"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the stub quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/thread/meta":
            return self._send(200, {"tool_version": META["tool_version"],
                                    "run_id": META["run_id"],
                                    "exported_at": META["exported_at"]})
        if path == "/rest/api/2/search":
            return self._send(200, {"expand": "names", "startAt": 0,
                                    "maxResults": len(EXPORT["issues"]),
                                    "total": len(EXPORT["issues"]),
                                    "issues": EXPORT["issues"]})
        if path.startswith("/rest/api/2/issue/"):
            key = path.rsplit("/", 1)[-1]
            if key in ISSUES:
                return self._send(200, ISSUES[key])
            return self._send(404, {"errorMessages": [f"Issue {key} not found (stub)"]})
        return self._send(404, {"errorMessages": ["unknown path (stub)"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = HTTPServer((args.host, args.port), Handler)
    print(f"jira stub (simulator) on http://{args.host}:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
