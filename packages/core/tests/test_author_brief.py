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


# ------------------------------------------------------------- author --revise

def _revise_args(project, pack: str):
    from types import SimpleNamespace
    return SimpleNamespace(
        repo=str(project.root), pack="author", revise=pack, json=False,
        pr=None, latest_merged=False, prompt=None, since=None, model=None,
        provider=None, bypass=False, force=False, unattended=False,
        wait=False, launch=False, remote_control=None, origin="cli", device=None)


def test_revising_below_the_threshold_refuses_to_start(project, make_run):
    """A condition, not a warning. A pack with five findings nobody decided on
    has nothing to learn from, and a revision against them replaces the one
    method whose numbers were known with a differently random one."""
    import pytest
    from agency import packs

    packs.seed(project, "author")
    _decided(project, make_run, 2, 1)

    with pytest.raises(SystemExit, match="at least 10"):
        cli.cmd_run(_revise_args(project, "review-graph"))


def test_revising_above_the_threshold_hands_over_the_brief(project, make_run):
    """The brief IS the assignment — which is why `--revise` needs no
    `--prompt` even though `author` normally requires one."""
    from agency import packs

    packs.seed(project, "author")
    for i in range(4):
        _decided(project, make_run, 2, 1, run_id=f"01R{i}0000000000000000000000")

    code = cli.cmd_run(_revise_args(project, "review-graph"))

    assert code == 0
    run = next(r for r in runs.load_runs(project) if r.record()["pack"] == "author")
    brief = (run.dir / "evidence" / "for-author.md").read_text(encoding="utf-8")
    assert "What review-graph has been doing" in brief
    assert (run.dir / "evidence" / "for-author.json").is_file()

    ctx = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["revise"]["pack"] == "review-graph"
    assert ctx["revise"]["brief"] == "evidence/for-author.md"
    assert ctx["revise"]["skill"].endswith("agency-review-graph")


def test_only_the_author_may_revise(project, make_run):
    """Any other pack would be rewriting a method it does not own."""
    import pytest
    args = _revise_args(project, "review-graph")
    args.pack = "review-graph"

    with pytest.raises(SystemExit, match="belongs to"):
        cli.cmd_run(args)


def test_revising_a_pack_that_does_not_exist_says_so_first(project):
    import pytest
    from agency import packs

    packs.seed(project, "author")
    with pytest.raises(SystemExit, match="Unknown pack"):
        cli.cmd_run(_revise_args(project, "not-a-pack"))
