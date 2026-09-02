"""`agency` — příkazová řádka.

Každý příkaz umí `--json`, protože jeho druhým uživatelem je VS Code extension
a třetím agent. Kdyby výstup uměl jen člověk, byli by ti dva druhořadí.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import (anchor, backlog, chain as chains, config, dedup, export, graph,
               hires, ingest, knowledge, metrics, packs, proc, providers,
               registry, runs)
from .util import bundled, out, posix, read_json, strip_comments, ulid, write_json

# ---------------------------------------------------------------- pomůcky


def _emit(args, data, human) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        human()
    return 0


def _project(args) -> config.Project:
    project = config.require(getattr(args, "repo", None))
    # Registr je ukazatel, ne uloziste — plni se tim, ze v projektu neco delas.
    # Podminka na .agency drzi z registru projekty, kde jsi jen omylem spustil
    # `agency status`; ukazatel na nic je horsi nez chybejici ukazatel.
    if project.agency_dir.is_dir():
        try:
            registry.remember(project)
        except OSError:
            pass  # registr je postradatelny, prace kvuli nemu nespadne
    return project


def _pack_cfg(project: config.Project, pack_name: str, asked: str | None = None) -> dict:
    """Configuration of the pack a run is about to use.

    The name the user typed may have been a hire id, so the error has to answer
    both readings of "not found here" — nobody hired under that name, and no
    method installed under it either.
    """
    cfg = project.pack_config(pack_name)
    if cfg is not None:
        return cfg

    known = ", ".join(h.id for h in hires.load(project))
    installed = ", ".join(project.installed().get("packs") or {})
    lines = [f"Nothing here is called “{asked or pack_name}”."]
    if known:
        lines.append(f"Hired: {known}")
    if installed:
        lines.append(f"Methods installed: {installed}")
    lines.append(f"Hire one: `agency hire {pack_name}`")
    raise SystemExit("\n".join(lines))


# ---------------------------------------------------------------- init

def cmd_init(args) -> int:
    project = _project(args)
    facts = config.detect(project)
    facts["root"] = posix(project.root)

    def human():
        print(f"\n{out.bold(project.name)}  {out.dim(posix(project.root))}\n")
        rows = [
            ("git remote", facts["slug"] or out.warn("missing — the pack will need repo.slug set by hand")),
            ("default branch", facts["defaultBranch"] or out.warn("not detected")),
            ("code graph", out.ok("built") if facts["hasGraph"]
             else out.warn("missing — the first run builds it (`code-review-graph build`)")),
            ("CI command", facts["verifyCommand"] or out.dim("none — findings that CI catches will not be dropped")),
            ("project rules", facts["rules"] or out.dim("not found — 4 of 5 dimensions will run")),
            ("doc map", facts["docMap"] or out.dim("not found")),
            ("existing skills", ", ".join(facts["existingSkills"]) or out.dim("none")),
            ("playwright", f"{pw['configFile'] or 'no config'} · {pw['specs']} "
                           f"spec{'' if pw['specs'] == 1 else 's'} in {pw['testDir'] or '?'}"
             if (pw := facts["playwright"])["present"]
             else out.dim("none — QA can set one up inside the run directory")),
        ]
        for k, v in rows:
            print(f"  {k:20} {v}")
        print(f"\n  Next: {out.bold('agency add review-graph')}\n")

    return _emit(args, facts, human)


# ---------------------------------------------------------------- packs

def cmd_packs(args) -> int:
    project = config.discover(getattr(args, "repo", None))
    roster = hires.describe(project, _packs_by_name()) if project else []
    data = []
    for p in packs.available():
        entry = {"name": p.name, "version": p.version, "title": p.manifest.get("title"),
                 "description": p.manifest.get("description"),
                 # Dimenze a predpoklady jsou soucast odpovedi na „co ten
                 # specialista umi" — klient je jinak nema odkud vzit a musel by
                 # cist pack.json sam, cimz by obesel hranici.
                 "dimensions": p.manifest.get("dimensions") or [],
                 "requires": p.manifest.get("requires") or {},
                 # Behova politika patri do odpovedi „co ten specialista umi":
                 # bez ni by klient nevedel, jestli se ma ptat na pull request,
                 # nebo na zadani — a musel by jmena packu znat napevno.
                 "run": p.run_policy,
                 "installed": packs.installed_ref(project, p.name) if project else None}
        # Who works by this method here. A pack can have several workers, so
        # "which provider handles it" is no longer one field on the pack — the
        # client renders one row per hire and must get them from the core.
        entry["hires"] = [h for h in roster if h["pack"] == p.name]
        cfg = project.pack_config(p.name) if project else None
        if cfg:
            a = cfg.get("agent") or {}
            entry["agent"] = {"provider": a.get("provider"), "model": a.get("model")}
            entry["configPath"] = posix(project.pack_config_path(p.name))
            pw = cfg.get("playwright")
            if isinstance(pw, dict):
                entry["playwright"] = {
                    "enabled": bool(pw.get("enabled")),
                    "configFile": pw.get("configFile"),
                    "specTarget": pw.get("specTarget"),
                    "scaffold": pw.get("scaffold"),
                }
            board = cfg.get("board")
            if isinstance(board, dict):
                # The panel needs it for the same reason it needs `playwright`:
                # a specialist that writes outside the repository has to say so
                # on its own row, not in a configuration file nobody opens.
                w = cfg.get("writes") or {}
                entry["backlog"] = {
                    "repo": (cfg.get("repo") or {}).get("slug"),
                    "projectNumber": board.get("projectNumber"),
                    "roadmap": (cfg.get("roadmap") or {}).get("file"),
                    "cycle": (cfg.get("roadmap") or {}).get("cycle"),
                    "writes": [k for k, v in w.items() if v is True and k != "dryRun"],
                    "dryRun": bool(w.get("dryRun")),
                }
            b = cfg.get("brief") or {}
            entry["brief"] = {
                "standing": b.get("default"),
                "scenarios": [{"name": k, "text": v} for k, v in
                              sorted((b.get("scenarios") or {}).items())],
            }
        data.append(entry)

    def human():
        print()
        for e in data:
            mark = out.ok("installed " + e["installed"]) if e["installed"] else out.dim("not installed")
            print(f"  {out.bold(e['name']):28} {e['version']:8} {mark}")
            print(f"  {'':28} {out.dim(e['description'] or '')}")
            for h in e["hires"]:
                dot = out.ok("●") if h["available"] else out.err("●")
                print(f"  {'':26} {dot} {h['id']:30} {out.dim(h['label'])}")
        print()

    return _emit(args, data, human)


def cmd_add(args) -> int:
    """Install a pack and put one worker on it.

    Two things that used to be one. Installing brings the METHOD into the
    project; hiring says who will work by it. They stayed one command as long
    as a pack could have exactly one worker — the roster is what separated
    them, and `agency add` keeps doing both so nothing that worked before has
    to change.
    """
    project = _project(args)
    pack = packs.load(args.pack, args.from_path)
    steps = packs.plan(pack, project)
    blocked = [s for s in steps if s["action"] == "blocked"]

    provider = getattr(args, "provider", None)
    model = getattr(args, "model", None)
    hire = None

    if not args.dry_run and not blocked:
        packs.apply(pack, project, steps, detected=config.detect(project))
        registry.remember(project)  # .agency vzniklo az ted

        cfg = project.pack_config(pack.name) or {}
        if provider or model or getattr(args, "as_id", None):
            # An explicit provider means "another worker", even when the pack
            # already has one — that is the whole point of `agency hire`.
            agent = cfg.get("agent") or {}
            chosen = provider or agent.get("provider") or "claude"
            # A model is only inherited from the configuration when it was
            # written for this provider. Handing codex a claude model name
            # would be a launch flag that fails on the first run.
            chosen_model = model or (agent.get("model") if chosen == (
                agent.get("provider") or "claude") else None)
            hire = hires.add(project, pack.name, provider=chosen, model=chosen_model,
                             hire_id=getattr(args, "as_id", None),
                             title=getattr(args, "title", None))
        else:
            hire = hires.ensure_default(project, pack.name, cfg)

    data = {"pack": pack.ref, "dryRun": args.dry_run,
            "hire": hire.as_dict() if hire else None,
            "steps": [{k: v for k, v in s.items() if k != "src"} for s in steps]}

    def human():
        print(f"\n  {out.bold(pack.ref)} → {project.name}\n")
        icon = {"create": out.ok("+"), "update": out.ok("~"), "keep": out.dim("="),
                "blocked": out.err("!")}
        for s in steps:
            print(f"  {icon[s['action']]} {s['to']:52} {out.dim(s['why'])}")
        if blocked:
            print(f"\n  {out.err('Installation stopped.')} The files above were modified by hand.")
            print(out.dim("  Editing a pack by hand usually means a field is missing from the"))
            print(out.dim("  configuration — add it to .agency/, not to the method. Overwrite anyway: --force."))
        elif args.dry_run:
            print(f"\n  {out.dim('Dry run, nothing was written.')}")
        else:
            if hire:
                where = providers.installed(hire.provider)
                mark = out.ok("hired") if where else out.warn("hired, but not on PATH")
                print(f"\n  {mark} {out.bold(hire.id)}  "
                      f"{out.dim(hire.provider + (' · ' + hire.model if hire.model else ''))}")
                print(f"  {out.dim('Run it:')} agency run {hire.id}")
                print(f"  {out.dim('Another provider:')} "
                      f"agency hire {pack.name} --provider <name>")
            else:
                # Nobody new was hired, and silence here reads like a failure.
                # Re-running the command is how you refresh the method, so say
                # who is already doing the work instead of saying nothing.
                existing = hires.for_pack(project, pack.name)
                print(f"\n  {out.dim('Already hired:')} "
                      f"{', '.join(f'{h.id} ({h.label})' for h in existing)}")
                print(f"  {out.dim('Add another:')} "
                      f"agency hire {pack.name} --provider <name>")
            print(f"\n  Next: {out.bold('agency doctor')}")
        print()

    _emit(args, data, human)
    return 1 if blocked and not args.force else 0


# ---------------------------------------------------------------- roster

def _packs_by_name() -> dict:
    return {p.name: p for p in packs.available()}


def cmd_roster(args) -> int:
    """Who is hired here. One row per worker, not per method.

    The list is the answer to “can I run two providers on this?” — if a
    provider is missing from PATH, it says so here rather than at launch.
    """
    project = _project(args)
    data = hires.describe(project, _packs_by_name())

    def human():
        print(f"\n  {out.bold(project.name)}  {out.dim(posix(project.root))}\n")
        if not data:
            print(f"  {out.dim('Nobody hired yet.')}  agency hire review-graph\n")
            return
        for h in data:
            mark = out.ok("●") if h["available"] else out.err("●")
            model = h["model"] or out.dim("provider default")
            print(f"  {mark} {out.bold(h['id']):34} {h['display'][:30]:32} "
                  f"{h['provider']:10} {model}")
            if not h["available"]:
                print("    " + out.dim(
                    f"`{h['bin']}` is not on PATH — this one cannot run here"))
            if not h["packInstalled"]:
                print("    " + out.dim(
                    f"pack {h['pack']} is not installed — `agency add {h['pack']}`"))
        print(f"\n  {out.dim('Run one:')} agency run <id>   "
              f"{out.dim('Add one:')} agency hire <pack> --provider <name>\n")

    return _emit(args, data, human)


def cmd_fire(args) -> int:
    """Remove a roster entry. The pack, its configuration and every past run
    stay — firing a worker is not deleting their work."""
    project = _project(args)
    gone = hires.remove(project, args.hire)
    if not gone:
        known = ", ".join(h.id for h in hires.roster(project)) or "(nobody)"
        raise SystemExit(f"There is no hire “{args.hire}” here. Hired: {known}")

    data = {"fired": gone.as_dict(), "remaining": [h.as_dict() for h in hires.load(project)]}

    def human():
        print(f"\n  {out.ok('fired')} {out.bold(gone.id)}\n")
        print(out.dim("  The pack, its configuration and every past run stay where they were."))
        print(out.dim("  Findings this hire produced keep counting towards the metrics.\n"))

    return _emit(args, data, human)


def cmd_providers(args) -> int:
    """What AI runners this machine has.

    A property of the machine, not of the project — which is why adding one is
    a command and not a commit. Once `grok` is on PATH, one `providers add`
    makes it hireable for every pack in every project.
    """
    if args.remove:
        if not providers.forget(args.remove):
            raise SystemExit(
                f"“{args.remove}” is not registered. Built-in providers cannot be removed.")
    elif args.add:
        providers.register(
            args.add, bin=args.bin, title=args.title, modelFlag=args.model_flag,
            dirFlag=args.dir_flag, promptFlag=args.prompt_flag,
            defaultModel=args.default_model,
            models=[m.strip() for m in args.models.split(",") if m.strip()]
            if args.models else None)

    data = providers.detected()

    def human():
        print()
        for p in data:
            mark = out.ok("●") if p["installed"] else out.dim("○")
            tag = out.dim("built in") if p["builtin"] else out.dim("added by you")
            print(f"  {mark} {out.bold(p['id']):14} {p['title'][:24]:26} {tag}")
            print("    " + out.dim(p["path"] or f"`{p['bin']}` is not on PATH"))
            if p["models"]:
                print(f"    {out.dim('models: ' + ', '.join(p['models']))}")
        print(f"\n  {out.dim('Add one:')} agency providers --add grok --bin grok")
        print(f"  {out.dim('Hire it:')} agency hire review-graph --provider grok\n")

    return _emit(args, data, human)


# ---------------------------------------------------------------- doctor

def _run_hint(pack) -> str:
    """How this pack is launched. Read from the manifest, never from its name."""
    policy = pack.run_policy
    if policy["target"] == "pull-request":
        return " --pr <n>"
    return ' --prompt "…"' if policy["prompt"].get("required") else ""


def cmd_doctor(args) -> int:
    project = _project(args)
    checks = []

    def check(name, ok, detail, fatal=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})

    # Nástroj je předpoklad jen tehdy, když ho někdo najatý opravdu chce.
    # Projekt, který si najal jen QA, nemá svítit červeně kvůli grafu, který
    # nepoužije — a naopak: dokud není najatý nikdo, platí přísnější výchozí stav.
    hired = [p for p in packs.available() if packs.installed_ref(project, p.name)]
    wanted: set[str] = set()
    required_config: set[str] = set()
    for p in hired:
        wanted |= set((p.manifest.get("requires") or {}).get("tools") or [])
        required_config |= set((p.manifest.get("config") or {}).get("required") or [])

    def needed(tool: str) -> bool:
        return not hired or tool in wanted

    def tool_check(name: str, tool: str, value, missing: str) -> None:
        if value:
            check(name, True, value, fatal=needed(tool))
        elif needed(tool):
            check(name, False, missing)
        else:
            check(name, True, "not needed by the specialists hired here", fatal=False)

    check("git", proc.which("git"), proc.which("git") or "not on PATH")

    # One check per hired worker, not one per provider. The roster is shared
    # through the repository but the binaries are not: a colleague who clones
    # this project has to be told which of its specialists cannot run here,
    # and a missing binary is the one prerequisite that only shows up at launch.
    crew = hires.roster(project)
    for h in crew:
        where = providers.installed(h.provider)
        spec = providers.spec(h.provider)
        check(f"hire {h.id}", where,
              f"{where} · {h.label}" if where
              else f"`{spec.get('bin') or h.provider}` is not on PATH — install it, "
                   f"or `agency fire {h.id}`",
              # Not fatal: one unavailable specialist must not make the whole
              # project look broken when the others can work.
              fatal=False)
    if crew and not any(providers.installed(h.provider) for h in crew):
        check("agent", False,
              "none of the hired specialists has its runner on PATH — nothing can run here")

    tool_check("code-review-graph", "code-review-graph", proc.crg_version(),
               "not on PATH — `uv tool install code-review-graph`")
    login = proc.gh_login()
    tool_check("gh auth", "gh", f"signed in as {login}" if login else None,
               "not signed in — `gh auth login`")
    slug_needed = not hired or "repo.slug" in required_config
    check("repo slug", project.slug or not slug_needed,
          project.slug or ("origin remote missing" if slug_needed
                           else "no remote — the hired specialists do not need one"),
          fatal=slug_needed)

    if needed("code-review-graph"):
        g = graph.state(project.root).data
        check("code graph", g["exists"],
              f"{g.get('sizeBytes', 0) // 1_000_000} MB"
              + (f" · {g['nodes']} nodes, {g['files']} files"
                 if g.get("nodes") is not None else "")
              # Index z jiné hlavičky umí nález opřít o kód, který na téhle
              # větvi neexistuje — a pozná se to jen porovnáním commitů.
              + ("  built on another commit — `code-review-graph update`"
                 if g.get("stale") else "")
              if g["exists"]
              else "missing — build it with `code-review-graph build`", fatal=False)

    # Projektová pravidla jako koncepty. Rozbité pravidlo je horší než žádné:
    # dimenze by běžela s tichou dírou v zadání a nikdo by nevěděl proč.
    rules = knowledge.rules_summary(project)
    if rules["total"] or rules["broken"]:
        detail = f"{rules['total']} concepts"
        for label, count in (("expired", rules["expired"]),
                             ("deprecated", rules["deprecated"])):
            if count:
                detail += f" · {count} {label}"
        for bad in rules["broken"]:
            detail += f"\n{' ' * 29}{bad['path']}: {bad['error']}"
        check("project rules", not rules["broken"], detail, fatal=False)

    # Kurátorovaná znalost packů. Stránka bez hlavičky se čte dál — jen neví,
    # jestli ještě platí, a to je informace pro člověka, ne důvod k selhání.
    pg = knowledge.pages_summary(project)
    if pg["total"] or pg["broken"]:
        detail = " · ".join(f"{pack} {n}" for pack, n in pg["byPack"].items())
        for label, count in (("expired", pg["expired"]),
                             ("deprecated", pg["deprecated"]),
                             ("without frontmatter", pg["plain"])):
            if count:
                detail += f" · {count} {label}"
        for bad in pg["broken"]:
            detail += f"\n{' ' * 29}{bad['path']}: {bad['error']}"
        check("pack pages", not pg["broken"], detail, fatal=False)

    # Pack nainstalovaný verzí, která roster ještě nezapisovala. Dřív si takový
    # pack vyrobil „odvozeného" pracovníka a tvářil se, že je všechno v pořádku —
    # jenže ten pracovník nešel propustit a po propuštění posledního skutečného
    # se vracel sám. Teď se to řekne nahlas, protože spravit to jde jedním
    # příkazem.
    orphaned = [n for n in sorted((project.installed().get("packs") or {}))
                if not hires.for_pack(project, n)]
    if orphaned:
        check("roster", False,
              f"{', '.join(orphaned)} installed with nobody hired — "
              f"`agency hire {orphaned[0]}` writes the worker down. Runs still work: "
              f"they fall back to the pack configuration.", fatal=False)

    for p in packs.available():
        ref = packs.installed_ref(project, p.name)
        if not ref:
            continue
        cfg = project.pack_config(p.name) or {}
        missing = [k for k in (p.manifest.get("config", {}).get("required") or [])
                   if not _dig(cfg, k)]
        check(f"pack {p.name}", not missing,
              f"{ref}, configuration complete" if not missing
              else f"missing required: {', '.join(missing)}")
        if ref != p.ref:
            check(f"pack {p.name} version", False,
                  f"installed {ref}, available {p.ref} — `agency add {p.name}`", fatal=False)

        # Co pack od grafu chce vs. co driver umí. Ptá se to dopředu, protože
        # chybějící schopnost není chyba — je to dimenze, která poběží bez
        # grafového signálu. Tiché selhání uprostřed běhu je horší než tahle
        # věta na začátku.
        gp = p.run_policy["graph"]
        if gp:
            caps = set(graph.capabilities())
            lacks_required = [v for v in gp["required"] if v not in caps]
            lacks_optional = [v for v in gp["optional"] if v not in caps]
            if lacks_required:
                check(f"pack {p.name} graph", False,
                      f"the driver ({graph.DRIVER}) cannot answer "
                      f"{', '.join(lacks_required)} — this pack stands on it", fatal=False)
            elif lacks_optional:
                check(f"pack {p.name} graph", True,
                      f"{graph.DRIVER}, without {', '.join(lacks_optional)} — "
                      f"those dimensions run without the graph signal", fatal=False)

        # Pack, který zkouší běžící aplikaci, se má ptát dřív, než začne běh.
        # Nedostupná aplikace je nejlevnější způsob, jak přijít o celé sezení.
        base = (cfg.get("app") or {}).get("baseUrl")
        if base:
            ready = (cfg.get("app") or {}).get("readyCheck") or ""
            ok, detail = proc.reachable(base.rstrip("/") + (ready if ready.startswith("/") else ""))
            check(f"pack {p.name} app", ok, detail, fatal=False)

        if (cfg.get("playwright") or {}).get("enabled"):
            for name, ok, detail, is_fatal in _playwright_checks(project, cfg["playwright"]):
                check(f"pack {p.name} {name}", ok, detail, fatal=is_fatal)

        # Cesty, na které konfigurace ukazuje. Vyžadované pole může být
        # vyplněné a přesto ukazovat na soubor, který v projektu není — a to
        # se pozná až uprostřed běhu, kdy už agent přemýšlí nad prázdnem.
        for dotted in ((p.manifest.get("config") or {}).get("files") or []):
            rel = _dig(cfg, dotted)
            if not rel:
                continue  # už to hlásí kontrola „missing required"
            here = (project.root / str(rel)).is_file()
            check(f"pack {p.name} {dotted}", here,
                  str(rel) if here else
                  f"{rel} is not in the project — point `{dotted}` at a file that is")

        # Pack, který píše na cizí plochu, potřebuje na to oprávnění. Chybějící
        # scope se projeví až prvním zápisem — tedy potom, co agent hodinu
        # přemýšlel, co napsat.
        if (cfg.get("board") or {}).get("projectNumber"):
            scopes = proc.gh_scopes()
            can = "project" in scopes
            detail = (f"board #{cfg['board']['projectNumber']} · scopes: "
                      + (", ".join(scopes) or "unknown")) if can else (
                "the gh token has no `project` scope — `gh auth refresh -s project`")
            check(f"pack {p.name} board", can, detail)

        # Co ten pack smí udělat ven. Není to porucha, je to věc, kterou má
        # člověk vidět dřív, než ho překvapí ticket v cizí schránce.
        writes = cfg.get("writes")
        if isinstance(writes, dict):
            on = [k for k, v in writes.items() if v is True and k != "dryRun"]
            check(f"pack {p.name} writes",
                  True,
                  ("rehearsal only — writes.dryRun is on" if writes.get("dryRun")
                   else ("may " + ", ".join(on) if on else "reads only")),
                  fatal=False)

        # Zadání je u packu, který ho vyžaduje, taky předpoklad — jen se nedá
        # nainstalovat, musí ho napsat člověk.
        if p.run_policy["prompt"]["required"]:
            standing = ((cfg.get("brief") or {}).get("default") or "").strip()
            check(f"pack {p.name} brief", True,
                  standing[:60] if standing
                  else "no standing brief — every run will need --prompt", fatal=False)

    fatal = [c for c in checks if not c["ok"] and c["fatal"]]

    def human():
        print(f"\n  {out.bold(project.name)}\n")
        for c in checks:
            icon = out.ok("✓") if c["ok"] else (out.err("✗") if c["fatal"] else out.warn("!"))
            print(f"  {icon} {c['name']:24} {out.dim(c['detail'])}")
        print()
        if fatal:
            print(f"  {out.err('A run would fail.')} Fix the items marked ✗.\n")
        else:
            # Build the hint from what is actually installed. A hardcoded pair
            # of packs leaves the third specialist invisible right after
            # doctor — which is exactly when the user is looking for it.
            hints = [f"agency run {p.name}{_run_hint(p)}" for p in hired] or ["agency packs"]
            print(f"  {out.ok('Ready.')}  " +
                  f"  {out.dim('·')}  ".join(out.dim(h) for h in hints) + "\n")

    _emit(args, {"checks": checks, "ok": not fatal}, human)
    return 1 if fatal else 0


def _playwright_checks(project: config.Project, pw: dict) -> list[tuple]:
    """Co musí platit, aby sezení dojelo prohlížečem.

    Selhání Playwrightu přijde uprostřed sezení, po přihlášení a po deseti
    krocích průchodu — a celé sezení tím padá. Zeptat se dopředu stojí
    milisekundy.
    """
    rows: list[tuple] = []

    npx = proc.which("npx") or proc.which("npx.cmd")
    rows.append(("node", bool(npx),
                 npx or "npx is not on PATH — Playwright is started through it", True))

    local = (project.root / "node_modules" / "@playwright" / "test").is_dir()
    scaffold = pw.get("scaffold") or "run-dir"
    if local:
        ok, detail, fatal = True, "@playwright/test is installed in the project", False
    elif pw.get("configFile"):
        # Konfigurace projektu se opírá o jeho fixtures, a ty bez node_modules
        # nejsou. Náhradní konfigurace v běhovém adresáři to nezachrání —
        # zachrání to `npm install`, tak to řekni rovnou.
        ok, detail, fatal = (False,
                             f"{pw['configFile']} is here, but @playwright/test is not "
                             f"installed — `npm install`", False)
    elif scaffold == "run-dir":
        ok, detail, fatal = (True,
                             "the project has no Playwright; the session sets one up inside "
                             "the run directory", False)
    else:
        ok, detail, fatal = (False,
                             "the project has no Playwright and scaffolding is off — turn it "
                             "on or install Playwright", True)
    rows.append(("playwright", ok, detail, fatal))

    cache = proc.browser_cache()
    rows.append(("browsers", bool(cache),
                 cache or "not downloaded — `npx playwright install "
                          + " ".join(pw.get("browsers") or ["chromium"]) + "`", False))
    return rows


def _dig(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# ---------------------------------------------------------------- prs

def cmd_prs(args) -> int:
    """Seznam PR k recenzi.

    Existuje kvůli extension: výběr PR má být klikací, ne opisování čísla.
    Mergnuté jsou v seznamu záměrně — retrospektivní audit je plnohodnotný
    režim, ne výjimka.
    """
    project = _project(args)
    rows = []
    seen: set[int] = set()

    states = ["open", "merged"] if args.state == "all" else [args.state]
    for st in states:
        for pr in proc.pr_list(project.root, state=st, limit=args.limit):
            if pr["number"] in seen:
                continue
            seen.add(pr["number"])
            rows.append({
                "number": pr["number"],
                "title": pr.get("title"),
                "state": st,
                "kind": "merged-pull-request" if st == "merged" else "pull-request",
                "headRefOid": pr.get("headRefOid"),
                "mergedAt": pr.get("mergedAt"),
                "updatedAt": pr.get("updatedAt"),
                "author": (pr.get("author") or {}).get("login"),
                "reviewed": _reviewed(project, pr.get("headRefOid")),
            })

    def human():
        if not rows:
            print("\n  " + out.dim("No pull requests.") + "\n")
            return
        print()
        for r in rows:
            tag = out.dim("merged") if r["state"] == "merged" else out.ok("open")
            mark = out.dim(" · already reviewed") if r["reviewed"] else ""
            print(f"  #{r['number']:<5} {tag:20} {(r['title'] or '')[:58]:60}{mark}")
        print()

    return _emit(args, rows, human)


def _reviewed(project: config.Project, head: str | None) -> bool:
    """Byl tenhle přesný commit už recenzovaný? Klíč je (repo, PR, headRefOid)."""
    if not head:
        return False
    for run in runs.load_runs(project):
        if ((run.record().get("target") or {}).get("headRefOid")) == head:
            return True
    return False


# ---------------------------------------------------------------- run

def _one_line(text: str, limit: int = 400) -> str:
    """Zadání do spouštěcího příkazu. Víceřádkový text by terminál rozsekal."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def cmd_run(args, chain: dict | None = None) -> int:
    if getattr(args, "wait", False) and getattr(args, "json", False):
        # Agent píše do téhož stdout jako tenhle proces. Slíbit u toho, že na
        # výstupu bude jeden JSON dokument, nejde — a kontrakt, který se dá
        # rozbít cizím výpisem, je horší než chybějící kombinace přepínačů.
        raise SystemExit(
            "--wait and --json do not go together: the agent writes to this same "
            "stdout, so nothing could promise the output is a single JSON document. "
            "Prepare the run with --json and close it with `agency ingest`.")
    project = _project(args)
    # The positional argument names a WORKER, or a method when the project has
    # only one worker for it. Resolving it here is what lets two providers be
    # started over the same pull request without either of them being special.
    pack_name, hire = hires.resolve(project, args.pack)
    cfg = _pack_cfg(project, pack_name, asked=args.pack)
    pack = packs.load(pack_name)
    policy = pack.run_policy

    # V --json režimu se průběh potlačí, jinak by se mísil s výstupem
    # a extension by ho neuparsovala.
    out.quiet = bool(getattr(args, "json", False))

    def refuse(reason: str, code: str) -> int:
        out.note(reason)
        if out.quiet:
            print(json.dumps({"ok": False, "reason": code, "message": reason},
                             ensure_ascii=False, indent=2))
        return 1

    who = hire.display(pack.manifest.get("title")) if hire else pack.ref
    out.say(f"\n  {out.bold(who)}  {out.dim(pack.ref)} → {project.name}\n")

    # Zadání se řeší první. U packu, který ho vyžaduje, by běh bez něj jen
    # spálil přípravu a skončil na agentovi, který neví, co má dělat.
    asked = getattr(args, "prompt", None) or getattr(args, "scenario", None)
    if asked and not policy["prompt"]["accepts"]:
        raise SystemExit(
            f"Pack “{pack.name}” does not take a brief — --prompt and --scenario have "
            f"nothing to do here."
        )
    brief = runs.resolve_brief(cfg, getattr(args, "prompt", None), getattr(args, "scenario", None))
    if policy["prompt"]["required"] and not (brief["focus"] or brief["standing"]):
        return refuse(
            f"{pack.manifest.get('title') or pack.name} needs to know what to work on. "
            f"Pass --prompt \"…\", pick a --scenario, or write a standing brief into "
            f"brief.default in {posix(project.pack_config_path(pack.name))}.",
            "no-brief")

    if policy["target"] == "workspace":
        out.step("resolving the workspace")
        target = runs.resolve_workspace_target(project, getattr(args, "since", None))
        out.done(f"{target['ref']} @ {target['headRefOid'][:8]}"
                 + (f"  {out.dim('uncommitted changes included')}" if target["dirty"] else ""))
    else:
        out.step("looking up the pull request")
        target = runs.resolve_target(project, args.pr, args.latest_merged)
        kind = "merged (retrospective audit)" if target["kind"] == "merged-pull-request" else "open"
        out.done(f"PR #{target['pr']} — {target['title'][:58]}  {out.dim(kind)}")

        if target["_isDraft"] and not args.force:
            return refuse("The pull request is a draft. Continue with --force if that is intended.", "draft")
        if (runs.already_reviewed(target, pack.name, hire.id if hire else None)
                and not args.force):
            return refuse(
                f"Commit {target['headRefOid'][:8]} has already been reviewed by "
                f"{hire.id if hire else pack.name} — the marker is on the PR. "
                "Another specialist may still review it. Again: --force.",
                "already-reviewed")

    skip = (cfg.get("review") or {}).get("skipPatterns") or []
    all_files = target.pop("_files", [])
    files = [f for f in all_files if not runs._skip(f, skip)]
    skipped = len(all_files) - len(files)

    if policy["target"] == "workspace":
        # Prázdný seznam změn běh nezastaví: QA zkouší aplikaci, ne diff.
        # Změny jsou vodítko, kde hledat nejdřív, ne hranice běhu.
        out.done(f"{len(files)} changed files  {out.dim('— where to look first, not a boundary')}")
    else:
        out.done(f"{len(files)} files to review  {out.dim(f'({skipped} filtered out)')}")
        if not files:
            return refuse("No file left after filtering — there is nothing to review.", "no-files")

    run = runs.start(project, pack.ref, cfg, target, hire=hire)
    out.step(f"run {run.id}")

    wt = project.root
    wt_owned = bool(policy["worktree"])
    carried: list[str] = []
    ginfo: dict = {}
    try:
        if wt_owned:
            # The path is claimed in the record before the directory exists, so
            # a second specialist starting a moment later sees it taken instead
            # of force-deleting a review in progress.
            rec = run.record()
            rec["worktree"] = posix(runs.worktree_path(project, cfg, target, hire))
            run.save_record(rec)

            out.step("building a throwaway worktree")
            wt = runs.make_worktree(project, cfg, target, hire=hire, run=run)
            out.done(posix(wt))

            out.step("copying the pack method into the worktree")
            carried = runs.materialize_pack(project, pack, wt)
            out.done(f"{len(carried)} files" if carried
                     else "the pack installs nothing into the project")
        else:
            # Bez worktree, vědomě: aplikace, kterou pack zkouší, běží nad
            # pracovní kopií — s nainstalovanými závislostmi a s .env.
            # Zdrojový kód je pro takový běh ke ČTENÍ, zapisuje se do RUN_DIR.
            out.done(f"working in the project itself  {out.dim(posix(wt))}")

        # Na co se tenhle běh ptá. Paměti projektu bývá víc, než kolik se vejde
        # do okna, a bez dotazu se ořezává podle stáří — tedy zapomíná to
        # důležité ve prospěch toho čerstvého.
        query = knowledge.query_for(pack.name, brief, target)

        if policy["graph"]:
            out.step("updating the graph")
            ginfo = runs.prepare_graph(project, wt, cfg)
            out.done(f"graph: {ginfo['action']}"
                     + (f"  {out.dim(ginfo['tool'] or '')}" if ginfo.get("tool") else ""))

            out.step("collecting graph signal")
            stats = runs.collect_evidence(project, wt, run, target, files, query)
            out.done("evidence/ filled" + (f"  {out.dim(str(stats))}" if stats else ""))
        else:
            out.step("collecting signal from the project")
            stats = runs.collect_workspace_evidence(project, run, target, files, query)
            out.done(f"evidence/ filled  {out.dim(str(stats))}")

        if policy.get("backlog"):
            # Deterministic, so it belongs here and not to the session: the
            # queue and the roadmap wording get frozen at the moment of the
            # decision, which is the only way a cut stays reviewable later.
            out.step("reading the product queue and the roadmap")
            queue = runs.collect_backlog_evidence(project, run, cfg)
            stats.update(queue)
            if queue.get("backlogError"):
                out.fail(f"the queue could not be read — {queue['backlogError']}")
            else:
                out.done(f"{queue.get('openIssues', 0)} open issues · "
                         f"{queue.get('draftItems', 0)} drafts · "
                         f"{queue.get('roadmapFiles', 0)} roadmap files")

        # Řetěz: blok do záznamu a plný upstream do evidence. Pořadí je dané —
        # `write_context` na oba odkazuje, takže musí existovat dřív než ono.
        upstream_payload = None
        if chain:
            rec = run.record()
            rec["chain"] = chain
            run.save_record(rec)
            if chain["upstream"]:
                upstream_payload = chains.write_upstream(project, run, chain["upstream"])
                out.done(f"upstream: {upstream_payload['counts']['findings']} findings "
                         f"from {len(chain['upstream'])} run(s), "
                         f"{upstream_payload['counts']['undecided']} undecided")

        runs.write_context(run, cfg, target, wt, files, skipped,
                           brief=brief, worktree_owned=wt_owned, hire=hire,
                           pack_name=pack.name,
                           provider=getattr(args, "provider", None), chain=chain)

        rec = run.record()
        # Paměť není grafový signál. `graph` v run.v1 má zavřený seznam klíčů a
        # `knownFindings` mezi ně nepatří — slité dohromady dělaly ze záznamu
        # neplatný dokument, na který se nikdy nikdo nezeptal: `agency validate`
        # kontroluje findings.v1, run.v1 nikdo.
        memory = {k: stats.pop(k) for k in runs.MEMORY_STATS if k in stats}
        if ginfo:
            rec["graph"] = {**ginfo, **stats}
            rec["evidence"] = memory
        else:
            rec["evidence"] = {**stats, **memory}
        rec["brief"] = brief
        rec["target"]["filesReviewed"] = len(files)
        rec["target"]["filesSkipped"] = skipped
        run.save_record(rec)

    except Exception:
        if wt_owned and wt != project.root:
            runs.remove_worktree(project, wt)
        rec = run.record()
        rec.update(status="failed", finishedAt=runs.now())
        run.save_record(rec)
        raise

    # Kde se metoda packu vezme, ví `runs.method_hint` — ve worktree je jen
    # díky materialize_pack, v projektu tam, kam ji položila instalace.
    prompt = (
        f"{runs.method_hint(pack, project, carried, in_worktree=wt_owned)} "
        f"RUN_DIR={posix(run.dir)} — start from its context.json. "
        f"The required output is RUN_DIR/findings.json following finding.v1."
    )
    if chain:
        # Vykopnutí člena řetězu vlastní jádro — šablona je testovatelná a celá
        # skončí v `prompt.txt`, takže se dá číst, proč člen svou roli pochopil
        # nebo nepochopil. Obsahové věty v ní ale psal upstream agent.
        member = chains.Member(pack.name, pack.name, hire)
        prompt = chains.step_prompt(
            prompt, member, chain["position"], chain["of"],
            (upstream_payload or {}).get("runs") or [],
            (upstream_payload or {}).get("counts") or {"findings": 0, "undecided": 0},
            chain.get("handoff"))
    if brief["focus"]:
        # Zadání jde i do spouštěcího příkazu, ne jen do context.json: uživatel
        # má na obrazovce vidět, s čím agenta pouští.
        prompt += " Brief for this run: " + _one_line(brief["focus"])
    launch, agent_info = runs.launch_argv(
        # Celá paměť projektu, ne jen RUN_DIR: `context.json` posílá specialistu
        # do bundlu, do stránek packu a v řetězu do upstream běhů. Povolit mu
        # jen jeden z nich znamená ptát se ho na svolení k cestám, které jsme
        # mu sami dali.
        cfg, posix(project.agency_dir), prompt, hire=hire,
        provider=getattr(args, "provider", None), model=getattr(args, "model", None))
    rec = run.record()
    rec["agent"] = agent_info
    run.save_record(rec)
    (run.dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    if out.quiet:
        # Kontrakt pro extension: kde běh leží, kde je worktree a čím ho dokončit.
        print(json.dumps({
            "ok": True,
            "runId": run.id,
            "runDir": posix(run.dir),
            "worktree": posix(wt),
            "worktreeOwned": wt_owned,
            "hire": hire.as_dict() if hire else None,
            "brief": brief,
            "prompt": prompt,
            # Hotový příkaz — tvar spuštění vlastní CLI, ne klient.
            "launch": launch,
            "agent": agent_info,
            "target": {k: v for k, v in target.items() if not k.startswith("_")},
            "files": len(files),
            "filesSkipped": skipped,
            "graph": {**ginfo, **stats},
            "evidence": memory if ginfo else {**stats, **memory},
        }, ensure_ascii=False, indent=2))
        return 0

    out.say()
    out.done("preparation done — the deterministic part is finished")
    out.say()
    if wt_owned:
        out.say(f"  {out.dim('The worktree stays until you finish the run:')}")
        out.say(f"  {out.dim(posix(wt))}")
    else:
        out.say(f"  {out.dim('The run works in the project itself — nothing to clean up afterwards.')}")
    if brief["focus"] or brief["standing"]:
        out.say()
        out.say(f"  {out.dim('Brief:')} {_one_line(brief['focus'] or brief['standing'], 120)}")
    out.say()

    if args.wait:
        return _wait_for_agent(project, run, launch, wt, wt_owned)

    if args.launch:
        os.chdir(wt)
        out.say(f"  {out.bold('launching ' + launch[0] + '…')}\n")
        # `which` kvůli Windows: spouštění si domyslí jen `.exe`, takže `codex`
        # — fakticky `codex.CMD` — by jinak spadl na FileNotFoundError.
        os.execvp(proc.which(launch[0]) or launch[0], launch)

    print(f"  {out.bold('Start it:')}")
    print(f"    cd {posix(wt)}")
    print("    " + " ".join(
        json.dumps(a, ensure_ascii=False) if " " in a else a for a in launch))
    print()
    print(f"  {out.dim('When it finishes:')}  agency ingest --run {run.id[:8]}")
    if wt_owned:
        print(f"  {out.dim('Cleanup:')}           agency cleanup --run {run.id[:8]}")
    print()
    return 0


def cmd_chain(args) -> int:
    """`agency chain legal po` — specialisté za sebou, s předáním mezi nimi.

    Orchestrace je smyčka nad `cmd_run`, ne druhá cesta ke spuštění běhu. Je to
    záměr: kdyby chain běh připravoval sám, měl by projekt dvě místa, kde vzniká
    worktree, evidence a run record — a to druhé by tiše zastarávalo. Chain umí
    jen tři věci navíc, které samostatný běh nemá: složit členy, předat výstup
    dál a zastavit se, když někdo neuspěje.
    """
    project = _project(args)
    members = chains.resolve(project, args.members)

    if len(members) < 2:
        raise SystemExit("A chain needs at least two members — for one, `agency run` is the command.")

    if mixed := chains.one_provider(members):
        raise SystemExit(mixed)

    for m in members:
        # Radši teď než po prvním doběhnutém běhu: uživatel, kterému chain spadne
        # na překlepu ve třetím jméně, už zaplatil dva běhy.
        packs.load(m.pack)

    chain_id = ulid()
    out.say(f"\n  {out.bold('chain')}  "
            f"{out.dim(' → '.join(m.label for m in members))}  ·  {chain_id[:10]}\n")

    done: list[str] = []
    for position, member in enumerate(members, start=1):
        # Přepínače chainu platí pro každý krok stejně; `members` a `fn` jsou
        # věci orchestrátoru a členu by nedávaly smysl. `--json` je vypnuté
        # natvrdo: `--wait` píše do téhož stdout jako agent.
        carried = {k: v for k, v in vars(args).items() if k not in ("members", "fn")}
        step = argparse.Namespace(**{**carried, "pack": member.ref,
                                     "wait": True, "launch": False, "json": False})
        block = chains.block(chain_id, position, len(members), list(done))

        if done:
            # Vzkaz předchůdce jde do promptu jako jeho slova, ne jako převyprávění.
            previous = chains.find_member(project, chain_id, position - 1)
            text, source = chains.handoff_text(previous) if previous else (None, None)
            block["handoff"] = text
            if source:
                out.say(f"  {out.dim('handing over ' + source + ' from ' + members[position - 2].label)}")

        out.say(f"\n  {out.bold(f'step {position}/{len(members)}')}  {member.label}")
        code = cmd_run(step, chain=block)

        run = chains.find_member(project, chain_id, position)
        if run:
            done.append(run.id)

        if code != 0:
            # Pokračovat potichu by znamenalo, že další člen soudí nálezy, které
            # nevznikly. Co doběhlo, je zapsané a dokončit to jde ručně.
            out.say()
            out.fail(f"the chain stops at step {position}/{len(members)} ({member.label})")
            _chain_report(chain_id, members, done, position)
            return code

    out.say()
    out.done(f"chain finished — {len(done)} runs  {out.dim(chain_id[:10])}")
    _chain_report(chain_id, members, done, len(members))
    return 0


def _chain_report(chain_id: str, members, done: list[str], reached: int) -> None:
    """Co doběhlo a čím to stojí. Tiskne se po dokončení i po zastavení —
    přerušený řetěz je pořád výsledek, jen kratší."""
    out.say()
    for i, member in enumerate(members, start=1):
        run_id = done[i - 1] if i <= len(done) else None
        mark = "·" if run_id else " "
        state = out.dim(run_id[:10]) if run_id else out.dim("not started")
        if i == reached and run_id and reached < len(members):
            state += out.dim("  (stopped here)")
        out.say(f"  {mark} {i}/{len(members)}  {member.label:<24} {state}")
    out.say()
    if done:
        out.say(f"  {out.dim('Triage queue:')}  agency triage --list")


def _duration(seconds: float) -> str:
    """Doba běhu tak, jak ji čte člověk."""
    s = int(round(seconds))
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _wait_for_agent(project, run, launch: list[str], wt: Path, wt_owned: bool) -> int:
    """`--wait`: spustit agenta, počkat na něj a pustit bránu rovnou.

    Attended charakter se nemění — agent píše do tohohle terminálu a dá se do
    něj vstoupit. Mění se, kdo drží konec: dosud musel uživatel po doběhnutí
    napsat `agency ingest` a když na to zapomněl, zůstal běh navždycky
    `running` — bez nálezů, bez čísel a s worktree navíc.
    """
    out.say(f"  {out.bold('launching ' + launch[0] + '…')}  "
            f"{out.dim('Ctrl-C stops the run')}\n")
    try:
        result = runs.attend(project, run, launch, wt)
    except KeyboardInterrupt:
        # Přerušení není pád. Běh se zavírá jako opuštěný — a protože tenhle
        # proces na rozdíl od `--launch` pořád žije, uklidí i worktree, na který
        # by jinak musel uživatel přijít sám.
        info = runs.abandon(project, run, "stopped with Ctrl-C while the agent was running")
        out.say()
        out.note(f"stopped — {run.id[:10]} closed as abandoned"
                 + ("  ·  worktree removed" if info.get("worktreeRemoved") else ""))
        return 130

    code = result["exitCode"]
    out.say()
    out.say(f"  {out.dim('agent finished')}  exit {code}  {out.dim('·')}  "
            f"{_duration(result['wallClockSeconds'])}")

    # Co agent stihl zapsat, projde branou i po nenulovém konci. Zahodit hotové
    # nálezy kvůli chybě na konci sezení by byla ztráta, ne přísnost.
    if code == 0 or run.findings_path.is_file() or (run.dir / "findings.raw.json").is_file():
        _ingest_report(run, ingest.ingest(project, run))

    if code != 0:
        # Až po bráně: ta by z běhu bez findings.json udělala `no-findings`,
        # což je tvrzení „díval se a nic nenašel“. Exit code říká něco jiného.
        runs.failed(run, f"the agent exited with {code}")
        out.fail(f"the agent exited with {code} — the run is recorded as failed")
        if proc.which(launch[0]) is None:
            out.say(f"  {out.dim(launch[0] + ' is not on PATH; `agency doctor` checks that up front')}")
        out.say()

    if wt_owned:
        print(f"  {out.dim('Cleanup:')}  agency cleanup --run {run.id[:8]}\n")
    return 0 if code == 0 else 1


def cmd_cleanup(args) -> int:
    """Close a run that is not coming back, and take its worktree with it.

    Killing the terminal leaves two things behind: a record that still says
    `running`, and a worktree nobody will ever look at. Neither closes itself
    when the run was prepared and handed over: the CLI prints a command, and
    whatever runs it lives in a terminal this process knows nothing about. No
    pid to watch, no exit code to catch — closing the run is the same act as
    closing the terminal, and it belongs to the person who did it.

    `agency run --wait` is the way around it: that one owns the process, so it
    closes its own run. This command is for everything else — and for the runs
    that were left behind before it existed.
    """
    project = _project(args)

    targets: list = []
    if getattr(args, "unfinished", False):
        targets = runs.unfinished(project)
        if not targets:
            return _emit(args, {"closed": [], "unfinished": 0},
                         lambda: out.note("no run is still marked as running"))
    else:
        run = runs.find_run(project, args.run)
        if not run:
            raise SystemExit("No run found.")
        targets = [run]

    results = []
    for run in targets:
        rec = run.record()
        if getattr(args, "discard", False):
            results.append({**runs.discard(project, run, force=args.force), "action": "discarded"})
            continue

        ctx = read_json(run.dir / "context.json", default={})
        if rec.get("status") == "running":
            results.append({**runs.abandon(project, run), "action": "abandoned"})
        elif ctx.get("worktreeOwned") is False:
            # Běh bez vlastního worktree jel v pracovní kopii uživatele. Smazat ji
            # by bylo to nejhorší, co tenhle nástroj může udělat — proto se to hlídá
            # záznamem v kontextu, ne porovnáním cest.
            results.append({"run": run.id, "action": "nothing",
                            "why": "the run worked in the project itself"})
        else:
            wt = ctx.get("worktree")
            gone = bool(wt and Path(wt).exists())
            if gone:
                runs.remove_worktree(project, Path(wt))
                rec.pop("worktree", None)
                run.save_record(rec)
            results.append({"run": run.id, "action": "cleaned",
                            "worktreeRemoved": wt if gone else None})

    data = {"closed": results, "unfinished": len(runs.unfinished(project))}

    def human():
        for r in results:
            if r["action"] == "abandoned":
                out.done(f"{r['run'][:10]} closed as abandoned"
                         + (f"  {out.dim('worktree removed')}" if r.get("worktreeRemoved") else ""))
            elif r["action"] == "discarded":
                out.done(f"{r['run'][:10]} discarded — {r['findings']} findings went with it")
            elif r["action"] == "cleaned":
                out.done(f"worktree removed: {r['worktreeRemoved']}" if r["worktreeRemoved"]
                         else "the worktree no longer exists")
            else:
                out.note(r["why"])

    return _emit(args, data, human)


# ---------------------------------------------------------------- validate

def cmd_validate(args) -> int:
    project = _project(args)
    run = runs.find_run(project, args.run)
    if not run:
        raise SystemExit("No run found.")

    findings = run.findings()
    errors: list[dict] = []
    record_errors: list[dict] = []
    try:
        import jsonschema
        schema = read_json(bundled("schemas", "finding.v1.json"))
        v = jsonschema.Draft202012Validator(schema)
        for i, f in enumerate(findings):
            for e in v.iter_errors(f):
                errors.append({"index": i, "id": f.get("id"),
                               "path": "/".join(str(p) for p in e.path), "message": e.message})
        # A záznam běhu proti run.v1. Do 1. 9. 2026 ho nekontroloval nikdo —
        # a stihl se se svým vlastním kontraktem rozejít na třech místech,
        # aniž by to cokoli poznalo. Kontrakt, který se neověřuje, není kontrakt.
        rv = jsonschema.Draft202012Validator(read_json(bundled("schemas", "run.v1.json")))
        for e in rv.iter_errors(run.record()):
            record_errors.append({"path": "/".join(str(p) for p in e.path) or "(root)",
                                  "message": e.message})
    except ImportError:
        out.note("jsonschema is not installed, checking required fields only")
        for i, f in enumerate(findings):
            for key in ("id", "runId", "pack", "severity", "title", "body", "anchor", "evidence"):
                if key not in f:
                    errors.append({"index": i, "id": f.get("id"), "path": key, "message": "missing"})

    # Kotva se ověřuje proti pracovní kopii — nález, který nejde umístit, je
    # nález, který za měsíc nikdo nedohledá.
    resolved = []
    for f in findings:
        a = f.get("anchor") or {}
        if not a.get("file"):
            continue
        r = anchor.resolve(project.root, a)
        resolved.append({"id": f.get("id"), "file": a["file"], "line": a.get("line"),
                         "resolvedLine": r.line, "via": r.via, "note": r.note,
                         "drift": anchor.drift(project.root, a)})

    # `validate` je ČTENÍ. Stav běhu mění `ingest` — kdyby ho psaly obě cesty,
    # nešlo by z run recordu poznat, jestli nálezy prošly bránou, nebo jestli
    # je někdo jen zkontroloval.
    data = {"run": run.id, "findings": len(findings), "errors": errors,
            "recordErrors": record_errors, "anchors": resolved}

    def human():
        print(f"\n  run {out.bold(run.id)}  ·  {len(findings)} findings\n")
        if errors:
            print(f"  {out.err('The contract does not match:')}")
            for e in errors[:20]:
                print(f"    #{e['index']} {e['path']}: {e['message'][:90]}")
            print()
        if record_errors:
            print(f"  {out.err('The run record does not match run.v1:')}")
            for e in record_errors[:20]:
                print(f"    {e['path']}: {e['message'][:90]}")
            print()
        for r in resolved:
            icon = out.ok("✓") if r["resolvedLine"] else out.warn("?")
            loc = f"{r['file']}:{r['resolvedLine'] or r['line']}"
            print(f"  {icon} {loc:56} {out.dim(r['via'])} {out.dim(r['note'])}")
        print()
        if not errors and not record_errors:
            print(f"  {out.ok('The findings match finding.v1, the record matches run.v1.')}\n")

    _emit(args, data, human)
    return 1 if errors or record_errors else 0


# ---------------------------------------------------------------- graph

def cmd_graph(args) -> int:
    """Jedny dveře ke grafu — pro jádro i pro agenta.

    Půlka použití grafu žije v promptu (`SKILL.md`) a Python fasáda ji nepokryje.
    Vedlejší efekt je ten důležitý: šev se testuje každým během, ne až teoreticky
    v den výměny driveru.

    Výstup je vždycky JSON. Konzument je agent nebo skript; člověk, který se ptá
    na stav grafu, má `agency doctor`.
    """
    project = _project(args)
    root = project.root

    if args.verb == "capabilities":
        return _emit_json({
            "driver": graph.DRIVER, "tool": graph.version(),
            "capabilities": graph.capabilities(),
            "workspaceStrategy": graph.WORKSPACE_STRATEGY,
        })

    verbs = {
        "state": lambda: graph.state(root),
        "refresh": lambda: graph.refresh(root),
        "changes": lambda: graph.changes(root, args.base),
        "impact": lambda: graph.impact(root, args.files or [], depth=args.depth),
        "locate": lambda: graph.locate(root, args.symbol, kind=args.kind),
        "neighbors": lambda: graph.neighbors(root, args.symbol, direction=args.direction),
        "unreferenced": lambda: graph.unreferenced(root, args.path),
        "tests-for": lambda: graph.tests_for(root, args.symbol),
    }
    answer = verbs[args.verb]()
    _emit_json({"ok": answer.ok, "verb": args.verb,
                "data": answer.data, "error": answer.error})
    return 0 if answer.ok else 1


def _emit_json(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- ingest

def _ingest_report(run, data: dict) -> None:
    """Výstup brány. Tiskne ho `agency ingest` i `agency run --wait` — týž běh
    má vypadat stejně, ať branou prošel hned, nebo o hodinu později."""
    c = data["counts"]
    print(f"\n  run {out.bold(run.id)}\n")
    print(f"  {c['raw']:3} findings written by the pack")
    if data["dropped"]:
        print(f"  {out.err(str(c['gated']).rjust(3))} dropped by the gate")
        for d in data["dropped"]:
            label = (d["title"] or d["id"] or "")[:52]
            print(f"      {out.dim('·')} {label:54} {out.err(d['reason'])} "
                  f"{out.dim(d['detail'][:60])}")
    if data["duplicates"]:
        print(f"  {out.warn(str(len(data['duplicates'])).rjust(3))} duplicates of older findings")
        for d in data["duplicates"]:
            label = (d["title"] or "")[:52]
            ref = "= " + (d["duplicateOf"] or "")[:10]
            print(f"      {out.dim('·')} {label:54} {out.dim(ref)} {out.dim(d['how'])}")
    print(f"  {out.ok(str(c['kept']).rjust(3))} candidates to decide\n")
    b = data.get("bundle") or {}
    if b.get("error"):
        print(f"  {out.warn('knowledge bundle not written')} {out.dim(b['error'])}")
        print(f"  {out.dim('The findings are safe in .agency/runs/ — `agency knowledge --rebuild` catches it up.')}\n")
    elif b.get("changed") or b.get("removed"):
        touched = len(b.get("changed") or []) + len(b.get("removed") or [])
        print(f"  {out.dim('knowledge')}  {touched} file{'' if touched == 1 else 's'} "
              f"updated in {out.dim(b['path'])}\n")
    if c["kept"]:
        print(f"  Next: {out.bold('agency findings')}  or the Agency panel in VS Code\n")


def cmd_ingest(args) -> int:
    """Brána mezi tím, co napsal agent, a tím, co se stane nálezem."""
    project = _project(args)
    run = runs.find_run(project, args.run)
    if not run:
        raise SystemExit("No run found.")

    data = ingest.ingest(project, run, min_score=args.min_score)
    _emit(args, data, lambda: _ingest_report(run, data))
    return 0


# ---------------------------------------------------------------- knowledge

def cmd_knowledge(args) -> int:
    """Co projekt ví, jako commitovaný markdown.

    Bez `--rebuild` se nic nezapisuje — jen se řekne, jestli je odvozený bundle
    v souladu s běhy. To je ta otázka, kterou má smysl umět položit: bundle je
    přestavitelný, takže rozdíl proti `.agency/runs/` je vždycky chyba bundlu.
    """
    project = _project(args)
    data = knowledge.bundle(project, write=args.rebuild)
    data["rules"] = knowledge.rules_summary(project)
    data["pages"] = knowledge.pages_summary(project)

    def human():
        print(f"\n  {out.bold('knowledge')}  {out.dim(data['path'])}\n")
        pages = data["pages"]
        print(f"  {str(data['findings']).rjust(3)} findings"
              f"  {out.dim('·')}  {data['rules']['total']} rules"
              f"  {out.dim('·')}  {pages['total']} pages"
              + (f"  {out.dim('(' + ', '.join(f'{k} {v}' for k, v in pages['byPack'].items()) + ')')}"
                 if pages["byPack"] else ""))
        touched = data["changed"] + data["removed"]
        plural = "" if len(touched) == 1 else "s"
        if args.rebuild:
            print(f"  {out.ok(str(len(touched)).rjust(3))} file{plural} rewritten"
                  if touched else f"  {out.dim('already up to date')}")
        elif touched:
            print(f"  {out.warn(str(len(touched)).rjust(3))} file{plural} out of date")
            for name in touched[:10]:
                print(f"      {out.dim('·')} {name}")
            print(f"\n  Next: {out.bold('agency knowledge --rebuild')}")
        else:
            print(f"  {out.dim('up to date with .agency/runs/')}")
        print()

    return _emit(args, data, human)


# ---------------------------------------------------------------- metrics

def _bar(t: dict) -> str:
    """Precision jako proužek. None není nula — prázdno se kreslí jako pomlčka,
    protože „nevím" a „nic z toho neplatí" jsou dvě různé zprávy."""
    p = t.get("precision")
    if p is None:
        return out.dim("—".ljust(10)) + "     "
    filled = round(p * 10)
    color = out.ok if p >= 0.7 else out.warn if p >= 0.4 else out.err
    return color("#" * filled + "." * (10 - filled)) + f" {p:.0%}".rjust(5)


def cmd_metrics(args) -> int:
    projects = registry.resolve() if args.all_projects else [_project(args)]
    if not projects:
        raise SystemExit("The registry is empty — run `agency metrics` inside a project.")
    reports = [metrics.collect(p) for p in projects]
    data = reports if args.all_projects else reports[0]

    def table(title: str, rows: dict) -> None:
        rows = {k: v for k, v in (rows or {}).items() if v["accepted"] + v["rejected"]}
        if not rows:
            return
        print(f"  {out.dim(title)}")
        for k, v in rows.items():
            tally = f"{v['accepted']} yes / {v['rejected']} no"
            print(f"    {k[:22]:24} {_bar(v)}  {out.dim(tally)}")
        print()

    def one(r: dict) -> None:
        f, t, q = r["findings"], r["triage"], r["queue"]
        print(f"\n  {out.bold(r['project']['name'])}  {out.dim(str(r['runs']) + ' runs')}\n")
        undec = out.dim(f"  ({t['undecided']} undecided)") if t["undecided"] else ""
        print(f"  {out.bold('Precision')}   {_bar(t)}   "
              f"{t['accepted']} accepted / {t['rejected']} rejected{undec}")
        if not (t["accepted"] + t["rejected"]):
            print(f"  {out.dim('Nothing to compute from yet — precision comes out of triage.')}")
        print()
        dedup_note = out.dim(f"({f['dedupRatio']:.0%} duplicates)") if f["dedupRatio"] else ""
        print(f"  {out.dim('Gate')}            {f['raw']} written → {f['kept']} candidates  {dedup_note}")
        if f["gatedBy"]:
            print(f"  {out.dim('Dropped')}         "
                  + ", ".join(f"{v}x {k}" for k, v in f["gatedBy"].items()))
        if q["undecided"]:
            age = f", median {q['medianAgeDays']} days" if q["medianAgeDays"] else ""
            old = f", oldest {q['oldestDays']} days" if q["oldestDays"] else ""
            print(f"  {out.dim('Queue')}           {q['undecided']} waiting{age}{old}")
        if r["cost"]["secondsPerKeptFinding"]:
            print(f"  {out.dim('Cost')}            "
                  f"{r['cost']['secondsPerKeptFinding']} s per candidate")
        print()
        table("by dimension", r["byDimension"])
        table("by severity", r["bySeverity"])
        table("by specialist", r["byHire"])
        table("by model", r["byModel"])
        # Only worth printing once two workers have actually met over the same
        # code — with one hire the number is always zero and says nothing.
        ag = r.get("agreement") or {}
        if ag.get("hires", 0) > 1 and (ag["crossHire"] or ag["sameHire"]):
            print(f"  {out.dim('agreement')}")
            print(f"    {'found by another specialist too':32} {ag['crossHire']}")
            print(f"    {'found twice by the same one':32} {ag['sameHire']}")
            print(out.dim("    A high first number means the second runner is buying "
                          "confirmation, not coverage.\n"))
        if r["rejectReasons"]:
            print(f"  {out.dim('reasons for rejection')}")
            for k, v in r["rejectReasons"].items():
                print(f"    {k[:22]:24} {v}")
            print()

    def human():
        for r in reports:
            one(r)

    return _emit(args, data, human)


# ---------------------------------------------------------------- export

def cmd_export(args) -> int:
    project = _project(args)
    cfg = _pack_cfg(project, args.pack)
    number = args.project_number or (cfg.get("sinks") or {}).get("githubProject")
    if not number:
        raise SystemExit(
            "Nowhere to export to. Add `sinks.githubProject` to "
            f"{posix(project.pack_config_path(args.pack))}, or use --project <number>.")
    owner = args.owner or (project.slug or "/").split("/")[0]
    if not owner:
        raise SystemExit("Cannot tell who owns the Project. Use --owner.")

    if args.run:
        r = runs.find_run(project, args.run)
        selected = [r] if r else []
    else:
        selected = runs.load_runs(project)
    rows = export.plan(selected, only_decided=not args.include_undecided)
    if not rows:
        raise SystemExit(
            "Nothing to export. Only decided findings are exported — "
            "triage them, or run with --include-undecided.")

    data = export.push(rows, int(number), owner, dry_run=args.dry_run)

    def human():
        if data["dryRun"]:
            head = "Dry run — nothing was sent"
        else:
            title = data["project"].get("title")
            head = f"Project #{number} ({owner})" + (f" — {title}" if title else "")
        print(f"\n  {out.bold(head)}\n")
        for r in data["created"]:
            print(f"  {out.ok('+')} {(r['title'] or '')[:70]}")
        for r in data["updated"]:
            print(f"  {out.dim('~')} {(r['title'] or '')[:70]}")
        for r in data["fieldSkips"]:
            print(f"  {out.warn('!')} field {r['field']}: {r['why']}")
        for r in data["failed"]:
            print(f"  {out.err('x')} {(r['title'] or '')[:50]} — {r['error']}")
        fail = out.err(f", {len(data['failed'])} failed") if data["failed"] else ""
        print(f"\n  {len(data['created'])} new, "
              f"{len(data['updated'])} updated{fail}\n")

    _emit(args, data, human)
    return 1 if data["failed"] else 0


# ---------------------------------------------------------------- projects

def cmd_projects(args) -> int:
    rows = []
    for p in registry.resolve():
        all_runs = runs.load_runs(p)
        undecided = 0
        for r in all_runs:
            dec = runs.decisions(r)
            undecided += sum(1 for f in r.findings()
                             if f.get("state") != "duplicate" and f.get("id") not in dec)
        rows.append({
            "name": p.name, "slug": p.slug, "root": posix(p.root),
            "packs": sorted((p.installed().get("packs") or {}).keys()),
            "runs": len(all_runs), "undecided": undecided,
            "lastRun": all_runs[0].record().get("startedAt") if all_runs else None,
        })

    def human():
        if not rows:
            print(f"\n  {out.dim('The registry is empty. It fills up with the first `agency add` in a project.')}\n")
            return
        print()
        for r in rows:
            badge = out.warn(f"{r['undecided']} to decide") if r["undecided"] else out.dim("clear")
            packs_ = ", ".join(r["packs"]) or "no pack"
            print(f"  {out.bold(r['name']):28} {r['runs']:3} runs  {badge:24} {out.dim(packs_)}")
            print(f"  {'':28} {out.dim(r['root'])}")
        print()

    return _emit(args, rows, human)


# ---------------------------------------------------------------- findings

def cmd_findings(args) -> int:
    project = _project(args)
    selected = runs.load_runs(project) if args.all else (
        [r] if (r := runs.find_run(project, args.run)) else [])

    rows = []
    for run in selected:
        dec = runs.decisions(run)
        hist = runs.history(run)
        rec = run.record()
        for f in run.findings():
            d = dec.get(f.get("id"))
            a = f.get("anchor") or {}
            row = {
                "runId": run.id, "id": f.get("id"), "severity": f.get("severity"),
                "title": f.get("title"), "body": f.get("body"),
                "dimension": f.get("dimension"),
                "file": a.get("file"), "line": a.get("line"),
                "decision": d["state"] if d else None,
                "reason": d.get("reason") if d else None,
                "note": d.get("note") if d else None,
                # Normalizované, ne surové: starý zápis (`cli`, `vscode`) je
                # člověk a klient nemá mít dvě jména pro totéž.
                "by": runs.normalize_by(d.get("by")) if d else None,
            }
            # Kotva a drift jen do --json: konzumentem je extension, která bez
            # nich neumí ani proklik, ani pohled na kód v den analýzy.
            if getattr(args, "json", False):
                row["anchor"] = a
                row["evidence"] = f.get("evidence") or []
                row["target"] = rec.get("target") or {}
                row["history"] = hist.get(f.get("id"), [])
                row["state"] = f.get("state")
                row["duplicateOf"] = f.get("duplicateOf")
                row["score"] = f.get("score")
                row["pack"] = f.get("pack")
                if a.get("file"):
                    row["drift"] = anchor.drift(project.root, a)
                    r = anchor.resolve(project.root, a)
                    row["resolved"] = {"line": r.line, "via": r.via, "note": r.note}
            rows.append(row)

    def human():
        if not rows:
            print(f"\n  {out.dim('No findings. Run `agency run review-graph --pr <n>`.')}\n")
            return
        undecided = sum(1 for r in rows if not r["decision"])
        print(f"\n  {len(rows)} findings, {undecided} undecided\n")
        mark = {"accepted": out.ok("✔"), "rejected": out.err("✘"), "deferred": out.warn("⏱")}
        sev = {"blocker": out.err("●"), "high": out.err("●"), "medium": out.warn("●"), "low": out.dim("●")}
        for r in rows:
            m = mark.get(r["decision"], out.dim("·"))
            tail = ""
            if r["decision"]:
                tail = out.dim(f"{r['decision']}{'/' + r['reason'] if r['reason'] else ''} ({r['by']})")
            print(f"  {m} {sev.get(r['severity'], '·')} {(r['id'] or '')[:8]:9} "
                  f"{(r['title'] or '')[:52]:54} {out.dim(f'{r['file']}:{r['line']}')} {tail}")
        print()

    return _emit(args, rows, human)


def _run_with_finding(project: config.Project, finding_id: str) -> runs.Run:
    for r in runs.load_runs(project):
        if any(f.get("id") == finding_id for f in r.findings()):
            return r
    raise SystemExit(f"Finding “{finding_id}” was not found in any run.")


def cmd_triage(args) -> int:
    project = _project(args)
    run = _run_with_finding(project, args.finding)

    state = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}[args.action]
    ev = runs.append_decision(run, args.finding, state, args.reason, args.note, args.by)

    def human():
        print(f"  {args.finding} → {ev['state']}"
              + (f" · {ev['reason']}" if ev["reason"] else "")
              + (f" · {ev['note']}" if ev["note"] else ""))

    return _emit(args, ev, human)


def _set_path(data: dict, dotted: str, value) -> None:
    cur = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _unset_path(data: dict, dotted: str) -> bool:
    cur = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur.get(part)
        if not isinstance(cur, dict):
            return False
    return cur.pop(parts[-1], _MISSING) is not _MISSING


_MISSING = object()


def cmd_config(args) -> int:
    """Konfigurace packu — čtení i zápis jednou cestou.

    Zapisovat sem smí i klient: nastavení bydlí v projektu, ne v editoru, takže
    co nastavíš klikem, platí i pro běh z terminálu a pro agenta. Kdyby si
    extension držela vlastní kopii nastavení, byly by dvě pravdy o jedné věci.
    """
    project = _project(args)
    pack = packs.load(args.pack)
    path = project.pack_config_path(pack.name)
    if not path.is_file():
        raise SystemExit(f"Pack “{pack.name}” is not installed here. Run `agency add {pack.name}`.")

    raw = read_json(path, default={})
    changed: list[str] = []

    for pair in (args.set_pairs or []):
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"Expected key=value, got “{pair}”.")
        key = key.strip()
        if key.split(".")[0] == "pack":
            raise SystemExit("`pack` is stamped by the installation — change it with `agency add`.")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value  # holý text je platná hodnota, ne chyba
        _set_path(raw, key, parsed)
        changed.append(key)

    for key in (args.unset or []):
        if _unset_path(raw, key):
            changed.append(f"-{key}")

    if changed:
        write_json(path, raw)

    data = {
        "pack": pack.name,
        "path": posix(path),
        "config": strip_comments(raw),
        # Co si nástroj o projektu domyslí sám. Klient tím umí ukázat „tenhle
        # projekt už Playwright má" místo prázdného pole k vyplnění.
        "detected": config.detect(project),
        "run": pack.run_policy,
        "changed": changed,
    }

    def human():
        print(f"\n  {out.bold(pack.name)}  {out.dim(posix(path))}\n")
        if changed:
            print(f"  {out.ok('updated')} {', '.join(changed)}\n")
        print(json.dumps(data["config"], ensure_ascii=False, indent=2))
        print()

    return _emit(args, data, human)


