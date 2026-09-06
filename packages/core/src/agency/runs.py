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
import hashlib
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

from . import events, graph, instructions, outputs, packs, proc, providers
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
                bypass: bool = False,
                resume: str | None = None,
                remote_control: str | None = None,
                no_questions: bool = False,
                append_prompt: str | None = None,
                settings: str | None = None) -> tuple[list[str], dict]:
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

    `resume` continues a session the runner already had, so a follow-up
    question carries everything the first one established. `remote_control`
    names an interactive session the Claude app can drive — both are shapes
    from `providers.py`, not commands assembled here, for the same reason the
    rest of this function is a table lookup.

    `no_questions` is for a session started where nobody is standing: it adds
    the flags that stop the runner asking something before it starts. It costs
    the session something (see `providers.starts_without_asking`), which is why
    it is asked for rather than assumed.
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
    # Right after the prefix, because for codex resuming is `exec resume <id>`
    # — a subcommand of a subcommand. For claude it is an ordinary flag and the
    # position does not matter; one rule that satisfies both beats two.
    if resume and spec.get("resumeShape"):
        argv += [str(x).format(session=resume) for x in spec["resumeShape"]]
    if remote_control and spec.get("remoteControlFlag"):
        argv += [str(spec["remoteControlFlag"]), str(remote_control)]
    if no_questions:
        argv += providers.starts_without_asking(name)
    if model and spec.get("modelFlag"):
        argv += [spec["modelFlag"], model]
    # Standing text in front of the session — what the run must not have to be
    # reminded of. Takes exactly one value, so unlike the variadic flags below
    # it is safe anywhere ahead of the prompt.
    delivered = bool(append_prompt) and bool(providers.appends_system_prompt(name))
    if delivered and not _fits([*argv, append_prompt, prompt]):
        # Too long to hand over on the line. Dropping it costs the run its
        # memory of what was already rejected; keeping it costs the run
        # itself, with an error message pointing at the wrong thing.
        delivered = False
    if delivered:
        argv += [providers.appends_system_prompt(name), append_prompt]
    # Hooks travel as an argument, never as a file in the project (R5). One
    # value, so it is safe here too.
    hooked = bool(settings) and bool(spec.get("hookFlag"))
    if hooked:
        argv += [str(spec["hookFlag"]), settings]
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
    info = {"provider": name, "model": model, "bin": argv[0], "authorized": mode,
            # Whether the standing text actually went in front of the session,
            # or whether the run has to fall back on the agent reading a file.
            # Two different deliveries with two different hit rates must not
            # look like one population afterwards (R6).
            "systemPrompt": bool(delivered)}
    if remote_control and spec.get("remoteControlFlag"):
        # Recorded, because "which session in the app is this run" is a
        # question only the record can answer once the terminal is gone.
        info["remoteControl"] = str(remote_control)
    return argv, info


#: Where a run's tool calls are recorded, when the runner can carry a hook.
TOOL_CALLS = "tool-calls.jsonl"

#: Which tools can back a cited source, and which of their inputs is worth
#: keeping. A whitelist per TOOL, not per key: `tool_input` of a `Write`
#: carries the whole file, and a record of everything the agent touched would
#: be a different file with a different purpose. A tool that is not here
#: writes no row at all.
#:
#: `command` was the only one until 2026-09-06, which quietly meant that a
#: pack whose work is on the web — `ceo` reads it every run and may not write
#: a claim it cannot cite — was the one pack whose sources could never be
#: checked: `WebFetch` and `WebSearch` carry a `url` and a `query`, never a
#: `command`, so every one of their calls was dropped here.
RECORDED_TOOLS = {
    "Bash": ("command",),
    "WebFetch": ("url",),
    "WebSearch": ("query",),
}

#: Agency's own remarks about a run in progress — a loop, a flood of refusals,
#: a budget overrun. A SECOND file on purpose: `agent.jsonl` is the runner's
#: raw transcript and writing our sentences into it would corrupt the one
#: record of what the agent actually emitted. The phone's event stream reads
#: both and interleaves them, so a person watching sees the warning in the
#: feed they are already looking at rather than in a terminal they left.
NOTES = "notes.jsonl"


