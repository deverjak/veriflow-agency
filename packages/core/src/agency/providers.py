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
        # An event stream instead of silence. Without `--verbose`, `-p` emits
        # nothing until the very end, so ten minutes of work is indistinguishable
        # from a hung process.
        "streamArgs": ["--output-format", "stream-json", "--verbose"],
        "streamDialect": "claude-stream-json",
        "extraArgs": [],
        "models": ["opus", "sonnet", "haiku"],
        "defaultModel": None,
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
        "streamArgs": ["--json"],
        "streamDialect": "codex-jsonl",
        "extraArgs": [],
        "models": [],
        "defaultModel": None,
    },
}


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


def authorization(provider_id: str, needs: list[str], mode: str = "grant") -> list[str]:
    """The flags that start the agent allowed to do what its method does.

    `needs` are the commands from the pack manifest (`needs`) — `agency
    triage`, `git`, `gh pr view`, `npx vitest`. The core does not translate
    them into one runner's syntax, it only fills them into that runner's shape
    (`allowShapes`); a runner that authorizes with a sandbox (codex) ignores
    the list, and that is correct rather than a gap.

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
