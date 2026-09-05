"""A run you can come back to: one more question, or a session to talk to.

`docs/plans/remote.md`, steps 2 and 5. Until now a run was a one-shot: the
agent answered once and what it had established — the target, what it read,
why it wrote what it wrote — died with the process. The obvious next question
("and the second one?") cost a whole second run to answer, and a run somebody
wanted to argue with could not be entered at all.

Two shapes fix that, and they share every mechanism they can:

  * `agency follow` resumes the runner's own session with another question.
    The answer lands in the SAME run — same stream, same totals — because a
    follow-up is the run continuing, not a new one.
  * `--remote-control` opens the session as one a person can talk to, named so
    that it can be found in the Claude app.

What is pinned down here is mostly what must NOT happen: a follow-up must not
overwrite the run's stream, must not reset its cost, and must not overturn the
gate's verdict about its findings.
"""

from __future__ import annotations

import json

import pytest

from agency import cli, proc, providers, runs

from conftest import install_pack

INIT = '{"type":"system","subtype":"init","session_id":"abc-123"}'
RESULT = ('{"type":"result","subtype":"success","is_error":false,"num_turns":4,'
          '"total_cost_usd":0.25,"session_id":"abc-123","result":"Yes — twice.",'
          '"usage":{"input_tokens":100,"output_tokens":50}}')


def finished(make_run, **over):
    """A run as an unattended one leaves it: gated, and carrying the session id
    its own stream reported."""
    over.setdefault("status", "ok")
    over.setdefault("agent", {"provider": "claude", "model": "sonnet", "bin": "claude",
                              "sessionId": "abc-123", "turns": 41, "authorized": "grant"})
    over.setdefault("cost", {"provider": "claude", "model": "sonnet",
                             "credential": "subscription", "usd": 0.84,
                             "inputTokens": 120, "outputTokens": 900,
                             "wallClockSeconds": 300})
    return make_run(**over)


def answers(monkeypatch, lines=(INIT, RESULT), code: int = 0):
    def fake_stream(args, cwd=None, env=None, on_line=None, timeout=None):
        for line in lines:
            on_line(line)
        return code
    monkeypatch.setattr(proc, "stream", fake_stream)


def follow(project, run, *args) -> int:
    return cli.main(["follow", "--run", run.id, "--repo", str(project.root), *args])


# ------------------------------------------------------------- launch shapes

def test_the_session_is_resumed_not_started_again():
    """`--resume <id>` is the whole difference between a follow-up and a second
    run. Without it the question arrives at an agent that has never seen the
    project."""
    argv, _ = runs.launch_argv("C:/p/.agency", "and the second one?", provider="claude",
                               unattended=True, stream=True, resume="abc-123")

    assert argv[:4] == ["claude", "-p", "--resume", "abc-123"]
    assert argv[-1] == "and the second one?"


def test_resuming_codex_is_a_subcommand_not_a_flag():
    """Read off the 0.144.3 help: `codex exec resume <id>`. The shape belongs to
    the provider table for exactly this reason — one runner's flag is another
    runner's subcommand, and the order matters to both."""
    argv, _ = runs.launch_argv("C:/p/.agency", "?", provider="codex",
                               unattended=True, stream=True, resume="sess-9")

    assert argv[:4] == ["codex", "exec", "resume", "sess-9"]


def test_a_session_to_talk_to_is_named_by_the_core():
    """The Claude app shows a list of session names and nothing else. A default
    named after the hostname would say which computer it is; this says which
    specialist is asking and about which run."""
    name = runs.session_name("po", "01K5M2RRABCDEFGHJKMNPQRSTV")
    argv, info = runs.launch_argv("C:/p/.agency", "take a look", provider="claude",
                                  unattended=False, remote_control=name)

    assert name == "agency-po-01k5m2rr"
    assert argv[:3] == ["claude", "--remote-control", name]
    assert "-p" not in argv, "a session to talk to is not a printed one"
    assert info["remoteControl"] == name


def test_a_runner_without_remote_control_says_so():
    assert providers.remote_controls("claude") is True
    assert providers.remote_controls("codex") is False
    assert providers.resumes("claude") and providers.resumes("codex")
    assert not providers.resumes("some-script-of-mine")


# ------------------------------------------------------------- the stream

