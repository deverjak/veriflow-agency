"""The gate and dedup.

The gate does not check whether a finding is clever. It checks whether it CAN
be true — and a finding pointing at a file that does not exist at that commit
cannot be. It is the cheapest defence against raised volume turning straight
into raised waste.
"""

from __future__ import annotations

import json

from agency import dedup, ingest, runs
from agency.util import read_json, write_json

from conftest import as_code_evidence, git, install_pack, make_finding

RUN_A = "01AAAAAAAAAAAAAAAAAAAAAAAA"
RUN_B = "01BBBBBBBBBBBBBBBBBBBBBBBB"


def test_an_honest_finding_gets_through(project, make_run):
    run = make_run()
    result = ingest.ingest(project, run)
    assert result["counts"]["kept"] == 1
    assert result["dropped"] == []


def test_a_finding_on_a_file_that_does_not_exist_is_dropped(project, make_run):
    """A hallucinated path is the most common shape of waste, and it is
    recognisable without a model."""
    run = make_run()
    f = make_finding(project, run.id, anchor={"file": "src/neexistuje.ts"})
    write_json(run.findings_path, [f])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "phantom-file"
    # Nothing was lost — a dropped finding is kept with its reason, for review.
    assert (run.dir / "gated.json").is_file()
    assert run.record()["gatedBy"] == {"phantom-file": 1}


def test_a_line_past_the_end_of_the_file_is_dropped(project, make_run):
    run = make_run()
    write_json(run.findings_path, [make_finding(project, run.id, anchor={"line": 900})])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "phantom-line"


def test_a_finding_with_no_evidence_is_dropped(project, make_run):
    """The contract handles this itself — `evidence` has minItems 1. It is not
    a filter on the quality of the text, it is the schema."""
    run = make_run()
    f = make_finding(project, run.id)
    f["evidence"] = []
    write_json(run.findings_path, [f])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "schema"


def test_a_low_score_no_longer_keeps_a_finding_out(project, make_run):
    """The gate asks whether a claim CAN be true, and a score is not an answer
    to that — it is a number the model gave itself. A well-evidenced finding
    scored 40 is a finding its author was honest about, and dropping it taught
    every pack that the way through is to score higher."""
    run = make_run()
    write_json(run.findings_path, [make_finding(project, run.id, score=40)])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1
    assert result["dropped"] == []
    # Still recorded, because calibration is what it was always good for:
    # a pack that scores everything 90 and has precision 0.4 shows up nowhere
    # else.
    assert run.findings()[0]["score"] == 40


def test_a_pack_that_names_no_ceiling_still_has_one(project, make_run):
    """What replaced `minScore` as the one thing bounding a run's output.

    Six of the seven packs declare no `outputs` block at all, so a ceiling
    that only existed when a pack asked for one would have left them with a
    queue nothing limits — and a queue nobody can work through stops producing
    the feedback every number in `agency metrics` is computed from.

    The backstop is deliberately far above a real run: `baseline.md` measured
    three new findings from a four-persona run, and 51 across the whole period.
    It catches a pack having a bad day, not a pack doing its job.
    """
    from agency import outputs

    over = outputs.RUNAWAY + 1
    # Each in its own function, or they would be duplicates of one another —
    # the claim is the same claim, and dedup is right about that.
    run = make_run(findings=[
        make_finding(project, "x", title=f"Finding number {n} in a very long run",
                     anchor={"symbol": {"name": f"handler{n}", "range": [1, 4]}})
        for n in range(over)
    ])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == outputs.RUNAWAY
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["reason"] == "over-cardinality"
    # Equal scores, so the ceiling falls where the pack stopped writing.
    assert result["dropped"][0]["title"].startswith(f"Finding number {over - 1}")
    assert run.record()["gatedBy"] == {"over-cardinality": 1}


def test_the_gate_is_idempotent(project, make_run):
    """A second run gives the same result — it starts from findings.raw.json,
    not from the already filtered file."""
    run = make_run()
    first = ingest.ingest(project, run)
    second = ingest.ingest(project, run)

    assert first["counts"] == second["counts"]
    assert (run.dir / "findings.raw.json").is_file()


