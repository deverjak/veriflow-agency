"""A decision is an operation on storage, not a UI command.

This is the test that closes step 1 of the plan. Its point is not "append
works" — it is proof that a decision survives the process, that the last write
wins, and that a rejection with no reason does not get through. Were any of
those three missing, precision could not be computed and the extension would
have to work the state out for itself.
"""

from __future__ import annotations

import json

import pytest

from agency import cli, runs


def test_a_decision_survives_a_reload(project, make_run):
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="hire:review-graph@claude")

    # Read from disk through a new object — as if the process had died meanwhile.
    reopened = runs.find_run(project, run.id)
    state = runs.decisions(reopened)
    assert state[fid]["state"] == "sent"
    assert state[fid]["by"] == "hire:review-graph@claude", \
        "who decided is an input to the next run, not decoration"


def test_the_last_write_wins_but_the_history_stays(project, make_run):
    """Append-only: the state is replayed, not mutated. Without that, two
    histories (a person's and an agent's) cannot be merged."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="vscode")
    runs.append_decision(run, fid, "rejected", reason="by-design", by="cli")

    assert runs.decisions(run)[fid]["state"] == "rejected"

    rows = [json.loads(l) for l in run.decisions_path.read_text(encoding="utf-8").splitlines() if l]
    assert [r["state"] for r in rows] == ["sent", "rejected"], "the history was overwritten"
    assert [r["by"] for r in rows] == ["human", "human"], \
        "an old write (`vscode`, `cli`) is a person — the door does not decide identity"


def test_a_rejection_with_no_reason_does_not_get_through(project, make_run):
    """Free text would cost the same effort and yield no number — precision
    cannot be computed from it. Hence a reason is required, and from an enum."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "rejected", by="human")
    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "rejected", reason="protoze-se-mi-nelibi", by="human")

    assert runs.decisions(run) == {}


def test_a_note_is_not_a_decision(project, make_run):
    """A note is free text for a reader, a decision is structured input to a
    metric. Mixing them breaks either the measurement or the usability."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "note", "findingId": fid,
                            "text": "ověřeno na produkci", "by": "vscode"}) + "\n")

    assert runs.decisions(run) == {}, "the note was counted as a decision"

    runs.append_decision(run, fid, "sent", by="human")
    assert runs.decisions(run)[fid]["state"] == "sent"


def test_the_same_finding_in_two_runs_has_its_own_decision(project, make_run):
    """A decision belongs to the finding in a run, not to the fingerprint. A
    finding from an older run stays decided after a new run over the same code."""
    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")

    runs.append_decision(older, older.findings()[0]["id"], "sent", by="human")

    assert len(runs.decisions(older)) == 1
    assert runs.decisions(newer) == {}


# -------------------------------------------------------------- projection
#
# `state = fold(events, policy)`. One place folds the log; everybody else asks
# it. The trap this guards against is not the event list — it is ten readers
# each replaying history their own way and quietly disagreeing about what the
# current state is.


def test_two_answers_to_two_questions_are_two_states(project, make_run):
    """The whole reason the projection exists. Folding to one verdict per
    output meant the second answer erased the first, so a bet that was chosen
    and then worked had no record of having been chosen."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        for state, cycle in (("selected", "selection"), ("successful", "outcome")):
            f.write(json.dumps({"kind": "decision", "findingId": fid, "state": state,
                                "lifecycle": cycle, "polarity": "positive",
                                "by": "human", "at": runs.now()}) + "\n")

    answers = runs.verdicts(run)[fid]

    assert answers["selection"]["state"] == "selected"
    assert answers["outcome"]["state"] == "successful"
    # And the older fold is unchanged for everyone who only asks whether
    # anybody judged this at all.
    assert runs.decisions(run)[fid]["state"] == "successful"


