# Eclipse Thread MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Thread — on-prem MCP bridges for the legacy software-engineering toolchain, plus the Evidence Weaver that joins their records into one traceable thread.**

## Why this exists

The toolchain safety-critical software runs on — issue tracking, static
analysis, systems modeling, structural test — lives on-premises, inside
enclaves the vendors' cloud MCP servers cannot reach. Thread's bridges
run *inside* the wall, speak to the *local* tool over its sanctioned
interface, and join what they read into one traceable record whose gaps
are enumerated, not buried. (Family spec:
`../eclipse-thread-bridge-family-spec-20261025.md`.)

## Status — honest labels: SIMULATOR

v0.1.0 — **Evidence Weaver core + Jira DC bridge (mock)**. **No real
Jira, Coverity, Cameo, or VectorCAST instance exists in this
environment, and none is contacted.** Every target is a shipped fixture
or the bundled stub server; every surface carries the **(simulator)**
qualifier, per the family spec's decision #2 (doc-first + simulator
until licenses are in hand — a live-tested scope is never implied).
**No certification claimed — bench pending.**

**Qualification posture (spec §6, binding):** v0.1 is evidence
*assembly and transport only*. It generates no verification results of
its own — no analysis runs, no test authoring, no coverage computation.
Coverage numbers in the graph are the source tools' own, quoted with
their run receipts. **No compliance or tool-qualification (DO-330)
claims are made.**

## Tools (5)

| Tool | What it does |
|---|---|
| `ingest_fixture` | Ingest one export into the artifact graph: a local file — Jira-DC-shaped JSON, SARIF, VectorCAST-shaped JSON, or XMI-lite XML — or a bridge fetch (`jira_base_url`) over real HTTP from a stub/DC-shaped host. Every artifact gains provenance {source tool, version, run id, source ref}. `reset=true` clears first. |
| `graph_query` | Graph counts by type + receipt-chain check; list one artifact type; or fetch one artifact with its in/out trace links. |
| `trace_gaps` | **Gap-first** analysis: unlinked requirements, untested code units, orphan test cases, findings without tickets — plus the requirement→model→code→test matrix and per-layer coverage %. |
| `evidence_build` | Deterministic evidence package (JSON + gap-first Markdown summary): a manifest folding a hash of every artifact and link (GENESIS-anchored), so rebuilds over the same graph reproduce the same `package_id`. |
| `evidence_verify` | Verify a package **standalone**: recompute every artifact hash, the link set, and the identity fold from the package body alone; any substitution is named. |

## The fixture thread (planted gaps)

The shipped fixtures describe one small system end-to-end — 4
requirements, 3 model elements, 3 code units, 3 test cases, 3 findings,
2 tickets — with **exactly three planted gaps**, which the test suite
asserts as the known answer:

1. `ECL-104` — requirement no model element satisfies (**unlinked**)
2. `telemetry_codec.c` — code unit no test case exercises (**untested**)
3. `FIND-3` — SARIF finding with no tracking ticket

## The Jira DC bridge (mock)

`jira_bridge.py` speaks the DC REST v2 shape (`/rest/api/2/search`,
`/rest/api/2/issue/{key}`) and returns the same normalized export the
file ingest consumes — one code path for fixture, stub, and real
instance. `jira_stub.py` is a stdlib HTTP server serving the fixture in
that shape, so the bridge is exercised over **real HTTP**:

```bash
python3 jira_stub.py --port 8931          # terminal 1 (simulator)
python3 jira_bridge.py http://127.0.0.1:8931
# or, via the MCP tool: ingest_fixture {"jira_base_url": "http://127.0.0.1:8931"}
```

Pointing the bridge at a real Data Center instance is a **config-only
difference** (base URL + the instance's auth) — **[verify on a real
instance]**: per-version API surface, auth scheme, and rate behavior
must be confirmed against the customer's install before any live claim.
The bridge is **read-only** in v0.1 and calls only the configured base
URL (family design law: zero other egress).

## Receipts

Every ingest, gap run, and evidence build appends a **hash-chained
receipt** (GENESIS-anchored, append-only) to the local store;
`graph_query` reports chain validity, and tampering is detected in
tests.

## Run it

```bash
python3 server.py            # MCP over stdio, stdlib only, no dependencies
python3 smoke.py             # end-to-end stdio smoke (temp state)
python3 -m unittest discover tests   # 16 tests
```

State file: `$ECLIPSE_THREAD_STATE` or `./data/state.json` beside
`server.py` (git-ignored, along with built packages).

## Not in v0.1 (by spec, not by omission)

Coverity / Cameo / VectorCAST *bridges* (their export shapes are
ingested; the live bridges are T1+ work gated on interface verification
and tool-license access), any write path (draft tickets are a later,
individually justified step), any network call beyond the configured
Jira base URL, and any certification-use marketing language (gated on
the §6 quality/counsel review).
