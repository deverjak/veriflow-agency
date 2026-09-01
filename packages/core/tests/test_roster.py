"""Roster: jedna metoda, víc pracovníků.

Pack je metoda, hire je pracovník, který se jí drží. Táž metoda se dá najmout
jednou na každý runner — „recenzent na sonnetu" a „recenzent na codexu" jsou dva
zápisy nad jednou konfigurací, jednou frontou nálezů a jedním dedupem.

Nejdůležitější testy v souboru jsou dva a oba jsou o paralelním běhu:
`test_dva_specialiste_maji_kazdy_svuj_worktree` a
`test_beh_nesmi_prevzit_worktree_bezicimu_behu`. Bez nich by druhý specialista
nad tímtéž pull requestem prvnímu smazal rozdělanou práci `--force`em — a to je
selhání, které se pozná až tím, že chybí výsledek.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agency import cli, hires, metrics, packs, providers, runs
from agency.util import posix, write_json

from conftest import make_finding


# ------------------------------------------------------------------ providery

def test_neregistrovany_provider_se_neodmita():
    """`--provider mujskript` má fungovat bez registrace. Registrace je kvůli
    nabídce a doktorovi, ne kvůli povolení."""
    spec = providers.spec("nekdo-novy")
    assert spec["bin"] == "nekdo-novy"
    assert spec["unregistered"] is True


def test_registrace_pridava_runner_bez_zasahu_do_kodu(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_HOME", str(tmp_path / "home"))

    providers.register("grok", bin="grok-cli", title="Grok", models=["fast", "heavy"])

    assert "grok" in providers.known()
    assert providers.spec("grok")["bin"] == "grok-cli"
    assert providers.spec("grok")["models"] == ["fast", "heavy"]
    # Vestavěné registrace nepřepisuje.
    assert providers.spec("claude")["bin"] == "claude"

    assert providers.forget("grok") is True
    assert "grok" not in providers.known()


def test_prepis_vestavene_je_prekryv_ne_nahrada(tmp_path, monkeypatch):
    """Kdo má claude jinde nebo přes wrapper, přepíše `bin` a zbytek tvaru
    spuštění mu zůstane."""
    monkeypatch.setenv("AGENCY_HOME", str(tmp_path / "home"))

    providers.register("claude", bin="C:/tools/claude.exe")

    spec = providers.spec("claude")
    assert spec["bin"] == "C:/tools/claude.exe"
    assert spec["dirFlag"] == "--add-dir"


# --------------------------------------------------------------------- roster

def test_druhy_pracovnik_nad_toutez_metodou(project):
    a = hires.add(project, "review-graph", provider="claude", model="sonnet")
    b = hires.add(project, "review-graph", provider="codex")

    assert a.id == "review-graph@claude"
    assert b.id == "review-graph@codex"
    assert [h.id for h in hires.for_pack(project, "review-graph")] == [a.id, b.id]
    # Popisek je to, čím se liší — model, když je, jinak runner.
    assert a.label == "sonnet" and b.label == "codex"
    assert a.display("Reviewer") == "Reviewer · sonnet"


def test_dva_stejni_pracovnici_jsou_omyl(project):
    hires.add(project, "review-graph", provider="codex")
    with pytest.raises(SystemExit):
        hires.add(project, "review-graph", provider="codex")

    # Vědomý dvojník projde přes vlastní jméno.
    twin = hires.add(project, "review-graph", provider="codex", hire_id="reviewer-prisny",
                     title="Reviewer (strict)")
    assert twin.id == "reviewer-prisny"


def test_jmeno_se_odvodi_a_nekoliduje(project):
    hires.add(project, "review-graph", provider="claude", model="sonnet")
    druhy = hires.add(project, "review-graph", provider="claude", model="opus")

    assert druhy.id == "review-graph@claude-opus", \
        "druhý hire téhož providera se má odlišit modelem, ne pořadovým číslem"


def test_jmeno_hire_vyhrava_nad_jmenem_packu(project):
    """`review-graph@claude` si nikdo nevymyslí, takže hire s vlastním jménem
    musí být dosažitelný — i kdyby se jmenoval jako pack."""
    hires.add(project, "review-graph", provider="claude", model="sonnet")
    vlastni = hires.add(project, "review-graph", provider="codex", hire_id="review-graph")

    pack, hire = hires.resolve(project, "review-graph")
    assert hire.id == vlastni.id and pack == "review-graph"


def test_jmeno_packu_znamena_jeho_prvniho_pracovnika(project):
    prvni = hires.add(project, "review-graph", provider="claude", model="sonnet")
    hires.add(project, "review-graph", provider="codex")

    pack, hire = hires.resolve(project, "review-graph")
    assert pack == "review-graph" and hire.id == prvni.id


def test_projekt_bez_rosteru_bezi_jako_driv(project):
    """Metoda, kterou nikdo nenainstaloval, nemá ani pracovníka."""
    pack, hire = hires.resolve(project, "review-graph")
    assert pack == "review-graph" and hire is None


def test_starsi_instalace_ma_pracovnika_i_bez_zapisu(project):
    """Pack nainstalovaný dřív, než roster existoval, zápis v `hires.json` nemá.
    Číst to jako „nikdo tu není" by bylo dvakrát špatně: ta metoda tu běhala,
    a panel by uživatele hnal najmout někoho, koho už má."""
    packs.apply(packs.load("qa"), project, packs.plan(packs.load("qa"), project))
    project.save_installed({"version": 1, "packs": {"qa": {"ref": "qa@0.1.0"}}})
    assert hires.load(project) == [], "nic se nesmí zapsat"

    crew = hires.roster(project)

    assert [h.id for h in crew] == ["qa@claude"]
    assert crew[0].implicit is True
    assert crew[0].model == (project.pack_config("qa") or {})["agent"]["model"]
    # Čtení nesmí mít vedlejší efekt.
    assert not (project.agency_dir / "hires.json").exists()

    pack, hire = hires.resolve(project, "qa")
    assert pack == "qa" and hire.id == "qa@claude"


def test_najmuti_druheho_nesmi_smazat_prvniho(project):
    """Nejzrádnější místo celého odvozeného pracovníka: existuje jen tam, kde
    žádný zapsaný není — takže bez zapsání předchůdce by ho přidání kolegy
    smazalo. Přijít o pracovníka, kterého jsi měl, je opak toho, co „najmi
    dalšího" znamená."""
    project.save_installed({"version": 1, "packs": {"review-graph": {"ref": "review-graph@0.1.0"}}})
    assert [h.implicit for h in hires.roster(project)] == [True]

    hires.add(project, "review-graph", provider="codex")

    crew = hires.roster(project)
    assert [h.id for h in crew] == ["review-graph@claude", "review-graph@codex"]
    assert [h.implicit for h in crew] == [False, False], "oba už jsou zapsaní"
    # Pořadí drží: `agency run review-graph` pouští pořád téhož jako dřív.
    assert hires.resolve(project, "review-graph")[1].id == "review-graph@claude"


