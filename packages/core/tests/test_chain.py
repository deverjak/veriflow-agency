"""`agency chain`: specialisté za sebou, s předáním mezi nimi.

`teams.md` Krok 3. Chain není konverzace — je to sekvence běhů, kde si členové
předávají soubory. Tenhle soubor jede celou cestu přes CLI (`cli.cmd_chain`),
protože právě spojení dílů je to, co se rozbíjí: jednotlivě fungovaly `--wait`,
`knowledge.upstream()` i triage už před ním.

Co se tady zamyká:

  * řetěz je v datech (`run.chain`), ne v pořadí adresářů — bez toho nejde
    zpětně poznat, které rozhodnutí padlo nad cizím nálezem v rámci předání,
  * zadání pro druhého člena **nemá strop** (na rozdíl od pozadí), jinak by
    řetěz tiše vyráběl nálezy, o kterých nikdo nerozhodl,
  * vzkaz předchůdce jsou jeho slova, ne převyprávění jádra,
  * odmítnutý nebo spadlý krok chain zastaví a řekne, co doběhlo.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pathlib import Path

from agency import chain, cli, hires, knowledge, packs, proc, runs
from agency.util import posix, write_json

from conftest import make_finding


# ------------------------------------------------------------------ pomůcky

def install(project, *names: str) -> None:
    """Instalace tak, jak ji dělá `agency add` — včetně zápisu pracovníka.

    Samotné `packs.apply` nechá projekt s metodou, na které nikdo nedělá.
    Od zrušení odvozených pracovníků (1. 9. 2026) to znamená prázdný roster,
    takže by chain neměl koho spustit a fixture by testovala něco jiného než
    skutečný projekt.
    """
    for n in names:
        pack = packs.load(n)
        packs.apply(pack, project, packs.plan(pack, project))
        hires.ensure_default(project, n, project.pack_config(n) or {})


def args(project, *members, **over) -> SimpleNamespace:
    base = dict(repo=str(project.root), json=False, members=list(members),
                pr=None, latest_merged=False, prompt="reconsent po expiraci",
                scenario=None, since=None, model=None, provider=None, force=False)
    base.update(over)
    return SimpleNamespace(**base)


def specialist(project, monkeypatch, *, findings=1, handoff: str | None = None,
               code: int = 0, fails_on: int = 0):
    """Agent, který doopravdy něco nechá po sobě.

    Běh si najde sám podle stavu `running` — skutečný agent to má z RUN_DIR
    v promptu, ale fake ho v `proc.attend` nedostane. Zapisuje to, na čem stojí
    předání: nálezy a `handoff.md`.
    """
    seen = {"steps": 0, "argv": []}

    def fake(argv, cwd=None):
        seen["steps"] += 1
        seen["argv"].append(list(argv))
        run = next(r for r in runs.load_runs(project)
                   if r.record().get("status") == "running")
        write_json(run.findings_path,
                   [make_finding(project, run.id, title=f"Nález kroku {seen['steps']}")
                    for _ in range(findings)])
        (run.dir / "summary.md").write_text(f"Shrnutí kroku {seen['steps']}.", encoding="utf-8")
        if handoff:
            (run.dir / "handoff.md").write_text(handoff, encoding="utf-8")
        if fails_on and seen["steps"] == fails_on:
            return 1
        return code

    monkeypatch.setattr(proc, "attend", fake)
    return seen


@pytest.fixture(autouse=True)
def never_launch_for_real(monkeypatch):
    """Pojistka, ne kosmetika.

    `cmd_chain` končí u `proc.attend`, tedy u skutečné binárky. Test, který
    zapomene podstrčit agenta, by spustil `claude` na stroji, který testy pouští
    — jednou se to při psaní tohohle souboru stalo. Výchozí stav je proto pád
    s vysvětlením; `specialist()` ho přebije.
    """
    def refuse(argv, cwd=None):
        raise AssertionError(
            f"test se pokusil spustit skutečného agenta: {argv[0]} — "
            "chybí volání specialist()")
    monkeypatch.setattr(proc, "attend", refuse)


@pytest.fixture
def team(project):
    """Dva workspace packy — právník a product owner, dvojice z plánu."""
    install(project, "legal", "po")
    return project


# ------------------------------------------------------------------ složení

def test_retez_potrebuje_aspon_dva_cleny(team):
    """Pro jednoho je příkaz `agency run`. Chain s jedním členem by byl jen
    dražší způsob, jak napsat totéž."""
    with pytest.raises(SystemExit, match="at least two"):
        cli.cmd_chain(args(team, "legal"))


def test_mix_provideru_se_odmitne_hned(team):
    """Vědomé zúžení v1 — jeden binár, jeden credential, jedna sada quirků.
    Podstatné je „hned": uživatel, kterému to spadne po prvním běhu, už zaplatil."""
    # Jménem hire, ne packu: instalace zapsala `po@claude` a tohle přidá
    # druhého, takže holé „po" by sáhlo po tom prvním — a mix by se neprojevil.
    second = hires.add(team, pack="po", provider="codex")

    with pytest.raises(SystemExit, match="one provider at a time"):
        cli.cmd_chain(args(team, "legal", second.id))


