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

from . import anchor, config, packs, proc, runs
from .util import bundled, out, posix, read_json, ulid, write_json

# ---------------------------------------------------------------- pomůcky


def _emit(args, data, human) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        human()
    return 0


def _project(args) -> config.Project:
    return config.require(getattr(args, "repo", None))


def _pack_cfg(project: config.Project, pack_name: str) -> dict:
    cfg = project.pack_config(pack_name)
    if cfg is None:
        raise SystemExit(
            f"Pack „{pack_name}“ tady není nainstalovaný. Spusť `agency add {pack_name}`."
        )
    return cfg


# ---------------------------------------------------------------- init

def cmd_init(args) -> int:
    project = _project(args)
    facts = config.detect(project)
    facts["root"] = posix(project.root)

    def human():
        print(f"\n{out.bold(project.name)}  {out.dim(posix(project.root))}\n")
        rows = [
            ("git remote", facts["slug"] or out.warn("chybí — pack bude potřebovat repo.slug ručně")),
            ("výchozí větev", facts["defaultBranch"] or out.warn("nezjištěna")),
            ("graf kódu", out.ok("postavený") if facts["hasGraph"]
             else out.warn("chybí — první běh ho postaví (`code-review-graph build`)")),
            ("CI příkaz", facts["verifyCommand"] or out.dim("žádný — nálezy, které chytá CI, se nebudou zahazovat")),
            ("pravidla projektu", facts["rules"] or out.dim("nenalezena — poběží 4 z 5 dimenzí")),
            ("mapa dokumentace", facts["docMap"] or out.dim("nenalezena")),
            ("existující skills", ", ".join(facts["existingSkills"]) or out.dim("žádné")),
        ]
        for k, v in rows:
            print(f"  {k:20} {v}")
        print(f"\n  Dál: {out.bold('agency add review-graph')}\n")

    return _emit(args, facts, human)


# ---------------------------------------------------------------- packs

def cmd_packs(args) -> int:
    project = config.discover(getattr(args, "repo", None))
    data = []
    for p in packs.available():
        entry = {"name": p.name, "version": p.version, "title": p.manifest.get("title"),
                 "description": p.manifest.get("description"),
                 "installed": packs.installed_ref(project, p.name) if project else None}
        data.append(entry)

    def human():
        print()
        for e in data:
            mark = out.ok("nainstalován " + e["installed"]) if e["installed"] else out.dim("neinstalován")
            print(f"  {out.bold(e['name']):28} {e['version']:8} {mark}")
            print(f"  {'':28} {out.dim(e['description'] or '')}")
        print()

    return _emit(args, data, human)


def cmd_add(args) -> int:
    project = _project(args)
    pack = packs.load(args.pack, args.from_path)
    steps = packs.plan(pack, project)
    blocked = [s for s in steps if s["action"] == "blocked"]

    if not args.dry_run and not blocked:
        packs.apply(pack, project, steps, detected=config.detect(project))

    data = {"pack": pack.ref, "dryRun": args.dry_run,
            "steps": [{k: v for k, v in s.items() if k != "src"} for s in steps]}

    def human():
        print(f"\n  {out.bold(pack.ref)} → {project.name}\n")
        icon = {"create": out.ok("+"), "update": out.ok("~"), "keep": out.dim("="),
                "blocked": out.err("!")}
        for s in steps:
            print(f"  {icon[s['action']]} {s['to']:52} {out.dim(s['why'])}")
        if blocked:
            print(f"\n  {out.err('Instalace zastavena.')} Soubory výše byly ručně změněny.")
            print(out.dim("  Ruční úprava packu obvykle znamená, že v konfiguraci chybí pole —"))
            print(out.dim("  doplň ho do .agency/, ne do metody. Přepsat i tak: --force."))
        elif args.dry_run:
            print(f"\n  {out.dim('Zkušební běh, nic se nezapsalo.')}")
        else:
            print(f"\n  Dál: {out.bold('agency doctor')}")
        print()

    _emit(args, data, human)
    return 1 if blocked and not args.force else 0


