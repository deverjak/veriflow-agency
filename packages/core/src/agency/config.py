"""Projekt a jeho konfigurace.

Klíčová vlastnost: všechno se rozpouští relativně k CÍLOVÉMU PROJEKTU, nikdy
k repu Agency. To je celý důvod, proč tenhle nástroj vznikl — původní agenti
měli `repoRoot` mířící na sebe, a proto neuměli druhý projekt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import proc
from .util import read_json, strip_comments, write_json

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
    def name(self) -> str:
        return self.slug or self.root.name

    def pack_config_path(self, pack: str) -> Path:
        return self.agency_dir / f"{pack}.json"

    def pack_config(self, pack: str) -> dict | None:
        data = read_json(self.pack_config_path(pack), default={})
        return strip_comments(data) if data else None

    def installed_path(self) -> Path:
        return self.agency_dir / "installed.json"

    def installed(self) -> dict:
        return read_json(self.installed_path(), default={"version": 1, "packs": {}})

    def save_installed(self, data: dict) -> None:
        write_json(self.installed_path(), data)


def discover(start: str | Path | None = None) -> Project | None:
    """Najde projekt od zadané cesty nahoru. Bez git repa projekt není."""
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
            "Tady není git repozitář. `agency` pracuje vždy uvnitř projektu — "
            "přejdi do něj, nebo použij --repo <cesta>."
        )
    return p


def detect(project: Project) -> dict:
    """Co si nástroj o projektu domyslí sám. `agency init` se pak ptá jen na zbytek."""
    root = project.root
    facts: dict = {
        "slug": project.slug,
        "defaultBranch": project.default_branch,
        "hasGraph": (root / ".code-review-graph" / "graph.db").is_file(),
    }

    # CI příkaz — hledá se v package.json, ne hádá
    pkg = read_json(root / "package.json", default=None)
    if isinstance(pkg, dict):
        scripts = pkg.get("scripts") or {}
        for cand in ("verify", "check", "ci", "test"):
            if cand in scripts:
                facts["verifyCommand"] = f"npm run {cand}"
                break
    facts.setdefault("verifyCommand", None)

    # Odkazy na dokumentaci — jen pokud tam soubor s tou sekcí opravdu je
    claude = root / "CLAUDE.md"
    if claude.is_file():
        text = claude.read_text(encoding="utf-8", errors="replace").lower()
        facts["rules"] = "CLAUDE.md#rules-that-will-bite-you" if "will bite you" in text else None
        facts["docMap"] = "CLAUDE.md#where-the-truth-lives" if "where the truth lives" in text else None
    else:
        facts["rules"] = facts["docMap"] = None

    skills = root / ".claude" / "skills"
    facts["existingSkills"] = sorted(p.name for p in skills.iterdir()) if skills.is_dir() else []
    return facts
