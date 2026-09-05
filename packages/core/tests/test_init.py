"""`agency init` — the bootstrap.

The one command that puts a file into somebody else's project, so the tests
are about restraint as much as about copying: it must land where the runner
and Claude Code both already look, it must not touch what is already there,
and running it twice must be the same as running it once.
"""

from __future__ import annotations

import json
from pathlib import Path

from agency import config, packs
from agency.cli import main


def test_seeds_the_author_pack_where_a_skill_lives(repo: Path):
    project = config.discover(repo)
    assert packs.available(project) == []

    result = packs.seed(project)

    assert result["created"] is True
    assert result["path"] == ".claude/skills/agency-author"
    skill = repo / ".claude" / "skills" / "agency-author"
    assert (skill / "pack.json").is_file()
    assert (skill / "SKILL.md").is_file()
    # The references travel with it — the dimensions argument is the part of
    # this pack that is actually hard to reproduce.
    assert (skill / "references" / "dimensions.md").is_file()

    # And the runner finds it as a pack, by the same route as any other.
    hired = packs.available(project)
    assert [p.name for p in hired] == ["author"]
    assert hired[0].run_policy["prompt"] == "required"


def test_running_it_again_leaves_the_projects_own_copy_alone(repo: Path):
    project = config.discover(repo)
    packs.seed(project)

    skill = repo / ".claude" / "skills" / "agency-author"
    (skill / "SKILL.md").write_text("# ours now\n", encoding="utf-8")

    again = packs.seed(project)

    assert again["created"] is False
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "# ours now\n"


def test_force_copies_over_it_without_deleting_what_the_project_added(repo: Path):
    project = config.discover(repo)
    packs.seed(project)

    skill = repo / ".claude" / "skills" / "agency-author"
    (skill / "SKILL.md").write_text("# ours now\n", encoding="utf-8")
    (skill / "references" / "ours.md").write_text("kept\n", encoding="utf-8")

    forced = packs.seed(project, force=True)

    assert forced["created"] is True
    assert (skill / "SKILL.md").read_text(encoding="utf-8") != "# ours now\n"
    assert (skill / "references" / "ours.md").is_file()


def test_run_records_are_ignored_but_an_existing_answer_is_not_rewritten(repo: Path):
    project = config.discover(repo)

    assert packs.ignore_run_records(project) is True
    ignore = repo / ".agency" / ".gitignore"
    assert "runs/" in ignore.read_text(encoding="utf-8")

    ignore.write_text("# theirs\n", encoding="utf-8")
    assert packs.ignore_run_records(project) is False
    assert ignore.read_text(encoding="utf-8") == "# theirs\n"


def test_cli_reports_what_it_did_and_what_to_run_next(repo: Path, capsys):
    assert main(["init", "--repo", str(repo), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["pack"]["created"] is True
    assert data["gitignore"] is True
    assert data["next"].startswith("agency run author")
    assert ".claude/skills/agency-author/pack.json" in data["pack"]["files"]

    # Second time: nothing created, and it still exits 0 — this is a command
    # somebody runs when they are not sure whether they already have.
    assert main(["init", "--repo", str(repo), "--json"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["pack"]["created"] is False
    assert again["gitignore"] is False


def test_doctor_points_at_the_bootstrap_when_the_project_has_no_packs(repo: Path, capsys):
    main(["doctor", "--repo", str(repo)])
    assert "agency init" in capsys.readouterr().out


def test_the_author_pack_actually_ships_in_the_wheel():
    """A dev checkout finds `packs/` next to the source, so every test above
    passes whether or not the wheel carries it — and the breakage would only
    show up on somebody else's machine, after `uv tool install`, as an init
    that cannot find its own pack. This is the line that notices."""
    core = Path(__file__).resolve().parents[1]
    pyproject = (core / "pyproject.toml").read_text(encoding="utf-8")
    assert '"../../packs/author" = "agency/_bundled/packs/author"' in pyproject


def test_doctor_does_not_call_a_missing_remote_fatal_after_init(repo: Path, capsys):
    """The bootstrapped state has to be a working state.

    `author` reads the working tree and needs `git`, nothing else. A project
    with no remote is a perfectly good project for it — and telling somebody
    who has just run `agency init` that a run would fail is how the first two
    minutes with this tool go wrong.
    """
    project = config.discover(repo)
    packs.seed(project)

    code = main(["init", "--repo", str(repo)])  # noqa: F841 — silence the copy output
    capsys.readouterr()

    assert main(["doctor", "--repo", str(repo), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    slug = next(c for c in report["checks"] if c["name"] == "repo slug")
    assert slug["ok"] is True
    assert report["ok"] is True
