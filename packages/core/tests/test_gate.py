"""Brána a dedup.

Brána nekontroluje, jestli je nález chytrý. Kontroluje, jestli MŮŽE být
pravdivý — a nález ukazující na soubor, který na tom commitu neexistuje,
pravdivý být nemůže. Je to nejlevnější obrana proti tomu, aby se zvýšený objem
propsal do zvýšeného odpadu.
"""

from __future__ import annotations

from agency import dedup, ingest, runs
from agency.util import read_json, write_json

from conftest import install_pack, make_finding

RUN_A = "01AAAAAAAAAAAAAAAAAAAAAAAA"
RUN_B = "01BBBBBBBBBBBBBBBBBBBBBBBB"


def test_projde_poctivy_nalez(project, make_run):
    run = make_run()
    vysledek = ingest.ingest(project, run)
    assert vysledek["counts"]["kept"] == 1
    assert vysledek["dropped"] == []


def test_vyradi_nalez_na_neexistujici_soubor(project, make_run):
    """Halucinovaná cesta je nejčastější tvar odpadu a pozná se bez modelu."""
    run = make_run()
    f = make_finding(project, run.id, anchor={"file": "src/neexistuje.ts"})
    write_json(run.findings_path, [f])

    vysledek = ingest.ingest(project, run)

    assert vysledek["counts"]["kept"] == 0
    assert vysledek["dropped"][0]["reason"] == "phantom-file"
    # Nic se neztratilo — vyřazený nález je i s důvodem k přezkoumání.
    assert (run.dir / "gated.json").is_file()
    assert run.record()["gatedBy"] == {"phantom-file": 1}


def test_vyradi_radek_za_koncem_souboru(project, make_run):
    run = make_run()
    write_json(run.findings_path, [make_finding(project, run.id, anchor={"line": 900})])

    vysledek = ingest.ingest(project, run)

    assert vysledek["dropped"][0]["reason"] == "phantom-line"


def test_vyradi_nalez_bez_evidence(project, make_run):
    """Kontrakt to řeší sám — `evidence` má minItems 1. Není to filtr kvality
    textu, je to schéma."""
    run = make_run()
    f = make_finding(project, run.id)
    f["evidence"] = []
    write_json(run.findings_path, [f])

    vysledek = ingest.ingest(project, run)

    assert vysledek["dropped"][0]["reason"] == "schema"


def test_vyradi_pod_prahem_skore(project, make_run):
    run = make_run()
    write_json(run.findings_path, [make_finding(project, run.id, score=40)])

    vysledek = ingest.ingest(project, run)

    assert vysledek["dropped"][0]["reason"] == "below-score"
    assert run.record()["counts"]["belowScore"] == 1


def test_brana_je_idempotentni(project, make_run):
    """Druhé spuštění dá tentýž výsledek — vychází se z findings.raw.json,
    ne z už profiltrovaného souboru."""
    run = make_run()
    prvni = ingest.ingest(project, run)
    druhe = ingest.ingest(project, run)

    assert prvni["counts"] == druhe["counts"]
    assert (run.dir / "findings.raw.json").is_file()


# ------------------------------------------------------------------ dedup

def test_otisk_neni_zavisly_na_cisle_radku(project, make_run):
    """Číslo řádku se posune při každém commitu nad souborem. Kdyby bylo
    v otisku, dedup by nechytil nic."""
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id, anchor={"line": 47, "endLine": 48})

    assert dedup.fingerprint(a) == dedup.fingerprint(b)


def test_otisk_neni_zavisly_na_titulku(project, make_run):
    """Titulek přežije korekci diagnózy, obsah ne — párovat podle titulku je
    chyba, na kterou baseline.md §7.2 doplatil ručně."""
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id, title="Relace se nekontroluje a profil unikne odhlášenému")

    assert dedup.fingerprint(a) == dedup.fingerprint(b)


def test_jiny_nalez_ma_jiny_otisk(project, make_run):
    run = make_run()
    a = make_finding(project, run.id)
    b = make_finding(project, run.id,
                     title="Chybí index nad sloupcem created_at, dotaz projde celou tabulkou",
                     body="Dotaz nad objednávkami skenuje celou tabulku. Scénář: 200 tisíc "
                          "řádků, výpis se načítá osm sekund.")

    assert dedup.fingerprint(a) != dedup.fingerprint(b)


def test_opakovany_beh_oznaci_duplicitu(project, make_run):
    """Druhý běh nad týmž kódem najde totéž. Bez dedupu roste fronta rychleji,
    než se stíhá odbavovat."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, stary)

    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(novy.findings_path, [make_finding(project, novy.id)])
    vysledek = ingest.ingest(project, novy)

    assert len(vysledek["duplicates"]) == 1
    assert vysledek["counts"]["kept"] == 0
    ulozene = read_json(novy.findings_path)
    assert ulozene[0]["state"] == "duplicate"
    assert ulozene[0]["duplicateOf"] == stary.findings()[0]["id"]


def test_preformulovany_nalez_je_taky_duplicita(project, make_run):
    """Jiný model napíše totéž jinými slovy. Otisk to nechytí, podobnost ano."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, stary)

    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(novy.findings_path, [make_finding(
        project, novy.id,
        title="Neplatná relace pořád vrátí uživatele z repository",
        body="Funkce `getUser` nekontroluje relaci a vrátí uživatele. Odhlášený "
             "klient s uloženým id dostane profil zpátky, findUserById se zavolá vždy.")])

    vysledek = ingest.ingest(project, novy)

    assert len(vysledek["duplicates"]) == 1, "přeformulovaná duplicita neprošla"
    assert "similarity" in vysledek["duplicates"][0]["how"]


