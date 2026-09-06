"""The project's own agent instructions — and the one collision worth naming.

`CLAUDE.md` (and `AGENTS.md`, which is what Codex reads) is loaded by the
runner itself, from the directory the run starts in. Agency neither passes it
nor overrides it, and v1 decided on purpose not to grow a second rules file:
the project's rules stay where the project already keeps them.

The consequence is that a specialist arrives holding two sets of instructions
— the pack's method and the house rules — and nothing notices when they
disagree. Most disagreements are a matter of taste and belong to the founder.
One is not: the house forbidding a tool a hired pack cannot work without. Then
the specialist is hired for a method the project has banned, and the run
either breaks a rule or quietly does less; neither shows up anywhere. That is
what this module finds, so `agency doctor` can say it before twenty minutes of
work happen under it.

It reads for one thing and reports it verbatim. Nothing here interprets the
project's rules, and nothing acts on them — the sentence is quoted, the file
and line are named, and the decision stays with the person who wrote it.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Root instruction files, in the order a report should mention them. Both are
#: read: a project driving `claude` and `codex` has two of them, and a rule
#: that only ever lands in one is still a rule the other runner obeys.
#: Nested `CLAUDE.md` files (a package's own) are deliberately out of scope —
#: they are loaded on demand, for a subtree, and quoting one as "the project's
#: rule" would overstate what it is.
FILES = ("CLAUDE.md", "AGENTS.md")

#: A rule, not a remark. Both shapes live in the same real file:
#:
#:     "…do not install, query, or document GitNexus or `code-review-graph`"
#:     "`gh pr create --body` never sees a template - put the line in…"
#:
#: The first forbids a tool. The second is a fact about how a tool behaves,
#: and a check that reported it would be ignored by its second week. What
#: separates them is order: a directive names the thing it forbids *after* the
#: prohibition, a description names its subject first. So the tool has to
#: appear downstream of the marker in the same sentence — cheap, and it is the
#: grammar rather than a keyword list doing the work.
PROHIBITION = re.compile(
    r"\b(?:do not|don't|do NOT|never|must not|must never|no longer use|"
    r"stop using|nepoužívej|nepoužívat|nespouštěj|neinstaluj|nikdy|zakázáno)\b",
    re.IGNORECASE)

#: Where one sentence ends and the next begins — including the boundaries
#: markdown draws without punctuation. A heading ("### Never `db:reset` by
#: hand") sits directly above a paragraph that mentions `npm`, and a table row
#: sits directly above another one; treating either pair as one sentence
#: invents a prohibition nobody wrote.
BREAK = re.compile(r"(?<=[.!?;])\s+|\n\s*\n|\n(?=\s*(?:[#>|*+]|-\s|\d+[.)]\s))")

#: Fenced blocks are examples, not instructions. `graphify update .` inside a
#: shell fence is the project showing a command, and the prose above it already
#: carries whatever rule applies.
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)

#: Inline code — where a tool is named *as a tool*. The second half of the
#: grammar, and it came from the second false positive rather than from
#: taste. Probed against a real `AGENTS.md`:
#:
#:     "Do not recursively survey `docs/`, git history, or unrelated areas…"
#:
#: A prohibition, and it does contain the word `git`, and it forbids nothing
#: about the tool — "git history" is a noun phrase. A project writes a tool it
#: means as a command in backticks; it writes prose in prose. The trade is
#: deliberate: a rule phrased entirely without code formatting is missed. A
#: miss costs one warning nobody sees; noise costs the whole check, because a
#: doctor that cries wolf on a real file stops being read.
CODE = re.compile(r"`([^`]+)`")

#: How much of the sentence a report quotes. Enough to recognise the rule and
#: go read it; the file and line are there for the rest.
QUOTE = 110


def paths(root: Path) -> list[Path]:
    """The instruction files this project actually has."""
    return [root / name for name in FILES if (root / name).is_file()]


def _blank_out(text: str) -> str:
    """Fenced code gone, line count intact — a report that cites a line has to
    cite the line the founder will find when they open the file."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _sentences(text: str):
    """(line, sentence) for every sentence in the file, in order."""
    text = _blank_out(text)
    at = 0
    for piece in BREAK.split(text):
        if piece is None:
            piece = ""
        start = text.find(piece, at) if piece else at
        if start < 0:
            start = at
        at = start + len(piece)
        stripped = piece.strip()
        if stripped:
            yield text.count("\n", 0, start) + 1, " ".join(stripped.split())


def _mentions(tool: str) -> re.Pattern:
    # Not `\b`: `gh` inside `gh-pages` and `code-review-graph` inside
    # `code-review-graph-extra` are different tools, and a hyphen is a word
    # character to nobody but a regex.
    return re.compile(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", re.IGNORECASE)


def conflicts(root: Path, tools: dict[str, list[str]]) -> list[dict]:
    """Sentences in the project's instructions that forbid a tool a pack needs.

    `tools` maps a tool to the packs that require it, because "which
    specialist does this break" is the first thing anyone asks and the answer
    is already known here.

    A hit is a suspicion, not a verdict: it is one sentence, quoted, with its
    file and line. Everything past that — was the rule meant this way, is it
    still true, does the pack or the rule give — is the founder's call, and
    the report says so rather than guessing.
    """
    found: list[dict] = []
    if not tools:
        return found

    patterns = {tool: _mentions(tool) for tool in tools}
    for path in paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line, sentence in _sentences(text):
            rule = PROHIBITION.search(sentence)
            if not rule:
                continue
            # Only what the sentence itself marks as a command, and only what
            # comes after the prohibition — the two halves of the grammar.
            spans = [m.group(1) for m in CODE.finditer(sentence, rule.end())]
            for tool, pattern in patterns.items():
                if not any(pattern.search(s) for s in spans):
                    continue
                found.append({
                    "tool": tool,
                    "packs": list(tools[tool]),
                    "file": path.name,
                    "line": line,
                    "rule": sentence if len(sentence) <= QUOTE
                            else sentence[:QUOTE - 1].rstrip() + "…",
                })
    return found
