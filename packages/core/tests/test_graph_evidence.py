"""Grafový signál se čte strojově, ne z panelu psaného pro člověka.

Do 1. 9. 2026 se `changedFunctions` a spol. tahaly regexem z Rich panelu
`detect-changes --brief`. Až by CRG přeformuloval větu, čísla by tiše zmizela
z run recordu — nic by nespadlo, jen by se začaly zapisovat prázdná pole.
Proto tenhle soubor hlídá tvar dat, ne text, a shrnutí v podstrčených
odpovědích schválně lže: kdyby se někdo vrátil ke čtení vět, testy to poznají.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agency import proc, runs

SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "run.v1.json"

# Tvar `detect-changes` bez `--brief`, ověřený proti code-review-graph 2.3.7.
DETECT = {
    "summary": "Analyzed 1 changed file(s):\n  - 1 changed function(s)\n  - 0 test gap(s)",
    "risk_score": 0.8,
    "changed_functions": [{"name": f"f{i}"} for i in range(82)],
    "affected_flows": [{"name": "checkout"}],
    "test_gaps": [{"name": f"g{i}"} for i in range(50)],
    "functions_truncated": False,
}


def canned(payload) -> proc.Result:
    return proc.Result(True, 0, json.dumps(payload), "")


@pytest.fixture
def fake_crg(monkeypatch):
    """Podstrčí odpovědi grafu podle příkazu. Co se nestubuje, selže."""
    def _install(**by_command: proc.Result):
        def crg(*args: str, cwd=None, timeout: int = 1800) -> proc.Result:
            key = args[0].replace("-", "_")
            return by_command.get(key, proc.Result(False, 1, "", f"{args[0]}: not stubbed"))
        monkeypatch.setattr(proc, "crg", crg)
    return _install


def _all_stubbed(fake_crg, detect=None):
    fake_crg(detect_changes=canned(detect if detect is not None else DETECT),
             impact=canned({"status": "ok"}), dead_code=canned([]))


def test_statistiky_vznikaji_z_json_ne_z_vety_v_panelu(project, make_run, fake_crg):
    """Shrnutí hlásí jednu funkci, data jich mají 82. Platí data."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    assert stats["changedFunctions"] == 82
    assert stats["untestedFunctions"] == 50
    assert stats["affectedFlows"] == 1
    assert stats["riskScore"] == 0.8
    assert "changedFunctionsTruncated" not in stats

    saved = json.loads((run.dir / "evidence" / "detect-changes.json")
                       .read_text(encoding="utf-8"))
    assert len(saved["test_gaps"]) == 50, \
        "dimenze `tests` čte test_gaps[] — dřív to byl seznam „Untested:“ ve větě"


def test_pocet_souboru_je_z_bezu_ne_z_grafu(project, make_run, fake_crg):
    """`files[]` je seznam po `skipPatterns`. Graf počítá svůj diff a o filtru
    neví, takže jeho číslo popisuje jinou množinu, než jakou běh recenzuje."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run, {"baseRefOid": "b" * 40},
                                  ["src/auth.ts", "src/pay.ts"])

    assert stats["changedFiles"] == 2


def test_orizly_seznam_se_zapise_jako_orizly(project, make_run, fake_crg):
    """CRG řeže na `CRG_MAX_CHANGED_FUNCS` a ten strop hlásí i ve shrnutí jako
    výsledek. Bez příznaku by v záznamu stálo „500 změněných funkcí“ jako fakt,
    ne jako dolní odhad — a rozdíl mezi velkým a uříznutým PR by zmizel."""
    _all_stubbed(fake_crg, dict(DETECT, functions_truncated=True,
                                changed_functions=[{"name": f"f{i}"} for i in range(500)]))
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    assert stats["changedFunctions"] == 500
    assert stats["changedFunctionsTruncated"] is True


def test_chyba_grafu_nekonci_v_json_souboru(project, make_run, fake_crg):
    """Běh bez grafového signálu je legitimní výsledek, takže se nepadá. Ale
    chybová hláška uložená jako `.json` by dimenzi vypadala jako data."""
    fake_crg()
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])

    ev = run.dir / "evidence"
    assert not (ev / "detect-changes.json").exists()
    assert not (ev / "dead-code.json").exists()
    assert "not stubbed" in (ev / "detect-changes.error.txt").read_text(encoding="utf-8")
    assert "changedFunctions" not in stats
    assert stats["changedFiles"] == 1, "co jádro ví samo, přežije výpadek grafu"


def test_beh_zapise_na_co_se_driver_umi_zeptat(project, make_run, fake_crg):
    """Pack podle toho pozná, kterou dimenzi má přeskočit. Co driver neumí, se
    nedokládá — a bez tohohle souboru by to musel hádat z prázdné evidence."""
    _all_stubbed(fake_crg)
    run = make_run(findings=[])

    runs.collect_evidence(project, project.root, run, {"baseRefOid": "b" * 40}, [])

    caps = json.loads((run.dir / "evidence" / "graph-capabilities.json")
                      .read_text(encoding="utf-8"))
    assert caps["driver"]
    assert "tests-for" in caps["capabilities"]


def test_statistiky_se_vejdou_do_run_v1(project, make_run, fake_crg):
    """`graph` má v `run.v1` zavřený seznam klíčů. Nový statistický klíč bez
    zápisu do schématu nespadne tady, ale až při validaci hotového běhu."""
    _all_stubbed(fake_crg, dict(DETECT, functions_truncated=True))
    run = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, run,
                                  {"baseRefOid": "b" * 40}, ["src/auth.ts"])
    ginfo = runs.prepare_graph(project, project.root)

    allowed = set(json.loads(SCHEMA.read_text(encoding="utf-8"))
                  ["properties"]["graph"]["properties"])
    # Paměť se sbírá při téže přípravě, ale do `graph` ji jádro nepíše.
    graph_keys = (set(stats) | set(ginfo)) - set(runs.MEMORY_STATS)
    assert graph_keys <= allowed, f"neznámé pro schéma: {sorted(graph_keys - allowed)}"
    assert set(runs.MEMORY_STATS) & set(stats), "paměť se pořád sbírá, jen bydlí jinde"
    assert ginfo["driver"] and ginfo["capabilities"], \
        "bez driveru a schopností nejde výměnu vyhodnotit"
