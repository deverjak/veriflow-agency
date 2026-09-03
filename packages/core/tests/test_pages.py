"""Pack pages: curated knowledge, written by the specialist, owned by the project.

Unlike the ledger, nobody generates these — a human or an agent writes them
by hand. That gives them a different sensitivity than findings: the bundle
must never overwrite them, and a pack running in a worktree must never be
handed a path that gets deleted with the worktree after the run.

Pages are plain markdown with one convention — a leading
`Last reviewed: <date>` line — not a parsed format. A page that predates this
convention, or one a human wrote free-hand, must never be reported as
"broken".
"""

from __future__ import annotations

import json

from agency import knowledge, packs, runs

from conftest import install_pack

FRESH = """Last reviewed: 2099-01-01

# What is covered and what is not

Card payment passed. 3D Secure untested — the sandbox cannot do it.
"""

OLD = """Last reviewed: 2020-01-01

# What is covered and what is not

Card payment passed. 3D Secure untested — the sandbox cannot do it.
"""

PLAIN = """# Known regressions

The cart empties after login. It came back a second time.
"""


def write_page(project, pack: str, name: str, text: str):
    d = knowledge.pages_dir(project, pack)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(text, encoding="utf-8")
    return d / f"{name}.md"


# ------------------------------------------------------------------ reading

def test_a_page_carries_whether_it_is_stale(project):
    install_pack(project, "qa")
    write_page(project, "qa", "coverage", FRESH)
    write_page(project, "qa", "old", OLD)

    found = {p["id"]: p for p in knowledge.pages(project, "qa")}

    assert found["coverage"]["stale"] is False
    assert found["old"]["stale"] is True
    assert "3D Secure" not in found["coverage"]["title"], "the title is the heading, not the body"


def test_a_page_with_no_last_reviewed_line_is_not_broken(project):
    """Nothing here is ever reported as an error — a page a human wrote by
    hand must never look broken just because it skips a convention."""
    install_pack(project, "qa")
    write_page(project, "qa", "known-regressions", PLAIN)

    page = knowledge.pages(project, "qa")[0]

    assert page["stale"] is False
    assert page["title"] == "Known regressions", "the page carries its own name in the heading"


def test_pages_summary_counts_by_pack(project):
    install_pack(project, "qa")
    write_page(project, "qa", "coverage", FRESH)
    write_page(project, "qa", "old", OLD)

    summary = knowledge.pages_summary(project)

    assert summary["total"] == 2
    assert summary["stale"] == 1
    assert summary["byPack"] == {"qa": 2}


# ------------------------------------------------------------------ location

def test_pages_live_under_the_bundle(project):
    """No override: a pack's pages are always in `.agency/knowledge/pages/<pack>/`."""
    install_pack(project, "qa")
    install_pack(project, "po")

    assert knowledge.pages_dir(project, "qa") == \
        project.agency_dir / knowledge.BUNDLE / knowledge.PAGES / "qa"
    assert knowledge.pages_dir(project, "po") == \
        project.agency_dir / knowledge.BUNDLE / knowledge.PAGES / "po"


def test_the_bundle_does_not_overwrite_pages(project, make_run):
    """`findings/` is generated, `pages/` is written by hand. A generator
    that deletes what it did not generate would swallow the first
    specialist's conclusion."""
    install_pack(project, "qa")
    page = write_page(project, "qa", "coverage", FRESH)
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")

    result = knowledge.bundle(project)

    assert result["removed"] == []
    assert page.read_text(encoding="utf-8") == FRESH


def test_the_overview_links_to_pages(project, make_run):
    install_pack(project, "qa")
    write_page(project, "qa", "coverage", FRESH)
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    knowledge.bundle(project)

    index = (project.agency_dir / knowledge.BUNDLE / "index.md").read_text(encoding="utf-8")

    assert "## Pages" in index and "### qa" in index
    assert "(pages/qa/coverage.md)" in index
    assert (project.agency_dir / knowledge.BUNDLE / "pages/qa/coverage.md").is_file()


# ------------------------------------------------------------------ into a run

def test_pages_go_into_a_run_with_no_cap(project, make_run):
    """A specialist's own conclusions are not background, they are input.
    Trimming them means letting it arrive at one of them a second time."""
    install_pack(project, "qa")
    write_page(project, "qa", "coverage", FRESH)
    write_page(project, "qa", "known-regressions", PLAIN)
    run = make_run(findings=[], pack="qa")

    stats = knowledge.for_run(project, run)

    known = json.loads((run.dir / "evidence" / "known-pages.json").read_text(encoding="utf-8"))
    assert stats["knownPages"] == 2
    assert {p["id"] for p in known} == {"coverage", "known-regressions"}


def test_page_memory_does_not_belong_in_the_graph_block(project):
    """The same trap as `knownFindings`: `run.graph` has a closed key list in
    `run.v1`."""
    assert "knownPages" in runs.MEMORY_STATS


def test_a_run_in_a_worktree_gets_no_path_to_pages(project, make_run):
    """A worktree stands on the pull request's head and `agency run` removes
    it afterwards. A path where a pack would write conclusions that vanish
    right after is worse than no path."""
    install_pack(project, "review-graph", {"target": "pull-request", "worktree": True})
    install_pack(project, "qa", {"target": "workspace", "worktree": False})
    run = make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA")
    target = {"kind": "pull-request", "pr": 1, "headRefOid": "a" * 40}

    review_pack = packs.load("review-graph", project)
    runs.write_context(run, review_pack, target, project.root, [], 0,
                       worktree_owned=True)
    in_worktree = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))

    qa_pack = packs.load("qa", project)
    runs.write_context(run, qa_pack, target, project.root, [], 0,
                       worktree_owned=False)
    in_project = json.loads((run.dir / "context.json").read_text(encoding="utf-8"))

    assert in_worktree["pages"] is None
    assert in_project["pages"].endswith("knowledge/pages/qa") or in_project["pages"].endswith("knowledge\\pages\\qa")