def note_event(run_dir: Path, text: str) -> None:
    """One remark into the run's own feed. Never fatal: a warning that takes
    the run down with it is worse than the thing it was warning about."""
    try:
        path = Path(run_dir) / NOTES
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"kind": "note", "detail": text, "at": now()},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def hook_settings(run_dir: Path, provider: str | None = None) -> str | None:
    """The `--settings` payload that makes the runner report its own tool calls.

    A hook, not a promise: `evidence[].source` is a free string, so a finding
    can cite `agency graph impact` without ever having run it and nothing
    could tell. This is what turns that claim into a fact.

    Built here and passed on the launch line — **nothing is written into the
    project and nothing is installed into the user's harness** (R5). The
    RUN_DIR is baked into the hook's own command, so the hook needs no
    environment variable to find the run it belongs to.

    `None` when the runner cannot take a hook as an argument (codex reads its
    hooks from a config file in the project, which is the thing R5 forbids).
    Probed on 2026-09-06 — see `providers.supportsHooks`.
    """
    if not providers.spec(provider or "claude").get("supportsHooks"):
        return None
    def hook(event: str) -> dict:
        return {"matcher": "*", "hooks": [{"type": "command", "command":
                f'agency hook {event} --run-dir "{posix(run_dir)}"'}]}

    return json.dumps({"hooks": {"PostToolUse": [hook("tool-call")],
                                 # The second chance. `counts.gated` is a total
                                 # loss today — the agent wrote, exited, the
                                 # gate dropped it and nobody repeats the run —
                                 # and this is the one moment its context is
                                 # still alive enough to fix it.
                                 "Stop": [hook("stop")]}})


def record_tool_call(run_dir: Path, payload: dict) -> dict | None:
    """One line of `tool-calls.jsonl`, from a PostToolUse hook's own stdin.

    The shape of what arrives is the runner's, probed on 2026-09-06 rather
    than assumed: `tool_name`, `tool_input` (whose shape is the tool's own —
    `command` for a shell call, `url` for a fetch) and `tool_response`. There
    is no exit code in it — what there is is stdout and stderr — so the time
    is added here and the outcome is not claimed.

    The input is kept under `input` rather than flat, because `command` is one
    kind of input among several and a flat row would have to grow a key per
    tool. Rows written before that change are flat and stay readable —
    `ingest.commands_run` accepts both.

    `None` for a tool that cannot back a cited source (`RECORDED_TOOLS`): a
    `Read` is not evidence that anything ran.
    """
    tool = str(payload.get("tool_name") or "")
    keys = RECORDED_TOOLS.get(tool)
    raw = payload.get("tool_input")
    if not keys or not isinstance(raw, dict):
        return None
    kept = {k: " ".join(str(raw[k]).split()) for k in keys
            if raw.get(k) is not None and str(raw[k]).strip()}
    if not kept:
        return None
    row = {"at": now(), "tool": tool, "input": kept}
    path = Path(run_dir) / TOOL_CALLS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def session_name(pack_name: str, run_id: str) -> str:
    """What the Claude app will call this session.

    The pack and the run are both in it because the app shows a list of names
    and nothing else: `agency-po-01k5m2rr` says which specialist is asking and
    which run it belongs to, and `agency findings --run 01k5m2rr` finds the
    rest. A hostname-prefixed default would say only which computer it is.
    """
    return f"agency-{pack_name}-{run_id[:8].lower()}"


def working_dir(project: Project, run: Run) -> Path:
    """Where a session of this run belongs — its worktree while there is one.

    A resumed session has to start in the directory the first one worked in:
    the transcript is full of paths from it, and `claude --resume` looks up the
    session by the directory it ran in. Once `agency cleanup` has taken the
    worktree, the project itself is the only honest answer left.
    """
    ctx = read_json(run.dir / "context.json", default={})
    wt = ctx.get("worktree")
    if wt and Path(wt).is_dir():
        return Path(wt)
    return project.root


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
#: describes the state of the index and has a CLOSED key list in run.v1, so a
#: memory stat missing from here does not land in the wrong block, it makes the
#: whole record invalid.
#:
#: That is not hypothetical: `knownSpecs` was returned by `knowledge.for_run`
#: and absent here, so every graph run in a project with specs wrote a record
#: that failed its own schema. Nothing noticed, because the gate validates
#: `finding.v1`. `test_graph_evidence.py` now checks this list against what
#: `for_run` actually returns, which is the only version of this rule that
#: cannot drift again.
MEMORY_STATS = ("knownFindings", "knownPages", "knownSpecs", "knownRejections",
                "knownHere")


