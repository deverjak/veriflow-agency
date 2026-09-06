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

#: The same, for `proc.stream`. The guard in `conftest.py` stays in place — it
#: is what stops a test reaching a real binary — and the one test below that
#: examines this function fakes `Popen` under it, so nothing is launched
#: either way.
real_stream = proc.stream


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


# ------------------------------------------------------------------ budget

def _budgeted(project, run, monkeypatch, *, seconds: float, budget: dict,
              turns: int = 3):
    """A run that takes `seconds` of wall clock, as far as the record cares."""
    clock = {"t": 0.0}
    monkeypatch.setattr(runs.time, "monotonic", lambda: clock["t"])

    def stream(argv, cwd=None, env=None, on_line=None, timeout=None):
        clock["t"] += seconds
        on_line(json.dumps({"type": "result", "subtype": "success",
                            "is_error": False, "num_turns": turns,
                            "session_id": "s", "result": "done",
                            "permission_denials": []}))
        return 0

    monkeypatch.setattr(proc, "stream", stream)
    return runs.attend(project, run, ["claude", "-p"], project.root,
                       dialect="claude-stream-json", budget=budget)


def test_a_run_past_its_budget_is_flagged_and_still_finishes(project, make_run,
                                                             monkeypatch):
    """"Kill it" and "do nothing" are both wrong answers. It may be mid-write
    of findings.json, and throwing that away costs more than the overrun."""
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=30 * 60,
                       budget={"minutes": 25, "turns": None})

    assert result["overBudget"] is True
    assert run.record()["cost"]["overBudget"] is True
    assert run.record()["status"] != "failed", "over budget is not a failure"


def test_a_run_inside_its_budget_says_nothing(project, make_run, monkeypatch):
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=60,
                       budget={"minutes": 25, "turns": None})

    assert result["overBudget"] is False
    assert "overBudget" not in run.record()["cost"]


def test_turns_are_judged_only_where_they_are_measured(project, make_run,
                                                       monkeypatch):
    """`turns` exist only for a streamed run, so an attended one is never over
    on turns rather than being judged on a number it does not have."""
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=60, turns=99,
                       budget={"minutes": None, "turns": 60})

    assert result["overBudget"] is True


def test_three_times_over_is_a_fault_not_an_overrun(project, make_run, monkeypatch):
    """The one place anything is stopped on a number — and the number is the
    pack's own, which is what makes it a fault rather than a heuristic."""
    run = make_run()
    seen = {}

    def stream(argv, cwd=None, env=None, on_line=None, timeout=None):
        seen["timeout"] = timeout
        return 124                      # what proc.stream returns at the ceiling

    monkeypatch.setattr(proc, "stream", stream)
    result = runs.attend(project, run, ["claude", "-p"], project.root,
                         dialect="claude-stream-json",
                         budget={"minutes": 25, "turns": None})

    assert seen["timeout"] == 25 * 60 * runs.RUNAWAY
    assert result["runaway"] is True


def test_the_ceiling_stops_a_run_that_keeps_talking(monkeypatch):
    """`proc.stream` used to apply its timeout only after the stream ended, so
    a run that never stopped emitting never reached it — a ceiling that fires
    only once the thing has stopped by itself is not a ceiling."""
    import subprocess as sp

    clock = {"t": 0.0}
    monkeypatch.setattr(proc.time, "monotonic", lambda: clock["t"])

    class FakeProc:
        def __init__(self):
            self.stdout = self
            self.killed = False

        def __iter__(self):
            while True:
                clock["t"] += 10
                yield "line\n"

        def close(self):
            pass

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    fake = FakeProc()
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(proc, "which", lambda name: name)

    code = real_stream(["claude", "-p"], timeout=25, on_line=lambda t: None)

    assert code == 124 and fake.killed