def test_zapsani_predchudce_neni_duplicita(project):
    """Najmout znovu přesně toho, kdo tu už je, je omyl — a má se to říct."""
    project.save_installed({"version": 1, "packs": {"review-graph": {"ref": "review-graph@0.1.0"}}})
    cfg = project.pack_config("review-graph") or {}
    cfg["agent"] = {"provider": "claude", "model": "sonnet"}
    write_json(project.pack_config_path("review-graph"), cfg)

    with pytest.raises(SystemExit) as e:
        hires.add(project, "review-graph", provider="claude", model="sonnet")
    assert "already runs" in str(e.value)
    # A po odmítnutí zůstane roster tím, čím byl — jen zapsaný.
    assert [h.id for h in hires.roster(project)] == ["review-graph@claude"]


def test_odvozeneho_pracovnika_nejde_vyhodit(project):
    """Není co smazat — a „takový hire tu není" by lhalo o tom, co je v seznamu."""
    project.save_installed({"version": 1, "packs": {"review-graph": {"ref": "review-graph@0.1.0"}}})

    with pytest.raises(SystemExit) as e:
        cli.cmd_fire(SimpleNamespace(repo=str(project.root), json=True,
                                     hire="review-graph@claude"))
    assert "default worker" in str(e.value)


def test_vyhozeni_nechava_metodu_i_behy(project, make_run):
    hires.add(project, "review-graph", provider="claude", model="sonnet")
    run = make_run()

    assert hires.remove(project, "review-graph@claude") is not None
    assert hires.load(project) == []
    assert run.record_path.is_file()
    assert project.pack_config_path("review-graph").is_file()
    assert hires.remove(project, "review-graph@claude") is None


