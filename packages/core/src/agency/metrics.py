"""Čísla, která v baseline.md vznikala ručně.

Jedna otázka je nadřazená všem ostatním: **kolik z toho, co pack najde, je
pravda?** Bez ní se nedá rozhodnout ani o modelu, ani o tom, jestli má nástroj
žít dál — a přesně proto je krok 0 (stav `Rejected`) první v plánu.

Precision se počítá jen z ROZHODNUTÝCH nálezů. Nerozhodnutý nález není ani
pravda, ani lež; kdyby padal do jmenovatele, každý nový běh by precision
zředil a číslo by měřilo rychlost triage, ne kvalitu nálezů.

Rozpady (dimenze, severita, model) jsou tu proto, že souhrnné číslo neřekne,
co s tím. `precision 0.55` je k ničemu; `dimenze reuse 0.2, correctness 0.9`
je pokyn vypnout jednu dimenzi.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .config import Project
from .runs import Run, decisions, load_runs

DAY = 86400.0


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ratio(hit: int, total: int) -> float | None:
    """Poměr, nebo None. Nula z nuly není nula procent — je to „nevím",
    a zaokrouhlit „nevím" na 0.0 je nejlevnější způsob, jak si zalhat."""
    return round(hit / total, 3) if total else None


class Tally:
    """Přijato / zamítnuto / odloženo pro jeden řez daty."""

    def __init__(self) -> None:
        self.accepted = self.rejected = self.deferred = self.undecided = 0

    def add(self, state: str | None) -> None:
        if state == "accepted":
            self.accepted += 1
        elif state == "rejected":
            self.rejected += 1
        elif state == "deferred":
            self.deferred += 1
        else:
            self.undecided += 1

    @property
    def decided(self) -> int:
        return self.accepted + self.rejected

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted, "rejected": self.rejected,
            "deferred": self.deferred, "undecided": self.undecided,
            "precision": _ratio(self.accepted, self.decided),
        }


def _who(rec: dict) -> tuple[str, str, str]:
    """Model, provider and hire of a run — the three ways to slice by worker."""
    agent = rec.get("agent") or {}
    cost = rec.get("cost") or {}
    model = agent.get("model") or cost.get("model") or "default"
    provider = agent.get("provider") or cost.get("provider") or "default"
    return model, provider, agent.get("hire") or provider


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
    reasons: dict[str, int] = defaultdict(int)
    gated_by: dict[str, int] = defaultdict(int)

    raw = kept = duplicates = 0
    wall = 0.0
    ages: list[float] = []
    run_rows = []

    # A duplicate has to be able to ask its original how it was decided.
    #
    # This is what makes two providers over one pull request measurable at all.
    # The second one to arrive is marked as a duplicate and never reaches
    # triage — so under the per-worker breakdowns it would look like it found
    # nothing, when in fact it independently found the same true thing. In the
    # overall precision it stays excluded: counting one finding twice would
    # inflate the number the whole tool is judged by.
    index: dict[str, dict] = {}
    verdicts: dict[str, str | None] = {}
    for run in selected:
        dec = decisions(run)
        for f in run.findings():
            fid = f.get("id")
            if not fid:
                continue
            index[fid] = f
            verdicts[fid] = (dec.get(fid) or {}).get("state")

    def origin_state(f: dict) -> str | None:
        """The decision of the finding this one duplicates. Bounded so a
        duplicateOf cycle in a hand-edited file cannot hang the metrics."""
        cur = f
        for _ in range(8):
            nxt = cur.get("duplicateOf")
            if not nxt or nxt not in index:
                return None
            cur = index[nxt]
            if cur.get("state") != "duplicate":
                return verdicts.get(cur.get("id"))
        return None

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
    # Kill criteria adaptéru recallu, mechanicky. `foreign` je počet zásahů,
    # které nezapsala Agency — když po deseti bězích zůstane nula, dostával
    # běh zpátky jen to, co má v bundlu, a adaptér nepřinesl nic.
    recall = {"runs": 0, "hits": 0, "foreign": 0, "errors": 0}

    for run in selected:
        rec = run.record()
        dec = decisions(run)
        counts = rec.get("counts") or {}
        raw += counts.get("raw") or 0
        kept += counts.get("kept") or 0
        duplicates += counts.get("duplicates") or 0
        for k, v in (rec.get("gatedBy") or {}).items():
            gated_by[k] += v
        wall += ((rec.get("cost") or {}).get("wallClockSeconds") or 0)

        evidence = rec.get("evidence") or {}
        if "recalled" in evidence or "recallError" in evidence:
            recall["runs"] += 1
            recall["hits"] += evidence.get("recalled") or 0
            recall["foreign"] += evidence.get("recalledForeign") or 0
            recall["errors"] += 1 if evidence.get("recallError") else 0

        model, provider, hire = _who(rec)
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
                inherited = origin_state(f)
                if inherited is not None:
                    by_model[model].add(inherited)
                    by_provider[provider].add(inherited)
                    by_hire[hire].add(inherited)
                continue
            d = dec.get(f.get("id"))
            state = d["state"] if d else None
            overall.add(state)
            by_dimension[f.get("dimension") or "—"].add(state)
            by_severity[f.get("severity") or "—"].add(state)
            by_model[model].add(state)
            by_provider[provider].add(state)
            by_hire[hire].add(state)
            by_pack[(rec.get("pack") or "—")].add(state)
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
            # Kolik práce dedup ušetřil. Roste s počtem běhů nad týmž kódem —
            # a když neroste, dedup nefunguje.
            "dedupRatio": _ratio(duplicates, raw),
            # Kolik z toho, co agent napsal, vůbec prošlo bránou.
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
        # How often two workers land on the same thing. High cross-hire
        # agreement means the second provider is paying for confirmation
        # rather than for coverage — which is a reason to run them on
        # different pull requests, not on the same one.
        "agreement": {**agreement, "hires": len(by_hire)},
        "rejectReasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])) or None,
        "queue": {
            "undecided": overall.undecided,
            "medianAgeDays": median_age,
            # Nejstarší nerozhodnutý nález. Zácpa se pozná dřív z tohohle čísla
            # než z průměru — průměr se schová za čerstvé běhy.
            "oldestDays": round(ages[-1], 1) if ages else None,
        },
        "cost": {
            "wallClockSeconds": round(wall) or None,
            "secondsPerKeptFinding": round(wall / kept) if kept and wall else None,
        },
        # None, dokud si recall nikdo nezapnul — o vypnutém experimentu nemá
        # smysl reportovat nulu.
        "recall": recall if recall["runs"] else None,
        "runRows": run_rows,
    }
