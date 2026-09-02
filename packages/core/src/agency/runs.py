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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import events, graph, hires, proc, providers
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


def cfg_provider(cfg: dict) -> str:
    """Kterým providerem projekt jede, když se neřekne jinak."""
    return (cfg.get("agent") or {}).get("provider") or "claude"


#: The authorization modes `agent.unattended` accepts in a pack's config.
#: `grant` is the default and covers what the method does. `bypass` is the
#: user's deliberate opt-in; `ask` is the off switch for whoever would rather
#: click the permission prompts themselves.
AUTH_MODES = ("grant", "bypass", "ask")


def authorization_mode(cfg: dict) -> str:
    a = dict(cfg.get("agent") or {})
    mode = str(a.get("unattended") or "grant").strip().lower()
    if mode not in AUTH_MODES:
        raise SystemExit(
            f"agent.unattended is “{mode}” — known modes are "
            f"{', '.join(AUTH_MODES)}.")
    return mode


def authorized_commands(cfg: dict, needs: list[str] | None) -> list[str]:
    """What the agent may call: the pack manifest's list plus the project's.

    Widen, never narrow. The manifest describes the method — if a project could
    trim it, the result would be a run that quietly does half of what its pack
    promises, and nobody could tell a missing finding from a missing permission.
    """
    a = dict(cfg.get("agent") or {})
    out_: list[str] = []
    for cmd in [*(needs or []), *(a.get("allow") or [])]:
        cmd = str(cmd).strip()
        if cmd and cmd not in out_:
            out_.append(cmd)
    return out_


