"""What a run can be handed to — the AI runners present on this machine.

A provider is a property of the MACHINE, not of the project. Whether you have
`codex` depends on what you installed, not on which repository you happen to
have open — which is why this table lives in `~/.agency/providers.json`, next
to the project registry, and not in `.agency/`.

Two are built in because they are the two that have been exercised. A third is
added with a command, not with a commit:

    agency providers add grok --bin grok

Were this a branch in the code, every new runner would mean a release of the
tool — and that is exactly the thing the roster (`hires.py`) exists to avoid.

The launch shape is a description, not code: which flag carries the model,
which one grants a directory outside the working copy, whether the prompt goes
positionally or behind a flag. As long as a new runner fits that shape, one row
of data is enough.
"""

from __future__ import annotations

from pathlib import Path

from . import proc
from .util import read_json, write_json

# An empty `promptFlag` means a positional argument — both claude and codex.
FIELDS = ("title", "bin", "modelFlag", "dirFlag", "promptFlag", "promptSeparator",
          "unattendedPrefix", "editsGrant", "allowFlag", "allowShapes",
          "bypassArgs", "streamArgs", "streamDialect", "extraArgs",
          "models", "defaultModel")

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
        # run**, only read off the 0.144.3 help. The user's roster is entirely
        # `@claude` today; the first codex chain has to confirm it, and
        # `agency doctor` says so.
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


def path() -> Path:
    from .registry import home
    return home() / "providers.json"


def custom() -> dict[str, dict]:
    data = read_json(path(), default={"version": 1, "providers": {}})
    return data.get("providers") or {}


def load() -> dict[str, dict]:
    """The built-ins, overlaid with whatever the user added.

    An overlay, not a replacement: someone who wants claude with a different
    binary (another path, a wrapper) overrides `bin` alone and the rest of the
    launch shape stays.
    """
    merged = {k: dict(v) for k, v in BUILTIN.items()}
    for pid, over in custom().items():
        base = merged.get(pid) or {"title": pid, "bin": pid, "modelFlag": "--model",
                                   "dirFlag": None, "promptFlag": None,
                                   # `None` by default, because a foreign runner
                                   # need not know `--`. Whoever needs it sets it.
                                   "promptSeparator": None,
                                   # Empty: a foreign runner need not have an
                                   # unattended mode at all, and guessing one
                                   # means a chain that hangs on its first step.
                                   "unattendedPrefix": [],
                                   # Same for authorization: the flag a foreign
                                   # runner grants writes with cannot be guessed.
                                   # Empty = the agent will ask and nobody will
                                   # answer; `agency doctor` reports that.
                                   "editsGrant": [], "allowFlag": None,
                                   "allowShapes": [], "bypassArgs": [],
                                   # With no dialect the run goes through
                                   # `attend` — a terminal, no progress lines.
                                   # Worse, but working; a guessed stream shape
                                   # would be a parser that silently finds
                                   # nothing.
                                   "streamArgs": [], "streamDialect": None,
                                   "extraArgs": [], "models": [], "defaultModel": None}
        base.update({k: v for k, v in over.items() if k in FIELDS})
        merged[pid] = base
    return merged


def known() -> list[str]:
    return sorted(load())


def spec(provider_id: str) -> dict:
    """The launch shape of a provider. Unknown name = a binary of that name.

    An unknown name is DELIBERATELY not refused: `agency run … --provider
    myscript` should work without registering anything. Registration exists so
    a runner shows up in the picker and in the doctor, not to be mandatory.
    """
    s = load().get(provider_id)
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

    `needs` are the commands from the pack manifest (`run.needs`) —
    `agency triage`, `git`, `gh pr view`, `npx vitest`. The core does not
    translate them into one runner's syntax, it only fills them into that
    runner's shape (`allowShapes`); a runner that authorizes with a sandbox
    (codex) ignores the list, and that is correct rather than a gap.

    Three modes, because the difference between them is the user's decision:

      * `grant` — the default: writes into the working directory and into
        `--add-dir`, plus the listed commands. Covers what the method does.
      * `bypass` — a project opt-in: no checks at all. Covers what the method
        is not supposed to do as well; the worktree is throwaway, the machine
        is not.
      * `ask` — nothing is granted. An attended agent asks, an unattended one
        dies quietly; it exists so authorization can be turned off without a
        code change.
    """
    if mode == "ask":
        return []
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


def installed(provider_id: str) -> str | None:
    """Path to the binary, or None.

    This is why the roster lives in the project but availability is computed
    here: a colleague with the same repository need not have the same tools.
    """
    return proc.which(spec(provider_id).get("bin") or provider_id)


def detected() -> list[dict]:
    rows = []
    for pid, s in sorted(load().items()):
        rows.append({
            "id": pid,
            "title": s.get("title") or pid,
            "bin": s.get("bin") or pid,
            "models": s.get("models") or [],
            "defaultModel": s.get("defaultModel"),
            "builtin": pid in BUILTIN,
            "path": proc.which(s.get("bin") or pid),
        })
    for r in rows:
        r["installed"] = bool(r["path"])
    return rows


def register(provider_id: str, **fields) -> dict:
    provider_id = (provider_id or "").strip().lower()
    if not provider_id or not provider_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit(
            f"“{provider_id}” is not a usable provider id — letters, digits, - and _ only.")
    data = read_json(path(), default={"version": 1, "providers": {}})
    entry = dict((data.get("providers") or {}).get(provider_id) or {})
    entry.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
    entry.setdefault("bin", provider_id)
    entry.setdefault("title", provider_id)
    data.setdefault("providers", {})[provider_id] = entry
    data["version"] = 1
    write_json(path(), data)
    return spec(provider_id)


def forget(provider_id: str) -> bool:
    data = read_json(path(), default={"version": 1, "providers": {}})
    if provider_id not in (data.get("providers") or {}):
        return False
    data["providers"].pop(provider_id)
    write_json(path(), data)
    return True
