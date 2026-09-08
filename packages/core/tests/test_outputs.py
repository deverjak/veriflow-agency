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

import json

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
    return install_pack(project, "ceo", {"outputs": types or {"bet": BET}})


# ------------------------------------------------------------ the default

def test_a_pack_that_declares_nothing_keeps_the_policy_it_had(project):
    """Five of the six packs declare no types and every committed finding was
    written without one. If this ever fails, the migration window is closed
    and it closed by accident."""
    from agency import packs

    pack = packs.load("review-graph", project)
    policy = outputs.policy_for(pack, None)

    assert policy.name == "finding"
    # `max_per_run` is the one thing that is NOT what it was: a pack that
    # names no ceiling gets the backstop, because since Step 8 nothing else
    # bounds a run's output at all.
    assert policy.dedup is True and policy.max_per_run == outputs.RUNAWAY
    assert policy.kinds == ("sent", "rejected")
    assert policy.polarity("sent") == "positive"
    assert policy.polarity("rejected") == "negative"


def test_a_manifest_still_naming_minscore_is_told_it_does_nothing(project, capsys):
    """The quietest way this step could have gone wrong. `minScore: 85` reads
    as a stricter pack, keeps reading as one, and since Step 8 enforces
    nothing — so `agency doctor` says so rather than leaving it to be found by
    measuring."""
    from agency import cli

    install_pack(project, "legal", {"minScore": 85})
    cli.main(["doctor", "--repo", str(project.root), "--json"])
    checks = {c["name"]: c for c in json.loads(capsys.readouterr().out)["checks"]}

    row = checks["pack legal minScore"]
    assert row["ok"] is False and row["fatal"] is False
    assert "outputs.<type>.evidence" in row["detail"]


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


# ------------------------------------------------------------ the metric

def _decided(project, make_run, kind: str, state: str, body: str | None = None):
    """A bet, ingested and then answered.

    `body` is what keeps two of these apart: dedup compares the claim, so two
    bets worded identically are one bet found twice — correctly — and the
    second never reaches a decision at all.
    """
    _ceo(project)
    commit = _commit(project)
    f = make_finding(project, "x", pack="ceo", type=kind, evidence=[
        {"kind": "document", "detail": "the roadmap names distribution first",
         "locator": {"file": "src/auth.ts", "commit": commit}}])
    if body:
        f["body"] = body
    run = make_run(findings=[f], pack="ceo")
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]
    if state:
        runs.append_decision(run, fid, state, by="human")
    return run


def test_the_pack_names_its_own_ratio(project, make_run):
    """`precision` is the wrong word for whether a bet was chosen. The core
    computes the ratio; the word is the pack's."""
    from agency import metrics

    run = _decided(project, make_run, "bet", "selected")
    data = metrics.collect(project, [run])

    cell = data["byLifecycle"]["ceo/bet/selection"]
    assert cell["metric"] == "selection_rate"
    assert cell["value"] == 1.0 and cell["positive"] == 1


def test_the_two_questions_stay_two_numbers(project, make_run):
    """The failure this exists to prevent: (selected + successful) over
    everything, which is neither a selection rate nor a success rate."""
    from agency import metrics

    chosen = _decided(project, make_run, "bet", "selected")
    worked = _decided(project, make_run, "bet", "successful",
                      body="Regional information centres reach instructors we cannot.")
    data = metrics.collect(project, [chosen, worked])

    rows = data["byLifecycle"]
    assert set(rows) == {"ceo/bet/selection", "ceo/bet/outcome"}
    assert rows["ceo/bet/selection"]["metric"] == "selection_rate"
    assert rows["ceo/bet/outcome"]["metric"] == "success_rate"
    assert rows["ceo/bet/selection"]["positive"] == 1
    assert rows["ceo/bet/outcome"]["positive"] == 1


def test_one_bet_answers_both_questions(project, make_run):
    """Acceptance point 3, and the half of it that was open since Step 3: with
    one verdict per output, a bet marked `selected` and later `successful`
    appeared under `outcome` alone. `selection_rate` therefore lost a bet for
    every bet that got as far as an outcome — the two numbers were independent
    only while nobody answered the second one."""
    from agency import metrics

    run = _decided(project, make_run, "bet", "selected")
    runs.append_decision(run, run.findings()[0]["id"], "successful", by="human")

    rows = metrics.collect(project, [run])["byLifecycle"]

    assert rows["ceo/bet/selection"]["positive"] == 1
    assert rows["ceo/bet/selection"]["undecided"] == 0
    assert rows["ceo/bet/outcome"]["positive"] == 1


