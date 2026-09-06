"""Memory is a thing, not a side effect of starting a run.

Tests here guard three properties everything else stands on: attribution
(the ledger's trust tiers are built from it), the cap (the background has one,
the brief does not), and that the run projection did not change even though
`runs.py` no longer assembles it.
"""

from __future__ import annotations

import json

import pytest

from agency import knowledge, packs, runs
from agency.util import ulid

from conftest import install_pack


# ------------------------------------------------------------------ identity

def test_identity_tells_a_specialist_from_a_person(project, make_run):
    """The difference between "one model thinks so" and "a human accepted
    it" is the most valuable input for the next run. As a free string it
    was lost."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="hire:po@claude")
    assert runs.decisions(run)[fid]["by"] == "hire:po@claude"

    runs.append_decision(run, fid, "rejected", reason="by-design", by="human:kuba")
    assert runs.decisions(run)[fid]["by"] == "human:kuba"


@pytest.mark.parametrize("bad", ["po", "claude", "hire:", "human:", "agent 7", ""])
def test_an_unknown_identity_shape_is_refused(project, make_run, bad):
    """A free string would mean attribution cannot be weighed — and
    `hire:po` instead of `hire:po@claude` is exactly the mistake nobody would
    catch afterwards."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "sent", by=bad)


def test_an_old_write_reads_back_as_a_person(project, make_run):
    """History is not rewritten, only interpreted: `cli` and `vscode` were
    always a person, only indistinguishable from an agent that never sent
    `--by`."""
    assert runs.normalize_by("cli") == "human"
    assert runs.normalize_by("vscode") == "human"
    assert runs.normalize_by("hire:qa@codex") == "hire:qa@codex"


def test_a_worker_has_an_id_with_no_roster():
    """`pack@provider` is a naming convention, not a lookup into a file."""
    assert runs.worker_id("legal") == "legal@claude"
    assert runs.worker_id("legal", provider="codex") == "legal@codex"


def test_context_carries_a_ready_made_signature(project, make_run):
    """The core assembles the identity. If an agent assembled it, that would
    be the first place "a specialist decided" turns into "someone decided"."""
    install_pack(project, "legal", {"target": "workspace", "worktree": False})
    pack = packs.load("legal", project)
    run = make_run()
    runs.write_context(run, pack, {"kind": "workspace"}, project.root, [], 0)

    ctx = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["by"] == "hire:legal@claude"
    # And crucially: it is a valid signature, not just a string that looks right.
    assert runs.validate_by(ctx["by"]) == ctx["by"]


# -------------------------------------------------------------------- memory

def test_memory_carries_who_decided(project, make_run):
    """Without attribution, "codex found it, claude confirmed it, a human
    accepted it" is one string — and this exact difference is what the
    ledger's trust tiers are built from."""
    old = make_run(agent={"provider": "codex", "hire": "review-graph@codex"})
    fid = old.findings()[0]["id"]
    runs.append_decision(old, fid, "rejected", reason="by-design",
                         by="hire:review-graph@claude")

    picture = knowledge.assemble(project)

    finding = next(f for f in picture["findings"] if f["id"] == fid)
    assert finding["hire"] == "review-graph@codex", "who found it"
    assert finding["decidedBy"] == "hire:review-graph@claude", "who decided"
    assert finding["decision"] == "rejected"


def test_the_run_projection_has_a_cap_the_brief_does_not(project, make_run, monkeypatch):
    """The cap belongs to the background. A finding that does not fit the
    background is an inconvenience; one that does not fit the brief is a
    finding nobody decided on."""
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 2)
    old = make_run(findings=[
        {"id": f"f{i}", "title": f"finding {i}", "anchor": {"file": "src/auth.ts", "line": 2}}
        for i in range(5)
    ])
    new = make_run(findings=[])

    stats = knowledge.for_run(project, new)

    saved = json.loads(
        (new.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))
    assert len(saved) == 2, "only what fits goes into the run"
    assert stats["knownFindings"] == 5, "but the whole memory is counted, not the trimmed one"

    brief = knowledge.upstream(project, [old.id])
    assert len(brief["findings"]) == 5, "the brief is not trimmed"


def test_upstream_carries_the_summary_and_notes(project, make_run):
    """The brief for the next in line is not a list of findings — it is also
    what the previous specialist added in their own words."""
    old = make_run()
    fid = old.findings()[0]["id"]
    runs.append_note(old, fid, "verified in production, this is a regression",
                     by="hire:review-graph@claude")
    (old.dir / "summary.md").write_text("# Review\n\nTwo findings, one disputed.\n",
                                        encoding="utf-8")

    data = knowledge.upstream(project, [old.id])

    assert data["runs"][0]["summary"].startswith("# Review")
    finding = next(f for f in data["findings"] if f["id"] == fid)
    assert finding["notes"][0]["text"].startswith("verified")
    assert finding["notes"][0]["by"] == "hire:review-graph@claude"


