"""An unattended run: authorization, an event stream, and a truthful record.

`docs/plans/unattended.md`. Everything here was written after a real chain over
PR #479 finished "successfully" three times and produced nothing at all.

The shape of that failure is what these tests pin down. The agent was launched
correctly, ran for twelve minutes, was refused every single write, exited 0 — and
the gate then wrote `[]` on its behalf and called the run `no-findings`, which is
the claim "it looked and found nothing". The chain moved on to a second member
that judged findings which had never existed.

So: an agent must be allowed to do what its method does, a missing output must be
a failure rather than an empty result, and the record must say which of the two
happened.
"""

from __future__ import annotations

import json

import pytest

from agency import chain as chains, cli, events, ingest, proc, providers, runs
from agency.util import write_json


# ------------------------------------------------------------ authorization

def test_unattended_agent_is_allowed_to_write():
    """The bug that cost three chains: `-p` makes the agent non-interactive but
    leaves the permission model on "ask", and there is nobody to ask.

    Probed on claude 2.1.258: without `--permission-mode acceptEdits` a Write
    into the very directory handed over by `--add-dir` comes back denied.
    """
    argv, _ = runs.launch_argv("/mem", "do the work", provider="claude")

    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"


def test_the_pack_declares_what_it_may_call():
    """`acceptEdits` grants Write, not commands. A specialist that cannot run
    `agency triage` cannot decide on a finding, which is the whole reason a
    second member exists."""
    argv, _ = runs.launch_argv("/mem", "p", provider="claude",
                               needs=["agency triage", "code-review-graph"])

    assert "Bash(agency triage *)" in argv
    assert "Bash(code-review-graph *)" in argv


def test_a_bare_command_is_allowed_too():
    """Probed: `Bash(git status *)` on its own does not cover a bare
    `git status`, so both shapes are emitted."""
    argv, _ = runs.launch_argv("/mem", "p", provider="claude", needs=["git"])

    assert "Bash(git *)" in argv and "Bash(git)" in argv


def test_the_allow_list_never_stands_right_before_the_prompt():
    """`--allowedTools` is variadic exactly like `--add-dir`, and that one
    already swallowed a positional prompt once (commit 8186673). Another flag
    has to follow it."""
    argv, _ = runs.launch_argv("/mem", "the prompt", provider="claude",
                               needs=["git"])

    assert argv[-1] == "the prompt"
    assert argv[-2] == "--", "the separator protects the prompt"
    assert argv[-3] == "/mem" and argv[-4] == "--add-dir", "a flag follows the rules"


def test_bypass_is_a_choice_and_never_the_default():
    """The user asked for a permission bypass to be available. It is — as a
    `--bypass` flag on the run, because `acceptEdits` plus a command list
    covers what a method does, while a bypass covers what it is not supposed
    to do. The worktree is throwaway; the machine is not."""
    plain, _ = runs.launch_argv("/m", "p", provider="claude")
    bypassed, _ = runs.launch_argv("/m", "p", provider="claude", bypass=True)

    assert "--dangerously-skip-permissions" not in plain
    assert "--dangerously-skip-permissions" in bypassed
    assert "--permission-mode" not in bypassed, "a bypass replaces the grant"


def test_the_record_says_how_the_agent_was_authorized():
    """Without it, "the run found nothing" and "the run was not allowed to
    write" are indistinguishable afterwards — which is exactly the position this
    project was in on 2026-09-02."""
    _, info = runs.launch_argv("/m", "p", provider="claude")

    assert info["authorized"] == "grant"


# ------------------------------------------------------- nothing vs. refused

def test_a_run_that_wrote_nothing_is_not_a_run_that_found_nothing(project, make_run):
    """The heart of it. The gate used to read a missing `findings.json` as `[]`,
    write that `[]` back to disk and record `no-findings` — a claim on behalf of
    an agent that had been refused every write."""
    run = make_run()
    run.findings_path.unlink()

    data = ingest.ingest(project, run)

    assert data["noOutput"] is True
    assert not run.findings_path.exists(), "the gate does not invent an empty result"


