"""The project roster: who is hired here and what they work with.

A pack is a METHOD. A hire is one worker who works by that method — same
method, different runner. “Reviewer · sonnet” and “Reviewer · codex” are two
roster entries over a single pack.

Why at all: two providers on the same pull request is the cheapest way to find
out which of them is right. Without a roster the only way to do it would be to
rewrite `agent.provider` in the configuration between runs — and the run
records would then claim it was the same work, merely configured differently.

Shared memory is not a feature that had to be added — it follows from a hire
having NO storage of its own:

    .agency/<pack>.json     one configuration per pack (brief, thresholds, target)
    .agency/runs/           one finding queue, one dedup, one set of metrics
    .agency/hires.json      the roster — the only thing that is per hire

`agent.hire` goes into the run record, so “which specialist found this” is a
question for the data, not for memory. Findings are not partitioned by it: a
finding from run A deduplicates against one from run B even when a different
provider found it — that is the point. How often two providers agree is
measured by `metrics.agreement`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Project
from .util import read_json, write_json

ID_RE = re.compile(r"^[a-z0-9][a-z0-9@.:_-]*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Hire:
    id: str
    pack: str
    provider: str
    model: str | None = None
    title: str | None = None
    createdAt: str | None = None
    # Not in the file — derived from a pack that is installed with nobody on it.
    # See `roster()`.
    implicit: bool = False

    @property
    def label(self) -> str:
        """What tells this hire apart from its siblings.

        The model when there is one — “sonnet” says more than “claude”.
        Otherwise the provider.
        """
        return self.model or self.provider

    @property
    def slug(self) -> str:
        """A name usable inside a path. Without it two parallel runs over the
        same pull request would collide in one worktree directory."""
        return re.sub(r"[^a-z0-9]+", "-", self.id.lower()).strip("-") or "hire"

    def display(self, pack_title: str | None = None) -> str:
        if self.title:
            return self.title
        return f"{pack_title or self.pack} · {self.label}"

    def as_dict(self) -> dict:
        return {"id": self.id, "pack": self.pack, "provider": self.provider,
                "model": self.model, "title": self.title, "createdAt": self.createdAt,
                "label": self.label, "implicit": self.implicit}


def _path(project: Project):
    return project.agency_dir / "hires.json"


def load(project: Project) -> list[Hire]:
    data = read_json(_path(project), default={"version": 1, "hires": []})
    out: list[Hire] = []
    for row in data.get("hires") or []:
        if not row.get("id") or not row.get("pack"):
            continue
        out.append(Hire(
            id=row["id"], pack=row["pack"], provider=row.get("provider") or "claude",
            model=row.get("model"), title=row.get("title"), createdAt=row.get("createdAt"),
        ))
    return out


def save(project: Project, entries: list[Hire]) -> None:
    write_json(_path(project), {
        "version": 1,
        "hires": [{k: v for k, v in h.as_dict().items()
                   if k not in ("label", "implicit")} for h in entries],
    })


def roster(project: Project) -> list[Hire]:
    """Who works here — including the worker a project has without knowing it.

    A pack installed before the roster existed has no entry, and reading that as
    "nobody hired" would be wrong twice over: the project HAS been running that
    method, and the panel would push the user to hire someone they already have.

    So an installed pack with no entry of its own contributes one derived from
    its `agent` block. Nothing is written — a read must not have side effects,
    and the day the user hires anyone for that pack the stored entry takes over.
    An implicit worker exists only where there are no stored ones for that pack,
    so the two never mix.
    """
    stored = load(project)
    have = {h.pack for h in stored}
    out = list(stored)
    for name in sorted((project.installed().get("packs") or {})):
        if name in have:
            continue
        agent = ((project.pack_config(name) or {}).get("agent")) or {}
        provider = agent.get("provider") or "claude"
        out.append(Hire(id=f"{name}@{provider}", pack=name, provider=provider,
                        model=agent.get("model"), implicit=True))
    return out


def materialize(project: Project, pack: str) -> Hire | None:
    """Write down the worker a pack has been running on all along.

    Called before anyone new is hired for that pack. Without it, hiring a
    SECOND runner would make the first one vanish: an implicit worker exists
    only where there are no stored ones, so the act of adding a colleague would
    delete the incumbent. Losing the worker you already had is the opposite of
    what "hire another one" means.
    """
    if for_pack(project, pack):
        return None
    for h in roster(project):
        if h.pack == pack and h.implicit:
            h.implicit = False
            h.createdAt = _now()
            entries = load(project)
            entries.append(h)
            save(project, entries)
            return h
    return None


def get(project: Project, hire_id: str) -> Hire | None:
    for h in load(project):
        if h.id == hire_id:
            return h
    return None


def for_pack(project: Project, pack: str) -> list[Hire]:
    return [h for h in load(project) if h.pack == pack]


def suggest_id(pack: str, provider: str, model: str | None, taken: set[str]) -> str:
    """`review-graph@claude`, and once that is taken the model joins in.

    The name is derived because nobody enjoys inventing an identifier every
    time they hire a second reviewer. `--as` stays for the case where you want
    “reviewer-strict” instead of a machine-made name.
    """
    base = f"{pack}@{provider}"
    if base not in taken:
        return base
    if model:
        with_model = f"{base}-{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}"
        if with_model not in taken:
            return with_model
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def add(project: Project, pack: str, provider: str = "claude",
        model: str | None = None, hire_id: str | None = None,
        title: str | None = None) -> Hire:
    # The incumbent gets written down before a colleague joins — otherwise it
    # would be deleted by the very act of hiring one.
    materialize(project, pack)

    entries = load(project)
    taken = {h.id for h in entries}

    if hire_id:
        hire_id = hire_id.strip().lower()
        if not ID_RE.match(hire_id):
            raise SystemExit(
                f"“{hire_id}” is not a usable id — start with a letter or a digit and "
                "use only a-z, 0-9 and - _ . : @")
        if hire_id in taken:
            raise SystemExit(f"“{hire_id}” is already hired here. `agency roster` lists them.")
    else:
        hire_id = suggest_id(pack, provider, model, taken)

    # The same pack with the same provider AND the same model a second time is
    # almost certainly a slip — two entries doing literally the same thing only
    # add noise to the roster and to the metrics. A deliberate twin goes
    # through its own `--as`.
    for h in entries:
        if h.pack == pack and h.provider == provider and h.model == model and not title:
            raise SystemExit(
                f"“{h.id}” already runs {pack} on {provider}"
                + (f" with {model}" if model else "")
                + ".\nA second identical hire would only split the roster — give it a "
                  "different model, or a name of its own with --as <id>.")

    hire = Hire(id=hire_id, pack=pack, provider=provider, model=model,
                title=title, createdAt=_now())
    entries.append(hire)
    save(project, entries)
    return hire


def remove(project: Project, hire_id: str) -> Hire | None:
    entries = load(project)
    keep = [h for h in entries if h.id != hire_id]
    if len(keep) == len(entries):
        return None
    gone = next(h for h in entries if h.id == hire_id)
    save(project, keep)
    return gone


def ensure_default(project: Project, pack: str, cfg: dict | None = None) -> Hire | None:
    """The pack's first hire, taken from its configuration.

    Called after an installation so a project never has a pack installed with
    nobody to run it. The roster fills itself in and `agency add` stays exactly
    what it was.
    """
    if for_pack(project, pack):
        return None
    written = materialize(project, pack)
    if written:
        return written
    agent = (cfg or {}).get("agent") or {}
    return add(project, pack, provider=agent.get("provider") or "claude",
               model=agent.get("model"))


def resolve(project: Project, name: str) -> tuple[str, Hire | None]:
    """`agency run <what>` — the name is either a hire or a pack.

    The order matters: a hire wins. If the pack won, a hire could never be
    named after its pack — and `review-graph@claude` is not a name anyone
    invents, so a hire with a name of its own has to stay reachable.

    A pack name with no matching hire means “its first worker”. A project with
    no roster at all (an older installation) gets `None` and the run is handed
    over from the configuration exactly as before.
    """
    everyone = roster(project)
    for h in everyone:
        if h.id == name:
            return h.pack, h

    matching = [h for h in everyone if h.pack == name]
    if matching:
        return name, matching[0]
    return name, None


def describe(project: Project, packs_by_name: dict) -> list[dict]:
    """The roster for clients: a hire plus what the pack and the machine know.

    The core assembles this, not the client. The extension would otherwise have
    to know pack names and reach into `~/.agency/providers.json`, which is
    exactly the boundary it must not cross.
    """
    from . import providers

    rows = []
    for h in roster(project):
        pack = packs_by_name.get(h.pack)
        spec = providers.spec(h.provider)
        rows.append({
            **h.as_dict(),
            "display": h.display(pack.manifest.get("title") if pack else None),
            "packTitle": (pack.manifest.get("title") if pack else None) or h.pack,
            "packInstalled": bool(pack) and bool(
                (project.installed().get("packs") or {}).get(h.pack)),
            "providerTitle": spec.get("title") or h.provider,
            "bin": spec.get("bin") or h.provider,
            "available": bool(providers.installed(h.provider)),
        })
    return rows