def test_a_bet_nobody_chose_is_not_pending_an_outcome(project, make_run):
    """`requires` finally does something. It was declared, validated by the
    doctor and read by nothing, so a rejected bet sat in `success_rate`'s
    denominator as undecided — and the ratio fell with every bet the founder
    turned down, which is the opposite of what it measures."""
    from agency import metrics

    run = _decided(project, make_run, "bet", "rejected")

    rows = metrics.collect(project, [run])["byLifecycle"]

    assert rows["ceo/bet/selection"]["negative"] == 1
    assert "ceo/bet/outcome" not in rows


def test_a_chosen_bet_is_pending_its_outcome(project, make_run):
    """The other side of the same rule: for a bet the founder did choose, *did
    it work* is a question now open and unanswered. §5 calls that `unknown` —
    no source of feedback exists for it yet — and this is where that shows up
    as a number instead of as a sentence in a plan."""
    from agency import metrics

    run = _decided(project, make_run, "bet", "selected")

    rows = metrics.collect(project, [run])["byLifecycle"]

    assert rows["ceo/bet/outcome"]["undecided"] == 1
    assert rows["ceo/bet/outcome"]["value"] is None


def test_an_unanswered_output_counts_once(project, make_run):
    """Against the first question that could have been asked. Counting it
    against every lifecycle would read one unanswered bet as two."""
    from agency import metrics

    run = _decided(project, make_run, "bet", "")
    rows = metrics.collect(project, [run])["byLifecycle"]

    assert rows["ceo/bet/selection"]["undecided"] == 1
    assert rows["ceo/bet/selection"]["value"] is None, "nothing decided is not zero"
    assert "ceo/bet/outcome" not in rows


def test_a_finding_gets_no_second_name_for_precision(project, make_run):
    """`finding` is every pack's whether it asked or not, and its number is
    already called precision. A second ratio over the same decisions under a
    second name is not a measurement, it is an argument."""
    from agency import metrics

    run = make_run()
    ingest.ingest(project, run)
    data = metrics.collect(project, [run])

    assert data["byLifecycle"] is None
    assert data["triage"]["precision"] is None and data["triage"]["undecided"] == 1


# ------------------------------------------------- the slice, end to end
#
# One type, walked the whole way: written without an anchor, proved by a page
# the run actually opened and kept, gated, answered by the founder, counted
# under the pack's own word, and handed to the next run as memory.
#
# It exists because the four steps before it were built on an argument rather
# than on a run. If the argument was wrong, it is wrong HERE — in one file,
# after four steps, rather than after ten.

REAL_BET = {
    "cardinality": "many", "limit": 3, "anchor": "none", "dedup": True,
    "evidence": {"required": ["web_snapshot", "document"], "min": 1},
    "actions": "none", "memory": "proposes",
    "feedback": {
        "selection": {"metric": "selection_rate",
                      "kinds": {"selected": "positive", "rejected": "negative"}},
        "outcome": {"metric": "success_rate", "requires": "selection.selected",
                    "kinds": {"successful": "positive", "failed": "negative",
                              "abandoned": "neutral"}},
    },
}


def _bet(project, title: str, body: str, url: str = "https://www.kickk.cz/vyzvy") -> dict:
    """A bet as the CEO pack is now told to write one: no anchor, proved by a
    page rather than by a line of source."""
    f = make_finding(project, "x", pack="ceo", type="bet", dimension="distribution",
                     title=title, body=body)
    del f["anchor"]
    f["evidence"] = [{
        "kind": "web_snapshot",
        "detail": "the call is open until 30 September",
        "locator": {"url": url, "artifact": "evidence/web/01.md"},
    }]
    return f


def _walked(project, make_run, title: str, body: str, url="https://www.kickk.cz/vyzvy"):
    """A run that fetched the page, kept it, and wrote the bet."""
    install_pack(project, "ceo", {"outputs": {"bet": REAL_BET}})
    run = make_run(findings=[_bet(project, title, body, url)], pack="ceo")
    _kept_page(run, url)
    return run


def _kept_page(run, url: str) -> None:
    path = run.dir / "evidence" / "web" / "01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Výzva\nUzávěrka 30. 9. 2026\n", encoding="utf-8")
    with open(run.dir / runs.TOOL_CALLS, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"at": runs.now(), "tool": "WebFetch",
                            "input": {"url": url}}) + "\n")


BET_TITLE = "Distribuce přes regionální instituce, ne přes vyhledávání"
BET_BODY = ("Hypotéza: informační centra dovedou k produktu instruktory, ke kterým "
            "se přes SEO nedostaneme. Do 6 týdnů: tři centra zveřejní odkaz.")


