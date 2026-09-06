"""Output types and the policy a pack declares for them.

The point of this file is a boundary, and every test below is a way of asking
whether it still holds: **the core learns how an output is handled, never what
it means.** `BUILD-NOW`, `bet`, `stakeholder` never reach the core — what
reaches it is "deduplicate this", "this needs web evidence", "these are the
answers and this is their polarity". The day the core starts reading the
meaning, every future specialist has to pretend to be a code reviewer again.

The second thing they guard is the migration: a pack that declares nothing
must behave exactly as it did before types existed, because five of the six
packs in this repository declare nothing and every committed finding was
written without a type.
"""

from __future__ import annotations

import pytest

from agency import ingest, outputs, runs
from agency.util import write_json

from conftest import install_pack, make_finding

BET = {
    "cardinality": "many",
    "dedup": True,
    "evidence": {"required": ["document", "web_snapshot"], "min": 1},
    "actions": "none",
    "memory": "proposes",
    "feedback": {
        "selection": {"metric": "selection_rate",
                      "kinds": {"selected": "positive", "rejected": "negative"}},
        "outcome": {"metric": "success_rate", "requires": "selection.selected",
                    "kinds": {"successful": "positive", "failed": "negative",
                              "abandoned": "neutral"}},
    },
}

ANSWER = {"cardinality": "one", "dedup": False, "memory": "never",
          "actions": "none", "feedback": {}}


def _ceo(project, **types):
    """A pack that declares its own output types."""
    return install_pack(project, "ceo", {"minScore": 0, "outputs": types or {"bet": BET}})


# ------------------------------------------------------------ the default

def test_a_pack_that_declares_nothing_keeps_the_policy_it_had(project):
    """Five of the six packs declare no types and every committed finding was
    written without one. If this ever fails, the migration window is closed
    and it closed by accident."""
    from agency import packs

    pack = packs.load("review-graph", project)
    policy = outputs.policy_for(pack, None)

    assert policy.name == "finding"
    assert policy.dedup is True and policy.max_per_run is None
    assert policy.kinds == ("sent", "rejected")
    assert policy.polarity("sent") == "positive"
    assert policy.polarity("rejected") == "negative"


def test_the_finding_reasons_are_the_ones_the_board_uses():
    """`outputs` cannot import `runs` (it is read by the gate), so the five
    reasons are written twice. This is the test that holds them together —
    without it they drift and a rejection stops matching the board's field."""
    assert outputs.FINDING_REASONS == runs.REJECT_REASONS


def test_a_declared_type_does_not_take_the_default_with_it(project):
    pack = _pack(project)
    bet = outputs.policy_for(pack, "bet")
    finding = outputs.policy_for(pack, "finding")

    assert bet.required_evidence == ["document", "web_snapshot"]
    assert finding.required_evidence == [], "the default is untouched by a sibling"
    assert outputs.declares(pack, "bet") and outputs.declares(pack, "finding")
    assert not outputs.declares(pack, "manifesto")


def _pack(project, **types):
    from agency import packs
    _ceo(project, **types)
    return packs.load("ceo", project)


# ------------------------------------------------------------ two lifecycles

def test_one_output_can_have_two_questions_asked_of_it(project):
    """A bet is chosen, and later it works or it does not. Counting both in
    one ratio produces a number that is neither a selection rate nor a success
    rate — it just looks like a metric."""
    policy = outputs.policy_for(_pack(project), "bet")

    assert policy.lifecycle_of("selected").name == "selection"
    assert policy.lifecycle_of("failed").name == "outcome"
    assert policy.lifecycle_of("selected").metric == "selection_rate"
    assert policy.lifecycle_of("failed").metric == "success_rate"
    assert policy.lifecycle_of("failed").requires == "selection.selected"
    assert policy.polarity("abandoned") == "neutral"


def test_a_kind_in_two_lifecycles_is_reported(project):
    """Then no ratio could say which question the answer answered."""
    broken = dict(BET, feedback={
        "selection": {"kinds": {"selected": "positive", "done": "positive"}},
        "outcome": {"kinds": {"done": "positive", "failed": "negative"}},
    })
    pack = _pack(project, bet=broken)

    assert any("belongs to one lifecycle" in e for e in outputs.errors(pack))


def test_a_polarity_that_is_not_one_is_reported(project):
    pack = _pack(project, bet=dict(BET, feedback={
        "selection": {"kinds": {"selected": "good"}}}))

    assert any("one of positive" in e for e in outputs.errors(pack))


def test_requires_that_names_no_lifecycle_is_reported(project):
    pack = _pack(project, bet=dict(BET, feedback={
        "selection": {"kinds": {"selected": "positive"}},
        "outcome": {"requires": "review.accepted",
                    "kinds": {"successful": "positive"}}}))

    assert any("names no lifecycle" in e for e in outputs.errors(pack))


def test_a_typo_in_a_mechanical_key_is_reported(project):
    """The reason `agency doctor` asks at all: a policy is data the core acts
    on, so a wrong value does not fail — it defaults, quietly and wrongly."""
    pack = _pack(project, bet=dict(BET, cardinality="single", memory="always"))

    problems = " ".join(outputs.errors(pack))
    assert "cardinality" in problems and "memory" in problems


def test_a_healthy_policy_has_nothing_to_report(project):
    assert outputs.errors(_pack(project)) == []


# ------------------------------------------------------------ the gate

def _run(make_run, project, **over):
    f = make_finding(project, "x", pack="ceo", **over)
    return make_run(findings=[f], pack="ceo")