def known_memory(project: Project, run: Run, files: list[str] | None = None) -> dict:
    """The project's memory for this run. Assembled by `knowledge.for_run`."""
    from . import knowledge
    return knowledge.for_run(project, run, files)


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
    stats: dict = {"changedFiles": len(files)}

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

    # Memory last, deliberately: it narrows itself to the code this run
    # touches, and the blast radius it narrows by is `impact.json` — which
    # only exists once the lines above have run.
    stats.update(known_memory(project, run, files))
    return stats


def collect_workspace_evidence(project: Project, run: Run, target: dict,
                               files: list[str]) -> dict:
    """Signal for a run without a pull request: what has been happening lately."""
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    stats: dict = {"changedFiles": len(files), **known_memory(project, run, files)}

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


#: What Windows will take as a whole command line, minus room to spare.
#: `CreateProcess` caps at 32767 characters, and going over does NOT say so:
#: probed on 2026-09-06, a 32.8 KB command line comes back as
#: `FileNotFoundError: [WinError 206]`, which reads as "the binary is not
#: there" and would send someone to `agency doctor` for an hour.
#:
#: The margin is real but not what protects us — the cap on `do-not-report.md`
#: is 40 lines, which probed at 4.4 KB, so this only ever fires if something
#: else grows unbounded. It is here so that when it does, the run loses the
#: standing text and says so, rather than failing to start with the wrong
#: error.
COMMAND_LINE_MAX = 30000


def _fits(argv: list[str]) -> bool:
    return sum(len(a) + 3 for a in argv) < COMMAND_LINE_MAX


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


#: The whole of `cost` in run.v1. The schema refuses anything else, so this
#: is what may survive from a record the agent has already written.
COST_FIELDS = ("provider", "model", "credential", "inputTokens", "outputTokens",
               "usd", "dimensions", "wallClockSeconds")