def cmd_brief(args) -> int:
    """Co má pack dělat — trvale, nebo pod jménem.

    Zadání je konfigurace projektu, ne argument jednoho spuštění: „na tomhle
    projektu vždycky zkoušej rezervace a platby“ nemá cenu psát pokaždé znovu.
    Zapisuje se do `.agency/<pack>.json` k ostatní konfiguraci a čte ho stejně
    CLI, extension i agent.
    """
    project = _project(args)
    pack = packs.load(args.pack)
    path = project.pack_config_path(pack.name)
    if not path.is_file():
        raise SystemExit(f"Pack “{pack.name}” is not installed here. Run `agency add {pack.name}`.")

    # Čte se surový soubor včetně komentářů — konfiguraci vlastní projekt
    # a zápis z CLI mu nesmí vymazat dokumentaci šablony.
    raw = read_json(path, default={})
    brief = raw.setdefault("brief", {})
    scenarios = brief.setdefault("scenarios", {})
    changed = False

    if args.remove:
        if not args.scenario:
            raise SystemExit("--remove needs --scenario <name>.")
        if args.scenario not in scenarios:
            raise SystemExit(f"There is no scenario “{args.scenario}”.")
        scenarios.pop(args.scenario)
        changed = True
    elif args.set_text is not None:
        text = args.set_text.strip()
        if args.scenario:
            if not text:
                raise SystemExit("An empty scenario makes no sense — use --remove.")
            scenarios[args.scenario] = text
        else:
            brief["default"] = text or None
        changed = True

    if changed:
        write_json(path, raw)

    data = {
        "pack": pack.name,
        "configPath": posix(path),
        "accepts": pack.run_policy["prompt"]["accepts"],
        "standing": brief.get("default"),
        "scenarios": [{"name": k, "text": v} for k, v in sorted(scenarios.items())],
        "changed": changed,
    }

    def human():
        print(f"\n  {out.bold(pack.name)}  {out.dim(posix(path))}\n")
        if not data["accepts"]:
            print(f"  {out.warn('This pack does not take a brief.')} "
                  f"{out.dim('The text would be written but never read.')}\n")
        print(f"  {out.bold('standing')}  {out.dim('— applies to every run of this pack')}")
        print(f"    {data['standing'] or out.dim('not set')}")
        print()
        print(f"  {out.bold('scenarios')} {out.dim('— agency run ' + pack.name + ' --scenario <name>')}")
        if not data["scenarios"]:
            print(f"    {out.dim('none')}")
        for sc in data["scenarios"]:
            print(f"    {out.ok(sc['name']):20} {out.dim(_one_line(sc['text'], 70))}")
        print()

    return _emit(args, data, human)


