"""Running a pack again over a commit it has already judged.

Every part of this already existed and nobody had put them together:
`target.headRefOid` pins the code, the worktree makes it reproducible, the
fingerprint is deterministic, and the decisions say which findings turned out
to be true.

The number these tests are really about is `regressions`, because it is the
only one in the system with a single possible reading. Recall can fall for a
good reason — somebody fixed the bug — and "new" needs a person. A finding
this project has already said no to, coming back, is the method getting worse
at the one thing it was told.
"""

from __future__ import annotations

import json

from agency import cli, dedup, replay, runs

from conftest import make_finding

BY = "hire:review-graph@claude"


def _judged(project, make_run):
    """A run whose findings somebody decided on — the only kind worth pinning."""
    good = make_finding(project, "x", title="Session survives the tab closing")
    bad = make_finding(project, "x", dimension="reuse",
                       title="Nothing imports the retry helper",
                       body="No caller reaches `retryOnce` since the queue rewrite.",
                       anchor={"symbol": {"name": "retryOnce", "range": [1, 4]}})
    run = make_run(findings=[good, bad])
    ids = [f["id"] for f in run.findings()]
    runs.append_decision(run, ids[0], "sent", by=BY)
    runs.append_decision(run, ids[1], "rejected", reason="by-design", by=BY)
    return run, good, bad


def test_a_fixture_is_a_pinned_run(project, make_run):
    """Committed, because it is the project's answer key — not this machine's
    cache."""
    run, _, _ = _judged(project, make_run)

    fixture = replay.pin(project, run, "pr-479")

    assert fixture["pack"] == "review-graph"
    assert fixture["target"]["headRefOid"] == run.record()["target"]["headRefOid"]
    assert {g["decision"] for g in fixture["gold"]} == {"sent", "rejected"}
    assert (project.agency_dir / replay.EVALS / "pr-479.json").is_file()


def test_only_decided_findings_become_answers(project, make_run):
    """An undecided finding is not an answer. Pinning one would grade a pack
    against a queue nobody worked through."""
    import pytest
    make_run(run_id="01P0000000000000000000000A")
    run = runs.find_run(project, "01P0000000000000000000000A")

    with pytest.raises(SystemExit, match="no decided findings"):
        replay.pin(project, run, "empty")


def test_finding_the_same_true_things_again_is_recall(project, make_run):
    run, good, bad = _judged(project, make_run)
    fixture = replay.pin(project, run, "pr-479")

    result = replay.compare(fixture, [good])

    assert result["recall"] == 1.0
    assert result["recalled"] == 1 and result["recallOf"] == 1
    assert result["regressions"] == []
    assert result["pass"] is True


def test_a_rejected_finding_coming_back_is_a_regression(project, make_run):
    """The hard rule, and the reason it is hard: this is the one number with a
    single possible reading."""
    run, good, bad = _judged(project, make_run)
    fixture = replay.pin(project, run, "pr-479")

    result = replay.compare(fixture, [good, bad])

    assert len(result["regressions"]) == 1
    assert result["regressions"][0]["reason"] == "by-design"
    assert result["pass"] is False
    assert "already rejected" in replay.report(result)


def test_something_nobody_has_seen_is_neither_good_nor_bad(project, make_run):
    """`new` is for a person to judge — a method that got better and a method
    that got noisier both produce it."""
    run, good, _ = _judged(project, make_run)
    fixture = replay.pin(project, run, "pr-479")
    fresh = make_finding(project, "x", dimension="tests",
                         title="The cancellation path has no test at all",
                         body="`cancelOrder` is covered by nothing; a regression "
                              "there would ship silently.",
                         anchor={"symbol": {"name": "cancelOrder", "range": [1, 9]}})

    result = replay.compare(fixture, [good, fresh])

    assert len(result["new"]) == 1
    assert result["new"][0]["title"].startswith("The cancellation path")
    assert result["pass"] is True, "new findings do not fail a replay by themselves"


def test_a_finding_that_stopped_coming_back_is_reported_not_punished(
        project, make_run):
    """Recall can fall for a good reason — somebody fixed it — so it is said
    out loud and left to a person, unlike a regression."""
    run, _, _ = _judged(project, make_run)
    fixture = replay.pin(project, run, "pr-479")

    result = replay.compare(fixture, [])

    assert result["recall"] == 0.0
    assert len(result["missed"]) == 1
    assert result["pass"] is True


def test_matching_is_on_the_fingerprint_not_the_title(project, make_run):
    """A title survives a corrected diagnosis and the content does not — the
    same reason dedup does not use it either."""
    run, good, _ = _judged(project, make_run)
    fixture = replay.pin(project, run, "pr-479")
    reworded = {**good, "title": "Logging out leaves the profile readable"}
    assert dedup.fingerprint(reworded) == dedup.fingerprint(good)

    assert replay.compare(fixture, [reworded])["recall"] == 1.0


def test_the_cli_fails_the_run_when_something_regressed(project, make_run, capsys):
    """Exit code, so it can stand in a script between a revision and a commit."""
    run, _, _ = _judged(project, make_run)
    replay.pin(project, run, "pr-479")

    code = cli.main(["replay", "--fixture", "pr-479", "--repo", str(project.root),
                     "--json"])
    data = json.loads(capsys.readouterr().out)

    # The pinned run still has both findings on disk, the rejected one included.
    assert code == 1
    assert len(data["results"][0]["regressions"]) == 1


def test_replaying_without_a_fixture_says_how_to_make_one(project):
    import pytest
    with pytest.raises(SystemExit, match="agency replay --pin"):
        cli.main(["replay", "--pack", "review-graph", "--repo", str(project.root)])