def _sum(*values) -> int | float | None:
    """Add up what is there, and stay None when nothing is.

    A follow-up continues the same run, so its turns and its cost belong to
    that run's totals. Replacing them — which is what a plain assignment does
    — would say the run cost whatever its last question cost, and the numbers
    this tool exists to produce would quietly stop adding up.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    total = sum(present)
    return round(total, 6) if any(isinstance(v, float) for v in present) else total


#: Five, not three. Taken from ECC's `LOOP_THRESHOLD` together with the reason
#: they give for it: at three it fires on legitimate retries and polling, and a
#: warning that cries wolf is a warning nobody reads by its second week.
LOOP_THRESHOLD = 5

#: Refusals of the same tool before it is worth saying out loud. Three is
#: already a pattern — a pack asking for something its `needs` does not grant
#: will keep asking, and it will not get it.
DENIAL_THRESHOLD = 3

#: How many tool calls may pass without anything appearing in RUN_DIR before
#: that is worth a line. Generous: reading a large pull request legitimately
#: takes dozens of calls before the first thing is written.
QUIET_TOOLS = 40


class Watch:
    """Three things worth saying WHILE they happen, derived from the stream
    `attend` already parses.

    None of them kills anything and none of them asks anything (§0.5 of the
    harness plan). The point is only that a twenty-minute run should not be
    the first place a person learns it spent twenty minutes in a circle.

    The counting is deliberately dumb — same tool, same arguments, in a row —
    because the alternative is a heuristic about what the agent MEANT, and a
    wrong guess here costs a false alarm on every legitimate retry loop.
    """

    def __init__(self, run_dir: Path, say=None, minutes: float | None = None,
                 started: float | None = None) -> None:
        self.run_dir = run_dir
        self.say = say or (lambda text: None)
        self.started = started if started is not None else time.monotonic()
        self.minutes = minutes
        self.over_budget = False
        self.loops = 0
        self._last: tuple | None = None
        self._same = 0
        self._said = False
        self._denied: dict[str, int] = {}
        self._tools = 0
        self._prints: set | None = None

    def _files(self) -> set:
        # `agent.jsonl` is this very stream and grows with every event, so
        # counting it as progress would mean the check can never fire.
        try:
            return {(p.name, p.stat().st_size) for p in self.run_dir.rglob("*")
                    if p.is_file() and p.name != "agent.jsonl"}
        except OSError:
            return set()

    def see(self, event) -> None:
        # Said the moment it happens rather than at the end, which is the whole
        # difference: a PO run once burned 41 minutes and decided nothing, and
        # nobody knew until it was over and the number was already spent.
        if (self.minutes and not self.over_budget
                and time.monotonic() - self.started > self.minutes * 60):
            self.over_budget = True
            self.say(f"past the {self.minutes:g} minutes this pack calls normal — "
                     f"letting it finish, it may be mid-write")

        if event.kind == "tool":
            key = (event.tool, event.detail)
            if key == self._last:
                self._same += 1
            else:
                self._last, self._same, self._said = key, 1, False
            if self._same >= LOOP_THRESHOLD and not self._said:
                self.loops += 1
                self._said = True
                self.say(f"{event.tool} has been called {self._same}x in a row with "
                         f"the same arguments — it may be stuck in a loop")

            self._tools += 1
            if self._tools % QUIET_TOOLS == 0:
                now_ = self._files()
                if self._prints is not None and now_ == self._prints:
                    self.say(f"{self._tools} tool calls and nothing written into "
                             f"RUN_DIR yet")
                self._prints = now_

        elif event.kind == "denied":
            name = event.tool or "?"
            self._denied[name] = self._denied.get(name, 0) + 1
            if self._denied[name] == DENIAL_THRESHOLD:
                self.say(f"{name} has been refused {DENIAL_THRESHOLD}x — the pack "
                         f"needs it and `needs` in pack.json does not grant it")


#: How far past its own declared budget a run has to go before it is treated
#: as a fault rather than an overrun. Three times what the pack itself called
#: normal is not a deviation any more, which is what makes this the one
#: exception to "nothing is killed on a heuristic": the number is the pack's,
#: not a guess about it.
RUNAWAY = 3


def attend(project: Project, run: Run, launch: list[str], cwd: Path,
           dialect: str | None = None, on_event=None,
           chain: dict | None = None, timeout: float | None = None,
           append: bool = False, message_file: str = "agent.md",
           budget: dict | None = None) -> dict:
    """Start the agent, wait for it, and record how it went.

    `append` is a follow-up: the session is being continued, so its stream is
    added to the run's own `agent.jsonl` rather than replacing it, and what it
    spends is added to what the run already spent. A phone watching the stream
    sees the answer arrive in the same feed — which is the whole reason a
    follow-up is part of the run instead of a new one.
    """
    env = agent_env(run, chain)
    started = time.monotonic()
    collected: list = []
    minutes = (budget or {}).get("minutes")

    def remark(text: str) -> None:
        """To the terminal AND to the run's own feed — the person who needs to
        hear it is not necessarily the one at this machine."""
        out.note(text)
        note_event(run.dir, text)

    watch = Watch(run.dir, say=remark, minutes=minutes, started=started)
    # The runaway fuse. `timeout` given explicitly still wins — a caller that
    # named a ceiling meant it.
    if timeout is None and minutes:
        timeout = minutes * 60 * RUNAWAY

    if dialect:
        raw = (run.dir / "agent.jsonl").open("a" if append else "w", encoding="utf-8")

        def line(text: str) -> None:
            raw.write(text + "\n")
            for e in events.parse(dialect, text):
                collected.append(e)
                watch.see(e)
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
    prior = rec.get("agent") or {}
    prior_denied = (prior.get("denied") or {}) if append else {}
    agent = {**prior, "exitCode": code}
    if collected:
        if summary.get("last"):
            (run.dir / message_file).write_text(str(summary["last"]).rstrip() + "\n",
                                                encoding="utf-8")
        # A resumed session keeps its id, so the follow-up after the follow-up
        # has something to resume. When the runner reports none, the id already
        # recorded is still the truth.
        agent["sessionId"] = summary.get("session") or prior.get("sessionId")
        agent["turns"] = (_sum(prior.get("turns"), summary.get("turns"))
                          if append else summary.get("turns"))
        denied = events.denial_count(collected) + (prior_denied.get("count") or 0)
        tools = list(prior_denied.get("tools") or [])
        for t in summary.get("denied") or []:
            if t not in tools:
                tools.append(t)
        agent["denied"] = {"count": denied, "tools": tools}
        # Kept even when it is zero: "this run did not loop" and "nobody was
        # watching for loops" are different facts, and only a written number
        # can tell a pack that loops every time from one that had a bad day.
        agent["loops"] = _sum(prior.get("loops"), watch.loops) if append else watch.loops
    rec["agent"] = agent
    tokens = summary.get("tokens") or {}
    # The agent writes `run.json` too, and everything in `cost` is measured
    # here rather than observed by it. Carrying its object over wholesale let
    # a run invent `cost.note`, and the record then failed the schema this
    # same tool validates it against — so only the fields run.v1 knows survive.
    # Over budget on either axis. `minutes` is measurable for every run that
    # was waited for; `turns` only for a streamed one, so an attended run is
    # simply never over on turns rather than being judged on a number it does
    # not have (R6).
    turn_budget = (budget or {}).get("turns")
    over = bool(watch.over_budget)
    if minutes and seconds > minutes * 60:
        over = True
    if turn_budget and (summary.get("turns") or 0) > turn_budget:
        over = True

    inherited = {k: v for k, v in (rec.get("cost") or {}).items() if k in COST_FIELDS}
    # A follow-up adds to the run's totals; a first run has nothing to add to.
    was = inherited if append else {}
    usd = _sum(was.get("usd"), summary.get("usd"))
    rec["cost"] = {
        **inherited,
        "provider": agent.get("provider"),
        "model": agent.get("model"),
        "credential": credential(agent.get("provider")),
        "wallClockSeconds": _sum(was.get("wallClockSeconds"), seconds),
        **({"usd": usd} if usd is not None else {}),
        **({"inputTokens": _sum(was.get("inputTokens"), tokens["input"])}
           if tokens.get("input") is not None else {}),
        **({"outputTokens": _sum(was.get("outputTokens"), tokens["output"])}
           if tokens.get("output") is not None else {}),
        **({"overBudget": True} if over else {}),
    }
    rec["finishedAt"] = now()
    run.save_record(rec)
    return {"exitCode": code, "wallClockSeconds": seconds,
            "turns": summary.get("turns"), "usd": summary.get("usd"),
            "overBudget": over,
            # 124 is what `proc.stream` returns when it stopped the agent at the
            # ceiling. The caller needs to say that rather than "exited with
            # 124", which reads like the runner crashed.
            "runaway": code == 124 and bool(timeout),
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


def free_worktree(project: Project, run: Run) -> str | None:
    """Give back the checkout a run claimed, and say which one it was.

    Only the filesystem half — the record is the caller's, because the two
    callers disagree about what the run's status should say afterwards.
    """
    ctx = read_json(run.dir / "context.json", default={})
    wt = ctx.get("worktree")
    if ctx.get("worktreeOwned") is not False and wt and Path(wt).exists():
        remove_worktree(project, Path(wt))
        return wt
    return None


def abandon(project: Project, run: Run, reason: str | None = None) -> dict:
    """Close a run whose agent is not coming back, and free its worktree."""
    rec = run.record()
    was = rec.get("status")
    rec["status"] = "abandoned"
    rec["exitReason"] = reason or "the terminal was closed before the agent finished"
    rec.setdefault("finishedAt", now())

    freed = free_worktree(project, run)
    rec.pop("worktree", None)
    run.save_record(rec)
    return {"run": run.id, "wasRunning": was == "running", "worktreeRemoved": freed}


def release(project: Project, run: Run) -> dict:
    """Take back what a finished run still holds, and leave its verdict alone.

    A Remote Control session writes how the run went and then keeps standing
    in its window until somebody closes it. Closing that window must not turn
    `ok` into `abandoned`: the run did finish, the gate did decide, and the
    only thing still claimed is the worktree. `abandon` is the other case —
    a run whose agent never got to say anything.
    """
    freed = free_worktree(project, run)
    rec = run.record()
    if "worktree" in rec:
        rec.pop("worktree")
        run.save_record(rec)
    return {"run": run.id, "wasRunning": False, "worktreeRemoved": freed}


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


def _sha256(path: Path) -> str | None:
    """What is in the file, as one number. `None` when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _evidence_given(ev: Path) -> list[dict]:
    """Every file handed over in `evidence/`, and how much of it there was.

    `items` is the length of a JSON array rather than its size, because that
    is the number that means something for memory: a run given forty known
    findings and one given none are different runs, and `bytes` alone cannot
    tell that apart from a change in formatting.
    """
    rows: list[dict] = []
    for p in sorted(ev.glob("*")) if ev.is_dir() else []:
        if not p.is_file():
            continue
        data = read_json(p, default=None) if p.suffix == ".json" else None
        rows.append({"name": p.name, "bytes": p.stat().st_size,
                     "items": len(data) if isinstance(data, list) else None})
    return rows