# ------------------------------------------------------------------ spuštění

def test_hire_je_par_provider_a_model(project):
    """Konfigurace má `agent.model: sonnet` pro claude. Hire na codexu ten model
    NESMÍ zdědit — byl by to spouštěcí přepínač, který codex nezná."""
    cfg = {"agent": {"provider": "claude", "model": "sonnet"}}
    codex = hires.Hire(id="x", pack="review-graph", provider="codex", model=None)

    argv, info = runs.launch_argv(cfg, "/run", "P", hire=codex)

    assert info["provider"] == "codex"
    assert info["model"] is None
    assert info["hire"] == "x"
    assert "sonnet" not in argv
    assert argv[0] == "codex"


def test_prepinac_z_prikazu_prebije_hire(project):
    hire = hires.Hire(id="x", pack="review-graph", provider="claude", model="sonnet")

    argv, info = runs.launch_argv({}, "/run", "P", hire=hire, model="opus")
    assert info["model"] == "opus" and "--model" in argv

    # Změna providera odpojí i model — codex se jménem claudeovského modelu
    # by spadl na prvním spuštění.
    argv, info = runs.launch_argv({}, "/run", "P", hire=hire, provider="codex")
    assert info["provider"] == "codex" and info["model"] is None


def test_bez_hire_rozhoduje_konfigurace(project):
    cfg = {"agent": {"provider": "claude", "model": "sonnet", "extraArgs": ["--x"]}}
    argv, info = runs.launch_argv(cfg, "/run", "P")

    assert info == {"provider": "claude", "model": "sonnet", "bin": "claude", "hire": None}
    assert "--add-dir" in argv and "/run" in argv and "--x" in argv
    assert argv[-1] == "P"


def test_dodatecne_argumenty_patri_svemu_providerovi(project):
    """`extraArgs` jsou psané pro jednoho providera. Druhému by mohly nedávat
    smysl — nebo být rovnou chyba."""
    cfg = {"agent": {"provider": "claude", "extraArgs": ["--permission-mode", "acceptEdits"]}}
    codex = hires.Hire(id="x", pack="review-graph", provider="codex")

    argv, _ = runs.launch_argv(cfg, "/run", "P", hire=codex)

    assert "--permission-mode" not in argv


# ----------------------------------------------------------------- paralelně

def test_dva_specialiste_maji_kazdy_svuj_worktree(project):
    """Sdílená cesta by znamenala, že druhý běh smaže worktree prvnímu."""
    cfg = {}
    target = {"pr": 12}
    a = hires.Hire(id="review-graph@claude", pack="review-graph", provider="claude")
    b = hires.Hire(id="review-graph@codex", pack="review-graph", provider="codex")

    assert runs.worktree_path(project, cfg, target, a) \
        != runs.worktree_path(project, cfg, target, b)


def test_stara_sablona_bez_hire_se_stejne_odlisi(project):
    """Konfigurace napsaná dřív, než roster existoval, hire nezná. Odlišit
    cestu je levnější než odmítnout běh."""
    cfg = {"worktree": {"path": "../{repo}-review-pr-{n}"}}
    a = hires.Hire(id="review-graph@claude", pack="review-graph", provider="claude")
    b = hires.Hire(id="review-graph@codex", pack="review-graph", provider="codex")

    assert runs.worktree_path(project, cfg, {"pr": 12}, a) \
        != runs.worktree_path(project, cfg, {"pr": 12}, b)


def test_neznamy_zastupny_symbol_v_sablone_je_chyba(project):
    with pytest.raises(SystemExit):
        runs.worktree_path(project, {"worktree": {"path": "../{neco}"}}, {"pr": 1}, None)


