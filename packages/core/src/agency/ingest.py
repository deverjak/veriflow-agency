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

import json
from pathlib import Path
from urllib.parse import urlparse

from . import dedup, knowledge, outputs, proc
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
    "unproven-source": "evidence cites a command that never ran in this run",
    "weak-evidence": "not the kind of proof this dimension stands or falls on",
    "unverified-evidence": "the evidence locator points at something this run did not produce",
    "unknown-type": "an output of a type this pack does not declare",
    "missing-anchor": "a type whose claims must point at source, pointing at nothing",
    "over-cardinality": "more of this type in one run than the pack allows",
}

#: What makes a `source` a claim about something that RAN, rather than a
#: pointer to something that can be read. Explicit, not a heuristic: an early
#: version keyed on "contains a space", which made
#: `CLAUDE.md#rules-that-will-bite-you` a command and would have dropped an
#: honest finding for citing a document.
COMMAND_PREFIXES = ("agency ", "git ", "gh ", "npx ", "npm ", "python ",
                    "pnpm ", "yarn ", "code-review-graph ")


def _is_command(source: str) -> bool:
    return str(source or "").strip().startswith(COMMAND_PREFIXES)


def _head(command: str) -> list[str]:
    """The command and its subcommands — everything before the first flag.

    Flags and their values are deliberately not compared. An agent that wrote
    `--depth 2` and ran `--depth 3` is lying about a detail, not about having
    looked at the graph; dropping its finding for that would teach packs to
    cite nothing rather than to cite accurately.
    """
    head: list[str] = []
    for token in str(command or "").split():
        if token.startswith("-"):
            break
        head.append(token)
    return head


def _command_of(row: dict) -> str | None:
    """The shell command a recorded tool call ran, if it ran one.

    Two shapes, on purpose: rows written before 2026-09-06 are flat
    (`{"command": …}`), rows since carry the tool's own input under `input`,
    because `command` is one kind of input among several. Committed run
    history is not rewritten, so both are read.
    """
    if row.get("command"):
        return str(row["command"])
    data = row.get("input")
    if isinstance(data, dict) and data.get("command"):
        return str(data["command"])
    return None


def _tool_rows(run: Run) -> list[dict] | None:
    """Everything the recorder wrote for this run — `None` when nobody was.

    `None` and `[]` mean opposite things and the difference is the whole
    safety of every check built on this: no file means the hook never ran (an
    attended run, a codex run), and a gate stage that treated that as "did
    nothing" would drop every honest finding in those runs.
    """
    path = run.dir / _runs.TOOL_CALLS
    if not path.is_file():
        return None
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return None
    return rows


def commands_run(run: Run) -> list[str] | None:
    """What this run actually executed — `None` when nobody was recording."""
    rows = _tool_rows(run)
    if rows is None:
        return None
    return [c for c in (_command_of(row) for row in rows) if c]


def unproven(finding: dict, ran: list[str]) -> str | None:
    """The first cited command that never ran, or `None` when all of them did.

    Two places say "a command": the free-text `source`, which has to be
    recognised as one (`_is_command`), and `locator.command`, which says so by
    being there. Same lie, same reason — one check, so that a pack does not
    get a different verdict for citing the same command in the newer shape.
    """
    heads = [_head(c) for c in ran]
    for item in finding.get("evidence") or []:
        source = (item or {}).get("source")
        cited = ((item or {}).get("locator") or {}).get("command")
        if not cited:
            if not _is_command(source):
                continue
            cited = source
        want = _head(cited)
        if not any(head[:len(want)] == want or want[:len(head)] == head
                   for head in heads):
            return " ".join(want)
    return None


def _norm_url(url: str) -> str:
    """A URL as the comparison sees it.

    The recorded call and the cited page are written by two different hands —
    the runner's hook and the agent — so `https://KICKK.cz/vyzvy/` and
    `https://kickk.cz/vyzvy#program` must be the same page. Only the parts
    that cannot change the page are normalised away; a query string can, and
    stays.
    """
    text = str(url or "").strip()
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{(parsed.scheme or '').lower()}://{host}{path}{query}"


def urls_fetched(run: Run) -> set[str] | None:
    """Every page this run is recorded as having opened.

    `None` when nobody was recording, and it means the same as it means in
    `commands_run`: the check is skipped whole rather than failed. A run whose
    hook never fired must not lose its findings for it.
    """
    rows = _tool_rows(run)
    if rows is None:
        return None
    out: set[str] = set()
    for row in rows:
        url = (row.get("input") or {}).get("url") if isinstance(row.get("input"), dict) else None
        if url:
            out.add(_norm_url(url))
    return out


