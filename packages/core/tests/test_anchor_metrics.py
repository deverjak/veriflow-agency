"""Kotva nad driftem a metriky.

Kotva je jediná věc v datech, kterou nejde doplnit zpětně. Když selže, komentář
se posadí na nevinný kód, ty ho zamítneš — a rozbiješ tím právě tu metriku,
kvůli které měření vzniklo. Proto se testuje na skutečném posunu v git repu,
ne na vymyšleném řetězci.
"""

from __future__ import annotations

from agency import anchor, metrics, runs
from agency.util import write_json

from conftest import git, make_finding


def _posun_soubor(repo):
    """Přidá nad funkci deset řádků a commitne — kotva musí kód najít i tak."""
    p = repo / "src" / "auth.ts"
    p.write_text("// hlavicka\n" * 10 + p.read_text(encoding="utf-8"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "posun")


def test_kotva_na_nezmenenem_souboru_plati_doslova(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]

    r = anchor.resolve(project.root, a)

    assert r.line == a["line"]
    assert r.via == "exact"


def test_vrstva_1_se_pta_na_soubor_ne_na_repozitar(project, make_run):
    """Kdyby se testovalo `commit == HEAD`, propadl by sem i nález na souboru,
    na který od analýzy nikdo nesáhl — HEAD je skoro vždy jiný commit."""
    run = make_run()
    a = run.findings()[0]["anchor"]

    (project.root / "jiny.txt").write_text("nesouvisi\n", encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "jiny soubor")

    r = anchor.resolve(project.root, a)

    assert r.via == "exact", "nález na netknutém souboru propadl přes vrstvu 1"


def test_kotva_prezije_posun_radku(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]
    _posun_soubor(project.root)

    r = anchor.resolve(project.root, a)

    assert r.line == a["line"] + 10, "posunutý kód se nenašel"
    assert r.via.startswith("snippet")


def test_drift_pozna_ze_se_na_kod_sahlo(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]

    assert anchor.drift(project.root, a) == "untouched"

    p = project.root / "src" / "auth.ts"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "return user", "if (!session) return null\n  return user"), encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "oprava")

    assert anchor.drift(project.root, a) == "touched"


def test_smazany_soubor_se_degraduje_neztrati(project, make_run):
    run = make_run()
    a = run.findings()[0]["anchor"]
    git(project.root, "rm", "-q", "src/auth.ts")
    git(project.root, "commit", "-q", "-m", "smazano")

    r = anchor.resolve(project.root, a)

    assert r.line is None
    assert r.note, "degradace bez vysvětlení je ztráta"
    assert anchor.drift(project.root, a) == "deleted"


# ----------------------------------------------------------------- metriky

def test_precision_se_pocita_jen_z_rozhodnutych(project, make_run):
    """Nerozhodnutý nález není ani pravda, ani lež. Kdyby padal do jmenovatele,
    každý nový běh by precision zředil a číslo by měřilo rychlost triage."""
    run = make_run(findings=[make_finding(project, "x") for _ in range(4)])
    ids = [f["id"] for f in run.findings()]

    runs.append_decision(run, ids[0], "accepted", by="test")
    runs.append_decision(run, ids[1], "accepted", by="test")
    runs.append_decision(run, ids[2], "rejected", reason="by-design", by="test")
    # ids[3] zůstane nerozhodnutý

    r = metrics.collect(project)

    assert r["triage"]["precision"] == round(2 / 3, 3)
    assert r["triage"]["undecided"] == 1
    assert r["queue"]["undecided"] == 1


def test_precision_bez_dat_je_none_ne_nula(project, make_run):
    """Nula z nuly není nula procent. Zaokrouhlit „nevím" na 0.0 je nejlevnější
    způsob, jak si zalhat o vlastním nástroji."""
    make_run()
    r = metrics.collect(project)

    assert r["triage"]["precision"] is None


def test_metriky_rozpadaji_podle_dimenze_a_modelu(project, make_run):
    """Souhrnné číslo neřekne, co s tím. `reuse 0.2` je pokyn vypnout dimenzi."""
    run = make_run(findings=[
        make_finding(project, "x", dimension="correctness"),
        make_finding(project, "x", dimension="reuse", title="Mrtvý kód zůstal ve větvi po refaktoru"),
    ])
    ids = [f["id"] for f in run.findings()]
    runs.append_decision(run, ids[0], "accepted", by="test")
    runs.append_decision(run, ids[1], "rejected", reason="out-of-scope", by="test")

    r = metrics.collect(project)

    assert r["byDimension"]["correctness"]["precision"] == 1.0
    assert r["byDimension"]["reuse"]["precision"] == 0.0
    assert r["byModel"]["sonnet"]["accepted"] == 1
    assert r["rejectReasons"] == {"out-of-scope": 1}


def test_duplicity_se_do_metrik_nepocitaji(project, make_run):
    """Duplicita není nález k rozhodnutí. Kdyby se počítala, fronta by rostla
    o práci, kterou už někdo udělal."""
    run = make_run(findings=[
        make_finding(project, "x"),
        make_finding(project, "x", state="duplicate", duplicateOf="jiny"),
    ])

    r = metrics.collect(project)

    assert r["triage"]["undecided"] == 1
