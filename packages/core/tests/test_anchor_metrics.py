"""The anchor over drift, and the metrics.

The anchor is the one thing in the data that cannot be filled in afterwards.
When it fails, a comment lands on innocent code, you reject it — and that
breaks the very metric the measurement exists for. Which is why it is tested
against a real shift in a git repo, not against a made-up string.
"""

from __future__ import annotations

from agency import anchor, metrics, runs
from agency.util import write_json

from conftest import git, make_finding


def _shift_file(repo):
    """Adds ten lines above the function and commits — the anchor must find the
    code even so."""
    p = repo / "src" / "auth.ts"
    p.write_text("// header\n" * 10 + p.read_text(encoding="utf-8"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "shift")


def test_an_anchor_on_an_unchanged_file_holds_literally(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]

    r = anchor.resolve(project.root, a)

    assert r.line == a["line"]
    assert r.via == "exact"


def test_layer_1_asks_about_the_file_not_the_repository(project, make_run):
    """Were `commit == HEAD` the test, a finding on a file nobody has touched
    since the analysis would fall through here — HEAD is almost always another
    commit."""
    run = make_run()
    a = run.findings()[0]["anchor"]

    (project.root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "another file")

    r = anchor.resolve(project.root, a)

    assert r.via == "exact", "a finding on an untouched file fell through layer 1"


def test_an_anchor_survives_a_line_shift(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]
    _shift_file(project.root)

    r = anchor.resolve(project.root, a)

    assert r.line == a["line"] + 10, "the shifted code was not found"
    assert r.via.startswith("snippet")


def test_drift_notices_that_the_code_was_touched(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]

    assert anchor.drift(project.root, a) == "untouched"

    p = project.root / "src" / "auth.ts"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "return user", "if (!session) return null\n  return user"), encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "fix")

    assert anchor.drift(project.root, a) == "touched"


def test_a_deleted_file_degrades_rather_than_disappears(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]
    git(project.root, "rm", "-q", "src/auth.ts")
    git(project.root, "commit", "-q", "-m", "deleted")

    r = anchor.resolve(project.root, a)

    assert r.line is None
    assert r.note, "degrading with no explanation is a loss"
    assert anchor.drift(project.root, a) == "deleted"


# ----------------------------------------------------------------- metrics

def test_precision_is_computed_from_decided_findings_only(project, make_run):
    """An undecided finding is neither true nor false. In the denominator it
    would let every new run dilute precision, and the number would measure the
    speed of triage."""
    run = make_run(findings=[make_finding(project, "x") for _ in range(4)])
    ids = [f["id"] for f in run.findings()]
    by = "hire:review-graph@claude"

    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "sent", by=by)
    runs.append_decision(run, ids[2], "rejected", reason="by-design", by=by)
    # ids[3] stays undecided

    r = metrics.collect(project)

    assert r["triage"]["precision"] == round(2 / 3, 3)
    assert r["triage"]["undecided"] == 1
    assert r["queue"]["undecided"] == 1


def test_precision_counts_only_a_chain_members_decision(project, make_run):
    """A decision made online on the board is not stored locally — `human` in
    the data is history from before the trail, and `chain` means "nobody
    decided". Neither is a specialist's verdict, so neither may be precision's
    numerator."""
    run = make_run(findings=[make_finding(project, "x") for _ in range(2)])
    ids = [f["id"] for f in run.findings()]

    runs.append_decision(run, ids[0], "sent", by="human")
    runs.append_decision(run, ids[1], "sent", by="chain")

    r = metrics.collect(project)

    assert r["triage"]["precision"] is None
    assert r["triage"]["accepted"] == 0
    assert r["triage"]["undecided"] == 0, "it is done — it just does not count into precision"


def test_precision_with_no_data_is_none_not_zero(project, make_run):
    """Zero out of zero is not zero percent. Rounding "I do not know" to 0.0 is
    the cheapest way to lie about your own tool."""
    make_run()
    r = metrics.collect(project)

    assert r["triage"]["precision"] is None


def test_metrics_break_down_by_dimension_and_model(project, make_run):
    """The aggregate number does not say what to do about it. `reuse 0.2` is an
    instruction to switch a dimension off."""
    run = make_run(findings=[
        make_finding(project, "x", dimension="correctness"),
        make_finding(project, "x", dimension="reuse", title="Mrtvý kód zůstal ve větvi po refaktoru"),
    ])
    ids = [f["id"] for f in run.findings()]
    by = "hire:review-graph@claude"
    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "rejected", reason="out-of-scope", by=by)

    r = metrics.collect(project)

    assert r["byDimension"]["correctness"]["precision"] == 1.0
    assert r["byDimension"]["reuse"]["precision"] == 0.0
    assert r["byModel"]["sonnet"]["accepted"] == 1
    assert r["rejectReasons"] == {"out-of-scope": 1}