def test_a_runs_background_does_not_carry_notes(project, make_run):
    """A note is a discussion thread. It does not belong in every later
    run's background — that one assumes 300 items are read at once."""
    old = make_run()
    runs.append_note(old, old.findings()[0]["id"], "a long discussion", by="human")
    new = make_run(findings=[])

    knowledge.for_run(project, new)

    saved = json.loads(
        (new.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))
    assert "notes" not in saved[0]


# ------------------------------------------------------------------ summary

def test_a_runs_summary_is_recorded(project, make_run):
    """The core neither produces nor edits the summary — it only records
    that the pack wrote one. Without this the run record cannot tell whether
    a run left anything behind."""
    from agency import ingest as ingest_mod

    run = make_run()
    (run.dir / "summary.md").write_text("Went through the payment flow.\n", encoding="utf-8")
    ingest_mod.ingest(project, run)
    assert run.record()["outputs"]["summary"] is True
    assert knowledge.summary(run).startswith("Went through")

    without = make_run()
    ingest_mod.ingest(project, without)
    assert without.record()["outputs"]["summary"] is False
    assert knowledge.summary(without) is None


# ------------------------------------------------------- do not report again

def _reject(project, run, title, reason, at):
    """One rejection in the committed trail — the source this brief reads."""
    runs.append_trail(project, {
        "id": ulid(), "runId": run.id, "pack": "review-graph", "state": "rejected",
        "title": title, "severity": "high", "dimension": "correctness",
        "fingerprint": None, "anchor": {"file": "src/auth.ts", "line": 2},
        "by": "hire:review-graph@claude", "reason": reason, "at": at,
    })


def test_the_rejections_come_back_as_something_readable(project, make_run):
    """A row in a three-hundred-element array is not delivery. "This was
    already rejected as by-design" is the most valuable sentence a new run
    can be handed, so it gets its own file, in prose."""
    run = make_run()
    _reject(project, run, "Session survives the tab closing", "by-design", "2026-09-01T10:00:00Z")
    _reject(project, run, "Retry loop is unbounded", "wrong-diagnosis", "2026-09-02T10:00:00Z")
    _reject(project, run, "Cache key collides", "by-design", "2026-09-03T10:00:00Z")

    text = knowledge.do_not_report(project)

    assert "## by-design (2)" in text
    assert "## wrong-diagnosis (1)" in text
    assert "Session survives the tab closing" in text
    # And it points at where the whole story is, not just the headline.
    assert "findings/" in text


def test_nothing_rejected_yet_means_no_file_at_all(project, make_run):
    """A file that is always empty stops being read, and takes the ones that
    matter down with it."""
    make_run()
    assert knowledge.do_not_report(project) is None


def test_the_cap_cuts_inside_a_reason_never_a_whole_reason(project, make_run):
    """`by-design` means "never report this again" and has to survive the cut;
    `not-reproducible` from March may simply be reproducible today. Cutting by
    age across the whole file would delete the durable category first, because
    it is the one that stops accumulating."""
    run = make_run()
    for i in range(40):
        _reject(project, run, f"Noisy finding number {i}", "not-reproducible",
                f"2026-09-{(i % 28) + 1:02d}T10:00:00Z")
    _reject(project, run, "That is the design", "by-design", "2026-01-01T10:00:00Z")

    text = knowledge.do_not_report(project)

    assert len(text.splitlines()) <= knowledge.DO_NOT_REPORT_LINES
    # The oldest entry in the file, and it is still here.
    assert "That is the design" in text
    assert "## by-design" in text
    # And what did not fit is admitted, not silently dropped.
    assert "not listed" in text


def test_a_run_is_handed_the_brief_next_to_its_memory(project, make_run):
    """It has to be produced by the preparation, or nothing delivers it."""
    run = make_run()
    _reject(project, run, "Session survives the tab closing", "by-design",
            "2026-09-01T10:00:00Z")
    later = make_run(run_id=ulid())

    stats = knowledge.for_run(project, later)

    assert (later.dir / "evidence" / knowledge.DO_NOT_REPORT).is_file()
    assert stats["knownRejections"] == 1


def test_every_memory_stat_stays_out_of_the_graph_block(project, make_run):
    """run.v1's `graph` has a CLOSED key list, so a stat `for_run` returns and
    `MEMORY_STATS` does not name makes the whole record invalid — and nothing
    notices, because the gate validates `finding.v1`. That happened for real
    with `knownSpecs`. This is the check that cannot drift."""
    run = make_run()
    _reject(project, run, "Session survives the tab closing", "by-design",
            "2026-09-01T10:00:00Z")
    later = make_run(run_id=ulid())
    (later.dir / "specs").mkdir(parents=True, exist_ok=True)
    (later.dir / "specs" / "login.spec.ts").write_text("test", encoding="utf-8")
    knowledge.for_run(project, later)

    third = make_run(run_id=ulid())
    stats = knowledge.for_run(project, third)

    assert "knownSpecs" in stats and "knownRejections" in stats, "the case under test"
    assert set(stats) <= set(runs.MEMORY_STATS), (
        f"{sorted(set(stats) - set(runs.MEMORY_STATS))} would land in run.json → graph, "
        f"which run.v1 refuses")
