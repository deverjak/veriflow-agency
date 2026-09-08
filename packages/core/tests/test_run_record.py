"""The run record against its own contract.

Until 1 September 2026 nobody checked `run.v1` — `agency validate` read only
`finding.v1` — and the record had drifted from its schema in three places:
memory folded into `graph`, the `gated-out` state outside the enum, `slug: null`
in a repository with no remote. Two of those were schema bugs, one a writing
bug. What they had in common was that nothing existed to report them.
"""

from __future__ import annotations

import json

from agency import cli, packs, runs


def _validate(project, run, capsys) -> tuple[int, dict]:
    code = cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_a_run_record_fits_its_contract(project, make_run, capsys):
    """An ordinary run passes. If it did not, the validation would be useless —
    it would report an error on everything and nobody would read it."""
    run = make_run()

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0


def test_memory_folded_into_the_graph_is_reported(project, make_run, capsys):
    """Exactly the bug runs were written with until 1 September 2026: `graph`
    has a closed list of keys and `knownFindings` is not one of them."""
    run = make_run()
    rec = run.record()
    rec["graph"] = {"tool": "code-review-graph 2.3.7", "action": "update",
                    "knownFindings": 12}
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert code == 1
    assert any("knownFindings" in e["message"] for e in data["recordErrors"])


def test_gated_out_is_a_valid_state(project, make_run, capsys):
    """A run whose findings the gate dropped entirely is not a run with no
    findings — and the extension has always had its own icon for that state. It
    was only missing from the schema."""
    run = make_run()
    rec = run.record()
    rec["status"] = "gated-out"
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0


def test_a_project_with_no_remote_is_valid(project, make_run, capsys):
    """The doctor says "no remote — the hired specialists do not need one". The
    schema nevertheless wanted `slug` as a string, so every run in such a repo
    wrote an invalid record."""
    run = make_run()
    rec = run.record()
    rec["project"] = {"slug": None, "defaultBranch": "main"}
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0


def test_the_agent_does_not_get_to_invent_cost_fields(project, make_run, monkeypatch,
                                                      capsys):
    """The agent writes `run.json` too, and one run added `cost.note` to it.

    Everything under `cost` is measured by this process, not observed by the
    agent, but the merge carried its object over whole — so the record came
    out of a successful run failing the very schema `agency validate` checks
    it against. Seen on a real po run started from a phone.
    """
    from agency import proc, runs

    run = make_run()
    rec = run.record()
    rec["cost"] = {"note": "not separately metered by this run", "dimensions": 6}
    run.save_record(rec)
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    runs.attend(project, run, ["claude", "-p"], project.root)

    cost = run.record()["cost"]
    assert "note" not in cost, "a key run.v1 refuses must not survive the merge"
    assert cost["dimensions"] == 6, "a key it allows still comes through"

    code, report = _validate(project, run, capsys)
    assert code == 0, report


# ------------------------------------------------------------------- context

def _prepare(project, run, prompt=None):
    """The preparation a real run does, minus launching anything."""
    pack = packs.load("review-graph", project)
    runs.write_context(run, pack, {"kind": "workspace"}, project.root, [], 0,
                       prompt=prompt)
    return run.record()["context"]


def test_the_record_says_what_the_agent_was_handed(project, make_run, capsys):
    """Without this block "precision dropped" has no independent variable: the
    method, the house rules and the memory all change underneath the number."""
    (project.root / "CLAUDE.md").write_text("# House\n\nBe careful.\n", encoding="utf-8")
    run = make_run()
    (run.dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run.dir / "evidence" / "known-findings.json").write_text("[1, 2, 3]", encoding="utf-8")

    ctx = _prepare(project, run, prompt="look at the login flow")

    assert [i["path"] for i in ctx["instructions"]] == ["CLAUDE.md"]
    assert len(ctx["instructions"][0]["sha256"]) == 64
    assert ctx["skill"]["path"].endswith("agency-review-graph/SKILL.md")
    assert len(ctx["skill"]["sha256"]) == 64
    assert ctx["promptBytes"] == len("look at the login flow")
    # The number that means something about memory: three known findings, not
    # however many bytes their formatting took.
    assert [(e["name"], e["items"]) for e in ctx["evidence"]] == \
           [("known-findings.json", 3)]

    code, report = _validate(project, run, capsys)
    assert code == 0, report


def test_a_run_with_no_house_rules_and_no_prompt_still_records_the_block(
        project, make_run, capsys):
    """Absence has to be written down too. A block that only appears when
    something interesting happened cannot be counted across runs."""
    run = make_run()

    ctx = _prepare(project, run)

    assert ctx["instructions"] == []
    assert ctx["promptBytes"] is None
    assert ctx["conflicts"] == 0

    code, report = _validate(project, run, capsys)
    assert code == 0, report