def test_beh_nesmi_prevzit_worktree_bezicimu_behu(project, make_run):
    """Ztráta rozdělané recenze je horší než odmítnutý start."""
    wt = project.root.parent / "obsazeno"
    wt.mkdir()
    bezici = make_run(status="running")
    rec = bezici.record()
    rec["worktree"] = posix(wt)
    bezici.save_record(rec)

    assert runs.worktree_owner(project, wt) == bezici.id
    # Sám sebe za cizího nepovažuje — jinak by běh nemohl svůj adresář vzít.
    assert runs.worktree_owner(project, wt, exclude=bezici.id) is None

    with pytest.raises(SystemExit) as e:
        runs.make_worktree(project, {"worktree": {"path": "../obsazeno"}}, {"pr": 1})
    assert bezici.id[:10] in str(e.value)


def test_dokonceny_beh_worktree_nedrzi(project, make_run):
    wt = project.root.parent / "dokonceno"
    wt.mkdir()
    hotovy = make_run(status="ok")
    rec = hotovy.record()
    rec["worktree"] = posix(wt)
    hotovy.save_record(rec)

    assert runs.worktree_owner(project, wt) is None


def test_marker_nese_jmeno_specialisty(project):
    """Sdílený marker by znamenal, že první specialista druhého z toho commitu
    vyzamkne."""
    head = "a" * 40
    a = runs.review_marker("review-graph", head, "review-graph@claude")
    b = runs.review_marker("review-graph", head, "review-graph@codex")
    assert a != b

    target = {"headRefOid": head, "_comments": [{"body": f"hotovo\n{a}"}]}
    assert runs.already_reviewed(target, "review-graph", "review-graph@claude") is True
    assert runs.already_reviewed(target, "review-graph", "review-graph@codex") is False


def test_stary_marker_bez_hire_se_dal_cte(project):
    """PR odbavené před rosterem musí zůstat idempotentní."""
    head = "b" * 40
    target = {"headRefOid": head,
              "_comments": [{"body": runs.review_marker("review-graph", head)}]}

    assert runs.already_reviewed(target, "review-graph", "review-graph@claude") is True


# --------------------------------------------------------------- sdílená pamět

def test_pamet_je_spolecna_vsem_specialistum(project, make_run):
    """Kdyby si každý pamatoval jen svoje běhy, druhý provider by poctivě
    zopakoval všechno, co první před hodinou vyřešil."""
    starsi = make_run(agent={"provider": "claude", "model": "sonnet",
                             "hire": "review-graph@claude"})
    runs.append_decision(starsi, starsi.findings()[0]["id"], "rejected", reason="by-design")

    novy = make_run(findings=[], agent={"provider": "codex", "hire": "review-graph@codex"})
    stats = runs.known_memory(project, novy)

    known = __import__("json").loads(
        (novy.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))
    assert stats["knownFindings"] == 1
    assert known[0]["hire"] == "review-graph@claude"
    assert known[0]["decision"] == "rejected"
    assert known[0]["reason"] == "by-design", \
        "rozhodnutí je ta nejcennější věta, kterou nový běh dostane na vstupu"


def test_pamet_ma_i_beh_nad_pull_requestem(project, make_run):
    """Sdílená paměť nezávisí na tom, jestli se zkoumá PR, nebo běžící aplikace."""
    make_run()
    novy = make_run(findings=[])

    stats = runs.collect_evidence(project, project.root, novy, {"baseRefOid": None}, [])

    assert stats["knownFindings"] == 1
    assert (novy.dir / "evidence" / "known-findings.json").is_file()


def test_kontext_nese_pracovnika_i_jeho_marker(project, make_run):
    run = make_run()
    hire = hires.Hire(id="review-graph@codex", pack="review-graph", provider="codex")
    target = {"kind": "pull-request", "pr": 7, "headRefOid": "c" * 40}

    runs.write_context(run, {}, target, project.root, [], 0,
                       hire=hire, pack_name="review-graph")

    ctx = __import__("json").loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["hire"]["id"] == "review-graph@codex"
    assert ctx["hire"]["label"] == "codex"
    assert ctx["prCommentMarker"] == runs.review_marker(
        "review-graph", "c" * 40, "review-graph@codex")


