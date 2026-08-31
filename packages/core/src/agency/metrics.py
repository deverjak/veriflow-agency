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


def collect(project: Project, runs: list[Run] | None = None) -> dict:
    selected = runs if runs is not None else load_runs(project)
    now = datetime.now(timezone.utc)

    overall = Tally()
    by_dimension: dict[str, Tally] = defaultdict(Tally)
    by_severity: dict[str, Tally] = defaultdict(Tally)
    by_model: dict[str, Tally] = defaultdict(Tally)
    by_pack: dict[str, Tally] = defaultdict(Tally)
    reasons: dict[str, int] = defaultdict(int)
    gated_by: dict[str, int] = defaultdict(int)

    raw = kept = duplicates = 0
    wall = 0.0
    ages: list[float] = []
    run_rows = []

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

        model = ((rec.get("agent") or {}).get("model")
                 or (rec.get("cost") or {}).get("model") or "výchozí")
        started = _parse(rec.get("startedAt"))
        run_undecided = 0

        for f in run.findings():
            if f.get("state") == "duplicate":
                continue
            d = dec.get(f.get("id"))
            state = d["state"] if d else None
            overall.add(state)
            by_dimension[f.get("dimension") or "—"].add(state)
            by_severity[f.get("severity") or "—"].add(state)
            by_model[model].add(state)
            by_pack[(rec.get("pack") or "—")].add(state)
            if state == "rejected" and d.get("reason"):
                reasons[d["reason"]] += 1
            if state is None:
                run_undecided += 1
                if started:
                    ages.append((now - started).total_seconds() / DAY)

        run_rows.append({
            "id": run.id, "pack": rec.get("pack"), "model": model,
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
        "byPack": {k: v.as_dict() for k, v in sorted(by_pack.items())},
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
        "runRows": run_rows,
    }