# ------------------------------------------------------------------ dedup

def test_the_fingerprint_does_not_depend_on_the_line_number(project, make_run):
    """The line number shifts on every commit over the file. Were it in the
    fingerprint, dedup would catch nothing."""
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id, anchor={"line": 47, "endLine": 48})

    assert dedup.fingerprint(a) == dedup.fingerprint(b)


def test_the_fingerprint_does_not_depend_on_the_title(project, make_run):
    """A title survives a corrected diagnosis, the content does not — matching
    by title is the mistake baseline.md §7.2 paid for by hand."""
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id, title="Relace se nekontroluje a profil unikne odhlášenému")

    assert dedup.fingerprint(a) == dedup.fingerprint(b)


def test_a_different_finding_has_a_different_fingerprint(project, make_run):
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id,
                     title="Chybí index nad sloupcem created_at, dotaz projde celou tabulkou",
                     body="Dotaz nad objednávkami skenuje celou tabulku. Scénář: 200 tisíc "
                          "řádků, výpis se načítá osm sekund.")

    assert dedup.fingerprint(a) != dedup.fingerprint(b)


def test_a_repeated_run_marks_the_duplicate(project, make_run):
    """A second run over the same code finds the same things. Without dedup the
    queue grows faster than it can be worked through."""
    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, older)

    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(newer.findings_path, [make_finding(project, newer.id)])
    result = ingest.ingest(project, newer)

    assert len(result["duplicates"]) == 1
    assert result["counts"]["kept"] == 0
    saved = read_json(newer.findings_path)
    assert saved[0]["state"] == "duplicate"
    assert saved[0]["duplicateOf"] == older.findings()[0]["id"]


def test_a_reworded_finding_is_a_duplicate_too(project, make_run):
    """Another model writes the same thing in other words. The fingerprint does
    not catch it, similarity does."""
    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, older)

    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(newer.findings_path, [make_finding(
        project, newer.id,
        title="Neplatná relace pořád vrátí uživatele z repository",
        body="Funkce `getUser` nekontroluje relaci a vrátí uživatele. Odhlášený "
             "klient s uloženým id dostane profil zpátky, findUserById se zavolá vždy.")])

    result = ingest.ingest(project, newer)

    assert len(result["duplicates"]) == 1, "the reworded duplicate did not register"
    assert "similarity" in result["duplicates"][0]["how"]


def test_a_finding_in_another_function_is_not_a_duplicate(project, make_run):
    """Two different findings in the same file must not be merged — otherwise
    dedup throws work away instead of noise."""
    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, older)

    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(newer.findings_path, [make_finding(
        project, newer.id, anchor={"symbol": {"name": "deleteUser", "range": [10, 20]}})])

    result = ingest.ingest(project, newer)

    assert result["duplicates"] == []
    assert result["counts"]["kept"] == 1


def test_two_different_findings_in_the_same_function_do_not_merge(project, make_run):
    """The risk is asymmetric: a false duplicate THROWS work away, a missed one
    only lengthens the queue. This test guards the expensive side."""
    older = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, older)

    newer = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(newer.findings_path, [make_finding(
        project, newer.id,
        title="Chybí index nad sloupcem created_at, dotaz projde celou tabulkou",
        body="Načtení uživatele skenuje celou tabulku objednávek. Scénář: dvě stě "
             "tisíc řádků, výpis se načítá osm sekund a databáze vytíží procesor.")])

    result = ingest.ingest(project, newer)

    assert result["duplicates"] == [], "two different findings in one function were merged"
    assert result["counts"]["kept"] == 1


def test_inline_code_is_not_thrown_away_when_comparing(project, make_run):
    """`getUser` is the most load-bearing word of the finding. Were the markdown
    cleaner to delete it along with the backticks, dedup would be comparing
    connective text only."""
    assert "getuser" in dedup.tokens("Funkce `getUser` vrátí uživatele i bez relace")
    assert "prikaz" not in dedup.tokens("```\nprikaz --ktery-je-jen-citace\n```")


