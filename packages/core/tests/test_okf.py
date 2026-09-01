"""Koncepty: markdown s frontmatterem, který se čte bez nástroje.

Parser je vlastní, protože frontmatter konceptů je úzká podmnožina YAML a kvůli
deseti řádkům se do jádra netahá závislost. Cena je, že musí být **striktní**:
co nepozná, ohlásí s číslem řádku. Tichý špatný výklad pravidla je horší než
pravidlo, které se nenačte — a tenhle soubor je to, co tu cenu hlídá.
"""

from __future__ import annotations

import pytest

from agency import knowledge, okf

RULE = """---
type: Rule
title: "Sink PR komentáře nesmí spolknout chybu"
status: stable
tags: [area/export, severity/high]
stale_after: 2099-12-01
generated:
  by: human
  at: 2026-09-01T10:00:00Z
verified:
  - by: hire:review-graph@claude
    at: 2026-09-01T12:00:00Z
  - by: human
    at: 2026-09-01T13:00:00Z
sources:
  - resource: CLAUDE.md#rules-that-will-bite-you
---

Když selže zápis do PR komentáře, běh nesmí skončit jako `ok`.
"""


def write_rule(project, name: str, text: str):
    d = project.agency_dir / knowledge.BUNDLE / "rules"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ parser

def test_precte_cely_tvar_konceptu():
    front, body = okf.parse(RULE)

    assert front["type"] == "Rule"
    assert front["tags"] == ["area/export", "severity/high"]
    assert front["generated"] == {"by": "human", "at": "2026-09-01T10:00:00Z"}
    assert [v["by"] for v in front["verified"]] == ["hire:review-graph@claude", "human"]
    assert front["sources"][0]["resource"] == "CLAUDE.md#rules-that-will-bite-you"
    assert body.startswith("Když selže")


def test_dvojtecka_v_hodnote_neni_dalsi_klic():
    """`hire:qa@claude` i URL mají dvojtečku uvnitř hodnoty. Kdyby se dělilo na
    poslední, identita specialisty by se rozpadla na nesmysl."""
    front, _ = okf.parse("---\nresource: agency://project/findings/f_1\n"
                         "by: hire:qa@claude\n---\n")

    assert front["resource"] == "agency://project/findings/f_1"
    assert front["by"] == "hire:qa@claude"


@pytest.mark.parametrize("text,why", [
    ("bez fence\n", "soubor nezačíná `---`"),
    ("---\ntype: Rule\n", "frontmatter se nezavřel"),
    ("---\n  type: Rule\n---\n", "odsazení bez klíče nad ním"),
    ("---\ntype Rule\n---\n", "chybí dvojtečka"),
    ("---\nbody: |\n  víceřádkový text\n---\n", "víceřádkový skalár"),
    ("---\na:\n  b:\n    c: 1\n---\n", "zanoření hlubší než jedna úroveň"),
])
def test_co_parser_nepozna_ohlasi(text, why):
    with pytest.raises(okf.ConceptError):
        okf.parse(text)


def test_chyba_nese_cislo_radku():
    """Bez čísla řádku je hlášení k ničemu — pravidlo se má dát opravit, ne hledat."""
    with pytest.raises(okf.ConceptError, match="line 3"):
        okf.parse("---\ntype: Rule\ntitle bez dvojtečky\n---\n")


def test_neznamy_klic_se_nezahazuje():
    """OKF konzument nesmí odmítnout neznámý klíč — příští verze nějaký přidá."""
    rule = okf.parse("---\ntype: Rule\nattestation: signed-by-someone\n---\n")[0]

    assert rule["attestation"] == "signed-by-someone"


# ------------------------------------------------------------------ zápis

