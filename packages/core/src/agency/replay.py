"""Running a pack again over a commit it has already judged.

Every part of this existed and nobody had put them together: `target.headRefOid`
pins the code, a worktree makes that commit reproducible, `dedup.fingerprint`
is deterministic, and the decisions say which findings turned out to be true.
That is an eval — the only thing missing was a file saying "these were the
answers".

**A fixture is a pinned run**, committed to `.agency/evals/` because it is a
truth about the project like everything else here. Replaying it starts the
same pack over the same commit with TODAY's `SKILL.md`, and compares what
comes back against what was decided then.

One number matters more than the rest and it is deliberately blunt:

    a change to a method that brings back a previously REJECTED finding
    is a regression, and does not ship.

No exceptions, because it is the only number in this system with one possible
reading. Recall can drop for good reasons (a finding got fixed), "new" can be
good or bad and needs a person — but a finding this project has already said
no to, coming back, is the method getting worse at the one thing it was told.

One borrowed warning, from ECC's own anti-patterns and it applies here
unchanged: **a fixture a pack starts being tuned against has stopped
measuring.** So fixtures are added as real runs happen, and an old one is
never edited to make it pass.
"""

from __future__ import annotations

from pathlib import Path

from . import dedup
from . import runs as _runs
from .config import Project
from .util import posix, read_json, write_json

#: Committed, next to the knowledge. Fixtures are the project's answers, not
#: this machine's cache.
EVALS = "evals"

#: What a fixture keeps about each finding that was decided. Not the body: a
#: fixture is an answer key, and keeping the text would tempt the comparison
#: into matching on wording rather than on the fingerprint.
GOLD_FIELDS = ("fingerprint", "id", "title", "dimension", "decision", "reason")


def evals_dir(project: Project) -> Path:
    return project.agency_dir / EVALS


def fixtures(project: Project, pack: str | None = None) -> list[dict]:
    """Every fixture this project has, newest name last."""
    d = evals_dir(project)
    found = []
    for path in sorted(d.glob("*.json")) if d.is_dir() else []:
        data = read_json(path, default=None)
        if isinstance(data, dict) and (pack is None or data.get("pack") == pack):
            found.append(data)
    return found


def find(project: Project, name: str) -> dict | None:
    for f in fixtures(project):
        if f.get("name") == name:
            return f
    return None


def pin(project: Project, run, name: str) -> dict:
    """Turn a finished run into an answer key.

    Only findings somebody DECIDED on go into the gold. An undecided finding
    is not an answer — putting it in would make the eval grade a pack against
    a queue nobody has worked through, which is the same mistake precision
    already refuses to make.
    """
    rec = run.record()
    decided = _runs.decisions(run)
    gold: list[dict] = []
    for f in run.findings():
        d = decided.get(f.get("id"))
        if not d or d.get("state") not in ("sent", "rejected"):
            continue
        gold.append({
            "fingerprint": f.get("fingerprint") or dedup.fingerprint(f),
            "id": f.get("id"), "title": f.get("title"),
            "dimension": f.get("dimension"),
            "decision": d["state"], "reason": d.get("reason"),
        })
    if not gold:
        raise SystemExit(
            f"Run {run.id[:10]} has no decided findings, so there is no answer key in "
            f"it.\nDecide some (`agency findings`, or a `verify` member) and pin it "
            f"afterwards.")

    fixture = {
        "name": name,
        "pack": rec.get("pack"),
        "fromRun": run.id,
        "createdAt": _runs.now(),
        # The commit is the whole point: replaying against a moving branch
        # would compare a method change with a code change and call the sum
        # of them a result.
        "target": {k: v for k, v in (rec.get("target") or {}).items()
                   if not str(k).startswith("_")},
        "prompt": read_json(run.dir / "context.json", default={}).get("prompt"),
        "gold": gold,
    }
    path = evals_dir(project) / f"{name}.json"
    write_json(path, fixture)
    return {**fixture, "path": posix(path)}


def compare(fixture: dict, findings: list[dict]) -> dict:
    """What a replay produced, against what was decided the first time.

    Matched on `fingerprint`, never on the title: a title survives a corrected
    diagnosis and the content does not, which is the same reason dedup does
    not use it either.
    """
    seen = {f.get("fingerprint") or dedup.fingerprint(f) for f in findings}
    gold = fixture.get("gold") or []
    accepted = [g for g in gold if g.get("decision") == "sent"]
    rejected = [g for g in gold if g.get("decision") == "rejected"]

    found_again = [g for g in accepted if g.get("fingerprint") in seen]
    regressions = [g for g in rejected if g.get("fingerprint") in seen]
    known = {g.get("fingerprint") for g in gold}
    fresh = [{"title": f.get("title"), "dimension": f.get("dimension"),
              "fingerprint": f.get("fingerprint") or dedup.fingerprint(f)}
             for f in findings
             if (f.get("fingerprint") or dedup.fingerprint(f)) not in known]

    return {
        "fixture": fixture.get("name"),
        "pack": fixture.get("pack"),
        # How much of what held up last time still comes back.
        "recall": (round(len(found_again) / len(accepted), 3) if accepted else None),
        "recallOf": len(accepted),
        "recalled": len(found_again),
        # THE number. One reading, no exceptions.
        "regressions": [{"title": g.get("title"), "reason": g.get("reason")}
                        for g in regressions],
        "rejectedOf": len(rejected),
        # Neither good nor bad on its own — a person looks.
        "new": fresh,
        "missed": [{"title": g.get("title"), "dimension": g.get("dimension")}
                   for g in accepted if g.get("fingerprint") not in seen],
        "pass": not regressions,
    }


def report(result: dict) -> str:
    """The table, for a terminal and for a commit message."""
    lines = [f"  {result['fixture']}  ({result['pack']})", ""]
    recall = ("—" if result["recall"] is None
              else f"{result['recall']:.0%} ({result['recalled']}/{result['recallOf']})")
    lines.append(f"    recall       {recall}   of what held up last time")
    lines.append(f"    regressions  {len(result['regressions'])}"
                 f"   of {result['rejectedOf']} it had already rejected")
    for r in result["regressions"]:
        lines.append(f"      × {(r['title'] or '')[:60]}"
                     + (f"   (was: {r['reason']})" if r.get("reason") else ""))
    lines.append(f"    new          {len(result['new'])}   for a person to judge")
    for n in result["new"][:5]:
        lines.append(f"      + {(n['title'] or '')[:60]}")
    if result["missed"]:
        lines.append(f"    missed       {len(result['missed'])}   accepted before, "
                     f"not found now")
    lines += ["", "    PASS" if result["pass"] else
              "    FAIL — a finding this project already rejected came back"]
    return "\n".join(lines)
