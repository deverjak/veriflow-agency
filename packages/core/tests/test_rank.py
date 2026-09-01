"""Strop paměti vybírá podle relevance, ne podle stáří.

`docs/plans/tasks.md` Fáze 7. Původní verze téhle vrstvy byl adaptér cizího
démona; zamítnutá je proto, že si démon volá vlastní LLM, takže „lokální“
neznamenalo „nikam to nejde“ (`docs/plans/shared-memory.md` Krok 5). Zůstala
potřeba „seřaď mi, co mám“ — a na tu stačí statistika nad slovy.

Testy hlídají čtyři vlastnosti, na kterých to stojí: že se ranking vůbec chytí
na slovníku kódu (camelCase a cesty), že častý termín neváží jako vzácný, že
běh bez zadání dostane pořadí podle stáří, a že se strop nezvedl — mění se jen
kritérium výběru.
"""

from __future__ import annotations

import json

from agency import knowledge, rank


# ------------------------------------------------------------------ tokenizace

def test_slovnik_kodu_se_rozpadne_na_termíny():
    """Naivní `split()` by tyhle tři zápisy považoval za tři různá slova. Jenže
    zrovna ony nesou signál — jméno symbolu, cesta a snake_case jsou to, čím se
    nález odlišuje od jiného nálezu ve stejné dimenzi."""
    assert rank.tokens("PaymentFlow") == ["payment", "flow"]
    assert rank.tokens("payment_state_machine") == ["payment", "state", "machine"]
    assert rank.tokens("src/api/checkout.ts") == ["src", "api", "checkout", "ts"]


def test_jednopismenne_termíny_vypadnou():
    """`a`, `v`, `js` — v kódu jich je hodně a neodlišují nic."""
    assert rank.tokens("a payment v flow") == ["payment", "flow"]


def test_prazdny_vstup_neni_vyjimka():
    assert rank.tokens(None) == []
    assert rank.tokens("") == []
    assert rank.scores("cokoli", []) == []


# ------------------------------------------------------------------ skóre

def test_vzacny_termin_vazi_vic_nez_castý():
    """O tomhle je celé IDF a je to ten rozdíl proti prostému počítání shod:
    `review` má v paměti recenzenta každý nález, `reconsent` jeden."""
    docs = ["review reconsent banner", "review checkout total", "review login form"]
    got = rank.scores("review reconsent", docs)
    assert got[0] > got[1] and got[0] > got[2]

    # Samotný `review` je ve všech třech, takže nerozlišuje — skóre jsou si rovna.
    same = rank.scores("review", docs)
    assert len(set(round(s, 6) for s in same)) == 1


def test_dotaz_mimo_slovnik_da_same_nuly():
    """Nula není odpověď „nejmíň relevantní“, je to „nepotkalo se to“. Volající
    se podle toho musí umět vrátit k původnímu pořadí."""
    assert rank.scores("kterak arcibiskup", ["payment flow", "checkout"]) == [0.0, 0.0]


def test_delsi_dokument_nevyhrava_jen_delkou():
    """Bez normalizace na délku by vyhrával nález s dlouhým popisem, ne ten
    relevantní — a popisy si specialisté píšou různě dlouhé."""
    short = "checkout total"
    long = "checkout " + " ".join(f"slovo{i}" for i in range(200))
    got = rank.scores("checkout", [short, long])
    assert got[0] > got[1]


# ------------------------------------------------------------------ výběr

def test_pod_stropem_se_neradi_vubec():
    """Když se vejde všechno, je řazení jen zamíchání pořadí, které něco znamená
    (od nejnovějšího). Levné to je, ale nese to falešné tvrzení, že se vybíralo."""
    items = ["checkout", "payment", "login"]
    assert rank.top("checkout", items, lambda s: s, 5) == items


def test_bez_dotazu_zustava_poradi_podle_stari():
    """Běh bez `--prompt` a bez cíle nemá dotaz. Vymýšlet ho z ničeho by znamenalo
    řadit podle šumu — a to je horší než řadit podle času."""
    items = ["nejnovejsi", "starsi", "nejstarsi"]
    assert rank.top("", items, lambda s: s, 2) == ["nejnovejsi", "starsi"]