def test_a_bet_needs_no_anchor_and_is_not_thereby_unchecked(project, make_run):
    """The formulation the whole plan turns on. Not *a bet needs no anchor* —
    *a bet needs a different kind of proof*, and the gate still refuses it
    when that proof is not there."""
    run = _walked(project, make_run, BET_TITLE, BET_BODY)

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1, result["dropped"]
    assert "anchor" not in run.findings()[0]


def test_a_bet_citing_a_page_nobody_opened_is_refused(project, make_run):
    """The check that replaces the anchor. Without it, dropping the anchor
    would have left a type nothing could refuse."""
    install_pack(project, "ceo", {"outputs": {"bet": REAL_BET}})
    run = make_run(findings=[_bet(project, BET_TITLE, BET_BODY)], pack="ceo")
    # The artifact is there; the page was never fetched.
    path = run.dir / "evidence" / "web" / "01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Výzva\n", encoding="utf-8")
    with open(run.dir / runs.TOOL_CALLS, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"at": runs.now(), "tool": "WebFetch",
                            "input": {"url": "https://example.com/"}}) + "\n")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "unverified-evidence"


def test_a_finding_from_the_same_pack_still_must_point_at_source(project, make_run):
    """The policy is per type, not per pack. A CEO *finding* is a claim about
    the repository and keeps every check it had."""
    install_pack(project, "ceo", {"outputs": {"bet": REAL_BET}})
    f = make_finding(project, "x", pack="ceo")
    del f["anchor"]
    run = make_run(findings=[f], pack="ceo")

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "missing-anchor"


def test_the_pack_may_not_drop_the_anchor_and_prove_nothing(project, make_run):
    """`agency doctor` refuses the policy that would make a type unfalsifiable
    — the one way this change could have quietly become a hole."""
    from agency import packs

    install_pack(project, "ceo", {"outputs": {"bet": dict(REAL_BET, evidence={})}})
    problems = outputs.errors(packs.load("ceo", project))

    assert any("cannot be refused by anything" in p for p in problems)


def test_the_founders_answer_becomes_the_packs_own_number(project, make_run):
    """Three proposed, one chosen — `selection_rate 0.5` over the two that were
    answered, and `precision` never appears, because a bet is not a finding."""
    from agency import metrics

    chosen = _walked(project, make_run, BET_TITLE, BET_BODY)
    turned_down = _walked(project, make_run, "Newsletter jako druhý kanál",
                          "Hypotéza: newsletter udrží návštěvníky mezi sezónami.")
    ingest.ingest(project, chosen)
    ingest.ingest(project, turned_down)

    runs.record_feedback(project, chosen, chosen.findings()[0]["id"], "selected")
    runs.record_feedback(project, turned_down, turned_down.findings()[0]["id"], "rejected")

    data = metrics.collect(project, [chosen, turned_down])
    cell = data["byLifecycle"]["ceo/bet/selection"]

    assert cell["metric"] == "selection_rate"
    assert cell["value"] == 0.5 and cell["positive"] == 1 and cell["negative"] == 1
    assert data["triage"]["precision"] is None


def test_a_rejected_bet_reaches_the_next_run_as_memory(project, make_run):
    """The last link, and the one that makes the loop worth building: the next
    CEO run is told not to propose it again. Selected by POLARITY — the pack's
    negative word is `rejected` here and could be `not_selected` elsewhere, and
    reading the literal string would have quietly kept this for review packs
    only."""
    from agency import knowledge

    run = _walked(project, make_run, "Newsletter jako druhý kanál",
                  "Hypotéza: newsletter udrží návštěvníky mezi sezónami.")
    ingest.ingest(project, run)
    runs.record_feedback(project, run, run.findings()[0]["id"], "rejected")

    briefing = knowledge.do_not_report(project)

    assert briefing is not None
    assert "Newsletter" in briefing


def test_the_founder_uses_the_types_own_words(project, make_run):
    """`sent` means a board item and a bet has no board; `selected` means a
    finding nothing dispatched. Each type's vocabulary is its own, and the
    error says which words were available."""
    run = _walked(project, make_run, BET_TITLE, BET_BODY)
    ingest.ingest(project, run)
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit, match="selected"):
        runs.append_decision(run, fid, "sent")

    assert runs.record_feedback(project, run, fid, "selected")["polarity"] == "positive"


