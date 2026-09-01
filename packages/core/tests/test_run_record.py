"""Záznam běhu proti vlastnímu kontraktu.

`run.v1` do 1. 9. 2026 nekontroloval nikdo — `agency validate` četlo jen
`finding.v1` — a záznam se se svým schématem stihl rozejít na třech místech:
paměť slitá do `graph`, stav `gated-out` mimo enum, `slug: null` v repozitáři
bez remote. Dvě z toho byly chyby schématu, jedna chyba zápisu. Společné měly
to, že je nemělo co ohlásit.
"""

from __future__ import annotations

import json

from agency import cli


def _validate(project, run, capsys) -> tuple[int, dict]:
    code = cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_zaznam_behu_sedi_na_kontrakt(project, make_run, capsys):
    """Běžný běh projde. Kdyby neprošel, je validace k ničemu — hlásila by
    chybu na všechno a nikdo by ji nečetl."""
    run = make_run()

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0


def test_pamet_slita_do_grafu_se_ohlasi(project, make_run, capsys):
    """Přesně ta chyba, se kterou se běhy zapisovaly do 1. 9. 2026: `graph` má
    zavřený seznam klíčů a `knownFindings` mezi ně nepatří."""
    run = make_run()
    rec = run.record()
    rec["graph"] = {"tool": "code-review-graph 2.3.7", "action": "update",
                    "knownFindings": 12}
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert code == 1
    assert any("knownFindings" in e["message"] for e in data["recordErrors"])


def test_gated_out_je_platny_stav(project, make_run, capsys):
    """Běh, kterému brána zahodila všechno, není běh bez nálezů — a extension
    pro ten stav odjakživa má vlastní ikonu. Chybělo jen ve schématu."""
    run = make_run()
    rec = run.record()
    rec["status"] = "gated-out"
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0


def test_projekt_bez_remote_je_platny(project, make_run, capsys):
    """Doctor říká „no remote — the hired specialists do not need one“. Schéma
    přesto chtělo `slug` jako string, takže každý běh v takovém repu psal
    neplatný záznam."""
    run = make_run()
    rec = run.record()
    rec["project"] = {"slug": None, "defaultBranch": "main"}
    run.save_record(rec)

    code, data = _validate(project, run, capsys)

    assert data["recordErrors"] == []
    assert code == 0
