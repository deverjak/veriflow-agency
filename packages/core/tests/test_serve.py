"""`agency serve` — the daemon a phone talks to.

`docs/plans/remote.md`, steps 0 and 1. What is worth pinning down here is not
that HTTP works, it is the three claims the daemon makes about itself:

  * a request without a paired device gets nothing, and neither does one that
    arrives after the activation window has closed;
  * the run it starts is the same run the terminal starts — the argv is built
    from the same flags, plus who asked and from where;
  * the live progress is the agent's OWN stream, read back out of the run
    directory, never a second account of it assembled here.

No test may launch a real agent (`conftest.py` guards that) and none may spawn
`agency` either — `_spawn` and `agency()` are substituted, because what is
under test is what the daemon ASKS for, not that a subprocess works.
"""

from __future__ import annotations

import json
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from agency import cli, config, runs, serve
from agency.util import write_json
from conftest import git, install_pack


# ---------------------------------------------------------------- harness

class FakeProcess:
    """A subprocess that is alive until a test says otherwise."""

    def __init__(self, running: bool = True) -> None:
        self.running = running

    def poll(self):
        return None if self.running else 0


@pytest.fixture
def daemon(project, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_STATE_DIR", str(tmp_path / "state"))
    d = serve.serve([project], "127.0.0.1", 0, hours=1)
    yield d
    if d.server is not None:
        d.server.shutdown()


def call(daemon, method: str, path: str, token: str | None = None, body=None):
    url = f"http://127.0.0.1:{daemon.port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def pair(daemon, name: str = "phone", bypass: bool = False) -> str:
    code, data = call(daemon, "POST", "/api/pair",
                      body={"code": daemon.pair_code, "name": name, "bypass": bypass})
    assert code == 200, data
    return data["token"]


def spawns(daemon, monkeypatch, target: dict | None = None):
    """Substitute the subprocess: record the argv and write the record that
    `agency run` would have written a second later."""
    seen: dict = {}

    def fake_spawn(self, key, pack_name, device, argv):
        seen["argv"] = argv
        seen["key"] = key
        run = runs.start(self.projects[key], pack_name,
                         target or {"kind": "workspace", "ref": "main",
                                    "headRefOid": "a" * 40},
                         provider="claude", attended=False,
                         origin="remote", device=device.id)
        seen["runId"] = run.id
        return serve.Job(id="job", project=key, pack=pack_name, device=device.id,
                         log=Path(self.state / "jobs" / "job.log"), argv=argv,
                         process=FakeProcess())

    monkeypatch.setattr(serve.Daemon, "_spawn", fake_spawn)
    return seen


# ---------------------------------------------------------------- what it serves

def fake_repo(path: Path, worktree: bool = False, pack: bool = True) -> Path:
    """A repository on disk as a scan sees it — no git, because a scan does
    not run git either. A worktree's `.git` is a FILE; that is the whole
    difference, and it is the one that matters."""
    path.mkdir(parents=True, exist_ok=True)
    if worktree:
        (path / ".git").write_text("gitdir: ../real/.git/worktrees/x\n", encoding="utf-8")
    else:
        (path / ".git").mkdir()
    if pack:
        skill = path / ".claude" / "skills" / "agency-po"
        skill.mkdir(parents=True)
        (skill / "pack.json").write_text("{}", encoding="utf-8")
    return path


def test_a_scan_finds_projects_and_skips_a_runs_worktree(tmp_path):
    """The trap this was written for: `agency run` builds a throwaway worktree
    next to the repository and copies the pack into it, so
    `main-panel-review-pr-467` looks exactly like a project with a specialist.
    Three of them were sitting on the real disk when this was written."""
    root = tmp_path / "coding"
    fake_repo(root / "org" / "main-panel")
    fake_repo(root / "org" / "main-panel-review-pr-467", worktree=True)
    fake_repo(root / "org" / "notes", pack=False)
    fake_repo(root / "org" / "deep" / "nested" / "repo")

    found = [p.name for p in serve.scan_tree(root, depth=2)]

    assert found == ["main-panel"]


def test_a_scan_never_walks_into_a_repository(tmp_path):
    """Whatever is nested inside a repository belongs to it. A scan that
    descends offers a project's own fixtures as projects."""
    root = tmp_path / "coding"
    outer = fake_repo(root / "org" / "outer")
    fake_repo(outer / "fixtures" / "inner")

    found = [p.name for p in serve.scan_tree(root, depth=4)]

    assert found == ["outer"]


def test_two_projects_with_one_name_both_stay(tmp_path, repo):
    """The name is how the phone asks for a project, so it has to be unique —
    but refusing to start over it (which is what this did) means one clone in
    the wrong place takes the whole daemon down."""
    other = tmp_path / "elsewhere" / repo.name
    other.mkdir(parents=True)
    git(other, "init", "-q", "-b", "main")

    a, b = config.discover(repo), config.discover(other)
    keys = serve.project_keys([a, b])

    assert sorted(keys) == sorted([f"{repo.parent.name}/{repo.name}",
                                   f"{other.parent.name}/{other.name}"])
    assert len(keys) == 2


def test_a_named_project_is_opened_even_with_no_specialist(project, tmp_path):
    """A scan asks for a pack, because a project with nothing to task is a row
    that does nothing. A path someone typed is not a guess — it is opened."""
    bare = tmp_path / "bare"
    bare.mkdir()
    git(bare, "init", "-q", "-b", "main")

    found = serve.resolve_projects(serve.Selection(projects=[str(bare)]))

    assert [p.root.name for p in found] == ["bare"]


def test_the_list_is_the_question_not_its_answer(tmp_path, monkeypatch):
    """A scan is stored as a scan. Stored as the paths it found, it would go
    stale the day a repository is cloned — and re-running it is milliseconds."""
    monkeypatch.setenv("AGENCY_STATE_DIR", str(tmp_path / "state"))
    serve.save_selection(serve.Selection(projects=["C:/one"], scan=["C:/coding"], depth=3))

    back = serve.load_selection()

    assert (back.projects, back.scan, back.depth) == (["C:/one"], ["C:/coding"], 3)
    assert serve.Selection().empty(), "nothing named and nothing to scan is nothing to open"


def serve_once(*args) -> str:
    """`agency serve` with a window of zero: it opens, prints what it opened,
    and closes. Enough to test what it decided to serve, and nothing else."""
    cli.main(["serve", "--hours", "0", "--port", "0", *args])


def test_saving_the_list_means_a_bare_serve_opens_it_again(project, tmp_path,
                                                           monkeypatch, capsys):
    """The answer to "where else do I write the projects down": once, with
    --save, and never again."""
    monkeypatch.setenv("AGENCY_STATE_DIR", str(tmp_path / "state"))

    serve_once("--project", str(project.root), "--save")
    assert serve.load_selection().projects == [str(project.root)]

    capsys.readouterr()
    serve_once()
    printed = capsys.readouterr().out
    assert "stored list" in printed and project.root.name in printed

    serve_once("--forget")
    assert not serve.selection_path().exists()


def test_arguments_beat_the_stored_list_outright(project, tmp_path, monkeypatch, capsys):
    """"Serve exactly this one project for an hour" has to be sayable. A flag
    that silently joins a list written weeks ago is not that."""
    monkeypatch.setenv("AGENCY_STATE_DIR", str(tmp_path / "state"))
    serve.save_selection(serve.Selection(projects=["C:/somewhere/that/is/gone"]))

    capsys.readouterr()
    serve_once("--project", str(project.root))
    printed = capsys.readouterr().out

    assert "from the arguments" in printed
    assert serve.load_selection().projects == ["C:/somewhere/that/is/gone"], \
        "without --save the stored list is not touched"


# ---------------------------------------------------------------- step 0

def test_the_record_says_where_the_person_was_standing(project, capsys):
    """`origin` is not `attended` and not `kind`. A run from a phone is manual,
    unattended and remote at the same time, and the record has to keep all
    three apart — otherwise "what did I start from the train" has no answer."""
    run = runs.start(project, "review-graph",
                     {"kind": "workspace", "ref": "main", "headRefOid": "b" * 40},
                     attended=False, origin="remote", device="deadbeef")

    assert run.record()["trigger"] == {"kind": "manual", "attended": False,
                                       "origin": "remote", "device": "deadbeef"}

    write_json(run.findings_path, [])
    code = cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    assert json.loads(capsys.readouterr().out)["recordErrors"] == []
    assert code == 0


def test_an_ordinary_run_is_marked_too(project):
    """Written every time, including the boring answer: a field that only
    appears when it is interesting cannot be counted."""
    run = runs.start(project, "review-graph",
                     {"kind": "workspace", "ref": "main", "headRefOid": "c" * 40})

    assert run.record()["trigger"]["origin"] == "cli"
    assert "device" not in run.record()["trigger"]


# ---------------------------------------------------------------- pairing

def test_pairing_takes_the_code_printed_on_the_machine(daemon):
    bad, _ = call(daemon, "POST", "/api/pair", body={"code": "000000", "name": "x"})
    assert bad == 403

    ok, data = call(daemon, "POST", "/api/pair",
                    body={"code": daemon.pair_code, "name": "phone"})
    assert ok == 200 and data["token"]

    again, _ = call(daemon, "POST", "/api/pair",
                    body={"code": daemon.pair_code, "name": "second phone"})
    assert again == 403, "one code pairs one device — a code read over a shoulder is spent"


def test_a_console_that_cannot_print_does_not_fail_the_request(daemon, monkeypatch):
    """Found by running the daemon outside `main()`: the `✓` of a successful
    pairing hit a cp1250 console, raised `UnicodeEncodeError`, and the paired
    phone got HTTP 500 for something that had already worked. The line on the
    machine's console is a courtesy; the answer to the phone is the job."""
    def explode(*a, **kw):
        raise UnicodeEncodeError("charmap", "✓", 0, 1, "no")

    monkeypatch.setattr(serve.out, "done", explode)
    monkeypatch.setattr(serve.out, "say", explode)

    code, data = call(daemon, "POST", "/api/pair",
                      body={"code": daemon.pair_code, "name": "phone"})

    assert code == 200 and data["token"]


def test_guessing_the_code_runs_out(daemon):
    for _ in range(serve.PAIR_ATTEMPTS):
        call(daemon, "POST", "/api/pair", body={"code": "000000"})

    code, _ = call(daemon, "POST", "/api/pair", body={"code": daemon.pair_code})
    assert code == 403, "the window closes after a handful of wrong codes, right one included"


def test_without_a_device_there_is_nothing_to_read(daemon):
    code, data = call(daemon, "GET", "/api/projects")
    assert code == 401 and data["reason"] == "no-device"


def test_a_token_that_is_not_a_token_is_a_refusal(daemon):
    """`hmac.compare_digest` refuses two strings when either has a character
    outside ASCII — so a token autocorrected into a smart quote would crash the
    comparison instead of failing it. Compared as bytes, it is a plain 401.

    Through the query string, because that is the reachable way in: a header
    cannot carry those bytes at all, and the stream endpoint has to accept a
    token in the URL — `EventSource` cannot set a header.
    """
    pair(daemon)

    code, data = call(daemon, "GET", "/api/projects?token=tok%C3%A9n%E2%80%93x")

    assert code == 401 and data["reason"] == "no-device"


def test_a_revoked_token_stops_working(daemon):
    token = pair(daemon)
    assert call(daemon, "GET", "/api/projects", token)[0] == 200

    daemon.devices.revoke(daemon.devices.all()[0].id)
    assert call(daemon, "GET", "/api/projects", token)[0] == 401


# ---------------------------------------------------------------- activation

def test_the_window_closes_by_itself(daemon):
    token = pair(daemon)
    daemon.expires_at = time.time() - 1

    code, data = call(daemon, "GET", "/api/projects", token)
    assert code == 403 and data["reason"] == "not-activated"


def test_only_activated_projects_answer(daemon):
    token = pair(daemon)

    code, data = call(daemon, "GET", "/api/packs?project=somewhere-else", token)
    assert code == 404 and data["reason"] == "no-project"


def test_every_project_and_its_specialists_in_one_answer(project, tmp_path, monkeypatch):
    """What the phone opens is not one project — it is all of them. One request
    rather than one per project, because a phone that makes eight round trips
    before it can show anything shows a spinner."""
    monkeypatch.setenv("AGENCY_STATE_DIR", str(tmp_path / "state"))
    second = tmp_path / "second"
    second.mkdir()
    git(second, "init", "-q", "-b", "main")
    (second / "a.txt").write_text("x", encoding="utf-8")
    git(second, "add", "-A")
    git(second, "-c", "user.email=t@t.t", "-c", "user.name=T", "commit", "-q", "-m", "one")
    other = config.discover(second)
    install_pack(other, "ceo", {"target": "workspace", "worktree": False,
                                "prompt": "required"})

    d = serve.serve([config.discover(project.root), other], "127.0.0.1", 0, hours=1)
    try:
        token = pair(d)
        # The real subprocess answers here — `agency packs` per project, in
        # parallel — so this also pins that delegation actually works.
        code, data = call(d, "GET", "/api/overview", token)
    finally:
        d.server.shutdown()

    assert code == 200
    by_key = {p["key"]: p for p in data["projects"]}
    assert sorted(by_key) == [project.root.name, "second"]
    assert [x["name"] for x in by_key[project.root.name]["packs"]] == ["review-graph"]
    assert [x["name"] for x in by_key["second"]["packs"]] == ["ceo"]
    assert by_key["second"]["running"] == []


def test_the_overview_says_what_is_running_right_now(daemon, project):
    """A run in flight is the one thing on that screen that changes without
    anybody touching the phone."""
    token = pair(daemon)
    runs.start(project, "review-graph",
               {"kind": "workspace", "ref": "main", "headRefOid": "d" * 40})

    code, data = call(daemon, "GET", "/api/overview", token)

    assert code == 200
    running = data["projects"][0]["running"]
    assert [r["pack"] for r in running] == ["review-graph"]


def test_projects_are_named_by_their_directory(daemon, project):
    token = pair(daemon)

    code, data = call(daemon, "GET", "/api/projects", token)
    assert code == 200
    assert [p["key"] for p in data["projects"]] == [project.root.name]
    assert data["activatedFor"] > 0


# ---------------------------------------------------------------- runs

def test_the_run_is_the_one_the_terminal_would_have_started(daemon, project, monkeypatch):
    """The whole point of delegating instead of orchestrating: the daemon adds
    who asked and from where, and changes nothing else about the run."""
    seen = spawns(daemon, monkeypatch)
    token = pair(daemon)

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "review-graph",
                       "pr": 12, "prompt": "the payments branch"})

    assert code == 200, data
    assert data["runId"] == seen["runId"]
    argv = seen["argv"]
    assert argv[:4] == ["run", "review-graph", "--unattended", "--wait"]
    assert "--origin" in argv and argv[argv.index("--origin") + 1] == "remote"
    assert argv[argv.index("--device") + 1] == daemon.devices.all()[0].id
    assert argv[argv.index("--pr") + 1] == "12"
    assert argv[argv.index("--prompt") + 1] == "the payments branch"
    assert "--bypass" not in argv