# ---------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    project = _project(args)
    checks = []

    def check(name, ok, detail, fatal=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})

    check("git", proc.which("git"), proc.which("git") or "není v PATH")
    v = proc.crg_version()
    check("code-review-graph", v, v or "není v PATH — `uv tool install code-review-graph`")
    login = proc.gh_login()
    check("gh auth", login, f"přihlášen jako {login}" if login else "nepřihlášen — `gh auth login`")
    check("repo slug", project.slug, project.slug or "origin remote chybí")

    graph = proc.crg_status(project.root)
    check("graf kódu", graph["exists"],
          f"{graph.get('sizeBytes', 0) // 1_000_000} MB" if graph["exists"]
          else "chybí — postav `code-review-graph build`", fatal=False)

    for p in packs.available():
        ref = packs.installed_ref(project, p.name)
        if not ref:
            continue
        cfg = project.pack_config(p.name) or {}
        missing = [k for k in (p.manifest.get("config", {}).get("required") or [])
                   if not _dig(cfg, k)]
        check(f"pack {p.name}", not missing,
              f"{ref}, konfigurace úplná" if not missing
              else f"chybí povinné: {', '.join(missing)}")
        if ref != p.ref:
            check(f"pack {p.name} verze", False,
                  f"nainstalováno {ref}, dostupné {p.ref} — `agency add {p.name}`", fatal=False)

    fatal = [c for c in checks if not c["ok"] and c["fatal"]]

    def human():
        print(f"\n  {out.bold(project.name)}\n")
        for c in checks:
            icon = out.ok("✓") if c["ok"] else (out.err("✗") if c["fatal"] else out.warn("!"))
            print(f"  {icon} {c['name']:24} {out.dim(c['detail'])}")
        print()
        if fatal:
            print(f"  {out.err('Běh by selhal.')} Oprav položky s ✗.\n")
        else:
            print(f"  {out.ok('Připraveno.')}  {out.dim('agency run review-graph --pr <n>')}\n")

    _emit(args, {"checks": checks, "ok": not fatal}, human)
    return 1 if fatal else 0


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
            print("\n  " + out.dim("Žádné PR.") + "\n")
            return
        print()
        for r in rows:
            tag = out.dim("mergnutý") if r["state"] == "merged" else out.ok("otevřený")
            mark = out.dim(" · už recenzovaný") if r["reviewed"] else ""
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