# ------------------------------------------------------------ dispatch (trail)

def _sink(project, body: str) -> None:
    (project.root / "sink.py").write_text(body, encoding="utf-8")


SINK_TEMPLATE = "python sink.py --finding {id} --run-dir {runDir}"


def test_with_no_sink_a_finding_stays_candidate(project, make_run):
    """A pack with no `sink` — the channel is git, not a board. Nothing is
    dispatched and the trail stays silent."""
    run = make_run()

    result = ingest.ingest(project, run)

    assert run.findings()[0]["state"] == "candidate"
    assert result["sent"] == 0
    assert runs.read_trail(project) == {}


def test_with_a_sink_a_finding_reaches_the_board(project, make_run):
    """A successful sink: `state` becomes `sent`, the action carries what really
    happened, and the trail gets a row."""
    install_pack(project, "review-graph", {"sink": SINK_TEMPLATE})
    _sink(project, 'print(\'{"item": "PVTI_X", "url": "https://example.com/PVTI_X"}\')\n')
    run = make_run()
    fid = run.findings()[0]["id"]

    result = ingest.ingest(project, run)

    assert result["sent"] == 1
    saved = run.findings()[0]
    assert saved["state"] == "sent"
    assert runs.acted_ref(saved) == "PVTI_X"
    action = saved["actions"][0]
    assert action["result"] == "success" and action["url"].endswith("PVTI_X")
    trail = runs.read_trail(project)
    assert trail[fid]["state"] == "sent"
    assert trail[fid]["ref"] == "PVTI_X"


def test_a_failed_sink_leaves_the_finding_candidate_and_a_second_ingest_retries(project, make_run):
    """A non-zero exit is a dispatch failure, not a gate failure: the finding
    stays `candidate`, the error is written to `dispatchErrors`, and a repeated
    `agency ingest` tries again — as if nothing had happened the first time."""
    install_pack(project, "review-graph", {"sink": SINK_TEMPLATE})
    _sink(project, "import sys\nprint('boom', file=sys.stderr)\nsys.exit(1)\n")
    run = make_run()
    fid = run.findings()[0]["id"]

    first = ingest.ingest(project, run)

    assert run.findings()[0]["state"] == "candidate"
    assert first["dispatchErrors"] == [{"id": fid, "error": "boom"}]
    assert runs.read_trail(project) == {}
    # An attempt that failed is still an attempt — without it, "the board turned
    # this down three times" lives only in three separate run records.
    assert [a["result"] for a in run.findings()[0]["actions"]] == ["error"]

    _sink(project, 'print(\'{"item": "PVTI_Y"}\')\n')
    second = ingest.ingest(project, run)

    assert second["sent"] == 1
    assert second["dispatchErrors"] == []
    saved = run.findings()[0]
    assert saved["state"] == "sent"
    # Both are appended, not overwritten: a sink that failed on Tuesday and
    # passed on Thursday is two events, and only the second is a worse answer to
    # the question of how often that board answers at all.
    assert [a["result"] for a in saved["actions"]] == ["error", "success"]
    assert runs.acted_ref(saved) == "PVTI_Y", "the last success is read, not the first attempt"


