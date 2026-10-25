#!/usr/bin/env python3
"""Eclipse Thread MCP — v0.1.0 (Evidence Weaver core + Jira DC mock bridge).

Powered by Cyan Eclipse Technologies (cetech.ai).

Eclipse Thread — on-prem MCP bridges for the legacy software-engineering
toolchain, plus the Evidence Weaver that joins their records into one
traceable thread.

v0.1 SCOPE (honest labels — SIMULATOR): no real Jira, Coverity, Cameo,
or VectorCAST instance exists in this environment. Every target is a
fixture or a mock, and every surface says so. What v0.1 proves:

  * The Weaver core: an artifact graph (requirements, model elements,
    code units, test cases, findings, tickets) with typed trace links,
    assembled from four export shapes — a Jira-DC-shaped REST export, a
    SARIF findings file, a VectorCAST-shaped coverage report, and an
    XMI-lite model export. Every artifact carries provenance {source
    tool, version, run id, source ref}.
  * Trace-gap analysis, GAP-FIRST (family spec §5): unlinked
    requirements, untested code units, orphan test cases, findings
    without tickets — plus per-layer trace coverage.
  * Evidence packages: a deterministic bundle (JSON + MD summary) whose
    manifest hash-chains every artifact and link, verifiable standalone
    — recompute the hashes and any substitution shows.
  * The Jira DC bridge (mock): a client written against the DC REST v2
    shape, exercised over REAL HTTP against a shipped stdlib stub
    server (jira_stub.py). Same code path would address a real Data
    Center instance — a config-only difference [verify on a real
    instance]. Reads only.

QUALIFICATION POSTURE (family spec §6, binding): v0.1 is evidence
ASSEMBLY and TRANSPORT only. It generates no verification results of
its own — no analysis runs, no test authoring, no coverage computation;
coverage numbers are the source tools' own, quoted with their run
receipts. No compliance or tool-qualification claims are made.

Receipts: every ingest, gap run, and evidence build appends a
hash-chained receipt to the local store — append-only, verifiable.

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0), stdlib only.
State file: $ECLIPSE_THREAD_STATE or ./data/state.json beside this file.
"""
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import jira_bridge

STATE_PATH = Path(os.environ.get(
    "ECLIPSE_THREAD_STATE",
    Path(__file__).parent / "data" / "state.json"))

TOOL_VERSION = "0.1.0"
SOURCE_KINDS = ("jira-dc-export", "sarif", "vectorcast-report", "xmi-lite")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ToolError(Exception):
    pass


# ------------------------------------------------------------------ state
def empty_state() -> dict:
    return {"artifacts": {}, "links": [], "receipts": []}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return empty_state()


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True),
                          encoding="utf-8")


# ---------------------------------------------------------------- receipts
def emit_receipt(state: dict, rtype: str, detail: dict) -> dict:
    prev = state["receipts"][-1]["hash"] if state["receipts"] else "GENESIS"
    entry = {"seq": len(state["receipts"]) + 1, "ts": now(), "type": rtype,
             "detail": detail, "prev": prev}
    entry["hash"] = sha(canon({k: entry[k] for k in
                               ("seq", "ts", "type", "detail", "prev")}))
    state["receipts"].append(entry)
    return entry


def verify_receipt_chain(receipts) -> bool:
    prev = "GENESIS"
    for e in receipts:
        expect = sha(canon({k: e[k] for k in
                            ("seq", "ts", "type", "detail", "prev")}))
        if e.get("prev") != prev or e.get("hash") != expect:
            return False
        prev = e["hash"]
    return True


# ------------------------------------------------------------------- graph
def upsert_artifact(state, aid, atype, attributes, provenance):
    art = state["artifacts"].get(aid)
    if art is None:
        art = {"id": aid, "type": atype, "attributes": {},
               "provenance": dict(provenance)}
        art["provenance"]["sources"] = [provenance["source_ref"]]
        state["artifacts"][aid] = art
    art["attributes"].update(attributes)
    if provenance["source_ref"] not in art["provenance"]["sources"]:
        art["provenance"]["sources"].append(provenance["source_ref"])
        art["provenance"]["sources"].sort()
    for k in ("source_tool", "tool_version", "run_id"):
        art["provenance"][k] = provenance[k]
    return art