def cmd_run(args) -> int:
    project = _project(args)
    cfg = _pack_cfg(project, args.pack)
    pack = packs.load(args.pack)

    # V --json režimu se průběh potlačí, jinak by se mísil s výstupem
    # a extension by ho neuparsovala.
    out.quiet = bool(getattr(args, "json", False))

    out.say(f"\n  {out.bold(pack.ref)} → {project.name}\n")

    out.step("hledám PR")
    target = runs.resolve_target(project, args.pr, args.latest_merged)
    kind = "mergnutý (retrospektivní audit)" if target["kind"] == "merged-pull-request" else "otevřený"
    out.done(f"PR #{target['pr']} — {target['title'][:58]}  {out.dim(kind)}")

    def refuse(reason: str, code: str) -> int:
        out.note(reason)
        if out.quiet:
            print(json.dumps({"ok": False, "reason": code, "message": reason},
                             ensure_ascii=False, indent=2))
        return 1

    if target["_isDraft"] and not args.force:
        return refuse("PR je draft. Pokračuj s --force, jestli to je záměr.", "draft")
    if runs.already_reviewed(target, proc.gh_login()) and not args.force:
        return refuse(
            f"Commit {target['headRefOid'][:8]} už recenzovaný — marker je na PR. Znovu: --force.",
            "already-reviewed")

    skip = (cfg.get("review") or {}).get("skipPatterns") or []
    all_files = target.pop("_files", [])
    files = [f for f in all_files if not runs._skip(f, skip)]
    skipped = len(all_files) - len(files)
    out.done(f"{len(files)} souborů k recenzi  {out.dim(f'({skipped} odfiltrováno)')}")
    if not files:
        return refuse("Po odfiltrování nezbyl žádný soubor — není co recenzovat.", "no-files")

    run = runs.start(project, pack.ref, cfg, target)
    out.step(f"běh {run.id}")

    wt = None
    try:
        out.step("stavím jednorázový worktree")
        wt = runs.make_worktree(project, cfg, target)
        out.done(posix(wt))

        out.step("kopíruji metodu packu do worktree")
        carried = runs.materialize_pack(project, pack, wt)
        out.done(f"{len(carried)} souborů" if carried
                 else "pack v projektu nic neinstaluje")

        out.step("aktualizuji graf")
        ginfo = runs.prepare_graph(project, wt, cfg)
        out.done(f"graf: {ginfo['action']}" + (f"  {out.dim(ginfo['tool'] or '')}" if ginfo.get("tool") else ""))

        out.step("sbírám grafový signál")
        stats = runs.collect_evidence(wt, run, target, files)
        out.done("evidence/ naplněno" + (f"  {out.dim(str(stats))}" if stats else ""))

        runs.write_context(run, cfg, target, wt, files, skipped)

        rec = run.record()
        rec["graph"] = {**ginfo, **stats}
        rec["target"]["filesReviewed"] = len(files)
        rec["target"]["filesSkipped"] = skipped
        run.save_record(rec)

    except Exception:
        if wt:
            runs.remove_worktree(project, wt)
        rec = run.record()
        rec.update(status="failed", finishedAt=runs.now())
        run.save_record(rec)
        raise

    # Skill se ve worktree najde jen díky materialize_pack výše. Kdyby pack
    # do projektu nic neinstaloval, odkaž na metodu cestou — jinak by běh
    # skončil na Unknown skill a uživatel by neměl kam sáhnout.
    how = ("Použij skill agency-review-graph."
           if any(str(c).endswith("SKILL.md") for c in carried)
           else f"Přečti si metodu v {posix(project.root)}/.claude/skills/agency-review-graph/SKILL.md.")
    prompt = (
        f"{how} RUN_DIR={posix(run.dir)} — začni jeho context.json. "
        f"Povinný výstup je RUN_DIR/findings.json podle finding.v1."
    )
    launch, agent_info = runs.launch_argv(
        cfg, posix(run.dir), prompt,
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
            "prompt": prompt,
            # Hotový příkaz — tvar spuštění vlastní CLI, ne klient.
            "launch": launch,
            "agent": agent_info,
            "target": {k: v for k, v in target.items() if not k.startswith("_")},
            "files": len(files),
            "filesSkipped": skipped,
            "graph": {**ginfo, **stats},
        }, ensure_ascii=False, indent=2))
        return 0

    out.say()
    out.done("příprava hotová — deterministická část skončila")
    out.say()
    out.say(f"  {out.dim('Worktree zůstává, dokud běh nedokončíš:')}")
    out.say(f"  {out.dim(posix(wt))}")
    out.say()

    if args.launch:
        os.chdir(wt)
        out.say(f"  {out.bold('spouštím claude…')}\n")
        os.execvp(launch[0], launch)

    print(f"  {out.bold('Spusť recenzi:')}")
    print(f"    cd {posix(wt)}")
    print("    " + " ".join(
        json.dumps(a, ensure_ascii=False) if " " in a else a for a in launch))
    print()
    print(f"  {out.dim('Až doběhne:')}  agency validate --run {run.id[:8]}")
    print(f"  {out.dim('Úklid:')}        agency cleanup --run {run.id[:8]}")
    print()
    return 0


def cmd_cleanup(args) -> int:
    project = _project(args)
    run = runs.find_run(project, args.run)
    if not run:
        raise SystemExit("Žádný běh nenalezen.")
    cfg = _pack_cfg(project, run.record().get("pack", "review-graph").split("@")[0])
    ctx = read_json(run.dir / "context.json", default={})
    wt = ctx.get("worktree")
    if wt and Path(wt).exists():
        runs.remove_worktree(project, Path(wt))
        out.done(f"worktree odstraněn: {wt}")
    else:
        out.note("worktree už neexistuje")
    return 0


# ---------------------------------------------------------------- validate