def _in_run(run_dir: Path, artifact: str) -> Path | None:
    """The artifact's real path, or `None` when it points out of the run.

    The schema already forbids the shapes that escape; this is the second
    layer, because a path that leaves RUN_DIR is not a mistake in a locator —
    it is a run vouching for something it does not own.
    """
    try:
        root = run_dir.resolve()
        path = (run_dir / artifact).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def unverified(project: Project, run: Run, finding: dict,
               urls: set[str] | None) -> str | None:
    """The first evidence locator that does not check out, or `None`.

    Offline, always. Everything here is answered from the repository at a
    commit or from what the run itself kept in `RUN_DIR/evidence/` — never by
    asking the network. A gate that phoned out would give the same run two
    different answers on two different days, and `replay` would stop being a
    regression test.

    Locators are checked, `source` is not: an item with no locator is the
    older shape and keeps passing exactly as it did.
    """
    for item in finding.get("evidence") or []:
        kind = (item or {}).get("kind")
        loc = (item or {}).get("locator") or {}
        if not loc:
            continue

        if kind in ("code", "document"):
            ok, lines = _exists_at_commit(project.root, loc.get("commit") or "",
                                          loc.get("file") or "")
            if not ok:
                return (f"{kind}: {loc.get('file')} is not at "
                        f"{(loc.get('commit') or '')[:8]}")
            line = loc.get("line")
            if lines is not None and isinstance(line, int) and line > lines:
                return f"{kind}: line {line} > {lines} lines in {loc.get('file')}"

        elif kind in ("web_snapshot", "board_item"):
            if not _in_run(run.dir, loc.get("artifact") or ""):
                return f"{kind}: {loc.get('artifact')} is not in this run"
            if kind == "web_snapshot" and urls is not None:
                if _norm_url(loc.get("url") or "") not in urls:
                    return f"web_snapshot: {loc.get('url')} was not opened in this run"
            if kind == "board_item":
                path = _in_run(run.dir, loc["artifact"])
                ref = str(loc.get("ref") or "")
                try:
                    if ref not in path.read_text(encoding="utf-8", errors="replace"):
                        return f"board_item: {ref} is not in {loc['artifact']}"
                except OSError:
                    return f"board_item: {loc['artifact']} cannot be read"

    return None


#: The line a blocked run is read by. The pack writes the whole file; this is
#: the one sentence that reaches `agency status` and the chain report, so it
#: is the one the template puts first.
BLOCKED_LEAD = "what i could not do"


