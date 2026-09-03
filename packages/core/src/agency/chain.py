"""A chain of specialists — run, wait, hand over, next.

A chain is **not a conversation**: it is a sequence of runs whose members pass
each other files, not messages in a session. Everything the agents "say" is
either an append-only event on a finding (`decisions.jsonl`) or a file a run
left behind (`handoff.md`, `summary.md`, `findings.json`) — so it can be
replayed event by event and defended afterwards.

What this module **does not do**, and must not:

  * **It does not decide the order.** A person writes the list of members. No
    LLM orchestrator between runs — judgement belongs inside runs, because that
    is where it is recorded, attributed and paid for once.
  * **It does not write the prompt's content.** The core owns the template
    (`step_prompt`), but the sentences in it are the upstream agent's own words
    from its `handoff.md`.
  * **It does not resurrect an interrupted chain.** The runs are recorded and
    can be finished by hand.

A chain runs on one provider (`--provider`, default `claude`) — one binary,
one credential, one set of terminal quirks. What holds it together is the
`chain` block in `run.json`, not the order of directories.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import knowledge
from .config import Project
from .util import posix, write_json

#: How much of a handoff goes into the next member's prompt. A ceiling in
#: bytes, and a generous one, because a handoff is not a kick-off line — it is
#: the brief.
HANDOFF_BYTES = 16_000


@dataclass
class Member:
    """One chain member — a pack name, as `agency chain` received it."""
    pack: str

    @property
    def label(self) -> str:
        return self.pack


def resolve(refs: list[str]) -> list[Member]:
    return [Member(ref) for ref in refs]


def target(project: Project, pr: int | None, latest_merged: bool,
           since: str | None = None) -> dict:
    """What the whole chain is about — resolved once, before the first step.

    This is the difference between a team and several runs that happen to
    share an id. Members keep their own idea of what to DO with a target — a
    reviewer reads the diff, QA runs the application — but not of what the
    target IS.
    """
    from . import runs as _runs
    if pr is not None or latest_merged:
        return _runs.resolve_target(project, pr, latest_merged)
    return _runs.resolve_workspace_target(project, since)


def member_target(shared: dict, policy: dict) -> dict:
    """The chain's target as one member receives it — a copy, because
    `cmd_run` pops `_files` out of it and a shared dict would leave the second
    member with no file list at all."""
    return {k: (list(v) if isinstance(v, list) else v) for k, v in shared.items()}


#: What of the orchestration block may go into `run.json`. `chain` has a
#: closed key list in `run.v1`.
RECORD_KEYS = ("id", "position", "of", "upstream")


def block(chain_id: str, position: int, of: int, upstream: list[str]) -> dict:
    return {"id": chain_id, "position": position, "of": of, "upstream": list(upstream)}


def record_block(chain: dict) -> dict:
    return {k: chain[k] for k in RECORD_KEYS if k in chain}


def find_member(project, chain_id: str, position: int):
    """The run that took this position in the chain — or None."""
    from .runs import load_runs
    for run in load_runs(project):
        c = run.record().get("chain") or {}
        if c.get("id") == chain_id and c.get("position") == position:
            return run
    return None


def handoff_text(run) -> tuple[str | None, str | None, str | None]:
    """What the upstream run passes on, where it came from, and its full path.

    `handoff.md` is addressed ("what you need"), `summary.md` is descriptive
    ("what I did"). With both, the addressed one wins; with neither, `None`
    comes back and the prompt leans on the counts alone.
    """
    for name in ("handoff.md", "summary.md"):
        path = run.dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return _clip(text, HANDOFF_BYTES), name, posix(path)
    return None, None, None


def _clip(text: str, limit: int) -> str:
    """Cut on a line boundary, and say where the rest is."""
    if len(text.encode("utf-8")) <= limit:
        return text
    kept: list[str] = []
    size = 0
    lines = text.splitlines()
    for i, line in enumerate(lines):
        size += len(line.encode("utf-8")) + 1
        if size > limit:
            return "\n".join(kept) + f"\n… ({len(lines) - i} more lines in the file)"
        kept.append(line)
    return text


def write_upstream(project: Project, run, upstream_ids: list[str]) -> dict:
    """`evidence/upstream.json` — what this member was given as input.

    No ceiling: this is the brief, not the background. A finding that does not
    fit into it is a finding the second specialist never decided on.
    """
    data = knowledge.upstream(project, upstream_ids)
    undecided = len([f for f in data["findings"] if not f.get("decision")])
    payload = {
        "runs": data["runs"],
        "findings": data["findings"],
        "specs": data["specs"],
        "counts": {"findings": len(data["findings"]), "undecided": undecided},
    }
    write_json(run.dir / "evidence" / "upstream.json", payload)
    return payload


#: What a member is told about starting further runs.
LEAF = ("Do not start other runs — no `agency run`, no `agency chain`. You are "
        "one member; write findings.json and handoff.md and the chain moves on "
        "by itself.")


def step_prompt(base: str, member: Member, position: int, of: int,
                upstream: list[dict], counts: dict, handoff: str | None,
                handoff_path: str | None = None) -> str:
    """Kicking off a chain member — deterministically, from the core's
    template. The whole assembled prompt goes into the run's `prompt.txt`,
    so the quality of the kick-off is readable and can be tuned."""
    lines = [base, f"You are step {position}/{of} of a chain ({member.label})."]

    if not upstream:
        lines.append("You run first — nobody has handed you anything. "
                     "Whatever you write is the input of the next member.")
        lines.append(LEAF)
        return " ".join(lines[:2]) + "\n" + "\n".join(lines[2:])

    who = ", ".join(u.get("hire") or (u.get("pack") or "?") for u in upstream)
    if counts.get("findings"):
        lines.append(
            f"Upstream: {who} — {counts['findings']} findings "
            f"({counts['undecided']} undecided), full data in evidence/upstream.json.")
        lines.append(
            "First judge those findings — `agency triage accept|reject|defer <id> "
            "--by hire:<your id from context.json>`, or `agency note` when you are "
            "unsure — and only then run your own dimensions.")
    else:
        lines.append(
            f"Upstream: {who} reported no findings, so there is nothing to triage. "
            f"Its handoff below is your brief — answer it in your own findings.json "
            f"where it names something your dimensions cover, and in summary.md "
            f"where it does not.")
    if handoff:
        where = f" (full text: {handoff_path})" if handoff_path else ""
        lines.append(f"Handoff from {who}{where}:\n{handoff}")
    lines.append(LEAF)
    return "\n".join(lines)


def per_member(members: list[Member], focus: list[str]) -> dict[str, str]:
    """`--focus po:"…"` — a brief for one member, not for the whole chain.

    The key is the pack name a member goes by in the chain. An unknown name is
    refused: a silently discarded brief is worse than an error message.
    """
    known = {m.label for m in members}
    out_: dict[str, str] = {}
    for item in focus:
        who, sep, text = str(item).partition(":")
        who, text = who.strip(), text.strip()
        if not sep or not who or not text:
            raise SystemExit(f"Expected <who>:<text>, got “{item}”.")
        if who not in known:
            raise SystemExit(
                f"“{who}” is not in this chain. Members: {', '.join(m.label for m in members)}")
        out_[who] = text
    return out_