def add_link(state, frm, to, ltype, source_ref):
    link = {"from": frm, "to": to, "type": ltype, "source_ref": source_ref}
    if link not in state["links"]:
        state["links"].append(link)
    return link


def links_where(state, **kw):
    return [l for l in state["links"]
            if all(l.get(k) == v for k, v in kw.items())]


def artifacts_of(state, atype):
    return sorted((a for a in state["artifacts"].values()
                   if a["type"] == atype), key=lambda a: a["id"])


def record_hash(art) -> str:
    """Hash of an artifact's evidence content (provenance excluded — it
    is metadata about the record, folded separately via receipts)."""
    return sha(canon({"id": art["id"], "type": art["type"],
                      "attributes": art["attributes"]}))


def link_hash(link) -> str:
    return sha(canon({"from": link["from"], "to": link["to"],
                      "type": link["type"]}))


# ----------------------------------------------------------------- ingest
def _prov(meta, source_ref):
    return {"source_tool": meta.get("tool", "unknown"),
            "tool_version": meta.get("tool_version", "unknown"),
            "run_id": meta.get("run_id", "unknown"),
            "source_ref": source_ref, "ingested_at": now()}


def ingest_jira(state, export, source_ref):
    meta = export.get("export_meta", {})
    prov = _prov({**meta, "tool": meta.get("tool", "jira-dc-bridge (simulator)")},
                 source_ref)
    counts = {"artifacts": 0, "links": 0}
    for issue in export.get("issues", []):
        f = issue.get("fields", {})
        itype = f.get("issuetype", {}).get("name", "")
        atype = "requirement" if itype == "Requirement" else "ticket"
        upsert_artifact(state, issue["key"], atype,
                        {"summary": f.get("summary", ""),
                         "status": f.get("status", {}).get("name", ""),
                         "jira_type": itype,
                         "labels": f.get("labels", [])}, prov)
        counts["artifacts"] += 1
    return counts


def ingest_sarif(state, doc, source_ref):
    counts = {"artifacts": 0, "links": 0}
    for run in doc.get("runs", []):
        drv = run.get("tool", {}).get("driver", {})
        props = run.get("properties", {})
        prov = _prov({"tool": f"sarif:{drv.get('name', 'unknown')}",
                      "tool_version": drv.get("version", "unknown"),
                      "run_id": props.get("run_id", "unknown")}, source_ref)
        for res in run.get("results", []):
            p = res.get("properties", {})
            fid = p.get("finding_id") or f"{res.get('ruleId', 'FINDING')}?"
            locs = res.get("locations", [])
            uri, line = None, None
            if locs:
                pl = locs[0].get("physicalLocation", {})
                uri = pl.get("artifactLocation", {}).get("uri")
                line = pl.get("region", {}).get("startLine")
            upsert_artifact(state, fid, "finding",
                            {"rule_id": res.get("ruleId", ""),
                             "checker": p.get("checker", res.get("ruleId", "")),
                             "level": res.get("level", ""),
                             "message": res.get("message", {}).get("text", ""),
                             "location": {"uri": uri, "line": line}}, prov)
            counts["artifacts"] += 1
            if uri:
                upsert_artifact(state, uri, "code_unit", {"name": uri}, prov)
                add_link(state, fid, uri, "found_in", source_ref)
                counts["links"] += 1
            if p.get("ticket_key"):
                add_link(state, fid, p["ticket_key"], "tracked_by", source_ref)
                counts["links"] += 1
    return counts