def cmd_note(args) -> int:
    """Poznámka k nálezu. Vlastní příkaz, protože poznámka není rozhodnutí."""
    project = _project(args)
    run = _run_with_finding(project, args.finding)
    ev = runs.append_note(run, args.finding, args.text, args.by)

    def human():
        print(f"  {args.finding}: {ev['text']}")

    return _emit(args, ev, human)


def _target_label(target: dict) -> str:
    """Jak se cíl běhu jmenuje na jeden řádek."""
    if target.get("pr"):
        return f"PR #{target['pr']}"
    if target.get("kind") == "workspace":
        return target.get("ref") or "workspace"
    return target.get("title") or "—"


def cmd_status(args) -> int:
    project = _project(args)
    all_runs = runs.load_runs(project)
    data = []
    for run in all_runs[:args.limit]:
        rec = run.record()
        dec = runs.decisions(run)
        fs = run.findings()
        agent = rec.get("agent") or {}
        data.append({
            "id": run.id, "pack": rec.get("pack"), "status": rec.get("status"),
            "startedAt": rec.get("startedAt"),
            # Who took it. With several specialists over one pack the pack name
            # no longer identifies the run — and comparing them is the reason
            # for hiring more than one.
            "hire": agent.get("hire"),
            "provider": agent.get("provider"),
            "model": agent.get("model"),
            "target": (rec.get("target") or {}).get("pr"),
            "kind": (rec.get("target") or {}).get("kind"),
            # Popisek cíle skládá jádro, ne klient — běh bez PR by se v UI
            # jinak ukazoval jako holé ULID.
            "targetLabel": _target_label(rec.get("target") or {}),
            "brief": (rec.get("brief") or {}).get("focus")
                     or (rec.get("brief") or {}).get("standing"),
            # Členství v řetězu. Klient tím seskupuje běhy, které patřily
            # k sobě — bez toho vypadá tým jako několik nesouvisejících běhů.
            "chain": rec.get("chain"),
            "findings": len(fs), "undecided": sum(1 for f in fs if f.get("id") not in dec),
        })

    def human():
        print(f"\n  {out.bold(project.name)}  {out.dim(posix(project.root))}")
        installed = [f"{n} {v.get('ref')}" for n, v in (project.installed().get("packs") or {}).items()]
        print(f"  {out.dim('packs:')} {', '.join(installed) or out.dim('none')}")
        crew = [f"{h.id} ({h.label})" for h in hires.roster(project)]
        print(f"  {out.dim('hired:')} {', '.join(crew) or out.dim('nobody')}\n")
        if not data:
            print(f"  {out.dim('No runs yet.')}\n")
            return
        for d in data:
            icon = {"ok": out.ok("✓"), "no-findings": out.ok("○"), "running": out.warn("…"),
                    "abandoned": out.dim("×"), "failed": out.err("✗")}.get(
                        d["status"], out.dim("·"))
            pr = d["targetLabel"] or "—"
            c = d.get("chain") or {}
            tag = (out.dim(f"chain {c['id'][:6]} {c['position']}/{c['of']}") if c else "")
            print(f"  {icon} {d['id'][:10]} {pr[:18]:18} {d['findings']:3} findings "
                  f"{out.dim(f'{d['undecided']} undecided'):24} {out.dim(d['startedAt'] or '')}"
                  f"{'  ' + tag if tag else ''}")
        open_runs = [d for d in data if d["status"] == "running"]
        if open_runs:
            print(f"\n  {out.warn('still open:')} "
                  f"{', '.join(d['id'][:10] for d in open_runs)}")
            print(out.dim("  A run stays open until someone closes it — nothing here can see "
                          "the terminal it runs in."))
            print(out.dim("  Close them: agency cleanup --unfinished"))
        print()

    return _emit(args, data, human)