def test_nalez_v_jine_funkci_neni_duplicita(project, make_run):
    """Dva různé nálezy ve stejném souboru se nesmí slepit — jinak dedup
    zahazuje práci místo šumu."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, stary)

    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(novy.findings_path, [make_finding(
        project, novy.id, anchor={"symbol": {"name": "deleteUser", "range": [10, 20]}})])

    vysledek = ingest.ingest(project, novy)

    assert vysledek["duplicates"] == []
    assert vysledek["counts"]["kept"] == 1


def test_dva_ruzne_nalezy_v_teze_funkci_se_neslepi(project, make_run):
    """Nesymetrické riziko: falešná duplicita ZAHODÍ práci, zmeškaná jen
    prodlouží frontu. Tenhle test hlídá tu dražší stranu."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    ingest.ingest(project, stary)

    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")
    write_json(novy.findings_path, [make_finding(
        project, novy.id,
        title="Chybí index nad sloupcem created_at, dotaz projde celou tabulkou",
        body="Načtení uživatele skenuje celou tabulku objednávek. Scénář: dvě stě "
             "tisíc řádků, výpis se načítá osm sekund a databáze vytíží procesor.")])

    vysledek = ingest.ingest(project, novy)

    assert vysledek["duplicates"] == [], "dva různé nálezy v téže funkci se slepily"
    assert vysledek["counts"]["kept"] == 1


def test_inline_kod_se_pri_porovnani_nezahazuje(project, make_run):
    """`getUser` je nejnosnější slovo nálezu. Kdyby ho čistič markdownu smazal
    s apostrofy, dedup by porovnával jen spojovací text."""
    assert "getuser" in dedup.tokens("Funkce `getUser` vrátí uživatele i bez relace")
    assert "prikaz" not in dedup.tokens("```\nprikaz --ktery-je-jen-citace\n```")


# ------------------------------------------------------------------ dispatch (stopa)

def _sink(project, body: str) -> None:
    (project.root / "sink.py").write_text(body, encoding="utf-8")


SINK_TEMPLATE = "python sink.py --finding {id} --run-dir {runDir}"


def test_bez_sinku_zustane_nalez_candidate(project, make_run):
    """Pack bez `sink` — kanál je git, ne board. Nic se neposílá, stopa mlčí."""
    run = make_run()

    vysledek = ingest.ingest(project, run)

    assert run.findings()[0]["state"] == "candidate"
    assert vysledek["sent"] == 0
    assert runs.read_trail(project) == {}


def test_se_sinkem_nalez_dojde_na_board(project, make_run):
    """Úspěšný sink: `state` se stane `sent`, `sinks.githubProjectItem` nese
    referenci a stopa dostane řádek."""
    install_pack(project, "review-graph", {"sink": SINK_TEMPLATE})
    _sink(project, 'print(\'{"item": "PVTI_X", "url": "https://example.com/PVTI_X"}\')\n')
    run = make_run()
    fid = run.findings()[0]["id"]

    vysledek = ingest.ingest(project, run)

    assert vysledek["sent"] == 1
    saved = run.findings()[0]
    assert saved["state"] == "sent"
    assert saved["sinks"]["githubProjectItem"] == "PVTI_X"
    trail = runs.read_trail(project)
    assert trail[fid]["state"] == "sent"
    assert trail[fid]["ref"] == "PVTI_X"


def test_selhany_sink_necha_nalez_candidate_a_druhy_ingest_to_zkusi_znovu(project, make_run):
    """Nenulový exit = selhání dispatch, ne selhání brány: nález zůstane
    `candidate`, chyba se zapíše do `dispatchErrors` a opakovaný `agency
    ingest` to zkusí znovu — jako by se nic nestalo poprvé."""
    install_pack(project, "review-graph", {"sink": SINK_TEMPLATE})
    _sink(project, "import sys\nprint('boom', file=sys.stderr)\nsys.exit(1)\n")
    run = make_run()
    fid = run.findings()[0]["id"]

    prvni = ingest.ingest(project, run)

    assert run.findings()[0]["state"] == "candidate"
    assert prvni["dispatchErrors"] == [{"id": fid, "error": "boom"}]
    assert runs.read_trail(project) == {}

    _sink(project, 'print(\'{"item": "PVTI_Y"}\')\n')
    druhe = ingest.ingest(project, run)

    assert druhe["sent"] == 1
    assert druhe["dispatchErrors"] == []
    assert run.findings()[0]["state"] == "sent"


def test_prvni_pozice_v_retezu_ceka_druha_dispatchuje_obe(project, make_run):
    """Pozice 1/2: kept nález se stane `held`, nic se neposílá. Pozice 2/2:
    dispatchuje se vlastní nález i `held` nález z upstream běhu, který nikdo
    nerozhodl — řetěz končí, lokálně nic nečeká."""
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
    vysledek = ingest.ingest(project, second)

    assert vysledek["sent"] == 2
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
    install_pack(project, "review-graph", {"minScore": 80, "dimensions": [
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
    install_pack(project, "review-graph", {"minScore": 80, "dimensions": [
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