def test_an_empty_array_the_agent_wrote_is_still_a_real_result(project, make_run):
    """`[]` written by a specialist means "I looked and there is nothing there".
    That one is a measurement and must survive."""
    run = make_run(findings=[])

    data = ingest.ingest(project, run)

    assert not data.get("noOutput")
    assert run.record()["status"] == "no-findings"


def test_wait_records_a_silent_agent_as_failed(project, make_run, monkeypatch, capsys):
    """Exit 0 and nothing on disk. This is the combination that let a chain
    report success twice over while producing no findings at all."""
    run = make_run()
    run.findings_path.unlink()
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    code = cli._wait_for_agent(project, run, ["claude", "p"], project.root, False)
    capsys.readouterr()
    rec = run.record()

    assert code == 1, "the chain has something to stop on"
    assert rec["status"] == "failed"
    assert "no findings.json" in rec["exitReason"]


def test_a_silent_agent_stops_the_chain(project, make_run, monkeypatch, capsys):
    """Continuing would mean the next member judging findings that never came
    into being — the thing `teams.md` §3.5 was written to prevent."""
    run = make_run()
    run.findings_path.unlink()
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    code = cli._wait_for_agent(project, run, ["claude", "p"], project.root, False)
    capsys.readouterr()

    assert code != 0


def test_the_report_names_the_denials(project, make_run, monkeypatch, capsys):
    """A count of refused calls is the difference between "look at the pack" and
    "look at the configuration". Printing it is what turns a mystery into a
    task."""
    run = make_run()
    run.findings_path.unlink()
    rec = run.record()
    rec["agent"] = {**rec["agent"], "denied": {"count": 5, "tools": ["Write", "Bash"]}}
    run.save_record(rec)
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    cli._wait_for_agent(project, run, ["claude", "p"], project.root, False)
    printed = capsys.readouterr().out

    assert "5 tool calls were denied" in printed
    assert "Write" in printed


def test_streaming_is_actually_asked_for():
    """The flags have to reach the command line, not just the provider table.

    They did not, and the whole of Step 3 was dead because of it: `streamArgs`
    was defined in `providers.py` and read by nothing, so `claude -p` ran in
    plain text mode and printed one blob when it was completely finished. The
    orchestrator sat on a silent pipe for twenty minutes, `agent.jsonl` stayed
    empty, and turns, cost and denials were all null.

    The old tests could not catch it: they fed JSONL to the parser directly, so
    they proved the translator worked while nobody was requesting a translation.
    """
    argv, _ = runs.launch_argv("/mem", "p", provider="claude", stream=True)

    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv, "stream-json in print mode is refused without it"


def test_an_attended_run_is_not_asked_to_stream():
    """A terminal shows the agent to a person. Piping JSONL at them instead
    would be a downgrade, not a feature."""
    argv, _ = runs.launch_argv("/mem", "p", provider="claude")

    assert "--output-format" not in argv


def test_the_flags_and_the_dialect_come_from_one_place():
    """Asking for a stream and knowing how to read it is one decision. It was
    two — a table entry and a separate lookup at the launch site — and they
    disagreed silently: the dialect was set, the flags were never sent."""
    args, dialect = providers.streaming("claude")

    assert dialect == "claude-stream-json"
    assert args, "a dialect with no flags is the bug this pairs against"

    argv, _ = runs.launch_argv("/mem", "p", provider="claude", stream=True)
    assert all(a in argv for a in args)


def test_a_runner_with_no_dialect_gets_no_flags():
    """A foreign runner's stream shape cannot be guessed. It falls back to the
    terminal, which is worse UX and still works — unlike a parser that silently
    finds nothing."""
    assert providers.streaming("nosuchrunner") == ([], None)