def test_the_first_position_in_a_chain_waits_and_the_second_dispatches_both(project, make_run):
    """Position 1/2: a kept finding becomes `held` and nothing is dispatched.
    Position 2/2: both its own finding and the `held` one from the upstream run
    that nobody judged are dispatched — the chain ends, nothing waits locally."""
    install_pack(project, "review-graph", {"sink": SINK_TEMPLATE})
    _sink(project, 'print(\'{"item": "PVTI_CHAIN"}\')\n')
    chain_id = "01CHAINCHAINCHAINCHAINCHAI"

    first = make_run(run_id=RUN_A,
                     chain={"id": chain_id, "position": 1, "of": 2, "upstream": []})
    ingest.ingest(project, first)
    assert runs.find_run(project, RUN_A).findings()[0]["state"] == "held"
    assert runs.decisions(runs.find_run(project, RUN_A)) == {}

    second = make_run(
        [make_finding(project, RUN_B, title="Nález z druhého kroku",
                      body="Endpoint pro export dat nekontroluje oprávnění volajícího. "
                           "Scénář: běžný uživatel zavolá cizí export a dostane cizí data.")],
        run_id=RUN_B,
        chain={"id": chain_id, "position": 2, "of": 2, "upstream": [RUN_A]})
    result = ingest.ingest(project, second)

    assert result["sent"] == 2
    assert runs.find_run(project, RUN_B).findings()[0]["state"] == "sent"

    upstream_run = runs.find_run(project, RUN_A)
    upstream_finding = upstream_run.findings()[0]
    assert upstream_finding["state"] == "sent"
    decided = runs.decisions(upstream_run)
    assert decided[upstream_finding["id"]]["by"] == "chain"


# ------------------------------------------------------------------- blocked

BLOCKED_MD = """\
# Blocked

**What I could not do:** verify the cancellation flow on staging.
**Why:** https://staging.example.com returned 502 on every attempt.
**What would unblock me:** a staging URL that answers.
**What I did instead:** nothing — the other dimensions depend on this one.
"""


def test_a_wall_is_not_the_same_as_finding_nothing(project, make_run):
    """`no-findings` used to mean three different things at once, and one of
    them was "I hit a wall". Silence was indistinguishable from success, and
    while that held, nothing could honestly be run unattended."""
    run = make_run(findings=[])
    (run.dir / "blocked.md").write_text(BLOCKED_MD, encoding="utf-8")

    result = ingest.ingest(project, run)

    rec = run.record()
    assert rec["status"] == "blocked"
    assert rec["outputs"]["blocked"] is True
    # The sentence a person reads first, lifted out of the file into the record.
    assert rec["exitReason"] == "verify the cancellation flow on staging."
    assert result["blocked"] is True


def test_a_blocked_run_keeps_the_findings_it_managed(project, make_run):
    """Partial work is still work. Throwing it away would make the honest
    report — saying you were blocked — the expensive one to write."""
    rid = "01CCCCCCCCCCCCCCCCCCCCCCCC"
    run = make_run(run_id=rid, findings=[
        make_finding(project, rid),
        make_finding(project, rid, dimension="reuse",
                     title="Nothing imports the retry helper any more",
                     body="No caller reaches `retryOnce`; the last one went "
                          "away with the queue rewrite.",
                     anchor={"line": 3, "symbol": {"name": "retryOnce",
                                                   "range": [1, 4]}}),
    ])
    (run.dir / "blocked.md").write_text(BLOCKED_MD, encoding="utf-8")

    result = ingest.ingest(project, run)

    assert run.record()["status"] == "blocked"
    assert result["counts"]["kept"] == 2


def test_blocked_with_nothing_written_is_still_a_result(project, make_run):
    """The ordinary shape of being blocked: no findings.json at all. Without
    this branch the gate returned `noOutput` and the caller recorded `failed`,
    which reads as "the tool broke" rather than "staging is down"."""
    run = make_run()
    run.findings_path.unlink()
    (run.dir / "blocked.md").write_text(BLOCKED_MD, encoding="utf-8")

    result = ingest.ingest(project, run)

    assert not result.get("noOutput")
    assert run.record()["status"] == "blocked"
    # And the gate still did not invent an empty findings.json for it.
    assert not run.findings_path.is_file()


def test_no_findings_still_means_no_findings(project, make_run):
    """The other half of the contract: a pack that looked and found nothing
    must not start reading as blocked."""
    run = make_run(findings=[])

    ingest.ingest(project, run)

    assert run.record()["status"] == "no-findings"
    assert run.record()["outputs"]["blocked"] is False


# ------------------------------------------------------- evidence per dimension