def test_an_undeclared_type_is_dropped_with_its_name(project, make_run):
    """Not silently defaulted. A pack writing `bet` into a project whose pack
    has no `bet` is a pack and a manifest that disagree, and defaulting hides
    exactly that."""
    _ceo(project)
    run = _run(make_run, project, type="manifesto")

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "unknown-type"
    assert "manifesto" in result["dropped"][0]["detail"]


def test_a_type_can_demand_evidence_a_dimension_never_could(project, make_run):
    """The whole reason a CEO output does not have to point at source: it has
    to point at something else, and the type is where that is said."""
    _ceo(project)
    run = _run(make_run, project, type="bet", evidence=[
        {"kind": "graph", "detail": "the graph says nothing about markets"}])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "weak-evidence"
    assert "bet needs document or web_snapshot" in result["dropped"][0]["detail"]


def test_the_evidence_a_type_asked_for_passes(project, make_run):
    _ceo(project)
    commit = _commit(project)
    run = _run(make_run, project, type="bet", evidence=[
        {"kind": "document", "detail": "the roadmap names distribution first",
         "locator": {"file": "src/auth.ts", "commit": commit}}])

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def _commit(project):
    from conftest import git
    return git(project.root, "rev-parse", "HEAD")


def test_a_type_that_says_one_per_run_means_one(project, make_run):
    """Two answers to one question are not two answers — they are a run that
    lost the plot. The first survives; the rest are dropped with a reason,
    not deleted."""
    _ceo(project, answer=ANSWER)
    a = make_finding(project, "x", pack="ceo", type="answer")
    b = make_finding(project, "x", pack="ceo", type="answer",
                     title="A different answer to the very same question",
                     body="Something else entirely, at length, for the schema.")
    run = make_run(findings=[a, b], pack="ceo")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1
    assert result["dropped"][0]["reason"] == "over-cardinality"


def test_the_ceiling_is_checked_last(project, make_run):
    """A dishonest eleventh output must be dropped as dishonest, not as
    eleventh — otherwise a broken pack hides behind a full quota."""
    _ceo(project, answer=ANSWER)
    good = make_finding(project, "x", pack="ceo", type="answer")
    bad = make_finding(project, "x", pack="ceo", type="answer",
                       title="An answer pointing at a file that is not there",
                       body="Long enough for the schema to be satisfied here.",
                       anchor={"file": "src/nowhere.ts"})
    run = make_run(findings=[good, bad], pack="ceo")

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "phantom-file"


# ------------------------------------------------------------ dedup

def test_a_type_can_opt_out_of_dedup(project, make_run):
    """Two answers to the same question a month apart are two answers, and
    marking the second a duplicate throws away the current one."""
    _ceo(project, answer=ANSWER)
    first = make_finding(project, "x", pack="ceo", type="answer")
    run_a = make_run(findings=[first], pack="ceo")
    ingest.ingest(project, run_a)

    again = make_finding(project, "y", pack="ceo", type="answer")
    run_b = make_run(findings=[again], pack="ceo")
    result = ingest.ingest(project, run_b)

    assert result["counts"]["kept"] == 1
    assert run_b.findings()[0]["state"] != "duplicate"


def test_two_types_saying_the_same_thing_are_not_duplicates(project, make_run):
    """A bet and a finding about the same page share their nouns. Without the
    type in the comparison the similarity layer folds one into the other."""
    from agency import dedup

    a = make_finding(project, "x", type="bet")
    b = dict(a, id=a["id"][:-1] + "Z", type="finding")

    assert dedup.is_duplicate(b, a) == (False, "")
    assert dedup.fingerprint(a) != dedup.fingerprint(b)


# ------------------------------------------------------------ feedback

def test_feedback_is_judged_against_the_type_that_received_it(project, make_run):
    _ceo(project)
    commit = _commit(project)
    run = _run(make_run, project, type="bet", evidence=[
        {"kind": "document", "detail": "the roadmap names distribution first",
         "locator": {"file": "src/auth.ts", "commit": commit}}])
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]

    ev = runs.append_decision(run, fid, "selected")

    assert ev["lifecycle"] == "selection" and ev["polarity"] == "positive"


def test_a_finding_verb_is_not_a_bet_verb(project, make_run):
    """`sent` means a board item, and a bet has no board. The vocabulary is
    the type's, and a wrong verb has to say which ones were right."""
    _ceo(project)
    commit = _commit(project)
    run = _run(make_run, project, type="bet", evidence=[
        {"kind": "document", "detail": "the roadmap names distribution first",
         "locator": {"file": "src/auth.ts", "commit": commit}}])
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit, match="selected"):
        runs.append_decision(run, fid, "sent")


def test_a_rejection_needs_a_reason_only_where_the_pack_named_them(project, make_run):
    """A finding's five reasons are the board's own field and precision rests
    on them. The founder did not pick a bet out of a list, and demanding a
    reason would invent a taxonomy the pack never asked for."""
    _ceo(project)
    commit = _commit(project)
    run = _run(make_run, project, type="bet", evidence=[
        {"kind": "document", "detail": "the roadmap names distribution first",
         "locator": {"file": "src/auth.ts", "commit": commit}}])
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]

    assert runs.append_decision(run, fid, "rejected")["polarity"] == "negative"


def test_a_finding_still_cannot_be_rejected_without_one(project, make_run):
    run = make_run()
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit, match="reason"):
        runs.append_decision(run, fid, "rejected")

    ev = runs.append_decision(run, fid, "rejected", reason="by-design")
    assert ev["lifecycle"] == "triage" and ev["polarity"] == "negative"
