"""Runs: preparation, the run record, findings, decisions.

The split everything stands on:

    .agency/runs/<run-id>/   NOT committed (evidence, transcripts) —
        run.json             the run record
        context.json         what the pack gets — prepared by the CLI, not the agent
        findings.json        findings following finding.v1
        decisions.jsonl      append-only decisions, written by the CLI and the extension
        evidence/            code-review-graph output and the project's memory

    .agency/knowledge/       COMMITTED — derived memory, see knowledge.py
        trail.jsonl          COMMITTED — append-only: what a finding became
                             and where it went, once its own run is gone

This file does the deterministic preparation, because it is testable.
Judgement is the pack's job. Mixing the two makes neither verifiable.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import events, graph, proc, providers
from .config import AGENCY_DIR, Project
from .util import out, posix, read_json, ulid, write_json

#: `sent` and `rejected` only — both terminal. Read back, older data may still
#: carry `accepted` or `deferred`; nothing writes them any more.
DECISION_STATES = ("sent", "rejected")
# The same five values as the Reason field in the GitHub Project — so the
# pack's sink needs no mapping.
REJECT_REASONS = (
    "not-reproducible", "by-design", "wrong-diagnosis",
    "duplicate-missed", "out-of-scope",
)

#: What CI already catches and a pack's own installation footprint. A core
#: constant, not a project setting — the project that needs a different set is
#: a project that changes the code, not the configuration.
SKIP_PATTERNS = [
    ".claude/skills/agency-*/**",
    "**/package-lock.json", "**/pnpm-lock.yaml", "**/yarn.lock", "**/*.lock",
    "**/__snapshots__/**", "**/*.snap",
    "**/node_modules/**", "**/dist/**", "**/build/**",
    "**/*.generated.*",
]


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


# ---------------------------------------------------------------- preparation

def _skip(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def resolve_target(project: Project, pr: int | None, latest_merged: bool) -> dict:
    """An open PR, or a merged one for a retrospective audit.

    Without the retrospective mode a pack has nothing to do on a project whose
    only pull request is already merged — which is exactly how a large part of
    the baseline corpus came to exist.
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
    """A target with no pull request — the project as it is right now.

    QA does not examine a diff, it examines a running application. The target
    is therefore the working copy: HEAD for anchors (a finding has to point at
    a line that exists on that commit) and the list of changes against the
    base branch as a hint about where to look first — not a boundary it must
    not cross. An empty change list is a normal QA outcome, not a reason to
    refuse the run.
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
        # Its own records excluded from the listing. `.agency/` changes with
        # every run, so a run would otherwise show up as a change it made itself.
        return bool(path) and not path.endswith("/") and not path.startswith(AGENCY_DIR + "/")

    files: list[str] = []
    if base and base != head:
        r = proc.git("diff", "--name-only", base, cwd=project.root)
        if r.ok:
            files = [line.strip() for line in r.stdout.splitlines() if keep(line.strip())]

    # Work in progress belongs inside: the application QA tries runs over the
    # working copy, not over the last commit. `-uall` so an untracked directory
    # comes back as a list of files, not one entry "foo/".
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


def review_marker(pack: str, head: str, provider: str | None = None) -> str:
    """The marker that says a commit has already been handled.

    It carries the provider, not just the pack. Without that a second provider
    reviewing the same commit would hit the first one's mark and refuse to
    start — and the whole point of two specialists over one pull request would
    collapse.
    """
    who = f":{provider}" if provider else ""
    return f"<!-- agency:{pack}{who}:{head} -->"


def already_reviewed(target: dict, pack: str = "review-graph",
                     provider: str | None = None) -> bool:
    """Idempotence through a marker carrying the head commit — the same commit
    is not reviewed twice by the same provider. A different one may."""
    markers = [review_marker(pack, target["headRefOid"], provider)]
    if provider:
        markers.append(review_marker(pack, target["headRefOid"]))
    bodies = [c.get("body") or "" for c in target.get("_comments", [])]
    return any(m in b for m in markers for b in bodies)


def launch_argv(memory_dir: str, prompt: str,
                provider: str | None = None,
                model: str | None = None,
                unattended: bool = False,
                needs: list[str] | None = None,
                stream: bool = False,
                bypass: bool = False) -> tuple[list[str], dict]:
    """What to finish the run with.

    `memory_dir` is what the agent is allowed to read outside its working
    directory — the project's `.agency/`. For a long time only RUN_DIR went
    there, but `context.json` also sends the specialist elsewhere: into the
    `knowledge` bundle, into the pack's pages, and in a chain into upstream
    runs.

    The model is a property of the task, not of the user: keep coding on the
    strongest one and run reviews cheaper. The choice goes into the run
    record, because "which model produces better findings" is a question
    this tool is supposed to answer with numbers.
    """
    name = provider or "claude"
    spec = providers.spec(name)
    if model is None:
        model = spec.get("defaultModel")

    argv = [spec.get("bin") or name]
    # Unattended mode is what makes a chain a chain: `claude` and `codex` both
    # otherwise start an interactive session that does NOT end when the task is
    # done. The prefix goes right after the binary, since for codex it is a
    # subcommand (`exec`), not a flag.
    if unattended:
        argv += [str(x) for x in (spec.get("unattendedPrefix") or [])]
    if model and spec.get("modelFlag"):
        argv += [spec["modelFlag"], model]
    argv += [str(x) for x in (spec.get("extraArgs") or [])]

    # Authorization: handing the agent a path without the right to use it is a
    # bug, not caution. `allowFlag` is variadic just like `--add-dir`, so
    # another FLAG has to follow it — that flag is `dirFlag` below, or the
    # stream flags, or the prompt separator; never the prompt itself.
    mode = "bypass" if bypass else "grant"
    auth = providers.authorization(name, list(needs or []), mode)

    stream_args = providers.streaming(name)[0] if stream else []

    if (auth and spec.get("allowFlag") in auth
            and not stream_args and not spec.get("dirFlag")):
        auth = auth[:auth.index(spec["allowFlag"])]
    argv += auth
    argv += stream_args

    if spec.get("dirFlag"):
        argv += [spec["dirFlag"], memory_dir]
    if spec.get("promptFlag"):
        argv += [spec["promptFlag"], prompt]
    else:
        if spec.get("promptSeparator"):
            argv.append(spec["promptSeparator"])
        argv.append(prompt)
    return argv, {"provider": name, "model": model, "bin": argv[0],
                  "authorized": mode}


# The provider is in the path on purpose. Two specialists over one pull
# request is the reason a project might hire both `claude` and `codex` on the
# same pack — with a shared path the second run would delete the first one's
# worktree in the middle of its work.
WORKTREE_TEMPLATE = "../{repo}-review-pr-{n}-{provider}"


def worktree_path(project: Project, target: dict, provider: str | None = None) -> Path:
    """Where the worktree will be built. Computed separately so a run can
    record the path BEFORE it takes it — the guard below rests on that."""
    name = WORKTREE_TEMPLATE.format(
        repo=project.root.name, n=target.get("pr") or "x", provider=provider or "agent")
    return (project.root / name).resolve()


def worktree_owner(project: Project, wt: Path, exclude: str | None = None) -> str | None:
    """Which running run is holding this directory.

    Without this a parallel run by a second provider would silently
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


