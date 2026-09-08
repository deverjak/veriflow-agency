"""The numbers that used to be produced by hand in baseline.md.

One question outranks all the others: **how much of what a pack finds is
true?** Without it there is no deciding on a model, nor on whether the tool
should live on — which is exactly why step 0 (the `Rejected` state) came first
in the plan.

Precision is computed from DECIDED findings only. An undecided finding is
neither true nor false; putting it in the denominator would let every new run
dilute precision, and the number would measure the speed of triage rather than
the quality of the findings.

The breakdowns (dimension, severity, model) are here because the aggregate
number does not say what to do about it. `precision 0.55` is useless;
`dimension reuse 0.2, correctness 0.9` is an instruction to switch one
dimension off.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from . import outputs, packs
from .config import Project
from .runs import Run, decisions, load_runs, normalize_by, verdicts

DAY = 86400.0


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ratio(hit: int, total: int) -> float | None:
    """A ratio, or None. Zero out of zero is not zero percent — it is "I do not
    know", and rounding "I do not know" to 0.0 is the cheapest way to lie."""
    return round(hit / total, 3) if total else None


class Tally:
    """Accepted / rejected / deferred for one slice of the data.

    Only a decision by another chain member counts into precision — a `by`
    starting with `hire:`. A decision made online on the board is not stored
    locally and does not exist here; `human` in the data is history from before
    the trail, and `chain` is precisely nobody having decided. Neither belongs
    in precision's numerator.
    """

    def __init__(self) -> None:
        self.accepted = self.rejected = self.deferred = self.undecided = 0
        # What the pack thought of the findings that turned out each way. A
        # pack that gives everything 90 and has precision 0.4 is broken in a
        # way no other number here can show, and both halves were already
        # being written.
        self.scores: dict[str, list[int]] = {"accepted": [], "rejected": []}

    def score(self, state: str | None, by: str | None, value) -> None:
        if not isinstance(value, int) or not (by or "").startswith("hire:"):
            return
        if state in ("accepted", "sent"):
            self.scores["accepted"].append(value)
        elif state == "rejected":
            self.scores["rejected"].append(value)

    def add(self, state: str | None, by: str | None = None) -> None:
        is_hire = bool(by) and by.startswith("hire:")
        # `sent` (dispatched to the board) counts the same as the older
        # `accepted` — both mean the finding held up.
        if state in ("accepted", "sent") and is_hire:
            self.accepted += 1
        elif state == "rejected" and is_hire:
            self.rejected += 1
        elif state == "deferred":
            self.deferred += 1
        elif state is None:
            self.undecided += 1
        # else: `sent`/`rejected` by something other than a chain member — a
        # person, or `chain` dispatching what nobody judged. Terminal, but
        # not a verdict this tool can grade.

    @property
    def decided(self) -> int:
        return self.accepted + self.rejected

    def as_dict(self) -> dict:
        def mean(values: list[int]):
            return round(sum(values) / len(values), 1) if values else None

        return {
            "accepted": self.accepted, "rejected": self.rejected,
            "deferred": self.deferred, "undecided": self.undecided,
            "precision": _ratio(self.accepted, self.decided),
            # When these two do not differ, the score is measuring nothing —
            # and that is finally visible instead of merely suspected.
            "scoreAccepted": mean(self.scores["accepted"]),
            "scoreRejected": mean(self.scores["rejected"]),
        }