def ingest_vectorcast(state, doc, source_ref):
    meta = doc.get("export_meta", {})
    prov = _prov(meta, source_ref)
    counts = {"artifacts": 0, "links": 0}
    for unit in doc.get("units", []):
        upsert_artifact(state, unit["name"], "code_unit",
                        {"name": unit["name"],
                         "coverage": {"statement_pct": unit.get("statement_cov"),
                                      "branch_pct": unit.get("branch_cov"),
                                      "mcdc_pct": unit.get("mcdc_cov"),
                                      "environment": meta.get("environment"),
                                      "run_id": meta.get("run_id")}}, prov)
        counts["artifacts"] += 1
    for tc in doc.get("test_cases", []):
        upsert_artifact(state, tc["id"], "test_case",
                        {"name": tc.get("name", ""),
                         "result": tc.get("result", ""),
                         "environment": meta.get("environment")}, prov)
        counts["artifacts"] += 1
        for req in tc.get("verifies", []):
            add_link(state, tc["id"], req, "verifies", source_ref)
            counts["links"] += 1
        for unit in tc.get("exercises", []):
            upsert_artifact(state, unit, "code_unit", {"name": unit}, prov)
            add_link(state, tc["id"], unit, "exercises", source_ref)
            counts["links"] += 1
    return counts


def ingest_xmi(state, text, source_ref):
    root = ET.fromstring(text)
    prov = _prov({"tool": root.get("tool", "cameo-xmi-bridge (simulator)"),
                  "tool_version": root.get("toolVersion", "unknown"),
                  "run_id": root.get("runId", "unknown")}, source_ref)
    counts = {"artifacts": 0, "links": 0}
    for el in root.iter("modelElement"):
        mid = el.get("id")
        upsert_artifact(state, mid, "model_element",
                        {"name": el.get("name", ""), "kind": el.get("kind", "")},
                        prov)
        counts["artifacts"] += 1
        for sat in el.iter("satisfy"):
            add_link(state, mid, sat.get("requirement"), "satisfies", source_ref)
            counts["links"] += 1
        for imp in el.iter("implements"):
            cu = imp.get("codeUnit")
            upsert_artifact(state, cu, "code_unit", {"name": cu}, prov)
            add_link(state, mid, cu, "implements", source_ref)
            counts["links"] += 1
    return counts


def detect_and_ingest(state, raw_text, source_ref):
    text = raw_text.lstrip()
    if text.startswith("<?xml") or text.startswith("<xmi"):
        return "xmi-lite", ingest_xmi(state, raw_text, source_ref)
    doc = json.loads(raw_text)
    if "runs" in doc:
        return "sarif", ingest_sarif(state, doc, source_ref)
    tool = doc.get("export_meta", {}).get("tool", "")
    if "vectorcast" in tool:
        return "vectorcast-report", ingest_vectorcast(state, doc, source_ref)
    if "issues" in doc:
        return "jira-dc-export", ingest_jira(state, doc, source_ref)
    raise ToolError("unrecognized export shape (expected Jira DC export, "
                    "SARIF, VectorCAST-shaped report, or XMI-lite)")