def cmd_validate(args) -> int:
    project = _project(args)
    run = runs.find_run(project, args.run)
    if not run:
        raise SystemExit("Žádný běh nenalezen.")

    findings = run.findings()
    errors: list[dict] = []
    try:
        import jsonschema
        schema = read_json(bundled("schemas", "finding.v1.json"))
        v = jsonschema.Draft202012Validator(schema)
        for i, f in enumerate(findings):
            for e in v.iter_errors(f):
                errors.append({"index": i, "id": f.get("id"),
                               "path": "/".join(str(p) for p in e.path), "message": e.message})
    except ImportError:
        out.note("jsonschema není nainstalované, kontroluji jen povinná pole")
        for i, f in enumerate(findings):
            for key in ("id", "runId", "pack", "severity", "title", "body", "anchor", "evidence"):
                if key not in f:
                    errors.append({"index": i, "id": f.get("id"), "path": key, "message": "chybí"})

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

    rec = run.record()
    rec["counts"] = {**(rec.get("counts") or {}), "kept": len(findings)}
    rec["status"] = "ok" if findings and not errors else ("no-findings" if not findings else "failed")
    rec.setdefault("finishedAt", runs.now())
    run.save_record(rec)

    data = {"run": run.id, "findings": len(findings), "errors": errors, "anchors": resolved}

    def human():
        print(f"\n  běh {out.bold(run.id)}  ·  {len(findings)} nálezů\n")
        if errors:
            print(f"  {out.err('Kontrakt nesedí:')}")
            for e in errors[:20]:
                print(f"    #{e['index']} {e['path']}: {e['message'][:90]}")
            print()
        for r in resolved:
            icon = out.ok("✓") if r["resolvedLine"] else out.warn("?")
            loc = f"{r['file']}:{r['resolvedLine'] or r['line']}"
            print(f"  {icon} {loc:56} {out.dim(r['via'])} {out.dim(r['note'])}")
        print()
        if not errors:
            print(f"  {out.ok('Nálezy odpovídají finding.v1.')}\n")

    _emit(args, data, human)
    return 1 if errors else 0


# ---------------------------------------------------------------- findings

def cmd_findings(args) -> int:
    project = _project(args)
    selected = runs.load_runs(project) if args.all else (
        [r] if (r := runs.find_run(project, args.run)) else [])

    rows = []
    for run in selected:
        dec = runs.decisions(run)
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
                "by": d.get("by") if d else None,
            }
            # Kotva a drift jen do --json: konzumentem je extension, která bez
            # nich neumí ani proklik, ani pohled na kód v den analýzy.
            if getattr(args, "json", False):
                row["anchor"] = a
                row["evidence"] = f.get("evidence") or []
                row["target"] = rec.get("target") or {}
                if a.get("file"):
                    row["drift"] = anchor.drift(project.root, a)
                    r = anchor.resolve(project.root, a)
                    row["resolved"] = {"line": r.line, "via": r.via, "note": r.note}
            rows.append(row)

    def human():
        if not rows:
            print(f"\n  {out.dim('Žádné nálezy. Spusť `agency run review-graph --pr <n>`.')}\n")
            return
        undecided = sum(1 for r in rows if not r["decision"])
        print(f"\n  {len(rows)} nálezů, {undecided} bez rozhodnutí\n")
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


def cmd_triage(args) -> int:
    project = _project(args)
    run = None
    for r in runs.load_runs(project):
        if any(f.get("id") == args.finding for f in r.findings()):
            run = r
            break
    if run is None:
        raise SystemExit(f"Nález „{args.finding}“ jsem v žádném běhu nenašel.")

    state = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}[args.action]
    ev = runs.append_decision(run, args.finding, state, args.reason, args.note, args.by)

    def human():
        print(f"  {args.finding} → {ev['state']}"
              + (f" · {ev['reason']}" if ev["reason"] else "")
              + (f" · {ev['note']}" if ev["note"] else ""))

    return _emit(args, ev, human)


