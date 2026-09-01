"""Ledger nálezů: paměť, kterou přečte i ten, kdo Agency nemá.

`docs/plans/tasks.md` Fáze 5. Tady se zaplatí atribuce z Fáze 1 — z toho, kdo
nález našel, kdo ho potvrdil a kdo o něm rozhodl, vzniká tier. Testy hlídají
tři vlastnosti, které se dají snadno rozbít, aniž si toho kdokoli všimne:

  1. bundle je ODVOZENÝ — přegenerování nesmí nic změnit ani ztratit,
  2. duplicita od téhož pracovníka NENÍ potvrzení,
  3. do paměti jde to, co prošlo branou, ne to, co pack napsal.
"""

from __future__ import annotations

from agency import ingest, knowledge, okf, runs

from conftest import make_finding

RUN_A = "01AAAAAAAAAAAAAAAAAAAAAAAA"
RUN_B = "01BBBBBBBBBBBBBBBBBBBBBBBB"

CLAUDE = {"provider": "claude", "model": "sonnet", "bin": "claude",
          "hire": "review-graph@claude"}
CODEX = {"provider": "codex", "model": "gpt-5", "bin": "codex",
         "hire": "review-graph@codex"}


def read_concept(project, fid: str) -> dict:
    root = project.agency_dir / knowledge.BUNDLE
    return okf.read(root / knowledge.LEDGER / f"{fid}.md", root=project.root)


