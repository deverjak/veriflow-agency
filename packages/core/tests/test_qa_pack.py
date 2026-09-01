"""Druhý pack — a tím pádem zkouška, jestli formát packu a `finding.v1` unesou
i něco jiného než recenzi pull requestu.

Krok 5 plánu to říká přesně: kdyby byl QA pack první, navrhl by se formát podle
jednoho příkladu. Tyhle testy jsou ta kontrola druhým tvarem — běh bez pull
requestu, bez worktree, bez grafu a se zadáním od člověka.

Nejdůležitější test v souboru je `test_uklid_nesahne_na_pracovni_kopii`. Běh bez
vlastního worktree jede v pracovní kopii uživatele a `agency cleanup` na ni nesmí
sáhnout ani omylem.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agency import cli, config as agency_config, ingest, packs, runs
from agency.util import posix, write_json

from conftest import git, make_finding


# ------------------------------------------------------------ běhová politika

def test_politika_behu_je_v_manifestu_ne_v_kodu():
    qa = packs.load("qa")
    assert qa.run_policy["target"] == "workspace"
    assert qa.run_policy["worktree"] is False
    # Žádná grafová politika, ne „politika, která říká ne“ — pack, který
    # se grafu nedotkne, po driveru nechce nic.
    assert qa.run_policy["graph"] is None
    assert qa.run_policy["prompt"]["accepts"] is True
    assert qa.run_policy["prompt"]["required"] is True
    assert qa.skill_name == "agency-qa"

    rg = packs.load("review-graph")
    assert rg.run_policy["target"] == "pull-request"
    assert rg.run_policy["worktree"] is True
    # Recenzent vyjmenuje, co po grafu chce: bez `changes` a `impact` nemá běh
    # smysl, bez `unreferenced` a `tests-for` zhasnou dvě dimenze z pěti.
    assert rg.run_policy["graph"]["required"] == ["changes", "impact"]
    assert rg.run_policy["graph"]["optional"] == ["unreferenced", "tests-for"]


def test_pack_bez_bloku_run_zustava_recenzentem():
    """Chybějící pole je výchozí hodnota, ne chyba — starší pack se nerozbije."""
    p = packs.Pack("x", "0.1.0", {"name": "x", "version": "0.1.0"}, Path("."))
    assert p.run_policy["target"] == "pull-request"
    assert p.run_policy["prompt"]["accepts"] is False
    assert p.skill_name is None


def test_instalace_nepridava_dimenzi_kterou_pack_nezna(project):
    """QA žádné `repo-rules` nemá. Detekce pravidel v projektu jí je nesmí
    dopsat do konfigurace — pouštěla by dimenzi, kterou nezná."""
    detected = {"slug": "o/r", "rules": "CLAUDE.md#rules", "docMap": None, "verifyCommand": None}

    qa = packs.load("qa")
    packs.apply(qa, project, packs.plan(qa, project), detected=detected)
    assert "repo-rules" not in (project.pack_config("qa") or {})["review"]["dimensions"]

    # Fixture už jednu konfiguraci recenzenta má; šablona se do existující
    # konfigurace záměrně nezapisuje, ať je instalace opravdu první.
    project.pack_config_path("review-graph").unlink()
    rg = packs.load("review-graph")
    packs.apply(rg, project, packs.plan(rg, project), detected=detected)
    assert "repo-rules" in (project.pack_config("review-graph") or {})["review"]["dimensions"]


# ---------------------------------------------------------------- cíl bez PR

def test_workspace_cil_vidi_rozdelanou_praci(project):
    """Aplikace, kterou QA zkouší, běží nad pracovní kopií — ne nad posledním
    commitem. Nezacommitovaná změna proto do cíle patří."""
    (project.root / "src" / "novy.ts").write_text("export const x = 1\n", encoding="utf-8")

    cil = runs.resolve_workspace_target(project)

    assert cil["kind"] == "workspace"
    assert cil["ref"] == "main"
    assert cil["headRefOid"] == git(project.root, "rev-parse", "HEAD")
    assert len(cil["headRefOid"]) == 40
    assert "src/novy.ts" in cil["_files"]
    assert cil["dirty"] is True


def test_workspace_cil_neuvadi_vlastni_zaznamy(project, make_run):
    """Běh, který se objeví sám v sobě jako změna projektu, je artefakt nástroje."""
    make_run()

    cil = runs.resolve_workspace_target(project)

    assert not any(f.startswith(".agency/") for f in cil["_files"])
    assert not any(f.endswith("/") for f in cil["_files"])


def test_neznamy_zaklad_je_chyba_ne_ticho(project):
    with pytest.raises(SystemExit):
        runs.resolve_workspace_target(project, since="origin/neexistuje")


# ------------------------------------------------------------------- zadání

def test_scenar_a_volny_text_se_skladaji():
    """Volný text scénář nepřepisuje, zpřesňuje ho."""
    cfg = {"brief": {"default": "Rezervační aplikace.", "scenarios": {"smoke": "projdi login"}}}

    b = runs.resolve_brief(cfg, prompt="a na mobilu", scenario="smoke")

    assert b["standing"] == "Rezervační aplikace."
    assert "projdi login" in b["focus"] and "a na mobilu" in b["focus"]
    assert b["source"] == "scenario:smoke+prompt"
    assert b["scenario"] == "smoke"


def test_trvale_zadani_plati_i_bez_prompt():
    b = runs.resolve_brief({"brief": {"default": "Zkoušej hlavně platby."}})
    assert b["focus"] is None
    assert b["standing"] == "Zkoušej hlavně platby."
    assert b["source"] == "config"


def test_nezname_jmeno_scenare_je_chyba():
    with pytest.raises(SystemExit):
        runs.resolve_brief({"brief": {"scenarios": {"smoke": "x"}}}, scenario="neni")


def test_bez_konfigurace_je_zadani_prazdne():
    """Pack, který zadání nebere, nesmí na chybějícím bloku spadnout."""
    b = runs.resolve_brief({})
    assert b == {"standing": None, "focus": None, "scenario": None, "source": None}


# ------------------------------------------------------------------ kontext

def test_kontext_nese_zadani_i_vlastnictvi_worktree(project, make_run):
    run = make_run()
    cfg = {"review": {"minScore": 70, "skipPatterns": ["**/*.lock"]},
           "app": {"baseUrl": "http://localhost:3000"},
           "agent": {"model": "sonnet"}}
    brief = runs.resolve_brief({"brief": {"default": "stálé"}}, prompt="tohle teď")

    runs.write_context(run, cfg, runs.resolve_workspace_target(project), project.root,
                       ["app/booking.js"], 0, brief=brief, worktree_owned=False)

    ctx = run.dir / "context.json"
    data = __import__("json").loads(ctx.read_text(encoding="utf-8"))
    assert data["worktreeOwned"] is False
    assert data["brief"]["focus"] == "tohle teď"
    assert data["brief"]["standing"] == "stálé"
    # Celá konfigurace packu, aby jádro nemuselo znát klíče jednotlivých packů.
    assert data["config"]["app"]["baseUrl"] == "http://localhost:3000"
    assert "agent" not in data["config"]
    # skipPatterns jsou vstup přípravy, ne úkol pro agenta.
    assert "skipPatterns" not in data["review"]


def test_metoda_se_hleda_tam_kde_opravdu_je(project):
    qa = packs.load("qa")

    # Neinstalovaný pack: odkaz cestou. „Use the … skill“ by skončilo na Unknown skill.
    assert "Read the method in" in runs.method_hint(qa, project, [], in_worktree=False)

    packs.apply(qa, project, packs.plan(qa, project))
    assert runs.method_hint(qa, project, [], in_worktree=False) == "Use the agency-qa skill."
    # Ve worktree rozhoduje to, co tam materialize_pack opravdu přenesl.
    assert "Read the method in" in runs.method_hint(qa, project, [], in_worktree=True)


# -------------------------------------------------------------------- brána

def test_qa_nalez_projde_toutez_branou(project, make_run):
    """`finding.v1` není přišitý na recenzenta: nález z běžící aplikace,
    doložený pozorovaným chováním, projde stejnou bránou i kotvou."""
    run = make_run(findings=[], pack="qa@0.1.0",
                   target={"kind": "workspace", "ref": "main",
                           "headRefOid": git(project.root, "rev-parse", "HEAD")})
    f = make_finding(
        project, run.id,
        pack="qa@0.1.0",
        dimension="happy-path",
        title="Rezervace slotu skončí prázdnou stránkou místo potvrzení",
        evidence=[{"kind": "runtime",
                   "detail": "2× zopakováno v čisté session, POST /api/booking → 500",
                   "source": "evidence/booking-500.png"}])
    write_json(run.findings_path, [f])

    vysledek = ingest.ingest(project, run)

    assert vysledek["counts"]["kept"] == 1
    assert vysledek["dropped"] == []


# -------------------------------------------------------------------- úklid

def test_uklid_nesahne_na_pracovni_kopii(project, make_run, monkeypatch):
    """Běh bez vlastního worktree jel v repozitáři uživatele. `agency cleanup`
    na něj nesmí sáhnout — a rozhoduje o tom záznam v kontextu, ne porovnání cest."""
    run = make_run(pack="qa@0.1.0")
    write_json(run.dir / "context.json",
               {"worktree": posix(project.root), "worktreeOwned": False})
    smazano: list = []
    monkeypatch.setattr(runs, "remove_worktree", lambda *a, **k: smazano.append(a))

    cli.cmd_cleanup(SimpleNamespace(repo=str(project.root), json=False, run=run.id))

    assert smazano == []
    assert (project.root / "src" / "auth.ts").is_file()


# ---------------------------------------------------------------- prohlížeč

def _playwright_project(project) -> None:
    """Projekt, který Playwright už má — jeho konfiguraci, jeho adresář, jeho spec."""
    (project.root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\n"
        "export default defineConfig({ testDir: './tests/e2e' });\n", encoding="utf-8")
    d = project.root / "tests" / "e2e"
    d.mkdir(parents=True)
    (d / "home.spec.ts").write_text("test('home', async () => {});\n", encoding="utf-8")
    (project.root / "package.json").write_text(
        '{"devDependencies": {"@playwright/test": "^1.47.0"}}\n', encoding="utf-8")


def test_detekce_najde_playwright_projektu(project):
    """Sezení má psát v dialektu projektu. K tomu musí vědět, kde ten dialekt je."""
    _playwright_project(project)

    pw = agency_config.detect_playwright(project)

    assert pw["present"] is True
    assert pw["configFile"] == "playwright.config.ts"
    assert pw["testDir"] == "tests/e2e"          # z konfigurace, ne z hádání
    assert pw["dependency"] == "^1.47.0"
    assert pw["specs"] == 1


def test_detekce_uhodne_adresar_kdyz_ho_konfigurace_nerekne(project):
    (project.root / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")
    (project.root / "e2e").mkdir()

    pw = agency_config.detect_playwright(project)

    assert pw["configFile"] == "playwright.config.ts"
    assert pw["testDir"] == "e2e"


def test_projekt_bez_playwrightu_ho_nema_zapnuty(project):
    pw = agency_config.detect_playwright(project)
    assert pw["present"] is False
    assert pw["configFile"] is None

    qa = packs.load("qa")
    packs.apply(qa, project, packs.plan(qa, project), detected=agency_config.detect(project))
    assert (project.pack_config("qa") or {})["playwright"]["enabled"] is False


def test_instalace_prevezme_playwright_ktery_uz_v_projektu_je(project):
    """Existující Playwright se má POUŽÍT, ne postavit vedle. Cesty k němu proto
    vyplní instalace — uživatel je nedopisuje do konfigurace, kterou ještě neviděl."""
    _playwright_project(project)

    qa = packs.load("qa")
    packs.apply(qa, project, packs.plan(qa, project), detected=agency_config.detect(project))

    pw = (project.pack_config("qa") or {})["playwright"]
    assert pw["enabled"] is True
    assert pw["configFile"] == "playwright.config.ts"
    assert pw["projectTestDir"] == "tests/e2e"
    # Výchozí zůstává „nic v repozitáři neměnit".
    assert pw["specTarget"] == "run"
    assert pw["scaffold"] == "run-dir"


def test_nastaveni_se_zapisuje_do_konfigurace_projektu(project):
    """Zápis z klienta jde touž cestou jako z terminálu — jinak by byly dvě
    pravdy o jednom nastavení."""
    qa = packs.load("qa")
    packs.apply(qa, project, packs.plan(qa, project))

    cli.cmd_config(SimpleNamespace(
        repo=str(project.root), json=True, pack="qa", unset=None,
        set_pairs=['playwright.enabled=true', 'playwright.browsers=["chromium","webkit"]',
                   'app.baseUrl="http://localhost:3000"', 'playwright.artifacts.video="on"']))

    cfg = project.pack_config("qa") or {}
    assert cfg["playwright"]["enabled"] is True
    assert cfg["playwright"]["browsers"] == ["chromium", "webkit"]
    assert cfg["playwright"]["artifacts"]["video"] == "on"     # tečková cesta jde do hloubky
    assert cfg["app"]["baseUrl"] == "http://localhost:3000"

    cli.cmd_config(SimpleNamespace(repo=str(project.root), json=True, pack="qa",
                                   set_pairs=None, unset=["playwright.browsers"]))
    assert "browsers" not in (project.pack_config("qa") or {})["playwright"]


def test_razitko_instalace_se_z_klienta_neprepisuje(project):
    """`pack` je otisk instalace. Kdyby ho šlo přepsat, konfigurace by tvrdila,
    že patří jiné verzi packu, než která ji vyrobila."""
    qa = packs.load("qa")
    packs.apply(qa, project, packs.plan(qa, project))

    with pytest.raises(SystemExit):
        cli.cmd_config(SimpleNamespace(repo=str(project.root), json=True, pack="qa",
                                       unset=None, set_pairs=['pack="qa@9.9.9"']))


def test_predpoklady_prohlizece_se_kontroluji_predem(project):
    """Selhání Playwrightu přijde uprostřed sezení. Doktor se ptá dřív."""
    rows = dict((name, (ok, detail, fatal))
                for name, ok, detail, fatal in cli._playwright_checks(
                    project, {"enabled": True, "scaffold": "run-dir"}))
    assert rows["playwright"][0] is True            # scaffold to zachrání
    assert rows["playwright"][2] is False

    rows = dict((name, (ok, detail, fatal))
                for name, ok, detail, fatal in cli._playwright_checks(
                    project, {"enabled": True, "scaffold": "never"}))
    assert rows["playwright"][0] is False           # bez scaffoldu a bez instalace ne
    assert rows["playwright"][2] is True


def test_reprodukcni_specy_ze_starsich_behu_jsou_v_kontextu(project, make_run):
    """Spec uložený u nálezu je to, co dělá z otázky „je to opravené?" spuštění
    místo dalšího sezení. Musí se k dalšímu běhu dostat."""
    older = make_run(pack="qa@0.1.0")
    specs = older.dir / "specs"
    specs.mkdir()
    (specs / "rezervace.spec.ts").write_text("// repro\n", encoding="utf-8")

    run = make_run(findings=[], pack="qa@0.1.0")
    target = runs.resolve_workspace_target(project)
    stats = runs.collect_workspace_evidence(project, run, target, [])

    assert stats["knownSpecs"] == 1
    known = __import__("json").loads(
        (run.dir / "evidence" / "known-specs.json").read_text(encoding="utf-8"))
    assert known[0]["path"].endswith("specs/rezervace.spec.ts")
    assert known[0]["runId"] == older.id