# ---------------------------------------------------------------- backlog

def _backlog_ctx(args) -> tuple[config.Project, dict, "backlog.Board", runs.Run | None, dict | None]:
    """Everything a backlog command needs, resolved once.

    The run is optional on purpose. `agency backlog list` has to work before
    anything has been run, and a write made outside a run is still a legitimate
    write — it just signs without a run id and leaves no ledger entry.
    """
    project = _project(args)
    pack_name = getattr(args, "pack", None) or "po"
    cfg = _pack_cfg(project, pack_name)

    run = None
    if getattr(args, "run", None):
        run = runs.find_run(project, args.run)
        if run is None:
            raise SystemExit(f"Run “{args.run}” is not in this project.")
    else:
        # The run still in flight wins over the last finished one: a write made
        # while a session is open belongs to that session, and its ledger is
        # what the session will report on at the end.
        mine = [r for r in runs.load_runs(project)
                if str(r.record().get("pack", "")).split("@")[0] == pack_name]
        run = next((r for r in mine if r.record().get("status") == "running"),
                   mine[0] if mine else None)

    hire = (run.record().get("agent") if run else None) or None
    try:
        board = backlog.Board.of(project, cfg)
    except backlog.BacklogError as e:
        raise SystemExit(str(e))
    return project, cfg, board, run, hire


