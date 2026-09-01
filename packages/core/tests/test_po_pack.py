"""Čtvrtý pack — a první, který píše VEN.

Recenzent, QA i právník čtou; nejhorší, co se jim může stát, je nález, který
nesedí. Product owner zakládá tickety, komentuje cizí vlákna a přesouvá karty
na cizí nástěnce. Tím se posouvá, co znamená chyba: duplicitní ticket už není
šum v run recordu, je to práce navíc pro člověka, který o něj nežádal.

Testy tady proto hlídají čtyři švy, na kterých ten rozdíl stojí:

  * podpis — nic nesmí odejít ven bez toho, že je to od agenta a kdo to zvrátí;
  * marker a klíč — druhý běh musí poznat, co napsal první;
  * brána `writes.*` — akce, kterou projekt nepovolil, se nesmí stát;
  * ledger — co odešlo ven, leží v repu, ne jen na GitHubu.

Nejdůležitější test v souboru je `test_rozhodnuti_bez_duvodu_neprojde`.
Škrtnutí bez důvodu je přesně ten výstup, kvůli kterému lidi přestanou číst
tickety — a pack, který ho umí vyrobit, je horší než žádný.
"""

from __future__ import annotations

import json

import pytest

from agency import backlog, cli, ingest, packs, runs
from agency.util import write_json

from conftest import git, make_finding


def _cfg(**over) -> dict:
    """Konfigurace packu tak, jak vypadá po instalaci a vyplnění."""
    cfg = {
        "pack": "po@0.1.0",
        "repo": {"slug": "chytre/veriflow"},
        "roadmap": {"file": "docs/roadmap.md", "extra": [], "cycle": "2026-Q3",
                    "cycleEnds": "2026-09-30", "capacity": "1,5 člověka", "goals": []},
        "board": {"projectNumber": 7, "owner": "chytre", "statusField": "Status",
                  "status": {"now": ["Now", "Todo"], "next": ["Next"],
                             "notNow": ["Later", "Icebox"]},
                  "labels": {"now": None, "next": None, "notNow": "not-now",
                             "agent": "agency"}},
        "policy": {"defaultAnswer": "not-now", "requireRoadmapLink": True,
                   "maxOpenNow": 5, "cutIsAComment": True, "escalate": "@kuba"},
        "writes": {"comments": True, "draftIssues": True, "issues": False,
                   "promote": False, "labels": False, "close": False, "dryRun": False},
        "signature": {"name": "Product owner", "note": None, "disclose": True},
        "review": {"minScore": 75, "language": "cs", "dimensions": ["scope"]},
    }
    for key, value in over.items():
        cfg[key] = {**cfg.get(key, {}), **value} if isinstance(value, dict) else value
    return cfg


def _board(cfg: dict, issues=None, items=None) -> backlog.Board:
    """Nástěnka bez sítě. `_issues`/`_items` jsou cache, kterou by jinak
    naplnil `gh` — testy jádra nesmí sahat na cizí GitHub."""
    b = backlog.Board(slug="chytre/veriflow", project_number=7, owner="chytre", cfg=cfg)
    b._issues = issues or []
    b._items = items or []
    return b


# ------------------------------------------------------------ běhová politika

def test_politika_behu_je_v_manifestu_ne_v_kodu():
    po = packs.load("po")

    assert po.run_policy["target"] == "workspace"
    assert po.run_policy["worktree"] is False
    # Žádná grafová politika, ne „politika, která říká ne“ — pack, který
    # se grafu nedotkne, po driveru nechce nic.
    assert po.run_policy["graph"] is None
    # Nový krok přípravy. Fronta se čte deterministicky, aby session nezačínala
    # tím, co jde otestovat bez modelu.
    assert po.run_policy["backlog"] is True
    assert po.run_policy["prompt"]["accepts"] is True
    assert po.run_policy["prompt"]["required"] is False
    assert po.skill_name == "agency-po"


def test_starsi_packy_backlog_nezapinaji():
    """Výchozí hodnota musí být False, jinak by čtvrtý pack rozbil tři starší."""
    for name in ("review-graph", "qa", "legal"):
        assert packs.load(name).run_policy["backlog"] is False


