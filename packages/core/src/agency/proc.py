"""Wrappers over git, gh and code-review-graph.

Everything that reaches outside goes through this file — so a test has one
place to substitute, and so the Windows peculiarities (encoding) are handled
once.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass
class Result:
    ok: bool
    code: int
    stdout: str
    stderr: str

    def json(self, default: Any = None) -> Any:
        try:
            return json.loads(self.stdout)
        except (json.JSONDecodeError, ValueError):
            return default


def run(
    args: Sequence[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> Result:
    full_env = {**os.environ, **(env or {})}
    # code-review-graph draws Rich panels with box-drawing characters, which
    # die on UnicodeEncodeError in a cp1250 console. Setting this globally is
    # cheaper than remembering which call is at risk.
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        p = subprocess.run(
            list(args), cwd=str(cwd) if cwd else None, env=full_env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return Result(False, 127, "", f"{args[0]}: command not found")
    except subprocess.TimeoutExpired:
        return Result(False, 124, "", f"{args[0]}: timed out after {timeout}s")
    return Result(p.returncode == 0, p.returncode, p.stdout or "", p.stderr or "")


def which(tool: str) -> str | None:
    return shutil.which(tool)


def attend(args: Sequence[str], cwd: str | Path | None = None,
           env: dict[str, str] | None = None) -> int:
    """Run and wait — with a terminal, not a pipe. Returns the exit code.

    `run()` collects output because its caller reads it. An agent is the
    opposite: it talks to the user and waits for an answer. A pipe would turn an
    attended run into an unattended one that freezes on the first question
    nobody is there to read — which is why this process lets stdio be inherited.

    The binary goes through `which` even though CreateProcess would find it:
    CreateProcess only fills in `.exe`. On Windows `codex` is really `codex.CMD`
    and without expanding PATHEXT it ends as FileNotFoundError. Verified, not
    guessed.
    """
    exe = which(args[0]) or args[0]
    try:
        return subprocess.call([exe, *args[1:]], cwd=str(cwd) if cwd else None,
                               env={**os.environ, **(env or {})})
    except OSError:
        # The same code as `run()` uses: a shell reports an unrunnable command
        # as 127.
        return 127


def stream(args: Sequence[str], cwd: str | Path | None = None,
           env: dict[str, str] | None = None,
           on_line=None, timeout: float | None = None) -> int:
    """Run, read lines as they arrive, and return the exit code.

    The difference from `attend()` is who the audience is. `attend` gives the
    agent a terminal, because a person is talking to it. Here nobody is — it is
    a chain member — so the core takes its output and turns it into progress
    that means something (`events.py`). Without this an unattended run is mute:
    the user sees `launching claude…` and then ten minutes of nothing, whether
    the agent is working or being refused one write after another.

    `stdin=DEVNULL` on purpose. A pipe with no data makes `claude` wait three
    seconds and warn ("no stdin data received in 3s") — probed, not assumed. An
    empty input is a statement; an open pipe is not.

    Stderr is inherited. A runner's error message belongs to the user
    immediately, not after someone translates it.
    """
    exe = which(args[0]) or args[0]
    try:
        p = subprocess.Popen(
            [exe, *args[1:]], cwd=str(cwd) if cwd else None,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError:
        return 127

    deadline = (time.monotonic() + timeout) if timeout else None
    try:
        for line in p.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\r\n")
            if line and on_line:
                on_line(line)
            # The ceiling has to be checked HERE, not after the loop. A run
            # that keeps talking never reaches `p.wait`, so a timeout enforced
            # only there means "how long to wait after it stopped by itself" —
            # which is not a ceiling at all, and is exactly what a runaway
            # fuse must not be. (A run that hangs while emitting nothing still
            # blocks in this loop; catching that needs a reader thread and is
            # a different problem from a run that works too long.)
            if deadline and time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(exe, timeout or 0)
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The ceiling is time, not money: on a subscription the cost is an
        # estimate, whereas "the agent has been sitting there for two hours" is
        # a fact an orchestrator should act on.
        p.kill()
        p.wait()
        return 124
    except KeyboardInterrupt:
        # Ctrl-C in a terminal goes to the whole group, but the child need not
        # act on it — and an orphaned `claude` would keep running and keep
        # holding the worktree.
        p.kill()
        p.wait()
        raise
    finally:
        if p.stdout:
            p.stdout.close()


def kill_tree(process: subprocess.Popen, timeout: float = 5.0) -> bool:
    """Stop a child and everything it started. True if it was still alive.

    Killing the child alone is not enough for the runs this exists for. What
    gets started is `agency run`, and the agent is ITS child; on Windows the
    console window belongs to neither of them but to the group — it closes when
    the last process attached to it exits. Kill only the parent and `claude`
    keeps working in a window that now answers to nobody, which is the exact
    state this is meant to end.

    It is a kill, not a goodbye. There is no way to send Ctrl-C into another
    console's process group from here (`GenerateConsoleCtrlEvent` reaches only
    groups on the caller's own console), so whatever the agent was in the
    middle of stops there. The caller owes the user that sentence.

    The pid is safe to name because the caller still holds the Popen: an
    unwaited handle keeps Windows from handing that number to somebody else,
    so there is no window in which this kills a stranger.
    """
    if process.poll() is not None:
        return False
    if os.name == "nt":
        # taskkill walks the parent/child table — `/T` is the tree, `/F` is
        # because a console app that is waiting on input will not leave on
        # being asked.
        run(["taskkill", "/PID", str(process.pid), "/T", "/F"], timeout=30)
    else:
        # Only when the child leads its own group, which is what
        # `start_new_session=True` at spawn time buys. Without that check
        # `getpgid` answers with OUR group and the kill takes the caller with
        # it — the daemon shooting itself to stop one run.
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, AttributeError):
            process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Reaped or not, it is not coming back; a caller that waits forever
        # here is a daemon that stops answering the phone.
        pass
    return True


# ---------------------------------------------------------------- git

def git(*args: str, cwd: str | Path | None = None) -> Result:
    return run(["git", *args], cwd=cwd)


def repo_root(start: str | Path | None = None) -> Path | None:
    r = git("rev-parse", "--show-toplevel", cwd=start or Path.cwd())
    return Path(r.stdout.strip()) if r.ok else None


def head(cwd: str | Path) -> str:
    return git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


def default_branch(cwd: str | Path) -> str | None:
    r = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd)
    if r.ok:
        return r.stdout.strip().split("/", 1)[-1]
    for cand in ("main", "master"):
        if git("show-ref", "--verify", f"refs/remotes/origin/{cand}", cwd=cwd).ok:
            return cand
    return None


def remote_slug(cwd: str | Path) -> str | None:
    """owner/repo from origin, whether it is ssh or https."""
    r = git("remote", "get-url", "origin", cwd=cwd)
    if not r.ok:
        return None
    url = r.stdout.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@"):
        url = url.split(":", 1)[-1]
    elif "://" in url:
        url = url.split("://", 1)[-1].split("/", 1)[-1]
    parts = [p for p in url.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def file_unchanged(cwd: str | Path, commit: str, path: str) -> bool:
    """Has that FILE not changed between the commit and HEAD?

    Note: what decides is the file being unchanged, not whether commit == HEAD.
    Testing the whole repository would fail the anchor even for a finding on an
    untouched file.
    """
    return git("diff", "--quiet", f"{commit}..HEAD", "--", path, cwd=cwd).ok


def show_file(cwd: str | Path, commit: str, path: str) -> str | None:
    r = git("show", f"{commit}:{path}", cwd=cwd)
    return r.stdout if r.ok else None


def commit_exists(cwd: str | Path, commit: str) -> bool:
    return git("cat-file", "-e", f"{commit}^{{commit}}", cwd=cwd).ok


def browser_cache() -> str | None:
    """Where Playwright downloads browsers, if something is already there.

    The browsers are not in the project but in the user's cache — which is why
    `agency doctor` asks about them separately. They are typically missing on a
    fresh machine, and the error that causes arrives mid-session.
    """
    from pathlib import Path as _P

    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates = [override] if override and override != "0" else []
    home = _P.home()
    candidates += [
        os.environ.get("LOCALAPPDATA", "") and str(_P(os.environ["LOCALAPPDATA"]) / "ms-playwright"),
        str(home / "AppData" / "Local" / "ms-playwright"),
        str(home / "Library" / "Caches" / "ms-playwright"),
        str(home / ".cache" / "ms-playwright"),
    ]
    for c in candidates:
        if not c:
            continue
        d = _P(c)
        if d.is_dir() and any(d.iterdir()):
            return str(d)
    return None


def reachable(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Does that address answer?

    A QA session against an unreachable app is a wasted run — and one request
    ahead of time says so. 401 and 403 are fine: the app is up and only wants a
    login, which is exactly what the session is there to work through.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "agency-doctor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 400, f"{url} → HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"{url} → HTTP {e.code}"
    except Exception as e:  # network, DNS, TLS, timeout — one case for the doctor
        return False, f"{url} unreachable — {type(e).__name__}"


# ---------------------------------------------------------------- gh

def gh(*args: str, cwd: str | Path | None = None) -> Result:
    return run(["gh", *args], cwd=cwd)


PR_FIELDS = (
    "number,url,title,body,state,isDraft,author,headRefName,headRefOid,"
    "baseRefName,baseRefOid,isCrossRepository,files,additions,deletions,"
    "comments,mergedAt,mergeCommit"
)


def pr_view(cwd: str | Path, number: int | None = None) -> dict | None:
    args = ["pr", "view"]
    if number is not None:
        args.append(str(number))
    args += ["--json", PR_FIELDS]
    r = gh(*args, cwd=cwd)
    return r.json() if r.ok else None


def pr_list(cwd: str | Path, state: str = "open", limit: int = 20) -> list[dict]:
    r = gh("pr", "list", "--state", state, "--limit", str(limit),
           "--json", "number,title,state,headRefOid,mergedAt,author,updatedAt", cwd=cwd)
    return r.json(default=[]) or []


def gh_login() -> str | None:
    r = gh("api", "user", "-q", ".login")
    return r.stdout.strip() if r.ok else None


def gh_scopes() -> list[str]:
    """What the signed-in token is allowed to do.

    Asked before a run, not during one: a token without `project` reads issues
    fine and then fails on the first board write, half an hour in and after the
    agent has already decided what to post.
    """
    r = gh("auth", "status")
    m = re.search(r"[Tt]oken scopes:\s*(.+)", (r.stdout or "") + (r.stderr or ""))
    if not m:
        return []
    return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]


# ---------------------------------------------- code-review-graph

CRG = "code-review-graph"


def crg(*args: str, cwd: str | Path | None = None, timeout: int = 1800) -> Result:
    return run([CRG, *args], cwd=cwd, timeout=timeout)


def crg_version() -> str | None:
    r = crg("--version")
    return r.stdout.strip() if r.ok else None


# The graph's state is asked for by `graph.state()` — this file is a wrapper
# over a process, not the place that decides what a fresh index is.
