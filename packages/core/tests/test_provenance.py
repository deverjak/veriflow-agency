"""Evidence that cites a command it never ran.

`evidence[].source` is a free string in `finding.v1`, so a pack could write
`"source": "agency graph impact --depth 2"` without ever having run it, and
nothing — not the schema, not the gate — could tell. The quietest hole in the
whole gate, and the runner itself already knows the answer: it can be asked to
report every tool call it makes.

What these tests mostly guard is the OTHER half, because a provenance check
that drops honest findings is worse than none at all: a source that points at
a document must always pass, and a run where nothing was recording must not be
judged at all.
"""

from __future__ import annotations

import json

from agency import ingest, runs
from agency.util import write_json

from conftest import make_finding


def _calls(run, *commands: str) -> None:
    """The file the PostToolUse hook would have left behind."""
    path = run.dir / runs.TOOL_CALLS
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for c in commands:
            f.write(json.dumps({"at": runs.now(), "tool": "Bash", "command": c}) + "\n")


def _with_source(project, run_id, source: str) -> dict:
    f = make_finding(project, run_id)
    f["evidence"] = [{"kind": "graph", "detail": "no caller checks the session",
                      "source": source}]
    return f


def test_a_cited_command_that_ran_passes(project, make_run):
    run = make_run(findings=[_with_source(project, "x", "agency graph impact --depth 2")])
    _calls(run, "agency graph impact --files src/auth.ts --depth 3")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1, "flags are not compared, only the command"


def test_a_cited_command_that_never_ran_is_dropped(project, make_run):
    """The claim this exists to catch: the graph was cited, the graph was never
    opened."""
    run = make_run(findings=[_with_source(project, "x", "agency graph impact --depth 2")])
    _calls(run, "git diff --stat")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 0
    assert result["dropped"][0]["reason"] == "unproven-source"
    assert run.record()["gatedBy"] == {"unproven-source": 1}


def test_a_source_that_is_a_document_always_passes(project, make_run):
    """`CLAUDE.md#rules-that-will-bite-you` is a pointer to something readable,
    not a claim that something ran. An early rule keyed on "contains a space"
    and would have dropped this."""
    run = make_run(findings=[
        _with_source(project, "x", "CLAUDE.md#rules-that-will-bite-you")])
    _calls(run, "git diff --stat")

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1


def test_without_the_file_nothing_is_judged(project, make_run):
    """An attended run, a codex run, a run whose hook never fired. No file means
    nobody was recording — and a gate that read that as "ran nothing" would drop
    every honest finding in all of them."""
    run = make_run(findings=[_with_source(project, "x", "agency graph impact")])

    result = ingest.ingest(project, run)

    assert result["counts"]["kept"] == 1
    assert run.record()["context"]["toolCalls"] is False


def test_the_record_says_whether_anyone_was_watching(project, make_run):
    """Two populations must not look alike: `unproven-source` never appearing
    should read as "nobody was checked", not as "nobody lies"."""
    run = make_run(findings=[_with_source(project, "x", "agency graph impact")])
    _calls(run, "agency graph impact --files src/auth.ts")

    ingest.ingest(project, run)

    assert run.record()["context"]["toolCalls"] is True


# ------------------------------------------------------------- the hook itself

def test_the_hook_records_the_command_the_runner_reports(project, make_run):
    """The payload shape is the runner's, probed on 2026-09-06 rather than
    assumed — `tool_input.command` is the literal command line, and there is no
    exit code in it."""
    run = make_run()

    row = runs.record_tool_call(run.dir, {
        "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "agency graph impact  --files  src/x.ts"},
        "tool_response": {"stdout": "{}", "stderr": ""},
    })

    assert row["command"] == "agency graph impact --files src/x.ts"
    assert ingest.commands_run(run) == ["agency graph impact --files src/x.ts"]


def test_a_call_with_no_command_is_not_evidence(project, make_run):
    """A `Read` is not proof that a command ran, so it is not written at all —
    a file of everything the agent touched would be a different file with a
    different purpose."""
    run = make_run()

    assert runs.record_tool_call(run.dir, {
        "tool_name": "Read", "tool_input": {"file_path": "src/auth.ts"}}) is None
    assert ingest.commands_run(run) is None, "and no empty file is left behind"


def test_the_hook_travels_as_an_argument_not_as_a_file(project, make_run):
    """R5: nothing is written into the project and nothing is installed into
    the user's harness. The RUN_DIR is baked into the hook's own command, so it
    needs no environment variable to find the run it belongs to."""
    run = make_run()

    settings = runs.hook_settings(run.dir, "claude")
    argv, _ = runs.launch_argv("/mem", "p", provider="claude", settings=settings)

    assert "--settings" in argv
    hook = json.loads(argv[argv.index("--settings") + 1])
    command = hook["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "agency hook tool-call" in command and run.id in command


def test_a_runner_that_cannot_take_a_hook_says_so(project, make_run):
    """codex reads its hooks from a config file in the project — which is the
    thing R5 forbids — so it gets no hook rather than a file it never asked
    for, and its runs are simply never provenance-checked."""
    run = make_run()

    assert runs.hook_settings(run.dir, "codex") is None


# ------------------------------------------------ the second chance (Stop hook)

def _stop(run, project) -> tuple[int, str]:
    """The Stop hook, called the way the runner calls it."""
    import io
    import sys as _sys
    from agency import cli
    from agency.util import write_json as _write

    _write(run.dir / "context.json", {"project": {"root": str(project.root)}})
    stderr, _sys.stderr = _sys.stderr, io.StringIO()
    stdin, _sys.stdin = _sys.stdin, io.StringIO("{}")
    try:
        code = cli.main(["hook", "stop", "--run-dir", str(run.dir),
                         "--repo", str(project.root)])
        return code, _sys.stderr.getvalue()
    finally:
        _sys.stderr, _sys.stdin = stderr, stdin


def test_a_broken_findings_file_is_handed_back_while_it_can_be_fixed(project, make_run):
    """`counts.gated` is a total loss: the agent writes, exits, the gate drops
    it, nobody repeats the run. Exit 2 gives it back while the context that
    wrote it is still alive."""
    f = make_finding(project, "x")
    del f["score"]
    run = make_run(findings=[f])

    code, said = _stop(run, project)

    assert code == 2
    assert "score" in said
    assert run.record()["agent"]["stopBlocks"] == 1


def test_a_finding_pointing_at_nothing_is_handed_back_too(project, make_run):
    """The other check that needs only this run: does the anchor exist at the
    commit under review."""
    run = make_run(findings=[make_finding(project, "x",
                                          anchor={"file": "src/nowhere.ts"})])

    code, said = _stop(run, project)

    assert code == 2 and "does not exist" in said


def test_a_good_findings_file_simply_passes(project, make_run):
    run = make_run()

    code, said = _stop(run, project)

    assert code == 0 and said == ""
    assert "stopBlocks" not in (run.record().get("agent") or {})


def test_the_third_stop_passes_whatever_it_says(project, make_run):
    """A hook that can block forever produces a run that never finishes, which
    costs more than the findings it was trying to save."""
    f = make_finding(project, "x")
    del f["score"]
    run = make_run(findings=[f])

    assert _stop(run, project)[0] == 2
    assert _stop(run, project)[0] == 2
    assert _stop(run, project)[0] == 0, "the third time the gate has it"
    assert run.record()["agent"]["stopBlocks"] == 2
