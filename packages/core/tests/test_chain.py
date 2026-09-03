"""`agency chain`: specialists in sequence, handing over between them.

This file runs the whole way through the CLI (`cli.cmd_chain`), because it is
the wiring between the pieces that breaks: `--wait`, `knowledge.upstream()`
and triage all worked individually before this existed.

What is locked down here:

  * the chain lives in data (`run.chain`), not in directory order — without
    that there is no telling afterwards which decision was made over
    someone else's finding as part of a handover,
  * the brief for the second member has NO cap (unlike the background), or
    the chain would quietly manufacture findings nobody decided on,
  * a predecessor's message is its own words, not the core's retelling,
  * a refused or crashed step stops the chain and says what finished.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agency import chain, cli, knowledge, proc, runs
from agency.util import posix, write_json

from conftest import install_pack, make_finding


def args(project, *members, **over) -> SimpleNamespace:
    base = dict(repo=str(project.root), json=False, members=list(members),
                pr=None, latest_merged=False, prompt="reconsent after expiry",
                since=None, model=None, provider=None, bypass=False, force=False,
                keep_worktree=False, focus=None)
    base.update(over)
    return SimpleNamespace(**base)


def specialist(project, monkeypatch, *, findings=1, handoff: str | None = None,
               code: int = 0, fails_on: int = 0):
    """An agent that genuinely leaves something behind.

    It finds its own run by the `running` status — a real agent has RUN_DIR
    from the prompt, but the fake does not get it through `proc.attend`. It
    writes what a handover stands on: findings and `handoff.md`.
    """
    seen = {"steps": 0, "argv": [], "env": []}

    def work(argv, cwd=None, env=None):
        seen["steps"] += 1
        seen["argv"].append(list(argv))
        seen["env"].append(dict(env or {}))
        run = next(r for r in runs.load_runs(project)
                   if r.record().get("status") == "running")
        write_json(run.findings_path,
                   [make_finding(project, run.id, title=f"Finding of step {seen['steps']}")
                    for _ in range(findings)])
        (run.dir / "summary.md").write_text(f"Summary of step {seen['steps']}.", encoding="utf-8")
        if handoff:
            (run.dir / "handoff.md").write_text(handoff, encoding="utf-8")
        if fails_on and seen["steps"] == fails_on:
            return 1
        return code

    def fake_stream(argv, cwd=None, env=None, on_line=None, timeout=None):
        # A chain member runs unattended, so the core reads a stream of
        # events instead of a terminal. The fake speaks the same dialect —
        # otherwise the tests would lock a path the real chain never takes.
        rc = work(argv, cwd=cwd, env=env)
        if on_line:
            on_line('{"type":"system","subtype":"init","session_id":"test-session"}')
            on_line('{"type":"result","subtype":"success","is_error":false,'
                    '"num_turns":3,"total_cost_usd":0.01,"session_id":"test-session",'
                    '"result":"Done.","permission_denials":[]}')
        return rc

    monkeypatch.setattr(proc, "attend", work)
    monkeypatch.setattr(proc, "stream", fake_stream)
    return seen


def test_the_guard_watches_both_paths_to_a_real_agent():
    """A safety net, not cosmetics.

    The guard lives in `conftest.py` and watches `proc.attend` and
    `proc.stream` alike. It used to live here and watch only `attend` — and
    that backfired exactly when the chain switched to `stream`: tests started
    launching a real `claude` and waiting for it. This empty test keeps the
    reason next to the place it happened.
    """
    with pytest.raises(AssertionError, match="real agent"):
        proc.attend(["claude", "-p"])
    with pytest.raises(AssertionError, match="real agent"):
        proc.stream(["claude", "-p"])


@pytest.fixture
def team(project):
    """Two workspace packs — legal and product-owner, the plan's pair."""
    install_pack(project, "legal", {"target": "workspace", "worktree": False, "prompt": "optional"})
    install_pack(project, "po", {"target": "workspace", "worktree": False, "prompt": "optional"})
    return project


# ------------------------------------------------------------------ composition

def test_a_chain_needs_at_least_two_members(team):
    """For one, the command is `agency run`. A chain of one would just be a
    more expensive way to write the same thing."""
    with pytest.raises(SystemExit, match="at least two"):
        cli.cmd_chain(args(team, "legal"))


def test_a_typo_in_the_third_name_does_not_cost_two_runs(team):
    """Members are verified before the first run, not along the way."""
    with pytest.raises(SystemExit):
        cli.cmd_chain(args(team, "legal", "po", "does-not-exist"))
    assert runs.load_runs(team) == []


