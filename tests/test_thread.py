"""Eclipse Thread v0.1 tests — Weaver core + Jira DC mock bridge.

Run: python3 -m unittest discover tests   (from the product dir)

The fixtures plant EXACTLY three gaps, and the gap tests assert that
known answer:
  GAP-1  unlinked_requirement   ECL-104 (no model element satisfies it)
  GAP-2  untested_code          telemetry_codec.c (no test exercises it)
  GAP-3  finding_without_ticket FIND-3 (no ticket_key in the SARIF)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ECLIPSE_THREAD_STATE"] = str(
    Path(tempfile.mkdtemp()) / "state.json")

import server  # noqa: E402
import jira_bridge  # noqa: E402
import jira_stub  # noqa: E402

FIX = ROOT / "fixtures"


def fresh_state():
    st = server.empty_state()
    for name in ("jira-dc-export.json", "model.xmi",
                 "vectorcast-coverage.json", "findings.sarif"):
        raw = (FIX / name).read_text(encoding="utf-8")
        server.detect_and_ingest(st, raw, f"file:{name}")
    return st


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.st = fresh_state()

    def test_artifact_counts(self):
        c = server.compute_gaps(self.st)["counts"]
        self.assertEqual(c["requirements"], 4)
        self.assertEqual(c["model_elements"], 3)
        self.assertEqual(c["code_units"], 3)
        self.assertEqual(c["test_cases"], 3)
        self.assertEqual(c["findings"], 3)
        self.assertEqual(c["tickets"], 2)

    def test_provenance_on_every_artifact(self):
        for art in self.st["artifacts"].values():
            p = art["provenance"]
            for k in ("source_tool", "tool_version", "run_id", "sources"):
                self.assertIn(k, p, art["id"])
                self.assertTrue(p[k], art["id"])

    def test_provenance_names_the_source_tool(self):
        self.assertIn("jira", self.st["artifacts"]["ECL-101"]
                      ["provenance"]["source_tool"])
        self.assertIn("Coverity", self.st["artifacts"]["FIND-1"]
                      ["provenance"]["source_tool"])
        cov = self.st["artifacts"]["guidance.c"]["attributes"]["coverage"]
        self.assertEqual(cov["run_id"], "VCAST-RUN-2026-014")
        self.assertEqual(cov["statement_pct"], 96.2)


class TestGaps(unittest.TestCase):
    def setUp(self):
        self.gaps = server.compute_gaps(fresh_state())

    def test_exactly_three_planted_gaps(self):
        found = {(g["kind"], g["artifact"]) for g in self.gaps["gaps"]}
        self.assertEqual(found, {
            ("unlinked_requirement", "ECL-104"),
            ("untested_code", "telemetry_codec.c"),
            ("finding_without_ticket", "FIND-3"),
        })
        self.assertEqual(self.gaps["gap_count"], 3)

    def test_no_orphan_tests(self):
        kinds = [g["kind"] for g in self.gaps["gaps"]]
        self.assertNotIn("orphan_test", kinds)

    def test_coverage_layers(self):
        cov = self.gaps["coverage"]
        self.assertEqual(cov["requirements_with_model"], 75.0)
        self.assertEqual(cov["code_units_tested"], 66.7)
        self.assertEqual(cov["findings_with_tickets"], 66.7)
        self.assertEqual(cov["tests_tracing_to_requirements"], 100.0)
        self.assertEqual(cov["requirements_verified_by_tests"], 50.0)

    def test_matrix_rows(self):
        m = {r["requirement"]: r for r in self.gaps["matrix"]}
        self.assertEqual(m["ECL-101"]["model_elements"], ["ME-1"])
        self.assertEqual(m["ECL-101"]["code_units"], ["guidance.c"])
        self.assertEqual(sorted(m["ECL-101"]["test_cases"]), ["TC-1", "TC-3"])
        self.assertEqual(m["ECL-104"]["model_elements"], [])


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.st = fresh_state()
        server.emit_receipt(self.st, "ingest", {"kind": "test"})

    def test_package_identity_deterministic(self):
        self.assertEqual(server.build_package(self.st)["package_id"],
                         server.build_package(self.st)["package_id"])

    def test_verify_clean_package(self):
        pkg = server.build_package(self.st)
        out = server.verify_package(pkg)
        self.assertTrue(out["valid"], out["problems"])
        self.assertEqual(out["artifacts_checked"], 18)

    def test_tamper_detection(self):
        pkg = json.loads(json.dumps(server.build_package(self.st)))
        for a in pkg["artifacts"]:
            if a["id"] == "ECL-101":
                a["attributes"]["summary"] = "SUBSTITUTED TEXT"
        out = server.verify_package(pkg)
        self.assertFalse(out["valid"])
        self.assertTrue(any("ECL-101" in p for p in out["problems"]))

    def test_link_tamper_detection(self):
        pkg = json.loads(json.dumps(server.build_package(fresh_state())))
        pkg["links"] = [l for l in pkg["links"]
                         if not (l["type"] == "satisfies" and l["to"] == "ECL-103")]
        out = server.verify_package(pkg)
        self.assertFalse(out["valid"])

    def test_markdown_is_gap_first(self):
        md = server.package_markdown(server.build_package(self.st))
        self.assertLess(md.index("Gaps first"), md.index("Traceability matrix"))
        self.assertIn("unlinked_requirement", md)
        self.assertIn("ECL-104", md)


class TestBridgeStub(unittest.TestCase):
    """Bridge <-> stub over REAL HTTP (localhost, stdlib server)."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), jira_stub.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_fetch_export_shape(self):
        export = jira_bridge.fetch_export(self.base)
        self.assertEqual(len(export["issues"]), 6)
        self.assertEqual(export["export_meta"]["run_id"], "JIRA-EXP-2026-001")

    def test_bridge_ingest_matches_fixture_ingest(self):
        via_bridge = server.empty_state()
        export = jira_bridge.fetch_export(self.base)
        server.ingest_jira(via_bridge, export, "bridge:test")
        via_file = server.empty_state()
        raw = (FIX / "jira-dc-export.json").read_text(encoding="utf-8")
        server.detect_and_ingest(via_file, raw, "file:test")
        self.assertEqual(sorted(via_bridge["artifacts"]),
                         sorted(via_file["artifacts"]))
        for aid in via_file["artifacts"]:
            self.assertEqual(
                server.record_hash(via_bridge["artifacts"][aid]),
                server.record_hash(via_file["artifacts"][aid]), aid)


class TestReceiptsAndTransport(unittest.TestCase):
    def test_receipt_chain_and_tamper(self):
        st = server.empty_state()
        server.emit_receipt(st, "ingest", {"kind": "x"})
        server.emit_receipt(st, "trace_gaps", {"gap_count": 3})
        self.assertTrue(server.verify_receipt_chain(st["receipts"]))
        st["receipts"][0]["detail"]["kind"] = "forged"
        self.assertFalse(server.verify_receipt_chain(st["receipts"]))

    def test_tools_list(self):
        resp = server.handle({"jsonrpc": "2.0", "id": 1,
                              "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, {"ingest_fixture", "graph_query",
                                 "trace_gaps", "evidence_build",
                                 "evidence_verify"})


if __name__ == "__main__":
    unittest.main()