def test_dotaz_mimo_slovnik_nechá_poradi_byt():
    items = ["nejnovejsi checkout", "starsi payment", "nejstarsi login"]
    assert rank.top("kterak arcibiskup", items, lambda s: s, 2) == items[:2]


def test_shoda_skore_si_drzi_novejsi_napred():
    """Relevance vybírá, stáří rozhoduje shody. Kdyby řazení nebylo stabilní,
    dva stejně relevantní nálezy by se prohazovaly mezi běhy bez příčiny."""
    items = ["a checkout", "b checkout", "c checkout"]
    assert rank.top("checkout", items, lambda s: s, 2) == ["a checkout", "b checkout"]


# ------------------------------------------------------- projekce do běhu

def test_dotaz_se_sklada_ze_zadani_a_cile():
    got = knowledge.query_for("qa", {"focus": "reconsent banner"},
                              {"title": "Fix checkout totals"})
    assert "reconsent banner" in got and "Fix checkout totals" in got and "qa" in got


def test_dotaz_bez_niceho_je_prazdny():
    """Prázdný dotaz je platný stav, ne chyba — znamená „řaď podle stáří“."""
    assert knowledge.query_for(None, None, None) == ""
    assert knowledge.query_for(None, {"focus": None}, {"title": None}) == ""


def test_strop_vybira_relevantni_misto_nejnovejsich(project, make_run, monkeypatch):
    """Jádro celé Fáze 7. Nález o reconsentu je nejstarší ze všech, takže by pod
    původním „posledních N“ vypadl — a běh, který se ptá zrovna na reconsent, by
    ho nedostal."""
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 3)

    from conftest import make_finding
    rid = "00000000000000000000000001"
    make_run(run_id=rid, findings=[
        make_finding(project, rid, title="Reconsent banner se nezobrazí po expiraci")])

    for i in range(2, 8):
        make_run(run_id=f"0000000000000000000000000{i}")

    current = make_run(run_id="00000000000000000000000009")
    knowledge.for_run(project, current, query="reconsent banner")

    picked = json.loads((current.dir / "evidence" / "known-findings.json").read_text())
    assert len(picked) == 3
    assert any("Reconsent" in f["title"] for f in picked), \
        "nejstarší, ale jediný relevantní nález ve výběru chybí"


def test_bez_dotazu_projekce_zustava_jaka_byla(project, make_run, monkeypatch):
    """Zpětná kompatibilita: pack, který dosud dostával posledních N, je dostává
    dál. Ranker nemění kontrakt, mění kritérium — a jen když je podle čeho."""
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 2)
    for i in range(1, 6):
        make_run(run_id=f"0000000000000000000000000{i}")
    current = make_run(run_id="00000000000000000000000009")

    stats = knowledge.for_run(project, current)
    picked = json.loads((current.dir / "evidence" / "known-findings.json").read_text())

    assert len(picked) == 2
    assert [f["runId"] for f in picked] == ["00000000000000000000000005",
                                            "00000000000000000000000004"]
    assert "knownFindingsQuery" not in stats


def test_zaznam_rekne_podle_ceho_se_vybiralo(project, make_run, monkeypatch):
    """Bez toho se po čase nedá říct, jestli nález ve vstupu chyběl kvůli stropu,
    nebo kvůli dotazu."""
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 2)
    for i in range(1, 6):
        make_run(run_id=f"0000000000000000000000000{i}")
    current = make_run(run_id="00000000000000000000000009")

    stats = knowledge.for_run(project, current, query="reconsent banner")
    assert stats["knownFindingsQuery"] == "reconsent banner"

    # Pod stropem se nevybíralo, takže se nemá co zaznamenávat.
    monkeypatch.setattr(knowledge, "FOR_RUN_FINDINGS", 300)
    assert "knownFindingsQuery" not in knowledge.for_run(project, current, query="x")
