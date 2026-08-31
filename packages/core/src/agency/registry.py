"""Seznam projektů, ve kterých Agency něco dělá.

Pravda o projektu je v projektu (`<projekt>/.agency/`). Tenhle registr je
ukazatel, ne úložiště — smí kdykoli zaniknout a postaví se znovu tím, že
v projektu něco spustíš. Ve stejné třídě jako `agency.db`.

K čemu je: portfolio přehled bez otevřeného projektu. Bez něj by „ukaž mi
nálezy napříč projekty" znamenalo, že si uživatel čtyři cesty pamatuje sám.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import Project
from .util import posix, read_json, write_json


def home() -> Path:
    return Path(os.environ.get("AGENCY_HOME") or (Path.home() / ".agency"))


def path() -> Path:
    return home() / "projects.json"


def load() -> list[dict]:
    data = read_json(path(), default={"version": 1, "projects": []})
    return data.get("projects") or []


def remember(project: Project) -> None:
    """Zapíše projekt do registru. Volá se při každé operaci, která v projektu
    něco mění — registr tak nikdy nemá být plněný ručně."""
    rows = [p for p in load() if p.get("root") != posix(project.root)]
    rows.append({
        "root": posix(project.root),
        "name": project.name,
        "slug": project.slug,
    })
    write_json(path(), {"version": 1, "projects": sorted(rows, key=lambda p: p["name"])})


def forget(root: str) -> bool:
    rows = load()
    keep = [p for p in rows if p.get("root") != posix(root)]
    if len(keep) == len(rows):
        return False
    write_json(path(), {"version": 1, "projects": keep})
    return True


def resolve() -> list[Project]:
    """Registr → živé projekty. Zmizelé cesty se tiše přeskočí; smazaný projekt
    není chyba registru, jen zastaralý ukazatel."""
    from . import config
    out = []
    for row in load():
        p = config.discover(row["root"])
        if p is not None:
            out.append(p)
    return out