def test_the_last_answer_to_ONE_question_still_wins(project, make_run):
    """Two answers to the same question are a correction, not two facts. A
    fold that kept both would count one bet twice in its own ratio."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="human")
    runs.append_decision(run, fid, "rejected", reason="by-design", by="human")

    assert list(runs.verdicts(run)[fid]) == ["triage"]
    assert runs.verdicts(run)[fid]["triage"]["state"] == "rejected"


def test_an_event_from_before_lifecycles_is_read_through_the_policy(project, make_run):
    """Committed history has no `lifecycle` on its events — the field is
    younger than the log. The words were always the policy's, so that is where
    an old event is read from, rather than being filed under nothing."""
    run = make_run()
    fid = run.findings()[0]["id"]
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "decision", "findingId": fid, "state": "sent",
                            "by": "human", "at": runs.now()}) + "\n")

    assert runs.verdicts(run)[fid]["triage"]["state"] == "sent"


def test_a_state_no_policy_knows_is_not_an_answer_to_anything(project, make_run):
    """`deferred` is the one in the wild — `runs.py` says outright that nothing
    writes them any more. It must not become a lifecycle of its own, and it
    must not pass for an answer to a question somebody did ask."""
    run = make_run()
    fid = run.findings()[0]["id"]
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "decision", "findingId": fid, "state": "deferred",
                            "by": "human", "at": runs.now()}) + "\n")

    answers = runs.verdicts(run)[fid]

    assert list(answers) == [None]
    assert "triage" not in answers


def test_a_note_is_not_folded_into_the_state(project, make_run):
    """The same rule `decisions()` has always had, kept in the projection —
    otherwise a note would silently become the output's current verdict."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_note(run, fid, "checked on production", by="human")

    assert runs.verdicts(run) == {}


def test_a_duplicate_is_a_place_in_the_pipeline_not_a_verdict(project, make_run):
    """`dedup` writes `state: duplicate` on the output and no event at all, and
    that is the point: `state` is where an output stands, a verdict is what
    somebody said about it. Were the core to file its own bookkeeping as
    feedback, precision would start counting decisions nobody made."""
    from agency import ingest

    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, older)
    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    ingest.ingest(project, newer)

    assert newer.findings()[0]["state"] == "duplicate"
    assert runs.verdicts(newer) == {}
    assert runs.decisions(newer) == {}


def test_a_half_written_last_line_does_not_cost_the_verdicts_before_it(project, make_run):
    """The shape a killed process leaves. Reading the log is one function now,
    so this holds for every caller at once rather than for whichever one
    happened to guard against it."""
    run = make_run()
    fid = run.findings()[0]["id"]
    runs.append_decision(run, fid, "sent", by="human")
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write('{"kind": "decision", "findingId": "01X", "sta')

    assert runs.verdicts(run)[fid]["triage"]["state"] == "sent"
    assert runs.decisions(run)[fid]["state"] == "sent"


# ------------------------------------------------------------------ agency triage (CLI)

def test_triage_accept_is_dispatch(project, make_run):
    """`accept` is not a status flip — it runs the pack's sink. No sink in
    this fixture project, so the finding stays `candidate`, honestly."""
    run = make_run()
    fid = run.findings()[0]["id"]

    code = cli.main(["triage", "accept", fid, "--repo", str(project.root), "--json"])

    assert code == 0
    assert runs.find_run(project, run.id).findings()[0]["state"] == "candidate"


def test_triage_reject_requires_a_reason(project, make_run):
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        cli.main(["triage", "reject", fid, "--repo", str(project.root)])


