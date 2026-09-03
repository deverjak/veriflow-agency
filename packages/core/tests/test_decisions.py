"""Rozhodnutí je operace nad úložištěm, ne příkaz UI.

Tohle je test, který zavírá krok 1 plánu. Jeho smysl není „append funguje" —
je to důkaz, že rozhodnutí přežije proces, že poslední zápis vyhrává a že
zamítnutí bez důvodu neprojde. Kdyby kterákoli z těch tří vlastností chyběla,
precision se nedá spočítat a extension by musela stav dopočítávat sama.
"""

from __future__ import annotations

import json

import pytest

from agency import cli, runs


def test_rozhodnuti_prezije_znovunacteni(project, make_run):
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="hire:review-graph@claude")

    # Čte se z disku novým objektem — jako by mezitím spadl proces.
    znovu = runs.find_run(project, run.id)
    stav = runs.decisions(znovu)
    assert stav[fid]["state"] == "sent"
    assert stav[fid]["by"] == "hire:review-graph@claude", \
        "kdo rozhodl je vstup dalšího běhu, ne dekorace"


def test_posledni_zapis_vyhrava_ale_historie_zustava(project, make_run):
    """Append-only: stav se přehrává, nemutuje. Bez toho se dvě historie
    (člověk a agent) nedají sloučit."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "sent", by="vscode")
    runs.append_decision(run, fid, "rejected", reason="by-design", by="cli")

    assert runs.decisions(run)[fid]["state"] == "rejected"

    radky = [json.loads(l) for l in run.decisions_path.read_text(encoding="utf-8").splitlines() if l]
    assert [r["state"] for r in radky] == ["sent", "rejected"], "historie se přepsala"
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

    runs.append_decision(run, fid, "sent", by="human")
    assert runs.decisions(run)[fid]["state"] == "sent"


def test_stejny_nalez_ve_dvou_bezich_ma_vlastni_rozhodnuti(project, make_run):
    """Rozhodnutí patří k nálezu v běhu, ne k otisku. Nález ze staršího běhu
    zůstane rozhodnutý i po novém běhu nad týmž kódem."""
    stary = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    novy = make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB")

    runs.append_decision(stary, stary.findings()[0]["id"], "sent", by="human")

    assert len(runs.decisions(stary)) == 1
    assert runs.decisions(novy) == {}


# ------------------------------------------------------------------ agency triage (CLI)

def test_triage_accept_is_dispatch(project, make_run):
    """`accept` is not a status flip — it runs the pack's sink. No sink in
    this fixture project, so the finding stays `candidate`, honestly."""
    run = make_run()
    fid = run.findings()[0]["id"]

    code = cli.main(["triage", "accept", fid, "--repo", str(project.root), "--json"])

    assert code == 0
    assert runs.find_run(project, run.id).findings()[0]["state"] == "candidate"


def test_triage_reject_requires_a_reason(project, make_run):
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        cli.main(["triage", "reject", fid, "--repo", str(project.root)])


def test_triage_defer_no_longer_exists(project, make_run):
    """There is no third verdict any more — what is not rejected goes to
    the board when the chain ends, so `defer` is simply not a command."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        cli.main(["triage", "defer", fid, "--repo", str(project.root)])


def test_an_old_accepted_write_still_reads_back(project, make_run):
    """History is not rewritten, only interpreted. A decisions.jsonl line
    from before this migration still means what it always meant."""
    run = make_run()
    fid = run.findings()[0]["id"]
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"kind": "decision", "findingId": fid, "state": "accepted",
                            "reason": None, "note": None, "by": "human",
                            "at": runs.now()}) + "\n")

    assert runs.decisions(run)[fid]["state"] == "accepted"


def test_packs_json_carries_the_sink(project, capsys):
    """`agency doctor` and the pack's own manifest both need to see the sink
    a pack declares — without it a project without a board looks the same
    as one whose sink is simply broken."""
    from conftest import install_pack
    install_pack(project, "review-graph", {"sink": "python sink.py --finding {id}"})

    cli.main(["packs", "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    by_name = {p["name"]: p for p in data}
    assert by_name["review-graph"]["sink"] == "python sink.py --finding {id}"


def test_export_command_no_longer_exists(project):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["export"])


def test_status_json_carries_the_provider_catalog(project, make_run, capsys):
    """A client picking a runner before a run starts (the extension's preset
    picker) needs the provider/model list without hardcoding it."""
    make_run()

    cli.main(["status", "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    ids = [p["id"] for p in data["project"]["providers"]]
    assert "claude" in ids and "codex" in ids
