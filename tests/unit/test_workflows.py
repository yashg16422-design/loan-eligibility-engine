"""Static checks on the exported n8n workflows (n8n/workflows/*.json).

These JSON files are what gets imported into n8n, so a broken connection, a missing
error workflow or a leaked secret would ship silently. Every check here runs offline.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = {
    p.name: json.loads(p.read_text()) for p in sorted((ROOT / "n8n" / "workflows").glob("*.json"))
}
IDS = {wf["id"] for wf in WORKFLOWS.values()}
ERROR_WF = "LoanEngineWfE001"
# The only credentials a workflow may reference, by id (the secrets live in n8n, encrypted).
KNOWN_CREDENTIALS = {"PkRN0GO4XtFXA9pL", "fa286DA3YraErW57", "qaXP0OsyRtnbitga"}
SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password field": re.compile(r'"password"\s*:\s*"[^"]+"', re.IGNORECASE),
    "aws secret key": re.compile(r"aws_?secret_?access_?key", re.IGNORECASE),
    "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
}
TRIGGER_SUFFIXES = ("Trigger", "trigger", ".webhook", ".errorTrigger")


def is_trigger(node: dict) -> bool:
    return node["type"].endswith(TRIGGER_SUFFIXES)


def work_nodes(wf: dict) -> list[dict]:
    return [n for n in wf["nodes"] if n["type"] != "n8n-nodes-base.stickyNote"]


@pytest.fixture(params=sorted(WORKFLOWS), ids=sorted(WORKFLOWS))
def wf(request: pytest.FixtureRequest) -> dict:
    return WORKFLOWS[request.param]


def test_all_expected_workflows_are_exported():
    assert {
        "A_loan_discovery.json",
        "A1_process_batch.json",
        "B_matching.json",
        "B1_match_run.json",
        "C_notification.json",
        "C1_compose_batch.json",
        "E_error_handler.json",
        "E1_error_drill.json",
    } <= set(WORKFLOWS)
    assert len(IDS) == len(WORKFLOWS)  # ids are unique: import updates in place, never duplicates


def test_node_names_and_ids_unique(wf):
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names))
    assert len({n["id"] for n in wf["nodes"]}) == len(names)


def test_connections_reference_existing_nodes(wf):
    names = {n["name"] for n in wf["nodes"]}
    for src, outputs in wf["connections"].items():
        assert src in names, f"connection from unknown node {src!r}"
        for branch in outputs["main"]:
            for edge in branch:
                assert edge["node"] in names, f"{src!r} -> unknown node {edge['node']!r}"


def test_every_node_is_reachable_from_a_trigger(wf):
    """An orphan node is dead code in a workflow: usually a forgotten link."""
    seen = {n["name"] for n in work_nodes(wf) if is_trigger(n)}
    assert seen, "workflow has no trigger"
    frontier = list(seen)
    while frontier:
        for branch in wf["connections"].get(frontier.pop(), {}).get("main", []):
            for edge in branch:
                if edge["node"] not in seen:
                    seen.add(edge["node"])
                    frontier.append(edge["node"])
    orphans = {n["name"] for n in work_nodes(wf)} - seen
    assert not orphans, f"unreachable nodes: {sorted(orphans)}"


def test_every_production_workflow_reports_errors_to_e(wf):
    if wf["id"] == ERROR_WF:
        assert "errorWorkflow" not in wf["settings"]  # never its own handler (no loop)
        assert any(n["type"] == "n8n-nodes-base.errorTrigger" for n in wf["nodes"])
    else:
        assert wf["settings"].get("errorWorkflow") == ERROR_WF


def test_sub_workflow_calls_target_exported_workflows(wf):
    for node in wf["nodes"]:
        if node["type"] == "n8n-nodes-base.executeWorkflow":
            assert node["parameters"]["workflowId"]["value"] in IDS, node["name"]


def test_credentials_are_references_only(wf):
    for node in wf["nodes"]:
        for ref in node.get("credentials", {}).values():
            assert set(ref) == {"id", "name"}, f"{node['name']}: credential carries data"
            assert ref["id"] in KNOWN_CREDENTIALS, f"{node['name']}: unknown credential {ref}"


def test_no_secrets_in_exports(wf):
    text = json.dumps(wf)
    for label, pattern in SECRET_PATTERNS.items():
        assert not pattern.search(text), f"{label} found in workflow export"


def test_webhooks_require_authentication(wf):
    for node in wf["nodes"]:
        if node["type"] == "n8n-nodes-base.webhook":
            assert node["parameters"].get("authentication") == "headerAuth", node["name"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_code_nodes_are_valid_javascript(wf, tmp_path):
    """Syntax-check every Code node the way n8n runs it: the body of an async function."""
    for node in wf["nodes"]:
        if node["type"] != "n8n-nodes-base.code":
            continue
        body = node["parameters"]["jsCode"]
        script = tmp_path / "check.js"
        script.write_text(
            "const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;\n"
            f"new AsyncFunction({json.dumps(body)});\n"
        )
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{node['name']}: {result.stderr.strip()[:500]}"


def test_b1_correctness_proof_gates_the_run():
    """DF9: a failed brute-force proof must stop the run before Finish run (so B skips C)."""
    b1 = WORKFLOWS["B1_match_run.json"]
    out = lambda name, i: [e["node"] for e in b1["connections"][name]["main"][i]]  # noqa: E731
    assert out("Correctness proof", 0) == ["Proof passed?"]
    assert out("Proof passed?", 0) == ["Finish run"]
    assert out("Proof passed?", 1) == ["Stop: proof failed"]
    stop = next(n for n in b1["nodes"] if n["name"] == "Stop: proof failed")
    assert "throw new Error" in stop["parameters"]["jsCode"]
    assert out("Finish run", 0) == ["Treasure Hunt funnel"]


def test_b1_prewrite_proof_runs_before_any_match_is_written():
    """The class decisions are checked BEFORE Stage 3; a failure throws and Stage 3 never runs."""
    b1 = WORKFLOWS["B1_match_run.json"]
    out = lambda name, i: [e["node"] for e in b1["connections"][name]["main"][i]]  # noqa: E731
    assert out("Refresh planner stats", 0) == ["Pre-write proof"]
    assert out("Pre-write proof", 0) == ["Pre-write passed?"]
    assert out("Pre-write passed?", 0) == ["Stage 3 · expand, score, diff"]
    assert out("Pre-write passed?", 1) == ["Stop: pre-write proof failed"]
    stop = next(n for n in b1["nodes"] if n["name"] == "Stop: pre-write proof failed")
    assert "throw new Error" in stop["parameters"]["jsCode"]
    pre = next(n for n in b1["nodes"] if n["name"] == "Pre-write proof")
    assert "FROM matches" not in pre["parameters"]["query"]  # it never reads or writes matches
    # Stage 3 is reachable ONLY through the pre-write gate.
    into_stage3 = [
        src
        for src, conns in b1["connections"].items()
        for outs in conns["main"]
        for e in outs
        if e["node"] == "Stage 3 · expand, score, diff"
    ]
    assert into_stage3 == ["Pre-write passed?"]


@pytest.mark.parametrize("wf", WORKFLOWS.values(), ids=WORKFLOWS.keys())
def test_every_node_has_a_short_note_on_the_canvas(wf):
    """Each work node explains itself on the canvas in one line (notes shown in flow)."""
    for node in wf["nodes"]:
        if node["type"] == "n8n-nodes-base.stickyNote":
            continue
        note = node.get("notes", "")
        assert note and len(note) <= 120, f"{wf['name']} > {node['name']}: note missing or too long"
        assert node.get("notesInFlow") is True


def test_c_composes_every_users_email_in_bounded_batches_and_c1_never_sends():
    c, c1 = WORKFLOWS["C_notification.json"], WORKFLOWS["C1_compose_batch.json"]
    out = lambda wf, name, i: [e["node"] for e in wf["connections"][name]["main"][i]]  # noqa: E731
    assert out(c, "Record notifications", 0) == ["Compose the rest (C1)"]
    assert out(c, "Compose the rest (C1)", 0) == ["More to compose?"]
    assert out(c, "More to compose?", 0) == ["Compose the rest (C1)"]  # the loop
    guard = next(n for n in c["nodes"] if n["name"] == "More to compose?")
    condition = json.dumps(guard["parameters"])
    assert "remaining" in condition and "composed" in condition and "$runIndex < 200" in condition
    assert not any(n["type"] == "n8n-nodes-base.awsSes" for n in c1["nodes"])  # never sends