# ------------------------------------------------------------ gap analysis
def compute_gaps(state):
    """Gap-first trace analysis (spec §5). Returns gaps + layer coverage.

    Gap kinds (exactly these four):
      unlinked_requirement — requirement no model element satisfies
      untested_code        — code unit no test case exercises
      orphan_test          — test case that verifies no requirement
      finding_without_ticket — finding with no tracked_by ticket link
    """
    reqs = artifacts_of(state, "requirement")
    models = artifacts_of(state, "model_element")
    codes = artifacts_of(state, "code_unit")
    tests = artifacts_of(state, "test_case")
    findings = artifacts_of(state, "finding")

    satisfied = {l["to"] for l in links_where(state, type="satisfies")}
    implemented = {l["to"] for l in links_where(state, type="implements")}
    exercised = {l["to"] for l in links_where(state, type="exercises")}
    verified = {l["to"] for l in links_where(state, type="verifies")}
    tracked = {l["from"] for l in links_where(state, type="tracked_by")}

    gaps = []
    for r in reqs:
        if r["id"] not in satisfied:
            gaps.append({"kind": "unlinked_requirement", "artifact": r["id"],
                         "detail": "No model element satisfies this requirement."})
    for c in codes:
        if c["id"] not in exercised:
            gaps.append({"kind": "untested_code", "artifact": c["id"],
                         "detail": "No test case exercises this code unit."})
    for t in tests:
        if not links_where(state, type="verifies", **{"from": t["id"]}):
            gaps.append({"kind": "orphan_test", "artifact": t["id"],
                         "detail": "Test case verifies no requirement."})
    for f in findings:
        if f["id"] not in tracked:
            gaps.append({"kind": "finding_without_ticket", "artifact": f["id"],
                         "detail": "Finding has no tracking ticket."})
    gaps.sort(key=lambda g: (g["kind"], g["artifact"]))

    def pct(part, whole):
        return round(100.0 * part / whole, 1) if whole else None

    coverage = {
        "requirements_with_model": pct(len([r for r in reqs if r["id"] in satisfied]), len(reqs)),
        "model_elements_with_code": pct(len([m for m in models if m["id"] in
                                             {l["from"] for l in links_where(state, type="implements")}]), len(models)),
        "code_units_tested": pct(len([c for c in codes if c["id"] in exercised]), len(codes)),
        "tests_tracing_to_requirements": pct(len([t for t in tests if links_where(state, type="verifies", **{"from": t["id"]})]), len(tests)),
        "requirements_verified_by_tests": pct(len([r for r in reqs if r["id"] in verified]), len(reqs)),
        "findings_with_tickets": pct(len([f for f in findings if f["id"] in tracked]), len(findings)),
    }
    matrix = []
    for r in reqs:
        mes = sorted(l["from"] for l in links_where(state, type="satisfies", to=r["id"]))
        cus = sorted({l["to"] for me in mes
                      for l in links_where(state, type="implements", **{"from": me})})
        tcs = sorted(l["from"] for l in links_where(state, type="verifies", to=r["id"]))
        matrix.append({"requirement": r["id"], "model_elements": mes,
                       "code_units": cus, "test_cases": tcs})
    return {"gaps": gaps, "gap_count": len(gaps), "coverage": coverage,
            "matrix": matrix,
            "counts": {"requirements": len(reqs), "model_elements": len(models),
                       "code_units": len(codes), "test_cases": len(tests),
                       "findings": len(findings),
                       "tickets": len(artifacts_of(state, "ticket")),
                       "links": len(state["links"])}}


# ---------------------------------------------------------- evidence packages
def package_identity(state):
    """Content identity of the current graph: fold of every artifact and
    link hash, GENESIS-anchored. Rebuilds over the same graph reproduce
    the same package_id (build receipts are recorded, not folded)."""
    h = "GENESIS"
    for aid in sorted(state["artifacts"]):
        h = sha(h + record_hash(state["artifacts"][aid]))
    for lh in sorted(link_hash(l) for l in state["links"]):
        h = sha(h + lh)
    return h


def build_package(state):
    gap = compute_gaps(state)
    pkg = {
        "package": "eclipse-thread-evidence",
        "package_version": TOOL_VERSION,
        "package_id": package_identity(state),
        "simulator": True,
        "note": ("Assembled from FIXTURE/MOCK exports (simulator). Assembly "
                 "and transport only — no verification results generated "
                 "(family spec §6). No compliance claims."),
        "receipt_head_at_build": (state["receipts"][-1]["hash"]
                                  if state["receipts"] else "GENESIS"),
        "receipts_covered": len(state["receipts"]),
        "artifacts": [state["artifacts"][aid] for aid in sorted(state["artifacts"])],
        "artifact_hashes": {aid: record_hash(state["artifacts"][aid])
                            for aid in sorted(state["artifacts"])},
        "links": sorted(state["links"],
                        key=lambda l: (l["from"], l["to"], l["type"])),
        "link_hashes": sorted(link_hash(l) for l in state["links"]),
        "gap_report": gap,
    }
    return pkg


