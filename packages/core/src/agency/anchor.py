"""Kotva nálezu a test driftu.

Nález najdeš na commitu A a čteš ho o tři týdny později z pracovní kopie, která
je o třicet commitů dál. Číslo řádku už neplatí a NIJAK TO NEPOZNÁ — komentář se
posadí na nevinný kód, ty ho zamítneš, a tím si rozbiješ jedinou metriku, kvůli
které celé měření vzniklo.

Čtyři vrstvy, rozlišuje se shora dolů, zastaví se na první úspěšné. Když selže
všechno, nález se degraduje, neztratí.

Obě opravy, které vypadly ze spiku, jsou tady:
  vrstva 1 se ptá na neměnnost SOUBORU, ne repozitáře,
  vrstva 2 hledá blok, ne jediný řádek.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import proc

_WORDY = re.compile(r"[A-Za-z0-9_]{4}")


@dataclass
class Resolution:
    line: int | None
    via: str
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.line is not None


def distinctive_line(anchor: dict) -> tuple[str, int] | None:
    """Nejcharakterističtější řádek bloku a jeho offset od anchor.line.

    Jednořádkový snippet selže na `/**`, `}` a podobné boilerplatě — a docblock
    začíná přesně tím. Bere se nejdelší řádek, který nese aspoň čtyři
    alfanumerické znaky za sebou.
    """
    block = (anchor.get("snippet") or anchor.get("body") or "").split("\n")
    best: tuple[str, int] | None = None
    for i, raw in enumerate(block):
        t = raw.strip()
        if len(t) < 12 or not _WORDY.search(t):
            continue
        if best is None or len(t) > len(best[0]):
            best = (t, i)
    return best


def resolve(repo: str | Path, anchor: dict) -> Resolution:
    repo = Path(repo)
    rel = anchor["file"]
    abs_path = repo / rel
    if not abs_path.is_file():
        return Resolution(None, "none", "soubor v pracovní kopii neexistuje")

    try:
        lines = abs_path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError as e:
        return Resolution(None, "none", f"soubor nejde přečíst: {e}")
    count = len(lines)
    line = anchor.get("line") or 1

    # 1. soubor se od analýzy nezměnil → čísla řádků platí doslova
    commit = anchor.get("commit")
    if commit and proc.file_unchanged(repo, commit, rel):
        if line <= count:
            return Resolution(line, "exact", "soubor beze změny")
        return Resolution(None, "none", f"řádek {line} je za koncem souboru ({count} řádků)")

    # 2. text bloku → najde posunutý kód
    d = distinctive_line(anchor)
    if d:
        needle, offset = d
        hits = [i + 1 for i, raw in enumerate(lines) if raw.strip() == needle]
        if len(hits) == 1:
            resolved = max(1, hits[0] - offset)
            if resolved == line:
                return Resolution(resolved, "snippet (beze změny)")
            return Resolution(resolved, "snippet", f"posun {line} → {resolved}")
        if len(hits) > 1:
            best = min(hits, key=lambda h: abs(max(1, h - offset) - line))
            return Resolution(max(1, best - offset), "snippet (nejednoznačné)",
                              f"{len(hits)} shod, vybrána nejbližší")

    # 3. symbol z grafu — přežije refaktor tam, kde text řádku ne
    sym = anchor.get("symbol") or {}
    if sym.get("name"):
        r = proc.crg("search", sym["name"], "--repo", str(repo))
        if r.ok:
            for m in re.finditer(rf"{re.escape(rel)}[:\s]+(\d+)", r.stdout):
                return Resolution(int(m.group(1)), "symbol",
                                  f"přes {sym['name']} z grafu")

    # 4. selhání — degraduj, neztrať
    if line > count:
        return Resolution(None, "none", f"řádek {line} je za koncem souboru ({count} řádků)")
    return Resolution(None, "none", "text bloku se v souboru nenašel ani přes symbol")


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ", re.M)


def drift(repo: str | Path, anchor: dict) -> str:
    """`untouched` | `touched` | `deleted` | `unknown`.

    Pozor na výklad: `untouched` znamená, že se na ten ROZSAH nesáhlo — i když
    se soubor jinde přepsal a řádek se posunul. To rozlišení („přepsáno, koukni
    na diff" vs. „platí doslova“) je přesně to, co předtřídí frontu.
    """
    commit = anchor.get("commit")
    if not commit or not proc.commit_exists(repo, commit):
        return "unknown"
    rel = anchor["file"]
    if not (Path(repo) / rel).is_file():
        return "deleted"
    r = proc.git("diff", "-U0", f"{commit}..HEAD", "--", rel, cwd=repo)
    if not r.ok:
        return "unknown"
    if not r.stdout.strip():
        return "untouched"
    start_line = anchor.get("line") or 1
    end_line = anchor.get("endLine") or start_line
    for m in _HUNK.finditer(r.stdout):
        s = int(m.group(1))
        n = 1 if m.group(2) is None else max(int(m.group(2)), 1)
        if s <= end_line and s + n - 1 >= start_line:
            return "touched"
    return "untouched"
