"""Šev nad grafem: otázky, ne příkazy nástroje.

Volání grafu bylo rozeseté v pěti modulech a ve dvou SKILL.md, takže výměna
nástroje začínala grepem, ne kontraktem. Testy tady hlídají to, co po výměně
musí platit dál: verby vracejí typovaný tvar, cesty jsou relativní k repu,
chybějící schopnost je odpověď, ne výjimka — a pack umí říct, na čem stojí.
"""

from __future__ import annotations

import json

import pytest

from agency import cli, graph, packs, proc


def canned(payload) -> proc.Result:
    return proc.Result(True, 0, json.dumps(payload), "")


@pytest.fixture
def fake_crg(monkeypatch):
    """Podstrčí odpovědi driveru podle příkazu. Co se nestubuje, selže."""
    def _install(**by_command: proc.Result):
        def crg(*args: str, cwd=None, timeout: int = 1800) -> proc.Result:
            key = args[0].replace("-", "_")
            return by_command.get(key, proc.Result(False, 1, "", f"{args[0]}: not stubbed"))
        monkeypatch.setattr(proc, "crg", crg)
    return _install


# ---------------------------------------------------------- schopnosti

def test_pack_nechce_po_driveru_nic_vymysleneho(project):
    """Politika packu je seznam verbů, ne volný text. Kdyby si pack vyžádal
    `tests_for` místo `tests-for`, doctor by hlásil chybějící schopnost
    u driveru, který ji umí — a nikdo by nepoznal proč."""
    known = set(graph.capabilities())
    for pack in packs.available(project):
        policy = pack.run_policy["graph"]
        if not policy:
            continue
        unknown = [v for v in policy["required"] + policy["optional"] if v not in known]
        assert not unknown, f"{pack.name} chce neznámé verby: {unknown}"


def test_politika_grafu_snese_stary_boolean():
    """Starší manifest říkal jen ano/ne. Nesmí se rozbít — jen neurčuje verby."""
    assert packs.graph_policy(True) == {"required": [], "optional": []}
    assert packs.graph_policy(False) is None
    assert packs.graph_policy(None) is None
    assert packs.graph_policy({"required": ["changes"]}) == {
        "required": ["changes"], "optional": []}


# ---------------------------------------------------------------- verby

def test_chybejici_index_neni_chyba(project):
    """„Ještě se nestavěl" je odpověď. Výjimka by z legitimního stavu udělala
    selhání a doctor by nemohl poradit, co s tím."""
    answer = graph.state(project.root)

    assert answer.ok is True
    assert answer.data["exists"] is False


def test_stav_pozna_index_z_jine_hlavicky(project, fake_crg):
    """Index postavený na jiném commitu umí nález opřít o kód, který na téhle
    větvi neexistuje. Z lidského panelu se to dalo jen přečíst očima."""
    (project.root / ".code-review-graph").mkdir(parents=True, exist_ok=True)
    (project.root / graph.DB_PATH).write_bytes(b"x")
    fake_crg(status=canned({"nodes": 12, "edges": 30, "files": 4,
                            "built_at_commit": "a" * 40, "current_sha": "b" * 40}))

    data = graph.state(project.root).data

    assert data["nodes"] == 12
    assert data["stale"] is True


def test_zmeny_jsou_cisla_z_dat_ne_z_vety(project, fake_crg):
    """Shrnutí driveru je psané pro člověka a mění se s formulací. Kontrakt
    stojí na tvaru dat."""
    fake_crg(detect_changes=canned({
        "summary": "Analyzed 1 changed file(s):\n  - 1 changed function(s)",
        "risk_score": 0.8,
        "changed_functions": [{"name": f"f{i}"} for i in range(7)],
        "affected_flows": [], "test_gaps": [{"name": "g"}],
        "functions_truncated": True,
    }))

    d = graph.changes(project.root, "b" * 40).data

    assert d == {"functions": 7, "functionsTruncated": True, "flows": 0,
                 "testGaps": 1, "riskScore": 0.8}


def test_locate_vraci_cestu_relativni_k_repu(project, fake_crg):
    """Kotva potřebuje `src/auth.ts`, driver vrací absolutní cestu. Do 1. 9. 2026
    se to spravovalo regexem nad stdoutem přímo v `anchor.py`."""
    fake_crg(search=canned({"results": [{
        "name": "getUser", "kind": "Function",
        "file_path": str(project.root / "src" / "auth.ts"),
        "line_start": 1, "line_end": 4, "is_test": False,
    }]}))

    found = graph.locate(project.root, "getUser").data

    assert found[0]["file"] == "src/auth.ts"
    assert found[0]["line"] == 1


def test_selhani_driveru_je_odpoved_ne_vyjimka(project, fake_crg):
    """Běh bez grafového signálu je legitimní výsledek. Volající si vybere, co
    s tím — spadnout smí jen tam, kde na tom nález stojí."""
    fake_crg()

    answer = graph.changes(project.root, "b" * 40)

    assert answer.ok is False
    assert "not stubbed" in answer.error
    assert answer.data is None


def test_neznamy_smer_se_neptaame_grafu(project):
    """Překlep ve směru je chyba volajícího, ne odpověď grafu."""
    with pytest.raises(SystemExit):
        graph.neighbors(project.root, "getUser", direction="sideways")


# ------------------------------------------------------------ worktree

def test_priprava_bez_indexu_nic_nekopiruje(project, tmp_path, fake_crg):
    fake_crg()
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(project.root / graph.DB_PATH, wt)

    assert info["action"] == "missing"
    assert not (wt / graph.DB_PATH).exists()


def test_priprava_zkopiruje_index_a_doindexuje(project, tmp_path, fake_crg):
    """Strategie `copy-db`: `build` se ve worktree nespouští nikdy — přestavěl by
    celé repo kvůli stavu, který se za chvíli zahodí."""
    fake_crg(update=proc.Result(True, 0, "ok", ""), __version__=None)
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(src, wt)

    assert info["action"] == "update"
    assert (wt / graph.DB_PATH).read_bytes() == b"index"


def test_priprava_v_projektu_samotnem_nekopiruje_index_na_sebe(project, fake_crg):
    """Pack s grafem a bez worktree pracuje v projektu — index je už na místě.
    Kopie sebe na sebe je na Windows tvrdá chyba, ne hraniční případ."""
    fake_crg(update=proc.Result(True, 0, "ok", ""))
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")

    info = graph.prepare(src, project.root)

    assert info["action"] == "update"
    assert src.read_bytes() == b"index"


def test_priprava_neaktualizuje_kdyz_si_to_projekt_neprejeje(project, tmp_path, fake_crg):
    fake_crg()
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(src, wt, on_stale="ignore")

    assert info["action"] == "reused"


# ----------------------------------------------------------------- CLI

def test_agency_graph_rekne_co_driver_umi(project, capsys):
    """Půlka použití grafu žije v promptu a Python fasáda ji nepokryje. Tohle
    jsou ty dveře — a jsou zároveň místo, kde se šev testuje každým během."""
    assert cli.main(["graph", "capabilities", "--repo", str(project.root)]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["driver"] == graph.DRIVER
    assert "tests-for" in data["capabilities"]
    assert data["workspaceStrategy"] == "copy-db"


def test_agency_graph_vraci_nenulovy_kod_kdyz_se_nezeptal(project, capsys, fake_crg):
    fake_crg()

    code = cli.main(["graph", "changes", "--base", "b" * 40, "--repo", str(project.root)])

    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["ok"] is False
    assert data["error"]
