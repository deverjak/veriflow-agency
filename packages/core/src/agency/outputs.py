"""Output types, and the policy a pack declares for each of them.

An agent produces more than findings. A product owner decides board items, a
CEO proposes bets and drafts outreach, QA reproduces bugs. Until now the core
knew exactly one shape — a finding with an anchor — so everything else either
deformed itself to fit (a strategic claim anchored to `footer.tsx`) or went
around the core entirely (`packs/po/SKILL.md`: *"Findings still go to the
board through the core, decisions do not"*).

The way out is NOT for the core to learn what a bet is. It is for the pack to
say **how its outputs are to be handled mechanically**, and for the core to
know nothing else:

    dedup?  what evidence is required?  what feedback exists, with what
    polarity, in which lifecycle?  may it act?  may it become memory?  how
    many per run?

`BUILD-NOW`, `distribution`, `stakeholder` — none of that reaches here. That
is the pack's domain, and the moment the core starts reading it, every future
specialist has to pretend to be a code reviewer again.

Declared in `pack.json`:

    "outputs": {
      "bet": {
        "cardinality": "many",
        "dedup": true,
        "evidence": { "required": ["document", "web_snapshot"], "min": 1 },
        "actions": "none",
        "memory": "proposes",
        "feedback": {
          "selection": { "metric": "selection_rate",
                         "kinds": { "selected": "positive",
                                    "rejected": "negative" } },
          "outcome":   { "metric": "success_rate",
                         "requires": "selection.selected",
                         "kinds": { "successful": "positive",
                                    "failed": "negative",
                                    "abandoned": "neutral" } }
        }
      }
    }

A pack that declares nothing keeps the policy it has always had, which is why
this file can land without touching a single existing pack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What an output is when it does not say. Every finding written before types
#: existed is one of these, and so is every finding written by a pack that has
#: not been rewritten — the migration window is the default, not a flag.
DEFAULT_TYPE = "finding"

#: The five reasons a rejection may carry, from `runs.REJECT_REASONS`. Not
#: imported: `runs` imports half the tool, and this file is read by the gate.
#: The duplication is a constant, and `test_outputs.py` holds the two together.
FINDING_REASONS = ("not-reproducible", "by-design", "wrong-diagnosis",
                   "duplicate-missed", "out-of-scope")

#: The policy a `finding` has always had, written down for the first time.
#: Nothing here is new behaviour — it is what the core did when a finding was
#: the only thing it could imagine.
#:
#: `evidence` is empty on purpose: which kinds a finding needs is still said
#: per DIMENSION (`ingest.required_evidence`), because for a reviewer the
#: honest answer differs by question rather than by type. A type that says it
#: overrides the dimension; one that says nothing leaves the dimension alone.
FINDING_POLICY = {
    "cardinality": "many",
    "dedup": True,
    "evidence": {},
    "actions": "sink",
    "memory": "proposes",
    "feedback": {
        "triage": {
            "metric": "precision",
            "reasons": list(FINDING_REASONS),
            "kinds": {"sent": "positive", "rejected": "negative"},
        }
    },
}

POLARITIES = ("positive", "negative", "neutral")
CARDINALITIES = ("one", "many")
ACTIONS = ("none", "sink")
MEMORY = ("never", "proposes")


@dataclass(frozen=True)
class Lifecycle:
    """One question that can be asked about an output, and its answers.

    A bet has two — *was it chosen* and *did it work* — and they must not be
    counted together: `(selected + successful) / everything` is neither a
    selection rate nor a success rate, it is a number that looks like a metric.
    `requires` keeps the second question from being asked about an output that
    failed the first, which is the same rule `metrics` already applies to
    findings nobody decided on.
    """
    name: str
    metric: str | None
    requires: str | None
    kinds: dict[str, str]
    reasons: tuple[str, ...] = ()

    def polarity(self, kind: str) -> str | None:
        return self.kinds.get(kind)


@dataclass(frozen=True)
class TypePolicy:
    """How the core handles one type of output. Never what it means."""
    name: str
    cardinality: str = "many"
    limit: int | None = None
    dedup: bool = True
    evidence: dict = field(default_factory=dict)
    actions: str = "sink"
    memory: str = "proposes"
    lifecycles: tuple[Lifecycle, ...] = ()

    @property
    def max_per_run(self) -> int | None:
        """How many of this type one run may produce, or `None` for no ceiling."""
        if self.cardinality == "one":
            return 1
        return self.limit

    @property
    def required_evidence(self) -> list[str]:
        return [str(k) for k in (self.evidence.get("required") or [])]

    @property
    def min_evidence(self) -> int:
        try:
            return max(1, int(self.evidence.get("min") or 1))
        except (TypeError, ValueError):
            return 1

    @property
    def kinds(self) -> tuple[str, ...]:
        """Every feedback kind this type accepts, across all its lifecycles."""
        seen: list[str] = []
        for cycle in self.lifecycles:
            for kind in cycle.kinds:
                if kind not in seen:
                    seen.append(kind)
        return tuple(seen)

    def lifecycle_of(self, kind: str) -> Lifecycle | None:
        """Which question this answer belongs to."""
        for cycle in self.lifecycles:
            if kind in cycle.kinds:
                return cycle
        return None

    def polarity(self, kind: str) -> str | None:
        cycle = self.lifecycle_of(kind)
        return cycle.polarity(kind) if cycle else None


def _lifecycles(raw: dict) -> tuple[Lifecycle, ...]:
    out: list[Lifecycle] = []
    for name, body in (raw or {}).items():
        body = body if isinstance(body, dict) else {}
        kinds = {str(k): str(v) for k, v in (body.get("kinds") or {}).items()}
        out.append(Lifecycle(
            name=str(name),
            metric=str(body["metric"]) if body.get("metric") else None,
            requires=str(body["requires"]) if body.get("requires") else None,
            kinds=kinds,
            reasons=tuple(str(r) for r in (body.get("reasons") or [])),
        ))
    return tuple(out)


def _policy(name: str, raw: dict) -> TypePolicy:
    raw = raw if isinstance(raw, dict) else {}
    cardinality = str(raw.get("cardinality") or "many")
    limit = raw.get("limit")
    return TypePolicy(
        name=name,
        cardinality=cardinality if cardinality in CARDINALITIES else "many",
        limit=int(limit) if isinstance(limit, int) and limit > 0 else None,
        dedup=bool(raw.get("dedup", True)),
        evidence=raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {},
        actions=str(raw.get("actions") or "sink"),
        memory=str(raw.get("memory") or "proposes"),
        lifecycles=_lifecycles(raw.get("feedback") or {}),
    )


def policies(pack) -> dict[str, TypePolicy]:
    """Every type this pack may produce.

    `finding` is always among them. A pack that redefines it gets its own
    version; a pack that says nothing at all gets exactly the behaviour it had
    before types existed.
    """
    declared = (pack.manifest.get("outputs") if pack else None) or {}
    out = {name: _policy(str(name), body) for name, body in declared.items()
           if isinstance(name, str) and name}
    out.setdefault(DEFAULT_TYPE, _policy(DEFAULT_TYPE, FINDING_POLICY))
    return out


def policy_for(pack, type_name: str | None) -> TypePolicy:
    """The policy for one output. Never `None`.

    An output whose type the pack does not declare is not dropped here — the
    gate says that, with a reason a person can read. This returns the default
    so that every other caller can stay unconditional.
    """
    name = str(type_name or DEFAULT_TYPE)
    known = policies(pack) if pack else {DEFAULT_TYPE: _policy(DEFAULT_TYPE, FINDING_POLICY)}
    return known.get(name) or _policy(name, FINDING_POLICY)


def declares(pack, type_name: str | None) -> bool:
    """Whether the pack actually claims this type, rather than inheriting it."""
    return str(type_name or DEFAULT_TYPE) in policies(pack)


def errors(pack) -> list[str]:
    """What is wrong with a pack's `outputs` block, in a person's words.

    For `agency doctor`. A policy is data the core acts on, so a typo in it is
    not a quiet default — `dedpu: false` would silently keep deduplicating and
    the pack's author would have no way to find out.
    """
    found: list[str] = []
    declared = (pack.manifest.get("outputs") if pack else None) or {}
    if declared and not isinstance(declared, dict):
        return ["`outputs` must be an object of type name → policy"]

    for name, body in declared.items():
        where = f"outputs.{name}"
        if not isinstance(body, dict):
            found.append(f"{where}: must be an object")
            continue
        card = body.get("cardinality", "many")
        if card not in CARDINALITIES:
            found.append(f"{where}.cardinality: “{card}” — one of {', '.join(CARDINALITIES)}")
        if body.get("actions", "sink") not in ACTIONS:
            found.append(f"{where}.actions: one of {', '.join(ACTIONS)}")
        if body.get("memory", "proposes") not in MEMORY:
            found.append(f"{where}.memory: one of {', '.join(MEMORY)}")

        seen: dict[str, str] = {}
        cycles = body.get("feedback") or {}
        for cycle_name, cycle in cycles.items():
            at = f"{where}.feedback.{cycle_name}"
            if not isinstance(cycle, dict) or not (cycle.get("kinds") or {}):
                found.append(f"{at}: needs `kinds`, or it is a lifecycle nobody can answer")
                continue
            for kind, polarity in (cycle.get("kinds") or {}).items():
                if polarity not in POLARITIES:
                    found.append(f"{at}.kinds.{kind}: “{polarity}” — "
                                 f"one of {', '.join(POLARITIES)}")
                if kind in seen and seen[kind] != cycle_name:
                    found.append(f"{at}.kinds.{kind}: also in "
                                 f"{where}.feedback.{seen[kind]} — a feedback kind "
                                 f"belongs to one lifecycle, or no ratio can say "
                                 f"which question it answered")
                seen[kind] = cycle_name
            need = cycle.get("requires")
            if need and str(need).split(".")[0] not in cycles:
                found.append(f"{at}.requires: “{need}” names no lifecycle of this type")
    return found