def context_block(run: Run, pack, wt: Path, prompt: str | None) -> dict:
    """Fingerprints of what the agent is about to be handed — run.v1 `context`.

    The independent variable. Precision is measured per pack, and until this
    existed there was nothing to measure it AGAINST: the method, the house
    rules and the memory all changed underneath the number without leaving a
    mark, so "this pack got worse in October" had no answerable form.

    Hashes rather than copies. The files are in git (`CLAUDE.md`, `SKILL.md`)
    or regenerated per run (`evidence/`), so keeping a second copy in the run
    record would grow it without adding a fact — whereas a hash is enough to
    say "the same method as run X" and, when it differs, to go and diff the
    two commits.

    Read from `wt`, not from the project root: for a worktree run the house
    rules the agent sees are the ones committed at the pull request's head,
    which is exactly the version a rewrite in that same PR would change.
    """
    ins = []
    for path in instructions.paths(wt):
        digest = _sha256(path)
        if digest:
            ins.append({"path": posix(path.relative_to(wt)), "sha256": digest,
                        "bytes": path.stat().st_size})

    skill_md = pack.skill_dir / "SKILL.md"
    digest = _sha256(skill_md)
    skill = None
    if digest:
        try:
            rel = posix(skill_md.relative_to(run.project.root))
        except ValueError:
            rel = posix(skill_md)
        others = [p for p in pack.skill_dir.rglob("*")
                  if p.is_file() and p.name not in ("SKILL.md", "pack.json")]
        skill = {"path": rel, "sha256": digest, "references": len(others)}

    return {
        "instructions": ins,
        "skill": skill,
        "evidence": _evidence_given(run.dir / "evidence"),
        "promptBytes": len(prompt.encode("utf-8")) if prompt else None,
        # Always a number, never omitted when zero. "Checked, none" and "never
        # checked" are different facts, and a field that only appears when it
        # is interesting cannot be counted across runs.
        "conflicts": len(instructions.conflicts(
            wt, {tool: [pack.name] for tool in pack.requires})),
    }