def test_the_allow_list_is_still_protected_when_streaming():
    """`--allowedTools` is variadic. With streaming on there are two flags that
    could follow it, and the prompt must not be one of them."""
    argv, _ = runs.launch_argv("/mem", "the prompt", provider="claude",
                               needs=["git"], stream=True)

    assert argv[-1] == "the prompt" and argv[-2] == "--"
    assert argv[argv.index("--allowedTools") + 1].startswith("Bash(")
    after = argv[argv.index("--allowedTools"):]
    assert any(a.startswith("--") for a in after[1:]), "a flag closes the rule list"


# ------------------------------------------------------------- event stream

INIT = '{"type":"system","subtype":"init","session_id":"abc-123"}'
TOOL = ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
        '"name":"Write","input":{"file_path":"RUN_DIR/findings.json"}}]}}')
RESULT = ('{"type":"result","subtype":"success","is_error":false,"num_turns":41,'
          '"total_cost_usd":0.84,"session_id":"abc-123","result":"I found one thing.",'
          '"permission_denials":[{"tool_name":"Write"},{"tool_name":"Write"},'
          '{"tool_name":"Bash"}],"usage":{"input_tokens":120,"output_tokens":900}}')


def test_a_denial_is_not_an_error(project):
    """The trap in claude's own contract: `is_error` stays false even when the
    system refused the agent everything. `permission_denials` is the only
    signal, which is why the translator lifts it out rather than leaving it in
    the prose."""
    parsed = events.claude(RESULT)

    assert parsed[0].kind == "done"
    assert parsed[0].denials == ["Write", "Write", "Bash"]
    assert events.denial_count(parsed) == 3, "five refused writes are five, not one"


def test_the_stream_carries_what_the_record_needs():
    got = events.summarize([e for line in (INIT, TOOL, RESULT)
                            for e in events.claude(line)])

    assert got["session"] == "abc-123"
    assert got["turns"] == 41
    assert got["usd"] == 0.84
    assert got["last"] == "I found one thing."
    assert got["tokens"] == {"input": 120, "output": 900}


def test_a_tool_call_says_what_it_is_doing():
    """One line per tool is the whole point: `launching claude…` followed by
    twelve minutes of silence is indistinguishable from a hung process, and the
    user read it as exactly that."""
    parsed = events.claude(TOOL)

    assert parsed[0].kind == "tool" and parsed[0].tool == "Write"
    assert "findings.json" in parsed[0].detail


def test_an_unknown_line_is_dropped_rather_than_fatal():
    """A runner writes things into its stream this tool will never learn.
    Crashing on one would mean a provider upgrade breaking a run that would
    otherwise have finished."""
    assert events.claude("not json at all") == []
    assert events.claude('{"type":"something_new_in_2027"}') == []
    assert events.parse("no-such-dialect", INIT) == []


def test_the_stream_lands_in_the_run(project, make_run, monkeypatch):
    """Next time somebody asks why a run wrote nothing, the answer should be in
    the run — not in `~/.claude/projects`, where it took a transcript dig to
    find."""
    run = make_run()

    def fake_stream(args, cwd=None, env=None, on_line=None, timeout=None):
        for line in (INIT, TOOL, RESULT):
            on_line(line)
        return 0
    monkeypatch.setattr(proc, "stream", fake_stream)

    result = runs.attend(project, run, ["claude", "p"], project.root,
                         dialect="claude-stream-json")
    rec = run.record()

    assert (run.dir / "agent.jsonl").is_file()
    assert (run.dir / "agent.md").read_text(encoding="utf-8").strip() == "I found one thing."
    assert rec["agent"]["turns"] == 41
    assert rec["agent"]["denied"] == {"count": 3, "tools": ["Write", "Bash"]}
    assert rec["agent"]["sessionId"] == "abc-123"
    assert rec["cost"]["usd"] == 0.84
    assert result["denied"] == 3