def test_beh_nad_projektem_marker_nepotrebuje(project, make_run):
    run = make_run()
    runs.write_context(run, {}, {"kind": "workspace", "headRefOid": "d" * 40},
                       project.root, [], 0, pack_name="qa")
    ctx = __import__("json").loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["prCommentMarker"] is None


# ---------------------------------------------------------------- metriky

def test_duplicita_se_pripise_svemu_specialistovi(project, make_run):
    """Druhý provider, který najde totéž, se označí jako duplicita a do triage
    se nedostane. Bez tohohle by v rozpadu po specialistech vypadal, že nenašel
    nic — a porovnat dva providery by nešlo."""
    prvni = make_run(agent={"provider": "claude", "model": "sonnet",
                            "hire": "review-graph@claude"})
    nalez = prvni.findings()[0]
    runs.append_decision(prvni, nalez["id"], "accepted")

    druhy = make_run(agent={"provider": "codex", "hire": "review-graph@codex"})
    kopie = make_finding(project, druhy.id)
    kopie["state"] = "duplicate"
    kopie["duplicateOf"] = nalez["id"]
    write_json(druhy.findings_path, [kopie])

    r = metrics.collect(project)

    assert r["byHire"]["review-graph@claude"]["accepted"] == 1
    assert r["byHire"]["review-graph@codex"]["accepted"] == 1, \
        "duplicita nese rozhodnutí svého originálu — jinak druhý provider vypadá jako prázdný"
    # Do celkového čísla se ale nezapočítá dvakrát.
    assert r["triage"]["accepted"] == 1
    assert r["agreement"]["crossHire"] == 1
    assert r["agreement"]["sameHire"] == 0


def test_shoda_sama_se_sebou_se_nepocita_jako_shoda_dvou(project, make_run):
    prvni = make_run(agent={"provider": "claude", "hire": "review-graph@claude"})
    nalez = prvni.findings()[0]

    druhy = make_run(agent={"provider": "claude", "hire": "review-graph@claude"})
    kopie = make_finding(project, druhy.id)
    kopie["state"] = "duplicate"
    kopie["duplicateOf"] = nalez["id"]
    write_json(druhy.findings_path, [kopie])

    r = metrics.collect(project)

    assert r["agreement"] == {"crossHire": 0, "sameHire": 1, "hires": 1}


def test_kruh_duplicit_metriky_nezacykli(project, make_run):
    """Ručně upravený findings.json nesmí zavěsit `agency metrics`."""
    run = make_run(findings=[])
    a, b = make_finding(project, run.id), make_finding(project, run.id)
    a.update(state="duplicate", duplicateOf=b["id"])
    b.update(state="duplicate", duplicateOf=a["id"])
    write_json(run.findings_path, [a, b])

    r = metrics.collect(project)
    assert r["triage"]["accepted"] == 0


# -------------------------------------------------------------------- příkazy

def test_instalace_zaloziv_prvniho_pracovnika(project):
    """Projekt nikdy nemá nainstalovanou metodu bez jediného pracovníka."""
    cli.cmd_add(SimpleNamespace(
        repo=str(project.root), json=True, pack="qa", from_path=None,
        dry_run=False, force=False, provider=None, model=None, as_id=None, title=None))

    roster = hires.for_pack(project, "qa")
    assert len(roster) == 1
    assert roster[0].provider == "claude"


def test_najmuti_s_providerem_pridava_dalsiho(project):
    args = dict(repo=str(project.root), json=True, pack="qa", from_path=None,
                dry_run=False, force=False, as_id=None, title=None)
    cli.cmd_add(SimpleNamespace(**args, provider=None, model=None))
    cli.cmd_add(SimpleNamespace(**args, provider="codex", model=None))

    roster = hires.for_pack(project, "qa")
    assert [h.provider for h in roster] == ["claude", "codex"]
    # Model z konfigurace patří claudeovi, ne codexu.
    assert roster[1].model is None


def test_dry_run_nikoho_nenajme(project):
    cli.cmd_add(SimpleNamespace(
        repo=str(project.root), json=True, pack="qa", from_path=None,
        dry_run=True, force=False, provider="codex", model=None, as_id=None, title=None))

    assert hires.load(project) == []


