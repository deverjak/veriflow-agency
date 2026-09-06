"""The house rules, and where they contradict the specialists.

`CLAUDE.md` reaches the agent without the runner's help, so the only thing
Agency can honestly do about it is notice one collision — the project
forbidding a tool a hired pack stands on — and say so before a run happens
under it. These tests are mostly about the other half of that promise: what
must NOT be reported. Every false positive here was taken from a real file,
because a warning that fires on ordinary prose is a warning nobody reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from agency import config, instructions
from agency.cli import main

from conftest import install_pack

GRAPH_PACK = {"requires": ["code-review-graph"],
              "needs": ["code-review-graph", "git"]}


def rules(repo: Path, text: str, name: str = "CLAUDE.md") -> Path:
    (repo / name).write_text(text, encoding="utf-8")
    return repo / name


def hits(repo: Path, tool: str = "code-review-graph") -> list[dict]:
    return instructions.conflicts(repo, {tool: ["review-graph"]})


def test_a_rule_against_a_tool_the_pack_stands_on_is_found(repo: Path):
    rules(repo, "# Project\n\n"
                "Graphify is the only code-intelligence tool here — do not install, "
                "query, or document `code-review-graph`.\n")

    found = hits(repo)

    assert len(found) == 1
    assert found[0]["tool"] == "code-review-graph"
    assert found[0]["packs"] == ["review-graph"]
    assert found[0]["file"] == "CLAUDE.md"
    assert found[0]["line"] == 3
    assert "do not install" in found[0]["rule"]


def test_the_rule_is_found_when_the_sentence_is_wrapped_across_lines(repo: Path):
    """The real one wrapped mid-sentence: the prohibition sat on line 211 and
    the tool it forbids on 212. Matching physical lines would have missed the
    only collision this check exists for."""
    rules(repo, "# Project\n\n"
                "It is the only code-intelligence tool in this project — do not\n"
                "install, query, or document GitNexus or\n"
                "`code-review-graph`.\n")

    found = hits(repo)

    assert len(found) == 1
    # Where the sentence starts — that is the line the founder opens.
    assert found[0]["line"] == 3


def test_a_fact_about_a_tool_is_not_a_rule_against_it(repo: Path):
    """`gh pr create --body` never sees a template — a prohibition word and a
    tool in one sentence, forbidding nothing. The order is what separates
    them: a directive names its object after the prohibition."""
    rules(repo, "# Project\n\n"
                "`code-review-graph` never sees the working tree - it reads the "
                "committed index.\n")

    assert hits(repo) == []


def test_a_tool_named_in_prose_rather_than_as_a_command_is_not_a_rule(repo: Path):
    """Taken from a real `AGENTS.md`: "Do not recursively survey `docs/`, git
    history, or unrelated areas." A prohibition, containing the word `git`,
    forbidding nothing about the tool."""
    rules(repo, "# Project\n\n"
                "Do not recursively survey `docs/`, git history, or unrelated areas.\n")

    assert instructions.conflicts(repo, {"git": ["review-graph"]}) == []


def test_a_heading_does_not_lend_its_prohibition_to_the_paragraph_below(repo: Path):
    rules(repo, "# Project\n\n"
                "### Never reset the database by hand\n\n"
                "Build the index with `code-review-graph build` first.\n")

    assert hits(repo) == []


def test_a_command_inside_a_fence_is_an_example_not_an_instruction(repo: Path):
    rules(repo, "# Project\n\n"
                "How the index is built:\n\n"
                "```bash\n"
                "# do not run `code-review-graph build` twice\n"
                "code-review-graph build .\n"
                "```\n")

    assert hits(repo) == []


def test_agents_md_is_read_too_because_codex_obeys_it(repo: Path):
    rules(repo, "Never query `code-review-graph` here.\n", name="AGENTS.md")

    found = hits(repo)

    assert [h["file"] for h in found] == ["AGENTS.md"]


def test_doctor_warns_without_calling_the_run_broken(repo: Path, capsys):
    project = config.discover(repo)
    install_pack(project, "review-graph", GRAPH_PACK)
    rules(repo, "# Project\n\nDo not query `code-review-graph`.\n")

    main(["doctor", "--repo", str(repo), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]

    row = next(c for c in checks if c["name"] == "rules vs code-review-graph")
    assert row["ok"] is False
    # Not fatal: the project may be right, and the runner does not get to pick
    # which of the two instruction sets gives.
    assert row["fatal"] is False
    assert "review-graph" in row["detail"] and "CLAUDE.md:3" in row["detail"]


def test_doctor_says_it_read_the_rules_when_they_agree(repo: Path, capsys):
    project = config.discover(repo)
    install_pack(project, "review-graph", GRAPH_PACK)
    rules(repo, "# Project\n\nRun `npm run verify` before a pull request.\n")

    main(["doctor", "--repo", str(repo), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]

    row = next(c for c in checks if c["name"] == "house rules")
    assert row["ok"] is True and row["fatal"] is False
    assert "CLAUDE.md" in row["detail"]


def test_a_project_without_instructions_gets_no_row_about_them(repo: Path, capsys):
    project = config.discover(repo)
    install_pack(project, "review-graph", GRAPH_PACK)

    main(["doctor", "--repo", str(repo), "--json"])
    checks = json.loads(capsys.readouterr().out)["checks"]

    assert not [c for c in checks if c["name"].startswith(("house rules", "rules vs"))]


def test_a_run_under_a_conflicting_rule_records_that_it_happened(project, make_run):
    """`doctor` reports a collision BEFORE a run; nothing recorded that the run
    then went ahead under one anyway — and that is the run whose findings look
    inexplicably thin six weeks later."""
    from agency import packs, runs

    install_pack(project, "graphy", GRAPH_PACK)
    rules(project.root, "# Project\n\nDo not query `code-review-graph`.\n")
    run = make_run()

    runs.write_context(run, packs.load("graphy", project), {"kind": "workspace"},
                       project.root, [], 0)

    # A number, not the quoted sentence: the record counts, `doctor` explains.
    assert run.record()["context"]["conflicts"] == 1
