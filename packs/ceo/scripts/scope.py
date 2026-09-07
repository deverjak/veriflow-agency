#!/usr/bin/env python3
"""What a CEO run is about: the live bets.

Run by the core during preparation, never by the agent — `scope` in
`pack.json`. It prints `[{"kind": "bet", "ref": "<slug>"}, …]` on stdout and
nothing else; the core intersects that with the `subject` of everything the
project already knows, and what falls out is `evidence/known-here.json`. Before
this existed that file was empty for every run of this pack, because the only
scope the core could speak was files and symbols out of a code graph, and this
pack has no graph.

The bets are in `strategy.md`, the register the pack writes itself. Its `Ref:`
line is the bet's identity — the same string the bet's own `subject.ref`
carries — and a bet whose `Status:` says `killed` is not live and is left out:
a run should be handed what was decided about the bets it is still running, not
about the ones the founder ended in March.

Failing is not fatal. A scope that cannot be gathered costs the run its
narrowed memory and nothing else, so anything unreadable here is one bet fewer
rather than an exit code — the founder's own markdown is not a data format and
must not be able to stop a run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PAGE = Path(".agency/knowledge/pages/ceo/strategy.md")

#: The bet's identity, as `references/method.md` prescribes it. Deliberately
#: strict: a ref is compared as a string, so `Regional Distribution` and
#: `regional-distribution` would be two different bets and neither would match
#: what the last run wrote.
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")

_REF = re.compile(r"^\s*Ref:\s*(.+?)\s*$", re.M)
_STATUS = re.compile(r"^\s*Status:\s*(.+?)\s*$", re.M)


def bets(text: str) -> list[str]:
    """The slugs of the live bets, in the order the page lists them."""
    found: list[str] = []
    # One block per bet — the page starts with a positioning paragraph, so
    # everything before the first heading is not a bet and is dropped.
    for block in re.split(r"^###\s", text, flags=re.M)[1:]:
        ref = _REF.search(block)
        if not ref or not SLUG.match(ref.group(1)):
            continue
        status = _STATUS.search(block)
        if status and status.group(1).strip().lower().startswith("killed"):
            continue
        if ref.group(1) not in found:
            found.append(ref.group(1))
    return found


def main() -> int:
    try:
        text = PAGE.read_text(encoding="utf-8")
    except OSError:
        # No register yet — the first run of this pack, which has no bets to
        # be about. An empty scope is an answer, not an error.
        text = ""
    json.dump([{"kind": "bet", "ref": slug} for slug in bets(text)], sys.stdout,
              ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
