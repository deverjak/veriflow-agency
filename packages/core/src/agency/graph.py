"""Grafová vrstva — otázky, které recenze klade.

Verby jsou pojmenované podle **otázek**, ne podle příkazů nástroje: obtisk
současného CLI vypadá jako abstrakce a při druhé implementaci praskne. Volající
nikdy nevidí stdout — parsing bydlí tady a ven jde typovaný dict.

Tenhle modul **je** dnes driver `code-review-graph`. Rozdělit ho do `drivers/`
má smysl v den, kdy vzniká druhý soubor; do té doby je registr driverů mrtvý
kód (`docs/plans/graph-abstraction.md`, Krok 3).

Chybějící schopnost není chyba. Dvě z osmi otázek umí dnes jedině CRG
(`unreferenced`, `tests-for`) a každá z nich nese celou dimenzi packu — po
výměně driveru se dimenze přeskočí a zapíše se to, místo aby běh spadl.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import proc
from .util import posix

#: Id driveru. Jde do run recordu, aby po výměně šlo poznat, jestli nálezů
#: ubylo kvůli horšímu nástroji, nebo jen proto, že zmizela schopnost.
DRIVER = "code-review-graph"

DB_PATH = ".code-review-graph/graph.db"

#: Otázky, které klade každá recenze.
CORE = ("state", "refresh", "changes", "impact", "locate", "neighbors")
#: Otázky, které nemá každý nástroj — GitNexus ani Graphify neumí ani jednu.
EXTENDED = ("unreferenced", "tests-for")

#: Jak se index dostane do jednorázového worktree. CRG umí kopii souboru
#: a přírůstkový update; jiný driver bude muset reindexovat nebo přestavět.
WORKSPACE_STRATEGY = "copy-db"

#: Směr v grafu voláním. „Kdo mě volá" je otázka, „callers_of" je příkaz.
DIRECTIONS = {"in": "callers_of", "out": "callees_of"}


@dataclass
class Answer:
    """Odpověď driveru: normalizovaná data, a vedle nich to, co skutečně řekl.

    `data` je kontrakt — na ten se volající smí spolehnout a přežije výměnu
    driveru. `raw` je evidence: ukládá se do běhu, aby šlo dohledat, z čeho
    nález vznikl, a po výměně driveru se změní. Kdyby existovalo jen jedno
    z toho, buď by nešlo vyměnit, nebo by nešlo doložit.
    """
    ok: bool
    data: Any = None
    raw: Any = None
    error: str | None = None


def capabilities() -> list[str]:
    """Co tenhle driver umí. Volající se ptá předem, ne až podle výjimky."""
    return [*CORE, *EXTENDED]


def version() -> str | None:
    return proc.crg_version()


def _fail(r: proc.Result) -> Answer:
    return Answer(False, error=(r.stderr or r.stdout).strip()[:2000] or "no output")


def _parsed(r: proc.Result) -> Answer:
    payload = r.json()
    if payload is None:
        return _fail(r)
    return Answer(True, raw=payload)


def _rel(repo: str | Path, path: str | None) -> str | None:
    """Cesta relativně k repu. Driver vrací absolutní, kotva potřebuje krátkou."""
    if not path:
        return None
    p = Path(path)
    try:
        return posix(p.relative_to(Path(repo)))
    except ValueError:
        return posix(p)


def _node(repo: str | Path, n: dict) -> dict:
    """Uzel grafu tak, jak ho potřebuje volající: kde to je a co to je."""
    return {
        "name": n.get("name"),
        "kind": n.get("kind"),
        "file": _rel(repo, n.get("file_path") or n.get("file")),
        "line": n.get("line_start") or n.get("line"),
        "endLine": n.get("line_end"),
        "isTest": n.get("is_test"),
    }


# ------------------------------------------------------------------- core

def state(repo: str | Path) -> Answer:
    """Stav a čerstvost indexu.

    Chybějící index není chyba — je to odpověď „ještě se nestavěl". Čerstvost
    se pozná porovnáním commitu, na kterém se stavělo, s tím dnešním: index
    z jiné hlavičky umí nález opřít o kód, který na téhle větvi neexistuje.
    """
    db = Path(repo) / DB_PATH
    base = {"driver": DRIVER, "exists": db.is_file(), "path": str(db)}
    if not db.is_file():
        return Answer(True, data=base)

    base["sizeBytes"] = db.stat().st_size
    a = _parsed(proc.crg("status", "--repo", str(repo), "--json"))
    if not a.ok:
        return Answer(True, data=base, error=a.error)

    s = a.raw or {}
    built, current = s.get("built_at_commit"), s.get("current_sha")
    a.data = {
        **base,
        "nodes": s.get("nodes"), "edges": s.get("edges"), "files": s.get("files"),
        "languages": s.get("languages") or [],
        "lastUpdated": s.get("last_updated"),
        "builtAtCommit": built, "currentSha": current,
        "stale": bool(built and current and built != current),
    }
    return a


def refresh(repo: str | Path) -> Answer:
    """Doindexuj pro tenhle běh.

    `build` se tudy nespouští nikdy — přestavěl by celé repo kvůli stavu, který
    se za chvíli zahodí.
    """
    r = proc.crg("update", "--repo", str(repo))
    if not r.ok:
        return _fail(r)
    return Answer(True, data={"action": "update"}, raw=r.stdout.strip()[:2000])


def changes(repo: str | Path, base: str) -> Answer:
    """Co se změnilo proti base — v číslech, ne ve větě.

    `functionsTruncated` je tam proto, že driver seznam ořezává a ten strop
    hlásí ve svém shrnutí jako výsledek; bez příznaku by se do záznamu zapsalo
    „500 změněných funkcí" jako fakt, ne jako dolní odhad.
    """
    a = _parsed(proc.crg("detect-changes", "--repo", str(repo), "--base", base))
    if not a.ok:
        return a
    p = a.raw or {}
    a.data = {
        "functions": len(p.get("changed_functions") or []),
        "functionsTruncated": bool(p.get("functions_truncated")),
        "flows": len(p.get("affected_flows") or []),
        "testGaps": len(p.get("test_gaps") or []),
        "riskScore": p.get("risk_score"),
    }
    return a


def impact(repo: str | Path, files: list[str], depth: int = 2,
           max_results: int = 30) -> Answer:
    """Blast radius: co ještě se těch souborů dotýká."""
    if not files:
        return Answer(True, data={"changedNodes": 0, "impacted": 0, "impactedFiles": 0})
    a = _parsed(proc.crg("impact", "--repo", str(repo), "--files", *files[:40],
                         "--depth", str(depth), "--max-results", str(max_results)))
    if not a.ok:
        return a
    p = a.raw or {}
    a.data = {
        "changedNodes": len(p.get("changed_nodes") or []),
        "impacted": p.get("total_impacted", len(p.get("impacted_nodes") or [])),
        "impactedFiles": len(p.get("impacted_files") or []),
        "truncated": bool(p.get("truncated")),
    }
    return a


def locate(repo: str | Path, symbol: str, kind: str | None = None,
           limit: int = 5) -> Answer:
    """Symbol → `file:line`. Vrstva kotvy, která přežije refaktor."""
    args = ["search", symbol, "--repo", str(repo), "--limit", str(limit)]
    if kind:
        args += ["--kind", kind]
    a = _parsed(proc.crg(*args))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or {}).get("results") or []]
    return a


def neighbors(repo: str | Path, symbol: str, direction: str = "in") -> Answer:
    """Kdo mě volá (`in`), koho volám já (`out`)."""
    pattern = DIRECTIONS.get(direction)
    if pattern is None:
        raise SystemExit(f"Unknown direction “{direction}”. Use in or out.")
    a = _parsed(proc.crg("query", pattern, symbol, "--repo", str(repo)))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or {}).get("results") or []]
    return a


# --------------------------------------------------------------- extended

def unreferenced(repo: str | Path, path_glob: str | None = None,
                 kind: str | None = None, limit: int | None = None) -> Answer:
    """Kód, na který nikdo neukazuje. Na tomhle stojí dimenze `reuse`."""
    args = ["dead-code", "--repo", str(repo), "--json"]
    if limit is not None:
        args += ["--limit", str(limit)]
    if path_glob:
        args += ["--file-pattern", path_glob]
    if kind:
        args += ["--kind", kind]
    a = _parsed(proc.crg(*args))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or [])]
    return a


def tests_for(repo: str | Path, symbol: str) -> Answer:
    """Které testy se toho symbolu týkají. Na tomhle stojí dimenze `tests`."""
    a = _parsed(proc.crg("query", "tests_for", symbol, "--repo", str(repo)))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or {}).get("results") or []]
    return a


# -------------------------------------------------------------- workspace

def prepare(src_db: Path, wt: Path, on_stale: str = "update") -> dict:
    """Dostaň index do jednorázového worktree — strategie `copy-db`.

    Tohle je nejvíc driver-specifická věc v celém modulu: GitNexus drží index
    jinde a jinak, Graphify ho neumí aktualizovat přírůstkově vůbec. Proto to
    není sdílená implementace v `runs.py`, ale strategie driveru.
    """
    info: dict = {"tool": version(), "action": "missing"}
    if not Path(src_db).is_file():
        return info

    dst = Path(wt) / DB_PATH
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_db, dst)

    if on_stale == "ignore":
        info["action"] = "reused"
        return info

    a = refresh(wt)
    info["action"] = "update" if a.ok else "reused"
    if not a.ok:
        info["updateError"] = a.error
    return info
