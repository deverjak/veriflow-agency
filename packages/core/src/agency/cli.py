"""`agency` — the command line.

Every command understands `--json`, because its second user is the VS Code
extension and its third is an agent. If only a human could read the output,
those two would be second-class.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import anchor, chain as chains, config, graph, ingest, instructions, knowledge, metrics, outputs, packs, proc, providers, replay, runs, serve as serving
from .util import bundled, out, posix, read_json, ulid, write_json

# ---------------------------------------------------------------- helpers


def _emit(args, data, human) -> int:
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        human()
    return 0


def _project(args) -> config.Project:
    return config.require(getattr(args, "repo", None))


# ---------------------------------------------------------------- init

def cmd_init(args) -> int:
    """The bootstrap — and deliberately the only thing here that installs anything.

    A project still has no configuration afterwards. What it gets is one
    generic skill directory in its working tree, uncommitted, to read and
    commit like any other source, plus the one .gitignore line that keeps run
    records out of git. Everything else about this project is written BY that
    pack, in this repository, against this repository.

    Safe to run twice: a pack already there is left alone.
    """
    project = _project(args)
    # Both generic packs, because both are about this system rather than about
    # any project: `author` writes the specialists, `verify` judges what they
    # find. Everything else a project runs is written for it, by `author`.
    seeded_all = [packs.seed(project, name, force=args.force)
                  for name in packs.GENERIC]
    seeded = seeded_all[0]
    ignored = packs.ignore_run_records(project)
    nxt = f'agency run {packs.AUTHOR} --prompt "what the new specialist should do"'
    data = {"project": project.name, "pack": seeded, "packs": seeded_all,
            "gitignore": ignored, "next": nxt}

    def line(icon: str, path: str, note: str) -> None:
        print(f"  {icon} {path}")
        print(f"      {out.dim(note)}")

    note = {packs.AUTHOR: "it writes this project’s own specialists",
            packs.VERIFY: "a second pair of eyes over what they find"}

    def human():
        print(f"\n  {out.bold(project.name)}\n")
        for row in seeded_all:
            if row["created"]:
                line(out.ok("✓"), row["path"], note.get(row["pack"], "a generic pack"))
            else:
                line(out.warn("!"), row["path"],
                     "already here, left as it is — `--force` copies over it")
        if ignored:
            line(out.ok("✓"), ".agency/.gitignore",
                 "run records stay out of git; knowledge/ is committed on purpose")
        print(f"\n  {out.dim(nxt)}\n")

    return _emit(args, data, human)


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
            "scope": p.scope,
            "sink": p.sink,
        })

    def human():
        print()
        for e in data:
            print(f"  {out.bold(e['name']):28} {out.dim(e['skill'])}")
            print(f"  {'':28} {out.dim(e['description'] or '')}")
        print()

    return _emit(args, data, human)


# ---------------------------------------------------------------- doctor

def _script_of(command: str | None) -> str:
    """The file a pack's command runs, when it runs one of its own.

    Best effort, and deliberately so: `doctor` is here to catch the typo in a
    path, not to parse a command line. Anything it cannot recognise is left
    alone rather than reported as missing.
    """
    parts = (command or "").split()
    if parts and parts[0] == "python" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else ""


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
    # The same requirements, indexed the other way round: a tool, and who
    # would be left without it. `wanted` answers "does anyone need this";
    # naming the specialist is what makes a conflict actionable.
    by_tool: dict[str, list[str]] = {}
    for p in hired:
        wanted |= set(p.requires)
        for tool in p.requires:
            by_tool.setdefault(tool, []).append(p.name)

    def needed(tool: str) -> bool:
        return not hired or tool in wanted

    def tool_check(name: str, tool: str, value, missing: str) -> None:
        if value:
            check(name, True, value, fatal=needed(tool))
        elif needed(tool):
            # Fatal only once somebody is hired. A project with no packs has no
            # run to fail, and the one command it does have — `agency init` —
            # needs none of this; saying "a run would fail" there is answering
            # about a run nobody can start yet.
            check(name, False, missing, fatal=bool(hired))
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
    # A slug is a GitHub fact, so it is wanted by whoever wants `gh` — the same
    # question, asked once. A pack that only reads the working tree does not
    # care that there is no remote, and marking that fatal is how a project
    # that has just run `agency init` gets told a run would fail when nothing
    # about it would.
    tool_check("repo slug", "gh", project.slug,
               "no remote — the specialists in this project need one")

    # Two sets of instructions, one specialist. `CLAUDE.md` reaches the agent
    # on its own — the runner starts it in the project (or in a worktree that
    # carries the committed copy) and never passes or overrides that file — so
    # a house rule against a tool the pack stands on is invisible until a run
    # is already breaking it. Not fatal: the project may well be right, and
    # which of the two gives is not a question a runner gets to answer.
    house = instructions.conflicts(project.root, by_tool)
    for hit in house:
        check(f"rules vs {hit['tool']}", False,
              f"{hit['file']}:{hit['line']} · needed by {', '.join(hit['packs'])} · "
              f"“{hit['rule']}”", fatal=False)
    seen = instructions.paths(project.root)
    if seen and by_tool and not house:
        check("house rules", True,
              ", ".join(p.name for p in seen)
              + " · nothing there forbids what the specialists need", fatal=False)

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
        # A pack's own scripts, both of them. The failure is identical and it
        # is quiet in both directions: a missing sink leaves a finding resting
        # as a candidate, a missing scope leaves a run with memory nobody
        # narrowed — and neither says a word at the time.
        for label, command in (("sink", p.sink), ("scope", p.scope)):
            token = _script_of(command)
            if token and not (project.root / token).is_file():
                check(f"pack {p.name} {label}", False, f"{token} not found", fatal=False)

        # An output policy is data the core acts on, so a typo in it does not
        # fail — it defaults, quietly and wrongly. `dedpu: false` would keep
        # deduplicating and the pack's author would have no way to find out.
        for problem in outputs.errors(p):
            check(f"pack {p.name} outputs", False, problem, fatal=False)

        # A key that reads like a rule and is not one. `minScore` was the
        # gate's threshold until 8 September 2026; a pack still declaring 85
        # looks stricter than one declaring 70 and neither is stricter at all.
        for key in p.superseded_keys:
            check(f"pack {p.name} {key}", False,
                  f"`{key}` no longer does anything — a claim's bar is "
                  f"`outputs.<type>.evidence`, volume is `outputs.<type>.limit`",
                  fatal=False)

    fatal = [c for c in checks if not c["ok"] and c["fatal"]]

    def human():
        print(f"\n  {out.bold(project.name)}\n")
        for c in checks:
            icon = out.ok("✓") if c["ok"] else (out.err("✗") if c["fatal"] else out.warn("!"))
            print(f"  {icon} {c['name']:24} {out.dim(c['detail'])}")
        print()
        if house:
            # The fork, said out loud. A warning that only names the collision
            # leaves the founder with "and now what" — and the answer is short
            # enough to print: one of the two has to give, and neither the
            # runner nor the specialist is allowed to pick.
            fork = ("Change the rule, or the pack that needs the tool — "
                    "a run cannot choose for you.")
            print(f"  {out.warn('Two sets of instructions disagree.')} "
                  f"{out.dim(fork)}\n")
        if fatal:
            print(f"  {out.err('A run would fail.')} Fix the items marked ✗.\n")
        else:
            # No packs yet: the bootstrap is the only move there is.
            hints = [f"agency run {p.name}{_run_hint(p)}" for p in hired] or ["agency init"]
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


def cmd_run(args, chain: dict | None = None, pinned: dict | None = None) -> int:
    """Prepare and start one run.

    `pinned` is a target somebody else already resolved — a replay over the
    commit a fixture was recorded on. It is a separate argument from `chain`
    on purpose: a replay is not a chain member, and reusing the chain block to
    pin a target would put a `chain` block into the record of a run that has
    no team.
    """
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
    # Unattended is not "who launched it", it is whether anybody could
    # answer. A chain member never can — the orchestrator is blocked waiting
    # for it. `--unattended` says the same about a standalone run on purpose,
    # and both consequences follow together: the agent runs in print mode,
    # and the pack's `needsUnattended` commands are granted up front, because
    # there is nobody to ask about them.
    unattended = chain is not None or bool(getattr(args, "unattended", False))
    # Remote Control is an interactive session, and the two things that make a
    # run unattended — `-p` and the machine-readable stream — exist only
    # without one. Refused here, before a worktree is built for a run that
    # could not start.
    wants_remote = getattr(args, "remote_control", None) is not None
    if wants_remote:
        if unattended:
            raise SystemExit(
                "--remote-control and --unattended are two different runs: Remote "
                "Control hands you a session to talk to, --unattended is one nobody "
                "can answer. Pick one.")
        if not providers.remote_controls(provider):
            raise SystemExit(
                f"{provider} has no Remote Control — only `claude` does. "
                "Run it unattended and follow up with `agency follow` instead.")

    # In --json mode progress output is suppressed, or it would mix with the
    # output and the extension would fail to parse it.
    out.quiet = bool(getattr(args, "json", False))

    def refuse(reason: str, code: str) -> int:
        out.note(reason)
        if out.quiet:
            print(json.dumps({"ok": False, "reason": code, "message": reason},
                             ensure_ascii=False, indent=2))
        _hold_window(wants_remote and getattr(args, "origin", "cli") == "remote")
        return 1

    out.say(f"\n  {out.bold(pack.title)}  {out.dim(pack.name + '@' + provider)} → {project.name}\n")

    if unattended and chain is None:
        out.note("unsupervised — the pack's consequential commands are granted up "
                 "front and nothing will stop to ask")

    prompt_text = (getattr(args, "prompt", None) or "").strip() or None

    # Revising an existing method rather than writing a new one. The brief IS
    # the assignment here, so it stands in for `--prompt`, and the threshold is
    # a condition rather than a warning — see `metrics.REVISE_MINIMUM`.
    revise = (getattr(args, "revise", None) or "").strip() or None
    brief = None
    if revise:
        if pack.name != packs.AUTHOR:
            raise SystemExit(
                f"--revise belongs to `{packs.AUTHOR}` — it is the pack that writes packs. "
                f"`agency run {packs.AUTHOR} --revise {revise}`")
        packs.load(revise, project)                  # a typo, said before anything runs
        brief = metrics.for_author(project, revise)
        decided = brief["triage"]["accepted"] + brief["triage"]["rejected"]
        if decided < metrics.REVISE_MINIMUM:
            raise SystemExit(
                f"{revise} has {decided} decided findings; revising a method needs at "
                f"least {metrics.REVISE_MINIMUM}.\nA method rewritten against fewer is "
                f"differently random, not better — and it would replace the one whose "
                f"numbers you already know.\nRun the pack, decide what it finds "
                f"(`agency findings`), come back.")
        prompt_text = prompt_text or (
            f"Revise the {revise} pack against its own record. The brief is in "
            f"RUN_DIR/evidence/for-author.md.")
    elif prompt_text and policy["prompt"] == "none":
        raise SystemExit(
            f"Pack “{pack.name}” does not take a prompt — --prompt has nothing to do here.")
    if policy["prompt"] == "required" and not prompt_text:
        return refuse(
            f"{pack.title} needs to know what to work on. Pass --prompt \"…\".",
            "no-prompt")

    shared_target = (chain or {}).get("target")
    if pinned is not None:
        # An eval: the same commit as last time, today's method. Resolving it
        # again would compare a method change with a code change and call the
        # sum of the two a result.
        target = dict(pinned)
        out.done(f"{(target.get('headRefOid') or '')[:8]}  {out.dim('pinned by a fixture')}")
    elif shared_target is not None:
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
    # with `--wait` — unless `--unattended` said otherwise.
    run = runs.start(project, pack.name, target, provider=provider,
                     attended=not unattended,
                     origin=getattr(args, "origin", None) or "cli",
                     device=getattr(args, "device", None))
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

        if brief:
            # Both shapes, deliberately: the markdown is what makes the step
            # checkable by a person (if a founder cannot say what to change
            # after reading it, an agent will not manage it either), and the
            # JSON is there so a revision does not have to re-derive a number
            # by reading prose.
            ev = run.dir / "evidence"
            ev.mkdir(parents=True, exist_ok=True)
            (ev / "for-author.md").write_text(metrics.author_brief(brief),
                                              encoding="utf-8")
            write_json(ev / "for-author.json", brief)

        runs.write_context(run, pack, target, wt, files, skipped,
                           prompt=prompt_text, worktree_owned=wt_owned,
                           provider=provider, chain=chain, in_worktree=in_worktree,
                           revise=revise)

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
    # `needsUnattended` joins in only when nobody could be asked anyway. A
    # supervised run stays interactive, so leaving those commands out here is
    # what makes Claude Code's own permission prompt ask a person before the
    # pack's consequential ones run, instead of granting them blind.
    needs = list(policy.get("needs") or [])
    if unattended:
        needs += policy.get("needsUnattended") or []
    # The session's name is the run's own, so what shows up in the Claude app
    # can be matched back to a record here. A name given on the command line
    # wins: somebody typing one has a reason.
    remote = None
    if wants_remote:
        remote = str(args.remote_control or "").strip() or runs.session_name(pack.name, run.id)
    # Nobody at this machine, and an interactive runner: the flags that stop it
    # asking something before the session is up. At the terminal the question
    # can simply be answered, and giving things up to avoid it would be a loss.
    alone = remote is not None and getattr(args, "origin", "cli") == "remote"
    # What the project has already said no to, in front of the session rather
    # than in a file somebody hopes gets read. Generated during preparation
    # (`knowledge.for_run`); absent when the project has rejected nothing yet.
    rejected_before = run.dir / "evidence" / knowledge.DO_NOT_REPORT
    launch, agent_info = runs.launch_argv(
        posix(project.agency_dir), prompt, provider=provider,
        model=getattr(args, "model", None), unattended=unattended,
        needs=needs, stream=unattended,
        bypass=bool(getattr(args, "bypass", False)),
        remote_control=remote, no_questions=alone,
        append_prompt=(rejected_before.read_text(encoding="utf-8")
                       if rejected_before.is_file() else None),
        # Makes the runner report its own tool calls into RUN_DIR, which is
        # what turns `evidence[].source` from a claim into a fact. Nothing is
        # written into the project for it.
        settings=runs.hook_settings(run.dir, provider))
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
    if remote:
        out.say()
        out.say(f"  {out.bold('Remote Control')}  {out.dim('the session is called')} "
                f"{out.bold(remote)}")
        out.say(f"  {out.dim('Open that name in the Claude app to keep talking to it.')}")
    out.say()

    if alone and providers.trusted(provider, wt) is False:
        # The one question that has no flag. Opening the window anyway would
        # park a session on "Is this a project you trust?" where nobody can
        # answer it — and the phone would watch a run that never started.
        info = runs.abandon(project, run, _untrusted(provider, wt, wt_owned))
        out.fail(_untrusted(provider, wt, wt_owned))
        if info.get("worktreeRemoved"):
            out.note("the worktree was removed again")
        return 1

    if args.wait:
        dialect = providers.streaming(agent_info["provider"])[1] if unattended else None
        if not dialect:
            # One line, not a warning and not a question: waiting attended is a
            # legitimate choice and the default. What it costs is that this run
            # records an exit code and a duration and nothing else — no turns,
            # no price, no session to follow up on — so it will be missing from
            # every number about what the agent did.
            out.say(f"  {out.dim('This run records only its exit code and duration. '
                                 'Turns, cost and a resumable session need '
                                 '--unattended.')}\n")
        return _wait_for_agent(project, run, launch, wt, wt_owned,
                               dialect=dialect, chain=chain, budget=pack.budget)

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
        # A shared prompt is addressed to the chain, not to each member — so a
        # member whose pack takes none simply does not get it. Passing it would
        # abort the whole chain at that step, and that is exactly how `verify`
        # (prompt: "none", deliberately: a verifier must not be handed an
        # assignment that could steer its verdict) would take the chain down
        # with it. A `--focus` aimed at such a member is still refused — that
        # one was addressed to it on purpose, and dropping it silently would be
        # worse than the error.
        takes_prompt = packs.load(member.pack, project).run_policy["prompt"] != "none"
        step = argparse.Namespace(**{**carried, "pack": member.pack,
                                     "wait": True, "launch": False, "json": False,
                                     "prompt": focus.get(member.label)
                                     or (carried.get("prompt") if takes_prompt else None)})
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

        # A blocked member exits cleanly — it did what it could and said so —
        # and that is exactly why the chain has to look. Carrying on would hand
        # the next specialist an empty handoff and pay it to judge nothing,
        # which is the most expensive way to learn nothing.
        rec = run.record() if run else {}
        if rec.get("status") == "blocked":
            out.say()
            out.fail(f"the chain stops at step {position}/{len(members)} ({member.label}) "
                     f"— it is blocked, not finished")
            out.say(f"  {out.warn(rec.get('exitReason') or 'see blocked.md')}")
            out.say(f"  {out.dim('Clear that, then run the chain again. '
                                 'The runs so far are recorded.')}")
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
        left = [n for n in ("summary.md", "handoff.md", "blocked.md", "agent.md")
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


def _untrusted(provider: str, wt: Path, throwaway: bool) -> str:
    """Why a session cannot be opened here, and what to do instead.

    Said in one place because `run` and `follow` hit it for the same reason and
    a person reading it on a phone should not have to tell two versions of it
    apart.
    """
    where = ("this specialist works in a throwaway worktree, and that is a new "
             "directory every time" if throwaway
             else f"{provider} has not been opened in {posix(wt)} before")
    return (f"A session to talk to cannot start here: {where}, so {provider} would "
            "stop and ask whether the folder is trusted — and nobody is at the machine "
            "to answer. Run it unsupervised instead, or open that directory in "
            f"{provider} once at the machine.")


def _hold_window(hold: bool) -> None:
    """Keep a window that was opened for this run from closing on the message.

    A run started as a session to talk to gets a console of its own, opened by
    `agency serve` because the daemon has none to lend. When preparation
    refuses — a draft pull request, a commit this specialist has already
    reviewed — the reason is printed into that console and the process then
    ends, taking the window and the only copy of the reason with it. The phone
    cannot be told either: this run's stdout is the window, not a pipe.

    So the window waits. Nothing is holding a worktree at this point, and the
    daemon forgets a job that produced no record, so an open window costs
    nothing but the pixels.
    """
    if not hold:
        return
    try:
        if sys.stdin.isatty():
            out.say()
            input("  Nothing started. Press Enter to close this window. ")
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def _wait_for_agent(project, run, launch: list[str], wt: Path, wt_owned: bool,
                    dialect: str | None = None, chain: dict | None = None,
                    budget: dict | None = None) -> int:
    """`--wait`: start the agent, wait for it, and run the gate right away."""
    out.say(f"  {out.bold('launching ' + launch[0] + '…')}  "
            f"{out.dim('Ctrl-C stops the run')}\n")
    try:
        result = runs.attend(project, run, launch, wt,
                             dialect=dialect, chain=chain, budget=budget,
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

    if result.get("runaway"):
        # Three times what the pack itself declared normal. The one place
        # anything is stopped on a number, and the number is the pack's own.
        minutes = (budget or {}).get("minutes")
        why = (f"stopped at {runs.RUNAWAY}x the pack's own budget "
               f"({minutes:g} min)" if minutes else "stopped at its ceiling")
        runs.failed(run, why)
        out.fail(f"{why} — the run is recorded as failed")
        out.say(f"  {out.dim('Raise `budget` in pack.json if this is what a real run costs here.')}")
        out.say()
    elif code != 0:
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


def cmd_follow(args) -> int:
    """`agency follow -p "and what about the migration?"` — one more question.

    Not a second run. The runner's own session is resumed, so everything the
    specialist established the first time is still in front of it: the target,
    the evidence it read, the findings it wrote and why. Asking the same thing
    as a new run would mean paying to re-read a pull request in order to answer
    "and the second one?".

    Two ways to ask, and they are the two this product has everywhere else:
    printed — the answer arrives in the run's own stream, which is what a phone
    watches — or as a session to talk to (`--remote-control`, driven from the
    Claude app). What a follow-up does NOT do is re-run the gate: the gate's
    verdict belongs to what the agent wrote, and if the answer changed that,
    `agency ingest` is the step that says so.
    """
    if getattr(args, "json", False):
        raise SystemExit(
            "--json and `follow` do not go together: the agent writes to this same "
            "stdout. Read the record afterwards with `agency status --json`.")
    runs.refuse_nested("agency follow")
    project = _project(args)

    run = runs.find_run(project, getattr(args, "run", None))
    if run is None:
        which = getattr(args, "run", None)
        raise SystemExit(
            f"No run {which} in {project.name}." if which
            else f"{project.name} has no run to follow up on yet.")

    rec = run.record()
    agent = rec.get("agent") or {}
    provider = agent.get("provider") or "claude"
    session = agent.get("sessionId")
    pack_name = rec.get("pack") or "?"

    def refuse(reason: str) -> int:
        out.note(reason)
        return 1

    if rec.get("status") == "running":
        return refuse(f"{pack_name} is still working on {run.id[:10]}. A follow-up "
                      "joins a session that has stopped — this one has not.")
    if not session:
        return refuse(
            f"Run {run.id[:10]} left no session to resume. Only a streamed run records "
            "one, so a run started in a terminal cannot be followed up on from here — "
            "that terminal is where it continues.")
    if not providers.resumes(provider):
        return refuse(f"{provider} cannot resume a session — there is nothing to "
                      "continue.")

    prompt_text = (getattr(args, "prompt", None) or "").strip()
    if not prompt_text:
        return refuse("A follow-up is a question. Pass --prompt “…”.")

    interactive = getattr(args, "remote_control", None) is not None
    if interactive and not providers.remote_controls(provider):
        return refuse(f"{provider} has no Remote Control — only `claude` does. Ask "
                      "without it and the answer arrives here.")
    remote = None
    if interactive:
        remote = str(args.remote_control or "").strip() or runs.session_name(pack_name, run.id)

    # The pack's `needs` again, because authorization is granted to a process,
    # not to a session: an agent that could call `agency triage` an hour ago is
    # refused it now unless it is granted again.
    needs: list[str] = []
    try:
        policy = packs.load(pack_name, project).run_policy
        needs = list(policy.get("needs") or [])
        if not interactive:
            needs += policy.get("needsUnattended") or []
    except SystemExit:
        # The pack was renamed or removed since the run. The session can still
        # answer a question — it just answers it with fewer commands.
        out.note(f"the pack “{pack_name}” is no longer in this project — "
                 "the follow-up runs with no commands granted")

    wd = runs.working_dir(project, run)
    alone = interactive and getattr(args, "origin", "cli") == "remote"
    if alone and providers.trusted(provider, wd) is False:
        return refuse(_untrusted(provider, wd, wd != project.root))
    launch, info = runs.launch_argv(
        posix(project.agency_dir), prompt_text, provider=provider,
        model=agent.get("model"), unattended=not interactive,
        needs=needs, stream=not interactive,
        bypass=bool(getattr(args, "bypass", False)),
        resume=session, remote_control=remote, no_questions=alone)

    out.say(f"\n  {out.bold('follow-up')}  {out.dim(pack_name + ' · ' + run.id[:10])}"
            f" → {project.name}\n")
    out.done(f"resuming session {out.dim(session)}")
    out.done(("in the run's worktree  " if wd != project.root else "in the project itself  ")
             + out.dim(posix(wd)))

    # The record says a person asked again BEFORE the agent starts: a phone
    # decides from `status` whether there is a live stream to watch, and it
    # asks the moment this command answers.
    prior_status = rec.get("status") or "ok"
    entry = {"at": runs.now(), "prompt": prompt_text,
             "origin": getattr(args, "origin", None) or "cli",
             "attended": interactive}
    if getattr(args, "device", None):
        entry["device"] = args.device
    ups = list(rec.get("followUps") or []) + [entry]
    rec["followUps"] = ups
    rec["status"] = "running"
    if remote:
        rec["agent"] = {**agent, "remoteControl": remote}
    run.save_record(rec)

    if remote:
        out.say()
        out.say(f"  {out.bold('Remote Control')}  {out.dim('the session is called')} "
                f"{out.bold(remote)}")
        out.say(f"  {out.dim('Open that name in the Claude app to keep talking to it.')}")
    out.say()
    out.say(f"  {out.bold('launching ' + launch[0] + '…')}  {out.dim('Ctrl-C stops it')}\n")

    dialect = providers.streaming(provider)[1] if not interactive else None
    findings_before = _mtime(run.findings_path)
    try:
        result = runs.attend(project, run, launch, wd, dialect=dialect,
                             append=True, message_file=f"answer-{len(ups)}.md",
                             on_event=_progress if dialect else None)
    except KeyboardInterrupt:
        _close_follow(run, prior_status, None)
        out.say()
        out.note("stopped — the run is back to what it was before the question")
        return 130
    _close_follow(run, prior_status, result["exitCode"])

    out.say()
    out.say(f"  {out.dim('the session finished')}  exit {result['exitCode']}  "
            f"{out.dim('·')}  {_duration(result['wallClockSeconds'])}"
            + (f"  {out.dim('·')}  {result['turns']} turns" if result.get("turns") else "")
            + (f"  {out.dim('·')}  ${result['usd']:.2f}" if result.get("usd") else ""))
    answer = run.dir / f"answer-{len(ups)}.md"
    if answer.is_file():
        out.say(f"  {out.dim('the answer:')}  {posix(answer)}")
    if result.get("denied"):
        out.say(f"  {out.err(str(result['denied']) + ' tool calls were denied')}")
    if _mtime(run.findings_path) != findings_before:
        out.say()
        out.note(f"findings.json changed — `agency ingest --run {run.id[:8]}` gates it again")
    out.say()
    return 0 if result["exitCode"] == 0 else 1


def _mtime(path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _close_follow(run: runs.Run, status: str, code: int | None) -> None:
    """Give the run back the status the gate gave it.

    A follow-up borrows `running` so a phone knows there is a stream to watch;
    it does not get to overturn what the gate decided about the findings, which
    is what any other status here would mean.
    """
    rec = run.record()
    rec["status"] = status
    ups = rec.get("followUps") or []
    if ups:
        ups[-1]["exitCode"] = code
    run.save_record(rec)


def cmd_cleanup(args) -> int:
    """Close a run that is not coming back, and take its worktree with it."""
    project = _project(args)

    if getattr(args, "all", False):
        if not getattr(args, "discard", False):
            raise SystemExit(
                "--all only goes with --discard. To close runs whose terminal is "
                "gone, use --unfinished.")
        closed, skipped = [], []
        for run in runs.load_runs(project):
            if run.record().get("status") == "running":
                continue
            if runs.decisions(run) and not args.force:
                skipped.append({"run": run.id, "decisions": len(runs.decisions(run))})
                continue
            closed.append({**runs.discard(project, run, force=args.force), "action": "discarded"})
        data = {"closed": closed, "skipped": skipped, "unfinished": len(runs.unfinished(project))}

        def human():
            findings = sum(r.get("findings", 0) for r in closed)
            print(f"  {len(closed)} run(s) discarded — {findings} findings went with them")
            if skipped:
                print(f"  {len(skipped)} kept, they carry decisions: "
                      + ", ".join(s["run"][:10] for s in skipped)
                      + "  — --force takes those too")

        return _emit(args, data, human)

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
            # No `anchor`: since Step 4 whether an output points at source
            # is the type's policy, not the schema's, and this branch cannot
            # see the pack. It checks what every output has.
            for key in ("id", "runId", "pack", "severity", "title", "body", "evidence"):
                if key not in f:
                    errors.append({"index": i, "id": f.get("id"), "path": key, "message": "missing"})

    resolved = []
    for f in findings:
        a = anchor.of(f)
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
    if data.get("blocked"):
        # Ahead of the counts on purpose: a blocked run's headline is the wall
        # it hit, not the two findings it managed before hitting it.
        print(f"  {out.warn('  ⊘')} {out.bold('blocked')} — "
              f"{data.get('blockedReason') or 'see RUN_DIR/blocked.md'}")
        print(f"  {out.dim('    This is a result, not a failure: read blocked.md, '
                           'clear the obstacle, run again.')}")
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
    print(f"  {out.ok(str(c['kept']).rjust(3))} kept"
          + (f"  {out.dim('·')}  {c.get('sent', 0)} sent to the board" if c.get("sent") else "")
          + (f"  {out.dim('·')}  {c.get('held', 0)} held for the next specialist"
             if c.get("held") else ""))
    for e in data.get("dispatchErrors") or []:
        print(f"  {out.err('  ×')} {e['id'][:10]} could not reach the board: {out.dim(e['error'][:80])}")
    print()
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

    data = ingest.ingest(project, run)
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

    if getattr(args, "for_author", None):
        # A different question with a different reader: not "how is this
        # project doing" but "what in this pack's SKILL.md is wrong". It may
        # well be read by an agent, so it comes out as markdown by default and
        # as data on request.
        packs.load(args.for_author, project)          # a typo, said now
        brief = metrics.for_author(project, args.for_author)
        return _emit(args, brief, lambda: print("\n" + metrics.author_brief(brief)))

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
        if t.get("scoreAccepted") is not None and t.get("scoreRejected") is not None:
            print(f"  {out.dim('Score')}           accepted {t['scoreAccepted']}  ·  "
                  f"rejected {t['scoreRejected']}"
                  + (out.dim("   they barely differ — the score is measuring nothing")
                     if abs(t["scoreAccepted"] - t["scoreRejected"]) < 5 else ""))
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
        # Cost, turns and denials exist only for a streamed run, so each says
        # how many runs it came from. Without that they read as averages over
        # every run — over a population half of which never recorded them.
        c, p = r["cost"], (r["cost"].get("population") or {})
        total = p.get("runs") or 0
        for label, key, fmt in (("usd", "usd", lambda v: f"${v:.2f}"),
                                ("turns", "turns", str),
                                ("denied", "denied", str)):
            if c.get(key) is None:
                continue
            print(f"  {out.dim(label.ljust(15))} {fmt(c[key])}  "
                  f"{out.dim(f'from {p.get(key, 0)} of {total} runs (streamed only)')}")
        if c.get("usdPerSentFinding") is not None:
            print(f"  {out.dim('per finding'.ljust(15))} ${c['usdPerSentFinding']:.2f}  "
                  f"{out.dim('to get one onto the board (streamed runs only)')}")
        blind = p.get("attended") or 0
        if blind and total:
            print(f"  {out.dim('Blind')}           "
                  f"{out.dim(f'{blind} of {total} runs were attended and recorded '
                             f'no cost or turns')}")
        print()

        # One line per lifecycle of every type a pack declared. Named by the
        # pack, because `precision` is the wrong word for whether a bet was
        # chosen — and one number covering both "was it chosen" and "did it
        # work" would be the wrong number as well.
        cycles = r.get("byLifecycle") or {}
        if cycles:
            print(f"  {out.dim('By output type')}")
            for key, cell in cycles.items():
                pack_name, type_name, cycle_name = key.split("/", 2)
                value = "—" if cell["value"] is None else f"{cell['value']:.2f}"
                decided = cell["positive"] + cell["negative"]
                name = (cell["metric"] or cycle_name)[:16]
                counts = out.dim(f"{cell['positive']} of {decided} decided")
                waiting = (out.dim(f"  ({cell['undecided']} undecided)")
                           if cell["undecided"] else "")
                print(f"    {(pack_name + ' ' + type_name)[:22]:24} "
                      f"{name:18} {value}  {counts}{waiting}")
            print()
        table("by dimension", r["byDimension"])
        table("by severity", r["bySeverity"])
        table("by specialist", r["byHire"])
        table("by model", r["byModel"])
        # Only worth printing once a pack's method has more than one version
        # in the data — one row here says nothing a pack row does not.
        if len(r.get("bySkill") or {}) > 1:
            table("by method version", r["bySkill"])
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


# ---------------------------------------------------------------- findings

def cmd_findings(args) -> int:
    project = _project(args)
    selected = runs.load_runs(project) if args.all else (
        [r] if (r := runs.find_run(project, args.run)) else [])

    rows = []
    seen_ids: set[str] = set()
    for run in selected:
        dec = runs.decisions(run)
        hist = runs.history(run)
        rec = run.record()
        for f in run.findings():
            fid = f.get("id")
            seen_ids.add(fid)
            d = dec.get(fid)
            a = anchor.of(f)
            row = {
                "runId": run.id, "id": fid, "severity": f.get("severity"),
                "title": f.get("title"), "body": f.get("body"),
                "dimension": f.get("dimension"),
                "type": f.get("type") or outputs.DEFAULT_TYPE,
                "file": a.get("file"), "line": a.get("line"),
                "state": f.get("state"),
                "decision": d.get("state") if d else None,
                "ref": runs.acted_ref(f),
                "url": d.get("url") if d else None,
                "reason": d.get("reason") if d else None,
                "note": d.get("note") if d else None,
                "by": runs.normalize_by(d.get("by")) if d else None,
            }
            if getattr(args, "json", False):
                row["anchor"] = a
                row["evidence"] = f.get("evidence") or []
                row["target"] = rec.get("target") or {}
                row["history"] = hist.get(fid, [])
                row["duplicateOf"] = f.get("duplicateOf")
                # What actually happened because of this output, with the
                # attempts that failed. `ref` above is only where it ended
                # up — which is the answer to a different question than "how
                # often does this pack's board answer at all".
                row["actions"] = f.get("actions") or []
                row["score"] = f.get("score")
                row["pack"] = f.get("pack")
                if a.get("file"):
                    row["drift"] = anchor.drift(project.root, a)
                    r = anchor.resolve(project.root, a)
                    row["resolved"] = {"line": r.line, "via": r.via, "note": r.note}
            rows.append(row)

    # Across all runs, a finding whose own run is gone still has a line —
    # the trail is what a clone with no `.agency/runs/` has to go on.
    if args.all:
        for fid, trow in runs.read_trail(project).items():
            # A row is worth showing once something HAPPENED to it. The two
            # words were the whole vocabulary until types existed; now the
            # verdict can be `selected` or `confirmed`, so what qualifies is
            # that a polarity was recorded at all.
            decided = (trow.get("polarity") is not None
                       or trow.get("state") in ("sent", "rejected"))
            if fid in seen_ids or not decided:
                continue
            a = trow.get("anchor") or {}
            rows.append({
                "runId": trow.get("runId"), "id": fid, "severity": trow.get("severity"),
                "title": trow.get("title"), "body": None, "dimension": trow.get("dimension"),
                "file": a.get("file"), "line": a.get("line"), "state": trow.get("state"),
                "type": trow.get("type") or outputs.DEFAULT_TYPE,
                "decision": trow.get("state"),
                "ref": trow.get("ref"), "url": trow.get("url"), "reason": trow.get("reason"),
                "note": None, "by": runs.normalize_by(trow.get("by")), "trailOnly": True,
            })

    # One pack now writes more than one kind of output, and a founder looking
    # for the three bets does not want them among forty findings.
    if getattr(args, "type", None):
        rows = [r for r in rows if r.get("type") == args.type]

    def human():
        if not rows:
            print(f"\n  {out.dim('No findings. Run `agency run review-graph --pr <n>`.')}\n")
            return
        undecided = sum(1 for r in rows if r["state"] in (None, "candidate", "held"))
        print(f"\n  {len(rows)} findings, {undecided} undecided\n")
        mark = {"sent": out.ok("→"), "rejected": out.err("✘")}
        sev = {"blocker": out.err("●"), "high": out.err("●"), "medium": out.warn("●"), "low": out.dim("●")}
        for r in rows:
            m = mark.get(r["state"], out.dim("·"))
            tail = ""
            if r["state"] == "rejected":
                tail = out.dim(f"{r['reason'] or ''} ({r['by']})" if r["by"] else (r["reason"] or ""))
            elif r["state"] == "sent" and r["ref"]:
                tail = out.dim(r["ref"])
            loc = f"{r['file']}:{r['line']}"
            print(f"  {m} {sev.get(r['severity'], '·')} {(r['id'] or '')[:8]:9} "
                  f"{(r['title'] or '')[:52]:54} {out.dim(loc)} {tail}")
        print()

    return _emit(args, rows, human)


def _run_with_finding(project: config.Project, finding_id: str) -> runs.Run:
    for r in runs.load_runs(project):
        if any(f.get("id") == finding_id for f in r.findings()):
            return r
    raise SystemExit(f"Finding “{finding_id}” was not found in any run.")


def cmd_triage(args) -> int:
    """Judge a finding — a chain member's own `agency triage`, or a person's.

    There is no `defer`: what is not rejected goes to the board when the
    chain ends, so the only two verdicts are `accept` (dispatch it now) and
    `reject` (remember not to report it again).
    """
    project = _project(args)
    run = _run_with_finding(project, args.finding)

    if args.action == "reject":
        ev = runs.reject(project, run, args.finding, args.reason, args.note, args.by)

        def human():
            print(f"  {args.finding} → rejected"
                  + (f" · {ev['reason']}" if ev["reason"] else "")
                  + (f" · {ev['note']}" if ev["note"] else ""))

        return _emit(args, ev, human)

    finding = next((f for f in run.findings() if f.get("id") == args.finding), None)
    if finding is None:
        raise SystemExit(f"Finding “{args.finding}” was not found in run {run.id}.")
    result = runs.dispatch(project, run, finding, args.by)

    def human():
        if result.get("noSink"):
            print(f"  {args.finding} — no board here, stays candidate")
        elif result["ok"]:
            print(f"  {args.finding} → sent" + (f" · {result['ref']}" if result["ref"] else ""))
        else:
            print(f"  {args.finding} — could not reach the board: {result['error']}")

    _emit(args, result, human)
    return 1 if (not result.get("noSink") and not result["ok"]) else 0


def cmd_feedback(args) -> int:
    """What happened to an output, in that output's own vocabulary.

    `agency triage` stays what it is: a finding's two verbs, and both of them
    DO something — `accept` dispatches through the pack's sink, `reject`
    remembers not to report the thing again. This command is for the types
    that act on nothing, where the whole of "what happened" is the record: a
    bet was `selected`, and a season later it was `successful`.

    The allowed words come from the pack (`outputs.<type>.feedback`), so this
    command has no vocabulary of its own and never needs one added.
    """
    project = _project(args)
    run = _run_with_finding(project, args.finding)
    finding = next((f for f in run.findings() if f.get("id") == args.finding), {})
    policy = outputs.policy_for(_pack_of(project, run), finding.get("type"))

    if policy.actions == "sink":
        raise SystemExit(
            f"“{policy.name}” goes out through this pack's sink, so its verdict is "
            f"`agency triage accept` / `agency triage reject` — those dispatch and "
            f"remember, which recording alone would not do.")

    ev = runs.record_feedback(project, run, args.finding, args.kind,
                              args.reason, args.note, args.by)

    def human():
        where = out.dim(ev["lifecycle"] or "")
        because = f" · {ev['reason']}" if ev["reason"] else ""
        print(f"  {args.finding} → {ev['state']}  {where}{because}")

    return _emit(args, ev, human)


def _pack_of(project: config.Project, run: runs.Run):
    try:
        return packs.load(run.record().get("pack") or "", project)
    except SystemExit:
        return None


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


def cmd_replay(args) -> int:
    """`agency replay` — run a pack again over a commit it has already judged.

    Without this, `author --revise` is a machine for unverifiable changes,
    which is worse than no machine: it would produce confident diffs nobody
    could check.
    """
    project = _project(args)

    if getattr(args, "pin", None):
        run = runs.find_run(project, args.pin)
        if run is None:
            raise SystemExit(f"No run {args.pin} in {project.name}.")
        name = (getattr(args, "name", None)
                or f"{run.record().get('pack')}-{run.id[:8].lower()}")
        fixture = replay.pin(project, run, name)

        def human():
            out.done(f"{fixture['name']}  {out.dim(fixture['path'])}")
            print(f"  {len(fixture['gold'])} decided findings pinned at "
                  f"{(fixture['target'].get('headRefOid') or '')[:8]}")
            print(f"  {out.dim('Commit it — a fixture is the project’s answer key.')}\n")

        return _emit(args, fixture, human)

    chosen = ([replay.find(project, args.fixture)] if getattr(args, "fixture", None)
              else replay.fixtures(project, getattr(args, "pack", None)))
    chosen = [f for f in chosen if f]
    if not chosen:
        raise SystemExit(
            "No fixture to replay. Pin a finished run whose findings were decided:\n"
            "  agency replay --pin <run> --name <fixture>")

    results = []
    for fixture in chosen:
        if getattr(args, "score_only", False):
            # No agent: score whatever the pinned run already has on disk. What
            # this checks is the fixture itself — a fixture that fails against
            # its own run is a fixture with a broken answer key.
            run = runs.find_run(project, fixture.get("fromRun"))
            results.append(replay.compare(fixture, run.findings() if run else []))
            continue

        out.say(f"\n  {out.bold('replay')}  {fixture['name']}  "
                f"{out.dim(fixture['pack'] + ' @ ' + (fixture['target'].get('headRefOid') or '')[:8])}")
        step = argparse.Namespace(
            **{**vars(args), "pack": fixture["pack"], "prompt": fixture.get("prompt"),
               # Always streamed, even when the original was attended: without
               # turns and a price there is nothing to compare the new run's
               # cost against, and "better" that costs three times as much is
               # not better.
               "unattended": True, "wait": True, "launch": False, "json": False,
               "revise": None, "remote_control": None, "force": True,
               "pr": None, "latest_merged": False, "since": None})
        before = {r.id for r in runs.load_runs(project)}
        # `_files` is the same private key the ordinary path uses to carry the
        # file list into preparation, so nothing downstream has to know a
        # replay is happening.
        cmd_run(step, pinned={**fixture["target"],
                              "_files": list(fixture.get("files") or [])})
        fresh = [r for r in runs.load_runs(project) if r.id not in before]
        results.append(replay.compare(fixture, fresh[0].findings() if fresh else []))

    def human():
        print()
        for r in results:
            print(replay.report(r))
            print()

    _emit(args, {"results": results}, human)
    return 0 if all(r["pass"] for r in results) else 1


def cmd_hook(args) -> int:
    """What the runner's own PostToolUse hook calls, once per tool call.

    Reads the hook payload from stdin, because that is how the runner hands it
    over. It is deliberately the dumbest command in the tool: append a line and
    exit 0. A hook that can fail is a hook that can take a run down with it, so
    a malformed payload, an unwritable directory or a runner shape nobody has
    seen yet all end the same way — silently, with the run carrying on.

    That silence is affordable precisely because a missing `tool-calls.jsonl`
    makes the gate skip the provenance check entirely rather than assume the
    worst (`ingest.commands_run`).
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    run_dir = Path(args.run_dir)

    if args.event == "stop":
        return _hook_stop(run_dir)
    try:
        runs.record_tool_call(run_dir, payload)
    except OSError:
        pass
    return 0


