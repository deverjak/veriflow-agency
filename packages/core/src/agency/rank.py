"""Které nálezy jsou pro tenhle běh relevantní — bez modelu, bez sítě, bez indexu.

Paměť projektu se do běhu předává se stropem (`knowledge.FOR_RUN_FINDINGS`),
protože kontextové okno není nekonečné. Do 1. 9. 2026 ten strop znamenal
„posledních 300": `load_runs` řadí od nejnovějšího ([`runs.py`](runs.py)) a
`for_run` z toho krájel začátek. Nález z jara tedy vypadl, aby se vešlo tři sta
čerstvých malicherností — a to je přesně to tiché zapomínání, kvůli kterému
paměť dostala vlastníka.

Tenhle modul strop nezvedá. Mění **kritérium**: když běh ví, co má dělat,
dostane těch tři sta, které s tím zadáním souvisejí.

**Proč BM25 a ne embeddings.** Vektory znamenají model, model znamená API klíč
nebo GPU, a tím se vrací přesně ta složitost, kvůli které padl Hindsight
adaptér (`docs/plans/shared-memory.md` Krok 5). BM25 je statistika nad slovy —
`math` a `re` ze standardní knihovny, pár stovek dokumentů v jednotkách
milisekund, žádný stav mezi běhy.

Cena je poctivá a je potřeba ji znát: **synonyma tohle neumí**. Dotaz
„payment flow" nenajde nález, který mluví jen o „checkout process". U projektové
paměti je ta mezera menší, než se zdá — dotaz i nálezy mluví slovníkem téhož
repa (cesty k souborům, jména symbolů, dimenze, packy) — ale mezera to je.
Kdyby jednou začala vadit, není odpovědí model v jádře; je jí lepší dotaz.
"""

from __future__ import annotations

import math
import re

#: Ladicí konstanty BM25 v hodnotách, se kterými se publikoval. Neladíme je:
#: bez korpusu, na kterém by se dalo měřit, by to bylo hádání s desetinnými
#: místy.
K1 = 1.5
B = 0.75

#: Hranice slova. Dělí se na nealfanumerických znacích **a** na camelCase, aby
#: `PaymentFlow`, `payment_state_machine` i `src/api/checkout.ts` daly tytéž
#: termíny. Tohle je jediné místo, kde ranker o kódu něco ví — a bez něj by
#: nefungoval, protože zrovna tyhle termíny nesou signál.
_SPLIT = re.compile(r"[^0-9A-Za-z]+|(?<=[a-z0-9])(?=[A-Z])")

#: Termíny kratší než tohle jsou šum (`a`, `to`, `js`) a v kódu jich je hodně.
MIN_LEN = 2


def tokens(text: str | None) -> list[str]:
    """Text na termíny. Prázdný vstup dává prázdný seznam, ne výjimku."""
    if not text:
        return []
    return [t.lower() for t in _SPLIT.split(text) if len(t) >= MIN_LEN]


def scores(query: str, documents: list[str]) -> list[float]:
    """BM25 skóre každého dokumentu proti dotazu. Pořadí odpovídá vstupu.

    Vrací nuly, když se dotaz s ničím nepotkal — volající se pak má vrátit
    k původnímu pořadí, ne předstírat, že nula je odpověď.
    """
    q = set(tokens(query))
    if not q or not documents:
        return [0.0] * len(documents)

    docs = [tokens(d) for d in documents]
    lengths = [len(d) for d in docs]
    avg = (sum(lengths) / len(lengths)) or 1.0
    counts = [_count(d) for d in docs]

    n = len(docs)
    out = [0.0] * n
    for term in q:
        # Kolik dokumentů termín obsahuje. Termín, který je všude (`review`,
        # `test`), tím dostane skóre k nule — o tom je celé IDF a přesně to
        # dělá rozdíl proti prostému počítání shod.
        df = sum(1 for c in counts if term in c)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, c in enumerate(counts):
            f = c.get(term, 0)
            if f:
                out[i] += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * lengths[i] / avg))
    return out


def _count(terms: list[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for t in terms:
        counted[t] = counted.get(t, 0) + 1
    return counted


def top(query: str, items: list, text, limit: int) -> list:
    """Nejrelevantnějších `limit` položek — a když se dotaz nechytil, prvních `limit`.

    Řazení je **stabilní**, což tady není detail implementace, ale rozhodnutí:
    vstupní pořadí je podle stáří (od nejnovějšího), takže dva stejně relevantní
    nálezy si mezi sebou zachovají „novější napřed". Relevance vybírá, stáří
    rozhoduje shody.

    `text` je funkce, která z položky udělá text ke skórování — schválně, aby
    tenhle modul nevěděl nic o tvaru nálezu.
    """
    if not query or len(items) <= limit:
        return items[:limit]
    ranked = scores(query, [text(i) for i in items])
    if not any(ranked):
        # Dotaz se s pamětí nepotkal ani jedním termínem. Řadit podle samých nul
        # by pořadí nezměnilo, ale tvrdilo by to, že proběhl výběr.
        return items[:limit]
    order = sorted(range(len(items)), key=lambda i: -ranked[i])
    return [items[i] for i in order[:limit]]
