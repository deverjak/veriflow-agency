"""What a run can be handed to — the two AI runners Agency drives.

Two, and they are a table in code, not a registry. A third runner is a change
to `BUILTIN`, not a migration: adding one means writing its launch shape once,
the same care a new provider took before, minus a file nobody but this
machine could read.

The launch shape is a description, not code: which flag carries the model,
which one grants a directory outside the working copy, whether the prompt goes
positionally or behind a flag.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import proc

BUILTIN: dict[str, dict] = {
    "claude": {
        "title": "Claude Code",
        "bin": "claude",
        "modelFlag": "--model",
        # RUN_DIR sits outside the worktree, and findings.json is written there.
        # Without this the agent asks for permission to write outside its
        # working directory on every single run.
        "dirFlag": "--add-dir",
        "promptFlag": None,
        # `--add-dir <directories...>` is VARIADIC: without this separator it
        # swallows the positional prompt as a second directory and the agent
        # starts with no brief at all. Verified on claude 2.1.258:
        #   claude -p --add-dir DIR "text"     → Error: Input must be provided…
        #   claude -p --add-dir DIR -- "text"  → answers
        # Nobody saw it, because the run "succeeded" with no findings.
        "promptSeparator": "--",
        # Without this the chain never moves. By its own help text `claude`
        # "starts an interactive session by default" — it does not exit once the
        # task is done, it sits on the prompt waiting for more input. So the
        # orchestrator never gets an exit code and the next member never starts.
        "unattendedPrefix": ["-p"],
        # Autonomy without authorization is not autonomy. `-p` makes the agent
        # a non-interactive process, but the permission model stays "ask" — and
        # there is nobody to ask. Probed on claude 2.1.258:
        #   -p --add-dir DIR "write DIR/x.txt"                    → Write DENIED
        #   -p --permission-mode acceptEdits --add-dir DIR "…"    → written
        #   -p --allowedTools "Write(//C:/…/**)" --add-dir DIR    → Write DENIED
        # A path-scoped Write rule therefore does not work on Windows;
        # `acceptEdits` does, and it is also the right shape: the worktree is
        # throwaway and RUN_DIR is a directory we handed the agent ourselves.
        "editsGrant": ["--permission-mode", "acceptEdits"],
        # `acceptEdits` grants Write/Edit, not commands. `agency triage`,
        # `code-review-graph query` and `npx vitest` are all refused without
        # this — and an agent that cannot decide on a finding is not a second
        # specialist, it is a spectator.
        "allowFlag": "--allowedTools",
        # Two shapes per command: with arguments and bare. Probed —
        # `Bash(git status *)` on its own does not cover a bare `git status`.
        "allowShapes": ["Bash({cmd} *)", "Bash({cmd})"],
        "bypassArgs": ["--dangerously-skip-permissions"],
        # Continuing a session that already happened. `claude --resume <id>`
        # takes the id the stream reported as `session_id` and starts where it
        # stopped — which is what makes a follow-up question a follow-up and
        # not a second run with none of the context. Verified against
        # `claude --help` (2.1.258): `-r, --resume [value]`.
        "resumeShape": ["--resume", "{session}"],
        # Remote Control: an interactive session the Claude app can drive.
        # `--remote-control [name]` per its own help — "Start an interactive
        # session with Remote Control enabled (optionally named)". The name is
        # how the session is recognised in the app, so the core always names it.
        "remoteControlFlag": "--remote-control",
        # What an interactive session asks BEFORE it starts, when the project
        # has an `.mcp.json` whose servers nobody has decided about yet:
        #
        #   New MCP server found in this project: <name>
        #   ❯ Continue without using this MCP server
        #
        # Probed on 2026-09-05 by reading the child's own console: bare
        # `claude` stops on that dialog and never reaches Remote Control, so a
        # session started from a phone hangs on a question nobody is there to
        # answer. `--strict-mcp-config` ("only use MCP servers from
        # --mcp-config") makes the question moot — the session comes straight
        # up, with the project's MCP servers off. That is the honest trade: a
        # session nobody can ask starts with less, rather than not at all.
        "noQuestionsArgs": ["--strict-mcp-config"],
        # The OTHER question, and this one has no flag: a directory Claude Code
        # has never been opened in gets "Is this a project you trust?", which
        # `--dangerously-skip-permissions` does not skip either (probed) — it
        # is skipped only in non-interactive mode. The answer is recorded per
        # directory in this file, so it can be read in advance and a session
        # that would hang can be refused with a reason instead.
        "trustFile": ".claude.json",
        # Can a hook, handed in on the launch line, be trusted to fire every
        # single time with nobody there to answer a question about it? Probed
        # on 2026-09-06 on claude 2.1.263, in a directory `claude` had never
        # opened before:
        #   -p --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command",
        #      "command":"echo FIRED > hookfired.txt"}]}]}}' "Say only: done"
        #   → prints "done", exit 0, hookfired.txt contains FIRED
        # No directory-trust dialog (expected — `-p` skips it per its own
        # `--help` text) and, more importantly, no separate "review this
        # hook" dialog either — unlike `noQuestionsArgs`/`trustFile` above,
        # nothing had to be bought here, the hook just ran. A Stop hook that
        # exits 2 is not a one-shot warning: fed a real `findings.json` write
        # (granted via `editsGrant`) and a hook that fails once with "missing
        # field 'score'" on stderr, the agent read that stderr, rewrote the
        # file to add the field, and stopped again — the hook's own stdin
        # payload carries `"stop_hook_active": true` on that second call,
        # which is the field to key Krok 7's two-block guard on instead of
        # the run counting its own calls. `--strict-mcp-config` and
        # `--setting-sources` do not interact: a project's
        # `.claude/settings.json` Stop hook fired identically with
        # `--setting-sources project` in a fresh `git worktree` and in the
        # main checkout, `--strict-mcp-config` present or not; `--setting-
        # sources local` (no `project`) correctly suppressed it in both.
        # A `PostToolUse` hook goes down the same path and its stdin payload
        # carries `tool_input.command` — the literal command line, not just
        # `tool_name` — which is the whole basis of evidence provenance.
        # There is no `exitCode` in it; what it has is `tool_response`
        # (`stdout`/`stderr`/`interrupted`) and `duration_ms`. And a hook
        # needs no environment variable to find the run: the path is baked
        # into the hook's own command string when `--settings` is built.
        "supportsHooks": True,
        # `--settings <file-or-json>` — "Path to a settings JSON file OR a
        # JSON string" (`--help`, 2.1.263). The probe above used the inline
        # JSON-string form; nothing has to be written into the target
        # project to hand a hook over.
        "hookFlag": "--settings",
        # Confirmed by reading the actual stream, not the one-line help text:
        # with `--include-hook-events` on top of `streamArgs` below, lifecycle
        # events land as their own lines —
        #   {"type":"system","subtype":"hook_started","hook_name":...,"hook_event":...}
        #   {"type":"system","subtype":"hook_response","hook_name":...,"stdout":...,"stderr":...}
        # — 8 such lines appeared across one run with a single Stop hook
        # configured, interleaved with the assistant/tool turns.
        "hookEventsArgs": ["--include-hook-events"],
        # An event stream instead of silence. Without `--verbose`, `-p` emits
        # nothing until the very end, so ten minutes of work is indistinguishable
        # from a hung process.
        "streamArgs": ["--output-format", "stream-json", "--verbose"],
        "streamDialect": "claude-stream-json",
        "extraArgs": [],
        "models": ["opus", "sonnet", "haiku"],
        # Named on purpose, rather than left to the binary. Without a model
        # flag `claude` runs on whatever the user's session happens to default
        # to that month — a run started from a row that says nothing about a
        # model would then quietly go to a model nobody chose for it. Worse,
        # the run record kept `model: null`, so "which model produces better
        # findings" — a question this tool is supposed to answer with numbers —
        # had a bucket full of unknowns.
        #
        # Sonnet, because it is the ordinary run; a method worth more says so
        # in its own `--model`, in a preset, or in the question the extension
        # asks on a specialist's first run.
        "defaultModel": "sonnet",
    },
    "codex": {
        "title": "Codex CLI",
        "bin": "codex",
        "modelFlag": "--model",
        # `codex exec --add-dir <DIR>` is an "additional directory that should
        # be WRITABLE alongside the primary workspace" (help of 0.144.3) — the
        # same thing claude needs for a RUN_DIR outside the worktree.
        "dirFlag": "--add-dir",
        "promptFlag": None,
        # Nothing variadic stands before the prompt, so no separator is needed
        # — and an unverified `--` against someone else's parser is a risk, not
        # a precaution.
        "promptSeparator": None,
        # `codex exec` is a subcommand, not a flag — so it goes right after the
        # binary, not among the options.
        "unattendedPrefix": ["exec"],
        # Codex authorizes with a sandbox, not a tool list: `workspace-write`
        # allows writes into the workspace and into `--add-dir`. Network access
        # is off inside it, so `gh` would fail — hence the second flag.
        #
        # CAUTION: unlike the claude branch this is **not verified by a real
        # run**, only read off the 0.144.3 help. `agency doctor` says so.
        "editsGrant": ["--sandbox", "workspace-write",
                       "-c", "sandbox_workspace_write.network_access=true"],
        # Codex has no per-command allowlist — the sandbox decides what is
        # permitted. So an empty list here is not a gap, it is a different model.
        "allowFlag": None,
        "allowShapes": [],
        "bypassArgs": ["--dangerously-bypass-approvals-and-sandbox"],
        # `codex exec resume <SESSION_ID> [PROMPT]` — a subcommand of `exec`,
        # so it follows `unattendedPrefix` and the shape stays a list. Read off
        # the 0.144.3 help, NOT verified by a real run, like the rest of this
        # branch.
        "resumeShape": ["resume", "{session}"],
        # Codex has no Remote Control. An empty entry here is not a gap, it is
        # the answer: `agency follow --remote-control` over a codex run says so
        # instead of inventing a flag.
        "remoteControlFlag": None,
        "noQuestionsArgs": [],
        "trustFile": None,
        # Codex has the hook TYPES — `PreToolUse`, `PostToolUse`, `Stop`,
        # `SessionStart`, `SubagentStart`, `UserPromptSubmit`,
        # `PermissionRequest` all appear as literal strings inside the
        # 0.144.3 binary, wire-compatible in shape with claude's — but no
        # launch-argument equivalent to `--settings` was found: `codex
        # --help` / `codex exec --help` (0.144.3) list no such flag, and the
        # same binary strings say hooks are read from a persisted project
        # `.codex/config.toml` and gated behind hook trust — "' hooks need
        # review before they can run." — that `--dangerously-bypass-hook-
        # trust` exists specifically to skip ("DANGEROUS. Intended only for
        # automation that already vets hook sources"). Trying `codex exec -c
        # 'hooks.Stop=[]' --json "say hi"` on 2026-09-06 neither errored nor
        # produced any observable hook effect, which is not evidence either
        # way and was not pursued further — the answer does not turn on it:
        # delivering a hook here means writing a config file into the target
        # project, which is the thing R5 forbids. `supportsHooks: False`
        # records that gap, not an absence of the underlying feature.
        "supportsHooks": False,
        "hookFlag": None,
        "hookEventsArgs": [],
        "streamArgs": ["--json"],
        "streamDialect": "codex-jsonl",
        "extraArgs": [],
        "models": [],
        "defaultModel": None,
    },
}


# `needs` names commands — `git`, `gh issue view`, `python …/backlog.py` — and
# the runner wraps each one in the runner's own shell shape. A pack that does
# its work on the web needs a TOOL, not a command: `WebSearch`,
# `WebFetch(domain:karp-kv.cz)`. Claude Code's tool names are PascalCase and a
# shell command never is, so the capital letter is the whole distinction.
TOOL_RULE = re.compile(r"^[A-Z][A-Za-z]*(\(.*\))?$")


def is_tool_rule(entry: str) -> bool:
    """Is this `needs` entry a tool rule already, rather than a command?"""
    return bool(TOOL_RULE.match(str(entry).strip()))


def known() -> list[str]:
    return sorted(BUILTIN)


def spec(provider_id: str) -> dict:
    """The launch shape of a provider. Unknown name = a bare binary of that
    name — `agency run … --provider myscript` works without registering
    anything, just with a narrower launch shape (no model flag, no
    authorization, no stream)."""
    s = BUILTIN.get(provider_id)
    if s is None:
        s = {"title": provider_id, "bin": provider_id, "modelFlag": "--model",
             "dirFlag": None, "promptFlag": None, "extraArgs": [],
             "editsGrant": [], "allowFlag": None, "allowShapes": [],
             "bypassArgs": [], "streamArgs": [], "streamDialect": None,
             "resumeShape": [], "remoteControlFlag": None,
             "noQuestionsArgs": [], "trustFile": None,
             "supportsHooks": False, "hookFlag": None, "hookEventsArgs": [],
             "models": [], "defaultModel": None, "unregistered": True}
    out = dict(s)
    out["id"] = provider_id
    return out


def authorizes(provider_id: str) -> bool:
    """Can this runner start an agent that may write, without asking?

    Without it an unattended run is not autonomous, only mute: the agent works,
    the system refuses every write, and at the end it looks like it found
    nothing. Both the doctor and `agency chain` ask through here, so this shows
    up before ten minutes of silence rather than after.
    """
    s = spec(provider_id)
    return bool(s.get("editsGrant") or s.get("bypassArgs"))


def resumes(provider_id: str) -> bool:
    """Can a finished session of this runner be picked up again?

    Without it a follow-up question is a new run with none of the context — it
    would re-read the whole target to answer "and what about the second one?".
    A runner that cannot resume says so here, and the follow-up is refused
    rather than quietly turned into something else.
    """
    return bool(spec(provider_id).get("resumeShape"))


def remote_controls(provider_id: str) -> bool:
    """Can this runner start a session the phone's own app can drive?"""
    return bool(spec(provider_id).get("remoteControlFlag"))