def launch_argv(cfg: dict, memory_dir: str, prompt: str,
                provider: str | None = None,
                model: str | None = None,
                hire=None, unattended: bool = False,
                needs: list[str] | None = None) -> tuple[list[str], dict]:
    """What to finish the run with.

    `memory_dir` je to, co se agentovi povolí číst mimo pracovní adresář —
    `.agency/` projektu. Dlouho tam chodil jen RUN_DIR, jenže `context.json`
    posílá specialistu i jinam: do `knowledge` bundlu, do stránek packu a
    v řetězu do upstream běhů. Běh ve worktree se proto po každém takovém
    čtení ptal na svolení k adresáři, který mu jádro samo předalo — dávat
    cestu a nedat k ní přístup je chyba autorizace, ne otravnost.

    The model is a property of the task, not of the user. You can keep coding
    on the strongest one and run reviews cheaper — a review is reading and
    classification, not writing. The choice goes into the run record, because
    "which model produces better findings" is a question this tool is supposed
    to answer with numbers.

    Precedence: `--provider/--model` from the command > hire > pack
    configuration. A hire is a PAIR, not two independent fields.
    """
    a = dict(cfg.get("agent") or {})
    configured = cfg_provider(cfg)

    # A hire is a PAIR (provider, model). Once one is in play the pack
    # configuration no longer decides the model — otherwise "Reviewer · codex"
    # would be handed `--model sonnet`, because that is what the configuration
    # says for claude.
    if hire is not None:
        base_provider, base_model = hire.provider, hire.model
    else:
        base_provider, base_model = configured, a.get("model")

    name = provider or base_provider
    # Overriding the provider on the command line detaches the model too:
    # `--provider codex` over a sonnet hire means codex on its own default
    # model, not codex holding the name of a model it does not know.
    m = model if model is not None else (base_model if name == base_provider else None)

    spec = providers.spec(name)
    # Project configuration may tune the launch shape (a different path to the
    # binary, a wrapper) — but only for the provider it was written for.
    if name == configured:
        for k in ("bin", "modelFlag", "dirFlag", "promptFlag"):
            if k in a:
                spec[k] = a[k]
    if m is None:
        m = spec.get("defaultModel")

    argv = [spec.get("bin") or name]
    # Neattended režim je to, co dělá z řetězu řetěz: `claude` i `codex` jinak
    # startují interaktivní sezení, které po dokončení úkolu NEKONČÍ — sedí na
    # promptu a čeká na další vstup. Orchestrátor pak nikdy nedostane exit code
    # a další člen se nespustí. Předpona jde hned za binárku, protože u codexu
    # je to podpříkaz (`exec`), ne přepínač.
    if unattended:
        argv += [str(x) for x in (spec.get("unattendedPrefix") or [])]
    if m and spec.get("modelFlag"):
        argv += [spec["modelFlag"], m]
    # Uživatelské přepínače PŘED adresářem, ne za ním. `--add-dir` je
    # variadický a bere všechno až po první volbu; `extraArgs` začínající
    # hodnotou by mu padly do klína. Takhle za ním stojí rovnou `--`.
    extra = a.get("extraArgs") if name == configured else None
    argv += [str(x) for x in (extra if extra is not None else spec.get("extraArgs") or [])]

    # Authorization: handing the agent a path without the right to use it is a
    # bug, not caution. Without this block `claude -p` refuses every Write into
    # RUN_DIR and every `agency triage` — and because `is_error` stays false on
    # a denial, the run then claims it looked and found nothing. Seen on a real
    # chain 2026-09-02: five refused `findings.json` writes, status
    # `no-findings`.
    #
    # It sits here on purpose: `allowFlag` is variadic just like `--add-dir`, so
    # another FLAG has to follow it. That flag is `dirFlag` on the line below —
    # and where a provider has none, `promptSeparator` or the prompt itself
    # would be soaked up into the rule list.
    auth = providers.authorization(name, authorized_commands(cfg, needs),
                                   authorization_mode(cfg))
    if auth and not spec.get("dirFlag") and spec.get("allowFlag") in auth:
        # Better no rules than rules that swallow the prompt. The grant
        # (`--permission-mode …`) stays; the command list is dropped.
        auth = auth[:auth.index(spec["allowFlag"])]
    argv += auth

    # Paměť projektu leží mimo worktree, a právě tam se zapisuje findings.json.
    # Jeden adresář, ne seznam: `.agency/` je nadmnožina RUN_DIRu, bundlu
    # i upstream běhů, takže se nemusí řešit, kolik hodnot která variadická
    # volba spolkne.
    if spec.get("dirFlag"):
        argv += [spec["dirFlag"], memory_dir]
    if spec.get("promptFlag"):
        argv += [spec["promptFlag"], prompt]
    else:
        # Poziční prompt musí být chráněný před variadickou volbou před ním.
        # `claude --add-dir <directories...>` si ho jinak vezme jako druhý
        # adresář a agent naběhne s prázdným zadáním — což vypadá jako běh,
        # co „nic nenašel", ne jako chyba. Viz `providers.promptSeparator`.
        if spec.get("promptSeparator"):
            argv.append(spec["promptSeparator"])
        argv.append(prompt)
    return argv, {"provider": name, "model": m, "bin": argv[0],
                  "hire": hire.id if hire else None,
                  # What the agent was authorized with. It belongs in the
                  # record because "the run found nothing" and "the run was not
                  # allowed to write" are otherwise indistinguishable
                  # afterwards — which is exactly what happened three times on
                  # 2026-09-02.
                  "authorized": authorization_mode(cfg)}


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


#: Where a team's shared checkout lives. Named after the chain, not after a
#: hire: several members work in it and none of them owns it.
CHAIN_WORKTREE = "../{repo}-chain-{n}-{chain}"


def make_chain_worktree(project: Project, target: dict, chain_id: str) -> Path:
    """One checkout for the whole team.

    A chain used to let every member build its own, which meant the same pull
    request checked out N times, the graph rebuilt N times, and — the part that
    actually broke things — a workspace pack left sitting in the user's own
    branch while the reviewer read the pull request.
    """
    wt = (project.root / CHAIN_WORKTREE.format(
        repo=project.root.name, n=target.get("pr") or "x",
        chain=chain_id[:10].lower())).resolve()
    return _checkout(project, target, wt)


