#!/usr/bin/env python3
"""Jira Data Center bridge client (simulator-tested) — Eclipse Thread.

Powered by Cyan Eclipse Technologies (cetech.ai).

Talks to a Jira Data Center instance over its sanctioned REST v2 API
(search + issue read) and returns a normalized export in exactly the
shape the Weaver's Jira ingest adapter consumes from a fixture file —
one code path for fixture, stub, and (config-only difference) a real
Data Center instance. [verify on a real instance] per the family spec:
auth (token/basic), per-version API surface, and rate behavior must be
confirmed against the customer's install before any live claim.

Design law (family spec §3): local-only transport — the base URL is
operator-configured and is expected to be an enclave-local instance;
the bridge makes no other network calls. Reads only in v0.1.

CLI:  python3 jira_bridge.py http://127.0.0.1:8931   # prints a summary
"""
import json
import sys
import urllib.request

TOOL_NAME = "jira-dc-bridge (simulator)"


def _get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_export(base_url: str) -> dict:
    """Fetch all issues via the DC search endpoint + provenance meta.

    Returns the normalized export dict {export_meta, issues} — the same
    shape as fixtures/jira-dc-export.json.
    """
    base = base_url.rstrip("/")
    meta = {}
    try:
        meta = _get_json(f"{base}/thread/meta")
    except Exception:
        meta = {}  # a real DC instance has no /thread/meta; meta is a stub extra
    search = _get_json(f"{base}/rest/api/2/search?maxResults=1000")
    issues = search.get("issues", [])
    # Round-trip one issue through the point endpoint as a liveness proof
    # of the second sanctioned surface the bridge depends on.
    if issues:
        _get_json(f"{base}/rest/api/2/issue/{issues[0]['key']}")
    return {
        "export_meta": {
            "tool": TOOL_NAME,
            "tool_version": meta.get("tool_version", "unknown [verify]"),
            "run_id": meta.get("run_id", "bridge-fetch"),
            "exported_at": meta.get("exported_at"),
            "base_url": base,
        },
        "issues": issues,
    }


def main():
    if len(sys.argv) != 2:
        print("usage: jira_bridge.py <base-url>", file=sys.stderr)
        return 2
    export = fetch_export(sys.argv[1])
    kinds = {}
    for i in export["issues"]:
        t = i["fields"]["issuetype"]["name"]
        kinds[t] = kinds.get(t, 0) + 1
    print(json.dumps({"base_url": sys.argv[1],
                      "run_id": export["export_meta"]["run_id"],
                      "issues": len(export["issues"]),
                      "by_type": kinds}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
