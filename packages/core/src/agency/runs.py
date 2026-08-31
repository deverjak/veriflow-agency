"""Běhy: příprava, run record, nálezy, rozhodnutí.

Rozdělení, na kterém všechno stojí:

    .agency/runs/<run-id>/   commituje se, JE TO PRAVDA
        run.json             záznam běhu
        context.json         co dostane pack — připravil CLI, ne agent
        findings.json        nálezy podle finding.v1
        decisions.jsonl      append-only rozhodnutí, zapisuje CLI i extension
        evidence/            výstupy code-review-graph

    ~/.agency/agency.db      NEcommituje se, kdykoli přestavitelné

Deterministickou přípravu dělá tenhle soubor, protože je testovatelná. Úsudek
dělá pack. Když se to smíchá, nejde ověřit ani jedno.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import proc
from .config import Project
from .util import out, posix, read_json, ulid, write_json

DECISION_STATES = ("accepted", "rejected", "deferred")
# Týchž pět hodnot jako pole Reason v GitHub Projectu — export tím pádem
# nepotřebuje mapování.
REJECT_REASONS = (
    "not-reproducible", "by-design", "wrong-diagnosis",
    "duplicate-missed", "out-of-scope",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- run dir

@dataclass
class Run:
    id: str
    dir: Path
    project: Project

    @property
    def record_path(self) -> Path:
        return self.dir / "run.json"

    @property
    def findings_path(self) -> Path:
        return self.dir / "findings.json"

    @property
    def decisions_path(self) -> Path:
        return self.dir / "decisions.jsonl"

    def record(self) -> dict:
        return read_json(self.record_path, default={})

    def findings(self) -> list[dict]:
        return read_json(self.findings_path, default=[])

    def save_record(self, data: dict) -> None:
        write_json(self.record_path, data)


def load_runs(project: Project) -> list[Run]:
    d = project.runs_dir
    if not d.is_dir():
        return []
    runs = [Run(p.name, p, project) for p in sorted(d.iterdir()) if (p / "run.json").is_file()]
    return sorted(runs, key=lambda r: r.id, reverse=True)


def find_run(project: Project, run_id: str | None) -> Run | None:
    runs = load_runs(project)
    if not runs:
        return None
    if run_id is None:
        return runs[0]
    for r in runs:
        if r.id == run_id or r.id.startswith(run_id):
            return r
    return None


# ---------------------------------------------------------------- příprava

def _skip(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def resolve_target(project: Project, pr: int | None, latest_merged: bool) -> dict:
    """Otevřený PR, nebo mergnutý pro retrospektivní audit.

    Bez retrospektivního režimu nemá pack co dělat na projektu, který má
    jediný mergnutý PR — a přesně tak vznikla velká část baseline korpusu.
    """
    if latest_merged:
        merged = proc.pr_list(project.root, state="merged", limit=1)
        if not merged:
            raise SystemExit("V tomhle repu není žádný mergnutý PR.")
        pr = merged[0]["number"]

    data = proc.pr_view(project.root, pr)
    if data is None:
        raise SystemExit(
            f"PR {pr if pr else '(aktuální větve)'} se nepodařilo načíst. "
            "Ověř `gh auth status` a že PR existuje."
        )

    merged_at = data.get("mergedAt")
    kind = "merged-pull-request" if merged_at else "pull-request"
    if not merged_at and data.get("state") != "OPEN":
        raise SystemExit(
            f"PR #{data['number']} je ve stavu {data['state']} a není mergnutý — nemám co recenzovat."
        )
    return {
        "kind": kind,
        "pr": data["number"],
        "url": data.get("url"),
        "title": data.get("title"),
        "headRefOid": data["headRefOid"],
        "baseRefOid": data.get("baseRefOid"),
        "mergedAt": merged_at,
        "_files": [f["path"] for f in (data.get("files") or [])],
        "_isDraft": data.get("isDraft", False),
        "_comments": data.get("comments") or [],
    }


def already_reviewed(target: dict, login: str | None) -> bool:
    """Idempotence přes marker s head commitem — tentýž commit se nerecenzuje dvakrát."""
    marker = f"<!-- agency:review-graph:{target['headRefOid']} -->"
    for c in target.get("_comments", []):
        if marker in (c.get("body") or ""):
            return True
    return False


# Tvar spuštění agenta. Ověřený je `claude`; ostatní se dají popsat
# v konfiguraci bez zásahu do kódu — proto je to tabulka dat, ne větvení.
PROVIDER_DEFAULTS = {
    "claude": {"bin": "claude", "modelFlag": "--model", "dirFlag": "--add-dir"},
    "codex": {"bin": "codex", "modelFlag": "--model", "dirFlag": None},
}


def launch_argv(cfg: dict, run_dir: str, prompt: str,
                provider: str | None = None,
                model: str | None = None) -> tuple[list[str], dict]:
    """Čím běh dokončit.

    Model je vlastnost úkolu, ne uživatele. Kódování si můžeš držet na tom
    nejsilnějším a recenzi pustit levněji — je to čtení a klasifikace, ne
    psaní. Volba se zapisuje do run recordu, protože „jaký model dává lepší
    nálezy" je otázka, kterou tenhle nástroj má umět zodpovědět čísly.
    """
    a = dict(cfg.get("agent") or {})
    name = provider or a.get("provider") or "claude"
    spec = dict(PROVIDER_DEFAULTS.get(name, {"bin": name}))
    for k in ("bin", "modelFlag", "dirFlag"):
        if k in a:
            spec[k] = a[k]

    argv = [spec.get("bin") or name]
    m = model or a.get("model")
    if m and spec.get("modelFlag"):
        argv += [spec["modelFlag"], m]
    # RUN_DIR leží mimo worktree, a právě tam se zapisuje findings.json.
    # Bez tohohle se agent ptá na zápis ven z pracovního adresáře v každém běhu.
    if spec.get("dirFlag"):
        argv += [spec["dirFlag"], run_dir]
    argv += [str(x) for x in (a.get("extraArgs") or [])]
    argv.append(prompt)
    return argv, {"provider": name, "model": m, "bin": argv[0]}


def make_worktree(project: Project, cfg: dict, target: dict) -> Path:
    """Jednorázový worktree na hlavičce PR.

    Nikdy se nečekoutuje do pracovní kopie uživatele — jeho větev i rozdělaná
    práce zůstanou netknuté.
    """
    tpl = (cfg.get("worktree") or {}).get("path") or "../{repo}-review-pr-{n}"
    name = tpl.format(repo=project.root.name, n=target.get("pr") or "x")
    wt = (project.root / name).resolve()
    if wt.exists():
        proc.git("worktree", "remove", str(wt), "--force", cwd=project.root)
    r = proc.git("fetch", "origin", f"pull/{target['pr']}/head", cwd=project.root)
    if not r.ok:
        # mergnutý PR se smazanou větví — hlavička bývá dosažitelná i tak
        proc.git("fetch", "origin", target["headRefOid"], cwd=project.root)
    ref = "FETCH_HEAD" if r.ok else target["headRefOid"]
    r = proc.git("worktree", "add", "--detach", str(wt), ref, cwd=project.root)
    if not r.ok:
        raise SystemExit(f"Worktree se nepodařilo vytvořit:\n{r.stderr.strip()}")
    return wt


def materialize_pack(project: Project, pack, wt: Path) -> list[str]:
    """Přenese nainstalované soubory packu do worktree.

    Worktree je čistý checkout hlavičky PR — vidí jen to, co je commitnuté.
    Skill packu commitnutý typicky není a být nemá: metoda patří nástroji, ne
    recenzovanému repu. Bez tohohle kroku se ve worktree metoda prostě nenajde
    a běh skončí na `Skill(...)` → Unknown skill.

    Kopíruje se z pracovní kopie projektu, ne z packu — do worktree má jít
    přesně to, co je v projektu nainstalované, včetně ruční úpravy, kterou
    upgrade označil jako blocked.
    """
    copied: list[str] = []
    for item in pack.manifest.get("installs", []):
        src = project.root / item["to"]
        if not src.is_file():
            continue
        dst = wt / item["to"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(item["to"])

    if copied:
        # Ať se zkopírované soubory netváří jako změna, kterou přinesl PR.
        # Recenzent i `git status` by je jinak viděly jako nové untracked
        # soubory — a nález „PR přidal skill" by byl artefakt nástroje.
        r = proc.git("rev-parse", "--absolute-git-dir", cwd=wt)
        if r.ok:
            info = Path(r.stdout.strip()) / "info"
            info.mkdir(parents=True, exist_ok=True)
            excl = info / "exclude"
            have = excl.read_text(encoding="utf-8") if excl.is_file() else ""
            add = [c for c in copied if c not in have]
            if add:
                with open(excl, "a", encoding="utf-8", newline="\n") as f:
                    f.write("\n# agency: soubory packu, nejsou součástí PR\n")
                    f.write("\n".join("/" + c for c in add) + "\n")

    return copied


def remove_worktree(project: Project, wt: Path) -> None:
    proc.git("worktree", "remove", str(wt), "--force", cwd=project.root)


def prepare_graph(project: Project, wt: Path, cfg: dict) -> dict:
    """Zkopíruje graf do worktree a přírůstkově doindexuje.

    `build` se ve worktree nespouští nikdy — přestavěl by celé repo kvůli stavu,
    který se za chvíli zahodí. `update` je jediný krok, který sem patří.
    """
    src = project.root / ((cfg.get("graph") or {}).get("db") or ".code-review-graph/graph.db")
    info: dict = {"tool": proc.crg_version()}

    if not src.is_file():
        info["action"] = "missing"
        return info

    dst = wt / ".code-review-graph" / "graph.db"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    mode = (cfg.get("graph") or {}).get("onStale", "update")
    if mode == "ignore":
        info["action"] = "reused"
        return info

    r = proc.crg("update", "--repo", str(wt))
    info["action"] = "update" if r.ok else "reused"
    if not r.ok:
        info["updateError"] = r.stderr.strip()[:400]
    return info


def collect_evidence(wt: Path, run: Run, target: dict, files: list[str]) -> dict:
    """Grafový signál. Tohle je ta část, kterou samotný diff nedá."""
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {}

    base = target.get("baseRefOid")
    if base:
        r = proc.crg("detect-changes", "--repo", str(wt), "--base", base, "--brief")
        (ev / "detect-changes.txt").write_text(r.stdout or r.stderr, encoding="utf-8")
        # Pozor na pořadí slov: `(\d+)\s+changed` chytí „10 changed file(s)"
        # dřív než „23 changed function(s)" a tiše podhlásí objem změny.
        import re as _re
        for key, pat in (("changedFiles", r"(\d+)\s+changed file"),
                         ("changedFunctions", r"(\d+)\s+changed function"),
                         ("affectedFlows", r"(\d+)\s+affected flow"),
                         ("untestedFunctions", r"(\d+)\s+test gap"),
                         ("riskScore", r"risk score:\s*([0-9.]+)")):
            m = _re.search(pat, r.stdout or "", _re.I)
            if m:
                stats[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))

    if files:
        r = proc.crg("impact", "--repo", str(wt), "--files", *files[:40],
                     "--depth", "2", "--max-results", "30")
        (ev / "impact.json").write_text(r.stdout or r.stderr, encoding="utf-8")

        dirs = sorted({posix(Path(f).parent) for f in files if Path(f).parent != Path(".")})
        if dirs:
            r = proc.crg("dead-code", "--repo", str(wt), "--file-pattern", dirs[0])
            (ev / "dead-code.txt").write_text(r.stdout or r.stderr, encoding="utf-8")

    return stats


def start(project: Project, pack_ref: str, cfg: dict, target: dict,
          trigger: str = "manual") -> Run:
    run_id = ulid()
    run = Run(run_id, project.runs_dir / run_id, project)
    run.dir.mkdir(parents=True, exist_ok=True)
    run.save_record({
        "id": run_id,
        "pack": pack_ref,
        "project": {"slug": project.slug, "defaultBranch": project.default_branch},
        "target": {k: v for k, v in target.items() if not k.startswith("_")},
        # Attended je vlastnost systému, ne úmysl: běh vzniká z interaktivního
        # příkazu, takže credential je subscription. Unattended větev by musela
        # mít API klíč s rozpočtem — a ta zatím neexistuje.
        "trigger": {"kind": trigger, "attended": True},
        "startedAt": now(),
        "status": "running",
    })
    return run


def write_context(run: Run, cfg: dict, target: dict, wt: Path,
                  files: list[str], skipped: int) -> None:
    review = dict(cfg.get("review") or {})
    review.pop("skipPatterns", None)
    write_json(run.dir / "context.json", {
        "runId": run.id,
        "runDir": posix(run.dir),
        "project": {"root": posix(run.project.root), "slug": run.project.slug},
        "worktree": posix(wt),
        "target": {k: v for k, v in target.items() if not k.startswith("_")},
        "files": files,
        "filesSkipped": skipped,
        "review": review,
        "sinks": cfg.get("sinks") or {},
        "schemas": {"finding": "finding.v1", "run": "run.v1"},
    })


# ---------------------------------------------------------------- rozhodnutí

def append_decision(run: Run, finding_id: str, state: str,
                    reason: str | None = None, note: str | None = None,
                    by: str = "cli") -> dict:
    """Append-only událost.

    Rozhodnutí NENÍ příkaz UI. Zapisuje sem extension i agent přes tutéž cestu —
    kdyby to byl příkaz editoru, agent by triage neuměl.
    """
    if state not in DECISION_STATES:
        raise SystemExit(f"Neznámý stav „{state}“. Povolené: {', '.join(DECISION_STATES)}")
    if state == "rejected" and not reason:
        raise SystemExit(
            "Zamítnutí vyžaduje důvod (--reason). Povolené: " + ", ".join(REJECT_REASONS)
            + "\nVolný text by dal stejnou práci a žádné číslo — precision se z něj nespočítá."
        )
    if reason and reason not in REJECT_REASONS:
        raise SystemExit(f"Neznámý důvod „{reason}“. Povolené: {', '.join(REJECT_REASONS)}")

    ev = {"kind": "decision", "findingId": finding_id, "state": state,
          "reason": reason, "note": note, "by": by, "at": now()}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def decisions(run: Run) -> dict[str, dict]:
    """Aktuální stav = přehrání událostí. Poslední zápis k danému id vyhrává."""
    cur: dict[str, dict] = {}
    if not run.decisions_path.is_file():
        return cur
    with open(run.decisions_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("kind", "decision") == "decision":
                cur[ev["findingId"]] = ev
    return cur
