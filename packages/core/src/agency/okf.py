"""Koncepty: adresář markdownu s YAML frontmatterem.

Formát je Open Knowledge Format (Google Cloud, v0.2) — ale je to **konvence,
ne závislost**. Nosná věc je „znalost projektu jako commitované markdown
soubory": čte je libovolný provider, kolega v editoru i holá session bez
Agency. OKF k tomu dodává hotová pole (`type`, `status`, `stale_after`,
`verified`, `sources`), která by se jinak musela vymýšlet. Kdyby v0.3 pole
přejmenovalo, je to mechanická migrace nad odvozeným artefaktem.

**Proč vlastní parser a ne PyYAML.** Frontmatter konceptů je úzká podmnožina
YAML a závislost navíc by se do jádra tahala kvůli deseti řádkům. Cena je, že
parser musí být *striktní*: co nepozná, ohlásí s číslem řádku. Tichý špatný
výklad pravidla je horší než pravidlo, které se nenačte — proto se tady nikdy
nehádá.

Podporovaná podmnožina, celá:

    key: skalár              string (i v uvozovkách), int, true/false, null
    key: [a, b]              seznam skalárů na řádku
    key:                     blok — seznam skalárů
      - a
    key:                     blok — seznam map (jedna úroveň)
      - by: hire:qa@claude
        at: 2026-09-01T10:00:00Z
    key:                     blok — mapa skalárů (jedna úroveň)
      by: human

Kotevní znaky, vícedokumentové soubory, víceřádkové skaláry (`|`, `>`) ani
hlubší zanoření podporované nejsou a hlásí se jako chyba.

Zapisovat umí `dump()` — a bydlí schválně tady, vedle parseru. Ledger nálezů
generuje koncepty, které někdo (i tenhle parser) zase čte; kdyby čtení a psaní
bydlelo každé jinde, rozešly by se a poznalo by se to až na rozbitém souboru.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FENCE = "---"
_INT = re.compile(r"-?\d+$")


class ConceptError(ValueError):
    """Koncept, který nejde přečíst. Nese číslo řádku, ať se dá opravit."""


@dataclass
class Concept:
    id: str
    path: str
    front: dict
    body: str


# ------------------------------------------------------------------ parser

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _scalar(raw: str, line: int):
    v = raw.strip()
    if v[:1] == '"' and v[-1:] == '"' and len(v) >= 2:
        return _unescape(v[1:-1])
    if v[:1] == "'" and v[-1:] == "'" and len(v) >= 2:
        return v[1:-1]
    # Komentář za hodnotou. Jen mimo uvozovky a jen po mezeře — `http://x#y`
    # není komentář a `a#b` taky ne.
    cut = v.find(" #")
    if cut >= 0:
        v = v[:cut].strip()
    low = v.lower()
    if low in ("", "null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT.match(v):
        return int(v)
    if v.startswith(("|", ">", "&", "*")):
        raise ConceptError(f"line {line}: unsupported YAML ({v[0]}) — see okf.py")
    return v


def _flow_list(raw: str, line: int) -> list:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [_scalar(part, line) for part in inner.split(",")]


def _indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" "))


def _pair(raw: str, line: int) -> tuple[str, str]:
    key, sep, rest = raw.partition(":")
    if not sep:
        raise ConceptError(f"line {line}: expected `key: value`")
    return key.strip(), rest.strip()


def _block(lines: list[tuple[int, str]], start: int, base: int) -> tuple[list[tuple[int, str]], int]:
    """Odsazené řádky pod klíčem, a index prvního řádku za nimi."""
    out: list[tuple[int, str]] = []
    i = start
    while i < len(lines):
        num, raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        if _indent(raw) <= base:
            break
        out.append((num, raw))
        i += 1
    return out, i


def _parse_block(block: list[tuple[int, str]]):
    """Blok pod klíčem: seznam skalárů, seznam map, nebo mapa skalárů."""
    if not block:
        return None
    first = block[0][1].strip()

    if first.startswith("- "):
        items: list = []
        current: dict | None = None
        for num, raw in block:
            text = raw.strip()
            if text.startswith("- "):
                text = text[2:].strip()
                if ":" in text:
                    key, value = _pair(text, num)
                    current = {key: _scalar(value, num)}
                    items.append(current)
                else:
                    current = None
                    items.append(_scalar(text, num))
            elif current is not None:
                key, value = _pair(text, num)
                current[key] = _scalar(value, num)
            else:
                raise ConceptError(f"line {num}: continuation of a scalar list item")
        return items

    out: dict = {}
    for num, raw in block:
        key, value = _pair(raw.strip(), num)
        if not value:
            raise ConceptError(f"line {num}: nesting deeper than one level")
        out[key] = _scalar(value, num)
    return out


def parse(text: str) -> tuple[dict, str]:
    """Frontmatter a tělo. Vyhodí `ConceptError`, když soubor není koncept."""
    raw_lines = text.replace("\r\n", "\n").split("\n")
    if not raw_lines or raw_lines[0].strip() != FENCE:
        raise ConceptError("line 1: the file must start with `---`")

    end = next((i for i in range(1, len(raw_lines)) if raw_lines[i].strip() == FENCE), None)
    if end is None:
        raise ConceptError("the frontmatter is never closed with `---`")

    lines = [(i + 1, raw_lines[i]) for i in range(1, end)]
    front: dict = {}
    i = 0
    while i < len(lines):
        num, raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if _indent(raw) > 0:
            raise ConceptError(f"line {num}: unexpected indentation")
        key, value = _pair(raw, num)
        if value.startswith("["):
            front[key] = _flow_list(value, num)
            i += 1
        elif value:
            front[key] = _scalar(value, num)
            i += 1
        else:
            block, i = _block(lines, i + 1, 0)
            front[key] = _parse_block(block)
    return front, "\n".join(raw_lines[end + 1:]).strip()


# ------------------------------------------------------------------ zápis

#: Co se dá napsat bez uvozovek, aniž by to parser přečetl jinak. Dvojtečka
#: uvnitř vadit nemůže (dělí se na první), mřížka po mezeře ano — proto tady
#: není. Cokoli mimo tuhle množinu se uzávorkuje, ne domýšlí.
_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/@:+()-]*$")


def dump_scalar(value) -> str:
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    s = str(value).replace("\n", " ").replace("\r", " ")
    plain = (_PLAIN.match(s) and s == s.strip()
             and s.lower() not in ("true", "false", "null", "~")
             and not _INT.match(s))
    if plain:
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_key(key: str, value) -> list[str]:
    if isinstance(value, dict):
        pairs = [(k, v) for k, v in value.items() if v is not None]
        if not pairs:
            return []
        return [f"{key}:"] + [f"  {k}: {dump_scalar(v)}" for k, v in pairs]

    if isinstance(value, list):
        if not value:
            return []
        if all(isinstance(x, dict) for x in value):
            lines = [f"{key}:"]
            for item in value:
                pairs = [(k, v) for k, v in item.items() if v is not None]
                if not pairs:
                    continue
                lines.append(f"  - {pairs[0][0]}: {dump_scalar(pairs[0][1])}")
                lines += [f"    {k}: {dump_scalar(v)}" for k, v in pairs[1:]]
            return lines if len(lines) > 1 else []
        items = [dump_scalar(x) for x in value]
        # Čárka je v řádkovém seznamu oddělovač, ne obsah — položka, která ji
        # nese, musí jít do bloku, jinak ji čtení rozpůlí na dvě.
        if any("," in x for x in items):
            return [f"{key}:"] + [f"  - {x}" for x in items]
        return [f"{key}: [" + ", ".join(items) + "]"]

    return [f"{key}: {dump_scalar(value)}"]


def dump(front: dict, body: str = "") -> str:
    """Koncept jako text. Klíč bez hodnoty se nepíše — `key:` bez obsahu je
    v podmnožině nahoře zanoření, a psát něco, co se nepřečte, je vada."""
    lines = [FENCE]
    for key, value in front.items():
        if value is not None:
            lines += _dump_key(key, value)
    lines.append(FENCE)
    text = "\n".join(lines) + "\n"
    body = (body or "").strip()
    return f"{text}\n{body}\n" if body else text


# ------------------------------------------------------------------ čtení

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _heading(body: str) -> str | None:
    """První nadpis textu. Stránka psaná před koncepty má jméno uvnitř sebe."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or None
        if line.strip():
            return None
    return None