def bundle_text(project, name: str) -> str:
    return (project.agency_dir / knowledge.BUNDLE / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ koncept

def test_nalez_je_koncept_ktery_precte_i_parser(project, make_run):
    """Zapisovač a čtečka bydlí v jednom modulu právě proto, aby se nerozešly.
    Kdyby ledger vyrobil soubor, který `okf.read` nepřečte, byl by to markdown
    pro lidi a rozbitý koncept pro všechny ostatní."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]

    knowledge.bundle(project)
    c = read_concept(project, fid)

    assert c["type"] == "Finding"
    assert c["title"].startswith("Uživatel se načte")
    assert c["status"] == "draft", "o nálezu nikdo nerozhodl"
    assert c["trust"] == "unverified"
    assert c["generated"] == {"by": "hire:review-graph@claude", "at": c["generated"]["at"]}
    assert "getUser" in c["body"], "koncept bez těla nálezu je jen nadpis"
    assert c["anchor"]["file"] == "src/auth.ts" and c["anchor"]["line"] == 2


def test_koncept_odkazuje_na_soubory_ktere_existuji(project, make_run):
    """Odkaz je celá pointa formátu — bundle se čte klikáním v editoru, ne
    nástrojem. Odkaz o adresář vedle je horší než žádný."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    knowledge.bundle(project)

    path = project.agency_dir / knowledge.BUNDLE / knowledge.LEDGER / f"{fid}.md"
    text = path.read_text(encoding="utf-8")

    assert "(../../../src/auth.ts)" in text
    assert (path.parent / "../../../src/auth.ts").resolve().is_file()
    assert f"(../../runs/{RUN_A}/)" in text
    assert (path.parent / f"../../runs/{RUN_A}").resolve().is_dir()


# ------------------------------------------------------------------ tiery

def test_duplicita_od_jineho_pracovnika_je_potvrzeni(project, make_run):
    """`codex našel → claude nezávisle potvrdil` je ta nejcennější věta na
    vstupu dalšího běhu. Jako dva samostatné nálezy v ledgeru by tvrdila, že
    projekt našel dvě věci — a tím by se ta informace ztratila úplně."""
    first = make_run(run_id=RUN_A, agent=CODEX)
    ingest.ingest(project, first)
    again = make_run([make_finding(project, RUN_B)], run_id=RUN_B, agent=CLAUDE)
    ingest.ingest(project, again)

    concepts = knowledge.ledger(project)

    assert len(concepts) == 1, "duplicita není další nález, je to druhý pracovník"
    c = concepts[0]
    assert c["trust"] == "machine-confirmed"
    assert c["occurrences"] == 2
    assert [v["by"] for v in c["verified"]] == ["hire:review-graph@claude"]
    assert c["generated"]["by"] == "hire:review-graph@codex", "autor je ten první"


def test_tyz_pracovnik_podruhe_neni_potvrzeni(project, make_run):
    """Týž pracovník nad týmž kódem podruhé je opakování, ne shoda dvou. Kdyby
    se to počítalo jako potvrzení, stačilo by pustit jeden pack dvakrát a
    ledger by tvrdil, že se na tom shodli dva."""
    ingest.ingest(project, make_run(run_id=RUN_A, agent=CLAUDE))
    ingest.ingest(project, make_run([make_finding(project, RUN_B)], run_id=RUN_B, agent=CLAUDE))

    c = knowledge.ledger(project)[0]

    assert c["occurrences"] == 2, "že ho našel podruhé, se neztrácí"
    assert c["verified"] == []
    assert c["trust"] == "unverified"


def test_rozhodnuti_cloveka_je_nejvyssi_tier(project, make_run):
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    runs.append_decision(run, fid, "rejected", reason="by-design", by="human:kuba")

    knowledge.bundle(project)
    c = read_concept(project, fid)

    assert c["trust"] == "human-reviewed"
    assert c["status"] == "deprecated", "tvrzení neobstálo — a nese si to v sobě"
    assert c["decision"] == {"state": "rejected", "reason": "by-design",
                             "by": "human:kuba", "at": c["decision"]["at"]}


def test_vlastni_rozhodnuti_nalez_nepotvrzuje(project, make_run):
    """Pack, který si sám odsouhlasí vlastní nález, není druhý názor. Bez téhle
    podmínky by stačilo `agency triage --by <vlastní hire>` a tier by vyskočil."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    runs.append_decision(run, fid, "accepted", by="hire:review-graph@claude")

    c = knowledge.ledger(project)[0]

    assert c["trust"] == "unverified"
    assert c["status"] == "stable", "rozhodnutí platí, jen ho nikdo nepřezkoumal"


def test_zamitnuty_nalez_z_pameti_nemizi(project, make_run):
    """„Tohle už jsme zamítli jako by-design" je vstup, kvůli kterému paměť
    existuje. Kdyby se zamítnuté nálezy do přehledu nepsaly, další běh by je
    hlásil znovu — a přesně tomu má ledger bránit."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    runs.append_decision(run, run.findings()[0]["id"], "rejected",
                         reason="by-design", by="human")
    knowledge.bundle(project)

    index = bundle_text(project, "index.md")

    assert "Rejected — do not report these again" in index
    assert "by-design" in index


# ------------------------------------------------------------------ odvozenost

def test_prestaveni_bundlu_nic_nezmeni(project, make_run):
    """Bundle je odvozený — dvě přestavení nad týmiž běhy musí dát bajt po
    bajtu totéž. Kdyby ne, `git diff` přestane odpovídat na otázku, co se
    změnilo, a bundle se stane šumem, který nikdo nečte."""
    make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)

    second = knowledge.bundle(project)

    assert second["changed"] == [] and second["removed"] == []


def test_bundle_jde_zahodit_a_postavit_znovu(project, make_run):
    """Pravda zůstává v `.agency/runs/`. Kdyby smazání bundlu něco ztratilo,
    byl by to druhý zdroj pravdy — a jeden špatný přepis by mazal historii."""
    import shutil

    run = make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)
    before = bundle_text(project, f"{knowledge.LEDGER}/{run.findings()[0]['id']}.md")

    shutil.rmtree(project.agency_dir / knowledge.BUNDLE)
    knowledge.bundle(project)

    assert bundle_text(project, f"{knowledge.LEDGER}/{run.findings()[0]['id']}.md") == before