def test_a_specialist_this_project_does_not_have(daemon, project, monkeypatch):
    spawns(daemon, monkeypatch)
    token = pair(daemon)

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "ceo"})

    assert code == 404 and data["reason"] == "no-pack"


def test_bypass_belongs_to_the_device_not_to_the_request(daemon, project, monkeypatch):
    """Starting a run with the authorization checks off is running arbitrary
    code on this machine. A phone either was paired with that right or it was
    not; asking nicely in the body is not how it gets one."""
    spawns(daemon, monkeypatch)
    token = pair(daemon, bypass=False)

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "review-graph",
                       "bypass": True})

    assert code == 403 and data["reason"] == "no-bypass"


def test_a_device_paired_for_bypass_may(daemon, project, monkeypatch):
    seen = spawns(daemon, monkeypatch)
    token = pair(daemon, bypass=True)

    code, _ = call(daemon, "POST", "/api/run", token,
                   {"project": project.root.name, "pack": "review-graph", "bypass": True})

    assert code == 200
    assert "--bypass" in seen["argv"]


def test_one_run_at_a_time_over_one_project(daemon, project, monkeypatch):
    """Preparation claims a worktree path. Two of them racing get the same
    directory — the extension serialises for the same reason."""
    spawns(daemon, monkeypatch)
    token = pair(daemon)
    first, _ = call(daemon, "POST", "/api/run", token,
                    {"project": project.root.name, "pack": "review-graph"})
    assert first == 200

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "review-graph"})

    assert code == 409 and data["reason"] == "busy"


