"""A temporary project for tests.

Core tests must never touch the user's real repositories. The whole chain —
run, finding, gate, decision, metric — can be built over a git repo that is
born and dies inside one test; and only such a test can be run a hundred
times in a row.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agency import config, proc, runs  # noqa: E402
from agency.util import ulid, write_json  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stderr}"
    return r.stdout.strip()


@pytest.fixture(autouse=True)
def never_launch_an_agent(monkeypatch, request):
    """No test may start a real AI runner. Ever.

    This is a safety net, not tidiness. `agency run --wait` and `agency chain`
    end at `proc.attend` / `proc.stream`, which is to say at `claude` on whatever
    machine is running the tests. A test that forgets to substitute the agent
    does not fail — it launches a real session, waits for it, and hangs the
    suite until somebody notices. That happened twice: once while `test_chain.py`
    was being written, and again when the chain switched from `attend` to
    `stream` and only the first of the two was guarded.

    Guarding one function was the mistake, so this guards both, and it lives in
    `conftest.py` rather than in one test file. A test that means to run an agent
    substitutes its own; the default is a failure that says what is missing.
    """
    def refuse(name):
        def fail(args, *a, **kw):
            raise AssertionError(
                f"a test tried to launch a real agent through proc.{name}: "
                f"{args[0]} — substitute it (monkeypatch proc.{name}) instead")
        return fail

    for name in ("attend", "stream"):
        monkeypatch.setattr(proc, name, refuse(name))


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


def install_pack(project: config.Project, name: str, manifest: dict | None = None,
                 skill_body: str = "# Test skill\n") -> Path:
    """Drops a minimal pack — `pack.json` next to `SKILL.md` — where the core
    looks for it: `.claude/skills/agency-<name>/`."""
    skill_dir = project.skills_dir / f"agency-{name}"
    skill_dir.mkdir(parents=True, exist_ok=True)
    m = {"name": name, "title": name, "description": "test pack",
         "requires": [], "target": "pull-request", "worktree": True,
         "graph": False, "prompt": "optional", "needs": [], "minScore": 70,
         "dimensions": [{"id": "correctness", "title": "Correctness"}]}
    m.update(manifest or {})
    write_json(skill_dir / "pack.json", m)
    (skill_dir / "SKILL.md").write_text(skill_body, encoding="utf-8")
    return skill_dir


@pytest.fixture
def project(repo: Path, tmp_path: Path) -> config.Project:
    p = config.discover(repo)
    assert p is not None
    install_pack(p, "review-graph", {"minScore": 80})
    return p


def make_finding(project: config.Project, run_id: str, **over) -> dict:
    """Nález, který projde kontraktem. Testy přepisují jen to, co zkoumají."""
    commit = git(project.root, "rev-parse", "HEAD")
    f = {
        "id": ulid(),
        "runId": run_id,
        "pack": "review-graph",
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
            "id": rid, "pack": "review-graph",
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