def test_triage_defer_no_longer_exists(project, make_run):
    """There is no third verdict any more — what is not rejected goes to
    the board when the chain ends, so `defer` is simply not a command."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        cli.main(["triage", "defer", fid, "--repo", str(project.root)])


def test_an_old_accepted_write_still_reads_back(project, make_run):
    """History is not rewritten, only interpreted. A decisions.jsonl line
    from before this migration still means what it always meant."""
    run = make_run()
    fid = run.findings()[0]["id"]
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "decision", "findingId": fid, "state": "accepted",
                            "reason": None, "note": None, "by": "human",
                            "at": runs.now()}) + "\n")

    assert runs.decisions(run)[fid]["state"] == "accepted"


def test_packs_json_carries_the_sink(project, capsys):
    """`agency doctor` and the pack's own manifest both need to see the sink
    a pack declares — without it a project without a board looks the same
    as one whose sink is simply broken."""
    from conftest import install_pack
    install_pack(project, "review-graph", {"sink": "python sink.py --finding {id}"})

    cli.main(["packs", "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    by_name = {p["name"]: p for p in data}
    assert by_name["review-graph"]["sink"] == "python sink.py --finding {id}"


def test_export_command_no_longer_exists(project):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["export"])


def test_status_json_carries_the_provider_catalog(project, make_run, capsys):
    """A client picking a runner before a run starts (the extension's preset
    picker) needs the provider/model list without hardcoding it."""
    make_run()

    cli.main(["status", "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    ids = [p["id"] for p in data["project"]["providers"]]
    assert "claude" in ids and "codex" in ids


# ------------------------------------------------------------------ actions
#
# What an output DID, as opposed to what it says. It used to be
# `sinks: {prComment, githubProjectItem}` — two destinations, hardcoded, with
# no room for a result, a time, or a second attempt — and a product owner's
# decision could not be expressed in it at all, which is one of the two
# reasons that pack went around the core.
#
# The distinction every test here guards: the OUTPUT is what the specialist
# decided or wrote, an ACTION is what changed in the world because of it.

SINK = "python sink.py --finding {id} --run-dir {runDir}"


def _sink(project, body: str) -> None:
    (project.root / "sink.py").write_text(body, encoding="utf-8")


def _with_sink(project, prints: str, **manifest):
    from conftest import install_pack
    install_pack(project, "review-graph", {"sink": SINK, **manifest})
    _sink(project, f"print({prints!r})\n")


def test_a_sink_says_what_it_did_and_the_core_writes_that_down(project, make_run):
    """`backlog.py` has always printed `draft`, `comment`, `issue` — the core
    threw that away and recorded one hardcoded destination instead. The kind is
    the pack's word and the core never reads it; what the core supplies is the
    shape around it."""
    from agency import ingest

    _with_sink(project, '{"kind": "draft", "item": "PVTI_X", "target": "255", '
                        '"url": "https://example.com/PVTI_X"}')
    run = make_run()

    ingest.ingest(project, run)

    action = run.findings()[0]["actions"][0]
    assert action["kind"] == "draft"
    assert action["result"] == "success"
    assert action["remoteId"] == "PVTI_X" and action["target"] == "255"
    assert action["at"], "an action with no time cannot be put in order against another"


def test_a_silent_sink_is_recorded_as_what_the_core_actually_knows(project, make_run):
    """Which is: the pack's sink ran. Guessing `github_project_item` on its
    behalf would be the same hardcoding this replaces, one level down."""
    from agency import ingest

    _with_sink(project, '{"item": "PVTI_X"}')
    run = make_run()

    ingest.ingest(project, run)

    assert run.findings()[0]["actions"][0]["kind"] == runs.SINK_ACTION


def test_a_kind_that_is_not_a_name_does_not_become_one(project, make_run):
    """The kind comes off text this tool did not write. Storing it unchecked
    produces a findings.json that only fails much later, in `agency validate`,
    over a field nobody reads."""
    from agency import ingest

    _with_sink(project, '{"kind": "Board Draft!", "item": "PVTI_X"}')
    run = make_run()

    ingest.ingest(project, run)

    assert run.findings()[0]["actions"][0]["kind"] == runs.SINK_ACTION


def test_an_output_whose_type_may_not_act_is_never_sent(project, make_run):
    """`outputs.<type>.actions` has been declarable since types existed and
    nothing read it — so a pack with a board would have filed its bets on it,
    turning a proposal for the founder into a ticket. This is the one place
    that has to ask."""
    from agency import ingest
    from conftest import make_finding

    _with_sink(project, '{"item": "PVTI_X"}',
               outputs={"bet": {"actions": "none", "anchor": "none",
                                "evidence": {"required": ["graph"]}}})
    bet = make_finding(project, "x", type="bet")
    del bet["anchor"]
    run = make_run(findings=[bet, make_finding(project, "y")])

    result = ingest.ingest(project, run)

    kept = {f.get("type") or "finding": f for f in run.findings()}
    assert kept["bet"]["state"] == "candidate" and not kept["bet"].get("actions")
    assert kept["finding"]["state"] == "sent", "and the pack's other type still goes"
    assert result["sent"] == 1


def test_the_ledger_reads_where_the_output_ended_up(project, make_run):
    """The committed ledger is the half of memory a colleague with no Agency
    reads. It got the board reference out of `sinks`, so a page written after
    this step would have lost it."""
    from agency import ingest, knowledge

    _with_sink(project, '{"kind": "draft", "item": "PVTI_X"}')
    run = make_run()
    ingest.ingest(project, run)

    knowledge.bundle(project)

    page = (project.agency_dir / knowledge.BUNDLE / knowledge.LEDGER
            / f"{run.findings()[0]['id']}.md").read_text(encoding="utf-8")
    assert "PVTI_X" in page


def test_a_finding_sent_before_actions_existed_still_says_where_it_went(project, make_run):
    """Committed history is not rewritten — every finding sent before
    2026-09-07 carries `sinks.githubProjectItem` and nothing else. The same
    rule evidence without a locator lives by."""
    old = {"sinks": {"githubProjectItem": "PVTI_OLD"}}
    assert runs.acted_ref(old) == "PVTI_OLD"

    both = {"sinks": {"githubProjectItem": "PVTI_OLD"},
            "actions": [{"kind": "draft", "result": "success", "remoteId": "PVTI_NEW"}]}
    assert runs.acted_ref(both) == "PVTI_NEW", "the newer shape wins where both exist"

    assert runs.acted_ref({}) is None
    assert runs.acted_ref({"actions": [{"kind": "draft", "result": "error"}]}) is None, \
        "an attempt that failed is not a place the output ended up"


def test_an_action_that_reached_the_board_survives_a_second_ingest(project, make_run):
    """The gate rebuilds from `findings.raw.json`, which is what the PACK
    wrote — so re-running it silently un-recorded a board item that really had
    been created. Idempotence is a promise about the judgement; an action
    already taken is not a verdict and cannot be taken back by re-reading a
    file."""
    from agency import ingest

    _with_sink(project, '{"kind": "draft", "item": "PVTI_X"}')
    run = make_run()
    ingest.ingest(project, run)

    # The board goes down, and the gate is run again over the same run.
    _sink(project, "import sys\nsys.exit(1)\n")
    ingest.ingest(project, run)

    saved = run.findings()[0]
    assert [a["result"] for a in saved["actions"]] == ["success", "error"]
    assert runs.acted_ref(saved) == "PVTI_X", \
        "where it ended up is still known, even though the last attempt failed"


def test_an_output_that_reached_nothing_has_no_actions(project, make_run):
    """An empty list is a legitimate state and the common one — a project with
    no board keeps its findings in git. A reader that treats "no actions" as
    "not yet dispatched" would retry forever against a sink that does not
    exist."""
    from agency import ingest

    run = make_run()

    ingest.ingest(project, run)

    saved = run.findings()[0]
    assert saved["state"] == "candidate"
    assert not saved.get("actions")


def test_a_second_ingest_does_not_call_a_run_a_duplicate_of_itself(project, make_run):
    """Found by the test above rather than by argument. `earlier_findings`
    skips runs at or after this one, but the trail half had no such guard —
    so the second `agency ingest` compared this run's findings against the
    trail rows the FIRST one wrote, and marked everything already sent a
    duplicate of itself. `ingest` documents itself as idempotent; it was not."""
    from agency import ingest

    _with_sink(project, '{"kind": "draft", "item": "PVTI_X"}')
    run = make_run()
    ingest.ingest(project, run)

    ingest.ingest(project, run)

    assert run.findings()[0]["state"] != "duplicate"