def test_an_attended_run_keeps_its_terminal(project, make_run, monkeypatch):
    """A pipe would turn an attended run into one that freezes on the first
    question nobody is there to read."""
    run = make_run()
    monkeypatch.setattr(proc, "stream", lambda *a, **k: pytest.fail("must not stream"))
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    runs.attend(project, run, ["claude", "p"], project.root)

    assert "turns" not in run.record()["agent"]


def test_the_streamed_record_still_matches_the_contract(project, make_run,
                                                        monkeypatch, capsys):
    """`agent` and `cost` both have closed key lists in `run.v1`. Three blocks
    have been added to that schema without widening it first; this is the test
    that stops the fourth."""
    run = make_run()

    def fake_stream(args, cwd=None, env=None, on_line=None, timeout=None):
        for line in (INIT, TOOL, RESULT):
            on_line(line)
        return 0
    monkeypatch.setattr(proc, "stream", fake_stream)
    runs.attend(project, run, ["claude", "p"], project.root,
                dialect="claude-stream-json")

    cli.main(["validate", "--run", run.id, "--repo", str(project.root), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert data["recordErrors"] == []


# ----------------------------------------------------------- who paid, who ran

def test_the_credential_comes_from_the_environment(project, make_run, monkeypatch):
    """It used to be derived from `trigger.attended`, which meant claiming a
    chain member runs on an API key. `claude -p` is unattended and runs on the
    same subscription an interactive session does."""
    run = make_run(trigger={"kind": "manual", "attended": False})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    runs.attend(project, run, ["claude", "p"], project.root)

    assert run.record()["cost"]["credential"] == "subscription"


def test_an_api_key_in_the_environment_is_the_one_thing_that_says_api_key(
        project, make_run, monkeypatch):
    run = make_run()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(proc, "attend", lambda args, cwd=None, env=None: 0)

    runs.attend(project, run, ["claude", "p"], project.root)

    assert run.record()["cost"]["credential"] == "api-key"


# --------------------------------------------------------------- a run is a leaf

def test_a_run_does_not_start_runs(project, monkeypatch):
    """One sentence in a brief ("use the PO agent to find out whether…") was
    enough: the reviewer started `agency run po@claude --wait` from inside its
    own session and produced a run with no owner, no terminal and no permission
    to write anything."""
    monkeypatch.setenv(runs.RUN_ENV, "01M1GNCHBDTZ8XM852RS83G8HE")

    with pytest.raises(SystemExit) as e:
        cli.main(["run", "review-graph", "--repo", str(project.root)])

    assert "does not start runs" in str(e.value)


def test_nor_chains(project, monkeypatch):
    monkeypatch.setenv(runs.RUN_ENV, "01M1GNCHBDTZ8XM852RS83G8HE")

    with pytest.raises(SystemExit) as e:
        cli.main(["chain", "review-graph", "po", "--repo", str(project.root)])

    assert "does not start runs" in str(e.value)


def test_the_agent_is_told_so_as_well(project):
    """The refusal is a rule, but a rule the agent runs into is a wasted turn.
    The prompt says it first."""
    member = chains.Member("review-graph")

    prompt = chains.step_prompt("base", member, 1, 2, [], {"findings": 0, "undecided": 0}, None)

    assert "Do not start other runs" in prompt


def test_the_agent_knows_which_run_it_is(project, make_run, monkeypatch):
    """The guard needs the run's process to carry its identity — otherwise it
    can only refuse a command it has no way of recognising."""
    run = make_run()
    seen = {}
    monkeypatch.setattr(proc, "attend",
                        lambda args, cwd=None, env=None: seen.update(env or {}) or 0)

    runs.attend(project, run, ["claude", "p"], project.root,
                chain={"id": "01M1GNCGGXM3Y600AHXYY0V18J"})

    assert seen[runs.RUN_ENV] == run.id
    assert seen[runs.CHAIN_ENV] == "01M1GNCGGXM3Y600AHXYY0V18J"