def test_duplicates_do_not_count_into_the_metrics(project, make_run):
    """A duplicate is not a finding to decide on. Were it counted, the queue
    would grow by work somebody has already done."""
    run = make_run(findings=[
        make_finding(project, "x"),
        make_finding(project, "x", state="duplicate", duplicateOf="jiny"),
    ])

    r = metrics.collect(project)

    assert r["triage"]["undecided"] == 1


# ------------------------------------------- attended and unattended runs

def _run_costing(make_run, project, *, attended: bool, usd, turns, run_id=None):
    """One run of each population — the attended one deliberately carries no
    turns and no price, because that is exactly what an attended run records."""
    return make_run(
        run_id=run_id,
        findings=[make_finding(project, run_id or "x")],
        trigger={"kind": "manual", "attended": attended},
        agent={"provider": "claude", "model": "sonnet",
               **({"turns": turns} if turns is not None else {})},
        cost={"wallClockSeconds": 60, **({"usd": usd} if usd is not None else {})},
    )


def test_cost_comes_from_the_runs_that_could_measure_it(project, make_run):
    """`turns`, `usd` and `denied` exist only for a streamed run. Averaged over
    every run they were an average across a population half of which never
    recorded them — a number that reads as if it were about all of them."""
    _run_costing(make_run, project, attended=True, usd=None, turns=None,
                 run_id="01A0000000000000000000000A")
    _run_costing(make_run, project, attended=True, usd=None, turns=None,
                 run_id="01A0000000000000000000000B")
    _run_costing(make_run, project, attended=False, usd=0.42, turns=7,
                 run_id="01A0000000000000000000000C")

    c = metrics.collect(project)["cost"]

    assert c["usd"] == 0.42
    assert c["turns"] == 7
    # And it says which runs it could have come from.
    assert c["population"]["usd"] == 1
    assert c["population"]["turns"] == 1
    assert c["population"]["runs"] == 3
    assert c["population"]["attended"] == 2
    assert c["population"]["unattended"] == 1
    # Wall clock is its own population: `--wait` measures it attended too.
    assert c["population"]["wallClockSeconds"] == 3


def test_precision_still_counts_every_run(project, make_run):
    """The split is about cost, not about findings. An attended run's findings
    and decisions are as real as anyone's, and dropping them would trade one
    dishonest number for another."""
    a = _run_costing(make_run, project, attended=True, usd=None, turns=None,
                     run_id="01B0000000000000000000000A")
    b = _run_costing(make_run, project, attended=False, usd=0.1, turns=3,
                     run_id="01B0000000000000000000000B")
    by = "hire:review-graph@claude"
    runs.append_decision(a, a.findings()[0]["id"], "sent", by=by)
    runs.append_decision(b, b.findings()[0]["id"], "rejected", reason="by-design", by=by)

    t = metrics.collect(project)["triage"]

    assert t["accepted"] == 1 and t["rejected"] == 1
    assert t["precision"] == 0.5


def test_a_price_nobody_measured_is_none_not_zero(project, make_run):
    """Only attended runs: there is no cost number to report, and reporting
    $0.00 would say the runs were free rather than unmeasured."""
    _run_costing(make_run, project, attended=True, usd=None, turns=None)

    c = metrics.collect(project)["cost"]

    assert c["usd"] is None and c["turns"] is None
    assert c["population"]["usd"] == 0


def test_the_score_is_compared_against_what_happened(project, make_run):
    """A pack that gives everything 90 and has precision 0.4 is miscalibrated
    in a way no other number here shows — and both halves of it were already
    being written."""
    run = make_run(findings=[
        make_finding(project, "x", score=95),
        make_finding(project, "x", score=55, dimension="reuse",
                     title="Nothing imports the retry helper",
                     body="No caller reaches `retryOnce` since the queue rewrite.",
                     anchor={"symbol": {"name": "retryOnce", "range": [1, 4]}}),
    ])
    ids = [f["id"] for f in run.findings()]
    by = "hire:review-graph@claude"
    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "rejected", reason="by-design", by=by)

    t = metrics.collect(project)["triage"]

    assert t["scoreAccepted"] == 95.0
    assert t["scoreRejected"] == 55.0