class Cycle:
    """One lifecycle of one output type, counted by POLARITY.

    `Tally` above knows the words `accepted`, `sent` and `rejected`, which is
    exactly the assumption this whole change exists to remove: a bet is
    `selected`, a decision is `upheld`, a bug is `confirmed`. Here the core
    counts what the pack said the answer means and nothing else, and the pack
    also supplies the name of the resulting ratio — `selection_rate`,
    `success_rate`, `confirmation_rate`.

    **One ratio per lifecycle, never per type.** A bet is asked two
    questions — was it chosen, and did it work — and
    `(selected + successful) / everything` is neither. `requires` is what
    keeps an unchosen bet out of the second denominator, the same rule
    `Tally` applies to findings nobody decided on.

    The population differs from `precision` on purpose. Precision counts only
    a chain member's verdict, because a person deciding a finding does it on
    the board and nothing local sees it. A bet has no board: the founder
    chooses it here, so `human` is the signal rather than pre-trail noise.
    """

    def __init__(self, metric: str | None = None) -> None:
        self.metric = metric
        self.positive = self.negative = self.neutral = self.undecided = 0

    def add(self, polarity: str | None) -> None:
        if polarity == "positive":
            self.positive += 1
        elif polarity == "negative":
            self.negative += 1
        elif polarity == "neutral":
            self.neutral += 1
        else:
            self.undecided += 1

    @property
    def decided(self) -> int:
        return self.positive + self.negative

    def as_dict(self) -> dict:
        return {"metric": self.metric, "value": _ratio(self.positive, self.decided),
                "positive": self.positive, "negative": self.negative,
                "neutral": self.neutral, "undecided": self.undecided}


def _method(rec: dict) -> str | None:
    """Which version of the pack's method ran — `context.skill.sha256`, short.

    An A/B test of a pack built out of one hash: rewrite `SKILL.md`, keep
    running, and the two versions separate themselves in the numbers without
    anyone having tagged the rewrite. `None` for a run recorded before
    context fingerprints existed, so those stay out rather than pooling into
    a bucket that pretends to be one method.
    """
    skill = ((rec.get("context") or {}).get("skill") or {})
    digest = skill.get("sha256")
    return f"{rec.get('pack') or '?'} {digest[:8]}" if digest else None


def _who(rec: dict) -> tuple[str, str, str]:
    """Model, provider and worker of a run — the three ways to slice by who did it.

    There is no roster: `worker` is the naming convention `pack@provider`, the
    same identity `runs.worker_id` writes into `by`. It slices finer than
    `provider` alone once a project runs the same pack on two providers.
    """
    agent = rec.get("agent") or {}
    cost = rec.get("cost") or {}
    model = agent.get("model") or cost.get("model") or "default"
    provider = agent.get("provider") or cost.get("provider") or "default"
    pack = rec.get("pack") or "?"
    return model, provider, agent.get("hire") or f"{pack}@{provider}"


#: How many runs back a dimension may have found nothing before it is worth
#: naming as a candidate for deletion. Not a verdict — a dimension can be
#: right and rare — but a dimension that has not fired in twenty runs is
#: costing a share of every run's context for nothing.
SILENT_AFTER = 20

#: How much decided history a pack needs before its method is worth rewriting.
#: A condition, not a warning: a pack with five findings nobody decided on has
#: nothing to learn from, and a revision against them produces a differently
#: random pack rather than a better one — which is worse than leaving it alone,
#: because it also destroys the one method whose numbers were known.
REVISE_MINIMUM = 10

#: How many findings of each outcome go into the brief as examples. Three, and
#: chosen for variety rather than for being interesting: Anthropic's own note
#: on few-shot prompting is "diverse, canonical examples", not edge cases
#: stuffed into a prompt.
EXAMPLES = 3


