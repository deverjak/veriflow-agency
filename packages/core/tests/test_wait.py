"""`agency run --wait`: a run with a parent.

`teams.md` Step 2. Until now the core printed the agent and said goodbye to it —
`cmd_cleanup` says so outright: *"no pid to watch and no exit code to catch"*.
So a run stayed `running` until somebody remembered `agency ingest`, and
forgetting cost nothing.

What is locked down here is what owning the process lets us assert for the
first time — and above all what must not be lost along the way: an agent that
crashed is not an agent with no findings; what it managed to write is not
thrown away; and an interruption is not a crash.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agency import cli, metrics, proc, runs
from agency.util import write_json

#: The real `proc.attend`, saved before conftest replaces it with a guard. Two
#: tests below examine it directly — how it assembles argv and what it does with
#: a missing binary — and they need it back.
real_attend = proc.attend

#: The same, for `proc.stream`. The guard in `conftest.py` stays in place — it
#: is what stops a test reaching a real binary — and the one test below that
#: examines this function fakes `Popen` under it, so nothing is launched
#: either way.
real_stream = proc.stream


def agent(monkeypatch, code: int = 0, leaves=None):
    """An agent showing only what matters: what it left behind and how it
    ended. Actually launching one is the single thing a test cannot do."""
    def fake(args, cwd=None, env=None):
        if leaves is not None:
            leaves()
        return code
    monkeypatch.setattr(proc, "attend", fake)


def wait(project, run, wt_owned: bool = False) -> int:
    return cli._wait_for_agent(project, run, ["claude", "prompt"], project.root, wt_owned)


# Since 2 September 2026 an agent that wrote nothing is `failed`, not
# `no-findings` — the gate does not invent an empty array for it. So tests that
# examine behaviour after a CRASH must leave `findings.json` in place, or they
# would be measuring this new branch instead.


def nothing_written(run) -> None:
    """An agent that wrote no findings.json. The fixture always creates one, but
    a real crashed run leaves nothing behind."""
    run.findings_path.unlink(missing_ok=True)


# --------------------------------------------------------------- finishing

def test_a_run_closes_itself_with_no_second_command(project, make_run, monkeypatch, capsys):
    """The done-check from `teams.md`: it finishes, the ingest happened without
    a second command, the run is not `running` and the record has
    `agent.exitCode`."""
    run = make_run()
    agent(monkeypatch, code=0)

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 0
    assert rec["status"] == "ok"
    assert rec["agent"]["exitCode"] == 0
    assert rec["counts"]["kept"] == 1, "the gate ran without `agency ingest`"
    assert runs.unfinished(project) == []


def test_the_wall_clock_finally_has_somebody_to_measure_it(project, make_run, monkeypatch, capsys):
    """`cost.wallClockSeconds` has been in `run.v1` from the start and nothing
    ever filled it in — there was no process to do the measuring. The metrics
    read it, which is why `s per candidate` was always empty."""
    run = make_run()
    # A stopwatch, not real waiting: what is measured is the difference between
    # two readings, and the test should assert something exact about that
    # number, not that "it is a float".
    tick = iter([1000.0, 1272.4])
    monkeypatch.setattr(runs.time, "monotonic", lambda: next(tick, 1272.4))
    agent(monkeypatch, code=0)

    wait(project, run)
    capsys.readouterr()
    cost = run.record()["cost"]

    assert cost["wallClockSeconds"] == 272.4
    assert cost["credential"] == "subscription", "an attended run goes on the subscription"
    assert cost["provider"] == "claude"
    assert metrics.collect(project)["cost"]["secondsPerKeptFinding"] == 272


def test_a_record_with_an_exit_code_fits_the_contract(project, make_run, monkeypatch, capsys):
    """`agent.exitCode` and `cost` are new fields in an already validated
    document."""
    run = make_run()
    agent(monkeypatch, code=0)
    wait(project, run)
    capsys.readouterr()

    cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["recordErrors"] == []


# ---------------------------------------------------------------- failures

def test_an_agent_that_crashed_is_not_a_run_with_no_findings(project, make_run, monkeypatch, capsys):
    """With no findings.json the gate writes `no-findings` — which is the claim
    "it looked and found nothing". For an agent that exited with 1 that is
    untrue, and the exit code is exactly what exposes it."""
    run = make_run()
    agent(monkeypatch, code=1, leaves=lambda: nothing_written(run))

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 1, "the chain has something to stop on"
    assert rec["status"] == "failed"
    assert "1" in rec["exitReason"]
    assert "counts" not in rec, "the gate ran over nothing, so it claims nothing"


def test_what_the_agent_managed_to_write_is_not_thrown_away(project, make_run, monkeypatch, capsys):
    """An error at the end of a session is no reason to throw away finished
    findings. They go through the gate as always — the run merely stays
    `failed`, so somebody goes and looks at it."""
    run = make_run()
    agent(monkeypatch, code=2)

    code = wait(project, run)
    capsys.readouterr()
    rec = run.record()

    assert code == 1
    assert rec["counts"]["kept"] == 1
    assert rec["status"] == "failed" and "2" in rec["exitReason"]


def test_an_interruption_is_an_abandoned_run_and_cleans_up_after_itself(project, make_run, monkeypatch, capsys):
    """Ctrl-C in the terminal kills the agent and this process too. The
    difference from `--launch` is that this process is still alive and gets to
    close the run — worktree included, which the user would otherwise have to
    find on their own."""
    run = make_run()
    wt = project.root.parent / "worktree"
    wt.mkdir()
    write_json(run.dir / "context.json", {"worktree": str(wt), "worktreeOwned": True})
    monkeypatch.setattr(runs, "remove_worktree", lambda project, path: None)

    def interrupted(args, cwd=None, env=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(proc, "attend", interrupted)

    code = wait(project, run, wt_owned=True)
    capsys.readouterr()
    rec = run.record()

    assert code == 130
    assert rec["status"] == "abandoned"
    assert "Ctrl-C" in rec["exitReason"]
    assert "worktree" not in rec


# ---------------------------------------------------------------- launching

def test_the_binary_is_looked_up_through_which(monkeypatch):
    """Windows fills in only `.exe` for a command. `codex` is really `codex.CMD`
    and without expanding PATHEXT it ends as FileNotFoundError — verified on a
    real installation, not inferred."""
    seen: list = []
    monkeypatch.setattr(proc, "which", lambda tool: r"C:\npm\codex.CMD")
    monkeypatch.setattr(subprocess, "call",
                        lambda args, cwd=None, env=None: seen.append(args) or 0)
    # Through the real function, not conftest's guard: this test examines
    # exactly what the guard otherwise forbids — how the launch command is
    # assembled.
    monkeypatch.setattr(proc, "attend", real_attend)

    assert proc.attend(["codex", "--model", "gpt"], cwd="/tmp") == 0
    assert seen[0] == [r"C:\npm\codex.CMD", "--model", "gpt"]


def test_a_missing_binary_is_not_a_crash(monkeypatch):
    """An unrunnable command is 127, the same as in `proc.run` and the same as
    in a shell — the core does not turn it into an exception the caller would
    have to catch."""
    monkeypatch.setattr(proc, "which", lambda tool: None)

    def missing(args, cwd=None, env=None):
        raise FileNotFoundError(2, "not found")
    monkeypatch.setattr(subprocess, "call", missing)
    monkeypatch.setattr(proc, "attend", real_attend)

    assert proc.attend(["not-there"]) == 127


# ------------------------------------------------------------------- flags

def test_wait_and_json_are_mutually_exclusive(project):
    """The agent writes to the same stdout. The contract "the output is one JSON
    document" cannot be promised alongside that — and a promise that breaks
    somebody else's output is worse than a missing combination of flags."""
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "review-graph", "--wait", "--json", "--repo", str(project.root)])

    assert "--json" in str(e.value)