def test_zahozeny_beh_zmizi_i_z_ledgeru(project, make_run):
    import shutil

    run = make_run(run_id=RUN_A, agent=CLAUDE)
    fid = run.findings()[0]["id"]
    knowledge.bundle(project)
    shutil.rmtree(run.dir)

    result = knowledge.bundle(project)

    assert f"{knowledge.LEDGER}/{fid}.md" in result["removed"]
    assert not (project.agency_dir / knowledge.BUNDLE / knowledge.LEDGER / f"{fid}.md").is_file()


def test_kontrola_bez_zapisu_nic_nepise(project, make_run):
    """`agency knowledge` bez `--rebuild` odpovídá na otázku, jestli je bundle
    v souladu s běhy. Odpověď, která si stav rovnou opraví, není odpověď."""
    make_run(run_id=RUN_A, agent=CLAUDE)

    dry = knowledge.bundle(project, write=False)

    assert dry["changed"], "bundle ještě neexistuje, takže se liší"
    assert not (project.agency_dir / knowledge.BUNDLE).exists()


def test_rucne_psana_pravidla_bundle_nesaha(project, make_run):
    """`rules/` je jediná část bundlu, kterou píše člověk. Generátor, který by
    mazal, co nevygeneroval, by první expirované pravidlo přepsal na nic."""
    rules_dir = project.agency_dir / knowledge.BUNDLE / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "sink.md").write_text(
        '---\ntype: Rule\ntitle: "Sink nesmí spolknout chybu"\n---\n\nTělo.\n',
        encoding="utf-8")
    make_run(run_id=RUN_A, agent=CLAUDE)

    result = knowledge.bundle(project)

    assert result["removed"] == []
    assert (rules_dir / "sink.md").is_file()
    assert "Sink nesmí spolknout chybu" in bundle_text(project, "index.md")


# ------------------------------------------------------------------ chronologie

def test_chronologie_bere_slova_specialisty(project, make_run):
    """`log.md` je jediné místo, kde specialista mluví vlastními slovy. Jádro
    shrnutí nepíše ani nedopisuje — jen ho přepíše do chronologie."""
    run = make_run(run_id=RUN_A, agent=CLAUDE)
    (run.dir / "summary.md").write_text(
        "Prošel jsem pět souborů kolem exportu. Jediné, co stojí za zmínku, "
        "je spolknutá chyba v sinku.", encoding="utf-8")
    knowledge.bundle(project)

    log = bundle_text(project, "log.md")

    assert "spolknutá chyba v sinku" in log
    assert f"[run {RUN_A}](../runs/{RUN_A}/)" in log
    assert "hire:review-graph@claude" in log


def test_beh_bez_shrnuti_je_v_chronologii_videt(project, make_run):
    """Kontrakt `summary.md` je v SKILL.md packů. Prázdné místo v chronologii
    je jediné, kde je vidět, že ho pack nesplnil — vynechat ten běh by tu
    informaci schovalo."""
    make_run(run_id=RUN_A, agent=CLAUDE)
    knowledge.bundle(project)

    assert "_No summary left behind._" in bundle_text(project, "log.md")


# ------------------------------------------------------------------ brána

def test_do_pameti_jde_az_to_co_proslo_branou(project, make_run):
    """Halucinovaný nález se nesmí stát pamětí projektu. Brána běží první a
    ledger se staví z toho, co po ní zbylo."""
    good = make_finding(project, RUN_A)
    phantom = make_finding(project, RUN_A, anchor={"file": "src/neni.ts"},
                           title="Nález v souboru, který na tom commitu není",
                           body="Jiné tvrzení o jiném místě, aby to nebyla duplicita.")
    run = make_run([good, phantom], run_id=RUN_A, agent=CLAUDE)

    result = ingest.ingest(project, run)

    assert result["counts"]["gated"] == 1
    ids = [c["id"] for c in knowledge.ledger(project)]
    assert ids == [good["id"]]
    assert result["bundle"]["changed"], "ingest ledger obnovuje sám"
