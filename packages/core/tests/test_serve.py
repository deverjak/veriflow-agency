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
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agency import cli, runs, serve
from agency.util import write_json


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

def stream(daemon, run_id: str, project_key: str, token: str,
           offset: int = 0) -> tuple[list[dict], dict | None]:
    """Read the SSE stream to its end — it ends by itself, the run is over.

    Returns the progress events and the closing state separately, because they
    are two different things on the wire: `data:` frames and the one `event:
    done` that carries the run's own record.
    """
    url = (f"http://127.0.0.1:{daemon.port}/api/run/{run_id}/events"
           f"?project={project_key}&token={token}&offset={offset}")
    with urllib.request.urlopen(url, timeout=30) as r:
        lines = r.read().decode("utf-8").splitlines()

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