def test_taking_over_a_session_is_named_not_pretended(daemon, project, monkeypatch):
    spawns(daemon, monkeypatch)
    token = pair(daemon)

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "review-graph",
                       "mode": "remote-control"})

    assert code == 501 and data["reason"] == "mode-not-here"


def test_a_run_that_never_started_answers_with_what_was_printed(daemon, project,
                                                                monkeypatch, tmp_path):
    """A draft PR, a commit already reviewed, a missing prompt: `agency run`
    refuses before it writes a record, and it says why on stdout. Inventing a
    reason here would mean the phone is told something the terminal never said."""
    log = tmp_path / "job.log"
    log.write_text("  ! The pull request is a draft. Continue with --force.\n",
                   encoding="utf-8")

    def fake_spawn(self, key, pack_name, device, argv):
        return serve.Job(id="job", project=key, pack=pack_name, device=device.id,
                         log=log, argv=argv, process=FakeProcess(running=False))

    monkeypatch.setattr(serve.Daemon, "_spawn", fake_spawn)
    token = pair(daemon)

    code, data = call(daemon, "POST", "/api/run", token,
                      {"project": project.root.name, "pack": "review-graph"})

    assert code == 400 and data["reason"] == "not-started"
    assert "draft" in data["output"]


def test_every_remote_action_leaves_a_line(daemon, project, monkeypatch):
    spawns(daemon, monkeypatch)
    token = pair(daemon)
    call(daemon, "POST", "/api/run", token,
         {"project": project.root.name, "pack": "review-graph"})

    lines = [json.loads(x) for x in
             daemon.audit_path.read_text(encoding="utf-8").splitlines()]

    assert [x["action"] for x in lines] == ["paired", "run"]
    assert lines[1]["device"] == daemon.devices.all()[0].id
    assert lines[1]["pack"] == "review-graph"