def write_context(run: Run, pack, target: dict, wt: Path,
                  files: list[str], skipped: int,
                  prompt: str | None = None, worktree_owned: bool = True,
                  provider: str | None = None, chain: dict | None = None,
                  in_worktree: bool | None = None,
                  revise: str | None = None) -> None:
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
        # The weaker delivery of the same thing. A runner whose launch line can
        # carry standing text (`claude`) gets this in front of the session and
        # never has to be told to open it; a runner that cannot (`codex`) gets
        # the path, and its SKILL.md is what makes it read it.
        # Which pack's method is being rewritten, when that is what this run
        # is. `null` for an ordinary run — the author writing a new pack does
        # not have one, and the difference decides which half of its own
        # SKILL.md the agent follows.
        "revise": ({"pack": revise,
                    "brief": "evidence/for-author.md",
                    "briefData": "evidence/for-author.json",
                    "skill": posix((run.project.skills_dir / f"agency-{revise}"))}
                   if revise else None),
        "doNotReport": (posix(Path("evidence") / knowledge.DO_NOT_REPORT)
                        if (run.dir / "evidence" / knowledge.DO_NOT_REPORT).is_file()
                        else None),
        "schemas": {"finding": "finding.v1", "run": "run.v1"},
    })

    # The same preparation, fingerprinted into the record. Here rather than in
    # its own step because this is the one moment everything the agent gets is
    # assembled and nothing has run yet — a hash taken later would be of the
    # files as the run left them, which is a different question.
    rec = run.record()
    rec["context"] = context_block(run, pack, wt, prompt)
    run.save_record(rec)


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