def test_co_se_zapise_se_da_precist():
    """Ledger koncepty generuje a někdo je zase čte. Kdyby se zapisovač
    s parserem rozešel, poznalo by se to až na rozbitém souboru v repu."""
    front = {
        "type": "Finding",
        "title": 'Sink "PR" komentáře: spolkne chybu # a hlásí úspěch',
        "status": "stable",
        "tags": ["pack/review-graph", "severity/high"],
        "generated": {"by": "hire:review-graph@codex", "at": "2026-08-31T21:44:00Z"},
        "verified": [{"by": "hire:review-graph@claude", "at": "2026-09-01T00:00:00Z"}],
        "occurrences": 2,
        "sources": [{"resource": "agency graph impact --depth 2", "note": "3 volající, 0 testů"}],
    }

    back, body = okf.parse(okf.dump(front, "Tělo nálezu."))

    assert back == front, "round-trip musí sedět do posledního klíče"
    assert body == "Tělo nálezu."


@pytest.mark.parametrize("value", [
    'uvozovky "uvnitř" hodnoty',
    "mřížka # po mezeře",
    "dvojtečka: uprostřed",
    "true", "42", "", "  odsazeno  ",
    "zpětné \\ lomítko",
])
def test_hodnota_prezije_zapis_v_puvodnim_tvaru(value):
    """Cokoli, co by parser přečetl jinak, se uzávorkuje. Domýšlet se nesmí
    nic — tichý špatný výklad je horší než hlášená chyba."""
    back, _ = okf.parse(okf.dump({"type": "Rule", "title": value}))

    assert back["title"] == value


def test_polozka_s_carkou_nejde_do_radkoveho_seznamu():
    """V `[a, b]` je čárka oddělovač. Položka, která ji nese, by se rozpůlila
    na dvě — a nikdo by si toho nevšiml, protože obojí je platný seznam."""
    back, _ = okf.parse(okf.dump({"type": "Rule", "tags": ["a, s čárkou", "b"]}))

    assert back["tags"] == ["a, s čárkou", "b"]


def test_klic_bez_hodnoty_se_nepise():
    """`key:` bez obsahu je v podporované podmnožině začátek bloku. Napsat ho
    prázdný znamená vyrobit soubor, který se pak nepřečte."""
    text = okf.dump({"type": "Rule", "stale_after": None, "tags": [], "generated": {}})

    assert text == "---\ntype: Rule\n---\n"


# ------------------------------------------------------------------ čtení

def test_pravidlo_si_nese_jestli_jeste_plati(project):
    write_rule(project, "pr-comment-sink", RULE)
    write_rule(project, "stary", RULE.replace("2099-12-01", "2020-01-01"))

    found = {r["id"]: r for r in knowledge.rules(project)}

    assert found["pr-comment-sink"]["expired"] is False
    assert found["stary"]["expired"] is True, \
        "vypršelé pravidlo se pozná ze souboru, nedopočítává se za běhu"
    assert found["pr-comment-sink"]["path"] == ".agency/knowledge/rules/pr-comment-sink.md"


def test_rozbite_pravidlo_nezmizi_mezi_ostatnimi(project):
    """Kdyby se přeskočilo, dimenze poběží s tichou dírou v zadání a nikdo
    nezjistí proč."""
    write_rule(project, "dobre", RULE)
    write_rule(project, "rozbite", "---\ntype: Rule\nrozbito\n---\n")

    summary = knowledge.rules_summary(project)

    assert summary["total"] == 1
    assert len(summary["broken"]) == 1
    assert "rozbite.md" in summary["broken"][0]["path"]
    assert "line 3" in summary["broken"][0]["error"]


def test_do_behu_jdou_jen_pravidla_ktera_se_daji_precist(project, make_run):
    write_rule(project, "dobre", RULE)
    write_rule(project, "rozbite", "---\ntype: Rule\nrozbito\n---\n")
    run = make_run(findings=[])

    stats = knowledge.for_run(project, run)

    import json
    known = json.loads((run.dir / "evidence" / "known-rules.json").read_text(encoding="utf-8"))
    assert stats["knownRules"] == 1
    assert known[0]["title"].startswith("Sink")
    assert known[0]["body"], "pravidlo bez těla je jen nadpis — dimenze potřebuje obsah"


def test_pamet_o_pravidlech_nepatri_do_grafu(project, make_run):
    """`knownRules` je paměť, ne stav indexu. Do `run.graph` by se nevešlo —
    a přesně takhle se tam předtím dostalo `knownFindings`."""
    from agency import runs as runs_mod

    assert "knownRules" in runs_mod.MEMORY_STATS
