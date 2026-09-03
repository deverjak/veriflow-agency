"""The gate between what the agent wrote and what becomes a finding.

The agent writes `findings.json` and exits. Until that moment it is text, not
data. This file turns it into candidates — and, more importantly, REFUSES.

Three reasons the gate is deterministic and not another LLM step:

  1. More findings must not mean more waste. Waste is recognisable without a
     model: a finding pointing at a file that does not exist at that commit is
     a hallucination, not an opinion.
  2. A model watching a model costs twice as much and is half as reliable.
  3. Discarding has to be reviewable. So nothing is deleted — rejected findings
     go to `gated.json` with their reason, and the count lands in the run record.

The gate does not judge the quality of the text. That is what the pack's `score`
and a human's triage are for. It checks whether a finding CAN be true at all.
"""

from __future__ import annotations

from pathlib import Path

from . import dedup, knowledge, proc
from . import runs as _runs
from .config import Project
from .runs import Run, load_runs, now
from .util import bundled, read_json, write_json

# Why a finding was dropped. Like a rejection reason this is an enum and not
# free text — otherwise there is no counting what a pack wastes the most on.
GATE_REASONS = {
    "schema": "does not match finding.v1",
    "phantom-file": "the file does not exist at the analysed commit",
    "phantom-line": "the line is past the end of the file as of the analysis",
    "below-score": "score below the project threshold",
}


def _schema_errors(findings: list[dict]) -> dict[int, list[str]]:
    """Contract errors by index. Without jsonschema, required fields only."""
    errs: dict[int, list[str]] = {}
    try:
        import jsonschema
    except ImportError:
        required = ("id", "runId", "pack", "severity", "title", "body", "anchor", "evidence")
        for i, f in enumerate(findings):
            missing = [k for k in required if k not in f]
            if missing:
                errs[i] = [f"missing {k}" for k in missing]
        return errs

    schema = read_json(bundled("schemas", "finding.v1.json"))
    v = jsonschema.Draft202012Validator(schema)
    for i, f in enumerate(findings):
        msgs = ["/".join(str(p) for p in e.path) + ": " + e.message for e in v.iter_errors(f)]
        if msgs:
            errs[i] = msgs
    return errs


def _exists_at_commit(root: Path, commit: str, path: str) -> tuple[bool, int | None]:
    """Was that file at that commit, and how many lines did it have?

    Returns `(True, None)` when the commit is not in the clone — an unreachable
    commit is no proof the finding lies. A squash merge with the branch deleted
    is GitHub's default, and dropping an honest finding over it would be a worse
    mistake than letting it through.
    """
    if not commit or not proc.commit_exists(root, commit):
        return True, None
    content = proc.show_file(root, commit, path)
    if content is None:
        return False, None
    return True, content.count("\n") + 1


def gate(project: Project, run: Run, findings: list[dict], min_score: int | None) -> tuple[list[dict], list[dict]]:
    """Splits findings into those that pass and those dropped, with a reason."""
    kept: list[dict] = []
    dropped: list[dict] = []
    errs = _schema_errors(findings)

    for i, f in enumerate(findings):
        def drop(reason: str, detail: str = "") -> None:
            dropped.append({
                "id": f.get("id"), "title": f.get("title"),
                "reason": reason, "detail": detail or GATE_REASONS.get(reason, ""),
                "finding": f,
            })

        if i in errs:
            drop("schema", "; ".join(errs[i])[:400])
            continue

        a = f.get("anchor") or {}
        ok, lines = _exists_at_commit(project.root, a.get("commit") or "", a["file"])
        if not ok:
            drop("phantom-file", f"{a['file']} is not at {(a.get('commit') or '')[:8]}")
            continue
        if lines is not None and a.get("line", 1) > lines:
            drop("phantom-line", f"line {a['line']} > {lines} lines in the file")
            continue

        score = f.get("score")
        if min_score is not None and isinstance(score, int) and score < min_score:
            drop("below-score", f"score {score} < {min_score}")
            continue

        kept.append(f)

    return kept, dropped