# ---------------------------------------------------------------- progress

def split_sse(body: str) -> tuple[list[dict], dict | None]:
    """The progress events and the closing state, separately.

    They are two different things on the wire — plain `data:` frames and the
    one `event: done` that carries the run's own record — and telling them
    apart by looking for a key inside is how a test starts passing for the
    wrong reason: the closing state has a `trigger.kind` in it.
    """
    lines = body.splitlines()
    progress: list[dict] = []
    final = None
    i = 0
    while i < len(lines):
        if lines[i] == "event: done":
            final = json.loads(lines[i + 1][6:])
            i += 2
            continue
        if lines[i].startswith("data: "):
            progress.append(json.loads(lines[i][6:]))
        i += 1
    return progress, final


def stream(daemon, run_id: str, project_key: str, token: str,
           offset: int = 0, headers: dict | None = None) -> tuple[list[dict], dict | None]:
    """Read the SSE stream to its end — it ends by itself, the run is over."""
    url = (f"http://127.0.0.1:{daemon.port}/api/run/{run_id}/events"
           f"?project={project_key}&token={token}&offset={offset}")
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return split_sse(r.read().decode("utf-8"))


def test_the_progress_is_the_agents_own_stream(daemon, project, make_run):
    """Nothing new is recorded for the phone: `runs.attend` already writes the
    runner's every line into `agent.jsonl`, and `events.py` already knows how
    to read it. This is those two over HTTP."""
    token = pair(daemon)
    run = make_run(status="ok", counts={"raw": 2, "kept": 1})
    (run.dir / "agent.jsonl").write_text("\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "src/auth.ts"}}]}}),
        json.dumps({"type": "result", "num_turns": 4, "total_cost_usd": 0.12,
                    "result": "done", "usage": {"input_tokens": 10, "output_tokens": 2}}),
    ]) + "\n", encoding="utf-8")

    progress, final = stream(daemon, run.id, project.root.name, token)

    assert [e["kind"] for e in progress] == ["start", "tool", "done"]
    assert progress[1]["tool"] == "Read" and "auth.ts" in progress[1]["detail"]
    assert final["status"] == "ok" and final["counts"]["kept"] == 1