def make_worktree(project: Project, target: dict, provider: str | None = None,
                  run: "Run | None" = None) -> Path:
    """A throwaway worktree on the pull request's head.

    Never checked out into the user's working copy — their branch and work in
    progress stay untouched.
    """
    wt = worktree_path(project, target, provider)
    if wt.exists():
        busy = worktree_owner(project, wt, exclude=run.id if run else None)
        if busy:
            raise SystemExit(
                f"{posix(wt)} is still held by the running run {busy[:10]}.\n"
                "Two specialists on the same pull request need two worktrees — this "
                "one is already named after its provider, so finish the other run first.")
        proc.git("worktree", "remove", str(wt), "--force", cwd=project.root)
    r = proc.git("fetch", "origin", f"pull/{target['pr']}/head", cwd=project.root)
    if not r.ok:
        # a merged PR with its branch deleted — the head is usually reachable anyway
        proc.git("fetch", "origin", target["headRefOid"], cwd=project.root)
    ref = "FETCH_HEAD" if r.ok else target["headRefOid"]
    r = proc.git("worktree", "add", "--detach", str(wt), ref, cwd=project.root)
    if not r.ok:
        raise SystemExit(f"The worktree could not be created:\n{r.stderr.strip()}")
    return wt


#: Where a team's shared checkout lives. Named after the chain, not after a
#: provider: several members work in it and none of them owns it.
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
    """Copies the pack's skill (`.claude/skills/agency-<name>/`) into the worktree.

    A worktree is a clean checkout of the pull request's head — it only sees
    what is committed. The pack's skill is typically not committed (nothing
    of Agency belongs in the target project's own repository) and should not
    be. Without this step the method simply is not found in the worktree and
    the run ends on "Unknown skill".
    """
    try:
        rel = pack.skill_dir.relative_to(project.root)
    except ValueError:
        return []
    src = project.root / rel
    if not src.is_dir():
        return []
    dst = wt / rel
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    copied = [posix((p.relative_to(wt)))
              for p in sorted(dst.rglob("*")) if p.is_file()]

    if copied:
        # So the copied files do not look like a change the PR brought in.
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