def test_doktor_rekne_ktery_specialista_tu_bezet_nemuze(project, monkeypatch, capsys):
    """Roster cestuje s repozitářem, binárky ne."""
    hires.add(project, "review-graph", provider="claude", model="sonnet")
    hires.add(project, "review-graph", provider="grok", hire_id="reviewer-grok")
    monkeypatch.setattr(providers, "installed",
                        lambda pid: "C:/claude.exe" if pid == "claude" else None)

    cli.cmd_doctor(SimpleNamespace(repo=str(project.root), json=True))
    data = __import__("json").loads(capsys.readouterr().out)

    rows = {c["name"]: c for c in data["checks"]}
    assert rows["hire review-graph@claude"]["ok"] is True
    assert rows["hire reviewer-grok"]["ok"] is False
    # Jeden nedostupný specialista nesmí shodit celý projekt.
    assert rows["hire reviewer-grok"]["fatal"] is False
    assert "agent" not in rows, "dokud aspoň jeden runner je, běh se pustit dá"


def test_roster_bez_jedineho_runneru_je_fatalni(project, monkeypatch, capsys):
    hires.add(project, "review-graph", provider="grok", hire_id="reviewer-grok")
    monkeypatch.setattr(providers, "installed", lambda pid: None)

    cli.cmd_doctor(SimpleNamespace(repo=str(project.root), json=True))
    data = __import__("json").loads(capsys.readouterr().out)

    rows = {c["name"]: c for c in data["checks"]}
    assert rows["agent"]["ok"] is False and rows["agent"]["fatal"] is True


def test_odvozeny_pracovnik_dojde_i_ke_klientovi(project, capsys):
    """Panel u starší instalace nesmí tvrdit „nikdo nenajatý" o metodě, která
    tu běhá — a runner s modelem si musí vzít z její konfigurace."""
    cfg = project.pack_config("review-graph") or {}
    cfg["agent"] = {"provider": "claude", "model": "sonnet"}
    write_json(project.pack_config_path("review-graph"), cfg)
    project.save_installed({"version": 1, "packs": {"review-graph": {"ref": "review-graph@0.1.0"}}})

    cli.cmd_packs(SimpleNamespace(repo=str(project.root), json=True))
    data = {p["name"]: p for p in __import__("json").loads(capsys.readouterr().out)}

    rg = data["review-graph"]["hires"]
    assert [h["id"] for h in rg] == ["review-graph@claude"]
    assert rg[0]["implicit"] is True
    assert rg[0]["display"] == "Reviewer · sonnet"


def test_packs_nese_roster_klientovi(project, capsys):
    hires.add(project, "review-graph", provider="claude", model="sonnet")
    hires.add(project, "review-graph", provider="codex")

    cli.cmd_packs(SimpleNamespace(repo=str(project.root), json=True))
    data = {p["name"]: p for p in __import__("json").loads(capsys.readouterr().out)}

    assert [h["id"] for h in data["review-graph"]["hires"]] == [
        "review-graph@claude", "review-graph@codex"]
    assert data["qa"]["hires"] == []
    assert data["review-graph"]["hires"][0]["display"] == "Reviewer · sonnet"


# ------------------------------------------------------- nedokončené běhy

def test_zabity_terminal_nechava_beh_otevreny(project, make_run):
    """Jádro připraví běh a vypíše příkaz; ten pak běží v terminálu, o kterém
    tenhle proces neví nic. Není co hlídat, takže „běží" znamená to, co je
    v záznamu — a zavřít ho je akt člověka, ne úklidu na pozadí."""
    bezici = make_run(status="running")
    hotovy = make_run(status="ok")

    otevrene = runs.unfinished(project)

    assert [r.id for r in otevrene] == [bezici.id]
    assert hotovy.id not in [r.id for r in otevrene]