def for_author(project: Project, pack_name: str) -> dict:
    """Everything about one pack that could change how its method is written.

    Not a dashboard. `agency metrics` answers "how is this project doing"; this
    answers one question, for one reader, and the reader may be an agent: what
    in this pack's `SKILL.md` is wrong?

    Every number carries its own denominator, because the failure mode here is
    specific and expensive — a dimension with one decided finding is not a
    signal, and a revision that treats it as one makes the pack differently
    random rather than better.
    """
    picked = [r for r in load_runs(project) if r.record().get("pack") == pack_name]
    whole = collect(project, picked)

    dims: dict[str, dict] = {}
    last_seen: dict[str, int] = {}
    gated: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    examples: dict[str, list[dict]] = {"accepted": [], "rejected": []}
    blocked: list[dict] = []
    methods: dict[str, dict] = {}
    denied_tools: dict[str, int] = defaultdict(int)
    stop_blocks = over_budget = 0

    for index, run in enumerate(picked):
        rec = run.record()
        agent = rec.get("agent") or {}
        dec = decisions(run)

        if rec.get("status") == "blocked":
            blocked.append({"run": run.id, "why": rec.get("exitReason"),
                            "at": rec.get("startedAt")})
        stop_blocks += agent.get("stopBlocks") or 0
        over_budget += 1 if (rec.get("cost") or {}).get("overBudget") else 0
        for tool in (agent.get("denied") or {}).get("tools") or []:
            denied_tools[tool] += 1

        digest = ((rec.get("context") or {}).get("skill") or {}).get("sha256")
        if digest:
            m = methods.setdefault(digest[:8], {"runs": 0, "accepted": 0, "rejected": 0,
                                                "firstSeen": rec.get("startedAt")})
            m["runs"] += 1

        for reason, n in (rec.get("gatedBy") or {}).items():
            gated["—"][reason] += n

        for f in run.findings():
            dim = f.get("dimension") or "—"
            last_seen.setdefault(dim, index)
            d = dec.get(f.get("id"))
            state = d["state"] if d else None
            if state in ("sent", "accepted"):
                bucket = "accepted"
            elif state == "rejected":
                bucket = "rejected"
            else:
                continue
            if digest and digest[:8] in methods:
                methods[digest[:8]][bucket] += 1
            if len(examples[bucket]) < EXAMPLES:
                examples[bucket].append({
                    "title": f.get("title"), "dimension": dim,
                    "score": f.get("score"), "scoreReason": f.get("scoreReason"),
                    "reason": (d or {}).get("reason"),
                    "note": (d or {}).get("note"),
                })

    for dim, tally in whole["byDimension"].items():
        row = dict(tally)
        row["decided"] = tally["accepted"] + tally["rejected"]
        # The sentence that keeps a revision honest. One decided finding is not
        # a precision of 1.0, it is one finding.
        row["signal"] = row["decided"] >= 5
        row["silentFor"] = (len(picked) if dim not in last_seen
                            else last_seen[dim])
        dims[dim] = row

    pages_ = [p for p in _knowledge_pages(project, pack_name) if p.get("stale")]

    return {
        "pack": pack_name,
        "runs": len(picked),
        # Which population every cost number below came from (Krok 14). A brief
        # that mixes attended and unattended leads to a revision resting on an
        # average over nothing.
        "population": whole["cost"]["population"],
        "triage": whole["triage"],
        "byDimension": dims,
        "gatedBy": {k: dict(v) for k, v in gated.items()} or None,
        "rejectReasons": whole["rejectReasons"],
        "examples": examples,
        "blocked": blocked,
        "deniedTools": dict(denied_tools) or None,
        "stopBlocks": stop_blocks,
        "overBudgetRuns": over_budget,
        "usdPerSentFinding": whole["cost"].get("usdPerSentFinding"),
        # What happened after the last change to the method itself.
        "byMethod": methods,
        "stalePages": [{"title": p.get("title"), "path": p.get("path")} for p in pages_],
    }


def _knowledge_pages(project: Project, pack_name: str) -> list[dict]:
    from . import knowledge
    return knowledge.pages(project, pack_name)