def prepare_graph(project: Project, wt: Path) -> dict:
    """The index for this run."""
    src = project.root / graph.DB_PATH
    info = graph.prepare(src, wt, "update")
    info["driver"] = graph.DRIVER
    info["capabilities"] = graph.capabilities()
    return info


#: Which of the collected stats is memory, not graph signal. Gathered during
#: the same preparation, but it belongs elsewhere in the run record — `graph`
#: describes the state of the index.
MEMORY_STATS = ("knownFindings", "knownPages")


def known_memory(project: Project, run: Run) -> dict:
    """The project's memory for this run. Assembled by `knowledge.for_run`."""
    from . import knowledge
    return knowledge.for_run(project, run)


def _graph_evidence(ev: Path, name: str, answer: graph.Answer) -> None:
    """What the driver actually said, into evidence — and when it said nothing, let that show."""
    if not answer.ok:
        (ev / f"{name}.error.txt").write_text(answer.error or "no output", encoding="utf-8")
    elif answer.raw is not None:
        write_json(ev / f"{name}.json", answer.raw)


def collect_evidence(project: Project, wt: Path, run: Run, target: dict,
                     files: list[str]) -> dict:
    """Graph signal. This is the part a plain diff cannot give."""
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {"changedFiles": len(files), **known_memory(project, run)}

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
                               files: list[str]) -> dict:
    """Signal for a run without a pull request: what has been happening lately."""
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


def method_hint(pack, project: Project, carried: list[str], in_worktree: bool) -> str:
    """How the agent gets to the pack's method."""
    skill_md = pack.skill_dir / "SKILL.md"
    present = (any(str(c).endswith("SKILL.md") for c in carried) if in_worktree
               else skill_md.is_file())
    if present:
        return f"Use the {pack.skill_name} skill."
    try:
        rel = posix(skill_md.relative_to(project.root))
    except ValueError:
        rel = posix(skill_md)
    return f"Read the method in {posix(project.root)}/{rel}."


def start(project: Project, pack_name: str, target: dict,
          trigger: str = "manual", provider: str | None = None,
          attended: bool = True, origin: str = "cli",
          device: str | None = None) -> Run:
    run_id = ulid()
    run = Run(run_id, project.runs_dir / run_id, project)
    run.dir.mkdir(parents=True, exist_ok=True)
    run.save_record({
        "id": run_id,
        "pack": pack_name,
        "agent": {"provider": provider} if provider else {},
        "project": {"slug": project.slug, "defaultBranch": project.default_branch},
        "target": {k: v for k, v in target.items() if not k.startswith("_")},
        # Attendedness is a fact about the process, not a wish: it says whether
        # anyone could step into this run at all, which is what decides whether
        # a question the agent asks can ever be answered. A chain member runs
        # with nobody able to enter it, and that is what gets written.
        #
        # `origin` is a different question — where the person was standing when
        # they asked. It is written every time, including the ordinary `cli`,
        # because a field that only appears when the answer is interesting
        # cannot be counted.
        "trigger": {"kind": trigger, "attended": attended, "origin": origin,
                    **({"device": device} if device else {})},
        "startedAt": now(),
        "status": "running",
    })
    return run


