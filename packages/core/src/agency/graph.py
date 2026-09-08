"""The graph layer — the questions a review asks.

The verbs are named after the **questions**, not after the tool's commands: an
imprint of the current CLI looks like an abstraction and breaks on the second
implementation. The caller never sees stdout — parsing lives here and a typed
dict goes out.

Today this module **is** the `code-review-graph` driver. Splitting it into
`drivers/` makes sense on the day a second file appears; until then a driver
registry is dead code (`docs/plans/graph-abstraction.md`, Step 3).

A missing capability is not an error. Two of the eight questions are answered
today only by CRG (`unreferenced`, `tests-for`) and each carries a whole pack
dimension — after a driver swap the dimension is skipped and that is recorded,
instead of the run falling over.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import proc
from .util import posix

#: The driver's id. It goes into the run record so that after a swap it can be
#: told whether findings dropped because the tool is worse, or only because a
#: capability disappeared.
DRIVER = "code-review-graph"

DB_PATH = ".code-review-graph/graph.db"

#: The questions every review asks.
CORE = ("state", "refresh", "changes", "impact", "locate", "neighbors")
#: The questions not every tool has — neither GitNexus nor Graphify answers one.
EXTENDED = ("unreferenced", "tests-for")

#: How the index reaches a throwaway worktree. CRG can do a file copy and an
#: incremental update; another driver will have to reindex or rebuild.
WORKSPACE_STRATEGY = "copy-db"

#: Direction in the call graph. "Who calls me" is a question, "callers_of" is a
#: command.
DIRECTIONS = {"in": "callers_of", "out": "callees_of"}


@dataclass
class Answer:
    """A driver's answer: normalised data, and beside it what it actually said.

    `data` is the contract — that is what a caller may rely on, and it survives
    a driver swap. `raw` is evidence: it is stored with the run so a finding can
    be traced back to what it came from, and it changes when the driver does. If
    only one of the two existed, either swapping or evidencing would be lost.
    """
    ok: bool
    data: Any = None
    raw: Any = None
    error: str | None = None


def capabilities() -> list[str]:
    """What this driver can do. A caller asks up front, not from an exception."""
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
    """A path relative to the repo. The driver returns absolute, the anchor
    needs short."""
    if not path:
        return None
    p = Path(path)
    try:
        return posix(p.relative_to(Path(repo)))
    except ValueError:
        return posix(p)


def _node(repo: str | Path, n: dict) -> dict:
    """A graph node the way the caller needs it: where it is and what it is."""
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
    """The index's state and freshness.

    A missing index is not an error — it is the answer "it has not been built
    yet". Freshness is told by comparing the commit it was built on with
    today's: an index from another head can rest a finding on code that does
    not exist on this branch.
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
    """Top the index up for this run.

    `build` is never run from here — it would rebuild the whole repo for a
    state that is thrown away shortly after.
    """
    r = proc.crg("update", "--repo", str(repo))
    if not r.ok:
        return _fail(r)
    return Answer(True, data={"action": "update"}, raw=r.stdout.strip()[:2000])


def changes(repo: str | Path, base: str) -> Answer:
    """What changed against base — in numbers, not in a sentence.

    `functionsTruncated` is there because the driver truncates the list and
    reports that ceiling in its summary as a result; without the flag the record
    would carry "500 changed functions" as a fact rather than a lower bound.
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
    """Blast radius: what else touches those files."""
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
    """Symbol → `file:line`. The anchor layer that survives a refactor."""
    args = ["search", symbol, "--repo", str(repo), "--limit", str(limit)]
    if kind:
        args += ["--kind", kind]
    a = _parsed(proc.crg(*args))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or {}).get("results") or []]
    return a


def neighbors(repo: str | Path, symbol: str, direction: str = "in") -> Answer:
    """Who calls me (`in`), whom I call (`out`)."""
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
    """Code nothing points at. The `reuse` dimension rests on this."""
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
    """Which tests concern that symbol. The `tests` dimension rests on this."""
    a = _parsed(proc.crg("query", "tests_for", symbol, "--repo", str(repo)))
    if not a.ok:
        return a
    a.data = [_node(repo, n) for n in (a.raw or {}).get("results") or []]
    return a


# -------------------------------------------------------------- workspace

def prepare(src_db: Path, wt: Path, on_stale: str = "update") -> dict:
    """Get the index into a throwaway worktree — the `copy-db` strategy.

    This is the most driver-specific thing in the whole module: GitNexus keeps
    its index elsewhere and differently, Graphify cannot update one
    incrementally at all. Which is why this is a driver strategy rather than a
    shared implementation in `runs.py`.
    """
    info: dict = {"tool": version(), "action": "missing"}
    if not Path(src_db).is_file():
        return info

    dst = Path(wt) / DB_PATH
    if Path(src_db).resolve() != dst.resolve():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_db, dst)
    # A run without a worktree works in the project itself — the index is
    # already in place. Copying a file onto itself is a hard error on Windows
    # (another process holds it) and nonsense elsewhere; topping it up is still
    # right, though.

    if on_stale == "ignore":
        info["action"] = "reused"
        return info

    a = refresh(wt)
    info["action"] = "update" if a.ok else "reused"
    if not a.ok:
        info["updateError"] = a.error
    return info
