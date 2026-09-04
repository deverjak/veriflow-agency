"""`agency serve` — the third client: a phone on the same tailnet.

The extension is a viewer that talks only to `agency … --json`
([`cli.js`](../../../extension/src/cli.js)). This is the same thing over HTTP,
for the case where the person is not at the machine: the PC is running, the
project is activated, and a specialist should start now rather than tonight.

**The daemon has no judgement of its own.** It authenticates a device, knows
which projects are activated, and hands everything else to `agency` as a
subprocess — the same binary, the same flags, the same JSON. Nothing here
decides what a pack is, what a finding is worth, or how a run is prepared. If
this file ever needs to know one of those things, the answer belongs in the
core and this file should be asking for it.

Three properties it does not get to be talked out of:

* **It listens on the loopback.** What publishes it to the tailnet is
  `tailscale serve`, which terminates TLS and knows who is on the other end.
  Binding `0.0.0.0` would put an authorization surface written in an afternoon
  in front of the whole home network instead.
* **A device is a credential, not a setting.** Tokens live outside the project
  (a token in `.agency/` is a token in a pull request) and every remote action
  is appended to `remote.jsonl` next to them.
* **A run started from a phone is unattended by construction.** Nobody is at
  the terminal to answer the agent, so the only mode this step implements is
  the one that does not ask. Taking over an attended session from the phone is
  the Remote Control step of `docs/plans/remote.md`, and it is deliberately not
  here yet.
"""

from __future__ import annotations

import dataclasses
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config, events, packs, providers, runs
from .util import out, posix, read_json, write_json

#: How long after startup a phone can still pair. The plan said 60 s; a minute
#: is not enough to unlock a phone, open a browser and type a code, and a
#: window that expires while you are typing gets reopened by restarting the
#: daemon — which is worse than a window measured in minutes.
PAIR_WINDOW = 300

#: Wrong codes before the window closes for good. Six digits is a million, so
#: this is not about entropy — it is about a script on the tailnet not getting
#: unlimited tries at the one number that matters.
PAIR_ATTEMPTS = 5

#: How long `POST /api/run` waits for the run record to appear before it gives
#: up and reports what the subprocess printed. Preparation resolves a pull
#: request through `gh` and can build a worktree, so seconds, not milliseconds.
RUN_ID_TIMEOUT = 180

#: Silence on an SSE connection that some proxy will eventually cut.
SSE_HEARTBEAT = 20

#: How long `agency packs` is believed for. A pack changes when somebody
#: commits one; a pull-to-refresh should not cost a subprocess per project.
PACKS_TTL = 60

# A document meant to be read on a phone. The cap is not about disk: it is the
# point past which handing the whole thing to a browser stops being a kindness.
OUTPUT_MAX = 200_000


# ---------------------------------------------------------------- state

def state_dir() -> Path:
    """Where device tokens and the audit log live.

    Deliberately **not** `~/.agency/`, which this tool refuses to have, and
    deliberately not the project either. The rule that killed `~/.agency/` was
    about configuration — settings that decide how a run behaves belong in the
    project, where they can be reviewed. A device token decides nothing; it is
    a credential for one machine, and the only other place to put it is a
    committed directory, which is how secrets end up in pull requests.
    """
    override = os.environ.get("AGENCY_STATE_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        root = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(root) / "agency"


# ---------------------------------------------------------------- what it serves

#: Directories a scan never walks into. Not a policy, just the places a
#: repository is never hiding.
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "dist", "build",
             "target", "vendor", "AppData", "Library"}

#: How many directories below a scan root a repository may sit. Two, because
#: `coding/<org>/<repo>` is the layout this was written against; deeper costs
#: nothing but time.
SCAN_DEPTH = 2


@dataclass
class Selection:
    """What the daemon opens: paths named outright, plus trees to look in.

    Kept as the *question* rather than its answer — a scan stored as a list of
    paths would go stale the day a repository is cloned, and re-running it is
    milliseconds.
    """
    projects: list[str] = field(default_factory=list)
    scan: list[str] = field(default_factory=list)
    depth: int = SCAN_DEPTH

    def empty(self) -> bool:
        return not self.projects and not self.scan


