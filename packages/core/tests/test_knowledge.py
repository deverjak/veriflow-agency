"""Paměť je věc, ne vedlejší produkt startu běhu.

Společný základ obou plánů (`docs/plans/tasks.md` Fáze 1): identita `by`,
shrnutí běhu a `knowledge.py` jako jediné místo, kde se skládá „co projekt ví“.
Testy tady hlídají tři vlastnosti, na kterých stojí všechno další — atribuci
(z ní vzniknou tiery ledgeru), strop (pozadí ho má, zadání ne) a to, že se
projekce do běhu nezměnila, i když ji už neskládá `runs.py`.
"""

from __future__ import annotations

import json

import pytest

from agency import hires, knowledge, runs


# ------------------------------------------------------------------ identita

def test_identita_rozlisuje_specialistu_od_cloveka(project, make_run):
    """Rozdíl mezi „jeden model si to myslí“ a „člověk to přijal“ je ten
    nejcennější vstup pro další běh. Jako volný string se ztrácel."""
    run = make_run()
    fid = run.findings()[0]["id"]

    runs.append_decision(run, fid, "accepted", by="hire:po@claude")
    assert runs.decisions(run)[fid]["by"] == "hire:po@claude"

    runs.append_decision(run, fid, "deferred", by="human:kuba")
    assert runs.decisions(run)[fid]["by"] == "human:kuba"


@pytest.mark.parametrize("bad", ["po", "claude", "hire:", "human:", "agent 7", ""])
def test_neznamy_tvar_identity_neprojde(project, make_run, bad):
    """Volný string by znamenal, že se atribuce nedá vážit — a `hire:po` místo
    `hire:po@claude` je přesně ta chyba, kterou nikdo zpětně nepozná."""
    run = make_run()
    fid = run.findings()[0]["id"]

    with pytest.raises(SystemExit):
        runs.append_decision(run, fid, "accepted", by=bad)


def test_stary_zapis_se_cte_jako_clovek(project, make_run):
    """Historie se nepřepisuje, jen vykládá: `cli` i `vscode` byl vždycky
    člověk, jen se to nedalo odlišit od agenta, který `--by` neposlal."""
    assert runs.normalize_by("cli") == "human"
    assert runs.normalize_by("vscode") == "human"
    assert runs.normalize_by("hire:qa@codex") == "hire:qa@codex"


def test_pracovnik_ma_id_i_bez_rosteru(project):
    """Běh bez hire není běh bez pracovníka. Kdyby id vzniklo jen z rosteru,
    „rozhodl specialista“ by v projektu bez rosteru splynulo s „rozhodl člověk“."""
    assert runs.worker_id({}, "legal") == "legal@claude"
    assert runs.worker_id({"agent": {"provider": "codex"}}, "legal") == "legal@codex"
    assert runs.worker_id({}, "legal", provider="codex") == "legal@codex"

    hire = hires.Hire(id="legal@codex", pack="legal", provider="codex")
    assert runs.worker_id({}, "legal", hire=hire) == "legal@codex"


def test_kontext_nese_hotovy_podpis(project, make_run):
    """Identitu skládá jádro. Kdyby ji skládal agent, je to první místo, kde se
    „rozhodl specialista“ změní v „rozhodl někdo“."""
    run = make_run()
    runs.write_context(run, {}, {"kind": "workspace"}, project.root, [], 0,
                       pack_name="legal")

    ctx = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))
    assert ctx["by"] == "hire:legal@claude"
    # A hlavně: je to platný podpis, ne jen řetězec, který vypadá dobře.
    assert runs.validate_by(ctx["by"]) == ctx["by"]


# -------------------------------------------------------------------- paměť