def read(path: Path, root: Path | None = None, plain_ok: bool = False) -> dict:
    """Jeden koncept jako dict. Rozbitý koncept se ohlásí, nezmizí.

    `plain_ok` je pro adresáře, kde markdown bez frontmatteru dává smysl sám
    o sobě — stránky packů se psaly dřív, než koncepty existovaly, a nazvat
    fungující paměť „rozbitou" by byla nepravda. U pravidel se to nepovoluje:
    pravidlo bez hlavičky neví, jestli ještě platí, a nález na něm nesmí stát.
    """
    rel = str(path if root is None else path.relative_to(root)).replace("\\", "/")
    out: dict = {"id": path.stem, "path": rel}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        out["error"] = str(e)
        return out

    try:
        front, body = parse(text)
        out["frontmatter"] = True
    except ConceptError as e:
        if not (plain_ok and not text.lstrip().startswith(FENCE)):
            # Pravidlo, které se nedá přečíst, nesmí mizet mezi ostatními:
            # dimenze by pak běžela s tichou dírou v zadání a nikdo by nevěděl
            # proč. Rozbitá hlavička je něco jiného než žádná hlavička.
            out["error"] = str(e)
            return out
        front, body = {}, text.strip()
        out["frontmatter"] = False

    stale_after = front.get("stale_after")
    out.update({
        "type": front.get("type"),
        "title": front.get("title") or _heading(body) or path.stem,
        "status": front.get("status") or "stable",
        "tags": front.get("tags") or [],
        "staleAfter": stale_after,
        "expired": bool(stale_after and str(stale_after)[:10] < _today()),
        "generated": front.get("generated"),
        "verified": front.get("verified") or [],
        "sources": front.get("sources") or [],
        "body": body,
    })
    # Neznámé klíče se nezahazují — konzument OKF je odmítat nesmí a příští
    # verze specifikace nějaké přidá.
    for key, value in front.items():
        if key not in ("type", "title", "status", "tags", "stale_after",
                       "generated", "verified", "sources"):
            out.setdefault(key, value)
    return out


def load_dir(directory: Path, kind: str | None = None, root: Path | None = None,
             plain_ok: bool = False) -> list[dict]:
    """Všechny koncepty v adresáři, seřazené podle id. Chybějící adresář = nic."""
    if not directory.is_dir():
        return []
    found = [read(p, root=root, plain_ok=plain_ok) for p in sorted(directory.glob("*.md"))]
    if kind is None:
        return found
    return [c for c in found if c.get("type") == kind or "error" in c]