def test_preklep_ve_tretim_jmenu_nestoji_dva_behy(team):
    """Ověření členů je před prvním spuštěním, ne za pochodu."""
    with pytest.raises(SystemExit):
        cli.cmd_chain(args(team, "legal", "po", "neexistuje"))
    assert runs.load_runs(team) == []


# ------------------------------------------------------------------ průchod

def test_retez_dobehne_a_je_v_datech(team, monkeypatch, capsys):
    """Kontrola hotovosti Kroku 3: dva běhy, oba nesou týž `chain.id`, druhý má
    prvního v `upstream`."""
    specialist(team, monkeypatch)

    code = cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    assert code == 0
    done = sorted(runs.load_runs(team), key=lambda r: r.id)
    assert len(done) == 2

    first, second = (r.record() for r in done)
    assert first["chain"]["id"] == second["chain"]["id"]
    assert (first["chain"]["position"], first["chain"]["of"]) == (1, 2)
    assert (second["chain"]["position"], second["chain"]["of"]) == (2, 2)
    assert first["chain"]["upstream"] == []
    assert second["chain"]["upstream"] == [done[0].id]
    # Oba doběhly branou — chain nečeká na ruční `agency ingest`.
    assert first["status"] == "ok" and second["status"] == "ok"


def test_druhy_clen_dostane_upstream_bez_stropu(team, monkeypatch, capsys):
    """Strop 300 patří pozadí. Zadání se ořezávat nesmí: nález, který se do něj
    nevejde, je nález, o kterém druhý specialista nerozhodl."""
    specialist(team, monkeypatch, findings=5)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    upstream = json.loads((second.dir / "evidence" / "upstream.json").read_text(encoding="utf-8"))

    assert upstream["counts"]["findings"] == 5
    assert upstream["counts"]["undecided"] == 5
    assert len(upstream["findings"]) == 5
    assert upstream["runs"][0]["summary"].startswith("Shrnutí kroku 1")