def test_wait_and_launch_are_mutually_exclusive(project, capsys):
    """Two answers to "who holds the agent". Argparse refuses it before
    anything is prepared."""
    with pytest.raises(SystemExit):
        cli.main(["run", "review-graph", "--wait", "--launch", "--repo", str(project.root)])

    assert "not allowed with" in capsys.readouterr().err


# ------------------------------------------------------------------ budget

def _budgeted(project, run, monkeypatch, *, seconds: float, budget: dict,
              turns: int = 3):
    """A run that takes `seconds` of wall clock, as far as the record cares."""
    clock = {"t": 0.0}
    monkeypatch.setattr(runs.time, "monotonic", lambda: clock["t"])

    def stream(argv, cwd=None, env=None, on_line=None, timeout=None):
        clock["t"] += seconds
        on_line(json.dumps({"type": "result", "subtype": "success",
                            "is_error": False, "num_turns": turns,
                            "session_id": "s", "result": "done",
                            "permission_denials": []}))
        return 0

    monkeypatch.setattr(proc, "stream", stream)
    return runs.attend(project, run, ["claude", "-p"], project.root,
                       dialect="claude-stream-json", budget=budget)


def test_a_run_past_its_budget_is_flagged_and_still_finishes(project, make_run,
                                                             monkeypatch):
    """"Kill it" and "do nothing" are both wrong answers. It may be mid-write
    of findings.json, and throwing that away costs more than the overrun."""
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=30 * 60,
                       budget={"minutes": 25, "turns": None})

    assert result["overBudget"] is True
    assert run.record()["cost"]["overBudget"] is True
    assert run.record()["status"] != "failed", "over budget is not a failure"


