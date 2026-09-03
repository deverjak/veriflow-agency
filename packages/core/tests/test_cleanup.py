"""`agency cleanup --all` — bulk discard of finished runs.

The trail is committed and append-only, so bulk-discarding is safe even for
a run that already sent something: what it reported survives in
`.agency/knowledge/trail.jsonl` after `.agency/runs/<id>/` is gone. These
tests guard the two things that make that safety claim true: a running run
is never touched, and a run carrying a decision is skipped unless `--force`
says to take it anyway.
"""

from __future__ import annotations

import pytest

from agency import cli, runs


def test_all_without_discard_is_refused(project, make_run):
    make_run()

    with pytest.raises(SystemExit):
        cli.main(["cleanup", "--all", "--repo", str(project.root)])


def test_all_discards_finished_runs_and_leaves_running_alone(project, make_run):
    finished = make_run(status="ok")
    running = make_run(status="running")

    code = cli.main(["cleanup", "--all", "--discard", "--repo", str(project.root), "--json"])

    assert code == 0
    assert runs.find_run(project, finished.id) is None
    assert runs.find_run(project, running.id) is not None


def test_all_skips_runs_that_carry_decisions(project, make_run):
    decided = make_run(status="ok")
    runs.append_decision(decided, decided.findings()[0]["id"], "rejected",
                         reason="by-design", by="human")
    plain = make_run(status="ok")

    cli.main(["cleanup", "--all", "--discard", "--repo", str(project.root), "--json"])

    assert runs.find_run(project, decided.id) is not None, "a decision is work someone did — it stays"
    assert runs.find_run(project, plain.id) is None


def test_all_force_takes_decided_runs_too(project, make_run):
    decided = make_run(status="ok")
    runs.append_decision(decided, decided.findings()[0]["id"], "rejected",
                         reason="by-design", by="human")

    cli.main(["cleanup", "--all", "--discard", "--force",
             "--repo", str(project.root), "--json"])

    assert runs.find_run(project, decided.id) is None


def test_the_trail_survives_a_bulk_discard(project, make_run):
    run = make_run(status="ok")
    fid = run.findings()[0]["id"]
    runs.append_trail(project, {"id": fid, "runId": run.id, "state": "sent", "ref": "PVTI_X"})

    cli.main(["cleanup", "--all", "--discard", "--repo", str(project.root), "--json"])

    assert runs.find_run(project, run.id) is None
    assert runs.read_trail(project)[fid]["state"] == "sent"
