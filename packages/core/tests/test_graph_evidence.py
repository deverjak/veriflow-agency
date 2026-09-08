"""The graph signal is read by machine, not off a panel written for a person.

Until 1 September 2026 `changedFunctions` and friends were pulled by regex out
of the Rich panel of `detect-changes --brief`. The day CRG reworded that
sentence, the numbers would have quietly vanished from the run record — nothing
would fall over, empty fields would simply start being written. So this file
guards the shape of the data, not the text, and the summary in the stubbed
answers lies on purpose: should anyone go back to reading sentences, the tests
will say so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agency import proc, runs

SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "run.v1.json"

# The shape of `detect-changes` without `--brief`, verified against
# code-review-graph 2.3.7.
DETECT = {
    "summary": "Analyzed 1 changed file(s):\n  - 1 changed function(s)\n  - 0 test gap(s)",
    "risk_score": 0.8,
    "changed_functions": [{"name": f"f{i}"} for i in range(82)],
    "affected_flows": [{"name": "checkout"}],
    "test_gaps": [{"name": f"g{i}"} for i in range(50)],
    "functions_truncated": False,
}


def canned(payload) -> proc.Result:
    return proc.Result(True, 0, json.dumps(payload), "")


@pytest.fixture
def fake_crg(monkeypatch):
    """Stubs the graph's answers per command. What is not stubbed fails."""
    def _install(**by_command: proc.Result):
        def crg(*args: str, cwd=None, timeout: int = 1800) -> proc.Result:
            key = args[0].replace("-", "_")
            return by_command.get(key, proc.Result(False, 1, "", f"{args[0]}: not stubbed"))
        monkeypatch.setattr(proc, "crg", crg)
    return _install


def _all_stubbed(fake_crg, detect=None):
    fake_crg(detect_changes=canned(detect if detect is not None else DETECT),
             impact=canned({"status": "ok"}), dead_code=canned([]))


def test_the_stats_come_from_json_not_from_a_sentence_in_a_panel(project, make_run, fake_crg):
    """The summary reports one function, the data has 82. The data wins."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    assert stats["changedFunctions"] == 82
    assert stats["untestedFunctions"] == 50
    assert stats["affectedFlows"] == 1
    assert stats["riskScore"] == 0.8
    assert "changedFunctionsTruncated" not in stats

    saved = json.loads((run.dir / "evidence" / "detect-changes.json")
                       .read_text(encoding="utf-8"))
    assert len(saved["test_gaps"]) == 50, \
        "the `tests` dimension reads test_gaps[] — it used to be an \"Untested:\" list in a sentence"


def test_the_file_count_comes_from_the_run_not_from_the_graph(project, make_run, fake_crg):
    """`files[]` is the list after `skipPatterns`. The graph computes its own
    diff and knows nothing of the filter, so its number describes a different
    set than the one the run is reviewing."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run, {"baseRefOid": "b" * 40},
                                  ["src/auth.ts", "src/pay.ts"])

    assert stats["changedFiles"] == 2


def test_a_truncated_list_is_recorded_as_truncated(project, make_run, fake_crg):
    """CRG cuts at `CRG_MAX_CHANGED_FUNCS` and reports that ceiling in its
    summary as a result. Without the flag the record would say "500 changed
    functions" as a fact rather than a lower bound — and the difference between
    a large PR and a truncated one would disappear."""
    _all_stubbed(fake_crg, dict(DETECT, functions_truncated=True,
                                changed_functions=[{"name": f"f{i}"} for i in range(500)]))
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    assert stats["changedFunctions"] == 500
    assert stats["changedFunctionsTruncated"] is True


def test_a_graph_error_does_not_end_up_in_a_json_file(project, make_run, fake_crg):
    """A run with no graph signal is a legitimate result, so nothing falls over.
    But an error message stored as `.json` would look like data to a dimension."""
    fake_crg()
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    ev = run.dir / "evidence"
    assert not (ev / "detect-changes.json").exists()
    assert not (ev / "dead-code.json").exists()
    assert "not stubbed" in (ev / "detect-changes.error.txt").read_text(encoding="utf-8")
    assert "changedFunctions" not in stats
    assert stats["changedFiles"] == 1, "what the core knows by itself survives a graph outage"


def test_a_run_records_what_the_driver_can_be_asked(project, make_run, fake_crg):
    """This is how a pack knows which dimension to skip. What the driver cannot
    do is not evidenced — and without this file the pack would have to guess it
    from empty evidence."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    runs.collect_evidence(project, project.root, run, {"baseRefOid": "b" * 40}, [])

    caps = json.loads((run.dir / "evidence" / "graph-capabilities.json")
                      .read_text(encoding="utf-8"))
    assert caps["driver"]
    assert "tests-for" in caps["capabilities"]


def test_the_stats_fit_into_run_v1(project, make_run, fake_crg):
    """`graph` has a closed list of keys in `run.v1`. A new stat key with no
    entry in the schema does not fail here but at the validation of a finished
    run."""
    _all_stubbed(fake_crg, dict(DETECT, functions_truncated=True))
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])
    ginfo = runs.prepare_graph(project, project.root)

    allowed = set(json.loads(SCHEMA.read_text(encoding="utf-8"))
                  ["properties"]["graph"]["properties"])
    # Memory is collected in the same preparation, but the core does not write
    # it into `graph`.
    graph_keys = (set(stats) | set(ginfo)) - set(runs.MEMORY_STATS)
    assert graph_keys <= allowed, f"unknown to the schema: {sorted(graph_keys - allowed)}"
    assert set(runs.MEMORY_STATS) & set(stats), "memory is still collected, it just lives elsewhere"
    assert ginfo["driver"] and ginfo["capabilities"], \
        "without the driver and its capabilities a swap cannot be evaluated"