#: How an agent's own run recognises itself. `cmd_run` and `cmd_chain` read
#: these and refuse to start — a run is a leaf, not a node.
RUN_ENV = "AGENCY_RUN"
CHAIN_ENV = "AGENCY_CHAIN"

#: How to tell what paid for a run. A key present in the runner's environment
#: is a fact; `trigger.attended` is the caller's intent, and `claude -p` proves
#: it wrong — unattended and still running on the subscription.
API_KEY_ENV = {"claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
               "codex": ("OPENAI_API_KEY",)}


#: Blocks in a run record whose keys `run.v1` closes.
CLOSED_BLOCKS = {
    "chain": ("id", "position", "of", "upstream"),
}


def repair_record(run: Run) -> list[str]:
    """Drop what `run.v1` does not know, and say what was dropped."""
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
    """A run does not start runs."""
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
    """Start the agent, wait for it, and record how it went."""
    env = agent_env(run, chain)
    started = time.monotonic()
    collected: list = []

    if dialect:
        raw = (run.dir / "agent.jsonl").open("w", encoding="utf-8")

        def line(text: str) -> None:
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
        if summary.get("last"):
            (run.dir / "agent.md").write_text(str(summary["last"]).rstrip() + "\n",
                                              encoding="utf-8")
        agent["sessionId"] = summary.get("session")
        agent["turns"] = summary.get("turns")
        denied = events.denial_count(collected)
        agent["denied"] = {"count": denied, "tools": summary.get("denied") or []}
    rec["agent"] = agent
    tokens = summary.get("tokens") or {}
    rec["cost"] = {
        **(rec.get("cost") or {}),
        "provider": agent.get("provider"),
        "model": agent.get("model"),
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
    """A run whose agent ended in error."""
    rec = run.record()
    rec["status"] = "failed"
    rec["exitReason"] = reason
    rec.setdefault("finishedAt", now())
    run.save_record(rec)
    return {"run": run.id, "status": "failed", "exitReason": reason}


def unfinished(project: Project) -> list[Run]:
    """Runs still marked as running."""
    return [r for r in load_runs(project) if r.record().get("status") == "running"]


def abandon(project: Project, run: Run, reason: str | None = None) -> dict:
    """Close a run whose agent is not coming back, and free its worktree."""
    rec = run.record()
    was = rec.get("status")
    rec["status"] = "abandoned"
    rec["exitReason"] = reason or "the terminal was closed before the agent finished"
    rec.setdefault("finishedAt", now())

    freed = None
    ctx = read_json(run.dir / "context.json", default={})
    wt = ctx.get("worktree")
    if ctx.get("worktreeOwned") is not False and wt and Path(wt).exists():
        remove_worktree(project, Path(wt))
        freed = wt
    rec.pop("worktree", None)
    run.save_record(rec)
    return {"run": run.id, "wasRunning": was == "running", "worktreeRemoved": freed}


def discard(project: Project, run: Run, force: bool = False) -> dict:
    """Delete a run outright — record, evidence and all."""
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


def write_context(run: Run, pack, target: dict, wt: Path,
                  files: list[str], skipped: int,
                  prompt: str | None = None, worktree_owned: bool = True,
                  provider: str | None = None, chain: dict | None = None,
                  in_worktree: bool | None = None) -> None:
    from . import knowledge  # circular import: `knowledge` stands on `runs`

    if in_worktree is None:
        in_worktree = worktree_owned

    write_json(run.dir / "context.json", {
        "runId": run.id,
        "runDir": posix(run.dir),
        "project": {"root": posix(run.project.root), "slug": run.project.slug},
        # The project's committed memory. Absolute on purpose: the bundle is
        # part of the repository, so it exists in a worktree on the PR's head
        # too — but at the version from that commit. A relative path would send
        # the specialist to read an older
        # memory than the project actually has.
        "knowledge": posix(run.project.agency_dir / knowledge.BUNDLE),
        # Where the pack writes its own conclusions. `null` for a run inside a
        # worktree — it stands on the pull request's head and the tool deletes
        # it afterwards.
        "pages": (posix(knowledge.pages_dir(run.project, pack.name))
                  if not in_worktree else None),
        "worktree": posix(wt),
        "worktreeOwned": worktree_owned,
        "target": {k: v for k, v in target.items() if not k.startswith("_")},
        "files": files,
        "filesSkipped": skipped,
        "prompt": prompt,
        # What to sign a decision with (`agency triage … --by <by>`).
        "by": f"hire:{worker_id(pack.name, provider)}",
        "prCommentMarker": (review_marker(pack.name, target["headRefOid"], provider)
                            if target.get("pr") else None),
        "chain": ({**{k: chain[k] for k in ("id", "position", "of", "upstream")
                      if k in chain},
                   "upstreamFile": "evidence/upstream.json",
                   "handoffFile": "handoff.md"} if chain else None),
        "review": {"dimensions": [d.get("id") for d in pack.dimensions],
                   "minScore": pack.min_score},
        "schemas": {"finding": "finding.v1", "run": "run.v1"},
    })


# ---------------------------------------------------------------- trail

#: Committed, append-only. One line per finding per state change that
#: matters once a finding leaves its own run — `sent`, `rejected` or
#: `gated-out`. `candidate`, `held` and `duplicate` never appear here: they
#: are not terminal and the run directory they live in is still the truth.
TRAIL = "trail.jsonl"


def trail_path(project: Project) -> Path:
    return project.agency_dir / "knowledge" / TRAIL


def append_trail(project: Project, row: dict) -> dict:
    row = {"at": now(), **row}
    path = trail_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read_trail(project: Project) -> dict[str, dict]:
    """Every finding the trail remembers, by id — the last line for an id
    wins, same replay rule as `decisions()`. A broken line is skipped, not
    fatal: the trail is committed text, and a hand-merge conflict marker left
    behind should not take the whole file down."""
    path = trail_path(project)
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            fid = row.get("id")
            if fid:
                out[fid] = row
    return out


# ---------------------------------------------------------------- decisions

#: A person. Optionally `human:<name>`, when a project has more than one.
HUMAN = "human"

#: The chain itself, deciding by NOT deciding: a chain that ends still sends
#: whatever an upstream member left `held` and nobody judged. Not a hire and
#: not a human — `metrics.py` counts precision only from `hire:*`, so a
#: `chain` decision never inflates it, the same way a `human` one never did.
CHAIN = "chain"

#: Until 2026-09-01 the CLI wrote `cli` and the extension wrote `vscode`. Read
#: back as a person — history is not rewritten, only interpreted.
LEGACY_BY = {"cli": HUMAN, "vscode": HUMAN, "extension": HUMAN}

#: The shape of a worker's identity: `hire:<id>`. With no roster it is just a
#: naming convention (`pack@provider`), not a pointer into a file.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9@.:_-]*$")


def normalize_by(value: str | None) -> str | None:
    """How what was ever written is read today. Nothing written is `None`."""
    v = (value or "").strip()
    return LEGACY_BY.get(v, v) or None


def validate_by(value: str | None) -> str:
    """The shape of an identity is checked on write, because trust tiers are computed from attribution."""
    v = normalize_by(value) or ""
    if v == HUMAN or v == CHAIN or (v.startswith("human:") and v[len("human:"):].strip()):
        return v
    if v.startswith("hire:") and ID_RE.match(v[len("hire:"):]):
        return v
    raise SystemExit(
        f"Unknown identity “{value}”. Use `hire:<id>` for a specialist — the "
        f"ready-made value is in context.json under `by` — or `human` / "
        f"`human:<name>` for a person."
    )


def worker_id(pack_name: str, provider: str | None = None) -> str:
    """Who did this run — `pack@provider`."""
    return f"{pack_name}@{provider or 'claude'}"


def append_decision(run: Run, finding_id: str, state: str,
                    reason: str | None = None, note: str | None = None,
                    by: str = HUMAN, ref: str | None = None,
                    url: str | None = None) -> dict:
    """An append-only event.

    A decision is NOT a UI command. The extension and an agent both write here
    through the same path — if it were an editor command, an agent could not
    triage at all.

    `ref`/`url` carry where a `sent` decision landed — the board item, from
    the pack's sink. Absent for `rejected`, which never reaches a board.
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
          "reason": reason, "note": note, "by": validate_by(by), "at": now(),
          "ref": ref, "url": url}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def append_note(run: Run, finding_id: str, text: str, by: str = HUMAN) -> dict:
    """A note is NOT a decision."""
    text = (text or "").strip()
    if not text:
        raise SystemExit("Empty note. Write something, or write nothing at all.")
    ev = {"kind": "note", "findingId": finding_id, "text": text,
          "by": validate_by(by), "at": now()}
    with open(run.decisions_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def _set_finding_state(run: Run, finding_id: str, **fields) -> dict | None:
    """Mutates one finding in `findings.json` in place and persists it.
    Returns the updated finding, or `None` when the id is not in this run."""
    fs = run.findings()
    updated = None
    for f in fs:
        if f.get("id") == finding_id:
            f.update(fields)
            updated = f
            break
    if updated is not None:
        write_json(run.findings_path, fs)
    return updated


def dispatch(project: Project, run: Run, finding: dict, by: str) -> dict:
    """Sends one gated finding through its pack's sink onto the board.

    `run` is whichever run owns the finding — its own run for a candidate
    that reached the end of the pipeline, or an upstream run's for a `held`
    finding nobody in the chain decided on. Without a sink (a project with no
    board) this does nothing at all: the finding stays `candidate`, which is
    exactly the git-only fallback the pack's absence of a `sink` means.

    On success the finding becomes `sent`, `sinks.githubProjectItem` carries
    the board reference, and a `sent` event lands in both `decisions.jsonl`
    and the committed trail. On failure — a non-zero exit, a timeout, or a
    sink that did not print JSON — the finding stays `candidate` and the
    caller records the error; a later `agency ingest` tries again, and the
    sink's own idempotence marker keeps a retry from posting twice.
    """
    by = validate_by(by)
    fid = finding.get("id")

    from . import packs
    try:
        pack = packs.load(run.record().get("pack") or "", project)
    except SystemExit:
        pack = None
    sink = pack.sink if pack else None
    if not sink:
        return {"id": fid, "ok": False, "noSink": True, "ref": None, "url": None, "error": None}

    cmd = shlex.split(sink.format(id=fid, runDir=posix(run.dir)))
    try:
        result = subprocess.run(
            cmd, cwd=project.root, env={**os.environ, RUN_ENV: run.id},
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return {"id": fid, "ok": False, "noSink": False, "ref": None, "url": None, "error": str(e)}

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()[:400] or f"exit {result.returncode}"
        return {"id": fid, "ok": False, "noSink": False, "ref": None, "url": None, "error": error}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"id": fid, "ok": False, "noSink": False, "ref": None, "url": None,
                "error": "the sink printed no readable JSON"}

    ref = data.get("item") or data.get("ref")
    url = data.get("url")

    _set_finding_state(run, fid, state="sent",
                       sinks={**(finding.get("sinks") or {}), "githubProjectItem": ref})
    append_decision(run, fid, "sent", by=by, ref=ref, url=url)
    append_trail(project, {
        "id": fid, "runId": run.id, "pack": run.record().get("pack"),
        "state": "sent", "title": finding.get("title"), "severity": finding.get("severity"),
        "dimension": finding.get("dimension"), "fingerprint": finding.get("fingerprint"),
        "anchor": finding.get("anchor"), "by": by, "ref": ref, "url": url, "reason": None,
    })
    return {"id": fid, "ok": True, "noSink": False, "ref": ref, "url": url, "error": None}


def reject(project: Project, run: Run, finding_id: str, reason: str,
          note: str | None = None, by: str = HUMAN) -> dict:
    """A finding the next specialist in a chain judged untrue. Terminal — it
    never reaches the board, and the trail remembers not to report it again."""
    ev = append_decision(run, finding_id, "rejected", reason=reason, note=note, by=by)
    finding = _set_finding_state(run, finding_id, state="rejected") or {}
    append_trail(project, {
        "id": finding_id, "runId": run.id, "pack": run.record().get("pack"),
        "state": "rejected", "title": finding.get("title"), "severity": finding.get("severity"),
        "dimension": finding.get("dimension"), "fingerprint": finding.get("fingerprint"),
        "anchor": finding.get("anchor"), "by": ev["by"], "reason": reason, "ref": None, "url": None,
    })
    return ev


def history(run: Run) -> dict[str, list[dict]]:
    """All events by finding, in write order — decisions and notes alike."""
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
    """Current state = replaying the events. The last write to an id wins."""
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