def _checkout(project: Project, target: dict, wt: Path) -> Path:
    r = proc.git("fetch", "origin", f"pull/{target['pr']}/head", cwd=project.root)
    if not r.ok:
        # A merged pull request whose branch is gone — its head is usually
        # reachable anyway.
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
    """Index pro tenhle běh. Jak se tam dostane, je věc driveru (`graph.py`)."""
    src = project.root / ((cfg.get("graph") or {}).get("db") or graph.DB_PATH)
    info = graph.prepare(src, wt, (cfg.get("graph") or {}).get("onStale", "update"))
    # Který driver a co uměl. Bez toho po výměně nepoznáš, jestli nálezů ubylo
    # kvůli horšímu nástroji, nebo jen proto, že zmizela schopnost — a to je
    # jediná věc, kvůli které se dá výměna vůbec vyhodnotit.
    info["driver"] = graph.DRIVER
    info["capabilities"] = graph.capabilities()
    return info


#: Co z připravených statistik je paměť, ne grafový signál. Sbírá se při téže
#: přípravě, ale v run recordu patří jinam — `graph` popisuje stav indexu.
MEMORY_STATS = ("knownFindings", "knownSpecs", "knownRules", "knownPages",
                "knownFindingsQuery")


def known_memory(project: Project, run: Run, query: str | None = None) -> dict:
    """Paměť projektu do tohohle běhu. Skládá ji `knowledge.for_run`.

    `query` je zadání běhu. Nálezů bývá víc, než kolik se vejde do okna, a bez
    dotazu se ořezávají podle stáří — tedy tiše zapomíná to důležité ve prospěch
    toho čerstvého. S dotazem rozhoduje relevance.
    """
    # Import až tady: knowledge staví nad tímhle modulem, takže nahoře by to byl
    # kruh. Paměť se skládá na jednom místě a tohle je jen jeho volání.
    from . import knowledge
    return knowledge.for_run(project, run, query=query)


def _graph_evidence(ev: Path, name: str, answer: graph.Answer) -> None:
    """To, co driver skutečně řekl, do evidence — a když neřekl nic, ať je to vidět.

    Běh bez grafového signálu je legitimní výsledek, takže se nepadá. Ale zapsat
    chybovou hlášku do `.json` znamená, že se nad ní dimenze bude dohadovat jako
    nad daty; proto jde chyba vedle, do `.error.txt`.
    """
    if not answer.ok:
        (ev / f"{name}.error.txt").write_text(answer.error or "no output", encoding="utf-8")
    elif answer.raw is not None:
        write_json(ev / f"{name}.json", answer.raw)


def collect_evidence(project: Project, wt: Path, run: Run, target: dict,
                     files: list[str], query: str | None = None) -> dict:
    """Grafový signál. Tohle je ta část, kterou samotný diff nedá."""
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    # Kolik souborů běh recenzuje, ví jádro ze seznamu, který samo odfiltrovalo.
    # Číst to z grafu znamená číst číslo z jeho shrnutí — a shrnutí počítá svůj
    # diff, ne ten po `skipPatterns`. Workspace běh to má stejně.
    stats: dict = {"changedFiles": len(files), **known_memory(project, run, query)}

    # Na co se tenhle driver umí zeptat. Čte to pack: co driver neumí, se
    # nedokládá — dimenze se přeskočí a napíše se to, místo aby se dohadovala.
    write_json(ev / "graph-capabilities.json",
               {"driver": graph.DRIVER, "tool": graph.version(),
                "capabilities": graph.capabilities()})

    base = target.get("baseRefOid")
    if base:
        answer = graph.changes(wt, base)
        _graph_evidence(ev, "detect-changes", answer)
        if answer.ok:
            d = answer.data
            stats["changedFunctions"] = d["functions"]
            stats["affectedFlows"] = d["flows"]
            stats["untestedFunctions"] = d["testGaps"]
            if d["riskScore"] is not None:
                stats["riskScore"] = d["riskScore"]
            if d["functionsTruncated"]:
                stats["changedFunctionsTruncated"] = True

    if files:
        _graph_evidence(ev, "impact", graph.impact(wt, files))

        dirs = sorted({posix(Path(f).parent) for f in files if Path(f).parent != Path(".")})
        if dirs:
            _graph_evidence(ev, "dead-code", graph.unreferenced(wt, dirs[0]))

    return stats