def starts_without_asking(provider_id: str) -> list[str]:
    """Flags that keep a session from stopping on a question before it starts.

    Only for a session nobody is standing at: they buy the start by giving
    something up (for `claude`, the project's own MCP servers), and at the
    machine that trade is a loss, because there the question can just be
    answered.
    """
    return [str(x) for x in (spec(provider_id).get("noQuestionsArgs") or [])]


def trusted(provider_id: str, cwd, home=None) -> bool | None:
    """Has this runner been let into that directory? `None` = cannot tell.

    Claude Code asks about a folder it has never been opened in, and there is
    no flag to skip it — so the only way to keep a session started from a phone
    from hanging on it is to read the answer it recorded last time. That answer
    is in `~/.claude.json`, keyed by the directory with forward slashes.

    `None` rather than `False` when the file cannot be read or does not have
    the shape expected: a guess that refuses a session which would have worked
    is worse than the hang it was trying to prevent, so an unreadable answer
    lets the launch go ahead.
    """
    name = spec(provider_id).get("trustFile")
    if not name:
        return None
    path = Path(home or Path.home()) / str(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        projects = data["projects"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(projects, dict):
        return None
    key = str(cwd).replace("\\", "/").rstrip("/")
    for candidate, block in projects.items():
        if str(candidate).replace("\\", "/").rstrip("/").lower() == key.lower():
            return bool(isinstance(block, dict)
                        and block.get("hasTrustDialogAccepted"))
    return False


def authorization(provider_id: str, needs: list[str], mode: str = "grant") -> list[str]:
    """The flags that start the agent allowed to do what its method does.

    `needs` are the commands from the pack manifest (`needs`) — `agency
    triage`, `git`, `gh pr view`, `npx vitest`. The core does not translate
    them into one runner's syntax, it only fills them into that runner's shape
    (`allowShapes`); a runner that authorizes with a sandbox (codex) ignores
    the list, and that is correct rather than a gap. An entry that is a tool
    rule already (`WebSearch`, `WebFetch(domain:…)` — see `is_tool_rule`) is
    passed through untouched.

    Two modes:

      * `grant` — the default: writes into the working directory and into
        `--add-dir`, plus the listed commands. Covers what the method does.
      * `bypass` — a run-level opt-in (`--bypass`): no checks at all. The
        worktree is throwaway; the machine is not.
    """
    s = spec(provider_id)
    if mode == "bypass":
        return [str(x) for x in (s.get("bypassArgs") or [])]

    argv = [str(x) for x in (s.get("editsGrant") or [])]
    flag, shapes = s.get("allowFlag"), s.get("allowShapes") or []
    if flag and shapes and needs:
        rules: list[str] = []
        for cmd in needs:
            cmd = str(cmd).strip()
            if not cmd:
                continue
            # A tool rule goes in as it stands. Wrapping it would grant a
            # shell command called `WebSearch` that does not exist, and
            # refuse the tool the pack actually asked for.
            if is_tool_rule(cmd):
                if cmd not in rules:
                    rules.append(cmd)
                continue
            for shape in shapes:
                rule = shape.format(cmd=cmd)
                if rule not in rules:
                    rules.append(rule)
        if rules:
            # A variadic option — its values take everything up to the next
            # flag, so a positional prompt must never follow it. `launch_argv`
            # guards that with ordering; here it is enough to return the shape.
            argv += [flag, *rules]
    return argv


def streaming(provider_id: str) -> tuple[list[str], str | None]:
    """How to ask this runner for a live event stream — flags and dialect
    together, so no dialect means no flags and no flags means no dialect."""
    s = spec(provider_id)
    dialect = s.get("streamDialect")
    if not dialect:
        return [], None
    return [str(x) for x in (s.get("streamArgs") or [])], dialect


def installed(provider_id: str) -> str | None:
    """Path to the binary, or None."""
    return proc.which(spec(provider_id).get("bin") or provider_id)


def catalog() -> list[dict]:
    """Providers and the models they offer, for a client choosing between
    them before a run starts. No PATH check — `detected()` is for that,
    inside `agency doctor`; a client offering a choice does not need it."""
    return [{"id": pid, "title": s.get("title") or pid,
             "models": s.get("models") or [], "defaultModel": s.get("defaultModel")}
            for pid, s in sorted(BUILTIN.items())]


def detected() -> list[dict]:
    rows = []
    for pid, s in sorted(BUILTIN.items()):
        path = proc.which(s.get("bin") or pid)
        rows.append({
            "id": pid, "title": s.get("title") or pid, "bin": s.get("bin") or pid,
            "models": s.get("models") or [], "defaultModel": s.get("defaultModel"),
            "path": path, "installed": bool(path),
        })
    return rows
