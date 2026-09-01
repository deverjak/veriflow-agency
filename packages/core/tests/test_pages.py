"""Stránky packů: kurátorovaná znalost, kterou píše specialista a vlastní projekt.

`docs/plans/tasks.md` Fáze 6. Na rozdíl od ledgeru je nikdo negeneruje — a proto
je tady jiná citlivost než u nálezů: bundle je nesmí přepsat, migrace na
koncepty nesmí prohlásit fungující paměť za rozbitou, a pack, který běží ve
worktree, nesmí dostat cestu, kam by psal do adresáře, co se po běhu smaže.
"""

from __future__ import annotations

import json

from agency import knowledge, okf, runs

PAGE = """---
type: Page
title: "Co je prozkoumané a co ne"
status: stable
stale_after: 2099-12-01
verified:
  - by: hire:qa@claude
    at: 2026-09-01T12:00:00Z
---

Platba kartou prošlá. 3D Secure nezkoušené — sandbox ho neumí.
"""

PLAIN = """# Známé regrese

Košík se vyprázdní po přihlášení. Vrátilo se to podruhé.
"""


def write_page(project, pack: str, name: str, text: str):
    d = knowledge.pages_dir(project, pack)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(text, encoding="utf-8")
    return d / f"{name}.md"


def install(project, pack: str, memory_dir: str | None = None):
    """Pack najatý v projektu — `pages_summary` čte z instalace, ne z disku."""
    from agency.util import write_json
    state = project.installed()
    state.setdefault("packs", {})[pack] = {"version": "0.1.0", "ref": f"{pack}@0.1.0"}
    project.save_installed(state)
    cfg = {"pack": f"{pack}@0.1.0"}
    if memory_dir:
        cfg["memory"] = {"dir": memory_dir}
    write_json(project.agency_dir / f"{pack}.json", cfg)


# ------------------------------------------------------------------ čtení

def test_stranka_si_nese_jestli_zaver_jeste_plati(project):
    install(project, "qa")
    write_page(project, "qa", "coverage", PAGE)
    write_page(project, "qa", "stara", PAGE.replace("2099-12-01", "2020-01-01"))

    found = {p["id"]: p for p in knowledge.pages(project, "qa")}

    assert found["coverage"]["expired"] is False
    assert found["stara"]["expired"] is True
    assert found["coverage"]["verified"][0]["by"] == "hire:qa@claude"
    assert "3D Secure" in found["coverage"]["body"]


def test_stranka_bez_hlavicky_neni_rozbita(project):
    """Paměť se psala dřív, než koncepty existovaly. Prohlásit fungující
    stránku za rozbitou by byla nepravda — a uživatel by šel opravovat něco,
    co funguje."""
    install(project, "qa")
    write_page(project, "qa", "known-regressions", PLAIN)

    page = knowledge.pages(project, "qa")[0]

    assert "error" not in page
    assert page["frontmatter"] is False
    assert page["title"] == "Známé regrese", "jméno si stránka nese v nadpisu"
    assert "Košík" in page["body"]


def test_nedodelana_migrace_je_videt(project):
    """Stránka bez hlavičky se čte dál, ale neví, jestli ještě platí. Je to
    nedokončený přechod, ne chyba — a jako takový má být v přehledu vidět."""
    install(project, "qa")
    write_page(project, "qa", "coverage", PAGE)
    write_page(project, "qa", "known-regressions", PLAIN)

    summary = knowledge.pages_summary(project)

    assert summary["total"] == 2
    assert summary["plain"] == 1
    assert summary["broken"] == []
    assert summary["byPack"] == {"qa": 2}


def test_rozbita_hlavicka_se_hlasi_s_cislem_radku(project):
    """Žádná hlavička a rozbitá hlavička jsou dvě různá tvrzení. Druhé z nich
    znamená, že se někdo o koncept pokusil a nepovedlo se."""
    install(project, "qa")
    write_page(project, "qa", "rozbita", "---\ntype: Page\nrozbito\n---\n")

    summary = knowledge.pages_summary(project)

    assert summary["total"] == 0
    assert len(summary["broken"]) == 1
    assert "line 3" in summary["broken"][0]["error"]


def test_pravidlo_bez_hlavicky_rozbite_zustava(project):
    """Shovívavost platí pro stránky, ne pro pravidla. Pravidlo bez hlavičky
    neví, jestli ještě platí — a nález na něm stavět nelze."""
    d = project.agency_dir / knowledge.BUNDLE / "rules"
    d.mkdir(parents=True, exist_ok=True)
    (d / "bez-hlavicky.md").write_text("# Pravidlo\n\nText.\n", encoding="utf-8")

    assert knowledge.rules_summary(project)["broken"], \
        "pravidlo bez hlavičky se nesmí tvářit jako v pořádku"