def verify_package(pkg):
    problems = []
    arts = {a["id"]: a for a in pkg.get("artifacts", [])}
    for aid, expect in pkg.get("artifact_hashes", {}).items():
        if aid not in arts:
            problems.append(f"artifact {aid} missing from package body")
        elif record_hash(arts[aid]) != expect:
            problems.append(f"artifact {aid} hash mismatch (content substituted?)")
    link_hashes = sorted(link_hash(l) for l in pkg.get("links", []))
    if link_hashes != pkg.get("link_hashes"):
        problems.append("link set hash mismatch (links substituted?)")
    # Recompute the identity fold from the package's own body.
    h = "GENESIS"
    for aid in sorted(arts):
        h = sha(h + record_hash(arts[aid]))
    for lh in link_hashes:
        h = sha(h + lh)
    if h != pkg.get("package_id"):
        problems.append("package_id does not match recomputed content fold")
    return {"valid": not problems, "problems": problems,
            "package_id": pkg.get("package_id"),
            "artifacts_checked": len(arts)}


def package_markdown(pkg):
    g = pkg["gap_report"]
    out = [f"# Eclipse Thread — Evidence Package (SIMULATOR)",
           "",
           f"Package ID: `{pkg['package_id']}` · artifacts: "
           f"{len(pkg['artifacts'])} · links: {len(pkg['links'])} · "
           f"receipts covered: {pkg['receipts_covered']}",
           "",
           "> Assembled from fixture/mock exports. Assembly and transport "
           "only — no verification results generated, no compliance claims "
           "(family spec §6).",
           "",
           f"## Gaps first — {g['gap_count']} open",
           ""]
    if g["gaps"]:
        for gap in g["gaps"]:
            out.append(f"- **{gap['kind']}** — `{gap['artifact']}`: {gap['detail']}")
    else:
        out.append("- None. The thread is complete for the ingested records.")
    out += ["", "## Trace coverage", ""]
    for k, v in g["coverage"].items():
        out.append(f"- {k}: {v}%")
    out += ["", "## Traceability matrix", "",
            "| Requirement | Model elements | Code units | Test cases |",
            "|---|---|---|---|"]
    for row in g["matrix"]:
        out.append("| {} | {} | {} | {} |".format(
            row["requirement"],
            ", ".join(row["model_elements"]) or "—",
            ", ".join(row["code_units"]) or "—",
            ", ".join(row["test_cases"]) or "—"))
    out += ["", "## Provenance", "",
            "| Artifact | Type | Source tool | Run |",
            "|---|---|---|---|"]
    for a in pkg["artifacts"]:
        p = a["provenance"]
        out.append(f"| {a['id']} | {a['type']} | {p['source_tool']} "
                   f"{p['tool_version']} | {p['run_id']} |")
    out.append("")
    return "\n".join(out)


# -------------------------------------------------------------------- tools
def t_ingest_fixture(state, args):
    if args.get("reset"):
        state["artifacts"], state["links"] = {}, []
    if args.get("jira_base_url"):
        export = jira_bridge.fetch_export(args["jira_base_url"])
        kind, counts = "jira-dc-export", ingest_jira(
            state, export, f"bridge:{args['jira_base_url']}")
        source = f"jira bridge (mock) @ {args['jira_base_url']}"
    elif args.get("path"):
        raw = Path(args["path"]).read_text(encoding="utf-8")
        kind, counts = detect_and_ingest(state, raw, f"file:{args['path']}")
        source = args["path"]
    else:
        raise ToolError("ingest_fixture needs `path` (fixture file) or "
                        "`jira_base_url` (bridge fetch from a stub/DC-shaped host)")
    r = emit_receipt(state, "ingest", {"kind": kind, "source": source,
                                       **counts})
    return {"status": "ingested", "kind": kind, "source": source,
            **counts, "total_artifacts": len(state["artifacts"]),
            "total_links": len(state["links"]), "receipt_seq": r["seq"],
            "simulator": True}


def t_graph_query(state, args):
    if args.get("artifact_id"):
        art = state["artifacts"].get(args["artifact_id"])
        if art is None:
            raise ToolError(f"no artifact {args['artifact_id']}")
        return {"artifact": art,
                "links_out": links_where(state, **{"from": art["id"]}),
                "links_in": links_where(state, to=art["id"])}
    if args.get("artifact_type"):
        arts = artifacts_of(state, args["artifact_type"])
        return {"type": args["artifact_type"], "count": len(arts),
                "artifacts": arts}
    counts = {}
    for a in state["artifacts"].values():
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    return {"counts_by_type": counts, "total_artifacts": len(state["artifacts"]),
            "total_links": len(state["links"]),
            "receipts": len(state["receipts"]),
            "receipt_chain_valid": verify_receipt_chain(state["receipts"])}