def test_napoveda_k_spusteni_se_odvozuje_z_manifestu():
    assert cli._run_hint(packs.load("po")) == ""


# ------------------------------------------------------------------ instalace

def test_instalace_prinese_metodu_i_recept_na_zapis(project):
    po = packs.load("po")
    packs.apply(po, project, packs.plan(po, project))

    skill = project.root / ".claude" / "skills" / "agency-po"
    assert (skill / "SKILL.md").is_file()
    # Recept na `agency backlog` není příloha: bez něj si pack sáhne po `gh`
    # sám a podpis, marker i brána zůstanou v promptu, kde je nikdo nevymáhá.
    assert (skill / "references" / "backlog.md").is_file()


def test_roadmapa_je_povinna_konfigurace(project):
    """Bez závazků nemá pack čím říct ne — a product owner, který neumí říct
    ne, je generátor ticketů."""
    po = packs.load("po")
    # Slug si instalace domyslí z remote; roadmapu ne — tu musí napsat člověk,
    # a přesně proto je to jediná věc, která po instalaci chybí.
    packs.apply(po, project, packs.plan(po, project), detected={"slug": "chytre/veriflow"})

    cfg = project.pack_config("po") or {}
    assert cfg["repo"]["slug"] == "chytre/veriflow"
    assert cfg["roadmap"]["file"] is None
    assert set(po.manifest["config"]["required"]) == {"repo.slug", "roadmap.file"}
    assert po.manifest["config"]["files"] == ["roadmap.file"]

    chybi = [k for k in po.manifest["config"]["required"] if not cli._dig(cfg, k)]
    assert chybi == ["roadmap.file"]


def test_zapisy_ven_jsou_ve_vychozim_stavu_zavrene(project):
    """Ticket odejde do cizí schránky. Draft a komentář jsou vratné, issue
    a promote ne — proto se zapínají ručně, jedno po druhém."""
    po = packs.load("po")
    packs.apply(po, project, packs.plan(po, project))

    w = (project.pack_config("po") or {})["writes"]
    assert w["comments"] is True and w["draftIssues"] is True
    assert w["issues"] is False and w["promote"] is False
    assert w["close"] is False and w["labels"] is False


# -------------------------------------------------------------------- podpis

def test_podpis_rekne_ze_je_to_agent_i_kdo_ho_zvrati():
    cfg = _cfg()
    text = backlog.signature(cfg, run=None, hire={"provider": "claude", "model": "opus"})

    assert "Product owner" in text
    assert "agent, not a person" in text
    # Odvolání je součást podpisu schválně: agent, který řekne ne a nenapíše,
    # kdo ho přebije, není specialista, ale překážka.
    assert "@kuba" in text
    assert "`opus`" in text


def test_podpis_visi_pod_kazdym_telem_a_marker_je_nahore():
    body = backlog.compose(_cfg(), "Tohle se nestaví.", "referral-programme")

    assert body.startswith("<!-- agency:po:referral-programme -->")
    assert "Tohle se nestaví." in body
    assert "written by an agent" in body
    assert backlog.marker_in(body) == "referral-programme"


def test_klic_je_odvozeny_z_titulku_a_stabilni():
    """Náhodné id by bylo unikátní a k ničemu: pointa je, že DRUHÝ běh pozná,
    co napsal první."""
    a = backlog.key_for("Referral programme, phase 1")
    assert a == backlog.key_for("Referral programme, phase 1")
    assert a == "referral-programme-phase-1"
    assert backlog.key_for("") == "item"
    assert len(backlog.key_for("x" * 300)) <= 64


# ------------------------------------------------------------------ idempotence

def test_uz_zalozeny_ticket_se_nezalozi_podruhe():
    cfg = _cfg(writes={"issues": True})
    b = _board(cfg, issues=[{
        "number": 41, "title": "Referral programme", "state": "OPEN",
        "url": "https://github.com/chytre/veriflow/issues/41",
        "body": backlog.compose(cfg, "…", "referral-programme"),
    }])

    res = backlog.create_issue(b, cfg, "Referral programme", "…", "referral-programme")

    assert res["action"] == "exists"
    assert res["number"] == 41


