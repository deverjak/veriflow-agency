"""Packs — specialists, the way this project finds them.

A pack IS a skill: `.claude/skills/agency-<name>/pack.json` next to its
`SKILL.md`. Nothing installs it, nothing versions it separately from the
project — it is a file in the repository, exactly as commitable and as
project-specific as the `SKILL.md` beside it. A second project gets a copy of
the directory and rewrites its `SKILL.md` and `scripts/`, not a parameter.

`pack.json` is deliberately small — everything the CORE needs to run the
pack, nothing the pack alone acts on. Facts about the project (which board,
which staging URL, which law applies) live in `SKILL.md`, where the agent
reads them; the core never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Project
from .util import read_json

PROMPT_MODES = ("required", "optional", "none")


def graph_policy(value) -> dict | None:
    """What a pack wants from the code graph. `None` when nothing.

    A missing capability is a legitimate degradation — a dimension the graph
    cannot feed skips itself and says so — but it has to be visible up front,
    in `agency doctor`, not as a silent gap mid-run.
    """
    if not value:
        return None
    if value is True:
        return {"required": [], "optional": []}
    return {"required": list(value.get("required") or []),
            "optional": list(value.get("optional") or [])}


@dataclass
class Pack:
    name: str
    manifest: dict
    skill_dir: Path

    @property
    def title(self) -> str:
        return self.manifest.get("title") or self.name

    @property
    def skill_name(self) -> str:
        """The skill's own name, e.g. `agency-po` — what the agent invokes it as."""
        return self.skill_dir.name

    @property
    def run_policy(self) -> dict:
        m = self.manifest
        prompt = str(m.get("prompt") or "none").strip().lower()
        if prompt not in PROMPT_MODES:
            raise SystemExit(
                f"pack {self.name}: prompt is “{prompt}” — known values are "
                f"{', '.join(PROMPT_MODES)}.")
        return {
            "target": m.get("target") or "workspace",
            "worktree": bool(m.get("worktree")),
            "graph": graph_policy(m.get("graph")),
            "prompt": prompt,
            "needs": [str(x).strip() for x in (m.get("needs") or []) if str(x).strip()],
            # Granted ON TOP of `needs`, but only when nobody could answer a
            # permission prompt anyway — a chain member. Attended, leaving a
            # command out of the grant is what makes Claude Code's own
            # permission dialog ask the person watching before it runs; a
            # pack puts its consequential, hard-to-undo commands here rather
            # than in `needs` so a standalone run keeps asking for them.
            "needsUnattended": [str(x).strip() for x in (m.get("needsUnattended") or []) if str(x).strip()],
        }

    @property
    def dimensions(self) -> list[dict]:
        return list(self.manifest.get("dimensions") or [])

    @property
    def min_score(self) -> int:
        return int(self.manifest.get("minScore") or 70)

    @property
    def requires(self) -> list[str]:
        return list(self.manifest.get("requires") or [])

    @property
    def sink(self) -> str | None:
        """The command that sends one gated finding to this pack's board.

        Absent on purpose for a project with no board: the finding then rests
        as `candidate` in the committed knowledge instead — git as the channel.
        """
        v = str(self.manifest.get("sink") or "").strip()
        return v or None


def available(project: Project) -> list[Pack]:
    d = project.skills_dir
    if not d.is_dir():
        return []
    found = []
    for sub in sorted(d.iterdir()):
        m = sub / "pack.json"
        if m.is_file():
            data = read_json(m)
            found.append(Pack(data["name"], data, sub))
    return found


def load(name: str, project: Project) -> Pack:
    for p in available(project):
        if p.name == name:
            return p
    known = ", ".join(p.name for p in available(project)) or "(none)"
    raise SystemExit(
        f"Unknown pack “{name}” in {project.name}. Available: {known}\n"
        f"A pack is a skill: {project.skills_dir}/agency-{name}/pack.json")