def t_trace_gaps(state, args):
    gap = compute_gaps(state)
    r = emit_receipt(state, "trace_gaps", {"gap_count": gap["gap_count"],
                                           "kinds": [g["kind"] for g in gap["gaps"]]})
    return {**gap, "receipt_seq": r["seq"],
            "note": "Gap-first (spec §5): what is missing leads the report."}


def t_evidence_build(state, args):
    pkg = build_package(state)
    out_dir = Path(args.get("out_dir") or (STATE_PATH.parent / "packages"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"evidence-package-{pkg['package_id'][:12]}"
    jpath = out_dir / f"{stem}.json"
    mpath = out_dir / f"{stem}.md"
    jpath.write_text(json.dumps(pkg, indent=1, sort_keys=True), encoding="utf-8")
    mpath.write_text(package_markdown(pkg), encoding="utf-8")
    r = emit_receipt(state, "evidence_build",
                     {"package_id": pkg["package_id"],
                      "artifacts": len(pkg["artifacts"]),
                      "gaps": pkg["gap_report"]["gap_count"]})
    return {"package_id": pkg["package_id"], "json_path": str(jpath),
            "md_path": str(mpath), "artifacts": len(pkg["artifacts"]),
            "links": len(pkg["links"]),
            "gap_count": pkg["gap_report"]["gap_count"],
            "receipt_seq": r["seq"], "simulator": True}


def t_evidence_verify(state, args):
    if not args.get("package_path"):
        raise ToolError("evidence_verify needs `package_path`")
    pkg = json.loads(Path(args["package_path"]).read_text(encoding="utf-8"))
    out = verify_package(pkg)
    out["receipt_chain_valid_in_store"] = verify_receipt_chain(state["receipts"])
    return out


TOOLS = {
    "ingest_fixture": (t_ingest_fixture,
                       "Ingest one export into the artifact graph: a local fixture file (`path`) — Jira-DC-shaped JSON, SARIF, VectorCAST-shaped JSON, or XMI-lite XML — or a live bridge fetch (`jira_base_url`) from a stub/DC-shaped host over real HTTP. Every artifact gains provenance {source tool, version, run id, source ref}. `reset=true` clears the graph first. SIMULATOR: fixtures/mocks only.",
                       {"path": {"type": "string"}, "jira_base_url": {"type": "string"},
                        "reset": {"type": "boolean"}}, []),
    "graph_query": (t_graph_query,
                    "Query the artifact graph: no args = counts by type + receipt-chain check; `artifact_type` = list that type; `artifact_id` = one artifact with its in/out trace links.",
                    {"artifact_type": {"type": "string"}, "artifact_id": {"type": "string"}}, []),
    "trace_gaps": (t_trace_gaps,
                   "Gap-first trace analysis: unlinked requirements, untested code units, orphan test cases, findings without tickets — plus the requirement/model/code/test matrix and per-layer coverage percentages.",
                   {}, []),
    "evidence_build": (t_evidence_build,
                       "Assemble a deterministic evidence package (JSON + Markdown summary) from the current graph: hash-chained manifest over every artifact and link, gap report leading. Optional `out_dir`.",
                       {"out_dir": {"type": "string"}}, []),
    "evidence_verify": (t_evidence_verify,
                        "Verify a built evidence package STANDALONE: recompute every artifact hash, the link set, and the package identity fold from the package body; any substitution is named.",
                        {"package_path": {"type": "string"}}, ["package_path"]),
}


def tool_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for name, (_, desc, props, req) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-thread", "version": TOOL_VERSION}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        state = load_state()
        try:
            out = TOOLS[name][0](state, args)
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, indent=1)}]}}
        except ToolError as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None  # notification


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line))
        except Exception as e:  # never crash the transport
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