def test_a_phone_that_lost_signal_resumes_where_it_stopped(daemon, project, make_run):
    """`offset` is a line of `agent.jsonl` and every event carries the line it
    came from. Without it, a lift means replaying an hour of tool calls."""
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "agent.jsonl").write_text("\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "looking at the diff"}]}}),
    ]) + "\n", encoding="utf-8")

    progress, _ = stream(daemon, run.id, project.root.name, token, offset=1)

    assert [e["kind"] for e in progress] == ["text"], "the first line was already seen"


def test_a_half_written_line_is_waited_for_not_skipped(daemon, project, make_run):
    """The runner's output is buffered, so a read can land inside a line. Taking
    that as a line hands the phone a JSON fragment and loses the rest for good."""
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "agent.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}) + "\n"
        + '{"type": "assist',  # the write that was still in flight
        encoding="utf-8")

    progress, final = stream(daemon, run.id, project.root.name, token)

    assert [e["kind"] for e in progress] == ["start"]
    assert final is not None, "the stream still closes — the run is over either way"


def test_a_dropped_connection_resumes_from_the_browsers_own_header(daemon, project, make_run):
    """`EventSource` reconnects by itself and sends `Last-Event-ID`. A resume
    that only works when the client remembers to add `?offset=` is a resume
    that will one day replay an hour of tool calls."""
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "agent.jsonl").write_text("\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "still here"}]}}),
    ]) + "\n", encoding="utf-8")

    progress, _ = stream(daemon, run.id, project.root.name, token,
                         headers={"Last-Event-ID": "1"})

    assert [e["kind"] for e in progress] == ["text"]


