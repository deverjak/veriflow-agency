"""The findings ledger: memory that reads even for someone without Agency.

This is where the attribution work pays off — who found a finding, who
confirmed it and who decided on it produces a trust tier. Tests guard three
properties that break easily without anyone noticing:

  1. the bundle is DERIVED — rebuilding it must not change or lose anything,
  2. a duplicate from the SAME worker is NOT a confirmation,
  3. memory holds what passed the gate, not what the pack wrote.

The generated `findings/*.md` files are read by humans and agents, never
re-parsed by the tool — so these tests check the raw text, the same way any
other reader would.
"""

from __future__ import annotations

from agency import ingest, knowledge, runs
from agency.util import write_json

from conftest import make_finding

RUN_A = "01AAAAAAAAAAAAAAAAAAAAAAAA"
RUN_B = "01BBBBBBBBBBBBBBBBBBBBBBBB"

CLAUDE = {"provider": "claude", "model": "sonnet", "bin": "claude",
          "hire": "review-graph@claude"}
CODEX = {"provider": "codex", "model": "gpt-5", "bin": "codex",
         "hire": "review-graph@codex"}


def finding_text(project, fid: str) -> str:
    root = project.agency_dir / knowledge.BUNDLE
    return (root / knowledge.LEDGER / f"{fid}.md").read_text(encoding="utf-8")


def bundle_text(project, name: str) -> str:
    return (project.agency_dir / knowledge.BUNDLE / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ the concept

def test_a_finding_is_a_readable_concept(project, make_run):
    """The finding without a body is just a heading — the whole point of the
    format is that it carries the claim, not just a pointer to it."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]

    knowledge.bundle(project)
    text = finding_text(project, fid)

    assert 'type: "Finding"' in text
    assert 'outcome: "candidate"' in text, "nobody has decided on the finding"
    assert 'trust: "unverified"' in text
    assert 'by: "hire:review-graph@claude"' in text
    assert "getUser" in text, "a concept without the finding's body is only a heading"
    assert 'file: "src/auth.ts"' in text and "line: 2" in text


def test_a_concept_links_to_files_that_exist(project, make_run):
    """The link is the whole point of the format — the bundle is read by
    clicking in an editor, not by a tool. A link one directory off is worse
    than no link."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    knowledge.bundle(project)

    path = project.agency_dir / knowledge.BUNDLE / knowledge.LEDGER / f"{fid}.md"
    text = path.read_text(encoding="utf-8")

    assert "(../../../src/auth.ts)" in text
    assert (path.parent / "../../../src/auth.ts").resolve().is_file()
    assert f"(../../runs/{RUN_A}/)" in text
    assert (path.parent / f"../../runs/{RUN_A}").resolve().is_dir()


# ------------------------------------------------------------------ trust tiers

def test_a_duplicate_from_another_worker_is_a_confirmation(project, make_run):
    """"codex found it → claude independently confirmed it" is the most
    valuable sentence on a later run's input. As two separate findings in
    the ledger it would claim the project found two things — and lose that
    information entirely."""
    first = make_run(run_id=RUN_A, agent=CODEX)
    ingest.ingest(project, first)
    again = make_run([make_finding(project, RUN_B)], run_id=RUN_B, agent=CLAUDE)
    ingest.ingest(project, again)

    concepts = knowledge.ledger(project)

    assert len(concepts) == 1, "a duplicate is not another finding, it is a second worker"
    c = concepts[0]
    assert c["trust"] == "machine-confirmed"
    assert c["occurrences"] == 2
    assert [v["by"] for v in c["verified"]] == ["hire:review-graph@claude"]
    assert c["generated"]["by"] == "hire:review-graph@codex", "the author is the first one"


def test_the_same_worker_twice_is_not_a_confirmation(project, make_run):
    """The same worker over the same code a second time is a repeat, not
    agreement between two. If it counted as confirmation, running one pack
    twice would be enough to make the ledger claim two workers agreed."""
    ingest.ingest(project, make_run(run_id=RUN_A, agent=CLAUDE))
    ingest.ingest(project, make_run([make_finding(project, RUN_B)], run_id=RUN_B, agent=CLAUDE))

    c = knowledge.ledger(project)[0]

    assert c["occurrences"] == 2, "finding it a second time is not lost"
    assert c["verified"] == []
    assert c["trust"] == "unverified"


def test_a_humans_decision_is_the_highest_tier(project, make_run):
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    runs.reject(project, run, fid, "by-design", by="human:kuba")

    knowledge.bundle(project)
    text = finding_text(project, fid)

    assert 'trust: "human-reviewed"' in text
    assert 'outcome: "rejected"' in text, "the claim did not hold — and it carries that with it"
    assert "rejected by `human:kuba`" in text
    assert "by-design" in text


def test_a_packs_own_decision_does_not_confirm_its_finding(project, make_run):
    """A pack that approves its own finding is not a second opinion. Without
    this guard, `agency triage --by <its own hire>` alone would bump the tier."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    fs = run.findings()
    fs[0]["state"] = "sent"
    write_json(run.findings_path, fs)
    runs.append_decision(run, fid, "sent", by="hire:review-graph@claude")

    c = knowledge.ledger(project)[0]

    assert c["trust"] == "unverified"
    assert c["outcome"] == "sent", "the decision holds, nobody has reviewed it yet"


def test_a_rejected_finding_stays_in_memory(project, make_run):
    """"We already rejected this as by-design" is the exact reason memory
    exists. If rejected findings were dropped from the overview, the next
    run would report them again — the ledger exists to stop that."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    runs.reject(project, run, run.findings()[0]["id"], "by-design", by="human")
    knowledge.bundle(project)

    index = bundle_text(project, "index.md")

    assert "Do not report again" in index
    assert "by-design" in index


# ------------------------------------------------------------------ derived-ness

def test_rebuilding_the_bundle_changes_nothing(project, make_run):
    """The bundle is derived — two rebuilds over the same runs must give
    byte-for-byte the same result. Otherwise `git diff` stops answering what
    actually changed, and the bundle becomes noise nobody reads."""
    make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)

    second = knowledge.bundle(project)

    assert second["changed"] == [] and second["removed"] == []


