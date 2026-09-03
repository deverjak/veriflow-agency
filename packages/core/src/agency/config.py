"""A project: where it is and what it is called.

The key property: everything resolves relative to the TARGET project, never
to the Agency repository itself. There is no project configuration — packs
are skills in `.claude/skills/agency-<pack>/`, committed with the project.
The core therefore knows nothing about a project beyond where it is and what
it is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import proc

AGENCY_DIR = ".agency"


@dataclass
class Project:
    root: Path
    slug: str | None
    default_branch: str | None

    @property
    def agency_dir(self) -> Path:
        return self.root / AGENCY_DIR

    @property
    def runs_dir(self) -> Path:
        return self.agency_dir / "runs"

    @property
    def skills_dir(self) -> Path:
        return self.root / ".claude" / "skills"

    @property
    def name(self) -> str:
        return self.slug or self.root.name


def discover(start: str | Path | None = None) -> Project | None:
    """Finds the project upward from the given path. No git repo, no project."""
    root = proc.repo_root(start)
    if root is None:
        return None
    return Project(
        root=root,
        slug=proc.remote_slug(root),
        default_branch=proc.default_branch(root),
    )


def require(start: str | Path | None = None) -> Project:
    p = discover(start)
    if p is None:
        raise SystemExit(
            "There is no git repository here. `agency` always works inside a project — "
            "cd into one, or use --repo <path>."
        )
    return p