def test_a_run_inside_its_budget_says_nothing(project, make_run, monkeypatch):
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=60,
                       budget={"minutes": 25, "turns": None})

    assert result["overBudget"] is False
    assert "overBudget" not in run.record()["cost"]


def test_turns_are_judged_only_where_they_are_measured(project, make_run,
                                                       monkeypatch):
    """`turns` exist only for a streamed run, so an attended one is never over
    on turns rather than being judged on a number it does not have."""
    run = make_run()

    result = _budgeted(project, run, monkeypatch, seconds=60, turns=99,
                       budget={"minutes": None, "turns": 60})

    assert result["overBudget"] is True


def test_three_times_over_is_a_fault_not_an_overrun(project, make_run, monkeypatch):
    """The one place anything is stopped on a number — and the number is the
    pack's own, which is what makes it a fault rather than a heuristic."""
    run = make_run()
    seen = {}

    def stream(argv, cwd=None, env=None, on_line=None, timeout=None):
        seen["timeout"] = timeout
        return 124                      # what proc.stream returns at the ceiling

    monkeypatch.setattr(proc, "stream", stream)
    result = runs.attend(project, run, ["claude", "-p"], project.root,
                         dialect="claude-stream-json",
                         budget={"minutes": 25, "turns": None})

    assert seen["timeout"] == 25 * 60 * runs.RUNAWAY
    assert result["runaway"] is True


def test_the_ceiling_stops_a_run_that_keeps_talking(monkeypatch):
    """`proc.stream` used to apply its timeout only after the stream ended, so
    a run that never stopped emitting never reached it — a ceiling that fires
    only once the thing has stopped by itself is not a ceiling."""
    import subprocess as sp

    clock = {"t": 0.0}
    monkeypatch.setattr(proc.time, "monotonic", lambda: clock["t"])

    class FakeProc:
        def __init__(self):
            self.stdout = self
            self.killed = False

        def __iter__(self):
            while True:
                clock["t"] += 10
                yield "line\n"

        def close(self):
            pass

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    fake = FakeProc()
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(proc, "which", lambda name: name)

    code = real_stream(["claude", "-p"], timeout=25, on_line=lambda t: None)

    assert code == 124 and fake.killed
