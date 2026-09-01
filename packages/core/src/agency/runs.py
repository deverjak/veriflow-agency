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

from . import proc, providers
from .config import AGENCY_DIR, Project
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
            raise SystemExit("There is no merged pull request in this repo.")
        pr = merged[0]["number"]

    data = proc.pr_view(project.root, pr)
    if data is None:
        raise SystemExit(
            f"PR {pr if pr else '(of the current branch)'} could not be loaded. "
            "Check `gh auth status` and that the PR exists."
        )

    merged_at = data.get("mergedAt")
    kind = "merged-pull-request" if merged_at else "pull-request"
    if not merged_at and data.get("state") != "OPEN":
        raise SystemExit(
            f"PR #{data['number']} is in state {data['state']} and is not merged — nothing to review."
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


def resolve_workspace_target(project: Project, since: str | None = None) -> dict:
    """Cíl bez pull requestu — projekt tak, jak je právě teď.

    QA nezkoumá diff, zkoumá běžící aplikaci. Cíl je proto pracovní kopie:
    HEAD kvůli kotvám (nález musí ukázat na řádek, který na tom commitu
    existuje) a seznam změn proti základní větvi jako vodítko, kde hledat
    nejdřív — ne jako hranice, za kterou se nesmí. Prázdný seznam změn je
    u QA normální stav, ne důvod běh odmítnout.
    """
    head = proc.head(project.root)
    if not head:
        raise SystemExit(
            "This repository has no commit yet — a finding would have nothing to anchor to."
        )

    branch = proc.git("rev-parse", "--abbrev-ref", "HEAD", cwd=project.root).stdout.strip() or "HEAD"

    base = None
    candidates = [since] if since else (
        [f"origin/{project.default_branch}", project.default_branch]
        if project.default_branch else [])
    for ref in [c for c in candidates if c]:
        r = proc.git("merge-base", "HEAD", ref, cwd=project.root)
        if r.ok and r.stdout.strip():
            base = r.stdout.strip()
            break
    if since and base is None:
        raise SystemExit(f"Ref “{since}” could not be resolved in this repository.")

    def keep(path: str) -> bool:
        # Vlastní záznamy z výčtu ven. `.agency/` se mění každým během, takže
        # by se každý běh objevil sám v sobě jako změna projektu — a stejná
        # chyba jako u materialize_pack: artefakt nástroje vypadá jako práce.
        return bool(path) and not path.endswith("/") and not path.startswith(AGENCY_DIR + "/")

    files: list[str] = []
    if base and base != head:
        r = proc.git("diff", "--name-only", base, cwd=project.root)
        if r.ok:
            files = [line.strip() for line in r.stdout.splitlines() if keep(line.strip())]

    # Rozdělaná práce patří dovnitř: aplikace, kterou QA zkouší, běží nad
    # pracovní kopií, ne nad posledním commitem. `-uall` kvůli tomu, aby
    # nesledovaný adresář byl seznam souborů, ne jedna položka „foo/“.
    dirty: list[str] = []
    for line in proc.git("status", "--porcelain", "-uall", cwd=project.root).stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if keep(path):
            dirty.append(path)

    return {
        "kind": "workspace",
        "ref": branch,
        "title": f"{branch} · {head[:8]}",
        "url": None,
        "headRefOid": head,
        "baseRefOid": base,
        "dirty": bool(dirty),
        "_files": sorted(set(files) | set(dirty)),
        "_isDraft": False,
        "_comments": [],
    }


def resolve_brief(cfg: dict, prompt: str | None = None, scenario: str | None = None) -> dict:
    """Zadání běhu: co se má tentokrát dělat.

    Dvě vrstvy, protože každá platí jinak dlouho. `standing` je to, co o
    projektu platí pořád — kde aplikace běží, co je na ní důležité — a bydlí
    v konfiguraci. `focus` je tenhle jeden běh; přijde z `--prompt`, nebo
    z pojmenovaného scénáře. Slít je do jednoho pole by znamenalo, že zadání
    jednoho běhu přepíše to, co pro projekt platí pořád.
    """
    b = cfg.get("brief") or {}
    scenarios = b.get("scenarios") or {}
    focus: str | None = None
    source: list[str] = []

    if scenario:
        if scenario not in scenarios:
            known = ", ".join(sorted(scenarios)) or "none defined in the configuration"
            raise SystemExit(f"Unknown scenario “{scenario}”. Known: {known}")
        focus = str(scenarios[scenario] or "").strip() or None
        source.append(f"scenario:{scenario}")

    if prompt and prompt.strip():
        # Volný text scénář nepřepisuje, zpřesňuje ho: „pusť smoke, ale na mobilu“.
        focus = f"{focus}\n\n{prompt.strip()}" if focus else prompt.strip()
        source.append("prompt")

    standing = (b.get("default") or "").strip() or None
    return {
        "standing": standing,
        "focus": focus,
        "scenario": scenario,
        "source": "+".join(source) or ("config" if standing else None),
    }


def review_marker(pack: str, head: str, hire_id: str | None = None) -> str:
    """The marker that says a commit has already been handled.

    It carries the hire, not just the pack. Without that a second provider on
    the same commit would hit the first one's mark and refuse to start — and
    the whole point of two specialists over one pull request would collapse.
    The old shape (no hire) is still read, so pull requests handled before the
    roster existed stay idempotent.
    """
    who = f":{hire_id}" if hire_id and hire_id != pack else ""
    return f"<!-- agency:{pack}{who}:{head} -->"


def already_reviewed(target: dict, pack: str = "review-graph",
                     hire_id: str | None = None) -> bool:
    """Idempotence through a marker carrying the head commit — the same commit
    is not reviewed twice by the same specialist. A different one may."""
    markers = [review_marker(pack, target["headRefOid"], hire_id)]
    if hire_id:
        # History: runs from before the roster wrote the marker without a hire.
        # For a pack's first hire that is the same worker, so it must count.
        markers.append(review_marker(pack, target["headRefOid"]))
    bodies = [c.get("body") or "" for c in target.get("_comments", [])]
    return any(m in b for m in markers for b in bodies)


def launch_argv(cfg: dict, run_dir: str, prompt: str,
                provider: str | None = None,
                model: str | None = None,
                hire=None) -> tuple[list[str], dict]:
    """What to finish the run with.

    The model is a property of the task, not of the user. You can keep coding
    on the strongest one and run reviews cheaper — a review is reading and
    classification, not writing. The choice goes into the run record, because
    "which model produces better findings" is a question this tool is supposed
    to answer with numbers.

    Precedence: `--provider/--model` from the command > hire > pack
    configuration. A hire is a PAIR, not two independent fields.
    """
    a = dict(cfg.get("agent") or {})
    cfg_provider = a.get("provider") or "claude"

    # A hire is a PAIR (provider, model). Once one is in play the pack
    # configuration no longer decides the model — otherwise "Reviewer · codex"
    # would be handed `--model sonnet`, because that is what the configuration
    # says for claude.
    if hire is not None:
        base_provider, base_model = hire.provider, hire.model
    else:
        base_provider, base_model = cfg_provider, a.get("model")

    name = provider or base_provider
    # Overriding the provider on the command line detaches the model too:
    # `--provider codex` over a sonnet hire means codex on its own default
    # model, not codex holding the name of a model it does not know.
    m = model if model is not None else (base_model if name == base_provider else None)

    spec = providers.spec(name)
    # Project configuration may tune the launch shape (a different path to the
    # binary, a wrapper) — but only for the provider it was written for.
    if name == cfg_provider:
        for k in ("bin", "modelFlag", "dirFlag", "promptFlag"):
            if k in a:
                spec[k] = a[k]
    if m is None:
        m = spec.get("defaultModel")

    argv = [spec.get("bin") or name]
    if m and spec.get("modelFlag"):
        argv += [spec["modelFlag"], m]
    # RUN_DIR leží mimo worktree, a právě tam se zapisuje findings.json.
    # Bez tohohle se agent ptá na zápis ven z pracovního adresáře v každém běhu.
    if spec.get("dirFlag"):
        argv += [spec["dirFlag"], run_dir]
    extra = a.get("extraArgs") if name == cfg_provider else None
    argv += [str(x) for x in (extra if extra is not None else spec.get("extraArgs") or [])]
    if spec.get("promptFlag"):
        argv += [spec["promptFlag"], prompt]
    else:
        argv.append(prompt)
    return argv, {"provider": name, "model": m, "bin": argv[0],
                  "hire": hire.id if hire else None}


# The hire is in the path on purpose. Two specialists over one pull request is
# the main reason the roster exists — and with a shared path the second run
# would delete the first one's worktree in the middle of its work.
WORKTREE_TEMPLATE = "../{repo}-review-pr-{n}-{hire}"


def worktree_path(project: Project, cfg: dict, target: dict, hire=None) -> Path:
    """Where the worktree will be built. Computed separately so a run can
    record the path BEFORE it takes it — the guard below rests on that."""
    tpl = (cfg.get("worktree") or {}).get("path") or WORKTREE_TEMPLATE
    fields = {
        "repo": project.root.name,
        "n": target.get("pr") or "x",
        "hire": hire.slug if hire else "solo",
        "provider": (hire.provider if hire else None) or "agent",
        "model": (hire.model if hire else None) or "default",
    }
    try:
        name = tpl.format(**fields)
    except KeyError as e:
        raise SystemExit(
            f"worktree.path uses {e} — known placeholders are "
            "{repo}, {n}, {hire}, {provider}, {model}.")

    # A safety net for configurations written before the roster existed: their
    # template knows nothing about a hire and two specialists would meet in one
    # directory. Making the path distinct is cheaper than refusing the run —
    # the worktree is throwaway anyway and its path is printed.
    if hire and fields["hire"] not in name:
        name = f"{name}-{fields['hire']}"
    return (project.root / name).resolve()


def worktree_owner(project: Project, wt: Path, exclude: str | None = None) -> str | None:
    """Which running run is holding this directory.

    Without this a parallel run by a second specialist would silently
    `--force`-delete the first one's worktree. Losing a review in progress is
    worse than a refused start, so it refuses.
    """
    want = posix(wt)
    for r in load_runs(project):
        if r.id == exclude:
            continue
        rec = r.record()
        if rec.get("status") == "running" and rec.get("worktree") == want:
            return r.id
    return None


def make_worktree(project: Project, cfg: dict, target: dict, hire=None,
                  run: "Run | None" = None) -> Path:
    """Jednorázový worktree na hlavičce PR.

    Nikdy se nečekoutuje do pracovní kopie uživatele — jeho větev i rozdělaná
    práce zůstanou netknuté.
    """
    wt = worktree_path(project, cfg, target, hire)
    if wt.exists():
        busy = worktree_owner(project, wt, exclude=run.id if run else None)
        if busy:
            raise SystemExit(
                f"{posix(wt)} is still held by the running run {busy[:10]}.\n"
                "Two specialists on the same pull request need two worktrees — give this "
                "one a name of its own via worktree.path (the {hire} placeholder does "
                "exactly that), or finish the other run first.")
        proc.git("worktree", "remove", str(wt), "--force", cwd=project.root)
    r = proc.git("fetch", "origin", f"pull/{target['pr']}/head", cwd=project.root)
    if not r.ok:
        # mergnutý PR se smazanou větví — hlavička bývá dosažitelná i tak
        proc.git("fetch", "origin", target["headRefOid"], cwd=project.root)
    ref = "FETCH_HEAD" if r.ok else target["headRefOid"]
    r = proc.git("worktree", "add", "--detach", str(wt), ref, cwd=project.root)
    if not r.ok:
        raise SystemExit(f"The worktree could not be created:\n{r.stderr.strip()}")
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
                    f.write("\n# agency: pack files, not part of the PR\n")
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


def known_memory(project: Project, run: Run) -> dict:
    """What this project already knows — across runs, packs and specialists.

    This is the shared memory. The roster allows several workers over one pack;
    if each of them remembered only its own runs, the second provider would
    dutifully repeat everything the first one settled an hour ago, and the
    queue would grow twice as fast as the value.

    Findings carry their decision with them: "this was already rejected as
    by-design" is the most valuable sentence a new run can be handed on input.
    Dedup after ingest is a safety net, not a substitute — a session that
    starts without knowing past findings is condemned to repeat them.
    """
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    known: list[dict] = []
    specs: list[dict] = []
    for other in load_runs(project):
        if other.id == run.id:
            continue
        rec = other.record()
        who = (rec.get("agent") or {}).get("hire")
        dec = decisions(other)
        for f in other.findings():
            d = dec.get(f.get("id"))
            a = f.get("anchor") or {}
            known.append({
                "id": f.get("id"), "title": f.get("title"), "dimension": f.get("dimension"),
                "severity": f.get("severity"), "file": a.get("file"), "line": a.get("line"),
                "decision": d["state"] if d else None,
                "reason": d.get("reason") if d else None,
                "runId": other.id,
                # Who found it. Without this there is no telling "a colleague
                # on another model already found this" from "I wrote this
                # myself last week".
                "hire": who, "pack": rec.get("pack"),
                "provider": (rec.get("agent") or {}).get("provider"),
            })
        if (other.dir / "specs").is_dir():
            for f in sorted((other.dir / "specs").rglob("*")):
                if f.is_file():
                    specs.append({"runId": other.id, "hire": who,
                                  "path": posix(f.relative_to(project.root))})

    write_json(ev / "known-findings.json", known[:300])
    stats = {"knownFindings": len(known)}
    if specs:
        # Reproduction tests from earlier runs. This is the thing a repro is
        # written as an executable file for and not as a paragraph: "is it
        # fixed yet?" is then answered by running it, not by another session.
        write_json(ev / "known-specs.json", specs[:200])
        stats["knownSpecs"] = len(specs)
    return stats


def collect_evidence(project: Project, wt: Path, run: Run, target: dict,
                     files: list[str]) -> dict:
    """Grafový signál. Tohle je ta část, kterou samotný diff nedá."""
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = dict(known_memory(project, run))

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


def collect_workspace_evidence(project: Project, run: Run, target: dict,
                               files: list[str]) -> dict:
    """Signal for a run without a pull request: what has been happening lately.

    The project's shared memory is added by `known_memory` — the same for both
    kinds of run, because "what this project already knows" does not depend on
    whether a pull request or a running application is being examined.
    """
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {"changedFiles": len(files), **known_memory(project, run)}

    base = target.get("baseRefOid")
    if base and base != target.get("headRefOid"):
        r = proc.git("diff", "--stat", base, cwd=project.root)
        (ev / "changes.txt").write_text(r.stdout or r.stderr, encoding="utf-8")
        log = proc.git("log", "--oneline", "-n", "30", f"{base}..HEAD", cwd=project.root)
        stats["commitsSinceBase"] = len([x for x in log.stdout.splitlines() if x.strip()])
    else:
        log = proc.git("log", "--oneline", "-n", "30", cwd=project.root)
    (ev / "recent-commits.txt").write_text(log.stdout or log.stderr, encoding="utf-8")
    return stats


def collect_backlog_evidence(project: Project, run: Run, cfg: dict) -> dict:
    """The product queue and the commitments it is measured against.

    Two halves, and both have to be frozen at the moment of the decision. The
    queue because a session that lists tickets itself burns its first minutes
    on something deterministic. The roadmap because a decision is only
    reviewable against the wording it was made from — a cut defended by "the
    roadmap said so" is worth nothing once the roadmap has been edited twice.
    """
    from . import backlog  # local: backlog needs Run, and the cycle is real

    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {}

    road = cfg.get("roadmap") or {}
    wanted: list[str] = [road["file"]] if road.get("file") else []
    wanted += [str(x) for x in (road.get("extra") or [])]
    copied: list[str] = []
    missing: list[str] = []
    for rel in wanted:
        for src in sorted(project.root.glob(rel)) or [project.root / rel]:
            if not src.is_file():
                missing.append(rel)
                continue
            dst = ev / "roadmap" / src.relative_to(project.root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(posix(src.relative_to(project.root)))
    stats["roadmapFiles"] = len(copied)
    if missing:
        # Not fatal: the gate that a run needs a roadmap belongs to `doctor`,
        # and a run that gets this far should say what it lacked rather than
        # die on it.
        stats["roadmapMissing"] = sorted(set(missing))

    try:
        board = backlog.Board.of(project, cfg)
        snap = backlog.snapshot(board, cfg)
    except backlog.BacklogError as e:
        write_json(ev / "backlog.json", {"error": str(e), "items": []})
        stats["backlogError"] = str(e)[:200]
        return stats

    write_json(ev / "backlog.json", snap)
    stats["openIssues"] = snap.get("issues", 0)
    stats["draftItems"] = snap.get("drafts", 0)

    # What this pack has already written to the board, across every past run.
    # Without it the second session re-proposes what the first one filed an
    # hour ago, and the board grows twice as fast as the product.
    written: list[dict] = []
    for other in load_runs(project):
        if other.id == run.id:
            continue
        for ev_row in backlog.ledger(other):
            written.append({**ev_row, "runId": other.id})
    if written:
        write_json(ev / "backlog-written.json", written[-300:])
        stats["alreadyWritten"] = len(written)
    return stats


def method_hint(pack, project: Project, carried: list[str], in_worktree: bool) -> str:
    """Jak se agent dostane k metodě packu.

    Ve worktree je metoda jen díky `materialize_pack`, v projektu je tam, kam ji
    položila instalace. Když neplatí ani jedno, odkaž na ni cestou — jinak běh
    skončí na „Unknown skill“ a uživatel nemá kam sáhnout.
    """
    installs = [str(i["to"]) for i in pack.manifest.get("installs", [])
                if str(i.get("to", "")).endswith("SKILL.md")]
    present = (any(str(c).endswith("SKILL.md") for c in carried) if in_worktree
               else any((project.root / to).is_file() for to in installs))
    if pack.skill_name and present:
        return f"Use the {pack.skill_name} skill."
    if installs:
        return f"Read the method in {posix(project.root)}/{installs[0]}."
    return "The pack installs no method into the project — work from the run context."


def start(project: Project, pack_ref: str, cfg: dict, target: dict,
          trigger: str = "manual", hire=None) -> Run:
    run_id = ulid()
    run = Run(run_id, project.runs_dir / run_id, project)
    run.dir.mkdir(parents=True, exist_ok=True)
    run.save_record({
        "id": run_id,
        "pack": pack_ref,
        # Which roster entry took the run. Written at start rather than with
        # `agent` at the end of preparation — a parallel run by a second
        # specialist is recognisable from it before anything is created.
        "agent": {"provider": hire.provider, "model": hire.model,
                  "hire": hire.id} if hire else {},
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


def unfinished(project: Project) -> list[Run]:
    """Runs still marked as running.

    Nothing here can tell whether one is alive: the CLI prepares the run and
    prints the command, and a terminal somewhere else runs it. There is no pid
    to check, so "unfinished" means what the record says — and closing one is
    the user's call, made when they close the terminal.
    """
    return [r for r in load_runs(project) if r.record().get("status") == "running"]


def abandon(project: Project, run: Run, reason: str | None = None) -> dict:
    """Close a run whose agent is not coming back, and free its worktree.

    The record stays. A started run is a fact, and one that was walked away
    from is worth seeing — an hour of wall clock with nothing to show for it is
    exactly the kind of thing the cost numbers are meant to catch.
    """
    rec = run.record()
    was = rec.get("status")
    rec["status"] = "abandoned"
    rec["exitReason"] = reason or "the terminal was closed before the agent finished"
    rec.setdefault("finishedAt", now())

    freed = None
    ctx = read_json(run.dir / "context.json", default={})
    wt = ctx.get("worktree")
    # A run without its own worktree worked in the user's working copy.
    # Removing that would be the worst thing this tool could do, so it is
    # decided by the record, never by comparing paths.
    if ctx.get("worktreeOwned") is not False and wt and Path(wt).exists():
        remove_worktree(project, Path(wt))
        freed = wt
    rec.pop("worktree", None)
    run.save_record(rec)
    return {"run": run.id, "wasRunning": was == "running", "worktreeRemoved": freed}


def discard(project: Project, run: Run, force: bool = False) -> dict:
    """Delete a run outright — record, evidence and all.

    Kept apart from `abandon` because it destroys history, and the one thing
    this tool must never lose is a decision somebody made. A run that has any
    is refused; one that only produced candidates says how many are going.
    """
    dec = decisions(run)
    if dec and not force:
        raise SystemExit(
            f"Run {run.id[:10]} carries {len(dec)} decision(s) — that is work somebody "
            "did, and discarding it would take the numbers with it.\n"
            "Use `agency cleanup --run <id>` to close the run and keep the record.")

    counts = {"findings": len(run.findings()), "decisions": len(dec)}
    abandon(project, run, reason="discarded")
    shutil.rmtree(run.dir, ignore_errors=True)
    return {"run": run.id, "removed": posix(run.dir), **counts}


def write_context(run: Run, cfg: dict, target: dict, wt: Path,
                  files: list[str], skipped: int,
                  brief: dict | None = None, worktree_owned: bool = True,
                  hire=None, pack_name: str | None = None) -> None:
    review = dict(cfg.get("review") or {})
    review.pop("skipPatterns", None)
    # Celá konfigurace packu, aby jádro nemuselo znát klíče jednotlivých packů.
    # `review` a `sinks` zůstávají i nahoře — na tom stojí kontrakt, který už
    # čte review-graph, a rozbít ho kvůli úspoře dvou klíčů se nevyplatí.
    pack_config = {k: v for k, v in cfg.items() if k not in ("agent", "brief")}
    write_json(run.dir / "context.json", {
        "runId": run.id,
        "runDir": posix(run.dir),
        "project": {"root": posix(run.project.root), "slug": run.project.slug},
        "worktree": posix(wt),
        # Kdo worktree vlastní. False = běh jede v pracovní kopii uživatele
        # a nesmí do ní psát nic, co po sobě neuklidí.
        "worktreeOwned": worktree_owned,
        "target": {k: v for k, v in target.items() if not k.startswith("_")},
        "files": files,
        "filesSkipped": skipped,
        # Zadání běhu. `standing` platí pro projekt pořád, `focus` jen teď.
        "brief": brief or {"standing": None, "focus": None, "scenario": None, "source": None},
        # Which worker took this run. The pack needs it for two things: to sign
        # what it produces, and to use the right idempotence marker — with two
        # specialists over one pull request a shared marker would let the first
        # one lock the second out of the same commit.
        "hire": ({"id": hire.id, "provider": hire.provider, "model": hire.model,
                  "label": hire.label} if hire else None),
        # The marker is computed by the core and handed over ready-made. A pack
        # assembling it itself would be a second place where the rule lives,
        # and `already_reviewed` would stop matching it the day either changes.
        "prCommentMarker": (review_marker(pack_name, target["headRefOid"],
                                          hire.id if hire else None)
                            if pack_name and target.get("pr") else None),
        "review": review,
        "sinks": cfg.get("sinks") or {},
        "config": pack_config,
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
        raise SystemExit(f"Unknown state “{state}”. Allowed: {', '.join(DECISION_STATES)}")
    if state == "rejected" and not reason:
        raise SystemExit(
            "A rejection needs a reason (--reason). Allowed: " + ", ".join(REJECT_REASONS)
            + "\nFree text would cost the same effort and yield no number — precision cannot be computed from it."
        )
    if reason and reason not in REJECT_REASONS:
        raise SystemExit(f"Unknown reason “{reason}”. Allowed: {', '.join(REJECT_REASONS)}")

    ev = {"kind": "decision", "findingId": finding_id, "state": state,
          "reason": reason, "note": note, "by": by, "at": now()}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def append_note(run: Run, finding_id: str, text: str, by: str = "cli") -> dict:
    """Poznámka NENÍ rozhodnutí.

    Rozhodnutí má strukturovaný důvod z pevného seznamu, protože se z něj počítá
    precision. Poznámka je volný text pro čtenáře („ověřeno na produkci, dva
    řádky"). Smíchat je znamená rozbít buď měření, nebo použitelnost — ve spiku
    to bylo zkoušené a rozbilo to obojí.

    Jde do téhož append-only proudu, aby historie nálezu byla jedna, ne dvě.
    """
    text = (text or "").strip()
    if not text:
        raise SystemExit("Empty note. Write something, or write nothing at all.")
    ev = {"kind": "note", "findingId": finding_id, "text": text, "by": by, "at": now()}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def history(run: Run) -> dict[str, list[dict]]:
    """Všechny události po nálezech, v pořadí zápisu — rozhodnutí i poznámky.

    Aktuální stav dá `decisions()`. Tohle je to, co se ukazuje ve vlákně:
    proč se rozhodlo tak, jak se rozhodlo, a co k tomu kdo dopsal.
    """
    out: dict[str, list[dict]] = {}
    if not run.decisions_path.is_file():
        return out
    with open(run.decisions_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.setdefault(ev.get("findingId"), []).append(ev)
    return out


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
