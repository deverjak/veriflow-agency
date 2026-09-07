"""Memory is a thing, not a side effect of starting a run.

Tests here guard three properties everything else stands on: attribution
(the ledger's trust tiers are built from it), the cap (the background has one,
the brief does not), and that the run projection did not change even though
`runs.py` no longer assembles it.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from agency import knowledge, packs, runs
from agency.util import ulid

from conftest import install_pack, make_finding


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


# --------------------------------------------------- memory about THIS code

def test_a_run_gets_the_history_of_the_files_it_touches(project, make_run):
    """A pull request into `src/auth.ts` wants the findings that were ever
    about `src/auth.ts` far more than it wants the newest three hundred. That
    is a question about shape, not ranking — hence a second short list rather
    than a re-sort of the long one."""
    older = make_run(findings=[
        make_finding(project, "01D0000000000000000000000A"),
        make_finding(project, "01D0000000000000000000000A", dimension="reuse",
                     title="Elsewhere entirely",
                     anchor={"file": "src/other.ts", "symbol": None}),
    ], run_id="01D0000000000000000000000A")
    assert len(older.findings()) == 2

    run = make_run(run_id="01D0000000000000000000000B")
    stats = knowledge.for_run(project, run, files=["src/auth.ts"])

    nearby = json.loads((run.dir / "evidence" / knowledge.HERE).read_text(encoding="utf-8"))
    assert [f["file"] for f in nearby] == ["src/auth.ts"]
    assert stats["knownHere"] == 1


def test_a_run_touching_nothing_familiar_gets_no_file(project, make_run):
    """A file that is usually empty teaches the reader to stop opening it,
    and then it is empty the one time it matters."""
    make_run(run_id="01E0000000000000000000000A")
    run = make_run(run_id="01E0000000000000000000000B")

    stats = knowledge.for_run(project, run, files=["src/brand-new.ts"])

    assert not (run.dir / "evidence" / knowledge.HERE).is_file()
    assert "knownHere" not in stats


def test_the_blast_radius_counts_as_here_too(project, make_run):
    """The graph already paid for `impact.json` during the same preparation.
    A finding on a symbol the change reaches is about this run even when its
    file is nowhere in the diff."""
    make_run(findings=[make_finding(project, "01F0000000000000000000000A")],
             run_id="01F0000000000000000000000A")
    run = make_run(run_id="01F0000000000000000000000B")
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "impact.json").write_text(
        json.dumps({"impacted_nodes": [{"name": "getUser", "kind": "function"}],
                    "impacted_files": []}), encoding="utf-8")

    knowledge.for_run(project, run, files=["src/totally-unrelated.ts"])

    nearby = json.loads((ev / knowledge.HERE).read_text(encoding="utf-8"))
    assert [f["symbol"] for f in nearby] == ["getUser"]

# ------------------------------------------------------ what a run is about
#
# `known-here.json` used to be selected by files and symbols out of
# `impact.json`, which is a code graph — so for `po` and `ceo`, both of which
# run with `graph: false`, it was dead code. The intersection asks the same
# question in a vocabulary a pack can also speak. The three tests above are
# review's answer, and they are the ones that must not change.


def _scope_command(script: Path) -> str:
    """A runnable `scope` command for a test pack.

    The interpreter running the suite rather than a `python` on PATH, as
    posix-quoted text, because a manifest holds a command line and
    `shlex.split` eats the backslashes in a Windows one.
    """
    return " ".join(shlex.quote(Path(p).as_posix()) for p in (sys.executable, script))


def _pack_that_knows_its_own_scope(project, prints: str, name: str = "ceo"):
    """A pack with no graph whose `scope` command says what its runs are about."""
    skill = install_pack(project, name, {"target": "workspace", "worktree": False,
                                         "graph": False})
    script = skill / "scripts" / "scope.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"print({prints!r})\n", encoding="utf-8")
    manifest = json.loads((skill / "pack.json").read_text(encoding="utf-8"))
    manifest["scope"] = _scope_command(script)
    (skill / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    return skill


def _about(project, run_id, ref, title, *, pack="ceo"):
    """One output about one bet — no anchor, so `subject` is its only place."""
    f = make_finding(project, run_id, pack=pack, type="bet", title=title,
                     subject={"kind": "bet", "ref": ref})
    del f["anchor"]
    return f


def test_a_pack_with_no_graph_finally_gets_a_here_list(project, make_run):
    """The acceptance criterion of the step: `known-here.json` non-empty for a
    pack that has no code graph. Until the intersection existed there was no
    vocabulary in which such a run could say what it was about, so the one
    short list a run is meant to read whole was always absent."""
    _pack_that_knows_its_own_scope(project, '[{"kind": "bet", "ref": "regional-distribution"}]')
    make_run(findings=[_about(project, "01G0000000000000000000000A",
                              "regional-distribution", "Distribuce přes instituce kraje")],
             run_id="01G0000000000000000000000A", pack="ceo")
    run = make_run(findings=[], run_id="01G0000000000000000000000B", pack="ceo")

    stats = runs.known_memory(project, run, [])

    nearby = json.loads((run.dir / "evidence" / knowledge.HERE).read_text(encoding="utf-8"))
    assert [f["subject"]["ref"] for f in nearby] == ["regional-distribution"]
    assert stats["knownHere"] == 1 and stats["scopeItems"] == 1


def test_a_run_about_one_bet_is_not_handed_the_others(project, make_run):
    """The narrowing has to narrow. A second short list that contains
    everything is the long list with extra steps."""
    _pack_that_knows_its_own_scope(project, '[{"kind": "bet", "ref": "regional-distribution"}]')
    make_run(findings=[
        _about(project, "01H0000000000000000000000A", "regional-distribution",
               "Distribuce přes instituce kraje"),
        _about(project, "01H0000000000000000000000A", "newsletter-retention",
               "Newsletter drží návštěvníky mezi sezónami"),
    ], run_id="01H0000000000000000000000A", pack="ceo")
    run = make_run(findings=[], run_id="01H0000000000000000000000B", pack="ceo")

    runs.known_memory(project, run, [])

    nearby = json.loads((run.dir / "evidence" / knowledge.HERE).read_text(encoding="utf-8"))
    assert [f["subject"]["ref"] for f in nearby] == ["regional-distribution"]


def test_the_scope_a_run_was_narrowed_by_is_written_down(project, make_run):
    """An empty `known-here.json` has two explanations — nothing matched, or
    the run never said what it was about — and without the scope beside it
    they look the same."""
    _pack_that_knows_its_own_scope(project, '[{"kind": "bet", "ref": "regional-distribution"}]')
    run = make_run(findings=[], pack="ceo")

    stats = runs.known_memory(project, run, ["src/auth.ts"])

    wanted = json.loads((run.dir / "evidence" / knowledge.SCOPE).read_text(encoding="utf-8"))
    assert {"kind": "file", "ref": "src/auth.ts"} in wanted
    assert {"kind": "bet", "ref": "regional-distribution"} in wanted
    assert stats["scopeItems"] == 2, "counted even though nothing matched it"


def test_a_scope_command_that_breaks_costs_the_memory_and_not_the_run(project, make_run):
    """The pack's own script is the least trustworthy thing in the
    preparation. Failing it costs this run its narrowed memory; killing the
    run over it costs the whole run — and what went wrong has to be readable
    afterwards, next to the evidence it did not produce."""
    skill = _pack_that_knows_its_own_scope(project, "unused")
    (skill / "scripts" / "scope.py").write_text(
        "import sys; sys.stderr.write('strategy.md is unreadable'); sys.exit(1)\n",
        encoding="utf-8")
    run = make_run(findings=[], pack="ceo")

    stats = runs.known_memory(project, run, [])

    assert stats["scopeItems"] == 0
    assert "unreadable" in (run.dir / "evidence" / "scope.error.txt").read_text(encoding="utf-8")


def test_a_scope_that_is_not_a_scope_is_refused_the_same_way(project, make_run):
    """A script that prints prose is the same failure as one that exits
    non-zero, and reading half of it would be worse than reading none."""
    _pack_that_knows_its_own_scope(project, "the live bets are: distribution")
    run = make_run(findings=[], pack="ceo")

    assert runs.known_memory(project, run, [])["scopeItems"] == 0
    assert (run.dir / "evidence" / "scope.error.txt").is_file()


def test_a_pack_that_declares_no_scope_runs_no_command(project, make_run):
    """Every pack in this repository but one declares nothing, and preparation
    must not start looking for a script that was never promised."""
    run = make_run(findings=[])

    stats = runs.known_memory(project, run, ["src/auth.ts"])

    assert stats["scopeItems"] == 1, "the changed file, and nothing the pack added"
    assert not (run.dir / "evidence" / "scope.error.txt").exists()


def test_the_run_is_told_where_its_scope_is(project, make_run):
    """The agent reads it — to write an output's `subject` in the vocabulary
    the memory it was handed was selected by — and never writes it."""
    _pack_that_knows_its_own_scope(project, '[{"kind": "bet", "ref": "regional-distribution"}]')
    pack = packs.load("ceo", project)
    run = make_run(findings=[], pack="ceo")
    runs.known_memory(project, run, [])

    runs.write_context(run, pack, {"kind": "workspace"}, project.root, [], 0)

    ctx = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["scope"] == "evidence/scope.json"


def test_doctor_says_when_a_declared_scope_script_is_not_there(project, capsys):
    """The quietest failure this step can produce. A manifest naming a script
    that is not there costs every run its narrowed memory and reports nothing
    at the time — the same shape as a missing sink, which is why it is the
    same check."""
    from agency import cli

    install_pack(project, "ceo", {"target": "workspace", "worktree": False,
                                  "scope": "python .claude/skills/agency-ceo/scripts/scope.py"})

    cli.main(["doctor", "--repo", str(project.root), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]

    broken = next(c for c in checks if c["name"] == "pack ceo scope")
    assert broken["ok"] is False and "scope.py" in broken["detail"]
    assert broken["fatal"] is False, "a run without narrowed memory is still a run"