def test_three_is_the_packs_own_ceiling(project, make_run):
    """“At most three live bets” was a sentence in `references/method.md` that
    nothing enforced. It is now `limit: 3` in the manifest, and the fourth is
    dropped with a reason rather than silently kept."""
    install_pack(project, "ceo", {"outputs": {"bet": REAL_BET}})
    claims = [
        "Informační centra dovedou k produktu instruktory, ke kterým se přes vyhledávání nedostaneme.",
        "Newsletter udrží návštěvníky mezi sezónami a sníží závislost na sezónním provozu.",
        "Mobilní aplikace v obchodě otevře skupinu uživatelů, která web nepoužívá vůbec.",
        "Partnerství s krajskou agenturou přinese data, která nikdo jiný nemá k dispozici.",
    ]
    bets = [_bet(project, f"Sázka číslo {n} na distribuci produktu", claim)
            for n, claim in enumerate(claims, start=1)]
    run = make_run(findings=bets, pack="ceo")
    _kept_page(run, "https://www.kickk.cz/vyzvy")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 3
    assert result["dropped"][0]["reason"] == "over-cardinality"


def test_the_ceiling_keeps_the_best_scored_ones(project, make_run):
    """The one thing `score` decides since Step 8, and it decides an ORDER.

    It never says a bet is false — nothing a model gives itself can say that,
    which is why `below-score` left the gate. It says *this one before that
    one*, and that only matters when a run wrote more than anybody will read.
    """
    install_pack(project, "ceo", {"outputs": {"bet": REAL_BET}})
    claims = [
        ("Informační centra dovedou k produktu instruktory, ke kterým se přes vyhledávání nedostaneme.", 60),
        ("Newsletter udrží návštěvníky mezi sezónami a sníží závislost na sezónním provozu.", 30),
        ("Mobilní aplikace v obchodě otevře skupinu uživatelů, která web nepoužívá vůbec.", 95),
        ("Partnerství s krajskou agenturou přinese data, která nikdo jiný nemá k dispozici.", 80),
    ]
    bets = []
    for n, (claim, score) in enumerate(claims, start=1):
        f = _bet(project, f"Sázka číslo {n} na distribuci produktu", claim)
        f["score"] = score
        bets.append(f)
    run = make_run(findings=bets, pack="ceo")
    _kept_page(run, "https://www.kickk.cz/vyzvy")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 3
    assert [f["score"] for f in run.findings()] == [60, 95, 80], \
        "what survives is the best three; the order they were written in is kept"
    assert result["dropped"][0]["title"].startswith("Sázka číslo 2")


def test_the_real_ceo_manifest_says_all_of_this(project):
    """The pack in `packs/ceo/` is a reference copy of one that lives in
    another repository, so nothing else in this suite would notice if the two
    halves of this step disagreed."""
    import json as _json
    from pathlib import Path

    from agency import packs

    manifest = _json.loads(
        (Path(__file__).resolve().parents[3] / "packs" / "ceo" / "pack.json")
        .read_text(encoding="utf-8"))
    install_pack(project, "ceo", manifest)
    pack = packs.load("ceo", project)

    assert outputs.errors(pack) == []
    policy = outputs.policy_for(pack, "bet")
    assert policy.anchor == "none" and policy.max_per_run == 3
    assert policy.required_evidence == ["web_snapshot", "document"]
    assert policy.lifecycle_of("selected").metric == "selection_rate"
    assert policy.lifecycle_of("failed").requires == "selection.selected"


def test_two_anchorless_outputs_do_not_share_one_place(project, make_run):
    """Found by the slice rather than by argument, which is what it is for.

    `subject_key` (then `symbol_key`) fell back to `file:?`, so every output
    without an anchor
    shared one place — and the guard that says "two claims in different places
    are two claims" became its opposite: everything was in the same place, so
    everything was comparable, and four differently-worded bets collapsed into
    one. With no place, only an identical claim counts, and that still does.
    """
    from agency import dedup

    a = _bet(project, "Distribuce přes regionální instituce v kraji",
             "Informační centra dovedou k produktu instruktory, které vyhledávání mine.")
    b = _bet(project, "Newsletter jako druhý kanál pro návštěvníky",
             "Newsletter udrží návštěvníky produktu mezi jednotlivými sezónami.")
    same = dict(b, body=a["body"])
    for f in (a, b, same):
        f["fingerprint"] = dedup.fingerprint(f)

    assert dedup.subject_key(a) == "", "no anchor and no subject is no place, not a shared one"
    assert dedup.is_duplicate(b, a) == (False, "")
    assert dedup.is_duplicate(same, a) == (True, "fingerprint"), \
        "the same claim word for word is still the same claim"

# ------------------------------------------------------- subject, as a place
#
# The vertical slice found that an output with no anchor had no place at all,
# so only an identical claim counted as a duplicate. `subject` is what gives
# it one back — and it is the same pair the run's scope is written in, so the
# thing that decides "we already argued about this" and the thing that decides
# "here is what was decided about it" are one vocabulary rather than two.