def earlier_findings(project: Project, run: Run) -> list[dict]:
    """Findings from older runs, plus the trail — what deduplication compares
    against.

    A run still on disk contributes its live findings — `candidate`, `held`
    or `sent`; reporting a duplicate of a duplicate tells nobody anything.
    The trail adds what a run no longer on disk sent or had rejected, so
    discarding a run's directory does not make it forget what it already
    reported — that memory is exactly why the trail is committed.
    """
    pool: list[dict] = []
    seen: set[str] = set()
    for r in load_runs(project):
        if r.id >= run.id:
            continue
        for f in r.findings():
            if f.get("state") in (None, "candidate", "held", "sent"):
                fid = f.get("id")
                if fid:
                    seen.add(fid)
                pool.append(f)
    for fid, row in _runs.read_trail(project).items():
        if fid in seen or row.get("state") not in ("sent", "rejected"):
            continue
        pool.append({"id": fid, "fingerprint": row.get("fingerprint"),
                     "title": row.get("title"), "anchor": row.get("anchor"),
                     "state": row.get("state")})
    return pool


def _held_upstream_runs(project: Project, chain: dict) -> list[Run]:
    """Every upstream run reachable from this chain's own `upstream` list,
    followed recursively through each of THEIR `upstream` too — the flat
    list `agency chain` writes already carries the whole history, but a run
    prepared some other way might not, so this does not assume it."""
    seen: set[str] = set()
    queue = list(chain.get("upstream") or [])
    found: list[Run] = []
    while queue:
        rid = queue.pop()
        if rid in seen:
            continue
        seen.add(rid)
        r = _runs.find_run(project, rid)
        if not r:
            continue
        found.append(r)
        queue.extend((r.record().get("chain") or {}).get("upstream") or [])
    return found


