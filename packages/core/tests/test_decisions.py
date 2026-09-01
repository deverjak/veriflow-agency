"""Rozhodnutí je operace nad úložištěm, ne příkaz UI.

Tohle je test, který zavírá krok 1 plánu. Jeho smysl není „append funguje" —
je to důkaz, že rozhodnutí přežije proces, že poslední zápis vyhrává a že
zamítnutí bez důvodu neprojde. Kdyby kterákoli z těch tří vlastností chyběla,
precision se nedá spočítat a extension by musela stav dopočítávat sama.
"""

from __future__ import annotations

import json

import pytest

from agency import runs


def test_rozhodnuti_prezije_znovunacteni(project, make_run):
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "accepted", by="hire:review-graph@claude")

    # Čte se z disku novým objektem — jako by mezitím spadl proces.
    znovu = runs.find_run(project, run.id)
    stav = runs.decisions(znovu)
    assert stav[fid]["state"] == "accepted"
    assert stav[fid]["by"] == "hire:review-graph@claude", \
        "kdo rozhodl je vstup dalšího běhu, ne dekorace"


def test_posledni_zapis_vyhrava_ale_historie_zustava(project, make_run):
    """Append-only: stav se přehrává, nemutuje. Bez toho se dvě historie
    (člověk a agent) nedají sloučit."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "deferred", by="vscode")
    runs.append_decision(run, fid, "rejected", reason="by-design", by="cli")

    assert runs.decisions(run)[fid]["state"] == "rejected"

    radky = [json.loads(l) for l in run.decisions_path.read_text(encoding="utf-8").splitlines() if l]
    assert [r["state"] for r in radky] == ["deferred", "rejected"], "historie se přepsala"
    assert [r["by"] for r in radky] == ["human", "human"], \
        "starý zápis (`vscode`, `cli`) je člověk — dveřmi se identita neurčuje"


def test_zamitnuti_bez_duvodu_neprojde(project, make_run):
    """Volný text by dal stejnou práci a žádné číslo — precision se z něj
    nespočítá. Proto je důvod povinný a z enumu."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "rejected", by="human")
    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "rejected", reason="protoze-se-mi-nelibi", by="human")

    assert runs.decisions(run) == {}


def test_poznamka_neni_rozhodnuti(project, make_run):
    """Poznámka je volný text pro čtenáře, rozhodnutí je strukturovaný vstup
    metriky. Smíchat je znamená rozbít buď měření, nebo použitelnost."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "note", "findingId": fid,
                            "text": "ověřeno na produkci", "by": "vscode"}) + "\n")

    assert runs.decisions(run) == {}, "poznámka se započítala jako rozhodnutí"

    runs.append_decision(run, fid, "accepted", by="human")
    assert runs.decisions(run)[fid]["state"] == "accepted"


def test_stejny_nalez_ve_dvou_bezich_ma_vlastni_rozhodnuti(project, make_run):
    """Rozhodnutí patří k nálezu v běhu, ne k otisku. Nález ze staršího běhu
    zůstane rozhodnutý i po novém běhu nad týmž kódem."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")

    runs.append_decision(stary, stary.findings()[0]["id"], "accepted", by="human")

    assert len(runs.decisions(stary)) == 1
    assert runs.decisions(novy) == {}