def test_draft_se_pozna_podle_toho_ze_nema_cislo():
    """Typ z `gh` se může přejmenovat; číslo má issue i pull request, draft ne."""
    assert backlog._is_draft({"content": {"title": "nápad"}}) is True
    assert backlog._is_draft({"content": {"type": "DraftIssue"}}) is True
    assert backlog._is_draft({"content": {"type": "Issue", "number": 3}}) is False


def test_snapshot_nese_klice_at_vi_dalsi_beh_co_uz_je_napsane():
    cfg = _cfg()
    b = _board(
        cfg,
        issues=[{"number": 41, "title": "Referral", "state": "OPEN", "labels": [],
                 "body": backlog.compose(cfg, "…", "referral")},
                {"number": 12, "title": "Staré", "state": "CLOSED", "labels": [],
                 "body": backlog.compose(cfg, "…", "stare")}],
        items=[{"id": "PVTI_a", "title": "Nápad",
                "content": {"title": "Nápad", "body": backlog.compose(cfg, "…", "napad")}}],
    )

    snap = backlog.snapshot(b, cfg)

    # Snapshot ukazuje otevřené — zavřený ticket na frontě nikoho netlačí.
    assert snap["issues"] == 1 and snap["drafts"] == 1
    assert {r["agencyKey"] for r in snap["items"]} == {"referral", "napad"}


# ------------------------------------------------------------------- brána

def test_brana_zapisu_rekne_ktery_prepinac_chybi():
    ok, why = backlog.allowed(_cfg(), "issue")

    assert ok is False
    # „Nesmíš" bez cesty dál je totéž co pád, jen tišší.
    assert "writes.issues" in why
    assert "agency config po --set writes.issues=true" in why


def test_brana_pousti_to_co_projekt_povolil():
    assert backlog.allowed(_cfg(), "comment")[0] is True
    assert backlog.allowed(_cfg(), "draft")[0] is True
    assert backlog.allowed(_cfg(), "promote")[0] is False


def test_zkouska_nanecisto_ukaze_telo_a_nic_neposle(monkeypatch):
    cfg = _cfg(writes={"draftIssues": True})
    b = _board(cfg)
    monkeypatch.setattr(backlog.proc, "gh",
                        lambda *a, **k: pytest.fail("dry-run sáhl na gh"))

    res = backlog.create_draft(b, cfg, "Referral", "Proč to chceme.", "referral",
                               dry_run=True)

    assert res["action"] == "would-create"
    assert "written by an agent" in res["body"]


def test_globalni_nanecisto_z_konfigurace_platí_i_bez_prepinace():
    assert backlog.is_rehearsal(_cfg(writes={"dryRun": True})) is True
    assert backlog.is_rehearsal(_cfg()) is False


# --------------------------------------------------------------- rozhodnutí

def test_rozhodnuti_bez_duvodu_neprojde(project):
    """Škrtnutí bez důvodu je ten výstup, kvůli kterému lidi přestanou číst
    tickety. Stojí jednu větu a je to celá hodnota téhle role."""
    with pytest.raises(SystemExit) as e:
        cli.main(["backlog", "decide", "41", "not-now", "--repo", str(project.root)])

    assert "--because" in str(e.value)


def test_rozhodnuti_bez_volby_neprojde(project):
    with pytest.raises(SystemExit) as e:
        cli.main(["backlog", "decide", "41", "--because", "nic to nekryje",
                  "--repo", str(project.root)])

    assert "not-now" in str(e.value)


def test_telo_rozhodnuti_pojmenuje_zavazek_i_kdyz_zadny_neni():
    cfg = _cfg()

    kryte = backlog.decision_body(cfg, "now", "Kryje to onboarding.",
                                  commitment="docs/roadmap.md#L18")
    nekryte = backlog.decision_body(cfg, "not-now", "Nikdo si to neobjednal.")

    assert "docs/roadmap.md#L18" in kryte
    assert "2026-Q3 (ends 2026-09-30)" in kryte
    # Nekryté se nesmí tvářit, že závazek má — a musí říct, kdy se to vrátí.
    assert "none — nothing in the roadmap covers this" in nekryte
    assert "Revisit" in nekryte