def blocked_reason(path: Path) -> str | None:
    """The one sentence out of `blocked.md` that says what could not be done.

    `None` when the file is not there. An empty file still counts as blocked —
    the agent said something went wrong even if it said it badly, and turning
    that back into "no findings" is exactly the confusion this exists to end.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip().lstrip("*-# ").strip()
        if not line:
            continue
        head, sep, rest = line.partition(":")
        if sep and head.strip().strip("*").lower() == BLOCKED_LEAD:
            return rest.strip().strip("*").strip() or None
    # No template line. The first non-empty line that is not the heading is a
    # better answer than nothing, because the alternative is a blocked run
    # whose record cannot say a word about why.
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line.strip("*").strip()[:200]
    return None


def _schema_errors(findings: list[dict]) -> dict[int, list[str]]:
    """Contract errors by index. Without jsonschema, required fields only."""
    errs: dict[int, list[str]] = {}
    try:
        import jsonschema
    except ImportError:
        required = ("id", "runId", "pack", "severity", "title", "body", "evidence")
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


def required_evidence(pack) -> dict[str, list[str]]:
    """Which kinds of proof each dimension stands or falls on.

    A dimension may say so in `pack.json`:

        { "id": "reuse", "title": "Code nothing points at", "evidence": ["graph"] }

    …because the schema weighs SHAPE, not strength: `finding.v1` asks for one
    piece of evidence out of six equal kinds, so `reuse` — which stands
    entirely on the call graph — passes on a quotation from the README.

    A dimension without the key behaves exactly as before. Backwards
    compatibility for free, and the pack decides rather than the core: only
    the pack knows which of its questions have one honest kind of answer.
    """
    out_: dict[str, list[str]] = {}
    for d in (pack.dimensions if pack else []):
        kinds = [str(k).strip() for k in (d.get("evidence") or []) if str(k).strip()]
        if kinds and d.get("id"):
            out_[str(d["id"])] = kinds
    return out_


def gate(project: Project, run: Run, findings: list[dict], min_score: int | None,
         evidence: dict[str, list[str]] | None = None,
         pack=None) -> tuple[list[dict], list[dict]]:
    """Splits findings into those that pass and those dropped, with a reason."""
    kept: list[dict] = []
    dropped: list[dict] = []
    errs = _schema_errors(findings)
    # Loaded once. `None` means nothing was recording this run, and then the
    # whole check is skipped — never drop a finding because a hook did not run.
    ran = commands_run(run)
    urls = urls_fetched(run)
    # How many of each type have already passed. The ceiling is the pack's own
    # (`outputs.<type>.cardinality` / `limit`) — a CEO answer is one per run
    # and a second one is not a second answer, it is a run that lost the plot.
    seen_of_type: dict[str, int] = {}

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

        type_name = f.get("type") or outputs.DEFAULT_TYPE
        if pack is not None and not outputs.declares(pack, type_name):
            drop("unknown-type", f"“{type_name}” is not in this pack's `outputs`")
            continue
        policy = outputs.policy_for(pack, type_name)

        # Whether a claim has to point at source is a question about the KIND
        # of output, which the schema cannot answer because it cannot see the
        # pack. A finding must — that has not changed and the default is
        # `required`. A bet about a market must not pretend to: it was that
        # requirement which had `footer.tsx` carrying a claim about a funding
        # call. What replaces it is the type's own `evidence.required`, and a
        # policy that drops one without naming the other is refused by
        # `outputs.errors`.
        a = f.get("anchor") or {}
        if policy.anchor == "required" and not a.get("file"):
            drop("missing-anchor", f"{type_name} must point at a file and a line")
            continue
        if a.get("file"):
            ok, lines = _exists_at_commit(project.root, a.get("commit") or "", a["file"])
            if not ok:
                drop("phantom-file", f"{a['file']} is not at {(a.get('commit') or '')[:8]}")
                continue
            if lines is not None and a.get("line", 1) > lines:
                drop("phantom-line", f"line {a['line']} > {lines} lines in the file")
                continue

        # The type wins over the dimension when it says anything: the type is
        # the coarser statement ("a bet stands on documents or the web") and a
        # pack that declares both means the finer one for its findings.
        wanted = policy.required_evidence or (evidence or {}).get(f.get("dimension") or "")
        kinds = {(e or {}).get("kind") for e in (f.get("evidence") or [])}
        if wanted and not kinds & set(wanted):
            drop("weak-evidence",
                 f"{type_name if policy.required_evidence else f.get('dimension')} "
                 f"needs {' or '.join(wanted)}, got "
                 f"{', '.join(sorted(k for k in kinds if k)) or 'nothing'}")
            continue
        if len(f.get("evidence") or []) < policy.min_evidence:
            drop("weak-evidence",
                 f"{type_name} needs {policy.min_evidence} pieces of evidence, "
                 f"got {len(f.get('evidence') or [])}")
            continue

        if ran is not None:
            cited = unproven(f, ran)
            if cited:
                drop("unproven-source", f"“{cited}” did not run in this run")
                continue

        # After the command check on purpose: a fabricated command is the
        # older and better-understood lie, and reading it as the newer one
        # would make the two populations in `gatedBy` impossible to tell
        # apart.
        broken = unverified(project, run, f, urls)
        if broken:
            drop("unverified-evidence", broken)
            continue

        score = f.get("score")
        if min_score is not None and isinstance(score, int) and score < min_score:
            drop("below-score", f"score {score} < {min_score}")
            continue

        # Last, and after everything that judges the output itself: a ceiling
        # is not a statement about this output, it is about how many came
        # before it. Dropping the eleventh before checking whether it is
        # honest would hide a broken pack behind a full quota.
        ceiling = policy.max_per_run
        if ceiling is not None and seen_of_type.get(type_name, 0) >= ceiling:
            drop("over-cardinality",
                 f"{type_name}: {ceiling} per run is this pack's own ceiling")
            continue
        seen_of_type[type_name] = seen_of_type.get(type_name, 0) + 1

        kept.append(f)

    return kept, dropped


#: How many times one run may be sent back to fix its own output. Two, and
#: then the gate has it. ECC hit the same wall and answered it with a switch
#: (`GATEGUARD_FACT_FORCE_FULL_DENIALS`); the lesson underneath is not the
#: switch, it is that a hook able to block forever produces a run that never
#: finishes — which costs more than the findings it was trying to save.
STOP_BLOCKS = 2


def stop_errors(run_dir: Path, root: Path) -> list[str]:
    """What is wrong with this run's `findings.json`, in the agent's own terms.

    Deliberately only the two checks that need nothing but this run: the
    contract, and whether the anchor exists at the commit under review. Dedup,
    score distribution and provenance all need state from outside the run and
    belong to the gate — a hook that reached for them would be a second gate
    with a worse view.

    Both checks are the gate's own functions, called rather than reimplemented:
    a second implementation would drift, and the day it did, the agent would be
    sent back to fix something the gate does not actually mind.
    """
    findings = read_json(Path(run_dir) / "findings.json", default=None)
    if findings is None:
        return ["findings.json is missing — write it before you stop."]
    if not isinstance(findings, list):
        return ["findings.json must be an array of finding.v1 objects."]

    problems: list[str] = []
    for i, msgs in _schema_errors(findings).items():
        title = str((findings[i] or {}).get("title") or f"finding {i + 1}")[:60]
        problems.append(f"{title}: {'; '.join(msgs)[:300]}")

    for f in findings:
        a = (f or {}).get("anchor") or {}
        if not a.get("file") or not a.get("commit"):
            continue
        ok, lines = _exists_at_commit(Path(root), a.get("commit") or "", a["file"])
        title = str((f or {}).get("title") or "")[:60]
        if not ok:
            problems.append(f"{title}: {a['file']} does not exist at "
                            f"{(a.get('commit') or '')[:8]}.")
        elif lines is not None and (a.get("line") or 1) > lines:
            problems.append(f"{title}: line {a.get('line')} is past the end of "
                            f"{a['file']} ({lines} lines).")
    return problems


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
    blocked_path = run.dir / "blocked.md"
    is_blocked = blocked_path.is_file()
    # Whether the pack wrote findings at all — kept separately because the gate
    # must not invent an empty `findings.json` for a run that wrote none.
    wrote_findings = raw_path.is_file() or run.findings_path.is_file()

    if raw_path.is_file():
        findings = read_json(raw_path, default=[])
    elif not wrote_findings:
        if not is_blocked:
            # Neither `findings.json` nor `findings.raw.json`. There is nothing
            # to put through the gate and, more to the point, nothing to claim
            # — the caller turns this into `failed: no-output`.
            return {"run": run.id, "noOutput": True, "raw": 0, "kept": 0,
                    "duplicates": [], "dropped": [], "counts": None,
                    "blocked": False, "bundle": None}
        # Blocked and nothing else written is the ordinary shape of being
        # blocked, not a failure to write: the agent said so in the one file
        # it could still write. It goes through the rest of the gate with an
        # empty list so the record comes out complete.
        findings = []
    else:
        findings = run.findings()
        if findings:
            # The agent's original output is kept aside so the gate can be
            # re-run with different rules without losing what the pack actually
            # wrote.
            write_json(raw_path, findings)

    raw_count = len(findings)
    from . import packs
    pack_name = run.record().get("pack") or "review-graph"
    try:
        pack = packs.load(pack_name, project)
    except SystemExit:
        # The pack no longer exists (renamed, removed) — the gate still has to
        # run, just without a threshold or per-dimension evidence to check.
        pack = None
    if min_score is None and pack:
        min_score = pack.min_score

    kept, dropped = gate(project, run, findings, min_score,
                         evidence=required_evidence(pack), pack=pack)
    for f in kept:
        f["fingerprint"] = dedup.fingerprint(f)

    # A type may say it is not deduplicated (`outputs.<type>.dedup: false`).
    # An answer is the case: two answers to the same question a month apart
    # are two answers, and marking the second a duplicate of the first would
    # throw away the one that is current.
    dedupable = [f for f in kept
                 if outputs.policy_for(pack, f.get("type")).dedup]
    dups = dedup.mark_duplicates(dedupable, earlier_findings(project, run))

    rec = run.record()
    chain = rec.get("chain") or {}
    # A chain member is not the last one: what it found waits for the next
    # specialist to judge, and dispatch is not this run's call to make.
    last = not chain or chain.get("position", 1) >= chain.get("of", 1)

    if not last:
        for f in kept:
            if f.get("state") == "candidate":
                f["state"] = "held"

    if wrote_findings:
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
            "anchor": dropped_finding.get("anchor"),
            "subject": dropped_finding.get("subject"), "by": None,
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
    # Which population this run belongs to (R6). A gate stage that only some
    # runs are subject to must not leave those runs and the rest looking alike
    # — otherwise `unproven-source` never appearing reads as "nobody lies"
    # rather than "nobody was checked".
    rec["context"] = {**(rec.get("context") or {}),
                      "toolCalls": commands_run(run) is not None}
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
                      "handoff": (run.dir / "handoff.md").is_file(),
                      "blocked": is_blocked}
    # Blocked first, and regardless of how many findings came with it. A run
    # that hit a wall may well have finished two dimensions before it did, and
    # throwing those away would make the honest report the expensive one. What
    # must not survive is the old reading, where that same run was recorded as
    # `no-findings` — the status a pack gets for looking and finding nothing.
    if is_blocked:
        rec["status"] = "blocked"
        reason = blocked_reason(blocked_path)
        if reason:
            rec["exitReason"] = reason
    else:
        rec["status"] = "ok" if kept else ("no-findings" if raw_count == 0 else "gated-out")
    rec.setdefault("finishedAt", now())
    run.save_record(rec)

    return {
        "run": run.id,
        "raw": raw_count,
        "kept": rec["counts"]["kept"],
        "sent": sent,
        "held": held,
        "blocked": is_blocked,
        "blockedReason": rec.get("exitReason") if is_blocked else None,
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