def _body_of(args, text_attr: str, file_attr: str, what: str) -> str:
    """Body from a flag or from a file.

    The file is not a convenience. A ticket body is markdown with newlines and
    quotes, and passing it through a Windows command line is how it arrives
    mangled — the agent writes it into the run directory and points at it.
    """
    path = getattr(args, file_attr, None)
    if path:
        p = Path(path)
        if not p.is_file():
            raise SystemExit(f"{what} file “{path}” does not exist.")
        return p.read_text(encoding="utf-8")
    text = getattr(args, text_attr, None)
    if not text:
        raise SystemExit(f"{what} is missing — pass --{text_attr.replace('_', '-')} "
                         f"or --{file_attr.replace('_', '-')}.")
    return text


def _backlog_emit(args, data: dict, headline: str) -> int:
    def human():
        icon = {"created": out.ok("+"), "promoted": out.ok("↑"),
                "commented": out.ok("»"), "exists": out.dim("="),
                "moved": out.ok("→"), "labelled": out.ok("#")}
        print(f"\n  {icon.get(data.get('action'), out.dim('·'))} {headline}")
        for key in ("url", "item", "number", "why", "boardError"):
            if data.get(key):
                print(f"    {out.dim(f'{key}: {data[key]}')}")
        for extra in ("status", "labels"):
            sub = data.get(extra)
            if isinstance(sub, dict) and sub.get("action") not in (None, "skipped"):
                what = sub.get("to") or ", ".join(sub.get("labels") or []) or ""
                print(f"    {out.dim(extra + ': ' + str(sub.get('action')) + ' ' + what)}")
        if data.get("dryRun"):
            print(f"    {out.warn('rehearsal — nothing was posted')}")
        print()

    return _emit(args, data, human)