def test_context_rekne_packu_ze_je_v_retezu(team, monkeypatch, capsys):
    """Pack se o své roli dozví z `context.json`, ne z promptu — prompt agent
    přečte jednou, context.json má po celý běh."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    ctx = json.loads((second.dir / "context.json").read_text(encoding="utf-8"))

    assert ctx["chain"]["position"] == 2
    assert ctx["chain"]["upstreamFile"] == "evidence/upstream.json"
    assert ctx["chain"]["handoffFile"] == "handoff.md"

    first = sorted(runs.load_runs(team), key=lambda r: r.id)[0]
    assert json.loads((first.dir / "context.json").read_text(encoding="utf-8"))["chain"]["position"] == 1


# ------------------------------------------------------------------ předání

def test_vzkaz_predchudce_jsou_jeho_slova(team, monkeypatch, capsys):
    """`handoff.md` jde do promptu doslova. Kdyby ho jádro převyprávělo, byla by
    to věta, za kterou se nikdo nepodepsal."""
    specialist(team, monkeypatch, handoff="Reconsent stojí na domněnce o účtech — potvrď ji.")

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    prompt = (second.dir / "prompt.txt").read_text(encoding="utf-8")

    assert "Reconsent stojí na domněnce o účtech — potvrď ji." in prompt
    assert "step 2/2" in prompt
    assert "evidence/upstream.json" in prompt
    assert "First judge those findings" in prompt


def test_bez_handoffu_se_preda_summary(team, monkeypatch, capsys):
    """`handoff.md` je volitelný. Když chybí, popisné shrnutí je pořád lepší
    vstup než holé počty."""
    specialist(team, monkeypatch, handoff=None)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    assert "Shrnutí kroku 1." in (second.dir / "prompt.txt").read_text(encoding="utf-8")


def test_prvni_clen_nedostane_upstream(team, monkeypatch, capsys):
    """Prvnímu nikdo nic nepředal — a prompt to má říct, místo aby mlčel."""
    specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    first = sorted(runs.load_runs(team), key=lambda r: r.id)[0]
    prompt = (first.dir / "prompt.txt").read_text(encoding="utf-8")

    assert "step 1/2" in prompt
    assert "You run first" in prompt
    assert not (first.dir / "evidence" / "upstream.json").exists()


def test_mlceni_agenta_se_nenahrazuje(team, monkeypatch, capsys):
    """Když člen nenechá ani handoff, ani summary, prompt se opře o počty.
    Vymyslet za něj vzkaz by bylo tvrzení, za které se nikdo nepodepsal."""
    def fake(argv, cwd=None):
        run = next(r for r in runs.load_runs(team) if r.record().get("status") == "running")
        write_json(run.findings_path, [make_finding(team, run.id)])
        return 0
    monkeypatch.setattr(proc, "attend", fake)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    second = sorted(runs.load_runs(team), key=lambda r: r.id)[1]
    prompt = (second.dir / "prompt.txt").read_text(encoding="utf-8")
    assert "Handoff from" not in prompt
    assert "1 findings" in prompt


def test_agent_smi_cist_celou_pamet_projektu(team, monkeypatch, capsys):
    """Autorizace musí pokrýt to, co jádro samo předalo.

    `context.json` posílá specialistu do `knowledge` bundlu, do stránek packu
    a v řetězu do `evidence/upstream.json` s odkazy na cizí běhy. Dlouho se
    přitom povoloval jen RUN_DIR, takže běh ve worktree narazil na „Read
    outside the working directories" u adresáře, na který ho poslalo jádro.
    Dát cestu a nedat k ní přístup je chyba autorizace, ne otravnost.
    """
    seen = specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    for step in seen["argv"]:
        assert "--add-dir" in step
        allowed = step[step.index("--add-dir") + 1]
        assert allowed == posix(team.agency_dir), (
            f"agent dostal povolený {allowed}, ale čte celou paměť projektu")


def test_povoleny_adresar_pokryva_upstream_i_bundle(team, monkeypatch, capsys):
    """Konkrétně: run dir druhého člena, běh prvního člena a knowledge bundle
    leží všechny pod tím jedním povoleným adresářem."""
    seen = specialist(team, monkeypatch)

    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    allowed = Path(seen["argv"][1][seen["argv"][1].index("--add-dir") + 1])
    first, second = sorted(runs.load_runs(team), key=lambda r: r.id)
    for path in (second.dir, first.dir, team.agency_dir / knowledge.BUNDLE):
        assert allowed in path.parents or allowed == path, f"{path} je mimo povolený adresář"


# ------------------------------------------------------------------ zastavení

def test_spadly_krok_retez_zastavi(team, monkeypatch, capsys):
    """Pokračovat potichu by znamenalo, že product owner soudí nálezy, které
    nevznikly."""
    specialist(team, monkeypatch, fails_on=1)

    code = cli.cmd_chain(args(team, "legal", "po"))
    printed = capsys.readouterr().out

    assert code != 0
    assert len(runs.load_runs(team)) == 1, "druhý člen se neměl spustit"
    assert "the chain stops at step 1/2" in printed
    assert runs.load_runs(team)[0].record()["status"] == "failed"


def test_zastaveny_retez_rekne_co_dobehlo(team, monkeypatch, capsys):
    """Přerušený řetěz je pořád výsledek, jen kratší — a musí být vidět, kde
    se dá navázat ručně."""
    specialist(team, monkeypatch, fails_on=2)

    cli.cmd_chain(args(team, "legal", "po", "qa"))
    printed = capsys.readouterr().out

    assert "1/3" in printed and "2/3" in printed and "3/3" in printed
    assert "not started" in printed


# ------------------------------------------------------------------ přehled

def test_status_ukaze_prislusnost_k_retezu(team, monkeypatch, capsys):
    """Bez toho vypadá tým jako několik nesouvisejících běhů."""
    specialist(team, monkeypatch)
    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    cli.cmd_status(SimpleNamespace(repo=str(team.root), json=False, limit=10))
    printed = capsys.readouterr().out
    assert "chain" in printed and "1/2" in printed and "2/2" in printed


def test_status_json_nese_cely_blok(team, monkeypatch, capsys):
    specialist(team, monkeypatch)
    cli.cmd_chain(args(team, "legal", "po"))
    capsys.readouterr()

    cli.cmd_status(SimpleNamespace(repo=str(team.root), json=True, limit=10))
    data = json.loads(capsys.readouterr().out)
    blocks = [r["chain"] for r in data]
    assert {b["position"] for b in blocks} == {1, 2}
    assert len({b["id"] for b in blocks}) == 1


# ------------------------------------------------------------------ jednotky

def test_handoff_se_zkrati_a_rekne_o_tom(project, make_run):
    """Vykopávací věta má být k přečtení, ne k prolistování — a že se krátilo,
    se nesmí zamlčet."""
    run = make_run()
    (run.dir / "handoff.md").write_text("\n".join(f"řádek {i}" for i in range(120)),
                                        encoding="utf-8")
    text, source = chain.handoff_text(run)

    assert source == "handoff.md"
    assert text.count("\n") == chain.HANDOFF_LINES
    assert "more lines in the file" in text


def test_prazdny_handoff_se_chova_jako_zadny(project, make_run):
    run = make_run()
    (run.dir / "handoff.md").write_text("   \n\n", encoding="utf-8")
    (run.dir / "summary.md").write_text("Shrnutí.", encoding="utf-8")

    text, source = chain.handoff_text(run)
    assert (text, source) == ("Shrnutí.", "summary.md")


def test_ingest_zaznamena_ze_handoff_existuje(project, make_run):
    """Brána soubor nečte ani nedopisuje — jen zaznamená, že je."""
    from agency import ingest
    run = make_run()
    (run.dir / "handoff.md").write_text("Vzkaz.", encoding="utf-8")

    ingest.ingest(project, run)
    assert run.record()["outputs"]["handoff"] is True
    assert run.record()["outputs"]["summary"] is False
