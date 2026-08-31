"""Brána a dedup.

Brána nekontroluje, jestli je nález chytrý. Kontroluje, jestli MŮŽE být
pravdivý — a nález ukazující na soubor, který na tom commitu neexistuje,
pravdivý být nemůže. Je to nejlevnější obrana proti tomu, aby se zvýšený objem
propsal do zvýšeného odpadu.
"""

from __future__ import annotations

from agency import dedup, ingest
from agency.util import read_json, write_json

from conftest import make_finding


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
    assert "podobnost" in vysledek["duplicates"][0]["how"]


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