def test_the_page_is_served_and_never_cached(daemon):
    """The phone's client is a file on this machine, read on every request —
    a phone holding yesterday's copy would be a bug with nowhere to look."""
    with urllib.request.urlopen(f"http://127.0.0.1:{daemon.port}/", timeout=10) as r:
        body = r.read().decode("utf-8")
        assert r.headers["Content-Type"].startswith("text/html")
        assert r.headers["Cache-Control"] == "no-store"

    assert "<title>Agency</title>" in body
    assert "EventSource" in body, "the live progress is the point of the page"


def test_the_run_state_is_the_records_own_words(daemon, project, make_run):
    token = pair(daemon)
    run = make_run(status="ok", counts={"raw": 3, "kept": 2, "duplicates": 1})

    code, data = call(daemon, "GET",
                      f"/api/run/{run.id}?project={project.root.name}", token)

    assert code == 200
    assert data["counts"] == {"raw": 3, "kept": 2, "duplicates": 1}
    assert data["pack"] == "review-graph" and data["findings"] == 1


def test_a_run_from_another_project_is_not_found(daemon, project, make_run):
    token = pair(daemon)

    code, data = call(daemon, "GET",
                      f"/api/run/01NOSUCHRUN?project={project.root.name}", token)

    assert code == 404 and data["reason"] == "no-run"


# --------------------------------------------------- http -> https

def raw_get(daemon, path: str, headers: dict | None = None):
    """One request, no redirect following, no JSON assumed.

    `call` follows redirects and parses the body, which is exactly what a test
    about a redirect must not do.
    """
    conn = http.client.HTTPConnection("127.0.0.1", daemon.port, timeout=10)
    try:
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        r.read()
        return r.status, r.getheader("Location")
    finally:
        conn.close()


