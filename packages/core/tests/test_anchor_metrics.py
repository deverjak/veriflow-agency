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
    by = "hire:review-graph@claude"

    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "sent", by=by)
    runs.append_decision(run, ids[2], "rejected", reason="by-design", by=by)
    # ids[3] zůstane nerozhodnutý

    r = metrics.collect(project)

    assert r["triage"]["precision"] == round(2 / 3, 3)
    assert r["triage"]["undecided"] == 1
    assert r["queue"]["undecided"] == 1


def test_precision_pocita_jen_rozhodnuti_dalsiho_clena_retezu(project, make_run):
    """Rozhodnutí online na boardu se lokálně neukládá — `human` v datech je
    historie zpřed stopy a `chain` znamená „nikdo nerozhodl". Ani jedno není
    verdikt specialisty, tak ani jedno nesmí být čitatelem precision."""
    run = make_run(findings=[make_finding(project, "x") for _ in range(2)])
    ids = [f["id"] for f in run.findings()]

    runs.append_decision(run, ids[0], "sent", by="human")
    runs.append_decision(run, ids[1], "sent", by="chain")

    r = metrics.collect(project)

    assert r["triage"]["precision"] is None
    assert r["triage"]["accepted"] == 0
    assert r["triage"]["undecided"] == 0, "hotovo to je — jen to nezapočítá precision"


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
    by = "hire:review-graph@claude"
    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "rejected", reason="out-of-scope", by=by)

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


# ------------------------------------------- attended and unattended runs

def _run_costing(make_run, project, *, attended: bool, usd, turns, run_id=None):
    """One run of each population — the attended one deliberately carries no
    turns and no price, because that is exactly what an attended run records."""
    return make_run(
        run_id=run_id,
        findings=[make_finding(project, run_id or "x")],
        trigger={"kind": "manual", "attended": attended},
        agent={"provider": "claude", "model": "sonnet",
               **({"turns": turns} if turns is not None else {})},
        cost={"wallClockSeconds": 60, **({"usd": usd} if usd is not None else {})},
    )


def test_cost_comes_from_the_runs_that_could_measure_it(project, make_run):
    """`turns`, `usd` and `denied` exist only for a streamed run. Averaged over
    every run they were an average across a population half of which never
    recorded them — a number that reads as if it were about all of them."""
    _run_costing(make_run, project, attended=True, usd=None, turns=None,
                 run_id="01A0000000000000000000000A")
    _run_costing(make_run, project, attended=True, usd=None, turns=None,
                 run_id="01A0000000000000000000000B")
    _run_costing(make_run, project, attended=False, usd=0.42, turns=7,
                 run_id="01A0000000000000000000000C")

    c = metrics.collect(project)["cost"]

    assert c["usd"] == 0.42
    assert c["turns"] == 7
    # And it says which runs it could have come from.
    assert c["population"]["usd"] == 1
    assert c["population"]["turns"] == 1
    assert c["population"]["runs"] == 3
    assert c["population"]["attended"] == 2
    assert c["population"]["unattended"] == 1
    # Wall clock is its own population: `--wait` measures it attended too.
    assert c["population"]["wallClockSeconds"] == 3


def test_precision_still_counts_every_run(project, make_run):
    """The split is about cost, not about findings. An attended run's findings
    and decisions are as real as anyone's, and dropping them would trade one
    dishonest number for another."""
    a = _run_costing(make_run, project, attended=True, usd=None, turns=None,
                     run_id="01B0000000000000000000000A")
    b = _run_costing(make_run, project, attended=False, usd=0.1, turns=3,
                     run_id="01B0000000000000000000000B")
    by = "hire:review-graph@claude"
    runs.append_decision(a, a.findings()[0]["id"], "sent", by=by)
    runs.append_decision(b, b.findings()[0]["id"], "rejected", reason="by-design", by=by)

    t = metrics.collect(project)["triage"]

    assert t["accepted"] == 1 and t["rejected"] == 1
    assert t["precision"] == 0.5


def test_a_price_nobody_measured_is_none_not_zero(project, make_run):
    """Only attended runs: there is no cost number to report, and reporting
    $0.00 would say the runs were free rather than unmeasured."""
    _run_costing(make_run, project, attended=True, usd=None, turns=None)

    c = metrics.collect(project)["cost"]

    assert c["usd"] is None and c["turns"] is None
    assert c["population"]["usd"] == 0


def test_the_score_is_compared_against_what_happened(project, make_run):
    """A pack that gives everything 90 and has precision 0.4 is miscalibrated
    in a way no other number here shows — and both halves of it were already
    being written."""
    run = make_run(findings=[
        make_finding(project, "x", score=95),
        make_finding(project, "x", score=55, dimension="reuse",
                     title="Nothing imports the retry helper",
                     body="No caller reaches `retryOnce` since the queue rewrite.",
                     anchor={"symbol": {"name": "retryOnce", "range": [1, 4]}}),
    ])
    ids = [f["id"] for f in run.findings()]
    by = "hire:review-graph@claude"
    runs.append_decision(run, ids[0], "sent", by=by)
    runs.append_decision(run, ids[1], "rejected", reason="by-design", by=by)

    t = metrics.collect(project)["triage"]

    assert t["scoreAccepted"] == 95.0
    assert t["scoreRejected"] == 55.0