def test_the_answer_joins_the_runs_own_stream(project, make_run, monkeypatch):
    """The phone watches `agent.jsonl`. Opening it for writing — which is what
    a first run does — would erase the run it is a follow-up to, and the page
    watching it would see an hour of work vanish."""
    run = finished(make_run)
    (run.dir / "agent.jsonl").write_text(INIT + "\n", encoding="utf-8")
    answers(monkeypatch)

    runs.attend(project, run, ["claude", "-p"], project.root,
                dialect="claude-stream-json", append=True, message_file="answer-1.md")

    lines = (run.dir / "agent.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3, "the follow-up was appended, not written over"
    assert (run.dir / "answer-1.md").read_text(encoding="utf-8").strip() == "Yes — twice."
    assert (run.dir / "agent.md").is_file() is False


def test_what_a_follow_up_costs_is_added_not_substituted(project, make_run, monkeypatch):
    """"Which model produces better findings" is a question this tool answers
    with numbers. A run whose cost silently became the cost of its last question
    would answer it wrong, and nothing would look broken."""
    run = finished(make_run)
    answers(monkeypatch)

    runs.attend(project, run, ["claude", "-p"], project.root,
                dialect="claude-stream-json", append=True)
    rec = run.record()

    assert rec["agent"]["turns"] == 45          # 41 + 4
    assert rec["cost"]["usd"] == pytest.approx(1.09)
    assert rec["cost"]["inputTokens"] == 220
    assert rec["cost"]["wallClockSeconds"] >= 300


def test_a_first_run_still_measures_only_itself(project, make_run, monkeypatch):
    """The other half of the same claim: without `append` nothing is inherited,
    or every re-run of a run would look more expensive than it was."""
    run = finished(make_run)
    answers(monkeypatch)

    runs.attend(project, run, ["claude", "-p"], project.root,
                dialect="claude-stream-json")

    assert run.record()["cost"]["usd"] == pytest.approx(0.25)
    assert run.record()["agent"]["turns"] == 4


# ------------------------------------------------------------- the command

def test_the_question_and_the_answer_are_part_of_the_run(project, make_run,
                                                         monkeypatch, capsys):
    run = finished(make_run)
    answers(monkeypatch)

    code = follow(project, run, "--prompt", "and the migration?")
    capsys.readouterr()
    rec = run.record()

    assert code == 0
    assert [f["prompt"] for f in rec["followUps"]] == ["and the migration?"]
    assert rec["followUps"][0]["exitCode"] == 0
    assert (run.dir / "answer-1.md").is_file()


def test_the_gates_verdict_survives_the_question(project, make_run, monkeypatch, capsys):
    """A follow-up borrows `running` so a phone knows there is a stream to
    watch. What it must not do is decide anything about the findings — the gate
    said `ok`, and answering a question is not a reason to unsay it."""
    run = finished(make_run, status="gated-out")
    answers(monkeypatch)

    follow(project, run, "--prompt", "why did you drop them?")
    capsys.readouterr()

    assert run.record()["status"] == "gated-out"


def test_a_run_still_going_is_not_interrupted(project, make_run, monkeypatch, capsys):
    run = finished(make_run, status="running")
    monkeypatch.setattr(proc, "stream", lambda *a, **k: pytest.fail("must not launch"))

    code = follow(project, run, "--prompt", "well?")

    assert code == 1
    assert "has not" in capsys.readouterr().out


def test_a_run_with_no_session_cannot_be_continued(project, make_run, monkeypatch,
                                                   capsys):
    """An attended run inherits a terminal and streams nothing, so no session id
    was ever recorded. That terminal is where it continues — saying so beats
    launching an agent that starts from an empty context."""
    run = make_run(status="ok", agent={"provider": "claude", "bin": "claude"})
    monkeypatch.setattr(proc, "stream", lambda *a, **k: pytest.fail("must not launch"))

    code = follow(project, run, "--prompt", "well?")

    assert code == 1
    assert "no session" in capsys.readouterr().out


def test_a_follow_up_with_nothing_in_it(project, make_run, monkeypatch, capsys):
    run = finished(make_run)
    monkeypatch.setattr(proc, "stream", lambda *a, **k: pytest.fail("must not launch"))

    code = follow(project, run, "--prompt", "   ")

    assert code == 1


def test_the_session_is_reopened_where_it_worked(project, make_run, monkeypatch, capsys):
    """`claude --resume` finds a session by the directory it ran in, and the
    transcript is full of paths from the worktree. Resuming from anywhere else
    would hand the agent a session about files it can no longer see."""
    run = finished(make_run)
    wt = project.root.parent / "worktree-of-the-run"
    wt.mkdir()
    (run.dir / "context.json").write_text(
        json.dumps({"worktree": str(wt).replace("\\", "/"), "worktreeOwned": True}),
        encoding="utf-8")
    seen = {}

    def fake_stream(args, cwd=None, env=None, on_line=None, timeout=None):
        seen["cwd"] = str(cwd)
        for line in (INIT, RESULT):
            on_line(line)
        return 0
    monkeypatch.setattr(proc, "stream", fake_stream)

    follow(project, run, "--prompt", "and now?")
    capsys.readouterr()

    assert seen["cwd"] == str(wt)


def test_a_worktree_that_is_gone_falls_back_to_the_project(project, make_run):
    """`agency cleanup` takes the worktree. The run is still followable — the
    honest answer for where is the project itself."""
    run = finished(make_run)
    (run.dir / "context.json").write_text(
        json.dumps({"worktree": "C:/nowhere/at/all", "worktreeOwned": True}),
        encoding="utf-8")

    assert runs.working_dir(project, run) == project.root


def test_a_session_to_talk_to_is_not_streamed(project, make_run, monkeypatch, capsys):
    """An interactive `claude` publishes no machine-readable stream — that
    exists only with `-p`. Asking for both would mean showing progress for a
    session this process knows nothing about."""
    run = finished(make_run)
    seen = {}
    monkeypatch.setattr(proc, "stream", lambda *a, **k: pytest.fail("must not stream"))

    def fake_attend(args, cwd=None, env=None):
        seen["argv"] = list(args)
        return 0
    monkeypatch.setattr(proc, "attend", fake_attend)

    follow(project, run, "--prompt", "talk me through it", "--remote-control")
    capsys.readouterr()
    rec = run.record()

    assert "--remote-control" in seen["argv"]
    assert "-p" not in seen["argv"]
    assert rec["agent"]["remoteControl"] == runs.session_name("review-graph", run.id)
    assert rec["followUps"][0]["attended"] is True


def test_the_record_of_a_continued_run_still_matches_the_contract(
        project, make_run, monkeypatch, capsys):
    """`followUps` and `agent.remoteControl` are new keys in a schema whose
    blocks are closed. Three blocks were added to `run.v1` before this file
    existed and two of them broke validation first."""
    run = finished(make_run)
    answers(monkeypatch)
    follow(project, run, "--prompt", "and the migration?", "--origin", "remote",
           "--device", "dev-1")
    capsys.readouterr()

    cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["recordErrors"] == []


# ------------------------------------------------------------- refusals

def test_remote_control_and_unattended_are_two_different_runs(project, capsys):
    """One hands you a session to talk to; the other is one nobody can answer.
    A flag combination that means both is a mistake worth catching before a
    worktree is built for it."""
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "review-graph", "--remote-control", "--unattended",
                  "--repo", str(project.root)])

    assert "--unattended" in str(e.value)