def test_a_dimension_that_stands_on_the_graph_refuses_a_quotation(project, make_run):
    """The schema weighs shape, not strength: `finding.v1` wants one piece of
    evidence out of six equal kinds. So `reuse` — which stands entirely on the
    call graph — used to pass on a sentence from the README."""
    install_pack(project, "review-graph", {"dimensions": [
        {"id": "reuse", "title": "Code nothing points at", "evidence": ["graph"]}]})
    f = make_finding(project, "x", dimension="reuse")
    f["evidence"] = [{"kind": "doc", "detail": "the README says it is unused",
                      "source": "README.md"}]
    run = make_run(findings=[f])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "weak-evidence"
    assert "graph" in result["dropped"][0]["detail"]


def test_the_same_dimension_passes_on_the_proof_it_asked_for(project, make_run):
    install_pack(project, "review-graph", {"dimensions": [
        {"id": "reuse", "title": "Code nothing points at", "evidence": ["graph"]}]})
    f = make_finding(project, "x", dimension="reuse")
    f["evidence"] = [{"kind": "graph", "detail": "no caller in the graph",
                      "source": "code-review-graph impact"}]
    run = make_run(findings=[f])

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def test_a_dimension_that_says_nothing_takes_anything(project, make_run):
    """Backwards compatibility for free — and the pack decides, not the core:
    only the pack knows which of its questions have one honest kind of answer."""
    f = make_finding(project, "x")
    f["evidence"] = [{"kind": "doc", "detail": "the README says so",
                      "source": "README.md"}]
    run = make_run(findings=[f])

    assert ingest.ingest(project, run)["counts"]["kept"] == 1

def test_a_finding_without_a_score_fails_the_contract(project, make_run):
    """`score` was optional, so the project's threshold could be walked around
    by saying nothing. The gate drops it as `schema` rather than as a new
    reason — the schema is the right place, and a second reason for the same
    thing splits the counts."""
    f = make_finding(project, "x")
    del f["score"]
    run = make_run(findings=[f])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "schema"
    assert "score" in result["dropped"][0]["detail"]


# ------------------------------------------------- evidence with a locator
#
# `source` is free text: a finding could cite `agency graph impact` or a URL it
# never opened and nothing could tell. A locator is the same claim in a shape a
# machine can open — and everything below is answered from the repository at a
# commit or from what the run itself kept, never from the network. A gate that
# phoned out would give the same run two answers on two days, and `replay`
# would stop being a regression test.


def _fetched(run, *urls: str) -> None:
    """The rows the PostToolUse hook would have left after fetching pages."""
    with open(run.dir / runs.TOOL_CALLS, "a", encoding="utf-8", newline="\n") as f:
        for url in urls:
            f.write(json.dumps({"at": runs.now(), "tool": "WebFetch",
                                "input": {"url": url}}) + "\n")


def _kept(run, artifact: str, text: str = "{}") -> None:
    """What the run kept about what it read."""
    path = run.dir / artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _evidence(project, item: dict) -> dict:
    f = make_finding(project, "x")
    f["evidence"] = [item]
    return f


def test_code_evidence_is_verified_at_the_commit(project, make_run):
    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[_evidence(project, {
        "kind": "code", "detail": "no caller checks the session",
        "locator": {"file": "src/auth.ts", "line": 2, "commit": commit}})])

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def test_code_evidence_pointing_at_a_file_that_is_not_there_is_dropped(project, make_run):
    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[_evidence(project, {
        "kind": "code", "detail": "no caller checks the session",
        "locator": {"file": "src/nowhere.ts", "line": 2, "commit": commit}})])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    # `phantom-file`, not `unverified-evidence`, since Step 9: a code locator
    # IS where an output points at source, and an invented file gets the name
    # the invented-file counter has always had. Were it counted as a broken
    # locator instead, a pack moving to the new shape would have watched its
    # hallucinations drain out of `phantom-file` and read like a better pack.
    assert result["dropped"][0]["reason"] == "phantom-file"
    assert "src/nowhere.ts" in result["dropped"][0]["detail"]