def _hook_stop(run_dir: Path) -> int:
    """The second chance, while the context that wrote the findings is alive.

    `counts.gated` is a total loss today: the agent writes, exits, the gate
    drops it, nobody repeats the run. Exit 2 with the problems on stderr hands
    them back to the agent instead — probed on 2026-09-06, and it genuinely
    works: an agent told a field was missing rewrote the file and stopped
    again.

    Two blocks at most, counted in the run's own record. The third stop passes
    whatever it says, because a hook that can block forever produces a run that
    never finishes — which costs more than the findings it was saving.
    """
    rec = read_json(run_dir / "run.json", default={})
    blocked = ((rec.get("agent") or {}).get("stopBlocks")) or 0
    if blocked >= ingest.STOP_BLOCKS:
        return 0

    ctx = read_json(run_dir / "context.json", default={})
    root = Path((ctx.get("project") or {}).get("root") or run_dir)
    try:
        problems = ingest.stop_errors(run_dir, root)
    except OSError:
        return 0
    if not problems:
        return 0

    rec["agent"] = {**(rec.get("agent") or {}), "stopBlocks": blocked + 1}
    try:
        write_json(run_dir / "run.json", rec)
    except OSError:
        pass

    print("findings.json does not pass the contract yet — fix these and stop again:",
          file=sys.stderr)
    for p in problems[:20]:
        print(f"  - {p}", file=sys.stderr)
    if blocked + 1 >= ingest.STOP_BLOCKS:
        print("  (this is the last time this will be checked — after the next "
              "stop the gate has it)", file=sys.stderr)
    return 2


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
            "outputs": [n for n in ("summary.md", "handoff.md", "blocked.md", "agent.md")
                        if (run.dir / n).is_file()],
            "findings": len(fs), "undecided": sum(1 for f in fs if f.get("id") not in dec),
        })

    # Over every run, not only the ones printed: "how much of my history can
    # answer a question about cost" is a fact about the project, not about the
    # last twenty rows.
    attended_runs = sum(1 for r in all_runs
                        if (r.record().get("trigger") or {}).get("attended") is not False)

    installed = [p.name for p in packs.available(project)]
    payload = {"project": {"name": project.name, "slug": project.slug,
                           "root": posix(project.root), "packs": installed,
                           "providers": providers.catalog()},
              "runs": rows,
              # Not a reproach — attended is the default and a good one. It is
              # what a person needs in order to know which questions their own
              # history can answer at all.
              "blind": {"attended": attended_runs, "runs": len(all_runs)}}

    def human():
        print(f"\n  {out.bold(project.name)}  {out.dim(posix(project.root))}")
        print(f"  {out.dim('packs:')} {', '.join(installed) or out.dim('none')}\n")
        if not rows:
            print(f"  {out.dim('No runs yet.')}\n")
            return
        for d in rows:
            icon = {"ok": out.ok("✓"), "no-findings": out.ok("○"), "running": out.warn("…"),
                    "blocked": out.warn("⊘"),
                    "abandoned": out.dim("×"), "failed": out.err("✗")}.get(
                        d["status"], out.dim("·"))
            pr = d["targetLabel"] or "—"
            c = d.get("chain") or {}
            tag = (out.dim(f"chain {c['id'][:6]} {c['position']}/{c['of']}") if c else "")
            print(f"  {icon} {d['id'][:10]} {pr[:18]:18} {d['findings']:3} findings "
                  f"{out.dim(f'{d['undecided']} undecided'):24} {out.dim(d['startedAt'] or '')}"
                  f"{'  ' + tag if tag else ''}")
            # The word, not only the mark. `no-findings` and `blocked` are one
            # character apart in the list and opposite in meaning, and the
            # second one is asking for something to be fixed.
            if d["status"] == "blocked":
                print(f"      {out.warn('blocked')} {out.dim(d.get('exitReason') or 'see blocked.md')}")
        if attended_runs:
            print(f"\n  {out.dim(f'{attended_runs} of {len(all_runs)} runs were attended '
                                 f'and recorded no cost or turns.')}")
            print(out.dim("  Those numbers come from --unattended runs only."))
        open_runs = [d for d in rows if d["status"] == "running"]
        if open_runs:
            print(f"\n  {out.warn('still open:')} "
                  f"{', '.join(d['id'][:10] for d in open_runs)}")
            print(out.dim("  A run stays open until someone closes it."))
            print(out.dim("  Close them: agency cleanup --unfinished"))
        print()

    return _emit(args, payload, human)