# ------------------------------------------------------------------ the run

def test_the_chain_finishes_and_is_in_the_data(team, monkeypatch, capsys):
    """Step 3's acceptance check: two runs, both carrying the same
    `chain.id`, the second one holding the first in `upstream`."""
    specialist(team, monkeypatch)

    code = cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    assert code == 0
    done = sorted(runs.load_runs(team), key=lambda r: r.id)
    assert len(done) == 2

    first, second = (r.record() for r in done)
    assert first["chain"]["id"] == second["chain"]["id"]
    assert (first["chain"]["position"], first["chain"]["of"]) == (1, 2)
    assert (second["chain"]["position"], second["chain"]["of"]) == (2, 2)
    assert first["chain"]["upstream"] == []
    assert second["chain"]["upstream"] == [done[0].id]
    # Both ran through the gate — the chain does not wait on a manual `agency ingest`.
    assert first["status"] == "ok" and second["status"] == "ok"


def test_the_second_member_gets_upstream_with_no_cap(team, monkeypatch, capsys):
    """The cap of 300 belongs to the background. The brief must not be
    trimmed: a finding that does not fit is a finding the second specialist
    never decided on."""
    specialist(team, monkeypatch, findings=5)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    upstream = json.loads((second.dir / "evidence" / "upstream.json").read_text(encoding="utf-8"))

    assert upstream["counts"]["findings"] == 5
    assert upstream["counts"]["undecided"] == 5
    assert len(upstream["findings"]) == 5
    assert upstream["runs"][0]["summary"].startswith("Summary of step 1")


def test_context_tells_the_pack_it_is_in_a_chain(team, monkeypatch, capsys):
    """A pack learns its role from `context.json`, not from the prompt — the
    agent reads the prompt once, but context.json lasts the whole run."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    ctx = json.loads((second.dir / "context.json").read_text(encoding="utf-8"))

    assert ctx["chain"]["position"] == 2
    assert ctx["chain"]["upstreamFile"] == "evidence/upstream.json"
    assert ctx["chain"]["handoffFile"] == "handoff.md"

    first = sorted(runs.load_runs(team), key=lambda r: r.id)[0]
    assert json.loads((first.dir / "context.json").read_text(encoding="utf-8"))["chain"]["position"] == 1


# ------------------------------------------------------------------ handover

def test_a_predecessors_message_is_its_own_words(team, monkeypatch, capsys):
    """`handoff.md` goes into the prompt verbatim. If the core retold it, it
    would be a sentence nobody signed."""
    specialist(team, monkeypatch, handoff="Reconsent rests on an assumption about accounts — confirm it.")

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    prompt = (second.dir / "prompt.txt").read_text(encoding="utf-8")

    assert "Reconsent rests on an assumption about accounts — confirm it." in prompt
    assert "step 2/2" in prompt
    assert "evidence/upstream.json" in prompt
    assert "First judge those findings" in prompt


def test_without_a_handoff_the_summary_is_passed_on(team, monkeypatch, capsys):
    """`handoff.md` is optional. When it is missing, a descriptive summary is
    still a better input than bare counts."""
    specialist(team, monkeypatch, handoff=None)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    assert "Summary of step 1." in (second.dir / "prompt.txt").read_text(encoding="utf-8")


def test_the_first_member_gets_no_upstream(team, monkeypatch, capsys):
    """Nobody handed the first member anything — the prompt has to say so
    instead of staying silent."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    first = sorted(runs.load_runs(team), key=lambda r: r.id)[0]
    prompt = (first.dir / "prompt.txt").read_text(encoding="utf-8")

    assert "step 1/2" in prompt
    assert "You run first" in prompt
    assert not (first.dir / "evidence" / "upstream.json").exists()


def test_an_agents_silence_is_not_invented_for_it(team, monkeypatch, capsys):
    """When a member leaves neither a handoff nor a summary, the prompt falls
    back on counts. Inventing a message on its behalf would be a claim
    nobody signed."""
    def fake(argv, cwd=None, env=None, on_line=None, timeout=None):
        run = next(r for r in runs.load_runs(team) if r.record().get("status") == "running")
        write_json(run.findings_path, [make_finding(team, run.id)])
        return 0
    monkeypatch.setattr(proc, "stream", fake)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    prompt = (second.dir / "prompt.txt").read_text(encoding="utf-8")
    assert "Handoff from" not in prompt
    assert "1 findings" in prompt