def test_code_evidence_past_the_end_of_the_file_is_dropped(project, make_run):
    """The two questions the anchor is asked, asked of the proof as well —
    and answered under the anchor's own two names."""
    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[_evidence(project, {
        "kind": "code", "detail": "no caller checks the session",
        "locator": {"file": "src/auth.ts", "line": 900, "commit": commit}})])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "phantom-line"
    assert "900" in result["dropped"][0]["detail"]


# --------------------------------------------- the anchor as `code` evidence

def test_a_finding_that_points_at_source_with_evidence_gets_through(project, make_run):
    """The migration in one line: the same finding, said the other way.

    Nothing about the claim changed — only which field carries the four
    layers — so the gate has to reach the same verdict. If it did not, every
    pack in every other repository would have had to migrate in the same
    commit as the core."""
    run = make_run(findings=[as_code_evidence(make_finding(project, "x"))])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1
    assert result["dropped"] == []


def test_a_type_that_must_point_at_source_is_not_satisfied_by_other_proof(project, make_run):
    """`anchor: required` asks for a place in the code, and only `code`
    evidence is one. A finding that proves itself with a graph fact and names
    no file is the shape the policy exists to refuse — the formulation being
    "a bet needs a different kind of proof", never "a bet needs no proof"."""
    f = make_finding(project, "x")
    f.pop("anchor")
    run = make_run(findings=[f])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "missing-anchor"


def test_every_place_a_finding_cites_is_checked_not_only_the_first(project, make_run):
    """A finding may cite three pieces of code and invent the third. Checking
    only the place it SITS would leave the other two unread, which is the
    whole difference between `anchor.of()` and `anchor.places()`."""
    commit = git(project.root, "rev-parse", "HEAD")
    f = as_code_evidence(make_finding(project, "x"))
    f["evidence"].append({"kind": "code", "detail": "and its caller does not either",
                          "locator": {"file": "src/invented.ts", "line": 3,
                                      "commit": commit}})
    run = make_run(findings=[f])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "phantom-file"
    assert "src/invented.ts" in result["dropped"][0]["detail"]


def test_a_pack_that_migrates_does_not_report_its_backlog_again(project, make_run):
    """The expensive way to get this step wrong.

    A pack that moves its anchor into `code` evidence goes on finding the same
    things in the same code. Dedup keys an output on its PLACE, and the place
    comes out of the symbol — so a locator that lost the symbol would make the
    first run after the migration report everything the project had already
    seen, with nothing failing to say so."""
    older = make_run(run_id=RUN_A)
    ingest.ingest(project, older)

    newer = make_run(run_id=RUN_B)
    write_json(newer.findings_path, [as_code_evidence(make_finding(project, RUN_B))])

    result = ingest.ingest(project, newer)

    assert len(result["duplicates"]) == 1, "the migrated finding was reported a second time"
    assert dedup.subject_key(read_json(newer.findings_path)[0]) == "sym:getUser"


def test_a_cited_command_reads_the_same_in_both_shapes(project, make_run):
    """`locator.command` and a `source` that looks like a command are the same
    claim, so they must get the same verdict and the same reason — otherwise a
    pack is punished for using the newer shape."""
    run = make_run(findings=[_evidence(project, {
        "kind": "command", "detail": "the graph has no such caller",
        "locator": {"command": "agency graph impact --depth 2"}})])
    with open(run.dir / runs.TOOL_CALLS, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"at": runs.now(), "tool": "Bash",
                            "input": {"command": "git diff --stat"}}) + "\n")

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "unproven-source"


def test_a_page_kept_and_opened_in_this_run_passes(project, make_run):
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "evidence/web/01.json"}})])
    _kept(run, "evidence/web/01.json")
    _fetched(run, "https://kickk.cz/vyzvy")

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def test_a_page_nobody_opened_is_dropped(project, make_run):
    """The lie this exists to catch: a claim about the world with a URL that
    reads as proof and was never fetched."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "evidence/web/01.json"}})])
    _kept(run, "evidence/web/01.json")
    _fetched(run, "https://example.com/something-else")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "unverified-evidence"
    assert "was not opened" in result["dropped"][0]["detail"]


def test_a_page_opened_but_not_kept_is_dropped(project, make_run):
    """Fetching is not keeping. Without the artifact the claim cannot be
    re-read later, and a run that cannot show what it read has not proved
    it."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "evidence/web/01.json"}})])
    _fetched(run, "https://kickk.cz/vyzvy")

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "unverified-evidence"
    assert "is not in this run" in result["dropped"][0]["detail"]