def selection_path() -> Path:
    return state_dir() / "projects.json"


def load_selection() -> Selection:
    d = read_json(selection_path(), default={}) or {}
    return Selection(projects=[str(x) for x in (d.get("projects") or [])],
                     scan=[str(x) for x in (d.get("scan") or [])],
                     depth=int(d.get("depth") or SCAN_DEPTH))


def save_selection(sel: Selection) -> Path:
    write_json(selection_path(), {"projects": sel.projects, "scan": sel.scan,
                                  "depth": sel.depth})
    return selection_path()


def has_pack(root: Path) -> bool:
    try:
        return any((root / ".claude" / "skills").glob("agency-*/pack.json"))
    except OSError:
        return False


def scan_tree(root: Path, depth: int) -> list[Path]:
    """Repositories with at least one specialist, at most `depth` levels down.

    Two exclusions carry the whole thing:

    * **A worktree is not a project.** `agency run` builds throwaway worktrees
      next to the repository and copies the pack into them, so on disk
      `main-panel-review-pr-467` looks exactly like a project with a
      specialist. Its `.git` is a FILE (`gitdir: …`) rather than a directory,
      which is how git itself tells them apart, and how this does.
    * **A repository is never walked into.** Whatever is nested inside one
      belongs to it — a scan that descends finds a project's own fixtures and
      offers them as projects.
    """
    found: list[Path] = []

    def walk(d: Path, level: int) -> None:
        if level > depth:
            return
        try:
            entries = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            return                                  # unreadable is not fatal
        for p in entries:
            if p.name.startswith(".") or p.name in SKIP_DIRS:
                continue
            git = p / ".git"
            if git.exists():
                if git.is_dir() and has_pack(p):
                    found.append(p)
                continue
            walk(p, level + 1)

    walk(Path(root).expanduser(), 1)
    return found


def resolve_projects(sel: Selection) -> list[config.Project]:
    """The selection, as projects. Named ones first, then what the scan found.

    A path named outright is opened whether or not it has a specialist yet —
    the person said so. A scanned one has to have one, because a project with
    nothing to task is a row on a phone that does nothing.
    """
    roots: list[Path] = []
    for raw in sel.projects:
        p = Path(str(raw)).expanduser()
        if p.exists():
            roots.append(p)
    for tree in sel.scan:
        roots.extend(scan_tree(Path(str(tree)), sel.depth))

    out_: list[config.Project] = []
    seen: set[str] = set()
    for root in roots:
        project = config.discover(root)
        if project is None:
            continue                                # not a git repository
        key = posix(project.root).lower()
        if key in seen:
            continue
        seen.add(key)
        out_.append(project)
    return out_


def project_keys(projects: list[config.Project]) -> dict[str, config.Project]:
    """How the phone names a project. The directory, and when two projects
    share it, the directory it sits in as well — `main-panel` is worth reading
    on a small screen, `chytre-digital/main-panel` only when it has to be."""
    names: dict[str, int] = {}
    for p in projects:
        names[p.root.name] = names.get(p.root.name, 0) + 1
    keyed: dict[str, config.Project] = {}
    for p in projects:
        key = p.root.name if names[p.root.name] == 1 else f"{p.root.parent.name}/{p.root.name}"
        while key in keyed:                         # two of those too — rare, still possible
            key += "~"
        keyed[key] = p
    return keyed


@dataclass
class Device:
    id: str
    name: str
    token: str
    bypass: bool = False
    pairedAt: str | None = None