def test_sloupec_se_hleda_jmenem_a_chybejici_se_nevymysli(monkeypatch):
    cfg = _cfg(writes={"labels": True})
    b = _board(cfg)
    b._meta = {"id": "PVT_1", "fields": {"Status": {
        "id": "F1", "name": "Status",
        "options": [{"id": "o1", "name": "Todo"}, {"id": "o2", "name": "Icebox"}]}}}
    posláno: list = []
    monkeypatch.setattr(backlog.proc, "gh",
                        lambda *a, **k: (posláno.append(a), __import__("agency.proc",
                                         fromlist=["Result"]).Result(True, 0, "{}", ""))[1])

    # `now` má kandidáty Now, Todo — nástěnka zná jen Todo, a to je správná volba.
    assert backlog.set_status(b, cfg, {"item": "PVTI_a"}, "now")["to"] == "Todo"
    # `next` má jediného kandidáta Next, ten na nástěnce není. Nevymýšlí se.
    přeskočeno = backlog.set_status(b, cfg, {"item": "PVTI_a"}, "next")
    assert přeskočeno["action"] == "skipped" and "Next" in přeskočeno["why"]


def test_stitky_z_konfigurace_se_pridaji_k_rozhodnuti():
    cfg = _cfg()

    assert backlog._labels(cfg, None, decision="not-now") == ["not-now", "agency"]
    # Štítek agenta visí na všem, i když rozhodnutí vlastní štítek nemá.
    assert backlog._labels(cfg, None, decision="now") == ["agency"]
    assert backlog._labels(cfg, ["bug", "agency"], decision="now") == ["bug", "agency"]


# --------------------------------------------------------------------- ledger

def test_ledger_lezi_v_behu_a_je_append_only(project, make_run):
    run = make_run(findings=[], pack="po@0.1.0")

    backlog.append(run, {"kind": "draft", "key": "a", "action": "created"})
    backlog.append(run, {"kind": "decide", "key": "b", "decision": "not-now"})

    rows = backlog.ledger(run)
    assert [r["kind"] for r in rows] == ["draft", "decide"]
    assert all(r["at"] for r in rows)
    # Leží to v repu, ne na GitHubu: co pack rozhodl, přežije smazaný ticket.
    assert (run.dir / "backlog.jsonl").is_file()


def test_zapis_bez_behu_se_nezahodi_ani_nespadne():
    """`agency backlog` jde volat i mimo běh. Bez ledgeru, ale bez pádu."""
    ev = backlog.append(None, {"kind": "comment", "key": "a"})

    assert ev["kind"] == "comment" and ev["at"]


# ------------------------------------------------------------------- evidence

def test_evidence_zmrazi_roadmapu_i_kdyz_frontu_precist_nejde(project, make_run):
    """Rozhodnutí je přezkoumatelné jen proti znění, ze kterého vzniklo.
    Nedostupná fronta je věc, kterou má běh říct — ne důvod přijít o závazky."""
    (project.root / "docs").mkdir()
    (project.root / "docs" / "roadmap.md").write_text(
        "# Roadmapa 2026-Q3\n\n- první rezervace do pěti minut\n", encoding="utf-8")

    run = make_run(findings=[], pack="po@0.1.0")
    cfg = _cfg(repo={"slug": None})       # bez remote se nástěnka nesestaví
    cfg["repo"] = {"slug": None}
    stats = runs.collect_backlog_evidence(project, run, cfg)

    assert stats["roadmapFiles"] == 1
    assert (run.dir / "evidence" / "roadmap" / "docs" / "roadmap.md").is_file()
    assert "backlogError" in stats


