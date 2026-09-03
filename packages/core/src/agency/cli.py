"""`agency` — the command line.

Every command understands `--json`, because its second user is the VS Code
extension and its third is an agent. If only a human could read the output,
those two would be second-class.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import anchor, chain as chains, config, export, graph, ingest, knowledge, metrics, packs, proc, providers, runs
from .util import bundled, out, posix, read_json, ulid

# ---------------------------------------------------------------- helpers


def _emit(args, data, human) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        human()
    return 0


def _project(args) -> config.Project:
    return config.require(getattr(args, "repo", None))


# ---------------------------------------------------------------- packs

def cmd_packs(args) -> int:
    project = _project(args)
    data = []
    for p in packs.available(project):
        data.append({
            "name": p.name, "title": p.title,
            "description": p.manifest.get("description"),
            "skill": p.skill_name,
            "dimensions": p.dimensions,
            "requires": p.requires,
            "run": p.run_policy,
            "minScore": p.min_score,
        })

    def human():
        print()
        for e in data:
            print(f"  {out.bold(e['name']):28} {out.dim(e['skill'])}")
            print(f"  {'':28} {out.dim(e['description'] or '')}")
        print()

    return _emit(args, data, human)


# ---------------------------------------------------------------- doctor

def _run_hint(pack) -> str:
    """How this pack is launched. Read from the manifest, never from its name."""
    policy = pack.run_policy
    if policy["target"] == "pull-request":
        return " --pr <n>"
    return ' --prompt "…"' if policy["prompt"] == "required" else ""


def cmd_doctor(args) -> int:
    project = _project(args)
    checks = []

    def check(name, ok, detail, fatal=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fatal": fatal})

    hired = packs.available(project)
    wanted: set[str] = set()
    for p in hired:
        wanted |= set(p.requires)

    def needed(tool: str) -> bool:
        return not hired or tool in wanted

    def tool_check(name: str, tool: str, value, missing: str) -> None:
        if value:
            check(name, True, value, fatal=needed(tool))
        elif needed(tool):
            check(name, False, missing)
        else:
            check(name, True, "not needed by the specialists in this project", fatal=False)

    check("git", proc.which("git"), proc.which("git") or "not on PATH")

    # Every hired pack can be launched on either provider (`--provider`), so
    # both are worth showing — but only `claude` is fatal, since it is the
    # default a bare `agency run` falls back to.
    for i, name in enumerate(("claude", "codex")):
        where = providers.installed(name)
        check(f"provider {name}", where, where or "not on PATH", fatal=(i == 0 and bool(hired)))

    tool_check("code-review-graph", "code-review-graph", proc.crg_version(),
               "not on PATH — `uv tool install code-review-graph`")
    login = proc.gh_login()
    tool_check("gh auth", "gh", f"signed in as {login}" if login else None,
               "not signed in — `gh auth login`")
    check("repo slug", project.slug or not hired,
          project.slug or "no remote — the specialists in this project do not need one",
          fatal=bool(hired))

    if needed("code-review-graph"):
        g = graph.state(project.root).data
        check("code graph", g["exists"],
              f"{g.get('sizeBytes', 0) // 1_000_000} MB"
              + (f" · {g['nodes']} nodes, {g['files']} files"
                 if g.get("nodes") is not None else "")
              + ("  built on another commit — `code-review-graph update`"
                 if g.get("stale") else "")
              if g["exists"]
              else "missing — build it with `code-review-graph build`", fatal=False)

    pg = knowledge.pages_summary(project)
    if pg["total"]:
        detail = " · ".join(f"{pack} {n}" for pack, n in pg["byPack"].items())
        if pg["stale"]:
            detail += f" · {pg['stale']} stale"
        check("pack pages", True, detail, fatal=False)

    for p in hired:
        # What a pack wants from the graph vs what the driver can answer. Asked
        # up front, because a missing capability is not a bug — it is a
        # dimension that runs without the graph signal, and a silent gap
        # mid-run is worse than this sentence at the start.
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
            hints = [f"agency run {p.name}{_run_hint(p)}" for p in hired] or ["agency packs"]
            print(f"  {out.ok('Ready.')}  " +
                  f"  {out.dim('·')}  ".join(out.dim(h) for h in hints) + "\n")

    _emit(args, {"checks": checks, "ok": not fatal}, human)
    return 1 if fatal else 0


# ---------------------------------------------------------------- prs

def cmd_prs(args) -> int:
    """The list of PRs to review. Exists for the extension: picking a PR
    should be a click, not copying a number. Merged ones are in the list on
    purpose — a retrospective audit is a full mode, not an exception."""
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
    """Was this exact commit already reviewed? The key is (repo, PR, headRefOid)."""
    if not head:
        return False
    for run in runs.load_runs(project):
        if ((run.record().get("target") or {}).get("headRefOid")) == head:
            return True
    return False


# ---------------------------------------------------------------- run

def _one_line(text: str, limit: int = 400) -> str:
    """A prompt going into the launch command. A multi-line one would be cut
    up by the terminal."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def cmd_run(args, chain: dict | None = None) -> int:
    if getattr(args, "wait", False) and getattr(args, "json", False):
        raise SystemExit(
            "--wait and --json do not go together: the agent writes to this same "
            "stdout, so nothing could promise the output is a single JSON document. "
            "Prepare the run with --json and close it with `agency ingest`.")
    # A run is a leaf. An agent that starts its own run produces one nobody
    # owns — no terminal, no authorization, and a record that lies about both.
    runs.refuse_nested("agency run")
    project = _project(args)
    pack = packs.load(args.pack, project)
    policy = pack.run_policy
    provider = getattr(args, "provider", None) or "claude"

    # In --json mode progress output is suppressed, or it would mix with the
    # output and the extension would fail to parse it.
    out.quiet = bool(getattr(args, "json", False))

    def refuse(reason: str, code: str) -> int:
        out.note(reason)
        if out.quiet:
            print(json.dumps({"ok": False, "reason": code, "message": reason},
                             ensure_ascii=False, indent=2))
        return 1

    out.say(f"\n  {out.bold(pack.title)}  {out.dim(pack.name + '@' + provider)} → {project.name}\n")

    prompt_text = (getattr(args, "prompt", None) or "").strip() or None
    if prompt_text and policy["prompt"] == "none":
        raise SystemExit(
            f"Pack “{pack.name}” does not take a prompt — --prompt has nothing to do here.")
    if policy["prompt"] == "required" and not prompt_text:
        return refuse(
            f"{pack.title} needs to know what to work on. Pass --prompt \"…\".",
            "no-prompt")

    shared_target = (chain or {}).get("target")
    if shared_target is not None:
        # The chain resolved the target once, before its first step, and every
        # member gets that same one — otherwise a workspace pack in the same
        # chain quietly resolves its own target from whatever branch happens
        # to be checked out.
        target = dict(shared_target)
        if target["kind"] == "workspace":
            out.done(f"{target['ref']} @ {target['headRefOid'][:8]}  "
                     f"{out.dim('the chain’s target')}")
        else:
            out.done(f"PR #{target['pr']} — {(target.get('title') or '')[:58]}  "
                     f"{out.dim('the chain’s target')}")
    elif policy["target"] == "workspace":
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
        if runs.already_reviewed(target, pack.name, provider) and not args.force:
            return refuse(
                f"Commit {target['headRefOid'][:8]} has already been reviewed by "
                f"{pack.name}@{provider} — the marker is on the PR. "
                "Another provider may still review it. Again: --force.",
                "already-reviewed")

    all_files = target.pop("_files", [])
    files = [f for f in all_files if not runs._skip(f, runs.SKIP_PATTERNS)]
    skipped = len(all_files) - len(files)

    if policy["target"] == "workspace":
        # An empty change list does not stop the run: QA tries the
        # application, not the diff.
        out.done(f"{len(files)} changed files  {out.dim('— where to look first, not a boundary')}")
    else:
        out.done(f"{len(files)} files to review  {out.dim(f'({skipped} filtered out)')}")
        if not files:
            return refuse("No file left after filtering — there is nothing to review.", "no-files")

    # A chain member runs unattended: the orchestrator is waiting for it to
    # end, so nobody can step into it. A standalone run stays attended even
    # with `--wait`.
    run = runs.start(project, pack.name, target, provider=provider, attended=chain is None)
    out.step(f"run {run.id}")

    wt = project.root
    wt_owned = bool(policy["worktree"])
    shared_wt = (chain or {}).get("worktree")
    carried: list[str] = []
    ginfo: dict = {}
    try:
        if shared_wt:
            wt = Path(shared_wt)
            in_worktree = True
            wt_owned = False
            out.done(f"working in the chain’s worktree  {out.dim(posix(wt))}")

            out.step("copying the pack method into the worktree")
            carried = runs.materialize_pack(project, pack, wt)
            out.done(f"{len(carried)} files" if carried
                     else "the pack installs nothing into the project")
        elif wt_owned:
            in_worktree = True
            rec = run.record()
            rec["worktree"] = posix(runs.worktree_path(project, target, provider))
            run.save_record(rec)

            out.step("building a throwaway worktree")
            wt = runs.make_worktree(project, target, provider=provider, run=run)
            out.done(posix(wt))

            out.step("copying the pack method into the worktree")
            carried = runs.materialize_pack(project, pack, wt)
            out.done(f"{len(carried)} files" if carried
                     else "the pack installs nothing into the project")
        else:
            in_worktree = False
            # No worktree, deliberately: the application a pack is trying runs
            # over the working copy — with its dependencies installed and its
            # .env. For such a run the source is to be READ; writes go to
            # RUN_DIR.
            out.done(f"working in the project itself  {out.dim(posix(wt))}")

        if policy["graph"]:
            out.step("updating the graph")
            ginfo = runs.prepare_graph(project, wt)
            out.done(f"graph: {ginfo['action']}"
                     + (f"  {out.dim(ginfo['tool'] or '')}" if ginfo.get("tool") else ""))

            out.step("collecting graph signal")
            stats = runs.collect_evidence(project, wt, run, target, files)
            out.done("evidence/ filled" + (f"  {out.dim(str(stats))}" if stats else ""))
        else:
            out.step("collecting signal from the project")
            stats = runs.collect_workspace_evidence(project, run, target, files)
            out.done(f"evidence/ filled  {out.dim(str(stats))}")

        # The chain: its block into the record and the full upstream into
        # evidence. The order is fixed — `write_context` points at both, so
        # both have to exist before it runs.
        upstream_payload = None
        if chain:
            rec = run.record()
            rec["chain"] = chains.record_block(chain)
            run.save_record(rec)
            if chain["upstream"]:
                upstream_payload = chains.write_upstream(project, run, chain["upstream"])
                out.done(f"upstream: {upstream_payload['counts']['findings']} findings "
                         f"from {len(chain['upstream'])} run(s), "
                         f"{upstream_payload['counts']['undecided']} undecided")

        runs.write_context(run, pack, target, wt, files, skipped,
                           prompt=prompt_text, worktree_owned=wt_owned,
                           provider=provider, chain=chain, in_worktree=in_worktree)

        rec = run.record()
        # Memory is not a graph signal. `graph` has a closed key list in
        # run.v1 — merging the two made every graph run an invalid record.
        memory = {k: stats.pop(k) for k in runs.MEMORY_STATS if k in stats}
        if ginfo:
            rec["graph"] = {**ginfo, **stats}
            rec["evidence"] = memory
        else:
            rec["evidence"] = {**stats, **memory}
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

    prompt = (
        f"{runs.method_hint(pack, project, carried, in_worktree=in_worktree)} "
        f"RUN_DIR={posix(run.dir)} — start from its context.json. "
        f"The required output is RUN_DIR/findings.json following finding.v1."
    )
    if chain:
        member = chains.Member(pack.name)
        prompt = chains.step_prompt(
            prompt, member, chain["position"], chain["of"],
            (upstream_payload or {}).get("runs") or [],
            (upstream_payload or {}).get("counts") or {"findings": 0, "undecided": 0},
            chain.get("handoff"), chain.get("handoffPath"))
    if prompt_text:
        shared = chain is not None and not chain.get("ownPrompt")
        label = ("Prompt for the chain as a whole — parts of it may be addressed to other "
                 "members; do only your part and leave theirs to them"
                 if shared else "Prompt for this run")
        prompt += f" {label}: " + _one_line(prompt_text)
    launch, agent_info = runs.launch_argv(
        posix(project.agency_dir), prompt, provider=provider,
        model=getattr(args, "model", None), unattended=chain is not None,
        needs=policy.get("needs"), stream=chain is not None,
        bypass=bool(getattr(args, "bypass", False)))
    rec = run.record()
    rec["agent"] = agent_info
    run.save_record(rec)
    (run.dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    if out.quiet:
        print(json.dumps({
            "ok": True,
            "runId": run.id,
            "runDir": posix(run.dir),
            "worktree": posix(wt),
            "worktreeOwned": wt_owned,
            "prompt": prompt_text,
            "launchPrompt": prompt,
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
    if prompt_text:
        out.say()
        out.say(f"  {out.dim('Prompt:')} {_one_line(prompt_text, 120)}")
    out.say()

    if args.wait:
        dialect = providers.streaming(agent_info["provider"])[1] if chain else None
        return _wait_for_agent(project, run, launch, wt, wt_owned,
                               dialect=dialect, chain=chain)

    if args.launch:
        import os
        os.chdir(wt)
        out.say(f"  {out.bold('launching ' + launch[0] + '…')}\n")
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
    """`agency chain review-graph po` — specialists in sequence, handing over
    between them.

    The orchestration is a loop over `cmd_run`, not a second way to start a
    run — if the chain prepared runs itself, the project would have two
    places where a worktree, evidence and a run record come into being.
    """
    runs.refuse_nested("agency chain")
    project = _project(args)
    members = chains.resolve(args.members)

    if len(members) < 2:
        raise SystemExit("A chain needs at least two members — for one, `agency run` is the command.")

    for m in members:
        # Better now than after the first run finishes.
        packs.load(m.pack, project)

    provider = getattr(args, "provider", None) or "claude"
    if not providers.spec(provider).get("unattendedPrefix"):
        out.fail(f"{provider} has no unattended mode — the chain will open an interactive "
                 f"session and wait for you to close it.")
    elif not providers.authorizes(provider):
        out.fail(f"{provider} has no way to authorize an unattended agent — every write "
                 f"it attempts will be refused and the run will end looking like it "
                 f"found nothing.")

    focus = chains.per_member(members, getattr(args, "focus", None) or [])
    chain_id = ulid()
    out.say(f"\n  {out.bold('chain')}  "
            f"{out.dim(' → '.join(m.label for m in members))}  ·  {chain_id[:10]}\n")

    target = chains.target(project, getattr(args, "pr", None),
                           getattr(args, "latest_merged", False),
                           getattr(args, "since", None))
    if target["kind"] == "workspace":
        out.done(f"target: {target['ref']} @ {target['headRefOid'][:8]}"
                 + (f"  {out.dim('uncommitted changes included')}" if target.get("dirty") else ""))
    else:
        kind = "merged (retrospective audit)" if target["kind"] == "merged-pull-request" else "open"
        out.done(f"target: PR #{target['pr']} — {(target.get('title') or '')[:52]}  {out.dim(kind)}")
    out.say()

    wants_worktree = any(packs.load(m.pack, project).run_policy["worktree"] for m in members)
    chain_wt = None
    if wants_worktree and target.get("pr"):
        out.step("building one worktree for the team")
        chain_wt = runs.make_chain_worktree(project, target, chain_id)
        out.done(posix(chain_wt))

    done: list[str] = []
    failed_at: int | None = None
    for position, member in enumerate(members, start=1):
        carried = {k: v for k, v in vars(args).items()
                   if k not in ("members", "fn", "focus")}
        step = argparse.Namespace(**{**carried, "pack": member.pack,
                                     "wait": True, "launch": False, "json": False,
                                     "prompt": focus.get(member.label) or carried.get("prompt")})
        own = member.label in focus
        block = chains.block(chain_id, position, len(members), list(done))
        block["ownPrompt"] = own
        block["target"] = chains.member_target(target, {})
        if chain_wt and packs.load(member.pack, project).run_policy["worktree"]:
            block["worktree"] = posix(chain_wt)

        if done:
            previous = chains.find_member(project, chain_id, position - 1)
            text, source, where = (chains.handoff_text(previous) if previous
                                   else (None, None, None))
            block["handoff"] = text
            block["handoffPath"] = where
            if source:
                out.say(f"  {out.dim('handing over ' + source + ' from ' + members[position - 2].label)}")

        out.say(f"\n  {out.bold(f'step {position}/{len(members)}')}  {member.label}")
        code = cmd_run(step, chain=block)

        run = chains.find_member(project, chain_id, position)
        if run:
            done.append(run.id)

        if code != 0:
            out.say()
            out.fail(f"the chain stops at step {position}/{len(members)} ({member.label})")
            failed_at = position
            break

    reached = failed_at or len(members)
    if failed_at is None:
        out.say()
        out.done(f"chain finished — {len(done)} runs  {out.dim(chain_id[:10])}")

    if chain_wt:
        if failed_at is None and not getattr(args, "keep_worktree", False):
            runs.remove_worktree(project, chain_wt)
            out.say(f"  {out.dim('worktree removed')}")
        else:
            out.say(f"  {out.dim('worktree kept:')} {posix(chain_wt)}")

    _chain_report(chain_id, members, done, reached, project)
    return 1 if failed_at else 0


def _chain_report(chain_id: str, members, done: list[str], reached: int,
                  project=None) -> None:
    """What finished, what it stands on, and what it cost. Printed after
    completion and after a stop alike — an interrupted chain is still a
    result, only a shorter one."""
    out.say()
    for i, member in enumerate(members, start=1):
        run_id = done[i - 1] if i <= len(done) else None
        mark = "·" if run_id else " "
        state = out.dim(run_id[:10]) if run_id else out.dim("not started")
        if i == reached and run_id and reached < len(members):
            state += out.dim("  (stopped here)")
        out.say(f"  {mark} {i}/{len(members)}  {member.label:<24} {state}")

        run = runs.find_run(project, run_id) if (project and run_id) else None
        if not run:
            continue
        rec = run.record()
        agent, cost = rec.get("agent") or {}, rec.get("cost") or {}
        bits = [f"{rec.get('status', '?')}"]
        if rec.get("counts"):
            bits.append(f"{rec['counts'].get('kept', 0)} kept")
        if agent.get("turns"):
            bits.append(f"{agent['turns']} turns")
        if cost.get("wallClockSeconds"):
            bits.append(_duration(cost["wallClockSeconds"]))
        if cost.get("usd"):
            bits.append(f"${cost['usd']:.2f}")
        denied = (agent.get("denied") or {}).get("count") or 0
        left = [n for n in ("summary.md", "handoff.md", "agent.md")
                if (run.dir / n).is_file()]
        line = f"      {out.dim(' · '.join(bits))}"
        if denied:
            line += f"  {out.err(f'{denied} denied')}"
        if left:
            line += f"  {out.dim('· ' + ', '.join(left))}"
        out.say(line)
    out.say()
    if done:
        out.say(f"  {out.dim('Triage queue:')}  agency triage --list")


def _duration(seconds: float) -> str:
    """A run's duration the way a person reads it."""
    s = int(round(seconds))
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


#: How many wrapped lines of one reasoning block reach the terminal. Enough to
#: see what the agent is thinking about, not enough to bury the chain's own
#: output — the full text is kept in `agent.jsonl` either way.
THINKING_LINES = 3


def _wrapped(text: str, limit: int) -> list[str]:
    import shutil as _shutil
    import textwrap
    width = max(40, min(_shutil.get_terminal_size((100, 24)).columns, 100) - 6)
    lines = textwrap.wrap(" ".join(str(text).split()), width=width)
    if len(lines) <= limit:
        return lines
    return lines[:limit] + ["…"]


def _progress(event) -> None:
    """One line per thing the agent does — and a glimpse of why."""
    if event.kind == "tool":
        label = event.tool or "?"
        out.say(f"  {out.dim('·')} {out.bold(label)}  {out.dim(event.detail or '')}")
    elif event.kind == "denied":
        out.say(f"  {out.err('×')} {out.bold(event.tool or '?')}  "
                f"{out.dim((event.detail or '') + '  — denied')}")
    elif event.kind == "thinking":
        for i, line in enumerate(_wrapped(event.detail or "", THINKING_LINES)):
            out.say(f"  {out.dim('~' if i == 0 else ' ')} {out.dim(line)}")
    elif event.kind == "text":
        for i, line in enumerate(_wrapped(event.detail or "", THINKING_LINES)):
            out.say(f"  {out.dim('›' if i == 0 else ' ')} {line}")


def _wait_for_agent(project, run, launch: list[str], wt: Path, wt_owned: bool,
                    dialect: str | None = None, chain: dict | None = None) -> int:
    """`--wait`: start the agent, wait for it, and run the gate right away."""
    out.say(f"  {out.bold('launching ' + launch[0] + '…')}  "
            f"{out.dim('Ctrl-C stops the run')}\n")
    try:
        result = runs.attend(project, run, launch, wt,
                             dialect=dialect, chain=chain,
                             on_event=_progress if dialect else None)
    except KeyboardInterrupt:
        info = runs.abandon(project, run, "stopped with Ctrl-C while the agent was running")
        out.say()
        out.note(f"stopped — {run.id[:10]} closed as abandoned"
                 + ("  ·  worktree removed" if info.get("worktreeRemoved") else ""))
        return 130

    code = result["exitCode"]
    out.say()
    out.say(f"  {out.dim('agent finished')}  exit {code}  {out.dim('·')}  "
            f"{_duration(result['wallClockSeconds'])}"
            + (f"  {out.dim('·')}  {result['turns']} turns" if result.get("turns") else "")
            + (f"  {out.dim('·')}  ${result['usd']:.2f}" if result.get("usd") else ""))

    gated = ingest.ingest(project, run)
    _ingest_report(run, gated)

    denied = (run.record().get("agent") or {}).get("denied") or {}

    if code != 0:
        runs.failed(run, f"the agent exited with {code}")
        out.fail(f"the agent exited with {code} — the run is recorded as failed")
        if proc.which(launch[0]) is None:
            out.say(f"  {out.dim(launch[0] + ' is not on PATH; `agency doctor` checks that up front')}")
        out.say()
    elif gated.get("noOutput"):
        runs.failed(run, "the agent wrote no findings.json")
        out.fail("nothing was written — the run is recorded as failed, not as “no findings”")
        out.say()

    if denied.get("count"):
        out.say(f"  {out.err(str(denied['count']) + ' tool calls were denied')}"
                f"  {out.dim(', '.join(denied.get('tools') or []))}")
        out.say(f"  {out.dim('The pack needs those — widen `needs` in pack.json, or pass --bypass.')}")
        out.say()
    elif gated.get("noOutput") and code == 0:
        out.say(f"  {out.dim('The agent finished cleanly and still wrote nothing — RUN_DIR/agent.md has what it said.')}")
        out.say()

    if wt_owned:
        print(f"  {out.dim('Cleanup:')}  agency cleanup --run {run.id[:8]}\n")
    return 0 if (code == 0 and not gated.get("noOutput")) else 1


def cmd_cleanup(args) -> int:
    """Close a run that is not coming back, and take its worktree with it."""
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

    if getattr(args, "fix", False):
        removed = runs.repair_record(run)
        if removed:
            out.done(f"removed keys run.v1 does not know: {', '.join(removed)}")
        else:
            out.note("nothing to repair in the record")

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

    resolved = []
    for f in findings:
        a = f.get("anchor") or {}
        if not a.get("file"):
            continue
        r = anchor.resolve(project.root, a)
        resolved.append({"id": f.get("id"), "file": a["file"], "line": a.get("line"),
                         "resolvedLine": r.line, "via": r.via, "note": r.note,
                         "drift": anchor.drift(project.root, a)})

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
    """One door to the graph — for the core and for the agent.

    Half of the graph's use lives in the prompt (`SKILL.md`), a Python
    facade does not cover it. The side effect is the important one: the seam
    is tested by every run, not theoretically on the day the driver changes.
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
    """The gate's output. Printed by `agency ingest` and `agency run --wait`
    alike — the same run should look the same, whether the gate ran right
    away or an hour later."""
    if data.get("noOutput"):
        print(f"\n  run {out.bold(run.id)}\n")
        print(f"  {out.err('  ×')} the agent wrote no findings.json")
        return
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
    """The gate between what the agent wrote and what becomes a finding."""
    project = _project(args)
    run = runs.find_run(project, args.run)
    if not run:
        raise SystemExit("No run found.")

    data = ingest.ingest(project, run, min_score=args.min_score)
    _emit(args, data, lambda: _ingest_report(run, data))
    return 1 if data.get("noOutput") else 0


# ---------------------------------------------------------------- knowledge

def cmd_knowledge(args) -> int:
    """What the project knows, as committed markdown."""
    project = _project(args)
    data = knowledge.bundle(project, write=args.rebuild)
    data["pages"] = knowledge.pages_summary(project)

    def human():
        print(f"\n  {out.bold('knowledge')}  {out.dim(data['path'])}\n")
        pages = data["pages"]
        print(f"  {str(data['findings']).rjust(3)} findings"
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
    """Precision as a bar. `None` is not zero — an empty precision draws as a
    dash, because "I don't know" and "none of it held up" are two different
    messages."""
    p = t.get("precision")
    if p is None:
        return out.dim("—".ljust(10)) + "     "
    filled = round(p * 10)
    color = out.ok if p >= 0.7 else out.warn if p >= 0.4 else out.err
    return color("#" * filled + "." * (10 - filled)) + f" {p:.0%}".rjust(5)


def cmd_metrics(args) -> int:
    project = _project(args)
    r = metrics.collect(project)

    def table(title: str, rows: dict) -> None:
        rows = {k: v for k, v in (rows or {}).items() if v["accepted"] + v["rejected"]}
        if not rows:
            return
        print(f"  {out.dim(title)}")
        for k, v in rows.items():
            tally = f"{v['accepted']} yes / {v['rejected']} no"
            print(f"    {k[:22]:24} {_bar(v)}  {out.dim(tally)}")
        print()

    def human():
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
        ag = r.get("agreement") or {}
        if ag.get("hires", 0) > 1 and (ag["crossHire"] or ag["sameHire"]):
            print(f"  {out.dim('agreement')}")
            print(f"    {'found by another specialist too':32} {ag['crossHire']}")
            print(f"    {'found twice by the same one':32} {ag['sameHire']}")
            print(out.dim("    A high first number means the second provider is buying "
                          "confirmation, not coverage.\n"))
        if r["rejectReasons"]:
            print(f"  {out.dim('reasons for rejection')}")
            for k, v in r["rejectReasons"].items():
                print(f"    {k[:22]:24} {v}")
            print()

    return _emit(args, r, human)


# ---------------------------------------------------------------- export

def cmd_export(args) -> int:
    project = _project(args)
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

    data = export.push(rows, int(args.project_number), owner, dry_run=args.dry_run)

    def human():
        if data["dryRun"]:
            head = "Dry run — nothing was sent"
        else:
            title = data["project"].get("title")
            head = f"Project #{args.project_number} ({owner})" + (f" — {title}" if title else "")
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
                "by": runs.normalize_by(d.get("by")) if d else None,
            }
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


def cmd_note(args) -> int:
    """A note on a finding. Its own command, because a note is not a decision."""
    project = _project(args)
    run = _run_with_finding(project, args.finding)
    ev = runs.append_note(run, args.finding, args.text, args.by)

    def human():
        print(f"  {args.finding}: {ev['text']}")

    return _emit(args, ev, human)


def _target_label(target: dict) -> str:
    """What a run's target is called, in one line."""
    if target.get("pr"):
        return f"PR #{target['pr']}"
    if target.get("kind") == "workspace":
        return target.get("ref") or "workspace"
    return target.get("title") or "—"


def cmd_status(args) -> int:
    project = _project(args)
    all_runs = runs.load_runs(project)
    rows = []
    for run in all_runs[:args.limit]:
        rec = run.record()
        dec = runs.decisions(run)
        fs = run.findings()
        agent = rec.get("agent") or {}
        rows.append({
            "id": run.id, "pack": rec.get("pack"), "status": rec.get("status"),
            "startedAt": rec.get("startedAt"),
            "provider": agent.get("provider"),
            "model": agent.get("model"),
            "target": (rec.get("target") or {}).get("pr"),
            "kind": (rec.get("target") or {}).get("kind"),
            "targetLabel": _target_label(rec.get("target") or {}),
            "prompt": rec.get("prompt"),
            "chain": rec.get("chain"),
            "exitReason": rec.get("exitReason"),
            "denied": (agent.get("denied") or {}).get("count") or 0,
            "outputs": [n for n in ("summary.md", "handoff.md", "agent.md")
                        if (run.dir / n).is_file()],
            "findings": len(fs), "undecided": sum(1 for f in fs if f.get("id") not in dec),
        })

    installed = [p.name for p in packs.available(project)]
    payload = {"project": {"name": project.name, "slug": project.slug,
                           "root": posix(project.root), "packs": installed},
              "runs": rows}

    def human():
        print(f"\n  {out.bold(project.name)}  {out.dim(posix(project.root))}")
        print(f"  {out.dim('packs:')} {', '.join(installed) or out.dim('none')}\n")
        if not rows:
            print(f"  {out.dim('No runs yet.')}\n")
            return
        for d in rows:
            icon = {"ok": out.ok("✓"), "no-findings": out.ok("○"), "running": out.warn("…"),
                    "abandoned": out.dim("×"), "failed": out.err("✗")}.get(
                        d["status"], out.dim("·"))
            pr = d["targetLabel"] or "—"
            c = d.get("chain") or {}
            tag = (out.dim(f"chain {c['id'][:6]} {c['position']}/{c['of']}") if c else "")
            print(f"  {icon} {d['id'][:10]} {pr[:18]:18} {d['findings']:3} findings "
                  f"{out.dim(f'{d['undecided']} undecided'):24} {out.dim(d['startedAt'] or '')}"
                  f"{'  ' + tag if tag else ''}")
        open_runs = [d for d in rows if d["status"] == "running"]
        if open_runs:
            print(f"\n  {out.warn('still open:')} "
                  f"{', '.join(d['id'][:10] for d in open_runs)}")
            print(out.dim("  A run stays open until someone closes it."))
            print(out.dim("  Close them: agency cleanup --unfinished"))
        print()

    return _emit(args, payload, human)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="project root (default: the current git repo)")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(
        prog="agency",
        parents=[common],
        description="Specialists for this repository — skills in .claude/skills/agency-<name>/. "
                    "Attended, on your own login, with evidence-backed findings that stay.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("packs", parents=[common], help="the specialists in this project")
    s.set_defaults(fn=cmd_packs)

    s = sub.add_parser("doctor", parents=[common], help="check the prerequisites BEFORE a run starts")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("prs", parents=[common], help="pull requests to review — open and merged")
    s.add_argument("--state", choices=["open", "merged", "all"], default="all")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_prs)

    s = sub.add_parser("run", parents=[common],
                       help="run a pack — over a pull request, or over the project as it is")
    s.add_argument("pack", help="a pack name, e.g. review-graph")
    s.add_argument("--pr", type=int, help="PR number (default: the PR of the current branch)")
    s.add_argument("--latest-merged", action="store_true",
                   help="the last merged PR — retrospective audit")
    s.add_argument("--prompt", "-p", help="what this run should focus on — free text")
    s.add_argument("--since", help="base ref for a run over the project (default: the default branch)")
    start = s.add_mutually_exclusive_group()
    start.add_argument("--launch", action="store_true",
                       help="start the agent right away and hand this terminal over to it")
    start.add_argument("--wait", action="store_true",
                       help="start the agent, wait for it, and run the gate when it ends")
    s.add_argument("--model", help="model for this run (default: the provider's default)")
    s.add_argument("--provider", choices=providers.known(),
                   help="which runner does the work (default: claude)")
    s.add_argument("--bypass", action="store_true",
                   help="no authorization checks at all — the worktree is throwaway, the machine is not")
    s.add_argument("--force", action="store_true", help="a draft or an already reviewed commit too")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("chain", parents=[common],
                       help="run specialists one after another, each judging what the previous one found")
    s.add_argument("members", metavar="pack", nargs="+",
                   help="two or more pack names, in the order they should run")
    s.add_argument("--pr", type=int, help="PR number (default: the PR of the current branch)")
    s.add_argument("--latest-merged", action="store_true",
                   help="the last merged PR — retrospective audit")
    s.add_argument("--prompt", "-p", help="what the chain should focus on — every member gets it")
    s.add_argument("--focus", action="append", metavar="PACK:TEXT",
                   help="a prompt for one member only, e.g. --focus po:\"is it worth it?\" "
                        "(repeatable; overrides --prompt for that member)")
    s.add_argument("--since", help="base ref for a run over the project (default: the default branch)")
    s.add_argument("--model", help="model for every step")
    s.add_argument("--provider", choices=providers.known(),
                   help="runner for every step — a chain runs on one provider (default: claude)")
    s.add_argument("--bypass", action="store_true", help="no authorization checks at all, every step")
    s.add_argument("--force", action="store_true", help="a draft or an already reviewed commit too")
    s.add_argument("--keep-worktree", action="store_true",
                   help="do not remove the team's worktree after a successful chain")
    s.set_defaults(fn=cmd_chain)

    s = sub.add_parser("validate", parents=[common], help="check findings.json against the contract and the anchors against the code")
    s.add_argument("--run", help="run id (default: the latest)")
    s.add_argument("--fix", action="store_true",
                   help="drop keys from the record that run.v1 does not know")
    s.set_defaults(fn=cmd_validate)

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
    s.add_argument("--min-score", type=int, help="overrides the pack's minScore")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("knowledge", parents=[common],
                       help="what the project knows, as committed markdown — readable without Agency")
    s.add_argument("--rebuild", action="store_true",
                   help="rewrite .agency/knowledge/ from the runs (it is derived, always safe)")
    s.set_defaults(fn=cmd_knowledge)

    s = sub.add_parser("metrics", parents=[common],
                       help="precision, dedup, queue age — by dimension, severity and provider")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("export", parents=[common], help="one-way push of decided findings into a GitHub Project")
    s.add_argument("--run", help="a single run only (default: all)")
    s.add_argument("--project", dest="project_number", type=int, required=True,
                   help="Project number")
    s.add_argument("--owner", help="Project owner (default: from the git remote)")
    s.add_argument("--include-undecided", action="store_true",
                   help="undecided findings too")
    s.add_argument("--dry-run", action="store_true", help="only show what would be sent")
    s.set_defaults(fn=cmd_export)

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

    s = sub.add_parser("note", parents=[common], help="a note on a finding — free text, not a decision")
    s.add_argument("finding")
    s.add_argument("text")
    s.add_argument("--by", default=runs.HUMAN,
                   help="who decides — `hire:<id>` for a specialist (ready-made in context.json), `human` for a person")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("status", parents=[common], help="overview of the project's runs")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_status)

    return p


def _force_utf8() -> None:
    """Windows console and pipes default to cp1250, and `→`, `✓` or diacritics
    come out as UnicodeEncodeError. `reconfigure` is not enough once the
    stream is already bound — wrapping the binary buffer directly is."""
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
