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

def _scalar(raw: str, line: int):
    v = raw.strip()
    if v[:1] in ('"', "'") and v[-1:] == v[:1] and len(v) >= 2:
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


# ------------------------------------------------------------------ čtení

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def read(path: Path, root: Path | None = None) -> dict:
    """Jeden koncept jako dict. Rozbitý koncept se ohlásí, nezmizí."""
    rel = str(path if root is None else path.relative_to(root)).replace("\\", "/")
    out: dict = {"id": path.stem, "path": rel}
    try:
        front, body = parse(path.read_text(encoding="utf-8"))
    except (ConceptError, OSError) as e:
        # Pravidlo, které se nedá přečíst, nesmí mizet mezi ostatními: dimenze
        # by pak běžela s tichou dírou v zadání a nikdo by nevěděl proč.
        out["error"] = str(e)
        return out

    stale_after = front.get("stale_after")
    out.update({
        "type": front.get("type"),
        "title": front.get("title") or path.stem,
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


def load_dir(directory: Path, kind: str | None = None, root: Path | None = None) -> list[dict]:
    """Všechny koncepty v adresáři, seřazené podle id. Chybějící adresář = nic."""
    if not directory.is_dir():
        return []
    found = [read(p, root=root) for p in sorted(directory.glob("*.md"))]
    if kind is None:
        return found
    return [c for c in found if c.get("type") == kind or "error" in c]