def test_chybejici_roadmapa_beh_nezabije_ale_rekne_se(project, make_run):
    run = make_run(findings=[], pack="po@0.1.0")
    cfg = _cfg()
    cfg["repo"] = {"slug": None}

    stats = runs.collect_backlog_evidence(project, run, cfg)

    assert stats["roadmapFiles"] == 0
    assert stats["roadmapMissing"] == ["docs/roadmap.md"]


# ---------------------------------------------------------------------- brána

def test_produktovy_nalez_projde_toutez_branou(project, make_run):
    """`finding.v1` neunese jen kód a předpis, ale i závazek: nález kotvený na
    řádek roadmapy projde stejnou bránou jako nález z grafu."""
    (project.root / "docs").mkdir()
    road = project.root / "docs" / "roadmap.md"
    road.write_text(
        "# Roadmapa 2026-Q3\n"
        "\n"
        "## Závazky\n"
        "- první rezervace do pěti minut od registrace\n", encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "roadmapa")

    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[], pack="po@0.1.0",
                   target={"kind": "workspace", "ref": "main", "headRefOid": commit})
    f = make_finding(
        project, run.id, pack="po@0.1.0", dimension="roadmap-drift", severity="medium",
        title="Závazek na první rezervaci nenese žádný ticket ani rozdělaná práce",
        body=("Roadmapa slibuje první rezervaci do pěti minut. Na nástěnce k tomu "
              "není otevřený ticket ani draft a poslední commity míří jinam."),
        evidence=[{"kind": "doc", "detail": "roadmap 2026-Q3, závazek na první rezervaci",
                   "source": "docs/roadmap.md#L4"}],
        score=82,
        anchor={"file": "docs/roadmap.md", "line": 4, "endLine": 4, "commit": commit,
                "snippet": "- první rezervace do pěti minut od registrace",
                "symbol": None, "body": None})
    write_json(run.findings_path, [f])
    write_json(project.agency_dir / "po.json", _cfg())

    res = ingest.ingest(project, run)

    assert res["kept"] == 1
    assert res["dropped"] == []


def test_nalez_na_neexistujici_zavazek_brana_zahodi(project, make_run):
    """Halucinovaný řádek roadmapy je táž chyba jako halucinovaný soubor —
    a pozná se bez modelu."""
    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[], pack="po@0.1.0",
                   target={"kind": "workspace", "ref": "main", "headRefOid": commit})
    f = make_finding(project, run.id, pack="po@0.1.0", dimension="roadmap-drift",
                     anchor={"file": "docs/roadmap.md", "line": 4})
    write_json(run.findings_path, [f])
    write_json(project.agency_dir / "po.json", _cfg())

    res = ingest.ingest(project, run)

    assert res["kept"] == 0
    assert res["dropped"][0]["reason"] == "phantom-file"


# ------------------------------------------------------------------ CLI brána

def test_cli_odmitne_zapis_ktery_projekt_nepovolil(project, capsys):
    write_json(project.agency_dir / "po.json", _cfg())

    kod = cli.main(["backlog", "issue", "--title", "Referral programme",
                    "--body", "…", "--repo", str(project.root), "--json"])

    assert kod == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["reason"] == "write-gate"
    assert "writes.issues" in data["message"]


def test_cli_chce_titul_drive_nez_sit(project):
    write_json(project.agency_dir / "po.json", _cfg())

    with pytest.raises(SystemExit) as e:
        cli.main(["backlog", "draft", "--body", "…", "--repo", str(project.root)])

    assert "--title" in str(e.value)


def test_klic_komentare_odlisi_dva_ruzne_texty_se_stejnym_zacatkem():
    """Prefix z prvního řádku by kolidoval v tom nebezpečném směru: druhý,
    jiný komentář by se tiše zahodil jako „už napsáno“."""
    a = backlog.key_for_text("Nestaví se to teď.\nProtože kapacita.")
    b = backlog.key_for_text("Nestaví se to teď.\nProtože to nikdo nechce.")

    assert a != b
    assert a == backlog.key_for_text("Nestaví se to teď.\nProtože kapacita.")
    # Klíč musí projít markerem, jinak ho druhý běh nenajde.
    assert backlog.marker_in(backlog.MARKER.format(key=a)) == a