def author_brief(data: dict) -> str:
    """The same thing as markdown, because a person has to be able to read it.

    That is not a nicety, it is the acceptance test of this whole step: if a
    founder cannot say what to change in `SKILL.md` after reading this, an
    agent will not manage it either, and the revision it writes will be
    confident about nothing.
    """
    p = data["population"]
    lines = [f"# What {data['pack']} has been doing", "",
             f"{data['runs']} runs. Cost and behaviour numbers below come from "
             f"{p.get('unattended', 0)} of them (streamed only); "
             f"{p.get('attended', 0)} were attended and recorded neither.", ""]

    t = data["triage"]
    decided = t["accepted"] + t["rejected"]
    lines += ["## Precision", "",
              f"{t['accepted']} accepted / {t['rejected']} rejected"
              + (f" — precision {t['precision']}" if t["precision"] is not None
                 else " — nothing decided yet, so there is no precision"),
              ""]
    if decided < REVISE_MINIMUM:
        lines += [f"**{decided} decided findings is not enough to revise on.** "
                  f"A method rewritten against this many is differently random, "
                  f"not better. Run the pack more, decide what it finds, come back.",
                  ""]

    lines += ["## By dimension", "",
              "| dimension | decided | precision | signal? | last found something |",
              "|---|---|---|---|---|"]
    for dim, row in sorted(data["byDimension"].items()):
        silent = row["silentFor"]
        when = "never" if silent >= data["runs"] and data["runs"] else f"{silent} runs ago"
        lines.append(f"| {dim} | {row['decided']} | "
                     f"{row['precision'] if row['precision'] is not None else '—'} | "
                     f"{'yes' if row['signal'] else 'too few to tell'} | {when} |")
    quiet = [d for d, r in data["byDimension"].items() if r["silentFor"] >= SILENT_AFTER]
    if quiet:
        lines += ["", f"Silent for {SILENT_AFTER}+ runs: **{', '.join(sorted(quiet))}** "
                  f"— candidates for deletion. A dimension can be right and rare, "
                  f"but it costs a share of every run's context either way."]
    lines.append("")

    if data["rejectReasons"]:
        lines += ["## Why findings were rejected", ""]
        lines += [f"- {reason}: {n}" for reason, n in data["rejectReasons"].items()]
        lines.append("")

    for bucket, heading in (("accepted", "Findings that held up"),
                            ("rejected", "Findings that did not")):
        if data["examples"][bucket]:
            lines += [f"## {heading}", ""]
            for e in data["examples"][bucket]:
                bits = [f"**{e['title']}** ({e['dimension']}, score {e['score']})"]
                if e.get("scoreReason"):
                    bits.append(f"  - it rested on: {e['scoreReason']}")
                if e.get("reason"):
                    bits.append(f"  - rejected as `{e['reason']}`"
                                + (f": {e['note']}" if e.get("note") else ""))
                lines += ["- " + bits[0]] + bits[1:]
            lines.append("")

    if data["blocked"]:
        lines += ["## Runs that could not finish", "",
                  "A wall hit twice is a `needs` or a `SKILL.md` problem, not a "
                  "project problem.", ""]
        lines += [f"- {b['run'][:10]}: {b['why'] or 'see blocked.md'}" for b in data["blocked"]]
        lines.append("")

    trouble = []
    if data["deniedTools"]:
        trouble.append("- refused tools: "
                       + ", ".join(f"{k} ({v} runs)" for k, v in data["deniedTools"].items())
                       + " — either `needs` is too narrow or the method reaches for "
                         "something it should not")
    if data["stopBlocks"]:
        trouble.append(f"- sent back to fix findings.json {data['stopBlocks']}x — a pack "
                       f"that needs a second round every time has a SKILL.md problem")
    if data["overBudgetRuns"]:
        trouble.append(f"- over its own budget in {data['overBudgetRuns']} runs")
    if data["usdPerSentFinding"] is not None:
        trouble.append(f"- ${data['usdPerSentFinding']:.2f} per finding that reached the board")
    if trouble:
        lines += ["## How the runs themselves went", ""] + trouble + [""]

    if len(data["byMethod"]) > 1:
        lines += ["## What happened after the method changed", "",
                  "| SKILL.md | runs | accepted | rejected |", "|---|---|---|---|"]
        for digest, m in sorted(data["byMethod"].items(),
                                key=lambda kv: kv[1]["firstSeen"] or ""):
            lines.append(f"| {digest} | {m['runs']} | {m['accepted']} | {m['rejected']} |")
        lines.append("")

    if data["stalePages"]:
        lines += ["## Pack pages nobody has reviewed lately", ""]
        lines += [f"- {p['title']}" for p in data["stalePages"]]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def collect(project: Project, runs: list[Run] | None = None) -> dict:
    selected = runs if runs is not None else load_runs(project)
    now = datetime.now(timezone.utc)

    overall = Tally()
    by_dimension: dict[str, Tally] = defaultdict(Tally)
    by_severity: dict[str, Tally] = defaultdict(Tally)
    by_model: dict[str, Tally] = defaultdict(Tally)
    by_provider: dict[str, Tally] = defaultdict(Tally)
    by_hire: dict[str, Tally] = defaultdict(Tally)
    by_pack: dict[str, Tally] = defaultdict(Tally)
    by_skill: dict[str, Tally] = defaultdict(Tally)
    reasons: dict[str, int] = defaultdict(int)
    gated_by: dict[str, int] = defaultdict(int)
    # Only for types a pack wrote down (`outputs.own_types`). `finding` is
    # everybody's whether they asked or not and its number already has a name.
    by_cycle: dict[tuple[str, str, str], Cycle] = {}
    packs_seen: dict[str, object] = {}

    def pack_of(name: str):
        if name not in packs_seen:
            try:
                packs_seen[name] = packs.load(name, project)
            except SystemExit:
                packs_seen[name] = None
        return packs_seen[name]

    def count_cycle(pack_name: str, finding: dict, answers: dict) -> None:
        """Every answer an output got, each under the question it answered.

        A bet marked `selected` and later `successful` answers two questions,
        and both count: that is what makes `selection_rate` and `success_rate`
        two independent numbers rather than a mixture. `answers` comes from
        `runs.verdicts()`, which is the one place the event log is folded.

        `requires` decides which questions are still OPEN, never which answers
        count. A bet nobody chose is not pending an outcome — it has no outcome
        to have, and counting it as undecided would drag `success_rate`'s
        denominator down with every bet the founder turned down. But an answer
        that was actually given is evidence the question was asked, whatever
        the ledger says about the step before it: dropping a recorded verdict
        because its precondition was never written down would throw away the
        one thing here nobody can reconstruct.
        """
        pack = pack_of(pack_name)
        kind = str(finding.get("type") or outputs.DEFAULT_TYPE)
        if not pack or kind not in outputs.own_types(pack):
            return
        policy = outputs.policy_for(pack, kind)

        def cell(cycle) -> Cycle:
            key = (pack_name, kind, cycle.name)
            if key not in by_cycle:
                by_cycle[key] = Cycle(cycle.metric)
            return by_cycle[key]

        def still_open(cycle) -> bool:
            """Whether an unanswered question is pending, or was never asked."""
            need = cycle.requirement
            if need is None:
                return True
            name, required_kind = need
            answered = answers.get(name)
            if answered is None:
                return False
            return not required_kind or answered.get("state") == required_kind

        for cycle in policy.lifecycles:
            # An output can also carry an answer whose lifecycle nothing could
            # resolve (`verdicts()` files those under `None`). It answers no
            # question here, so every question stays as it was.
            ev = answers.get(cycle.name)
            if ev is not None:
                cell(cycle).add(cycle.polarity(str(ev.get("state") or "")))
            elif still_open(cycle):
                cell(cycle).add(None)

    raw = kept = duplicates = sent = 0
    ages: list[float] = []
    run_rows = []

    # Two populations, and until this split existed they were averaged
    # together. `turns`, `usd` and `denied` exist ONLY for a streamed
    # (unattended) run — an attended session inherits the terminal and nothing
    # counts for it — so a mean over "all runs" was a mean over a set half of
    # which had no data. Each total therefore carries how many runs it came
    # from, and a number nothing fed stays `None` rather than becoming zero.
    #
    # Wall clock is the exception and gets its own counter: `--wait` measures
    # it for attended runs too, so its population is "runs that were waited
    # for", which is neither of the other two.
    pop = {"runs": 0, "attended": 0, "unattended": 0,
           "usd": 0, "turns": 0, "denied": 0, "wallClockSeconds": 0}
    wall = 0.0
    usd_total = 0.0
    turns_total = denied_total = 0

    # A duplicate has to be able to ask its original how it was decided.
    #
    # This is what makes two providers over one pull request measurable at all.
    # The second one to arrive is marked as a duplicate and never reaches
    # triage — so under the per-worker breakdowns it would look like it found
    # nothing, when in fact it independently found the same true thing. In the
    # overall precision it stays excluded: counting one finding twice would
    # inflate the number the whole tool is judged by.
    index: dict[str, dict] = {}
    verdict_of: dict[str, str | None] = {}
    verdict_by: dict[str, str | None] = {}
    for run in selected:
        dec = decisions(run)
        for f in run.findings():
            fid = f.get("id")
            if not fid:
                continue
            index[fid] = f
            d = dec.get(fid)
            verdict_of[fid] = d.get("state") if d else None
            verdict_by[fid] = normalize_by(d.get("by")) if d else None

    def origin_state(f: dict) -> tuple[str | None, str | None]:
        """The decision of the finding this one duplicates, and who made it.
        Bounded so a duplicateOf cycle in a hand-edited file cannot hang the
        metrics."""
        cur = f
        for _ in range(8):
            nxt = cur.get("duplicateOf")
            if not nxt or nxt not in index:
                return None, None
            cur = index[nxt]
            if cur.get("state") != "duplicate":
                fid = cur.get("id")
                return verdict_of.get(fid), verdict_by.get(fid)
        return None, None

    def origin_hire(f: dict) -> str | None:
        cur = f
        for _ in range(8):
            nxt = cur.get("duplicateOf")
            if not nxt or nxt not in index:
                return None
            cur = index[nxt]
            run_id = cur.get("runId")
            if cur.get("state") != "duplicate":
                for r in selected:
                    if r.id == run_id:
                        return _who(r.record())[2]
                return None
        return None

    agreement = {"crossHire": 0, "sameHire": 0}

    for run in selected:
        rec = run.record()
        dec = decisions(run)
        answered = verdicts(run)
        counts = rec.get("counts") or {}
        raw += counts.get("raw") or 0
        kept += counts.get("kept") or 0
        duplicates += counts.get("duplicates") or 0
        if (rec.get("trigger") or {}).get("attended") is False:
            # Only from the runs whose price is known, so the two halves of
            # the fraction come from the same population.
            sent += counts.get("sent") or 0
        for k, v in (rec.get("gatedBy") or {}).items():
            gated_by[k] += v

        cost, agent = rec.get("cost") or {}, rec.get("agent") or {}
        pop["runs"] += 1
        # Explicitly false, not "not true": a record with no `trigger.attended`
        # is one nobody can vouch for, and guessing it was unattended would put
        # its missing numbers into the population that is supposed to have them.
        streamed = (rec.get("trigger") or {}).get("attended") is False
        pop["unattended" if streamed else "attended"] += 1

        seconds = cost.get("wallClockSeconds")
        if seconds is not None:
            wall += seconds
            pop["wallClockSeconds"] += 1
        if streamed:
            if cost.get("usd") is not None:
                usd_total += cost["usd"]
                pop["usd"] += 1
            if agent.get("turns") is not None:
                turns_total += agent["turns"]
                pop["turns"] += 1
            denied = (agent.get("denied") or {}).get("count")
            if denied is not None:
                denied_total += denied
                pop["denied"] += 1

        model, provider, hire = _who(rec)
        method = _method(rec)
        started = _parse(rec.get("startedAt"))
        run_undecided = 0

        for f in run.findings():
            if f.get("state") == "duplicate":
                # A repeat still says something about its author: it found the
                # same thing, only second. Credited to the worker, never to the
                # overall number.
                who_first = origin_hire(f)
                if who_first is not None:
                    agreement["crossHire" if who_first != hire else "sameHire"] += 1
                inherited, inherited_by = origin_state(f)
                if inherited is not None:
                    by_model[model].add(inherited, inherited_by)
                    by_provider[provider].add(inherited, inherited_by)
                    by_hire[hire].add(inherited, inherited_by)
                continue
            d = dec.get(f.get("id"))
            state = d["state"] if d else None
            by = normalize_by(d.get("by")) if d else None
            overall.add(state, by)
            overall.score(state, by, f.get("score"))
            by_pack[(rec.get("pack") or "—")].score(state, by, f.get("score"))
            by_dimension[f.get("dimension") or "—"].add(state, by)
            by_severity[f.get("severity") or "—"].add(state, by)
            by_model[model].add(state, by)
            by_provider[provider].add(state, by)
            by_hire[hire].add(state, by)
            by_pack[(rec.get("pack") or "—")].add(state, by)
            count_cycle(rec.get("pack") or "—", f, answered.get(f.get("id")) or {})
            if method:
                by_skill[method].add(state, by)
            if state == "rejected" and d.get("reason"):
                reasons[d["reason"]] += 1
            if state is None:
                run_undecided += 1
                if started:
                    ages.append((now - started).total_seconds() / DAY)

        run_rows.append({
            "id": run.id, "pack": rec.get("pack"), "model": model,
            "provider": provider, "hire": (rec.get("agent") or {}).get("hire"),
            "pr": (rec.get("target") or {}).get("pr"),
            "startedAt": rec.get("startedAt"), "status": rec.get("status"),
            "counts": counts, "undecided": run_undecided,
            "wallClockSeconds": (rec.get("cost") or {}).get("wallClockSeconds"),
        })

    ages.sort()
    median_age = round(ages[len(ages) // 2], 1) if ages else None

    return {
        "project": {"name": project.name, "slug": project.slug},
        "runs": len(selected),
        "findings": {
            "raw": raw, "kept": kept, "duplicates": duplicates,
            # How much work dedup saved. It grows with the number of runs over
            # the same code — and when it does not, dedup is not working.
            "dedupRatio": _ratio(duplicates, raw),
            # How much of what the agent wrote got through the gate at all.
            "gateYield": _ratio(kept, raw),
            "gatedBy": dict(gated_by) or None,
        },
        "triage": overall.as_dict(),
        "byDimension": {k: v.as_dict() for k, v in sorted(by_dimension.items())},
        "bySeverity": {k: by_severity[k].as_dict()
                       for k in ("blocker", "high", "medium", "low", "—") if k in by_severity},
        "byModel": {k: v.as_dict() for k, v in sorted(by_model.items())},
        "byProvider": {k: v.as_dict() for k, v in sorted(by_provider.items())},
        "byHire": {k: v.as_dict() for k, v in sorted(by_hire.items())},
        "byPack": {k: v.as_dict() for k, v in sorted(by_pack.items())},
        # One ratio per LIFECYCLE of each type a pack declared for itself, and
        # the pack names it. `finding` is absent unless a pack wrote it down:
        # its number is `triage.precision` above, and a second ratio over the
        # same decisions under a second name is not a measurement, it is an
        # argument about which one is right.
        "byLifecycle": {f"{p}/{t}/{c}": cell.as_dict()
                        for (p, t, c), cell in sorted(by_cycle.items())} or None,
        # Precision per version of the method. What answers "did rewriting
        # this SKILL.md help", which nothing could answer before the run
        # record carried the hash of the method it ran under.
        "bySkill": {k: v.as_dict() for k, v in sorted(by_skill.items())},
        # How often two workers land on the same thing. High cross-hire
        # agreement means the second provider is paying for confirmation
        # rather than for coverage — which is a reason to run them on
        # different pull requests, not on the same one.
        "agreement": {**agreement, "hires": len(by_hire)},
        "rejectReasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])) or None,
        "queue": {
            "undecided": overall.undecided,
            "medianAgeDays": median_age,
            # The oldest undecided finding. A backlog shows up in this number
            # sooner than in the average — an average hides behind fresh runs.
            "oldestDays": round(ages[-1], 1) if ages else None,
        },
        "cost": {
            "wallClockSeconds": round(wall) or None,
            "secondsPerKeptFinding": round(wall / kept) if kept and wall else None,
            "usd": round(usd_total, 4) if pop["usd"] else None,
            "turns": turns_total if pop["turns"] else None,
            "denied": denied_total if pop["denied"] else None,
            # What a finding that reached the board actually cost. One number,
            # and it is the one that changes a decision about a model — both
            # halves of it were already being written and nobody divided them.
            "usdPerSentFinding": (round(usd_total / sent, 4)
                                  if sent and pop["usd"] else None),
            # Every number above, and how many runs it could have come from.
            # A number without the population it came from is worse than no
            # number: it reads as if it were about all of them.
            "population": dict(pop),
        },
        "runRows": run_rows,
    }
