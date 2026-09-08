"""The seam over the graph: questions, not a tool's commands.

Graph calls were scattered across five modules and two SKILL.md files, so
swapping the tool began with a grep rather than a contract. The tests here
guard what must still hold after a swap: the verbs return a typed shape, paths
are relative to the repo, a missing capability is an answer rather than an
exception — and a pack can say what it stands on.
"""

from __future__ import annotations

import json

import pytest

from agency import cli, graph, packs, proc


def canned(payload) -> proc.Result:
    return proc.Result(True, 0, json.dumps(payload), "")


@pytest.fixture
def fake_crg(monkeypatch):
    """Stubs the driver's answers per command. What is not stubbed fails."""
    def _install(**by_command: proc.Result):
        def crg(*args: str, cwd=None, timeout: int = 1800) -> proc.Result:
            key = args[0].replace("-", "_")
            return by_command.get(key, proc.Result(False, 1, "", f"{args[0]}: not stubbed"))
        monkeypatch.setattr(proc, "crg", crg)
    return _install


# ---------------------------------------------------------- schopnosti

def test_a_pack_asks_the_driver_for_nothing_invented(project):
    """A pack's policy is a list of verbs, not free text. Were a pack to ask for
    `tests_for` instead of `tests-for`, the doctor would report a missing
    capability on a driver that has it — and nobody would see why."""
    known = set(graph.capabilities())
    for pack in packs.available(project):
        policy = pack.run_policy["graph"]
        if not policy:
            continue
        unknown = [v for v in policy["required"] + policy["optional"] if v not in known]
        assert not unknown, f"{pack.name} asks for unknown verbs: {unknown}"


def test_the_graph_policy_tolerates_the_old_boolean():
    """An older manifest said only yes/no. It must not break — it simply names
    no verbs."""
    assert packs.graph_policy(True) == {"required": [], "optional": []}
    assert packs.graph_policy(False) is None
    assert packs.graph_policy(None) is None
    assert packs.graph_policy({"required": ["changes"]}) == {
        "required": ["changes"], "optional": []}


# ---------------------------------------------------------------- verby

def test_a_missing_index_is_not_an_error(project):
    """"It has not been built yet" is an answer. An exception would turn a
    legitimate state into a failure and the doctor could not advise on it."""
    answer = graph.state(project.root)

    assert answer.ok is True
    assert answer.data["exists"] is False


def test_the_state_notices_an_index_from_another_head(project, fake_crg):
    """An index built at another commit can rest a finding on code that does not
    exist on this branch. Off a human-readable panel that could only be spotted
    by eye."""
    (project.root / ".code-review-graph").mkdir(parents=True, exist_ok=True)
    (project.root / graph.DB_PATH).write_bytes(b"x")
    fake_crg(status=canned({"nodes": 12, "edges": 30, "files": 4,
                            "built_at_commit": "a" * 40, "current_sha": "b" * 40}))

    data = graph.state(project.root).data

    assert data["nodes"] == 12
    assert data["stale"] is True


def test_changes_are_numbers_from_data_not_from_a_sentence(project, fake_crg):
    """The driver's summary is written for a person and changes with its
    wording. The contract stands on the shape of the data."""
    fake_crg(detect_changes=canned({
        "summary": "Analyzed 1 changed file(s):\n  - 1 changed function(s)",
        "risk_score": 0.8,
        "changed_functions": [{"name": f"f{i}"} for i in range(7)],
        "affected_flows": [], "test_gaps": [{"name": "g"}],
        "functions_truncated": True,
    }))

    d = graph.changes(project.root, "b" * 40).data

    assert d == {"functions": 7, "functionsTruncated": True, "flows": 0,
                 "testGaps": 1, "riskScore": 0.8}


def test_locate_returns_a_path_relative_to_the_repo(project, fake_crg):
    """The anchor needs `src/auth.ts`, the driver returns an absolute path.
    Until 1 September 2026 that was fixed by a regex over stdout inside
    `anchor.py`."""
    fake_crg(search=canned({"results": [{
        "name": "getUser", "kind": "Function",
        "file_path": str(project.root / "src" / "auth.ts"),
        "line_start": 1, "line_end": 4, "is_test": False,
    }]}))

    found = graph.locate(project.root, "getUser").data

    assert found[0]["file"] == "src/auth.ts"
    assert found[0]["line"] == 1


def test_a_driver_failure_is_an_answer_not_an_exception(project, fake_crg):
    """A run with no graph signal is a legitimate result. The caller picks what
    to do about it — falling over is allowed only where a finding rests on it."""
    fake_crg()

    answer = graph.changes(project.root, "b" * 40)

    assert answer.ok is False
    assert "not stubbed" in answer.error
    assert answer.data is None


def test_an_unknown_direction_is_not_asked_of_the_graph(project):
    """A typo in the direction is the caller's mistake, not the graph's answer."""
    with pytest.raises(SystemExit):
        graph.neighbors(project.root, "getUser", direction="sideways")


# ------------------------------------------------------------ worktree

def test_preparing_with_no_index_copies_nothing(project, tmp_path, fake_crg):
    fake_crg()
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(project.root / graph.DB_PATH, wt)

    assert info["action"] == "missing"
    assert not (wt / graph.DB_PATH).exists()


def test_preparing_copies_the_index_and_tops_it_up(project, tmp_path, fake_crg):
    """The `copy-db` strategy: `build` is never run in a worktree — it would
    rebuild the whole repo for a state that is thrown away shortly after."""
    fake_crg(update=proc.Result(True, 0, "ok", ""), __version__=None)
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(src, wt)

    assert info["action"] == "update"
    assert (wt / graph.DB_PATH).read_bytes() == b"index"


def test_preparing_in_the_project_itself_does_not_copy_the_index_onto_itself(project, fake_crg):
    """A pack with a graph and no worktree works in the project — the index is
    already in place. Copying a file onto itself is a hard error on Windows, not
    an edge case."""
    fake_crg(update=proc.Result(True, 0, "ok", ""))
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")

    info = graph.prepare(src, project.root)

    assert info["action"] == "update"
    assert src.read_bytes() == b"index"


def test_preparing_does_not_update_when_the_project_does_not_want_it(project, tmp_path, fake_crg):
    fake_crg()
    src = project.root / graph.DB_PATH
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"index")
    wt = tmp_path / "wt"
    wt.mkdir()

    info = graph.prepare(src, wt, on_stale="ignore")

    assert info["action"] == "reused"


# ----------------------------------------------------------------- CLI

def test_agency_graph_says_what_the_driver_can_do(project, capsys):
    """Half of the graph's use lives in the prompt and the Python facade does
    not cover it. This is that door — and it is also where the seam gets tested
    on every run."""
    assert cli.main(["graph", "capabilities", "--repo", str(project.root)]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["driver"] == graph.DRIVER
    assert "tests-for" in data["capabilities"]
    assert data["workspaceStrategy"] == "copy-db"


def test_agency_graph_returns_a_non_zero_code_when_it_could_not_ask(project, capsys, fake_crg):
    fake_crg()

    code = cli.main(["graph", "changes", "--base", "b" * 40, "--repo", str(project.root)])

    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["ok"] is False
    assert data["error"]