_HERE = ("Informační centra dovedou k produktu instruktory, které vyhledávání mine. "
         "Do 6 týdnů uvidíme tři centra, která odkaz zveřejní.")
_SAME_AGAIN = ("Instruktory k produktu dovedou informační centra, ne vyhledávání. "
               "Do šesti týdnů uvidíme aspoň tři centra, která zveřejní odkaz.")


def _on(project, ref: str, title: str, body: str) -> dict:
    bet = _bet(project, title, body)
    bet["subject"] = {"kind": "bet", "ref": ref}
    return bet


def test_a_subject_gives_an_anchorless_output_its_place_back(project):
    """The other half of the slice's finding. Two runs arguing the same bet in
    different words are one bet argued twice, and until `subject` existed the
    similarity layer had nothing to hold them against — a reworded bet was a
    new bet, every run, forever."""
    from agency import dedup

    first = _on(project, "regional-distribution", "Distribuce přes instituce kraje", _HERE)
    again = _on(project, "regional-distribution", "Instituce jako kanál distribuce",
                _SAME_AGAIN)

    duplicate, how = dedup.is_duplicate(again, first)
    assert duplicate and how.startswith("similarity")


def test_two_bets_about_two_different_bets_stay_two(project):
    """The guard the place exists for. Two claims in different places are two
    claims, and a bet's place is which bet it is about."""
    from agency import dedup

    first = _on(project, "regional-distribution", "Distribuce přes instituce kraje", _HERE)
    other = _on(project, "newsletter-retention", "Newsletter jako retenční kanál",
                _SAME_AGAIN)

    assert dedup.is_duplicate(other, first) == (False, "")


def test_an_anchored_output_keeps_the_place_it_always_had(project):
    """Every committed finding carries a fingerprint computed from `sym:` or
    `file:`, and dedup against history compares the stored one against a fresh
    one. Generalising those two shapes into `symbol:` and `file:` in the same
    sweep would have silently stopped the second run over a commit from
    recognising the first."""
    from agency import dedup

    f = make_finding(project, "x")
    assert dedup.subject_key(f) == "sym:getUser"

    f["anchor"]["symbol"] = None
    assert dedup.subject_key(f) == "file:src/auth.ts"


def test_what_the_pack_says_wins_over_what_the_anchor_implies(project):
    """The anchor is where the claim was found; `subject` is what the claim is
    about, and only the pack knows when those differ. Nothing committed
    carries one, so no fingerprint in history moves."""
    from agency import dedup

    f = make_finding(project, "x", subject={"kind": "board_item", "ref": "255"})
    assert dedup.subject_key(f) == "board_item:255"


def test_the_real_ceo_scope_script_reads_the_register_it_documents(project):
    """`packs/ceo/` is a reference copy of a pack living in another
    repository, and its scope command is a file next to its manifest. Nothing
    else in this suite would notice if `references/method.md` prescribed a
    `Ref:` line the script did not read — and the failure would be an empty
    memory, not an error."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    page = project.agency_dir / "knowledge" / "pages" / "ceo" / "strategy.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "Last reviewed: 2026-09-07\n\n# Strategie\n\n"
        "Kvesteros je regionální discovery vrstva.\n\n"
        "### Bet 1 — Distribuce přes regionální instituce\n"
        "Ref: regional-distribution\n"
        "Status: confirmed (decisions.md, 2026-09-04)\n\n"
        "### Bet 2 — Newsletter jako retenční kanál\n"
        "Ref: newsletter-retention\n"
        "Status: killed (2026-08-20, nikdo se nepřihlásil)\n",
        encoding="utf-8")

    result = subprocess.run(
        [_sys.executable, str(root / "packs" / "ceo" / "scripts" / "scope.py")],
        cwd=project.root, capture_output=True, text=True, encoding="utf-8")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{"kind": "bet", "ref": "regional-distribution"}], \
        "the live bets, and a killed one is not one"


def test_the_ceo_manifest_and_its_scope_script_are_the_same_pack(project):
    """A manifest naming a script that is not there produces a run with no
    narrowed memory and no error anywhere — the failure mode this step is
    least able to notice."""
    import json as _json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    manifest = _json.loads((root / "packs" / "ceo" / "pack.json").read_text(encoding="utf-8"))
    command = manifest["scope"]

    assert command.endswith("scripts/scope.py")
    assert (root / "packs" / "ceo" / "scripts" / "scope.py").is_file()
    assert command.split()[-1].startswith(".claude/skills/agency-ceo/"), \
        "the path a run sees is the one inside the project, not this repository"