def test_a_runner_that_cannot_be_driven_says_so_before_it_starts(project, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "review-graph", "--remote-control", "--provider", "codex",
                  "--repo", str(project.root)])

    assert "Remote Control" in str(e.value)


# ------------------------------------------------------------- what it asks first
#
# Probed on 2026-09-05 by attaching to the console of a real `claude` and
# reading its screen. Both of these stop an interactive session BEFORE it
# starts, which from a phone looks like a window that opened and hung.

def test_a_session_nobody_can_answer_is_not_asked_anything():
    """`--strict-mcp-config` is the difference between a session that comes up
    and one parked on "New MCP server found in this project". It costs the
    project's MCP servers, which is why it is only for a session nobody is
    standing at."""
    argv, _ = runs.launch_argv("C:/p/.agency", "take a look", provider="claude",
                               unattended=False, remote_control="agency-po-01k",
                               no_questions=True)

    assert "--strict-mcp-config" in argv
    assert providers.starts_without_asking("codex") == []


def test_at_the_machine_nothing_is_given_up():
    argv, _ = runs.launch_argv("C:/p/.agency", "take a look", provider="claude",
                               unattended=False, remote_control="agency-po-01k")

    assert "--strict-mcp-config" not in argv


def test_whether_the_runner_has_been_let_into_a_directory(tmp_path):
    """The other question has no flag: a directory Claude Code has never been
    opened in gets "Is this a project you trust?", and
    `--dangerously-skip-permissions` does not skip it either. The answer it
    recorded last time is the only way to know in advance."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"projects": {
        "C:/work/known": {"hasTrustDialogAccepted": True},
        "C:/work/refused": {"hasTrustDialogAccepted": False},
    }}), encoding="utf-8")

    assert providers.trusted("claude", "C:/work/known", home=home) is True
    assert providers.trusted("claude", r"C:\work\known", home=home) is True
    assert providers.trusted("claude", "C:/work/refused", home=home) is False
    assert providers.trusted("claude", "C:/work/never-seen", home=home) is False


def test_an_answer_that_cannot_be_read_is_not_a_no(tmp_path):
    """A guess that refuses a session which would have worked is worse than the
    hang it was trying to prevent."""
    assert providers.trusted("claude", "C:/anything", home=tmp_path) is None
    assert providers.trusted("codex", "C:/anything", home=tmp_path) is None


def test_a_session_is_not_opened_into_a_question_nobody_can_answer(
        project, monkeypatch, capsys):
    """What the phone saw before this: a window that opened, asked about the
    folder and waited forever, while the run sat at `running` with nothing
    happening in it."""
    monkeypatch.setattr(providers, "trusted", lambda *a, **k: False)
    monkeypatch.setattr(proc, "attend", lambda *a, **k: pytest.fail("must not launch"))
    monkeypatch.setattr(runs, "resolve_workspace_target", lambda *a, **k: {
        "kind": "workspace", "ref": "main", "dirty": False,
        "headRefOid": "a" * 40, "_files": ["src/auth.ts"]})
    install_pack(project, "po", {"target": "workspace", "worktree": False,
                                 "prompt": "optional"})

    code = cli.main(["run", "po", "--remote-control", "--wait", "--origin", "remote",
                     "--repo", str(project.root)])
    out = capsys.readouterr().out

    assert code == 1
    assert "trusted" in out
    # The run is closed rather than left looking alive, and the phone reads the
    # reason off the record instead of a window that is not there.
    run = runs.load_runs(project)[0]
    assert run.record()["status"] == "abandoned"
    assert "nobody is at the machine" in run.record()["exitReason"]