def test_the_agent_may_read_the_whole_project_memory(team, monkeypatch, capsys):
    """Authorization must cover what the core itself handed over.

    `context.json` sends the specialist into the `knowledge` bundle, into the
    pack's pages, and in a chain into `evidence/upstream.json` with links to
    other runs. Only RUN_DIR used to be allowed, so a run in a worktree hit
    "Read outside the working directories" on a directory the core itself
    pointed it at.
    """
    seen = specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    for step in seen["argv"]:
        assert "--add-dir" in step
        allowed = step[step.index("--add-dir") + 1]
        assert allowed == posix(team.agency_dir), (
            f"the agent was granted {allowed}, but it reads the whole project memory")


def test_the_granted_directory_covers_upstream_and_bundle(team, monkeypatch, capsys):
    """Specifically: the second member's run dir, the first member's run,
    and the knowledge bundle all sit under that one granted directory."""
    seen = specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    allowed = Path(seen["argv"][1][seen["argv"][1].index("--add-dir") + 1])
    first, second = sorted(runs.load_runs(team), key=lambda r: r.id)
    for path in (second.dir, first.dir, team.agency_dir / knowledge.BUNDLE):
        assert allowed in path.parents or allowed == path, f"{path} is outside the granted directory"


# ------------------------------------------------------------------ stopping

def test_a_failed_step_stops_the_chain(team, monkeypatch, capsys):
    """Going on quietly would mean the product owner judges findings that
    never came into being."""
    specialist(team, monkeypatch, fails_on=1)

    code = cli.cmd_chain(args(team, "legal", "po"))
    printed = capsys.readouterr().out

    assert code != 0
    assert len(runs.load_runs(team)) == 1, "the second member should not have started"
    assert "the chain stops at step 1/2" in printed
    assert runs.load_runs(team)[0].record()["status"] == "failed"


def test_a_stopped_chain_says_what_finished(team, monkeypatch, capsys):
    """An interrupted chain is still a result, only a shorter one — and it
    has to show where to pick it up by hand."""
    install_pack(team, "qa", {"target": "workspace", "worktree": False, "prompt": "optional"})
    specialist(team, monkeypatch, fails_on=2)

    cli.cmd_chain(args(team, "legal", "po", "qa"))
    printed = capsys.readouterr().out

    assert "1/3" in printed and "2/3" in printed and "3/3" in printed
    assert "not started" in printed


# ------------------------------------------------------------------ autonomy

def test_a_chain_member_runs_unattended(team, monkeypatch, capsys):
    """This is the difference between a chain and a list of commands.

    `claude` and `codex` both start an interactive session by default that
    does NOT end when the task is done — it sits on the prompt waiting for
    more input. The orchestrator would then never get an exit code and the
    next member would never start.
    """
    seen = specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    for step in seen["argv"]:
        assert "-p" in step, f"a chain member must run unattended: {step}"
        assert step.index("-p") == 1, "for codex it is a subcommand, right after the binary"


def test_a_standalone_run_stays_attended():
    """`--wait` does not change the attended character: the user sees the
    session and can step into it. Unattended is a property of a CHAIN
    MEMBER, not of waiting for the end."""
    assert "-p" not in runs.launch_argv("/mem", "P")[0]
    assert "-p" in runs.launch_argv("/mem", "P", unattended=True)[0]


def test_the_record_says_the_run_was_not_attended(team, monkeypatch, capsys):
    """`cost.credential` is derived from this. Claiming "attended" about a
    run nobody could step into means billing it to the wrong credential."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    for run in runs.load_runs(team):
        assert run.record()["trigger"]["attended"] is False


def test_the_chain_record_matches_run_v1(team, monkeypatch, capsys):
    """The `chain` block has a closed key list in `run.v1`. The orchestrator
    carries a predecessor's message and a prompt flag in that same dict —
    neither belongs in the record."""
    specialist(team, monkeypatch, handoff="Message.")

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    for run in runs.load_runs(team):
        assert set(run.record()["chain"]) == set(chain.RECORD_KEYS)
        code = cli.main(["validate", "--run", run.id, "--repo", str(team.root), "--json"])
        assert json.loads(capsys.readouterr().out)["recordErrors"] == []
        assert code == 0


# ------------------------------------------------------------- per-member prompt

def test_a_prompt_for_one_member_does_not_reach_the_others(team, monkeypatch, capsys):
    """Without this, everyone got the same `--prompt`. A sentence addressed
    to somebody else is not context, it is a confusing instruction."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po",
                       prompt="review the terms", focus=["po:does this make product sense?"]))
    capsys.readouterr()

    first, second = sorted(runs.load_runs(team), key=lambda r: r.id)
    legal_prompt = (first.dir / "prompt.txt").read_text(encoding="utf-8")
    po_prompt = (second.dir / "prompt.txt").read_text(encoding="utf-8")

    assert "review the terms" in legal_prompt
    assert "product sense" not in legal_prompt, "someone else's prompt must not reach the reviewer"
    assert "does this make product sense?" in po_prompt
    assert "review the terms" not in po_prompt