def ingest(project: Project, run: Run, min_score: int | None = None) -> dict:
    """The whole gate: contract → existence → threshold → dedup → chain
    handoff → dispatch → write.

    Idempotent. A second run over the same run gives the same result, because it
    always starts from `findings.raw.json` when that exists, and a finding
    already `sent` is not `candidate` any more so it is not dispatched twice.

    **Writes nothing when the agent wrote nothing.** An empty array made up by
    the gate looks identical, on disk and in the record, to an empty array a
    specialist wrote — except the first says "I could not" and the second says
    "I looked and there is nothing there". On 2026-09-02 that difference cost
    two real findings: every write by the agent inside `claude -p` was refused,
    the gate filled in `[]` for it, and the chain moved on to a member judging
    findings that had never existed.
    """
    raw_path = run.dir / "findings.raw.json"
    if raw_path.is_file():
        findings = read_json(raw_path, default=[])
    elif not run.findings_path.is_file():
        # Neither `findings.json` nor `findings.raw.json`. There is nothing to
        # put through the gate and, more to the point, nothing to claim — the
        # caller turns this into `failed: no-output`.
        return {"run": run.id, "noOutput": True, "raw": 0, "kept": 0,
                "duplicates": [], "dropped": [], "counts": None, "bundle": None}
    else:
        findings = run.findings()
        if findings:
            # The agent's original output is kept aside so the gate can be
            # re-run with different rules without losing what the pack actually
            # wrote.
            write_json(raw_path, findings)

    raw_count = len(findings)
    if min_score is None:
        from . import packs
        pack_name = run.record().get("pack") or "review-graph"
        try:
            min_score = packs.load(pack_name, project).min_score
        except SystemExit:
            # The pack no longer exists (renamed, removed) — the gate still
            # has to run, just without a threshold to check.
            min_score = None

    kept, dropped = gate(project, run, findings, min_score)
    for f in kept:
        f["fingerprint"] = dedup.fingerprint(f)

    dups = dedup.mark_duplicates(kept, earlier_findings(project, run))

    rec = run.record()
    chain = rec.get("chain") or {}
    # A chain member is not the last one: what it found waits for the next
    # specialist to judge, and dispatch is not this run's call to make.
    last = not chain or chain.get("position", 1) >= chain.get("of", 1)

    if not last:
        for f in kept:
            if f.get("state") == "candidate":
                f["state"] = "held"

    write_json(run.findings_path, kept)
    if dropped:
        write_json(run.dir / "gated.json", dropped)
    elif (run.dir / "gated.json").is_file():
        (run.dir / "gated.json").unlink()

    for d in dropped:
        dropped_finding = d.get("finding") or {}
        _runs.append_trail(project, {
            "id": d.get("id"), "runId": run.id, "pack": rec.get("pack"),
            "state": "gated-out", "title": d.get("title"),
            "severity": dropped_finding.get("severity"),
            "dimension": dropped_finding.get("dimension"), "fingerprint": None,
            "anchor": dropped_finding.get("anchor"), "by": None,
            "reason": d.get("reason"), "ref": None, "url": None,
        })

    sent = 0
    dispatch_errors: list[dict] = []
    if last:
        own_by = f"hire:{_runs.worker_id(rec.get('pack') or 'unknown', (rec.get('agent') or {}).get('provider'))}"
        for f in kept:
            if f.get("state") != "candidate":
                continue
            result = _runs.dispatch(project, run, f, own_by)
            if result.get("noSink"):
                continue
            if result["ok"]:
                sent += 1
            else:
                dispatch_errors.append({"id": result["id"], "error": result["error"]})

        # The chain ended without anyone judging one of its own findings —
        # that is not a rejection, and holding it forever is not memory
        # either. It goes to the board the same way, marked `chain` so
        # nobody mistakes it for a specialist's endorsement.
        for upstream_run in _held_upstream_runs(project, chain):
            decided = _runs.decisions(upstream_run)
            for f in upstream_run.findings():
                if f.get("state") != "held" or f.get("id") in decided:
                    continue
                result = _runs.dispatch(project, upstream_run, f, _runs.CHAIN)
                if result.get("noSink"):
                    continue
                if result["ok"]:
                    sent += 1
                else:
                    dispatch_errors.append({"id": result["id"], "error": result["error"]})

    held = len([f for f in kept if f.get("state") == "held"])

    by_reason: dict[str, int] = {}
    for d in dropped:
        by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1

    rec = run.record()
    rec["counts"] = {
        "raw": raw_count,
        "gated": len(dropped),
        "belowScore": by_reason.get("below-score", 0),
        "duplicates": len(dups),
        "kept": len([f for f in kept if f.get("state") != "duplicate"]),
        "sent": sent,
        "held": held,
    }
    rec["gatedBy"] = by_reason or None
    if dispatch_errors:
        rec["dispatchErrors"] = dispatch_errors
    # The run's summary is the pack's contract (`RUN_DIR/summary.md`). The gate
    # neither reads nor writes it — it only records that it exists. Its readers
    # are a person, the memory's chronology and the next specialist in a chain.
    # `handoff.md` is the same thing one step more addressed — a message to the
    # next chain member. It is recorded for a standalone run too: a pack cannot
    # know whether anyone stands behind it, and writing one needlessly is
    # cheaper than not having it the day it is needed.
    rec["outputs"] = {"summary": (run.dir / "summary.md").is_file(),
                      "handoff": (run.dir / "handoff.md").is_file()}
    rec["status"] = "ok" if kept else ("no-findings" if raw_count == 0 else "gated-out")
    rec.setdefault("finishedAt", now())
    run.save_record(rec)

    return {
        "run": run.id,
        "raw": raw_count,
        "kept": rec["counts"]["kept"],
        "sent": sent,
        "held": held,
        "duplicates": dups,
        "dropped": [{k: v for k, v in d.items() if k != "finding"} for d in dropped],
        "dispatchErrors": dispatch_errors,
        "counts": rec["counts"],
        # The ledger is rebuilt after the gate, because what belongs in the
        # project's memory is what passed the gate — not what the pack wrote.
        # It is written after the record is saved: if writing the bundle failed,
        # the gate's result is already safely on disk and
        # `agency knowledge --rebuild` catches the bundle up.
        "bundle": _bundle(project),
    }


def _bundle(project: Project) -> dict:
    """The derived bundle is refreshed, but it must not bring down the gate.

    The findings are already saved in `.agency/runs/` before this call runs.
    A failure writing `.agency/knowledge/` is therefore an inconvenience, not
    data loss — reported as a line, not a crash, since a crash would send the
    user to run ingest again and that would fix nothing.
    """
    try:
        return knowledge.bundle(project)
    except OSError as e:
        return {"error": str(e)}
