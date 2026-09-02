"""`agency run --wait`: běh, který má rodiče.

`teams.md` Krok 2. Do teď jádro agenta vytisklo a rozloučilo se s ním —
`cmd_cleanup` to říká výslovně: *„no pid to watch and no exit code to catch"*.
Běh proto zůstal `running`, dokud si na `agency ingest` někdo nevzpomněl, a
nevzpomenout si nestálo nic.

Tady se zamyká to, co se s vlastnictvím procesu dá poprvé tvrdit — a hlavně to,
co se u toho nesmí ztratit: agent, který spadl, není agent bez nálezů; co stihl
zapsat, se nezahazuje; a přerušení není pád.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agency import cli, metrics, proc, runs
from agency.util import write_json

#: Skutečná `proc.attend`, uložená před tím, než ji conftest nahradí pojistkou.
#: Dva testy dole zkoumají ji samotnou — jak sestaví argv a co udělá s chybějící
#: binárkou — a ty ji potřebují zpátky.
real_attend = proc.attend


def agent(monkeypatch, code: int = 0, leaves=None):
    """Agent, ze kterého je vidět jen to podstatné: co po sobě nechal a jak
    skončil. Skutečné spuštění je jediná věc, kterou test pustit nemůže."""
    def fake(args, cwd=None, env=None):
        if leaves is not None:
            leaves()
        return code
    monkeypatch.setattr(proc, "attend", fake)


def wait(project, run, wt_owned: bool = False) -> int:
    return cli._wait_for_agent(project, run, ["claude", "prompt"], project.root, wt_owned)


# Agent, který nezapsal nic, je od 2. 9. 2026 `failed`, ne `no-findings` — brána
# za něj prázdné pole nevyrábí. Testy, které zkoumají chování po PÁDU, proto
# musí nechat `findings.json` na místě, jinak by měřily tuhle novou větev.


def nothing_written(run) -> None:
    """Agent, který nezapsal findings.json. Fixture ho zakládá vždycky, skutečný
    spadlý běh po sobě ale nenechá nic."""
    run.findings_path.unlink(missing_ok=True)


# ------------------------------------------------------------------ doběhnutí

def test_beh_se_zavre_sam_bez_druheho_prikazu(project, make_run, monkeypatch, capsys):
    """Kontrola hotovosti z `teams.md`: doběhne, ingest proběhl bez druhého
    příkazu, běh není `running` a záznam má `agent.exitCode`."""
    run = make_run()
    agent(monkeypatch, code=0)

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 0
    assert rec["status"] == "ok"
    assert rec["agent"]["exitCode"] == 0
    assert rec["counts"]["kept"] == 1, "brána proběhla bez `agency ingest`"
    assert runs.unfinished(project) == []


def test_hodiny_na_stopkach_maji_konecne_kdo_zmeri(project, make_run, monkeypatch, capsys):
    """`cost.wallClockSeconds` je v `run.v1` od začátku a nikdy ho nic
    nevyplnilo — nebyl proces, který by měřil. Metriky ho přitom čtou a
    `s per candidate` kvůli tomu bylo vždycky prázdné."""
    run = make_run()
    # Stopky, ne skutečné čekání: měří se rozdíl dvou čtení, a test má tvrdit
    # o tom čísle něco přesného, ne že „je to float".
    tick = iter([1000.0, 1272.4])
    monkeypatch.setattr(runs.time, "monotonic", lambda: next(tick, 1272.4))
    agent(monkeypatch, code=0)

    wait(project, run)
    capsys.readouterr()
    cost = run.record()["cost"]

    assert cost["wallClockSeconds"] == 272.4
    assert cost["credential"] == "subscription", "attended běh jede na předplatném"
    assert cost["provider"] == "claude"
    assert metrics.collect(project)["cost"]["secondsPerKeptFinding"] == 272


def test_zaznam_s_exit_codem_sedi_na_kontrakt(project, make_run, monkeypatch, capsys):
    """`agent.exitCode` a `cost` jsou nová pole v už validovaném dokumentu."""
    run = make_run()
    agent(monkeypatch, code=0)
    wait(project, run)
    capsys.readouterr()

    cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["recordErrors"] == []


# ------------------------------------------------------------------ selhání

def test_agent_ktery_spadl_neni_beh_bez_nalezu(project, make_run, monkeypatch, capsys):
    """Brána bez findings.json napíše `no-findings` — což je tvrzení „díval se
    a nic nenašel". U agenta, co skončil jedničkou, je to nepravda, a přesně tu
    exit code umí odhalit."""
    run = make_run()
    agent(monkeypatch, code=1, leaves=lambda: nothing_written(run))

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 1, "chain se má o co zastavit"
    assert rec["status"] == "failed"
    assert "1" in rec["exitReason"]
    assert "counts" not in rec, "brána nad ničím neběžela, takže ani nic netvrdí"


def test_co_agent_stihl_zapsat_se_nezahazuje(project, make_run, monkeypatch, capsys):
    """Chyba na konci sezení není důvod zahodit hotové nálezy. Projdou branou
    jako vždycky — jen běh u toho zůstane `failed`, aby se na něj někdo šel
    podívat."""
    run = make_run()
    agent(monkeypatch, code=2)

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 1
    assert rec["counts"]["kept"] == 1
    assert rec["status"] == "failed" and "2" in rec["exitReason"]


def test_preruseni_je_opusteny_beh_a_uklidi_po_sobe(project, make_run, monkeypatch, capsys):
    """Ctrl-C v terminálu zabije agenta i tenhle proces. Rozdíl proti `--launch`
    je, že tenhle proces ještě žije a stihne běh zavřít — včetně worktree, na
    který by uživatel jinak musel přijít sám."""
    run = make_run()
    wt = project.root.parent / "worktree"
    wt.mkdir()
    write_json(run.dir / "context.json", {"worktree": str(wt), "worktreeOwned": True})
    monkeypatch.setattr(runs, "remove_worktree", lambda project, path: None)

    def interrupted(args, cwd=None, env=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(proc, "attend", interrupted)

    code = wait(project, run, wt_owned=True)
    capsys.readouterr()
    rec = run.record()

    assert code == 130
    assert rec["status"] == "abandoned"
    assert "Ctrl-C" in rec["exitReason"]
    assert "worktree" not in rec


# ------------------------------------------------------------------ spuštění

def test_binarka_se_hleda_pres_which(monkeypatch):
    """Windows si k příkazu domyslí jen `.exe`. `codex` je fakticky `codex.CMD`
    a bez rozvinutí PATHEXT skončí jako FileNotFoundError — ověřeno na skutečné
    instalaci, ne odvozeno."""
    seen: list = []
    monkeypatch.setattr(proc, "which", lambda tool: r"C:\npm\codex.CMD")
    monkeypatch.setattr(subprocess, "call",
                        lambda args, cwd=None, env=None: seen.append(args) or 0)
    # Přes skutečnou funkci, ne přes pojistku z conftestu: tenhle test zkoumá
    # právě to, co pojistka jinak zakazuje — jak se sestaví spouštěcí příkaz.
    monkeypatch.setattr(proc, "attend", real_attend)

    assert proc.attend(["codex", "--model", "gpt"], cwd="/tmp") == 0
    assert seen[0] == [r"C:\npm\codex.CMD", "--model", "gpt"]


def test_chybejici_binarka_neni_pad(monkeypatch):
    """Nespustitelný příkaz je 127, stejně jako u `proc.run` a stejně jako
    v shellu — jádro z toho nedělá výjimku, kterou by musel chytat volající."""
    monkeypatch.setattr(proc, "which", lambda tool: None)

    def missing(args, cwd=None, env=None):
        raise FileNotFoundError(2, "nenalezeno")
    monkeypatch.setattr(subprocess, "call", missing)
    monkeypatch.setattr(proc, "attend", real_attend)

    assert proc.attend(["neni-tam"]) == 127


# ------------------------------------------------------------------ přepínače

def test_wait_a_json_se_vylucuji(project):
    """Agent píše do téhož stdout. Kontrakt „na výstupu je jeden JSON dokument"
    se u toho nedá slíbit — a slib, který rozbije cizí výpis, je horší než
    chybějící kombinace přepínačů."""
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "review-graph", "--wait", "--json", "--repo", str(project.root)])

    assert "--json" in str(e.value)


def test_wait_a_launch_se_vylucuji(project, capsys):
    """Dvě odpovědi na „kdo drží agenta". Argparse to odmítne dřív, než se
    cokoli připraví."""
    with pytest.raises(SystemExit):
        cli.main(["run", "review-graph", "--wait", "--launch", "--repo", str(project.root)])

    assert "not allowed with" in capsys.readouterr().err