# ------------------------------------------------------------------ umístění

def test_projekt_si_pamet_muze_nechat_kde_ji_ma(project):
    """`memory.dir` v konfiguraci vyhrává nad výchozím místem v bundlu. Packy
    si paměť psaly do `.agency/<pack>/` dřív, než bundle vznikl, a konfiguraci
    vlastní projekt — přesouvat ji za zády uživatele se nesmí."""
    install(project, "qa", memory_dir=".agency/qa")

    assert knowledge.pages_dir(project, "qa") == project.root / ".agency" / "qa"

    install(project, "po")
    assert knowledge.pages_dir(project, "po") == \
        project.agency_dir / knowledge.BUNDLE / knowledge.PAGES / "po"


def test_bundle_stranky_neprepise(project, make_run):
    """`findings/` se generuje, `pages/` se píše rukou. Generátor, který maže,
    co nevygeneroval, by první závěr specialisty spolkl."""
    install(project, "qa")
    page = write_page(project, "qa", "coverage", PAGE)
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")

    result = knowledge.bundle(project)

    assert result["removed"] == []
    assert page.read_text(encoding="utf-8") == PAGE


def test_prehled_na_stranky_odkazuje(project, make_run):
    install(project, "qa")
    write_page(project, "qa", "coverage", PAGE)
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    knowledge.bundle(project)

    index = (project.agency_dir / knowledge.BUNDLE / "index.md").read_text(encoding="utf-8")

    assert "## Pages" in index and "### qa" in index
    assert "(pages/qa/coverage.md)" in index
    assert (project.agency_dir / knowledge.BUNDLE / "pages/qa/coverage.md").is_file()


def test_odkaz_vede_i_na_pamet_mimo_bundle(project, make_run):
    """Pack, který si paměť nechal jinde, není chyba — jen se to musí poznat
    a odkaz musí vést tam, kde stránka opravdu je."""
    install(project, "qa", memory_dir=".agency/qa")
    write_page(project, "qa", "coverage", PAGE)
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    knowledge.bundle(project)

    index = (project.agency_dir / knowledge.BUNDLE / "index.md").read_text(encoding="utf-8")

    assert "(../qa/coverage.md)" in index


# ------------------------------------------------------------------ do běhu

def test_stranky_jdou_do_behu_bez_stropu(project, make_run):
    """Vlastní závěry nejsou pozadí, jsou to vstupy. Oříznout je znamená nechat
    specialistu dojít k některému z nich podruhé."""
    install(project, "qa")
    write_page(project, "qa", "coverage", PAGE)
    write_page(project, "qa", "known-regressions", PLAIN)
    run = make_run(findings=[], pack="qa@0.1.0")

    stats = knowledge.for_run(project, run)

    known = json.loads((run.dir / "evidence" / "known-pages.json").read_text(encoding="utf-8"))
    assert stats["knownPages"] == 2
    assert {p["id"] for p in known} == {"coverage", "known-regressions"}


def test_pamet_o_strankach_nepatri_do_grafu(project):
    """Táž past jako u `knownFindings` ve Fázi 0: `run.graph` má v `run.v1`
    zavřený seznam klíčů."""
    assert "knownPages" in runs.MEMORY_STATS


def test_beh_ve_worktree_cestu_ke_strankam_nedostane(project, make_run):
    """Worktree stojí na hlavičce PR a `agency run` ho po sobě smaže. Cesta,
    kam by pack psal závěry, které vzápětí zmizí, je horší než žádná."""
    run = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    target = {"kind": "pull-request", "pr": 1, "headRefOid": "a" * 40}

    runs.write_context(run, {}, target, project.root, [], 0,
                       worktree_owned=True, pack_name="review-graph")
    in_worktree = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))

    runs.write_context(run, {}, target, project.root, [], 0,
                       worktree_owned=False, pack_name="qa")
    in_project = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))

    assert in_worktree["pages"] is None
    assert in_project["pages"].endswith(".agency/knowledge/pages/qa")


def test_stranka_se_da_zapsat_i_precist(project):
    """Specialista stránku píše sám, ale čte ji zpátky jádro. Kdyby zapisovač
    uměl něco, co parser ne, závěr by zmizel při prvním přehledu."""
    install(project, "qa")
    front = {"type": "Page", "title": 'Platby: „karta" prošlá, 3DS ne',
             "status": "stable", "verified": [{"by": "hire:qa@codex", "at": "2026-09-01T00:00:00Z"}]}
    write_page(project, "qa", "coverage", okf.dump(front, "Tělo stránky."))

    page = knowledge.pages(project, "qa")[0]

    assert page["title"] == 'Platby: „karta" prošlá, 3DS ne'
    assert page["verified"][0]["by"] == "hire:qa@codex"
    assert page["body"] == "Tělo stránky."
