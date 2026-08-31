"""Otisk nálezu a dedup napříč běhy.

Proč vůbec: druhý běh nad stejným commitem — nebo běh nad PR, který se od
minula posunul o tři commity — vyrobí většinu týchž nálezů znovu. Bez dedupu
roste fronta rychleji, než ji stíháš odbavovat, a `precision` se počítá
z čísel, ve kterých je tentýž nález třikrát.

Otisk se ZÁMĚRNĚ nepočítá z čísla řádku ani z titulku:

  číslo řádku  se posune při každém commitu nad souborem,
  titulek      se přeformuluje, i když je tvrzení identické.

Počítá se ze SYMBOLU (kde to je) a z podpisu TVRZENÍ (co to říká). Podpis je
množina nejnosnějších slov — přeformulování spojovacího textu ho nezmění,
změna obsahu ano.

Nic z toho není LLM volání. Dedup, který by potřeboval model, by stál víc než
nález, který zahazuje.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Slova, která nesou nulovou informaci o tom, CO nález tvrdí. Česky i anglicky,
# protože nálezy chodí v obou jazycích podle `review.language`.
STOPWORDS = {
    "ktery", "ktera", "ktere", "kteri", "kterou", "kterym", "kterych",
    "protoze", "prototo", "takze", "pritom", "potom", "kdyz", "jenze",
    "tohle", "tento", "tato", "toto", "tyto", "tomu", "toho", "tim",
    "nebo", "ale", "aby", "jako", "jsou", "byla", "bylo", "byly", "bude",
    "budou", "muze", "muzou", "musi", "neni", "nema", "nemaji", "vsak",
    "pouze", "jeste", "uz", "pak", "tak", "tedy", "vzdy", "nikdy", "vsechny",
    "that", "this", "these", "those", "with", "without", "which", "when",
    "then", "than", "from", "into", "will", "would", "should", "could",
    "have", "has", "had", "been", "being", "does", "doesnt", "dont",
    "the", "and", "for", "not", "but", "are", "was", "were", "its",
}

_WORD = re.compile(r"[a-z0-9_]+")
# Bloky kódu jsou citace, ne tvrzení — ty pryč celé.
_FENCE = re.compile(r"```.*?```", re.S)
# Zbytek markdownu nese formu, ne obsah. POZOR: u inline kódu se mažou jen
# zpětné apostrofy, NE obsah — `getUser` je to nejnosnější slovo celého nálezu
# a smazat ho znamená, že dedup pak porovnává spojovací text.
_MD = re.compile(r"[`*_>#|]+|\[([^\]]*)\]\([^)]*\)")


def deaccent(s: str) -> str:
    """Bez diakritiky. `přeteče` a `pretece` je totéž tvrzení."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def tokens(text: str) -> set[str]:
    """Nosná slova textu. Krátká slova a spojky vypadnou — zbyde tvrzení."""
    cleaned = _MD.sub(" ", _FENCE.sub(" ", text or ""))
    words = _WORD.findall(deaccent(cleaned).lower())
    return {w for w in words if len(w) >= 4 and w not in STOPWORDS}


def claim(finding: dict) -> set[str]:
    """Nosná slova TVRZENÍ. Jen `body`, nikdy titulek.

    Titulek přežije korekci diagnózy — obsah ne. Párovat nálezy podle titulku
    je přesně ta chyba, na kterou baseline.md doplatil ručně (§7.2, pravidlo 3).
    """
    return tokens(finding.get("body") or "")


def signature(finding: dict, size: int = 12) -> list[str]:
    """Podpis tvrzení: `size` nejdelších nosných slov, seřazených.

    Nejdelší proto, že v nálezu o kódu jsou to jména symbolů, souborů a domény —
    přesně ta slova, která přeformulování nezmění.
    """
    t = claim(finding)
    return sorted(sorted(t, key=lambda w: (-len(w), w))[:size])


def symbol_key(finding: dict) -> str:
    """Kde nález sedí — symbol, když ho pack zná, jinak soubor.

    Symbol přežije přesun bloku i refaktor uvnitř souboru; soubor je slabší,
    ale pořád nezávislý na čísle řádku.
    """
    a = finding.get("anchor") or {}
    sym = a.get("symbol") or {}
    name = sym.get("name")
    if name:
        return f"sym:{name}"
    return f"file:{a.get('file') or '?'}"


def fingerprint(finding: dict) -> str:
    """Deterministický otisk. Stejný vstup, stejný otisk, na každém stroji."""
    parts = [
        (finding.get("pack") or "").split("@")[0],
        finding.get("dimension") or "",
        symbol_key(finding),
        " ".join(signature(finding)),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def overlap(a: set[str], b: set[str]) -> float:
    """Překryv vzhledem k menší množině, ne Jaccard.

    Jaccard trestá délku: nález rozepsaný na deset řádků a tentýž nález
    shrnutý do tří mají velkou sjednocenou množinu a poctivý překryv se v ní
    utopí. Otázka zní „říká menší z nich totéž, co ta větší?“, a na to
    odpovídá překryv.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# Práh podobnosti a minimální absolutní překryv. Obojí zároveň, protože samotný
# poměr u krátkých nálezů vystřelí — tři shodná slova ze šesti je 0.5, a přitom
# to můžou být dva různé nálezy v téže funkci.
#
# Nesymetrické riziko: falešná duplicita ZAHODÍ práci, zmeškaná duplicita jen
# prodlouží frontu. Proto se práh nastavuje raději přísně.
SIMILARITY = 0.5
MIN_SHARED = 4


def is_duplicate(new: dict, old: dict) -> tuple[bool, str]:
    """Je `new` duplicitou `old`? Vrací i to, čím se to poznalo.

    Dvě vrstvy, každá chytá jiný případ:
      otisk     — tentýž nález z opakovaného běhu, tvrzení slovo od slova
      podobnost — tentýž nález přeformulovaný jiným během nebo jiným modelem
    """
    if new.get("fingerprint") and new["fingerprint"] == old.get("fingerprint"):
        return True, "fingerprint"
    # Bez shody místa se neporovnává vůbec. Dva nálezy o téže věci v různých
    # funkcích jsou dva nálezy.
    if symbol_key(new) != symbol_key(old):
        return False, ""
    a, b = claim(new), claim(old)
    shared = a & b
    score = overlap(a, b)
    if score >= SIMILARITY and len(shared) >= MIN_SHARED:
        return True, f"podobnost {score:.2f} ({len(shared)} slov)"
    return False, ""


def mark_duplicates(new: list[dict], seen: list[dict]) -> list[dict]:
    """Označí duplicity v `new` proti `seen` (starší nálezy) i uvnitř `new`.

    Nález se NEZAHAZUJE — dostane `state: duplicate` a `duplicateOf`. Zahodit
    ho by znamenalo přijít o informaci, že ho pack našel podruhé; a `dedup
    ratio` je metrika, kvůli které se to počítá.
    """
    pool = list(seen)
    marked = []
    for f in new:
        f.setdefault("fingerprint", fingerprint(f))
        hit = None
        for old in pool:
            dup, how = is_duplicate(f, old)
            if dup:
                hit = (old, how)
                break
        if hit:
            old, how = hit
            f["state"] = "duplicate"
            f["duplicateOf"] = old.get("id")
            marked.append({"id": f.get("id"), "duplicateOf": old.get("id"),
                           "runId": old.get("runId"), "how": how,
                           "title": f.get("title")})
        else:
            f.setdefault("state", "candidate")
            pool.append(f)
    return marked