def test_the_bundle_can_be_discarded_and_rebuilt(project, make_run):
    """The truth stays in `.agency/runs/`. If deleting the bundle lost
    something, it would be a second source of truth — and one bad rewrite
    would erase history."""
    import shutil

    run = make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)
    before = bundle_text(project, f"{knowledge.LEDGER}/{run.findings()[0]['id']}.md")

    shutil.rmtree(project.agency_dir / knowledge.BUNDLE)
    knowledge.bundle(project)

    assert bundle_text(project, f"{knowledge.LEDGER}/{run.findings()[0]['id']}.md") == before


def test_a_discarded_run_stays_in_the_ledger_through_the_trail(project, make_run):
    """Losing `.agency/runs/<id>/` must not mean losing what it reported —
    that is exactly why the trail is committed and append-only."""
    import shutil

    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    finding = run.findings()[0]
    runs.append_decision(run, fid, "sent", by="hire:review-graph@claude", ref="PVTI_X")
    runs.append_trail(project, {
        "id": fid, "runId": run.id, "pack": "review-graph", "state": "sent",
        "title": finding["title"], "anchor": finding["anchor"], "severity": finding["severity"],
        "by": "hire:review-graph@claude", "ref": "PVTI_X",
    })
    knowledge.bundle(project)
    shutil.rmtree(run.dir)

    result = knowledge.bundle(project)

    assert f"{knowledge.LEDGER}/{fid}.md" not in result["removed"]
    text = bundle_text(project, f"{knowledge.LEDGER}/{fid}.md")
    assert "run directory is no longer present" in text
    assert 'outcome: "sent"' in text


def test_a_run_thats_actually_gone_and_unreported_is_removed(project, make_run):
    """A candidate no sink ever reached, whose run then vanished, really is
    gone — the trail only remembers what left something behind."""
    import shutil

    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    knowledge.bundle(project)
    shutil.rmtree(run.dir)

    result = knowledge.bundle(project)

    assert f"{knowledge.LEDGER}/{fid}.md" in result["removed"]
    assert not (project.agency_dir / knowledge.BUNDLE / knowledge.LEDGER / f"{fid}.md").is_file()


def test_a_dry_check_writes_nothing(project, make_run):
    """`agency knowledge` without `--rebuild` answers whether the bundle
    matches the runs. An answer that fixes itself along the way is not an
    answer."""
    make_run(run_id=RUN_A, agent=CLAUDE)

    dry = knowledge.bundle(project, write=False)

    assert dry["changed"], "the bundle does not exist yet, so it differs"
    assert not (project.agency_dir / knowledge.BUNDLE).exists()


# ------------------------------------------------------------------ chronology

def test_the_chronology_takes_the_specialists_own_words(project, make_run):
    """`log.md` is the one place a specialist speaks in its own words. The
    core does not write or edit the summary — it only copies it into the
    chronology."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    (run.dir / "summary.md").write_text(
        "Went through five files around the export. The one thing worth "
        "noting is a swallowed error in the sink.", encoding="utf-8")
    knowledge.bundle(project)

    log = bundle_text(project, "log.md")

    assert "swallowed error in the sink" in log
    assert f"[run {RUN_A}](../runs/{RUN_A}/)" in log
    assert "hire:review-graph@claude" in log


def test_a_run_without_a_summary_is_visible_in_the_chronology(project, make_run):
    """The `summary.md` contract lives in each pack's `SKILL.md`. An empty
    slot in the chronology is the one place that shows a pack did not meet
    it — skipping the run would hide that information."""
    make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)

    assert "_No summary left behind._" in bundle_text(project, "log.md")


# ------------------------------------------------------------------ the gate

def test_only_what_passed_the_gate_reaches_memory(project, make_run):
    """A hallucinated finding must never become the project's memory. The
    gate runs first, and the ledger is built from what survives it."""
    good = make_finding(project, RUN_A)
    phantom = make_finding(project, RUN_A, anchor={"file": "src/does-not-exist.ts"},
                           title="A finding in a file that does not exist at that commit",
                           body="A different claim about a different place, so it is not a duplicate.")
    run = make_run([good, phantom], run_id=RUN_A, agent=CLAUDE)

    result = ingest.ingest(project, run)

    assert result["counts"]["gated"] == 1
    ids = [c["id"] for c in knowledge.ledger(project)]
    assert ids == [good["id"]]
    assert result["bundle"]["changed"], "ingest refreshes the ledger itself"