def cmd_status(args) -> int:
    project = _project(args)
    all_runs = runs.load_runs(project)
    data = []
    for run in all_runs[:args.limit]:
        rec = run.record()
        dec = runs.decisions(run)
        fs = run.findings()
        data.append({
            "id": run.id, "pack": rec.get("pack"), "status": rec.get("status"),
            "startedAt": rec.get("startedAt"),
            "target": (rec.get("target") or {}).get("pr"),
            "kind": (rec.get("target") or {}).get("kind"),
            "findings": len(fs), "undecided": sum(1 for f in fs if f.get("id") not in dec),
        })

    def human():
        print(f"\n  {out.bold(project.name)}  {out.dim(posix(project.root))}")
        installed = [f"{n} {v.get('ref')}" for n, v in (project.installed().get("packs") or {}).items()]
        print(f"  {out.dim('packy:')} {', '.join(installed) or out.dim('žádné')}\n")
        if not data:
            print(f"  {out.dim('Zatím žádné běhy.')}\n")
            return
        for d in data:
            icon = {"ok": out.ok("✓"), "no-findings": out.ok("○"), "running": out.warn("…"),
                    "failed": out.err("✗")}.get(d["status"], out.dim("·"))
            pr = f"PR #{d['target']}" if d["target"] else "—"
            print(f"  {icon} {d['id'][:10]} {pr:9} {d['findings']:3} nálezů "
                  f"{out.dim(f'{d['undecided']} nerozhodnuto'):24} {out.dim(d['startedAt'] or '')}")
        print()

    return _emit(args, data, human)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    # Společné přepínače jako rodič, ne jen na kořeni — jinak by `--json` šlo
    # psát výhradně PŘED subpříkazem a `agency findings --json` by spadlo.
    # Konzumentem toho výstupu je extension a agent, takže na tom UX záleží.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="kořen projektu (výchozí: aktuální git repo)")
    common.add_argument("--json", action="store_true", help="strojově čitelný výstup")

    p = argparse.ArgumentParser(
        prog="agency",
        parents=[common],
        description="Specialisté, které si najmeš do repozitáře. Attended, na tvém "
                    "přihlášení, s doloženými nálezy, které zůstanou.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", parents=[common], help="rozpozná projekt a řekne, co o něm ví")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("packs", parents=[common], help="dostupní specialisté")
    s.set_defaults(fn=cmd_packs)

    s = sub.add_parser("add", parents=[common], help="nainstaluje packa do projektu")
    s.add_argument("pack")
    s.add_argument("--from", dest="from_path", help="cesta k packu (pro vývoj)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="přepsat i ručně změněné soubory")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("doctor", parents=[common], help="ověří předpoklady DŘÍV, než začne běh")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("prs", parents=[common], help="PR k recenzi — otevřené i prošlé")
    s.add_argument("--state", choices=["open", "merged", "all"], default="all")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_prs)

    s = sub.add_parser("run", parents=[common], help="připraví běh packu nad PR")
    s.add_argument("pack")
    s.add_argument("--pr", type=int, help="číslo PR (výchozí: PR aktuální větve)")
    s.add_argument("--latest-merged", action="store_true",
                   help="poslední mergnutý PR — retrospektivní audit")
    s.add_argument("--launch", action="store_true", help="rovnou spustit agenta")
    s.add_argument("--model", help="model pro tenhle běh (přebije agent.model z konfigurace)")
    s.add_argument("--provider", help="claude | codex (přebije agent.provider)")
    s.add_argument("--force", action="store_true", help="i draft nebo už recenzovaný commit")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("validate", parents=[common], help="ověří findings.json proti kontraktu a kotvy proti kódu")
    s.add_argument("--run", help="id běhu (výchozí: poslední)")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("cleanup", parents=[common], help="odstraní worktree běhu")
    s.add_argument("--run")
    s.set_defaults(fn=cmd_cleanup)

    s = sub.add_parser("findings", parents=[common], help="nálezy a jejich rozhodnutí")
    s.add_argument("--run")
    s.add_argument("--all", action="store_true", help="napříč všemi běhy")
    s.set_defaults(fn=cmd_findings)

    s = sub.add_parser("triage", parents=[common], help="rozhodnutí o nálezu — volá i agent")
    s.add_argument("action", choices=["accept", "reject", "defer"])
    s.add_argument("finding")
    s.add_argument("--reason", choices=list(runs.REJECT_REASONS))
    s.add_argument("--note")
    s.add_argument("--by", default="cli")
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("status", parents=[common], help="přehled běhů projektu")
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
        print("\n  přerušeno")
        return 130


if __name__ == "__main__":
    sys.exit(main())