def collect_workspace_evidence(project: Project, run: Run, target: dict,
                               files: list[str], query: str | None = None) -> dict:
    """Signal for a run without a pull request: what has been happening lately.

    The project's shared memory is added by `known_memory` — the same for both
    kinds of run, because "what this project already knows" does not depend on
    whether a pull request or a running application is being examined.
    """
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {"changedFiles": len(files), **known_memory(project, run, query)}

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
          trigger: str = "manual", hire=None, attended: bool = True) -> Run:
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
        # Attendedness is a fact about the process, not a wish: it says whether
        # anyone could step into this run at all, which is what decides whether
        # a question the agent asks can ever be answered. A chain member runs
        # with nobody able to enter it, and that is what gets written.
        #
        # It is NOT what decides who paid. `cost.credential` reads the runner's
        # environment for that — `claude -p` is unattended and still runs on the
        # subscription, so deriving payment from attendedness was simply wrong.
        "trigger": {"kind": trigger, "attended": attended},
        "startedAt": now(),
        "status": "running",
    })
    return run


#: How an agent's own run recognises itself. `cmd_run` and `cmd_chain` read
#: these and refuse to start — a run is a leaf, not a node. Without them one
#: sentence in a brief ("use the PO agent to find out…") is enough for an agent
#: to start its own run: no terminal, no permissions, and a record claiming
#: `attended: true`. Seen 2026-09-02.
RUN_ENV = "AGENCY_RUN"
CHAIN_ENV = "AGENCY_CHAIN"

#: How to tell what paid for a run. A key present in the runner's environment
#: is a fact; `trigger.attended` is the caller's intent, and `claude -p` proves
#: it wrong — unattended and still running on the subscription.
API_KEY_ENV = {"claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
               "codex": ("OPENAI_API_KEY",)}


#: Blocks in a run record whose keys `run.v1` closes. An orchestrator carries
#: more in the same dict than the record is allowed to hold, and a block that
#: leaked through leaves an invalid document on disk — `chain.handoff` did
#: exactly that before `record_block` existed.
CLOSED_BLOCKS = {
    "chain": ("id", "position", "of", "upstream"),
}


def repair_record(run: Run) -> list[str]:
    """Drop what `run.v1` does not know, and say what was dropped.

    For records written before the contract caught up with them. `agency
    validate` reports them today; without this the only fix was hand-editing
    JSON, which is how a record ends up wrong in a second way.
    """
    rec = run.record()
    removed: list[str] = []
    for name, allowed in CLOSED_BLOCKS.items():
        block = rec.get(name)
        if not isinstance(block, dict):
            continue
        for key in [k for k in block if k not in allowed]:
            block.pop(key)
            removed.append(f"{name}.{key}")
    if removed:
        run.save_record(rec)
    return removed


def refuse_nested(command: str) -> None:
    """A run does not start runs.

    Nothing stopped an agent from calling `agency run` from inside its own
    session, and on 2026-09-02 one did: the brief said "use the PO agent to find
    out whether…", so the reviewer obediently started `agency run po@claude
    --wait` from its own tool. What came out was a run with no owner, no
    terminal, no permission to write anything, and a record claiming
    `attended: true`.

    Who runs, and in what order, is a person's decision (`teams.md` §3.3). The
    refusal is here rather than in the prompt because a prompt is advice and this
    has to be a rule.
    """
    rid = os.environ.get(RUN_ENV)
    if not rid:
        return
    chain_id = os.environ.get(CHAIN_ENV)
    where = f" (chain {chain_id[:10]})" if chain_id else ""
    raise SystemExit(
        f"`{command}` was called from inside run {rid[:10]}{where}. A run does "
        f"not start runs: write findings.json and handoff.md, and the chain "
        f"continues on its own. If you meant to add a specialist, that is a "
        f"decision for the person running `agency chain`, not for an agent in "
        f"the middle of a step.")


