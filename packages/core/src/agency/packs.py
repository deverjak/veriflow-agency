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

import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Project
from .util import bundled, posix, read_json

PROMPT_MODES = ("required", "optional", "none")

# The packs that ship with the tool. Their subject is this system rather than
# any project, which is what makes them copyable unchanged.
#
# `author` writes the project-specific ones, so without it a fresh repository
# has no way to get its first specialist. `verify` judges what another pack
# found — it needs to know nothing about the project either, because it works
# from the finding's anchor and the code under it. See `seed` below.
AUTHOR = "author"
VERIFY = "verify"
GENERIC = (AUTHOR, VERIFY)


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
    def superseded_keys(self) -> list[str]:
        """Manifest keys that no longer do anything, for `agency doctor`.

        `minScore` was the gate's threshold until 8 September 2026, and its
        removal is silent in the worst way: a pack that says 85 keeps saying
        it, keeps reading as a stricter pack, and nothing enforces a thing.
        The key is not an error — the live packs are in other repositories and
        history is not rewritten — but nobody should find out by measuring.
        """
        return [k for k in ("minScore",) if self.manifest.get(k) is not None]

    @property
    def budget(self) -> dict:
        """What this pack considers a normal run — `{"turns": …, "minutes": …}`.

        Both optional, and a pack that declares neither is not policed. The
        pack is the only thing that could know: a legal review reading three
        regulations and a reviewer walking one diff have nothing in common
        except that somebody eventually pays for both.

        It is a declaration, not a limit. Going over produces a line and a
        flag; only three times over is treated as a fault (see `runs.attend`),
        and that is the single exception to "nothing is killed on a heuristic"
        — because three times a pack's own declared norm is not a deviation.
        """
        b = self.manifest.get("budget") or {}
        turns = b.get("turns")
        minutes = b.get("minutes")
        return {"turns": int(turns) if turns else None,
                "minutes": float(minutes) if minutes else None}

    @property
    def requires(self) -> list[str]:
        return list(self.manifest.get("requires") or [])

    @property
    def scope(self) -> str | None:
        """The command that says what a run of this pack is ABOUT.

        It prints `[{"kind": …, "ref": …}, …]` and nothing else. The core runs
        it during preparation and intersects the result with what it already
        knows, which is how memory gets narrowed for a pack with no code graph:
        `agency-po` prints its board items, `agency-ceo` its live bets.

        Absent for a pack whose runs are about the code — the changed files and
        the graph's blast radius are the core's own vocabulary and it needs no
        help to speak it.

        Never written by the agent (see `docs/plans/outputs.md` §3.2). A scope
        the agent chose would be memory it could widen for more context and
        narrow to miss the rejections it dislikes — and it would arrive after
        the memory was already handed over.
        """
        v = str(self.manifest.get("scope") or "").strip()
        return v or None

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
    # The bootstrap is the one missing pack this tool can do something about,
    # so it is the one that gets a command instead of a path to copy by hand.
    hint = (f"\n“{name}” is one of the generic ones — `agency init` puts it here."
            if name in GENERIC else "")
    raise SystemExit(
        f"Unknown pack “{name}” in {project.name}. Available: {known}\n"
        f"A pack is a skill: {project.skills_dir}/agency-{name}/pack.json{hint}")


# ---------------------------------------------------------------- the bootstrap
#
# `agency init` is not an installer, and this is the whole of it: one generic
# pack copied into the project as ordinary, uncommitted source. Every other
# pack in the agency repository is an EXAMPLE — its `SKILL.md` carries one
# project's facts, and copying it unchanged would hire a specialist that
# judges the wrong repository. Those get written per project, by `author`,
# which is exactly why `author` is the one worth shipping.

RUN_RECORDS_IGNORE = """\
# Run records: evidence, transcripts and findings.json from one machine at
# one moment, about commits this clone may not even have. The memory beside
# them (`knowledge/`) is committed on purpose — that is the part a colleague,
# and the next run, are meant to read.
runs/
"""


def seed(project: Project, name: str = AUTHOR, force: bool = False) -> dict:
    """Copies a bundled pack into the project as a skill.

    Idempotent: a pack already there is LEFT as it is, because by then it is
    the project's own file — possibly edited, certainly committable — and
    this command has no business overwriting it. `force` copies over it, and
    even then only adds and replaces files, never deletes one the project put
    there itself.
    """
    src = bundled("packs", name)
    if not (src / "pack.json").is_file():
        raise SystemExit(
            f"This installation carries no “{name}” pack ({src}). Reinstall the core: "
            f"`uv tool install --editable <veriflow-agency>/packages/core`.")

    dst = project.skills_dir / f"agency-{name}"
    rel = posix(dst.relative_to(project.root))
    if dst.exists() and not force:
        return {"pack": name, "path": rel, "created": False, "files": []}

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    files = sorted(posix(f.relative_to(project.root))
                   for f in dst.rglob("*") if f.is_file())
    return {"pack": name, "path": rel, "created": True, "files": files}


def ignore_run_records(project: Project) -> bool:
    """Keeps `.agency/runs/` out of git. True when it wrote the file.

    In `.agency/.gitignore` rather than the project's own, so that a project
    that has never heard of this tool does not get its root file rewritten,
    and so that deleting `.agency/` takes the rule with it. An existing file
    is never touched — by then it is the project's answer, not ours.
    """
    path = project.agency_dir / ".gitignore"
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RUN_RECORDS_IGNORE, encoding="utf-8")
    return True
