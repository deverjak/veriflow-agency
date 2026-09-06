"""The brief a pack's method gets revised against.

`agency metrics` answers "how is this project doing". This answers one
question for one reader — what in this pack's `SKILL.md` is wrong — and the
reader may be an agent.

The hardest requirement is not in the numbers, it is next to them: every
figure has to carry its own denominator. A dimension with one decided finding
is not a precision of 1.0, and a revision that treats it as one makes the pack
differently random rather than better.
"""

from __future__ import annotations

import json

from agency import cli, metrics, runs

from conftest import make_finding

BY = "hire:review-graph@claude"


def _decided(project, make_run, accepted: int, rejected: int, **over):
    run = make_run(findings=[
        make_finding(project, "x", title=f"Finding number {i} of this run",
                     score=90 - i)
        for i in range(accepted + rejected)], **over)
    ids = [f["id"] for f in run.findings()]
    for fid in ids[:accepted]:
        runs.append_decision(run, fid, "sent", by=BY)
    for fid in ids[accepted:]:
        runs.append_decision(run, fid, "rejected", reason="by-design", by=BY)
    return run


def test_the_brief_is_about_one_pack(project, make_run):
    from conftest import install_pack
    install_pack(project, "legal", {"target": "workspace", "worktree": False})
    _decided(project, make_run, 2, 1)
    make_run(run_id="01ZZZZZZZZZZZZZZZZZZZZZZZZ", pack="legal")

    brief = metrics.for_author(project, "review-graph")

    assert brief["pack"] == "review-graph"
    assert brief["runs"] == 1, "the legal run is somebody else's history"


def test_every_number_carries_its_denominator(project, make_run):
    """The failure this exists to prevent: a dimension with one decided
    finding read as a precision of 1.0."""
    _decided(project, make_run, 1, 0)

    brief = metrics.for_author(project, "review-graph")
    text = metrics.author_brief(brief)

    row = brief["byDimension"]["correctness"]
    assert row["decided"] == 1
    assert row["signal"] is False
    assert "too few to tell" in text


def test_it_refuses_to_look_authoritative_under_the_threshold(project, make_run):
    """Fáze D's own condition, said in the artefact itself rather than only in
    the plan — the brief is what a person or an agent actually reads."""
    _decided(project, make_run, 2, 1)

    text = metrics.author_brief(metrics.for_author(project, "review-graph"))

    assert "not enough to revise on" in text


def test_the_population_of_every_cost_number_is_named(project, make_run):
    """A brief that mixes attended and unattended leads to a revision resting
    on an average over nothing."""
    _decided(project, make_run, 1, 1, trigger={"kind": "manual", "attended": True})

    text = metrics.author_brief(metrics.for_author(project, "review-graph"))

    assert "were attended and recorded neither" in text


def test_a_blocked_run_is_in_the_brief_with_its_reason(project, make_run):
    """A wall hit twice is a `needs` or a SKILL.md problem, not a project
    problem — and that is exactly the kind of thing a revision should fix."""
    make_run(run_id="01B1000000000000000000000A", status="blocked",
             exitReason="staging returned 502 on every attempt")

    brief = metrics.for_author(project, "review-graph")

    assert brief["blocked"][0]["why"] == "staging returned 502 on every attempt"
    assert "502" in metrics.author_brief(brief)


def test_the_cli_says_so_when_the_pack_does_not_exist(project, capsys):
    """Said now, not after assembling a brief about nothing."""
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["metrics", "--for-author", "not-a-pack", "--repo", str(project.root)])


def test_the_brief_comes_out_as_data_too(project, make_run, capsys):
    """Krok 11 hands this to an agent; a person reads the markdown."""
    _decided(project, make_run, 1, 1)

    code = cli.main(["metrics", "--for-author", "review-graph",
                     "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    assert data["pack"] == "review-graph"
    assert data["triage"]["accepted"] == 1