def test_zavreny_beh_uvolni_worktree_a_zustane_v_historii(project, make_run, monkeypatch):
    run = make_run(status="running")
    wt = project.root.parent / "worktree-470"
    wt.mkdir()
    write_json(run.dir / "context.json", {"worktree": posix(wt), "worktreeOwned": True})
    rec = run.record()
    rec["worktree"] = posix(wt)
    run.save_record(rec)
    smazano: list = []
    monkeypatch.setattr(runs, "remove_worktree", lambda p, path: smazano.append(path))

    vysledek = runs.abandon(project, run)

    assert vysledek["wasRunning"] is True
    assert smazano == [wt]
    rec = run.record()
    assert rec["status"] == "abandoned"
    assert rec["finishedAt"]
    assert "terminal" in rec["exitReason"]
    # Rezervace cesty k worktree padá s ním — jinak by ji držel běh, který skončil.
    assert "worktree" not in rec
    # Záznam zůstává. Spuštěný běh je fakt a hodina wall clocku bez výsledku
    # je přesně to, co mají čísla o ceně chytat.
    assert run.record_path.is_file()


def test_zavreni_nesahne_na_pracovni_kopii(project, make_run, monkeypatch):
    """Běh bez vlastního worktree jel v repozitáři uživatele."""
    run = make_run(status="running", pack="qa@0.1.0")
    write_json(run.dir / "context.json",
               {"worktree": posix(project.root), "worktreeOwned": False})
    smazano: list = []
    monkeypatch.setattr(runs, "remove_worktree", lambda *a: smazano.append(a))

    runs.abandon(project, run)

    assert smazano == []
    assert (project.root / "src" / "auth.ts").is_file()
    assert run.record()["status"] == "abandoned"


def test_zahozeni_smaze_cely_beh(project, make_run):
    run = make_run(status="running")
    assert run.dir.is_dir()

    vysledek = runs.discard(project, run)

    assert vysledek["findings"] == 1
    assert not run.dir.exists()
    assert runs.find_run(project, run.id) is None


def test_beh_s_rozhodnutim_se_nezahodi(project, make_run):
    """Rozhodnutí je práce, kterou někdo odvedl, a počítá se z něj precision.
    Ztratit ji potichu by pokazilo jediné měření, kvůli kterému tenhle nástroj je."""
    run = make_run(status="running")
    runs.append_decision(run, run.findings()[0]["id"], "accepted")

    with pytest.raises(SystemExit) as e:
        runs.discard(project, run)
    assert "decision" in str(e.value)
    assert run.dir.is_dir()

    # Vědomé zahození projde přes --force.
    runs.discard(project, run, force=True)
    assert not run.dir.exists()


def test_uklid_zavre_vsechny_otevrene(project, make_run, monkeypatch, capsys):
    a = make_run(status="running")
    b = make_run(status="running")
    make_run(status="ok")
    monkeypatch.setattr(runs, "remove_worktree", lambda *args: None)

    cli.cmd_cleanup(SimpleNamespace(repo=str(project.root), json=True, run=None,
                                    unfinished=True, discard=False, force=False))
    data = __import__("json").loads(capsys.readouterr().out)

    assert {c["run"] for c in data["closed"]} == {a.id, b.id}
    assert all(c["action"] == "abandoned" for c in data["closed"])
    assert data["unfinished"] == 0


def test_uklid_bez_otevreneho_behu_nic_nedela(project, make_run, capsys):
    make_run(status="ok")

    cli.cmd_cleanup(SimpleNamespace(repo=str(project.root), json=True, run=None,
                                    unfinished=True, discard=False, force=False))

    assert __import__("json").loads(capsys.readouterr().out)["closed"] == []


def test_uklid_hotoveho_behu_jen_uklidi_worktree(project, make_run, monkeypatch, capsys):
    """Doběhnutý běh se nemá překlopit na „abandoned" jen proto, že se po něm
    uklízí — status je záznam o tom, jak dopadl, ne o tom, co se s ním dělalo."""
    run = make_run(status="ok")
    wt = project.root.parent / "worktree-hotovo"
    wt.mkdir()
    write_json(run.dir / "context.json", {"worktree": posix(wt), "worktreeOwned": True})
    monkeypatch.setattr(runs, "remove_worktree", lambda *args: None)

    cli.cmd_cleanup(SimpleNamespace(repo=str(project.root), json=True, run=run.id,
                                    unfinished=False, discard=False, force=False))
    data = __import__("json").loads(capsys.readouterr().out)

    assert data["closed"][0]["action"] == "cleaned"
    assert run.record()["status"] == "ok"