class Devices:
    """The paired phones. A flat file, because there are two of them."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items = [Device(**d) for d in read_json(path, default=[])]

    def all(self) -> list[Device]:
        return list(self._items)

    def add(self, name: str, bypass: bool) -> Device:
        d = Device(id=secrets.token_hex(4), name=name or "device",
                   token=secrets.token_urlsafe(32), bypass=bypass,
                   pairedAt=runs.now())
        self._items.append(d)
        write_json(self.path, [dataclasses.asdict(x) for x in self._items])
        return d

    def revoke(self, device_id: str) -> bool:
        keep = [d for d in self._items if d.id != device_id]
        if len(keep) == len(self._items):
            return False
        self._items = keep
        write_json(self.path, [dataclasses.asdict(x) for x in self._items])
        return True

    def find(self, token: str | None) -> Device | None:
        """Constant-time, because a token comparison that returns early is a
        token comparison that can be measured.

        Compared as bytes: `compare_digest` refuses two strings when either
        carries a character outside ASCII, and a token typed with a smart quote
        in it would then be a crash rather than a refusal.
        """
        if not token:
            return None
        candidate = str(token).encode("utf-8", "ignore")
        for d in self._items:
            if hmac.compare_digest(d.token.encode(), candidate):
                return d
        return None


def console(fn, *args) -> None:
    """Say something on the machine's console, and never let that fail a request.

    `agency serve` goes through `main()`, which wraps stdout in UTF-8 — but a
    daemon started any other way inherits a Windows console in cp1250, where
    printing the `✓` of a successful pairing raises `UnicodeEncodeError`. That
    turned a paired device into HTTP 500. The line on the console is a
    courtesy; the answer to the phone is the job.
    """
    try:
        fn(*args)
    except Exception:                               # noqa: BLE001
        pass


def append_audit(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"at": runs.now(), **entry}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- jobs

@dataclass
class Job:
    """One `agency run` subprocess.

    It is a subprocess and not a thread on purpose: stopping the daemon must
    not stop an agent that is halfway through a review. A child process keeps
    running when its parent goes away, and the run record on disk is what the
    next daemon reads to find it again.
    """
    id: str
    project: str
    pack: str
    device: str
    log: Path
    argv: list[str]
    process: subprocess.Popen
    runId: str | None = None
    startedAt: float = field(default_factory=time.monotonic)

    def alive(self) -> bool:
        return self.process.poll() is None

    def tail(self, lines: int = 25) -> str:
        try:
            text = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.rstrip().splitlines()[-lines:])


# ---------------------------------------------------------------- daemon

class Daemon:
    """Everything the request handler is allowed to know."""

    def __init__(self, projects: list[config.Project], hours: float,
                 pair_window: int = PAIR_WINDOW) -> None:
        self.projects = project_keys(projects)
        self.started = time.time()
        self.expires_at = self.started + hours * 3600
        self.state = state_dir()
        self.devices = Devices(self.state / "devices.json")
        self.audit_path = self.state / "remote.jsonl"

        self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
        self.pair_until = self.started + pair_window
        self.pair_attempts = 0

        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.port: int | None = None
        #: `agency packs` per project, for a while. The overview asks every
        #: project at once and a pack changes when someone commits one — a
        #: pull-to-refresh should not cost one subprocess per project every time.
        self._packs: dict[str, tuple[float, object]] = {}

    # -------------------------------------------------------- activation

    def activated(self) -> bool:
        return time.time() < self.expires_at

    def remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def project(self, key: str | None) -> config.Project | None:
        return self.projects.get(key or "")

    # -------------------------------------------------------- pairing

    def pair_open(self) -> bool:
        return time.time() < self.pair_until and self.pair_attempts < PAIR_ATTEMPTS

    def pair(self, code: str, name: str, bypass: bool) -> Device | None:
        if not self.pair_open():
            return None
        if not hmac.compare_digest(self.pair_code.encode(),
                                   str(code or "").encode("utf-8", "ignore")):
            self.pair_attempts += 1
            return None
        # One code, one device. Leaving it open would mean a code read over a
        # shoulder stays useful for the rest of the window.
        self.pair_until = 0
        return self.devices.add(name, bypass)

    # -------------------------------------------------------- delegation

    def agency(self, project: config.Project, args: list[str],
               timeout: int = 120) -> tuple[bool, object, str]:
        """`agency … --json`, as a subprocess, and its JSON straight through.

        Through `sys.executable -m agency` rather than the `agency` shim: the
        daemon may well be started by something that does not have the user's
        PATH, and the module is right here in the interpreter that is running
        this code.
        """
        argv = [sys.executable, "-m", "agency", *args,
                "--repo", str(project.root), "--json"]
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            return False, None, f"agency {args[0]} timed out after {timeout}s"
        if p.returncode != 0:
            return False, None, (p.stderr or p.stdout or "").strip()
        try:
            return True, json.loads(p.stdout), ""
        except json.JSONDecodeError:
            return False, None, "agency did not answer with JSON"

    # -------------------------------------------------------- overview

    def packs_of(self, project: config.Project) -> list:
        key = posix(project.root)
        hit = self._packs.get(key)
        if hit and time.monotonic() - hit[0] < PACKS_TTL:
            return hit[1]                            # type: ignore[return-value]
        ok, data, _ = self.agency(project, ["packs"], timeout=60)
        rows = data if ok and isinstance(data, list) else []
        self._packs[key] = (time.monotonic(), rows)
        return rows

    def overview(self) -> list[dict]:
        """Every project and its specialists, in one answer.

        One request rather than one per project, and the projects are asked in
        parallel: a phone that has to make eight round trips before it can show
        anything is a phone that shows a spinner.
        """
        keys = list(self.projects.items())
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(keys)))) as pool:
            packs_by_key = dict(zip(
                [k for k, _ in keys],
                pool.map(lambda kp: self.packs_of(kp[1]), keys)))

        rows = []
        for key, project in keys:
            running = [{"runId": r.id, "pack": r.record().get("pack")}
                       for r in runs.unfinished(project)]
            rows.append({
                "key": key, "name": project.name, "slug": project.slug,
                "root": posix(project.root),
                "packs": packs_by_key.get(key) or [],
                "running": running,
            })
        return rows

    # -------------------------------------------------------- runs

    def busy(self, key: str) -> Job | None:
        for job in self.jobs.values():
            if job.project == key and job.alive():
                return job
        return None

    def start_run(self, project: config.Project, key: str, device: Device,
                  body: dict) -> tuple[int, dict]:
        pack_name = str(body.get("pack") or "")
        known = {p.name for p in packs.available(project)}
        if pack_name not in known:
            return 404, {"ok": False, "reason": "no-pack",
                         "message": f"“{pack_name}” is not a specialist in {key}."}

        mode = body.get("mode") or "unattended"
        if mode != "unattended":
            # Naming the step rather than saying "unsupported": the client is
            # ours and the contract for the second mode is already written.
            return 501, {"ok": False, "reason": "mode-not-here",
                         "message": "Only unattended runs start from a phone so far. "
                                    "Taking over a session with Remote Control is the "
                                    "next step of docs/plans/remote.md."}

        bypass = bool(body.get("bypass"))
        if bypass and not device.bypass:
            return 403, {"ok": False, "reason": "no-bypass",
                         "message": "This device is not allowed to start a run with the "
                                    "authorization checks turned off."}

        with self.lock:
            running = self.busy(key)
            if running:
                return 409, {"ok": False, "reason": "busy",
                             "message": f"{running.pack} is already running in {key}. "
                                        "Preparation claims a worktree, so runs over one "
                                        "project go one at a time.",
                             "runId": running.runId}

            argv = ["run", pack_name, "--unattended", "--wait",
                    "--origin", "remote", "--device", device.id,
                    "--repo", str(project.root)]
            if body.get("pr"):
                argv += ["--pr", str(int(body["pr"]))]
            if body.get("latestMerged"):
                argv.append("--latest-merged")
            if (body.get("prompt") or "").strip():
                argv += ["--prompt", str(body["prompt"]).strip()]
            if body.get("provider"):
                argv += ["--provider", str(body["provider"])]
            if body.get("model"):
                argv += ["--model", str(body["model"])]
            if body.get("since"):
                argv += ["--since", str(body["since"])]
            if bypass:
                argv.append("--bypass")

            before = {r.id for r in runs.load_runs(project)}
            job = self._spawn(key, pack_name, device, argv)
            self.jobs[job.id] = job

        run_id = self._await_record(project, device, before, job)
        append_audit(self.audit_path, {
            "action": "run", "device": device.id, "deviceName": device.name,
            "project": key, "pack": pack_name, "bypass": bypass,
            "runId": run_id, "job": job.id,
        })
        if not run_id:
            # No record means preparation refused before it wrote one — a
            # draft PR, a commit already reviewed, a missing prompt. Those
            # refusals are printed, not returned, so the log is the honest
            # answer rather than a reason invented here.
            return 400, {"ok": False, "reason": "not-started", "job": job.id,
                         "message": "The run did not start.", "output": job.tail()}
        return 200, {"ok": True, "runId": run_id, "job": job.id, "pack": pack_name,
                     "project": key}

    def _spawn(self, key: str, pack_name: str, device: Device, argv: list[str]) -> Job:
        jobs_dir = self.state / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        job_id = secrets.token_hex(4)
        log = jobs_dir / f"{job_id}.log"
        # The progress `--wait` prints is not the phone's channel — the phone
        # reads the agent's own stream out of the run directory. It is kept
        # anyway, because when preparation refuses, this file is the only
        # place that says why.
        flags = {}
        if os.name == "nt":
            # No console window for a run nobody is watching. It also stops the
            # child from taking Ctrl-C aimed at the daemon.
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW
        # The child gets its own copy of the descriptor, so this one is closed
        # right away — otherwise every run leaves a handle behind, and on
        # Windows an open handle is also a file nothing else can rotate.
        with open(log, "w", encoding="utf-8", errors="replace") as handle:
            process = subprocess.Popen(
                [sys.executable, "-m", "agency", *argv],
                cwd=str(self.projects[key].root),
                stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **flags)
        return Job(id=job_id, project=key, pack=pack_name, device=device.id,
                   log=log, argv=argv, process=process)

    def _await_record(self, project: config.Project, device: Device,
                      before: set[str], job: Job) -> str | None:
        """Wait until the run writes its record, then read its id off the disk.

        The id is not returned by `agency run --wait` — `--wait` and `--json`
        are mutually exclusive, because the agent writes to that same stdout.
        Reading it back out of the run directory keeps the alternative from
        happening: parsing the human progress output for a ULID, which is
        exactly the kind of regex over someone else's text this codebase spent
        a phase removing.
        """
        deadline = time.monotonic() + RUN_ID_TIMEOUT
        while time.monotonic() < deadline:
            for run in runs.load_runs(project):
                if run.id in before:
                    continue
                trigger = (run.record().get("trigger") or {})
                if trigger.get("device") == device.id:
                    job.runId = run.id
                    return run.id
            if not job.alive():
                return None
            time.sleep(0.1)
        return None


# ---------------------------------------------------------------- HTTP

def _json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    daemon: Daemon  # set on the server class before serving

    # -------------------------------------------------------- plumbing

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        console(out.say,
                f"  {out.dim(self.command + ' ' + self.path.split('?')[0])}  "
                f"{out.dim(str(args[1]) if len(args) > 1 else '')}")

    def _send(self, code: int, data, headers: dict | None = None) -> None:
        body = _json_bytes(data)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # No CORS on purpose: the page is served by this same daemon, so it is
        # same-origin. A wildcard here would let any page the phone happens to
        # have open start a run with a token it stole from nowhere.
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code: int, reason: str, message: str) -> None:
        self._send(code, {"ok": False, "reason": reason, "message": message})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _token(self, query: dict) -> str | None:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        # EventSource cannot set a header — the only way a browser subscribes
        # to a stream is a URL. The token therefore has to be allowed in the
        # query string, and the audit log is on this machine anyway.
        return (query.get("token") or [None])[0]

    def _device(self, query: dict) -> Device | None:
        return self.daemon.devices.find(self._token(query))

    def _project(self, query: dict):
        key = (query.get("project") or [None])[0]
        return key, self.daemon.project(key)

    # -------------------------------------------------------- routing

    def do_GET(self) -> None:  # noqa: N802
        self._guard(self._get)

    def do_POST(self) -> None:  # noqa: N802
        self._guard(self._post)

    def _guard(self, fn) -> None:
        """A daemon nobody is watching does not get to die of a typo.

        Without this, an exception in a handler closes the connection with no
        answer at all, and the phone reports "network error" for something that
        is a bug on this machine. The traceback still goes to the console the
        daemon was started from.
        """
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass                                    # the phone walked away
        except Exception as e:                      # noqa: BLE001
            import traceback
            traceback.print_exc()
            try:
                self._fail(500, "daemon-error", f"{type(e).__name__}: {e}")
            except OSError:
                pass

    def _https_redirect(self) -> bool:
        """Send a phone that arrived over plain http to the https address.

        `tailscale serve` can publish this daemon on both :80 and :443, and the
        Tailscale app offers the http link first. Left alone the two are
        separate origins with separate localStorage, so the same phone would
        have to pair twice and would look unpaired whenever it took the other
        link. The proxy sets X-Forwarded-Proto only on the https side.

        A request straight to the loopback -- the CLI, the extension, a browser
        on this machine -- carries no X-Forwarded-Host and is left alone; that
        is also why the host is checked before it is echoed into Location,
        since anything that can reach the loopback could otherwise name a
        redirect target of its own.

        The dot is not cosmetic. MagicDNS answers to the short name as well,
        and a single-label name cannot hold a certificate, so sending a phone
        from http://laptop to https://laptop would send it nowhere. Redirect
        only where https can actually answer.
        """
        host = self.headers.get("X-Forwarded-Host")
        if not host or self.headers.get("X-Forwarded-Proto") == "https":
            return False
        if not re.fullmatch(r"[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63})+(:\d{1,5})?", host):
            return False
        self.send_response(301)
        self.send_header("Location", f"https://{host}{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _get(self) -> None:
        if self._https_redirect():
            return
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)

        if path in ("/", "/index.html"):
            return self._page()

        if not path.startswith("/api/"):
            return self._fail(404, "no-route", "No such path.")

        device = self._device(query)
        if not device:
            return self._fail(401, "no-device", "Pair this device first.")
        if not self.daemon.activated():
            return self._fail(403, "not-activated",
                              "The activation window has closed. Reopen it on the machine "
                              "with `agency serve`.")

        if path == "/api/projects":
            return self._send(200, {
                "ok": True,
                "activatedFor": self.daemon.remaining(),
                "device": {"id": device.id, "name": device.name, "bypass": device.bypass},
                "projects": [
                    {"key": key, "name": p.name, "slug": p.slug,
                     "root": posix(p.root), "defaultBranch": p.default_branch}
                    for key, p in self.daemon.projects.items()],
            })

        if path == "/api/overview":
            return self._send(200, {
                "ok": True,
                "activatedFor": self.daemon.remaining(),
                "device": {"id": device.id, "name": device.name, "bypass": device.bypass},
                "projects": self.daemon.overview(),
            })

        key, project = self._project(query)
        if not project:
            return self._fail(404, "no-project",
                              f"“{key}” is not an activated project.")

        if path == "/api/packs":
            return self._delegate(project, ["packs"])
        if path == "/api/prs":
            state = (query.get("state") or ["all"])[0]
            limit = (query.get("limit") or ["20"])[0]
            return self._delegate(project, ["prs", "--state", state, "--limit", limit])
        if path == "/api/runs":
            return self._delegate(project, ["status", "--limit",
                                            (query.get("limit") or ["10"])[0]])

        run_id, tail = _run_path(path)
        if run_id:
            run = runs.find_run(project, run_id)
            if not run:
                return self._fail(404, "no-run", f"No run {run_id} in {key}.")
            if tail == "events":
                # `Last-Event-ID` first: when the browser reconnects a dropped
                # EventSource it sends that header by itself, and a resume that
                # depends on the client remembering to add `?offset=` is a
                # resume that will one day replay an hour of tool calls.
                resume = self.headers.get("Last-Event-ID") or (query.get("offset") or ["0"])[0]
                return self._events(project, run, _int(resume))
            if tail == "output":
                name = (query.get("name") or [""])[0]
                if name not in _outputs(run):
                    return self._fail(404, "no-output",
                                      f"This run wrote no {name!r}.")
                text = (run.dir / name).read_text(encoding="utf-8", errors="replace")
                return self._send(200, {"ok": True, "name": name,
                                        "text": text[:OUTPUT_MAX],
                                        "clipped": len(text) > OUTPUT_MAX})
            if not tail:
                return self._send(200, {"ok": True, **_run_state(run)})

        return self._fail(404, "no-route", "No such path.")

    def _post(self) -> None:
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        body = self._body()

        if path == "/api/pair":
            device = self.daemon.pair(str(body.get("code") or ""),
                                      str(body.get("name") or "phone"),
                                      bool(body.get("bypass")))
            if not device:
                append_audit(self.daemon.audit_path,
                             {"action": "pair-refused", "from": self.client_address[0]})
                return self._fail(403, "pair-refused",
                                  "Wrong code, or the pairing window is closed. Restart "
                                  "`agency serve` to open a new one.")
            append_audit(self.daemon.audit_path,
                         {"action": "paired", "device": device.id, "deviceName": device.name,
                          "bypass": device.bypass})
            console(out.done, f"paired: {device.name}  {out.dim(device.id)}"
                    + ("  bypass allowed" if device.bypass else ""))
            return self._send(200, {"ok": True, "deviceId": device.id,
                                    "token": device.token, "bypass": device.bypass})

        device = self._device(query)
        if not device:
            return self._fail(401, "no-device", "Pair this device first.")
        if not self.daemon.activated():
            return self._fail(403, "not-activated",
                              "The activation window has closed. Reopen it on the machine "
                              "with `agency serve`.")

        # A POST names its project in the body; the query string is the
        # fallback so both shapes of client work.
        key = body.get("project") or (query.get("project") or [None])[0]
        project = self.daemon.project(key)
        if path == "/api/run":
            if not project:
                return self._fail(404, "no-project", f"“{key}” is not an activated project.")
            code, data = self.daemon.start_run(project, key, device, body)
            return self._send(code, data)

        run_id, tail = _run_path(path)
        if run_id and tail == "ingest":
            if not project:
                return self._fail(404, "no-project", f"“{key}” is not an activated project.")
            run = runs.find_run(project, run_id)
            if not run:
                return self._fail(404, "no-run", f"No run {run_id} in {key}.")
            append_audit(self.daemon.audit_path,
                         {"action": "ingest", "device": device.id, "project": key,
                          "runId": run.id})
            return self._delegate(project, ["ingest", "--run", run.id], timeout=300)

        return self._fail(404, "no-route", "No such path.")

    # -------------------------------------------------------- answers

    def _delegate(self, project, args: list[str], timeout: int = 120) -> None:
        ok, data, err = self.daemon.agency(project, args, timeout=timeout)
        if not ok:
            return self._fail(502, "cli-failed", err or f"agency {args[0]} failed.")
        self._send(200, data)

    def _page(self) -> None:
        page = Path(__file__).resolve().parent / "_web" / "index.html"
        if page.is_file():
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # Never cached: the page is read off disk on every request, so an
            # edit on the machine is live on the next pull-to-refresh. A phone
            # holding yesterday's copy would be a bug with no way to see it.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        text = ("agency serve is up, and the page it should hand you is missing from "
                "the install (src/agency/_web/index.html). This is the API.\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(text)))
        self.end_headers()
        self.wfile.write(text)

    def _events(self, project, run, offset: int) -> None:
        """The agent's own stream, translated, as server-sent events.

        Nothing new is recorded for this: `runs.attend` already writes every
        line the runner emits into `agent.jsonl`, and `events.parse` already
        turns a line into the same small vocabulary the terminal prints. This
        is those two, over HTTP.

        `offset` is a line number, and every event carries the line it came
        from as its SSE id — so a phone that loses signal in a lift reconnects
        where it stopped instead of replaying an hour of tool calls.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        rec = run.record()
        dialect = providers.streaming((rec.get("agent") or {}).get("provider") or "claude")[1]
        path = run.dir / "agent.jsonl"
        sent = max(0, offset)
        handle = None
        last_beat = time.monotonic()

        def write(chunk: str) -> bool:
            try:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False   # the phone closed the tab, which is not an error

        def drain() -> bool:
            """Every complete line that has arrived since the last pass.

            A half-written line is not skipped, it is waited for: the runner's
            output is buffered, so a read can land in the middle of one, and
            treating that as a line would hand the phone a JSON fragment and
            lose the rest of it forever.
            """
            nonlocal sent
            while True:
                where = handle.tell()
                line = handle.readline()
                if not line.endswith("\n"):
                    handle.seek(where)
                    return True
                sent += 1
                if not line.strip():
                    continue
                for e in events.parse(dialect or "", line.rstrip("\r\n")):
                    if not write(f"id: {sent}\ndata: "
                                 f"{json.dumps(dataclasses.asdict(e), ensure_ascii=False)}\n\n"):
                        return False

        try:
            while True:
                if handle is None and path.is_file():
                    handle = open(path, encoding="utf-8", errors="replace")
                    for _ in range(sent):        # resume where the phone stopped
                        if not handle.readline():
                            break

                # Read the status BEFORE draining, never after: `runs.attend`
                # closes the stream file and only then writes the record, so a
                # run that already says "finished" cannot still be writing.
                # The other order drops whatever arrived in between.
                finished = run.record().get("status") != "running"
                if handle is not None and not drain():
                    return
                if finished:
                    write("event: done\ndata: "
                          f"{json.dumps(_run_state(run), ensure_ascii=False)}\n\n")
                    return

                if time.monotonic() - last_beat > SSE_HEARTBEAT:
                    if not write(": keepalive\n\n"):
                        return
                    last_beat = time.monotonic()
                time.sleep(0.4)
        finally:
            if handle is not None:
                handle.close()


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _run_path(path: str) -> tuple[str | None, str | None]:
    """`/api/run/<id>` and `/api/run/<id>/<verb>` — nothing deeper."""
    parts = [unquote(p) for p in path.strip("/").split("/")]
    if len(parts) < 3 or parts[0] != "api" or parts[1] != "run":
        return None, None
    return parts[2], (parts[3] if len(parts) > 3 else None)