def test_a_phone_that_took_the_http_link_is_sent_to_the_https_one(daemon):
    """`tailscale serve` can publish this daemon on :80 as well as :443, and
    the Tailscale app offers the http link first. Two origins would mean two
    localStorages and a phone that has to pair twice."""
    status, location = raw_get(daemon, "/?x=1", {
        "X-Forwarded-Host": "laptop.tailnet.ts.net"})

    assert status == 301
    assert location == "https://laptop.tailnet.ts.net/?x=1"


def test_the_https_side_is_served_not_redirected(daemon):
    status, location = raw_get(daemon, "/", {
        "X-Forwarded-Host": "laptop.tailnet.ts.net", "X-Forwarded-Proto": "https"})

    assert status == 200 and location is None


def test_a_request_straight_to_the_loopback_is_left_alone(daemon):
    """The CLI, the extension and a browser on this machine reach the daemon
    directly. There is no https address for them to be sent to."""
    status, location = raw_get(daemon, "/")

    assert status == 200 and location is None


def test_the_redirect_target_is_not_whatever_the_caller_says(daemon):
    """Anything that can reach the loopback can set this header; echoing it
    into Location unchecked would make the daemon an open redirect."""
    status, location = raw_get(daemon, "/", {"X-Forwarded-Host": "evil.example.com/@x"})

    assert status == 200 and location is None


def test_the_short_magicdns_name_keeps_working_over_http(daemon):
    """MagicDNS answers to `laptop` as well as `laptop.tailnet.ts.net`, but a
    single-label name cannot hold a certificate. Redirecting it to https would
    send the phone to an address nothing serves."""
    status, location = raw_get(daemon, "/", {"X-Forwarded-Host": "laptop"})

    assert status == 200 and location is None


# --------------------------------------------------- the run's documents

def test_a_run_lists_the_documents_it_actually_wrote(daemon, project, make_run):
    """The list used to be three hardcoded names. A pack that answers a
    question writes answer.md, and the phone never heard about it."""
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "answer.md").write_text("the three tickets", encoding="utf-8")
    (run.dir / "summary.md").write_text("what happened", encoding="utf-8")
    (run.dir / "run.json").write_text("{}", encoding="utf-8")

    code, data = call(daemon, "GET",
                      f"/api/run/{run.id}?project={project.root.name}", token)

    assert code == 200
    assert data["outputs"] == ["answer.md", "summary.md"], "only what it wrote, and only prose"


def test_a_document_can_be_read_from_the_phone(daemon, project, make_run):
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "answer.md").write_text("# Top 3\n\n480, 343, 495\n", encoding="utf-8")

    code, data = call(daemon, "GET",
                      f"/api/run/{run.id}/output?project={project.root.name}"
                      f"&name=answer.md", token)

    assert code == 200 and data["clipped"] is False
    assert data["text"] == "# Top 3\n\n480, 343, 495\n"


def test_a_document_the_run_did_not_write_is_not_served(daemon, project, make_run):
    """The listing is the guard: a name that is not in it is not a file to
    read, which is also why there is no path here to traverse."""
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "answer.md").write_text("answer", encoding="utf-8")

    for name in ("run.json", "../../../../etc/passwd", r"..\..\run.json", ""):
        code, data = call(daemon, "GET",
                          f"/api/run/{run.id}/output?project={project.root.name}"
                          f"&name={urllib.parse.quote(name)}", token)
        assert code == 404 and data["reason"] == "no-output", name


def test_a_long_document_is_clipped_rather_than_sent_whole(daemon, project, make_run):
    token = pair(daemon)
    run = make_run(status="ok")
    (run.dir / "answer.md").write_text("x" * (serve.OUTPUT_MAX + 10), encoding="utf-8")

    code, data = call(daemon, "GET",
                      f"/api/run/{run.id}/output?project={project.root.name}"
                      f"&name=answer.md", token)

    assert code == 200 and data["clipped"] is True
    assert len(data["text"]) == serve.OUTPUT_MAX