# ---------------------------------------------------------------- serve

def cmd_serve(args) -> int:
    """Hold the projects open for a phone on the tailnet, and wait.

    The command is the activation: while it runs, the projects it names can be
    worked on from somewhere else; when it stops, they cannot. That is why the
    window is an argument here and not a setting anywhere — reopening it is a
    decision made at this machine, by the person who owns it.
    """
    if getattr(args, "forget", False):
        path = serving.selection_path()
        if path.is_file():
            path.unlink()
            out.done(f"forgotten — {posix(path)} is gone")
        else:
            out.note("there was no stored list")
        return 0

    # Flags beat the stored list outright rather than adding to it: "serve
    # exactly this one project for an hour" has to be sayable, and a flag that
    # silently joins a list written weeks ago is not that.
    flags = serving.Selection(projects=list(args.project or []),
                              scan=list(args.scan or []),
                              depth=args.depth)
    stored = serving.load_selection()
    selection, source = ((flags, "arguments") if not flags.empty()
                         else (stored, "stored list"))
    if getattr(args, "save", False):
        if flags.empty():
            raise SystemExit("--save wants something to save — pass --project or --scan with it.")
        serving.save_selection(flags)

    if selection.empty():
        selection = serving.Selection(projects=[posix(config.require(None).root)])
        source = "this project"

    projects = serving.resolve_projects(selection)
    if not projects:
        raise SystemExit(
            "Nothing to open. `--scan <dir>` looks for repositories with a specialist in "
            "them, `--project <path>` opens one whether it has any or not, and `--save` "
            "keeps the answer for next time.")

    try:
        daemon = serving.serve(projects, args.host, args.port, args.hours,
                               pair_window=args.pair_window,
                               allow_bypass=bool(getattr(args, "allow_bypass", False)))
    except OSError as e:
        raise SystemExit(
            f"Cannot listen on {args.host}:{args.port} — {e}. Another `agency serve` "
            "is probably already holding it; that one is the activation.")

    out.say(f"\n  {out.bold('agency serve')}  {out.dim(f'{args.host}:{daemon.port}')}"
            f"  {out.dim('·')}  {out.dim(f'activated for {args.hours:g} h')}"
            f"  {out.dim('·')}  {out.dim(f'{len(daemon.projects)} projects from the {source}')}\n")
    for key, p in daemon.projects.items():
        installed = ", ".join(x.name for x in packs.available(p)) or "no specialists yet"
        out.done(f"{key:28} {out.dim(installed)}")
    if source == "arguments" and not getattr(args, "save", False):
        out.say(f"  {out.dim('Add --save once and a bare `agency serve` opens these again.')}")
    out.say()
    out.say(f"  {out.bold('Pairing code:')}  {out.bold(daemon.pair_code)}"
            f"   {out.dim(f'valid for {args.pair_window // 60} minutes, for one device')}")
    if daemon.allow_bypass:
        # Printed loudly and every time. A window that hands out the right to
        # run with no authorization checks at all is not something to learn
        # about afterwards, from a log.
        out.say(f"  {out.err('This window grants --bypass')}"
                f"   {out.dim('the device paired with this code may run')}")
        out.say(f"  {out.dim('with the authorization checks off. Restart without the flag to stop offering it.')}")
    else:
        offer = "Pairs without the right to skip authorization checks — --allow-bypass grants it."
        out.say(f"  {out.dim(offer)}")
    known = daemon.devices.all()
    if known:
        out.say(f"  {out.dim('Already paired:')} "
                f"{out.dim(', '.join(d.name + ('  bypass' if d.bypass else '') for d in known))}")
    out.say()
    out.say(f"  {out.dim('Publish it to the tailnet (once, on this machine):')}")
    out.say(f"  {out.dim(f'  tailscale serve --bg {daemon.port}')}")
    out.say(f"  {out.dim('Never `tailscale funnel` — that one is the public internet.')}")
    out.say()
    out.say(f"  {out.dim('Ctrl-C closes the window. A run already under way keeps going.')}\n")

    try:
        while daemon.activated():
            time.sleep(1)
    except KeyboardInterrupt:
        out.say()
        out.note("stopped — the projects are no longer reachable from anywhere else")
        return 130
    finally:
        if daemon.server is not None:
            daemon.server.shutdown()
    out.note(f"the activation window closed after {args.hours:g} h — "
             "start `agency serve` again to reopen it")
    return 0


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

    s = sub.add_parser("init", parents=[common],
                       help="put the one generic pack — `author` — into this project")
    s.add_argument("--force", action="store_true",
                   help="copy it in again over the one already there")
    s.set_defaults(fn=cmd_init)

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
    s.add_argument("--remote-control", nargs="?", const="", metavar="NAME",
                   help="start an interactive session the Claude app can drive, named "
                        "agency-<pack>-<run> unless NAME says otherwise. Interactive by "
                        "definition, so not with --unattended.")
    start.add_argument("--wait", action="store_true",
                       help="start the agent, wait for it, and run the gate when it ends")
    s.add_argument("--model", help="model for this run (default: the runner's named "
                   "default — sonnet for claude, never the session's own)")
    s.add_argument("--provider", choices=providers.known(),
                   help="which runner does the work (default: claude)")
    s.add_argument("--bypass", action="store_true",
                   help="no authorization checks at all — the worktree is throwaway, the machine is not")
    s.add_argument("--unattended", action="store_true",
                   help="run unsupervised: the pack's consequential commands (`needsUnattended`) "
                        "are granted up front and nothing stops to ask. The agent runs in print "
                        "mode, so pair it with --wait to watch it and gate the output in one go.")
    s.add_argument("--revise", metavar="PACK",
                   help="for `author` only: revise an existing pack's method instead of "
                        "writing a new one. The run is handed that pack's brief "
                        "(`agency metrics --for-author`) and writes a diff into its "
                        "SKILL.md. Refuses to start with too little decided history.")
    s.add_argument("--force", action="store_true", help="a draft or an already reviewed commit too")
    # Hidden, because they are not something a person types: they are how a
    # client says who it is, and the run record is the only reader.
    s.add_argument("--origin", choices=["cli", "extension", "remote"], default="cli",
                   help=argparse.SUPPRESS)
    s.add_argument("--device", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("follow", parents=[common],
                       help="ask the specialist of a finished run one more thing — "
                            "the same session, not a new run")
    s.add_argument("--run", help="run id (default: the latest)")
    s.add_argument("--prompt", "-p", help="the question")
    s.add_argument("--remote-control", nargs="?", const="", metavar="NAME",
                   help="reopen the session as one you can talk to, from the Claude app")
    s.add_argument("--bypass", action="store_true",
                   help="no authorization checks at all, for this question")
    s.add_argument("--origin", choices=["cli", "extension", "remote"], default="cli",
                   help=argparse.SUPPRESS)
    s.add_argument("--device", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_follow)

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
                       help="the gate: contract, existence, evidence, dedup — BEFORE a finding becomes a finding")
    s.add_argument("--run", help="run id (default: the latest)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("knowledge", parents=[common],
                       help="what the project knows, as committed markdown — readable without Agency")
    s.add_argument("--rebuild", action="store_true",
                   help="rewrite .agency/knowledge/ from the runs (it is derived, always safe)")
    s.set_defaults(fn=cmd_knowledge)

    s = sub.add_parser("metrics", parents=[common],
                       help="precision, dedup, queue age — by dimension, severity and provider")
    s.add_argument("--for-author", metavar="PACK",
                   help="one pack's numbers as a brief for revising its method, "
                        "not as a dashboard")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("replay", parents=[common],
                       help="run a pack again over a commit it already judged — "
                            "and refuse a change that brings back a rejected finding")
    s.add_argument("--pack", help="every fixture of this pack")
    s.add_argument("--fixture", help="one fixture by name")
    s.add_argument("--pin", metavar="RUN",
                   help="turn a finished run's decided findings into a fixture")
    s.add_argument("--name", help="what to call the fixture being pinned")
    s.add_argument("--score-only", action="store_true",
                   help="do not run anything — score the pinned run's own findings, "
                        "which checks the fixture rather than the method")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("cleanup", parents=[common],
                       help="close a run that is not coming back and remove its worktree")
    s.add_argument("--run")
    s.add_argument("--unfinished", action="store_true",
                   help="every run still marked as running — what a closed terminal leaves behind")
    s.add_argument("--discard", action="store_true",
                   help="delete the run outright, record and evidence included; "
                        "refused when it carries decisions")
    s.add_argument("--all", action="store_true",
                   help="every finished run; only together with --discard")
    s.add_argument("--force", action="store_true",
                   help="discard even a run that carries decisions")
    s.set_defaults(fn=cmd_cleanup)

    s = sub.add_parser("findings", parents=[common], help="findings and their decisions")
    s.add_argument("--run")
    s.add_argument("--all", action="store_true", help="across all runs")
    s.add_argument("--type", help="only outputs of this type (`bet`, `decision`, …)")
    s.set_defaults(fn=cmd_findings)

    s = sub.add_parser("feedback", parents=[common],
                       help="what happened to an output, in its own type's words")
    s.add_argument("finding")
    s.add_argument("kind", help="one of the type's own feedback kinds")
    s.add_argument("--reason")
    s.add_argument("--note")
    s.add_argument("--by", default=runs.HUMAN,
                   help="who says so — `hire:<id>` for a specialist, `human` for a person")
    s.set_defaults(fn=cmd_feedback)

    s = sub.add_parser("triage", parents=[common], help="decide on a finding — an agent calls this too")
    s.add_argument("action", choices=["accept", "reject"])
    s.add_argument("finding")
    # No `choices`: which reasons are allowed depends on the output's type
    # (`outputs.<type>.feedback.<lifecycle>.reasons`), which argparse cannot
    # know. `runs.append_decision` validates and names the allowed set.
    s.add_argument("--reason")
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

    s = sub.add_parser("hook", parents=[common],
                       help="called by the runner's own hooks, not by a person")
    hsub = s.add_subparsers(dest="event", required=True)
    h = hsub.add_parser("tool-call", parents=[common],
                        help="record one PostToolUse call into RUN_DIR/tool-calls.jsonl")
    h.add_argument("--run-dir", required=True)
    h.set_defaults(fn=cmd_hook)
    h = hsub.add_parser("stop", parents=[common],
                        help="check findings.json before the run is allowed to end")
    h.add_argument("--run-dir", required=True)
    h.set_defaults(fn=cmd_hook)
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("status", parents=[common], help="overview of the project's runs")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("serve", parents=[common],
                       help="open this project to a paired phone on the tailnet, for a while")
    s.add_argument("--project", action="append", metavar="PATH",
                   help="open this project, specialists or not (repeatable)")
    s.add_argument("--scan", action="append", metavar="DIR",
                   help="open every repository under DIR that has a specialist in it "
                        "(repeatable). A run's throwaway worktree is not one.")
    s.add_argument("--depth", type=int, default=serving.SCAN_DEPTH, metavar="N",
                   help=f"how many directories below a --scan root to look "
                        f"(default: {serving.SCAN_DEPTH}, for <root>/<org>/<repo>)")
    s.add_argument("--save", action="store_true",
                   help="remember this --project/--scan so a bare `agency serve` opens it again")
    s.add_argument("--forget", action="store_true", help="drop the remembered list and stop")
    s.add_argument("--host", default="127.0.0.1",
                   help="what to bind (default: the loopback — `tailscale serve` publishes it)")
    s.add_argument("--port", type=int, default=7777)
    s.add_argument("--hours", type=float, default=8,
                   help="how long the projects stay open (default: 8)")
    s.add_argument("--pair-window", type=int, default=serving.PAIR_WINDOW,
                   metavar="SECONDS",
                   help="how long the pairing code printed at startup is accepted "
                        f"(default: {serving.PAIR_WINDOW})")
    s.add_argument("--allow-bypass", action="store_true",
                   help="let the device paired in this window start a run with the "
                        "authorization checks off (--dangerously-skip-permissions). "
                        "Asked here because it is a decision about this machine; the "
                        "phone cannot ask for it.")
    s.set_defaults(fn=cmd_serve)

    return p


def _force_utf8() -> None:
    """Windows console and pipes default to cp1250, and `→`, `✓` or diacritics
    come out as UnicodeEncodeError. `reconfigure` is not enough once the
    stream is already bound — wrapping the binary buffer directly is."""
    import io as _io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        # `or ""` twice, because a stream can carry `encoding = None` — an
        # in-memory one substituted by a caller, which is what a hook invoked
        # from inside another process looks like. Crashing there would take
        # down a run over the encoding of a message nobody is reading.
        if stream is None or (getattr(stream, "encoding", "") or "").lower().startswith("utf"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            if (stream.encoding or "").lower().startswith("utf"):
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
