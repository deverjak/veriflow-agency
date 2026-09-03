"""The committed trail — memory that survives a discarded run.

Three things break easily without anyone noticing: the last line for an id
has to win (not the first), a broken line must not take down every read, and
what the trail remembers has to actually reach dedup and a later run's own
background once the run directory it came from is gone.
"""

from __future__ import annotations

import json
import shutil

from agency import ingest, knowledge, runs

RUN_A = "01AAAAAAAAAAAAAAAAAAAAAAAA"
RUN_B = "01BBBBBBBBBBBBBBBBBBBBBBBB"


def _known_findings(run) -> list[dict]:
    return json.loads((run.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ append / read

def test_last_line_for_an_id_wins(project, make_run):
    run = make_run(run_id=RUN_A)
    fid = run.findings()[0]["id"]

    runs.append_trail(project, {"id": fid, "runId": run.id, "state": "gated-out",
                                "reason": "phantom-file"})
    runs.append_trail(project, {"id": fid, "runId": run.id, "state": "sent", "reason": None})

    assert runs.read_trail(project)[fid]["state"] == "sent"


def test_a_broken_line_is_skipped_not_fatal(project, make_run):
    run = make_run(run_id=RUN_A)
    fid = run.findings()[0]["id"]
    runs.append_trail(project, {"id": fid, "runId": run.id, "state": "sent"})

    with open(runs.trail_path(project), "a", encoding="utf-8") as f:
        f.write("this is not json\n")

    assert runs.read_trail(project)[fid]["state"] == "sent"


def test_reading_an_empty_trail_is_not_an_error(project):
    assert runs.read_trail(project) == {}


# ------------------------------------------------------------------ dedup

def test_earlier_findings_takes_sent_and_rejected_from_the_trail(project, make_run):
    """A run that no longer exists still reported something — dedup keeps
    comparing against it, or discarding a run brings its findings back."""
    gone = make_run(run_id=RUN_A)
    gone_finding = gone.findings()[0]
    runs.append_trail(project, {
        "id": gone_finding["id"], "runId": gone.id, "state": "sent",
        "fingerprint": gone_finding.get("fingerprint") or "fp-sent",
        "title": gone_finding["title"], "anchor": gone_finding["anchor"],
    })
    shutil.rmtree(gone.dir)

    later = make_run(run_id=RUN_B)
    pool = ingest.earlier_findings(project, later)

    assert any(f["id"] == gone_finding["id"] for f in pool)


def test_earlier_findings_also_takes_rejected(project, make_run):
    gone = make_run(run_id=RUN_A)
    gone_finding = gone.findings()[0]
    runs.append_trail(project, {
        "id": gone_finding["id"], "runId": gone.id, "state": "rejected",
        "reason": "by-design", "fingerprint": gone_finding.get("fingerprint") or "fp-rej",
        "title": gone_finding["title"], "anchor": gone_finding["anchor"],
    })
    shutil.rmtree(gone.dir)

    pool = ingest.earlier_findings(project, make_run(run_id=RUN_B))

    assert any(f["id"] == gone_finding["id"] for f in pool)


def test_gated_out_does_not_suppress(project, make_run):
    """Being dropped by the deterministic gate is a mechanic, not a
    judgement on the claim — the same finding from a cleaner angle still
    deserves a fresh look, so it must not dedup itself away."""
    holder = make_run(run_id=RUN_A, findings=[])
    runs.append_trail(project, {"id": "01GATEDOUTGATEDOUTGATEDOUT", "runId": holder.id,
                                "state": "gated-out", "reason": "phantom-file",
                                "fingerprint": "fp-gated"})

    pool = ingest.earlier_findings(project, make_run(run_id=RUN_B))

    assert not any(f["id"] == "01GATEDOUTGATEDOUTGATEDOUT" for f in pool)


# ------------------------------------------------------------------ known-findings.json

def test_for_run_remembers_a_discarded_runs_findings(project, make_run):
    """`.agency/runs/` is where the truth lives — until someone deletes it.
    The trail is what survives that, and a new run's background has to
    still carry it, or the next specialist repeats work already done."""
    gone = make_run(run_id=RUN_A)
    gone_finding = gone.findings()[0]
    runs.append_trail(project, {
        "id": gone_finding["id"], "runId": gone.id, "state": "sent",
        "title": gone_finding["title"], "anchor": gone_finding["anchor"],
        "pack": "review-graph", "by": "hire:review-graph@claude",
    })
    shutil.rmtree(gone.dir)

    new = make_run(run_id=RUN_B, findings=[])
    stats = knowledge.for_run(project, new)

    assert stats["knownFindings"] == 1
    saved = _known_findings(new)
    assert saved[0]["id"] == gone_finding["id"]
    assert saved[0]["decision"] == "sent"