def credential(provider: str | None) -> str:
    keys = API_KEY_ENV.get(provider or "", ())
    return "api-key" if any(os.environ.get(k) for k in keys) else "subscription"


def agent_env(run: Run, chain: dict | None = None) -> dict[str, str]:
    env = {RUN_ENV: run.id}
    if chain and chain.get("id"):
        env[CHAIN_ENV] = str(chain["id"])
    return env


def attend(project: Project, run: Run, launch: list[str], cwd: Path,
           dialect: str | None = None, on_event=None,
           chain: dict | None = None, timeout: float | None = None) -> dict:
    """Spustit agenta, počkat na něj a zapsat, jak dopadl.

    Tohle je celý rozdíl mezi `--launch` a `--wait`: proces, který se nenahradí,
    má rodiče — a ten se dočká exit codu i hodin na stopkách. `cmd_cleanup`
    dodnes říká „no pid to watch and no exit code to catch"; pro běh spuštěný
    touhle cestou to přestává platit.

    Two paths, because the audience differs. **Attended** (`dialect=None`)
    inherits the terminal: the agent is talking to a person and a pipe would
    take that away. **Unattended** reads an event stream — nobody is talking to
    it, so the core takes its output, translates it (`events.py`) and stores it.
    Until 2026-09-02 only the first path existed, so a chain member was mute for
    ten minutes and what mattered (five refused writes) survived only in the
    provider's own transcript.

    Stav běhu tady nevzniká. O tom, jestli je běh `ok`, rozhoduje brána podle
    toho, co agent napsal — exit code je do toho rozhodnutí vstup, ne ono samo.
    """
    env = agent_env(run, chain)
    started = time.monotonic()
    collected: list = []

    if dialect:
        raw = (run.dir / "agent.jsonl").open("w", encoding="utf-8")

        def line(text: str) -> None:
            # The whole stream to disk, including lines the translator does
            # not understand. Next time someone asks why a run wrote nothing,
            # the answer should be in the run, not in `~/.claude/projects`.
            raw.write(text + "\n")
            for e in events.parse(dialect, text):
                collected.append(e)
                if on_event:
                    on_event(e)
        try:
            code = proc.stream(launch, cwd=cwd, env=env, on_line=line, timeout=timeout)
        finally:
            raw.close()
    else:
        code = proc.attend(launch, cwd=cwd, env=env)

    seconds = round(time.monotonic() - started, 1)
    summary = events.summarize(collected) if collected else {}

    rec = run.record()
    agent = {**(rec.get("agent") or {}), "exitCode": code}
    if collected:
        # The agent's last message, on disk. This is where two finished
        # analyses vanished on 2026-09-02: the agent printed them to the
        # terminal because it was not allowed to write them, and a scrollback
        # is not a project's memory.
        if summary.get("last"):
            (run.dir / "agent.md").write_text(str(summary["last"]).rstrip() + "\n",
                                              encoding="utf-8")
        agent["sessionId"] = summary.get("session")
        agent["turns"] = summary.get("turns")
        denied = events.denial_count(collected)
        agent["denied"] = {"count": denied, "tools": summary.get("denied") or []}
    rec["agent"] = agent
    # `cost.wallClockSeconds` je v `run.v1` od začátku a dodnes ho nic
    # nevyplňovalo — nebylo co měřit. Metriky ho čtou (`s per candidate`),
    # takže tenhle zápis nezapíná nic nového, jen dosud mrtvé číslo.
    tokens = summary.get("tokens") or {}
    rec["cost"] = {
        **(rec.get("cost") or {}),
        "provider": agent.get("provider"),
        "model": agent.get("model"),
        # From the runner's environment, not from `trigger.attended`. Deriving
        # payment from attendedness meant claiming a chain member runs on an API
        # key — while `claude -p` runs on the same subscription an interactive
        # session does.
        "credential": credential(agent.get("provider")),
        "wallClockSeconds": seconds,
        **({"usd": summary["usd"]} if summary.get("usd") is not None else {}),
        **({"inputTokens": tokens["input"]} if tokens.get("input") is not None else {}),
        **({"outputTokens": tokens["output"]} if tokens.get("output") is not None else {}),
    }
    rec["finishedAt"] = now()
    run.save_record(rec)
    return {"exitCode": code, "wallClockSeconds": seconds,
            "turns": summary.get("turns"), "usd": summary.get("usd"),
            "denied": (agent.get("denied") or {}).get("count") or 0}