def test_a_shared_prompt_says_it_is_shared(team, monkeypatch, capsys):
    """When the prompt is not split, it must at least be visible that it also
    speaks to the others."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po", prompt="do a review and work out whether it makes sense"))
    capsys.readouterr()

    prompt = (sorted(runs.load_runs(team), key=lambda r: r.id)[0]
              .dir / "prompt.txt").read_text(encoding="utf-8")
    assert "Prompt for the chain as a whole" in prompt
    assert "do only your part" in prompt


def test_a_prompt_for_an_unknown_member_is_refused(team):
    """A silently discarded prompt is worse than an error message."""
    with pytest.raises(SystemExit, match="not in this chain"):
        cli.cmd_chain(args(team, "legal", "po", focus=["qa:anything"]))


@pytest.mark.parametrize("bad", ["po", ":text", "po:", ""])
def test_a_malformed_focus_is_refused(team, bad):
    with pytest.raises(SystemExit, match="Expected <who>:<text>"):
        cli.cmd_chain(args(team, "legal", "po", focus=[bad]))


# ------------------------------------------------------------------ overview

def test_status_shows_chain_membership(team, monkeypatch, capsys):
    """Without it a team looks like several unrelated runs."""
    specialist(team, monkeypatch)
    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    cli.cmd_status(SimpleNamespace(repo=str(team.root), json=False, limit=10))
    printed = capsys.readouterr().out
    assert "chain" in printed and "1/2" in printed and "2/2" in printed


def test_status_json_carries_the_whole_block(team, monkeypatch, capsys):
    specialist(team, monkeypatch)
    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    cli.cmd_status(SimpleNamespace(repo=str(team.root), json=True, limit=10))
    data = json.loads(capsys.readouterr().out)
    blocks = [r["chain"] for r in data["runs"]]
    assert {b["position"] for b in blocks} == {1, 2}
    assert len({b["id"] for b in blocks}) == 1


# ------------------------------------------------------------------ units

def test_a_handoff_goes_through_whole(project, make_run):
    """The cap is generous and in bytes, because a handoff is not a kick-off
    line, it is the brief.

    The earlier 40-line cap looked reasonable and was not: the first real
    handoff ran to 120 lines and its only addressed section — "recommendation
    for the PO agent" — sat at the bottom, past the cut. The next member got
    the technical recap and "… (80 more lines in the file)" with no path to
    the file.
    """
    run = make_run()
    (run.dir / "handoff.md").write_text("\n".join(f"line {i}" for i in range(120)),
                                        encoding="utf-8")
    text, source, where = chain.handoff_text(run)

    assert source == "handoff.md"
    assert "line 119" in text, "the addressed part tends to be at the end"
    assert where.endswith("handoff.md"), "the file's path always goes into the prompt"


def test_a_genuinely_large_handoff_is_clipped_and_says_so(project, make_run):
    """The cap still exists — for the prompt's size, not for readability —
    and when it clips, it has to show where the rest is."""
    run = make_run()
    (run.dir / "handoff.md").write_text("\n".join("x" * 200 for _ in range(200)),
                                        encoding="utf-8")
    text, _, where = chain.handoff_text(run)

    assert len(text.encode("utf-8")) <= chain.HANDOFF_BYTES + 200
    assert "more lines in the file" in text
    assert where.endswith("handoff.md")


def test_an_empty_handoff_behaves_like_none(project, make_run):
    run = make_run()
    (run.dir / "handoff.md").write_text("   \n\n", encoding="utf-8")
    (run.dir / "summary.md").write_text("Summary.", encoding="utf-8")

    text, source, _ = chain.handoff_text(run)
    assert (text, source) == ("Summary.", "summary.md")


def test_ingest_records_that_a_handoff_exists(project, make_run):
    """The gate neither reads nor edits the file — it only records that it exists."""
    from agency import ingest
    run = make_run()
    (run.dir / "handoff.md").write_text("Message.", encoding="utf-8")

    ingest.ingest(project, run)
    assert run.record()["outputs"]["handoff"] is True
    assert run.record()["outputs"]["summary"] is False
