"""A finding's anchor, and the drift test.

A finding is made at commit A and read three weeks later from a working tree
thirty commits further on. The line number no longer holds and NOTHING SAYS SO
— the comment lands on innocent code, you reject it, and with that you break
the one metric the whole measurement exists for.

Four layers, tried top to bottom, stopping at the first that succeeds. When
they all fail, the finding is degraded, not lost.

Both fixes that came out of the spike are here:
  layer 1 asks whether the FILE is unchanged, not the repository,
  layer 2 looks for a block, not a single line.

Since 8 September 2026 the four layers are carried by a `code` evidence item
rather than by an `anchor` field of its own. Nothing about the layers changed —
what changed is that pointing at source stopped being a property every output
has and became one kind of proof among five, which a type asks for or does not.
`of()` and `places()` are where both shapes are read; everything below them
sees one dict either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import graph, proc

_WORDY = re.compile(r"[A-Za-z0-9_]{4}")


@dataclass
class Resolution:
    line: int | None
    via: str
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.line is not None


def of(finding: dict) -> dict:
    """Where in the source this output sits — `{}` when it sits nowhere.

    Two shapes, and both are read for good. An output written since Step 9
    says it with a `code` evidence item whose locator carries the same four
    layers; every output written before it — which is all of committed run
    history — carries the `anchor` field. History is not rewritten, so the
    older shape is a fallback and not a deprecation.

    Code evidence wins when an output has both: a pack that writes it is a
    pack that knows about the newer shape, and the locator is where it put
    the layers. `places()` still checks the other one.
    """
    for item in finding.get("evidence") or []:
        if (item or {}).get("kind") != "code":
            continue
        loc = item.get("locator") or {}
        if loc.get("file"):
            return loc
    a = finding.get("anchor")
    return a if isinstance(a, dict) else {}


def places(finding: dict) -> list[dict]:
    """Every place in the source this output points at.

    A different question from `of()`, which is why it is a different function.
    `of()` answers "where does this sit" and one output sits in one place — it
    is what dedup, drift and the queue read. This answers "what has the gate
    got to check", and a finding may cite three pieces of code, of which any
    one can be invented.
    """
    out = []
    for item in finding.get("evidence") or []:
        if (item or {}).get("kind") != "code":
            continue
        loc = item.get("locator") or {}
        if loc.get("file"):
            out.append(loc)
    a = finding.get("anchor")
    if isinstance(a, dict) and a.get("file"):
        out.append(a)
    return out


def distinctive_line(anchor: dict) -> tuple[str, int] | None:
    """The block's most distinctive line, and its offset from anchor.line.

    A one-line snippet fails on `/**`, `}` and boilerplate like it — and that
    is exactly how a docblock starts. The longest line carrying at least four
    alphanumeric characters in a row is taken.
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
        return Resolution(None, "none", "the file does not exist in the working tree")

    try:
        lines = abs_path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError as e:
        return Resolution(None, "none", f"the file cannot be read: {e}")
    count = len(lines)
    line = anchor.get("line") or 1

    # 1. the file has not changed since the analysis → line numbers hold literally
    commit = anchor.get("commit")
    if commit and proc.file_unchanged(repo, commit, rel):
        if line <= count:
            return Resolution(line, "exact", "file unchanged")
        return Resolution(None, "none", f"line {line} is past the end of the file ({count} lines)")

    # 2. the block's text → finds code that has shifted
    d = distinctive_line(anchor)
    if d:
        needle, offset = d
        hits = [i + 1 for i, raw in enumerate(lines) if raw.strip() == needle]
        if len(hits) == 1:
            resolved = max(1, hits[0] - offset)
            if resolved == line:
                return Resolution(resolved, "snippet (unchanged)")
            return Resolution(resolved, "snippet", f"shifted {line} → {resolved}")
        if len(hits) > 1:
            best = min(hits, key=lambda h: abs(max(1, h - offset) - line))
            return Resolution(max(1, best - offset), "snippet (ambiguous)",
                              f"{len(hits)} matches, the closest one was picked")

    # 3. the symbol from the graph — survives a refactor where the line text does not
    sym = anchor.get("symbol") or {}
    if sym.get("name"):
        found = graph.locate(repo, sym["name"])
        if found.ok:
            for node in found.data:
                if node["file"] == rel and node["line"]:
                    return Resolution(node["line"], "symbol",
                                      f"via {sym['name']} from the graph")

    # 4. failure — degrade, do not lose
    if line > count:
        return Resolution(None, "none", f"line {line} is past the end of the file ({count} lines)")
    return Resolution(None, "none", "the block text was not found in the file, nor via the symbol")


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ", re.M)


def drift(repo: str | Path, anchor: dict) -> str:
    """`untouched` | `touched` | `deleted` | `unknown`.

    Read it carefully: `untouched` means that RANGE was not touched — even if
    the file was rewritten elsewhere and the line has shifted. That distinction
    ("rewritten, look at the diff" vs. "holds literally") is exactly what
    pre-sorts the queue.
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
