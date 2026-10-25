#!/usr/bin/env python3
"""Smoke: drive server.py over real stdio with a temp state file.
Ingests the four fixtures, runs the gap analysis, builds + verifies an
evidence package, prints a compact transcript. Synthetic fixtures and
a localhost stub only — NO real tool instance is contacted."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent


def call(proc, rid, name, args):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                 "method": "tools/call",
                                 "params": {"name": name,
                                            "arguments": args}}) + "\n")
    proc.stdin.flush()
    resp = json.loads(proc.stdout.readline())
    return json.loads(resp["result"]["content"][0]["text"])


def main():
    with tempfile.TemporaryDirectory() as td:
        env = {"ECLIPSE_THREAD_STATE": str(Path(td) / "state.json"),
               "PATH": "/usr/bin:/bin:/usr/local/bin",
               "PYTHONPATH": str(ROOT)}
        proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, env=env)
        try:
            proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                 "params": {"protocolVersion": "2025-03-26"}}) + "\n")
            proc.stdin.flush()
            init = json.loads(proc.stdout.readline())
            print("server:", init["result"]["serverInfo"])
            rid = 1
            for name in ("jira-dc-export.json", "model.xmi",
                         "vectorcast-coverage.json", "findings.sarif"):
                out = call(proc, rid, "ingest_fixture",
                           {"path": str(ROOT / "fixtures" / name)})
                rid += 1
                print(f"ingest {name}: {out['kind']} "
                      f"(+{out['artifacts']} artifacts, +{out['links']} links)")
            gaps = call(proc, rid, "trace_gaps", {})
            rid += 1
            print(f"trace_gaps: {gaps['gap_count']} gaps —",
                  [(g["kind"], g["artifact"]) for g in gaps["gaps"]])
            print("coverage:", gaps["coverage"])
            built = call(proc, rid, "evidence_build",
                         {"out_dir": str(Path(td) / "pkg")})
            rid += 1
            print("evidence_build:", built["package_id"][:16], "…",
                  built["json_path"].split("/")[-1])
            ver = call(proc, rid, "evidence_verify",
                       {"package_path": built["json_path"]})
            print("evidence_verify: valid =", ver["valid"],
                  f"({ver['artifacts_checked']} artifacts checked)")
        finally:
            proc.stdin.close()
            proc.wait(timeout=10)
    print("SMOKE OK")


if __name__ == "__main__":
    main()