def failed(run: Run, reason: str) -> dict:
    """Běh, jehož agent skončil chybou.

    Píše se AŽ po bráně, ne místo ní. Co agent stihl zapsat, projde branou
    jako vždycky — ale záznam nesmí skončit na `no-findings`, protože to je
    tvrzení „díval se a nic nenašel“, a exit code říká něco jiného.
    """
    rec = run.record()
    rec["status"] = "failed"
    rec["exitReason"] = reason
    rec.setdefault("finishedAt", now())
    run.save_record(rec)
    return {"run": run.id, "status": "failed", "exitReason": reason}


def unfinished(project: Project) -> list[Run]:
    """Runs still marked as running.

    A run prepared with `--launch` or by hand is run by a terminal this process
    knows nothing about: there is no pid to check, so "unfinished" means what
    the record says, and closing one is the user's call. `--wait` is the way
    around it — that one waits for the agent and closes the run itself.
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
                  hire=None, pack_name: str | None = None,
                  provider: str | None = None, chain: dict | None = None,
                  in_worktree: bool | None = None) -> None:
    from . import knowledge  # circular import: `knowledge` stands on `runs`

    # Being IN a worktree and OWNING one stopped being the same thing when a
    # chain started building one for all its members. The member works in a
    # throwaway checkout it must not delete, so the two questions get two
    # answers.
    if in_worktree is None:
        in_worktree = worktree_owned

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
        # Commitovaná paměť projektu. Absolutní schválně: bundle je součástí
        # repa, takže ve worktree na hlavičce PR existuje taky — jenže ve verzi
        # z toho commitu. Relativní cesta by specialistu poslala číst starší
        # memory than the project actually has.
        "knowledge": posix(run.project.agency_dir / knowledge.BUNDLE),
        # Where the pack writes its own conclusions. `null` for a run inside a
        # worktree, and not out of caution: the worktree stands on the pull
        # request's head, so the write would land in a throwaway directory the
        # tool deletes afterwards. A route through RUN_DIR for the reviewer
        # arrives once there is something for `ingest` to apply.
        "pages": (posix(knowledge.pages_dir(run.project, pack_name, cfg))
                  if pack_name and not in_worktree else None),
        "worktree": posix(wt),
        # Who owns the worktree — that is, who cleans it up. False means either
        # the run works in the user's own working copy (write nothing you do not
        # clean up) or a chain built this checkout for several members and will
        # remove it when they are all done.
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
        # Čím se podepsat pod rozhodnutí (`agency triage … --by <by>`). Skládá
        # to jádro, aby to byl opis, ne úsudek: identita složená agentem je
        # první místo, kde se „rozhodl specialista" změní v „rozhodl někdo".
        # Běh bez hire ji má taky — pracovník je pak `pack@provider`.
        "by": (f"hire:{worker_id(cfg, pack_name, hire=hire, provider=provider)}"
               if (hire or pack_name) else None),
        # The marker is computed by the core and handed over ready-made. A pack
        # assembling it itself would be a second place where the rule lives,
        # and `already_reviewed` would stop matching it the day either changes.
        "prCommentMarker": (review_marker(pack_name, target["headRefOid"],
                                          hire.id if hire else None)
                            if pack_name and target.get("pr") else None),
        # Členství v řetězu, nebo `null` u samostatného běhu. Pack se podle
        # toho pozná, že má napřed soudit cizí nálezy z `evidence/upstream.json`
        # a po sobě nechat `handoff.md` — obojí je kontrakt v jeho SKILL.md.
        # Jen schématické klíče plus ukazatele na soubory. Vzkaz předchůdce sem
        # nepatří — ten je v promptu, a druhá kopie téhož textu by znamenala dvě
        # místa, která se můžou rozejít.
        "chain": ({**{k: chain[k] for k in ("id", "position", "of", "upstream")
                      if k in chain},
                   "upstreamFile": "evidence/upstream.json",
                   "handoffFile": "handoff.md"} if chain else None),
        "review": review,
        "sinks": cfg.get("sinks") or {},
        "config": pack_config,
        "schemas": {"finding": "finding.v1", "run": "run.v1"},
    })


# ---------------------------------------------------------------- rozhodnutí

#: Člověk. Volitelně `human:<jméno>`, když je jich u projektu víc.
HUMAN = "human"

#: Do 1. 9. 2026 psalo CLI `cli` a extension `vscode`. Čtou se jako člověk —
#: historie se nepřepisuje, jen vykládá.
LEGACY_BY = {"cli": HUMAN, "vscode": HUMAN, "extension": HUMAN}


def normalize_by(value: str | None) -> str | None:
    """Jak se dnes čte to, co kdo kdy zapsal. Nic zapsaného je `None`.

    Prázdno se schválně nedoplňuje na člověka: „nevím, kdo rozhodl" a „rozhodl
    člověk" jsou různá tvrzení a jen jedno z nich někdo skutečně udělal.
    """
    v = (value or "").strip()
    return LEGACY_BY.get(v, v) or None


def validate_by(value: str | None) -> str:
    """Tvar identity se hlídá při zápisu, protože z atribuce se počítají tiery.

    Dva tvary, protože jen tenhle rozdíl jde později vážit: `hire:<id>` je
    pracovník, `human` je člověk. „Jeden model si to myslí" a „druhý model to
    potvrdil a člověk to přijal" jsou různě silné vstupy pro další běh a zpětně
    se od sebe nedají odlišit — proto se nepřijímá volný string.
    """
    v = normalize_by(value) or ""
    if v == HUMAN or (v.startswith("human:") and v[len("human:"):].strip()):
        return v
    if v.startswith("hire:") and hires.ID_RE.match(v[len("hire:"):]):
        return v
    raise SystemExit(
        f"Unknown identity “{value}”. Use `hire:<id>` for a specialist — the "
        f"ready-made value is in context.json under `by` — or `human` / "
        f"`human:<name>` for a person."
    )


def worker_id(cfg: dict, pack_name: str, hire=None, provider: str | None = None) -> str:
    """Kdo tenhle běh odpracuje — `pack@provider`, ať je v rosteru, nebo ne.

    Hire z rosteru má id sám. Běh bez hire ho dostane odvozený, aby „rozhodl
    specialista" šlo odlišit od „rozhodl člověk" i v projektu, kde roster nikdo
    nezaložil — a aby to id mělo týž tvar, kdyby se ten pracovník najal později.
    """
    if hire is not None:
        return hire.id
    return f"{pack_name}@{provider or cfg_provider(cfg)}"


def append_decision(run: Run, finding_id: str, state: str,
                    reason: str | None = None, note: str | None = None,
                    by: str = HUMAN) -> dict:
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
          "reason": reason, "note": note, "by": validate_by(by), "at": now()}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def append_note(run: Run, finding_id: str, text: str, by: str = HUMAN) -> dict:
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
    ev = {"kind": "note", "findingId": finding_id, "text": text,
          "by": validate_by(by), "at": now()}
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