def test_pamet_nese_kdo_rozhodl(project, make_run):
    """Bez atribuce je „codex to našel, claude potvrdil, člověk přijal“ jeden
    string — a přesně z tohohle rozdílu vzniknou tiery ledgeru (Fáze 5)."""
    stary = make_run(agent={"provider": "codex", "hire": "review-graph@codex"})
    fid = stary.findings()[0]["id"]
    runs.append_decision(stary, fid, "rejected", reason="by-design",
                         by="hire:review-graph@claude")

    obraz = knowledge.assemble(project)

    nalez = next(f for f in obraz["findings"] if f["id"] == fid)
    assert nalez["hire"] == "review-graph@codex", "kdo našel"
    assert nalez["decidedBy"] == "hire:review-graph@claude", "kdo rozhodl"
    assert nalez["decision"] == "rejected"


def test_projekce_do_behu_ma_strop_zadani_ne(project, make_run, monkeypatch):
    """Strop patří pozadí. Nález, který se nevejde do pozadí, je nepříjemnost;
    nález, který se nevejde do zadání, je nález, o kterém nikdo nerozhodl."""
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 2)
    stary = make_run(findings=[
        {"id": f"f{i}", "title": f"nález {i}", "anchor": {"file": "src/auth.ts", "line": 2}}
        for i in range(5)
    ])
    novy = make_run(findings=[])

    stats = knowledge.for_run(project, novy)

    ulozeno = json.loads(
        (novy.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))
    assert len(ulozeno) == 2, "do běhu jde jen to, co se vejde"
    assert stats["knownFindings"] == 5, "ale počítá se celá paměť, ne oříznutá"

    zadani = knowledge.upstream(project, [stary.id])
    assert len(zadani["findings"]) == 5, "zadání se neořezává"


def test_upstream_nese_shrnuti_a_poznamky(project, make_run):
    """Zadání pro dalšího v řadě není seznam nálezů — je to i to, co k nim
    předchozí specialista dopsal vlastními slovy."""
    stary = make_run()
    fid = stary.findings()[0]["id"]
    runs.append_note(stary, fid, "ověřeno na produkci, tohle je regrese",
                     by="hire:review-graph@claude")
    (stary.dir / "summary.md").write_text("# Recenze\n\nDva nálezy, jeden sporný.\n",
                                          encoding="utf-8")

    data = knowledge.upstream(project, [stary.id])

    assert data["runs"][0]["summary"].startswith("# Recenze")
    nalez = next(f for f in data["findings"] if f["id"] == fid)
    assert nalez["notes"][0]["text"].startswith("ověřeno")
    assert nalez["notes"][0]["by"] == "hire:review-graph@claude"


def test_pozadi_behu_poznamky_nenese(project, make_run):
    """Poznámka je vlákno diskuse. Do pozadí každého dalšího běhu nepatří —
    tam se počítá s tím, že se čte 300 položek naráz."""
    stary = make_run()
    runs.append_note(stary, stary.findings()[0]["id"], "dlouhá diskuse", by="human")
    novy = make_run(findings=[])

    knowledge.for_run(project, novy)

    ulozeno = json.loads(
        (novy.dir / "evidence" / "known-findings.json").read_text(encoding="utf-8"))
    assert "notes" not in ulozeno[0]


# ------------------------------------------------------------------ shrnutí

def test_shrnuti_behu_se_zaznamena(project, make_run):
    """Jádro shrnutí nevyrábí ani nedopisuje — jen zaznamená, že ho pack napsal.
    Bez toho se z run recordu nepozná, jestli běh po sobě něco nechal."""
    from agency import ingest as ingest_mod

    run = make_run()
    (run.dir / "summary.md").write_text("Prošel jsem platební tok.\n", encoding="utf-8")
    ingest_mod.ingest(project, run)
    assert run.record()["outputs"]["summary"] is True
    assert knowledge.summary(run).startswith("Prošel jsem")

    bez = make_run()
    ingest_mod.ingest(project, bez)
    assert bez.record()["outputs"]["summary"] is False
    assert knowledge.summary(bez) is None