def feedback_policy(run: Run, finding_id: str):
    """Which vocabulary this output's feedback is judged against.

    The type is on the output, the policy is in the pack that wrote it, and
    neither is knowable from the id alone — hence the lookup. Everything
    falls back to the finding policy, so a run whose pack has been renamed or
    removed can still be triaged: losing the ability to decide on old findings
    because a pack is gone would be the worst possible way to fail.
    """
    kind = None
    try:
        for f in run.findings():
            if f.get("id") == finding_id:
                kind = f.get("type")
                break
    except Exception:
        kind = None
    try:
        pack = packs.load((run.record().get("pack") or ""), run.project)
    except (SystemExit, Exception):
        pack = None
    return outputs.policy_for(pack, kind)


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
    policy = feedback_policy(run, finding_id)
    cycle = policy.lifecycle_of(state)
    if cycle is None:
        allowed = ", ".join(policy.kinds) or "(this type takes no feedback)"
        raise SystemExit(f"Unknown state “{state}” for {policy.name}. Allowed: {allowed}")
    polarity = cycle.polarity(state)

    # A reason is asked for only where the pack named the reasons. For a
    # finding those are the five in the board's own Reason field, and the
    # requirement is the whole basis of precision; for a bet the founder did
    # not pick it out of a list, and demanding one would invent a taxonomy the
    # pack never asked for.
    if cycle.reasons:
        if polarity == "negative" and not reason:
            raise SystemExit(
                "A rejection needs a reason (--reason). Allowed: " + ", ".join(cycle.reasons)
                + "\nFree text would cost the same effort and yield no number — precision cannot be computed from it."
            )
        if reason and reason not in cycle.reasons:
            raise SystemExit(f"Unknown reason “{reason}”. Allowed: {', '.join(cycle.reasons)}")

    ev = {"kind": "decision", "findingId": finding_id, "state": state,
          "lifecycle": cycle.name, "polarity": polarity,
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
        "type": finding.get("type") or outputs.DEFAULT_TYPE,
        "state": "sent", "lifecycle": "triage", "polarity": "positive",
        "title": finding.get("title"), "severity": finding.get("severity"),
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
        "type": finding.get("type") or outputs.DEFAULT_TYPE,
        "state": "rejected", "lifecycle": ev.get("lifecycle"), "polarity": ev.get("polarity"),
        "title": finding.get("title"), "severity": finding.get("severity"),
        "dimension": finding.get("dimension"), "fingerprint": finding.get("fingerprint"),
        "anchor": finding.get("anchor"), "by": ev["by"], "reason": reason, "ref": None, "url": None,
    })
    return ev


def record_feedback(project: Project, run: Run, finding_id: str, kind: str,
                    reason: str | None = None, note: str | None = None,
                    by: str = HUMAN) -> dict:
    """What happened to an output, for a type that acts on nothing.

    `accept` and `reject` are a finding's two verbs and both do something
    besides recording: one dispatches through the pack's sink, the other
    remembers not to report the thing again. A bet has no board to be sent
    to — the founder chooses it and, months later, it worked or it did not —
    so the whole of "what happened" is the record.

    The output's `state` is deliberately NOT touched. `state` is where the
    output stands in the pipeline (candidate, held, sent, duplicate); the
    verdict is the event, and folding the two together is what made every
    verdict have to be one of five words.
    """
    ev = append_decision(run, finding_id, kind, reason=reason, note=note, by=by)
    finding = next((f for f in run.findings() if f.get("id") == finding_id), {})
    append_trail(project, {
        "id": finding_id, "runId": run.id, "pack": run.record().get("pack"),
        "type": finding.get("type") or outputs.DEFAULT_TYPE,
        "state": kind, "lifecycle": ev.get("lifecycle"), "polarity": ev.get("polarity"),
        "title": finding.get("title"), "severity": finding.get("severity"),
        "dimension": finding.get("dimension"), "fingerprint": finding.get("fingerprint"),
        "anchor": finding.get("anchor"), "by": ev["by"], "reason": reason,
        "ref": None, "url": None,
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
