"""Dočasný projekt pro testy.

Testy jádra nesmí sahat na skutečné repozitáře uživatele. Celý řetěz — běh,
nález, brána, rozhodnutí, metrika — se dá postavit nad git repem, který vznikne
a zanikne v jednom testu; a jenom takový test jde pustit stokrát za sebou.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agency import config, runs  # noqa: E402
from agency.util import ulid, write_json  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Git repo se dvěma commity a jedním souborem, který se mezi nimi posune."""
    root = tmp_path / "projekt"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")

    src = root / "src"
    src.mkdir()
    (src / "auth.ts").write_text(
        "export function getUser(id: string) {\n"
        "  const user = await repository.findUserById(id)\n"
        "  return user\n"
        "}\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "prvni")
    return root


@pytest.fixture
def project(repo: Path, tmp_path: Path, monkeypatch) -> config.Project:
    # Registr do dočasného adresáře — test nesmí zapisovat do ~/.agency.
    monkeypatch.setenv("AGENCY_HOME", str(tmp_path / "home"))
    p = config.discover(repo)
    assert p is not None
    write_json(p.agency_dir / "review-graph.json", {
        "pack": "review-graph@0.1.0",
        "review": {"minScore": 80},
        "sinks": {"runRecord": True},
    })
    return p


def make_finding(project: config.Project, run_id: str, **over) -> dict:
    """Nález, který projde kontraktem. Testy přepisují jen to, co zkoumají."""
    commit = git(project.root, "rev-parse", "HEAD")
    f = {
        "id": ulid(),
        "runId": run_id,
        "pack": "review-graph@0.1.0",
        "dimension": "correctness",
        "severity": "high",
        "title": "Uživatel se načte i po odhlášení, protože se nekontroluje relace",
        "body": ("Funkce `getUser` vrátí uživatele i pro neplatnou relaci. "
                 "Scénář: odhlášený klient pošle staré id, dostane profil."),
        "anchor": {
            "file": "src/auth.ts",
            "line": 2,
            "endLine": 3,
            "commit": commit,
            "snippet": "  const user = await repository.findUserById(id)",
            "symbol": {"name": "getUser", "range": [1, 4]},
            "body": None,
        },
        "evidence": [{"kind": "graph", "detail": "getUser nemá volajícího s kontrolou relace",
                      "source": "code-review-graph impact"}],
        "score": 90,
        "state": "candidate",
    }
    anchor_over = over.pop("anchor", None)
    f.update(over)
    if anchor_over:
        f["anchor"].update(anchor_over)
    return f


@pytest.fixture
def make_run(project: config.Project):
    """Vyrobí běh s nálezy tak, jak by ho zanechal agent."""
    def _make(findings: list[dict] | None = None, run_id: str | None = None,
              **record_over) -> runs.Run:
        rid = run_id or ulid()
        run = runs.Run(rid, project.runs_dir / rid, project)
        run.dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "id": rid, "pack": "review-graph@0.1.0",
            "project": {"slug": project.slug, "defaultBranch": "main"},
            # `headRefOid` je v run.v1 povinné — bez něj by fixture vyráběla
            # záznam, jaký by skutečný běh nikdy nezapsal.
            "target": {"kind": "pull-request", "pr": 1, "headRefOid": git(project.root, "rev-parse", "HEAD")},
            "trigger": {"kind": "manual", "attended": True},
            "startedAt": runs.now(), "status": "running",
            "agent": {"provider": "claude", "model": "sonnet", "bin": "claude"},
        }
        rec.update(record_over)
        run.save_record(rec)
        fs = findings if findings is not None else [make_finding(project, rid)]
        write_json(run.findings_path, fs)
        return run
    return _make