def _run_state(run) -> dict:
    """What the phone needs to know about one run — the record's own words.

    `counts` is what the gate wrote. Recomputing any of it here would give the
    phone a second opinion about a number that already exists.
    """
    rec = run.record()
    agent = rec.get("agent") or {}
    return {
        "runId": run.id,
        "pack": rec.get("pack"),
        "status": rec.get("status"),
        "startedAt": rec.get("startedAt"),
        "finishedAt": rec.get("finishedAt"),
        "exitReason": rec.get("exitReason"),
        "trigger": rec.get("trigger") or {},
        "provider": agent.get("provider"),
        "model": agent.get("model"),
        "denied": (agent.get("denied") or {}).get("count") or 0,
        "counts": rec.get("counts"),
        "findings": len(run.findings()),
        "outputs": _outputs(run),
    }


def _outputs(run) -> list[str]:
    """The documents this run left behind, as they are on disk.

    This used to be a fixed list of the three names a review pack happens to
    write. A pack that answers a question writes `answer.md`, and the phone
    had no way to learn it existed -- the summary said "answered in answer.md"
    and that was the end of the trail.

    It doubles as the guard for reading one: a name is served only if it came
    from this listing, so there is no path to traverse.
    """
    try:
        return sorted(f.name for f in run.dir.iterdir()
                      if f.is_file() and f.suffix == ".md")
    except OSError:
        return []


# ---------------------------------------------------------------- entry

def serve(projects: list[config.Project], host: str, port: int, hours: float,
          pair_window: int = PAIR_WINDOW) -> Daemon:
    """Build the server and start it on its own thread. Returns the daemon so
    a test can drive it without a terminal."""
    daemon = Daemon(projects, hours, pair_window=pair_window)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    handler = type("BoundHandler", (Handler,), {"daemon": daemon})
    server = Server((host, port), handler)
    daemon.server = server
    daemon.port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return daemon