def test_the_same_page_written_two_ways_is_the_same_page(project, make_run):
    """The hook writes the URL and the agent writes the citation — two hands,
    so a trailing slash, a capital host or a fragment must not be a verdict."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy#program",
                    "artifact": "evidence/web/01.json"}})])
    _kept(run, "evidence/web/01.json")
    _fetched(run, "https://KICKK.cz/vyzvy/")

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def test_a_run_nobody_recorded_keeps_the_half_it_can_still_check(project, make_run):
    """No `tool-calls.jsonl` means the hook never ran (attended, codex) and no
    finding may be dropped for that. The artifact is in the run either way, so
    that half is still answered — the fetched half is skipped, not failed."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "evidence/web/01.json"}})])
    _kept(run, "evidence/web/01.json")

    assert ingest.ingest(project, run)["counts"]["kept"] == 1
    assert not (run.dir / runs.TOOL_CALLS).exists()


def test_an_artifact_outside_the_run_is_not_the_runs_to_vouch_for(project, make_run):
    """A path that leaves RUN_DIR is not a typo — it is a run vouching for
    something it does not own. Two layers, and this is the second: the pattern
    stops `/etc/passwd`, but `evidence/../../x` satisfies it and only resolving
    the path catches it."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "evidence/../../../secrets.json"}})])
    _fetched(run, "https://kickk.cz/vyzvy")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "unverified-evidence"


def test_an_absolute_artifact_never_gets_that_far(project, make_run):
    """The first layer. The schema has no reason to accept a path that was
    never going to be inside the run."""
    run = make_run(findings=[_evidence(project, {
        "kind": "web_snapshot", "detail": "the call closes on 30 September",
        "locator": {"url": "https://kickk.cz/vyzvy",
                    "artifact": "/etc/passwd"}})])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "schema"


def test_a_locator_the_kind_does_not_carry_fails_the_contract(project, make_run):
    """`code` without a file at a commit is not evidence in the newer shape —
    it is the older shape wearing its name, and the schema is where that is
    said."""
    run = make_run(findings=[_evidence(project, {
        "kind": "code", "detail": "no caller checks the session"})])

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "schema"
    assert "locator" in result["dropped"][0]["detail"]


def test_a_board_item_must_be_in_the_snapshot_the_run_took(project, make_run):
    run = make_run(findings=[_evidence(project, {
        "kind": "board_item", "detail": "nothing on the board covers this",
        "locator": {"ref": "255", "artifact": "evidence/backlog.json"}})])
    _kept(run, "evidence/backlog.json", '[{"number": 255, "title": "Platby"}]')

    assert ingest.ingest(project, run)["counts"]["kept"] == 1


def test_a_board_item_that_is_not_in_the_snapshot_is_dropped(project, make_run):
    run = make_run(findings=[_evidence(project, {
        "kind": "board_item", "detail": "nothing on the board covers this",
        "locator": {"ref": "479", "artifact": "evidence/backlog.json"}})])
    _kept(run, "evidence/backlog.json", '[{"number": 255, "title": "Platby"}]')

    result = ingest.ingest(project, run)

    assert result["dropped"][0]["reason"] == "unverified-evidence"
    assert "479" in result["dropped"][0]["detail"]


def test_evidence_without_a_locator_keeps_passing(project, make_run):
    """The migration window. Every pack writes the older shape until it is
    rewritten, and committed run history is full of it — a change that
    invalidated it would invalidate every past run's provenance with it."""
    run = make_run(findings=[_evidence(project, {
        "kind": "graph", "detail": "getUser has no caller that checks",
        "source": "code-review-graph impact"})])

    assert ingest.ingest(project, run)["counts"]["kept"] == 1
