"""Projekt a jeho konfigurace.

Klíčová vlastnost: všechno se rozpouští relativně k CÍLOVÉMU PROJEKTU, nikdy
k repu Agency. To je celý důvod, proč tenhle nástroj vznikl — původní agenti
měli `repoRoot` mířící na sebe, a proto neuměli druhý projekt.
"""

from __future__ import annotations

import re
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
            "There is no git repository here. `agency` always works inside a project — "
            "cd into one, or use --repo <path>."
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
    facts["playwright"] = detect_playwright(project)
    return facts


# Pořadí je významné: bere se první nalezený, stejně jako to dělá Playwright sám.
PLAYWRIGHT_CONFIGS = (
    "playwright.config.ts", "playwright.config.mts", "playwright.config.cts",
    "playwright.config.js", "playwright.config.mjs", "playwright.config.cjs",
)

# Kde e2e testy bývají, když je konfigurace nepojmenuje.
PLAYWRIGHT_TEST_DIRS = ("e2e", "tests/e2e", "test/e2e", "playwright", "tests/playwright", "src/e2e")


def detect_playwright(project: Project) -> dict:
    """Má projekt Playwright, a kde?

    Detekce je tu proto, aby QA sezení psalo testy v dialektu projektu — jeho
    fixtures, jeho přihlášení, jeho baseURL. Spec, který si vymyslí vlastní
    způsob přihlášení, je druhá pravda o tomtéž a rozpadne se při první změně.

    Nic se nespouští: `npx playwright --version` by na studeném cache stahoval
    balíček, a to je pro detekci příliš drahá cena.
    """
    root = project.root
    facts: dict = {"configFile": None, "testDir": None, "dependency": None,
                   "installed": False, "specs": 0}

    for name in PLAYWRIGHT_CONFIGS:
        f = root / name
        if not f.is_file():
            continue
        facts["configFile"] = name
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"""testDir\s*:\s*['"]([^'"]+)['"]""", text)
        if m:
            facts["testDir"] = m.group(1).lstrip("./").rstrip("/")
        break

    pkg = read_json(root / "package.json", default=None)
    if isinstance(pkg, dict):
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        facts["dependency"] = deps.get("@playwright/test") or deps.get("playwright")
    facts["installed"] = (root / "node_modules" / "@playwright" / "test").is_dir()

    if not facts["testDir"]:
        for cand in PLAYWRIGHT_TEST_DIRS:
            if (root / cand).is_dir():
                facts["testDir"] = cand
                break

    if facts["testDir"] and (root / facts["testDir"]).is_dir():
        facts["specs"] = sum(1 for _ in (root / facts["testDir"]).rglob("*.spec.*"))

    facts["present"] = bool(facts["configFile"] or facts["dependency"] or facts["specs"])
    return facts