def cmd_backlog(args) -> int:
    """The product queue: read it, write to it, and record what was written.

    An agent calls this the same way a human does — `agency triage` set that
    precedent and the reason is the same one. If posting a ticket were
    something the pack did by shelling out to `gh` itself, the signature, the
    idempotence marker and the write gate would live in a prompt, which is the
    one place none of them can be enforced.
    """
    needs_ref = {"promote", "comment", "decide"}
    if args.action in needs_ref and not args.ref:
        raise SystemExit(f"`agency backlog {args.action}` needs a ticket — an issue "
                         "number or a board item id.")
    if args.action in {"issue", "draft"} and not args.title:
        raise SystemExit(f"`agency backlog {args.action}` needs --title.")
    if args.action == "decide":
        if not args.decision:
            raise SystemExit("Decide what? `agency backlog decide <ref> "
                             + "|".join(backlog.DECISIONS) + ' --because "…"')
        if not (args.because or "").strip():
            # A decision with no reason is the thing this pack exists to stop
            # producing. It costs one sentence and it is the whole value.
            raise SystemExit("A decision needs --because. It is posted on the ticket, "
                             "and a cut nobody can read is how a backlog loses trust.")

    project, cfg, board, run, hire = _backlog_ctx(args)
    dry = bool(getattr(args, "dry_run", False)) or backlog.is_rehearsal(cfg)

    def refuse(message: str) -> int:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "reason": "write-gate", "message": message},
                             ensure_ascii=False, indent=2))
        else:
            print(f"\n  {out.warn('!')} {message}\n")
        return 1

    def gate(action: str) -> str | None:
        ok, why = backlog.allowed(cfg, action)
        return None if ok else why

    try:
        # ------------------------------------------------------------ list
        if args.action == "list":
            snap = backlog.snapshot(board, cfg, state=args.state)
            rows = snap["items"]
            if args.mine:
                rows = [r for r in rows if r.get("agencyKey")]

            def human():
                counts = f"{snap['issues']} issues · {snap['drafts']} drafts"
                print(f"\n  {out.bold(board.slug)}"
                      + (f"  {out.dim('board #' + str(board.project_number))}"
                         if board.has_project else "")
                      + f"  {out.dim(counts)}\n")
                if not rows:
                    print(f"  {out.dim('Nothing on the queue.')}\n")
                    return
                for r in rows:
                    tag = out.dim("draft") if r["kind"] == "draft" else out.ok(
                        f"#{r.get('number')}")
                    mine = out.dim(" · agency") if r.get("agencyKey") else ""
                    print(f"  {tag:16} {(r.get('title') or '')[:60]:62}"
                          f"{out.dim(','.join(r.get('labels') or []))}{mine}")
                print()

            return _emit(args, {"board": snap["board"], "items": rows,
                                "issues": snap["issues"], "drafts": snap["drafts"]}, human)

        # ---------------------------------------------------------- issue
        if args.action == "issue":
            if (why := gate("issue")):
                return refuse(why)
            body = _body_of(args, "body", "body_file", "The issue body")
            key = args.key or backlog.key_for(args.title)
            res = backlog.create_issue(board, cfg, args.title, body, key,
                                       labels=args.label, run=run, hire=hire,
                                       dry_run=dry)
            res["dryRun"] = dry
            backlog.append(run, {"kind": "issue", **res})
            return _backlog_emit(args, res, f"{res['action']}  {args.title}")

        # ---------------------------------------------------------- draft
        if args.action == "draft":
            if (why := gate("draft")):
                return refuse(why)
            body = _body_of(args, "body", "body_file", "The draft body")
            key = args.key or backlog.key_for(args.title)
            res = backlog.create_draft(board, cfg, args.title, body, key,
                                       run=run, hire=hire, dry_run=dry)
            res["dryRun"] = dry
            backlog.append(run, {"kind": "draft", **res})
            return _backlog_emit(args, res, f"{res['action']}  {args.title}")

        # -------------------------------------------------------- promote
        if args.action == "promote":
            if (why := gate("promote")):
                return refuse(why)
            ref = backlog.resolve_ref(board, args.ref)
            res = backlog.promote(board, cfg, ref, labels=args.label, dry_run=dry)
            res["dryRun"] = dry
            backlog.append(run, {"kind": "promote", **res})
            return _backlog_emit(args, res,
                                 f"{res['action']}  {ref.get('title') or args.ref}")

        # -------------------------------------------------------- comment
        if args.action == "comment":
            if (why := gate("comment")):
                return refuse(why)
            text = _body_of(args, "text", "text_file", "The comment")
            ref = backlog.resolve_ref(board, args.ref)
            key = args.key or backlog.key_for_text(text)
            res = backlog.comment(board, cfg, ref, text, key, run=run, hire=hire,
                                  dry_run=dry)
            res["dryRun"] = dry
            backlog.append(run, {"kind": "comment", "ref": args.ref, **res})
            return _backlog_emit(args, res,
                                 f"{res['action']}  {ref.get('title') or args.ref}")

        # --------------------------------------------------------- decide
        if args.action == "decide":
            ref = backlog.resolve_ref(board, args.ref)
            body = backlog.decision_body(cfg, args.decision, args.because,
                                         commitment=args.commitment, revisit=args.revisit)
            key = f"decision-{args.decision}-{backlog.key_for(ref.get('title') or args.ref)}"

            res: dict = {"action": "decided", "decision": args.decision,
                         "ref": args.ref, "number": ref.get("number"),
                         "item": ref.get("item"), "title": ref.get("title"),
                         "dryRun": dry}

            # The comment first: a decision that is not written down did not
            # happen, and a column moved without a reason is the thing that
            # makes people stop trusting a board.
            if (cfg.get("policy") or {}).get("cutIsAComment", True):
                if (why := gate("comment")):
                    return refuse(why)
                res["comment"] = backlog.comment(board, cfg, ref, body, key,
                                                 run=run, hire=hire, dry_run=dry)
                res["action"] = res["comment"].get("action", "decided")

            if not backlog.allowed(cfg, "status")[0]:
                res["status"] = {"action": "skipped", "why": "`writes.labels` is off"}
                res["labels"] = res["status"]
            else:
                res["status"] = backlog.set_status(board, cfg, ref, args.decision, dry_run=dry)
                res["labels"] = backlog.set_labels(board, cfg, ref, args.decision, dry_run=dry)

            backlog.append(run, {"kind": "decide", "key": key,
                                 "because": args.because,
                                 "commitment": args.commitment, **res})
            return _backlog_emit(args, res,
                                 f"{args.decision}  {ref.get('title') or args.ref}")

    except backlog.BacklogError as e:
        raise SystemExit(str(e))

    raise SystemExit(f"Unknown backlog action “{args.action}”.")


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    # Společné přepínače jako rodič, ne jen na kořeni — jinak by `--json` šlo
    # psát výhradně PŘED subpříkazem a `agency findings --json` by spadlo.
    # Konzumentem toho výstupu je extension a agent, takže na tom UX záleží.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="project root (default: the current git repo)")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(
        prog="agency",
        parents=[common],
        description="Specialists you hire into your repository. Attended, on your own "
                    "login, with evidence-backed findings that stay.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", parents=[common], help="detect the project and report what is known about it")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("packs", parents=[common], help="available specialists")
    s.set_defaults(fn=cmd_packs)

    # `hire` and `add` are one command under two names on purpose. Installing
    # the method and putting a worker on it is a single act the first time; the
    # second time it is only the hire, and the same flags have to work for both.
    for name, help_text in (
            ("hire", "hire a specialist — the same pack can be hired once per provider"),
            ("add", "install a pack into the project (alias of `hire`)")):
        s = sub.add_parser(name, parents=[common], help=help_text)
        s.add_argument("pack")
        s.add_argument("--provider",
                       help="which runner does the work — `agency providers` lists them. "
                            "Given explicitly it adds another worker to a pack that "
                            "already has one.")
        s.add_argument("--model", help="model for this worker (empty = the provider default)")
        s.add_argument("--as", dest="as_id",
                       help="id of the hire, e.g. reviewer-strict (default: <pack>@<provider>)")
        s.add_argument("--title", help="how this worker is named in the UI")
        s.add_argument("--from", dest="from_path", help="path to the pack (for development)")
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--force", action="store_true", help="overwrite hand-modified files too")
        s.set_defaults(fn=cmd_add)

    s = sub.add_parser("roster", parents=[common],
                       help="who is hired here — one row per worker, not per method")
    s.set_defaults(fn=cmd_roster)

    s = sub.add_parser("fire", parents=[common],
                       help="remove a hire; the pack, its configuration and past runs stay")
    s.add_argument("hire")
    s.set_defaults(fn=cmd_fire)

    s = sub.add_parser("providers", parents=[common],
                       help="AI runners available on this machine")
    s.add_argument("--add", metavar="ID", help="register a runner, e.g. grok")
    s.add_argument("--remove", metavar="ID")
    s.add_argument("--bin", help="the command to run (default: the id)")
    s.add_argument("--title", help="human-readable name")
    s.add_argument("--model-flag", default=None,
                   help="flag carrying the model, e.g. --model")
    s.add_argument("--dir-flag", default=None,
                   help="flag granting access to a directory outside the working copy; "
                        "without it the agent has to be told about the run directory itself")
    s.add_argument("--prompt-flag", default=None,
                   help="flag carrying the prompt (empty = passed positionally)")
    s.add_argument("--models", help="comma-separated list of models to offer")
    s.add_argument("--default-model", help="model used when the hire names none")
    s.set_defaults(fn=cmd_providers)

    s = sub.add_parser("doctor", parents=[common], help="check the prerequisites BEFORE a run starts")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("prs", parents=[common], help="pull requests to review — open and merged")
    s.add_argument("--state", choices=["open", "merged", "all"], default="all")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_prs)

    s = sub.add_parser("run", parents=[common],
                       help="prepare a pack run — over a pull request, or over the project as it is")
    s.add_argument("pack", metavar="who",
                   help="hire id from `agency roster`, or a pack name — a pack name "
                        "means its first worker")
    s.add_argument("--pr", type=int, help="PR number (default: the PR of the current branch)")
    s.add_argument("--latest-merged", action="store_true",
                   help="the last merged PR — retrospective audit")
    s.add_argument("--prompt", "-p",
                   help="what this run should focus on — free text, for packs that take a brief")
    s.add_argument("--scenario", help="a named brief from the pack configuration (brief.scenarios)")
    s.add_argument("--since", help="base ref for a run over the project (default: the default branch)")
    start = s.add_mutually_exclusive_group()
    start.add_argument("--launch", action="store_true",
                       help="start the agent right away and hand this terminal over to it")
    start.add_argument("--wait", action="store_true",
                       help="start the agent, wait for it, and run the gate when it ends")
    s.add_argument("--model", help="model for this run (overrides the hire and the configuration)")
    s.add_argument("--provider",
                   help="run this one on a different runner — `agency providers` lists them")
    s.add_argument("--force", action="store_true", help="a draft or an already reviewed commit too")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("chain", parents=[common],
                       help="run specialists one after another, each judging what the previous one found")
    s.add_argument("members", metavar="who", nargs="+",
                   help="two or more hire ids or pack names, in the order they should run")
    s.add_argument("--pr", type=int, help="PR number (default: the PR of the current branch)")
    s.add_argument("--latest-merged", action="store_true",
                   help="the last merged PR — retrospective audit")
    s.add_argument("--prompt", "-p",
                   help="what the chain should focus on — every member gets it")
    s.add_argument("--scenario", help="a named brief from the pack configuration (brief.scenarios)")
    s.add_argument("--since", help="base ref for a run over the project (default: the default branch)")
    s.add_argument("--model", help="model for every step (overrides the hire and the configuration)")
    s.add_argument("--provider", help="runner for every step — a chain runs on one provider")
    s.add_argument("--force", action="store_true", help="a draft or an already reviewed commit too")
    s.set_defaults(fn=cmd_chain)

    s = sub.add_parser("validate", parents=[common], help="check findings.json against the contract and the anchors against the code")
    s.add_argument("--run", help="run id (default: the latest)")
    s.set_defaults(fn=cmd_validate)

    # Jedny dveře ke grafu. `--repo` míří na worktree běhu, když se agent ptá
    # odtamtud — index je tam zkopírovaný a doindexovaný přípravou.
    s = sub.add_parser("graph", parents=[common],
                       help="ask the code graph — one door for the core and the agent, JSON out")
    gsub = s.add_subparsers(dest="verb", required=True)
    gsub.add_parser("state", parents=[common], help="is there an index, how fresh is it")
    gsub.add_parser("refresh", parents=[common], help="bring the index up to date for this run")
    gsub.add_parser("capabilities", parents=[common], help="which verbs this driver answers")
    g = gsub.add_parser("changes", parents=[common], help="what changed against a base")
    g.add_argument("--base", required=True)
    g = gsub.add_parser("impact", parents=[common], help="blast radius of these files")
    g.add_argument("--files", nargs="+", required=True)
    g.add_argument("--depth", type=int, default=2)
    g = gsub.add_parser("locate", parents=[common], help="symbol → file:line")
    g.add_argument("symbol")
    g.add_argument("--kind", choices=["File", "Class", "Function", "Type", "Test"])
    g = gsub.add_parser("neighbors", parents=[common], help="who calls it (in), what it calls (out)")
    g.add_argument("symbol")
    g.add_argument("--direction", choices=["in", "out"], default="in")
    g = gsub.add_parser("unreferenced", parents=[common], help="code nothing points at — the `reuse` dimension")
    g.add_argument("--path", help="path substring to narrow it down")
    g = gsub.add_parser("tests-for", parents=[common], help="tests that touch this symbol — the `tests` dimension")
    g.add_argument("symbol")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("ingest", parents=[common],
                       help="the gate: contract, existence, threshold, dedup — BEFORE a finding becomes a finding")
    s.add_argument("--run", help="run id (default: the latest)")
    s.add_argument("--min-score", type=int, help="overrides review.minScore from the configuration")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("knowledge", parents=[common],
                       help="what the project knows, as committed markdown — readable without Agency")
    s.add_argument("--rebuild", action="store_true",
                   help="rewrite .agency/knowledge/ from the runs (it is derived, always safe)")
    s.set_defaults(fn=cmd_knowledge)

    s = sub.add_parser("metrics", parents=[common],
                       help="precision, dedup, queue age — by dimension, severity, "
                            "specialist and model")
    s.add_argument("--all-projects", action="store_true", help="across the project registry")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("export", parents=[common], help="one-way push into a GitHub Project")
    s.add_argument("target", choices=["github"])
    s.add_argument("--pack", default="review-graph")
    s.add_argument("--run", help="a single run only (default: all)")
    s.add_argument("--project", dest="project_number", type=int,
                   help="Project number (default: sinks.githubProject)")
    s.add_argument("--owner", help="Project owner (default: from the git remote)")
    s.add_argument("--include-undecided", action="store_true",
                   help="undecided findings too")
    s.add_argument("--dry-run", action="store_true", help="only show what would be sent")
    s.set_defaults(fn=cmd_export)

    # The product queue. Every write is signed, marked and gated by `writes.*`
    # in the pack configuration — which is why the pack calls this instead of
    # calling `gh` itself. An agent is a first-class client here, exactly as it
    # is for `agency triage`.
    s = sub.add_parser("backlog", parents=[common],
                       help="the product queue — issues and board drafts, written signed "
                            "and only once")
    s.add_argument("action", choices=["list", "issue", "draft", "promote", "comment", "decide"])
    s.add_argument("ref", nargs="?",
                   help="issue number, issue URL or a board item id (PVTI_…) — for "
                        "promote, comment and decide")
    s.add_argument("decision", nargs="?", choices=list(backlog.DECISIONS),
                   help="for `decide`: now, next or not-now")
    s.add_argument("--pack", default="po", help="whose configuration decides (default: po)")
    s.add_argument("--run", help="run the write belongs to (default: the latest run of that pack)")
    s.add_argument("--title", help="title of the issue or draft")
    s.add_argument("--body", help="body — markdown")
    s.add_argument("--body-file", help="file holding the body; use this for anything "
                                       "with newlines")
    s.add_argument("--text", help="comment text")
    s.add_argument("--text-file", help="file holding the comment text")
    s.add_argument("--because", help="for `decide`: why. It is posted on the ticket.")
    s.add_argument("--commitment",
                   help="for `decide`: the roadmap line this was measured against")
    s.add_argument("--revisit", help="for `decide`: when it will be looked at again")
    s.add_argument("--label", action="append", help="issue label (repeatable)")
    s.add_argument("--key", help="idempotence key (default: derived from the title) — "
                                "the same key is never written twice")
    s.add_argument("--mine", action="store_true",
                   help="for `list`: only what this pack has written")
    s.add_argument("--state", choices=["open", "closed", "all"], default="open")
    s.add_argument("--dry-run", action="store_true",
                   help="rehearse it: show exactly what would be posted, post nothing")
    s.set_defaults(fn=cmd_backlog)

    s = sub.add_parser("projects", parents=[common], help="projects where Agency is doing something")
    s.set_defaults(fn=cmd_projects)

    s = sub.add_parser("cleanup", parents=[common],
                       help="close a run that is not coming back and remove its worktree")
    s.add_argument("--run")
    s.add_argument("--unfinished", action="store_true",
                   help="every run still marked as running — what a closed terminal leaves behind")
    s.add_argument("--discard", action="store_true",
                   help="delete the run outright, record and evidence included; "
                        "refused when it carries decisions")
    s.add_argument("--force", action="store_true",
                   help="discard even a run that carries decisions")
    s.set_defaults(fn=cmd_cleanup)

    s = sub.add_parser("findings", parents=[common], help="findings and their decisions")
    s.add_argument("--run")
    s.add_argument("--all", action="store_true", help="across all runs")
    s.set_defaults(fn=cmd_findings)

    s = sub.add_parser("triage", parents=[common], help="decide on a finding — an agent calls this too")
    s.add_argument("action", choices=["accept", "reject", "defer"])
    s.add_argument("finding")
    s.add_argument("--reason", choices=list(runs.REJECT_REASONS))
    s.add_argument("--note")
    s.add_argument("--by", default=runs.HUMAN,
                   help="who decides — `hire:<id>` for a specialist (ready-made in context.json), `human` for a person")
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("config", parents=[common],
                       help="pack configuration — show it, or change it with --set")
    s.add_argument("pack")
    s.add_argument("--set", dest="set_pairs", action="append", metavar="KEY=VALUE",
                   help="dotted path, JSON value (repeatable): --set playwright.enabled=true")
    s.add_argument("--unset", action="append", metavar="KEY", help="remove a key")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("brief", parents=[common],
                       help="the standing brief of a pack and its named scenarios — show or set")
    s.add_argument("pack")
    s.add_argument("--set", dest="set_text",
                   help="new text; without --scenario it becomes the standing brief")
    s.add_argument("--scenario", help="name of the scenario the text belongs to")
    s.add_argument("--remove", action="store_true", help="remove the scenario given by --scenario")
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("note", parents=[common], help="a note on a finding — free text, not a decision")
    s.add_argument("finding")
    s.add_argument("text")
    s.add_argument("--by", default=runs.HUMAN,
                   help="who decides — `hire:<id>` for a specialist (ready-made in context.json), `human` for a person")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("status", parents=[common], help="overview of the project runs")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_status)

    return p


def _force_utf8() -> None:
    """Windows konzole i roura jedou default v cp1250 a `→`, `✓` nebo diakritika
    z nich vylezou jako UnicodeEncodeError. `reconfigure` na to nestačí, když je
    stream už navázaný — spolehlivé je obalit rovnou binární buffer."""
    import io as _io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or getattr(stream, "encoding", "").lower().startswith("utf"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            if stream.encoding.lower().startswith("utf"):
                continue
        except Exception:
            pass
        try:
            setattr(sys, name, _io.TextIOWrapper(
                stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n  interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
