"""A chain of specialists — run, wait, hand over, next.

`docs/plans/teams.md` Step 3. A chain is **not a conversation**: it is a sequence
of runs whose members pass each other files, not messages in a session.
Everything the agents "say" is either an append-only event on a finding
(`decisions.jsonl`) or a file a run left behind (`handoff.md`, `summary.md`,
`findings.json`) — so it can be replayed event by event and defended afterwards.
The chain does not invent that philosophy, it only uses it: triage has stood on
it from the start.

What this module **does not do**, and must not:

  * **It does not decide the order.** A person writes the list of members. No
    LLM orchestrator between runs — judgement belongs inside runs, because that
    is where it is recorded, attributed and paid for once.
  * **It does not write the prompt's content.** The core owns the template
    (`step_prompt`), but the sentences in it are the upstream agent's own words
    from its `handoff.md`. "The orchestrator assembles the prompt" therefore
    means template plus someone else's words, not a hidden third model.
  * **It does not resurrect an interrupted chain.** The runs are recorded and
    can be finished by hand. `--resume` arrives when it is genuinely needed.

What holds a chain together is the `chain` block in `run.json` (`run.v1`), not
the order of directories. Without it there would be no telling afterwards which
decision was made over someone else's finding as part of a handover and which
was made alone — and that is the whole difference between a team and several
runs in a row.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hires, knowledge
from .config import Project
from .util import posix, write_json

#: How much of a handoff goes into the next member's prompt. A ceiling in bytes,
#: and a generous one, because a handoff is not a kick-off line — it is the
#: brief. The 40-line limit this replaced looked reasonable and was not: the
#: first real handoff ran to 120 lines and its only addressed section, the one
#: headed "recommendation for the PO agent", sat at the bottom. The next member
#: got the technical recap and "… (80 more lines in the file)".
HANDOFF_BYTES = 16_000


@dataclass
class Member:
    """One chain member, as `agency chain` received it on the command line."""
    ref: str
    pack: str
    hire: hires.Hire | None

    @property
    def label(self) -> str:
        return self.hire.id if self.hire else self.pack


def resolve(project: Project, refs: list[str]) -> list[Member]:
    """Command-line names into members. `hires.resolve` decides as it does for `run`.

    A hire's name beats a pack's name — the other way round, a hire named after
    its own pack would be unreachable.
    """
    return [Member(ref, *hires.resolve(project, ref)) for ref in refs]


def one_provider(members: list[Member]) -> str | None:
    """An error when a chain mixes providers — otherwise None.

    A deliberate v1 narrowing (`teams.md` §3.2), not an architectural barrier:
    the handoff is file-based, so mixing providers is a change to this one
    function. The narrowing exists because of the terminal — one binary, one
    credential, one set of quirks — and it falls once the pipeline has proven
    itself. Until then, refusing up front beats refusing halfway through.
    """
    seen = {m.hire.provider for m in members if m.hire}
    if len(seen) <= 1:
        return None
    named = ", ".join(f"{m.label} ({m.hire.provider})" for m in members if m.hire)
    return (f"a chain runs on one provider at a time, and this one mixes "
            f"{' and '.join(sorted(seen))}: {named}. Run them separately, or pick "
            f"workers from the same provider.")


def target(project: Project, pr: int | None, latest_merged: bool,
           since: str | None = None) -> dict:
    """What the whole chain is about — resolved once, before the first step.

    This is the difference between a team and several runs that happen to share
    an id. `--pr N` only ever reached a pack whose own `run.target` is a pull
    request; a workspace pack (po, legal, qa) in the same chain quietly resolved
    its own target from whatever branch was checked out. On 2026-09-02 a chain
    started over PR #479 had its product owner judging PR #474, and neither the
    output nor the record said the two members had looked at different things.

    Members keep their own idea of what to DO with a target — a reviewer reads
    the diff, QA runs the application — but not of what the target IS.
    """
    from . import runs as _runs
    if pr is not None or latest_merged:
        return _runs.resolve_target(project, pr, latest_merged)
    return _runs.resolve_workspace_target(project, since)


def member_target(shared: dict, policy: dict) -> dict:
    """The chain's target as one member receives it.

    A copy, because `cmd_run` pops `_files` out of it and a shared dict would
    leave the second member with no file list at all — the kind of bug that
    looks like an empty pull request.
    """
    out_ = {k: (list(v) if isinstance(v, list) else v) for k, v in shared.items()}
    return out_


#: What of the orchestration block may go into `run.json`. `chain` has a closed
#: key list in `run.v1`, so neither the predecessor's message nor a per-member
#: brief — things the orchestrator carries in that same dict — belong in the
#: record. Without this filter every team run was an invalid record and
#: `agency validate` said so.
RECORD_KEYS = ("id", "position", "of", "upstream")


def block(chain_id: str, position: int, of: int, upstream: list[str]) -> dict:
    """The `chain` block for the run record. `run.v1` guards its shape."""
    return {"id": chain_id, "position": position, "of": of, "upstream": list(upstream)}


def record_block(chain: dict) -> dict:
    """Only what `run.v1` knows on a `chain` block. The rest is the orchestrator's."""
    return {k: chain[k] for k in RECORD_KEYS if k in chain}


def find_member(project, chain_id: str, position: int):
    """The run that took this position in the chain — or None.

    The chain asks this way after every step rather than "which run is newest":
    the newest run may belong to someone else (a parallel reviewer over the same
    pull request is a supported case), whereas the `chain` block is an identity
    the run carries itself.
    """
    from .runs import load_runs
    for run in load_runs(project):
        c = run.record().get("chain") or {}
        if c.get("id") == chain_id and c.get("position") == position:
            return run
    return None


def handoff_text(run) -> tuple[str | None, str | None, str | None]:
    """What the upstream run passes on, where it came from, and its full path.

    `handoff.md` is addressed ("what you need"), `summary.md` is descriptive
    ("what I did"). With both, the addressed one wins; with neither, `None` comes
    back and the prompt leans on the counts alone. Silence is a legitimate
    result — inventing a message the agent did not write would be a claim nobody
    signed.

    The path comes back too, and it goes into the prompt whether or not the text
    was clipped. It used to live only in `context.json`, so a member holding a
    truncated handoff had nowhere to go for the rest.
    """
    for name in ("handoff.md", "summary.md"):
        path = run.dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return _clip(text, HANDOFF_BYTES), name, posix(path)
    return None, None, None


def _clip(text: str, limit: int) -> str:
    """Cut on a line boundary, and say where the rest is.

    Bytes, not lines: what threatens a prompt is size, and a line can be a word
    or a paragraph. Cutting on a line boundary keeps the markdown readable.
    """
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

    **No ceiling, and that is the whole difference from `known-findings.json`.**
    Three hundred is a ceiling on background: a finding that does not fit into
    background is an inconvenience. This is the brief — a finding that does not
    fit into the brief is a finding the second specialist never decided on, and
    the chain would be quietly manufacturing holes in its own output.
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


#: What a member is told about starting further runs. Without it one sentence in
#: a brief ("use the PO agent to find out whether…") is enough: on 2026-09-02 a
#: reviewer dutifully ran `agency run po@claude --wait` from inside its own
#: session, producing a run with no terminal, no permissions and a record
#: claiming it was attended.
LEAF = ("Do not start other runs — no `agency run`, no `agency chain`. You are "
        "one member; write findings.json and handoff.md and the chain moves on "
        "by itself.")


def step_prompt(base: str, member: Member, position: int, of: int,
                upstream: list[dict], counts: dict, handoff: str | None,
                handoff_path: str | None = None) -> str:
    """Kicking off a chain member — deterministically, from the core's template.

    The whole assembled prompt goes into the run's `prompt.txt`, so the quality
    of the kick-off is readable and can be tuned. That is why the core owns the
    template and not the pack: if every pack wrote its own, there would be no
    comparing why one member understood its role and another did not.
    """
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
        # Judging someone else's finding is work to be done BEFORE a member's own
        # dimensions: otherwise it arrives at the decision with a head full of its
        # own findings and rushes the other one. So the ordering lives in the
        # prompt, not only in SKILL.md.
        lines.append(
            "First judge those findings — `agency triage accept|reject|defer <id> "
            "--by hire:<your id from context.json>`, or `agency note` when you are "
            "unsure — and only then run your own dimensions.")
    else:
        # Telling a member to "judge those findings" when there are none reads as
        # an instruction it cannot carry out, and the handoff — which is the real
        # brief in that case — gets treated as background. Seen on the first real
        # chain: the reviewer reported zero findings and wrote 120 lines of
        # product context, and the PO was told to triage nothing.
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

    Without this everyone got the same `--prompt`. On the first real chain that
    played out exactly as it had to: the user wrote "do a review and use the PO
    agent to work out whether this makes product sense", the reviewer read the
    second half as its own and started answering product questions. A sentence
    addressed to somebody else is not context, it is a confusing instruction.

    The key is the name a member goes by in the chain — a hire id, or a pack
    name when the chain was assembled from packs. An unknown name is refused: a
    silently discarded brief is worse than an error message.
    """
    known = {m.label for m in members} | {m.pack for m in members} | {m.ref for m in members}
    out_: dict[str, str] = {}
    for item in focus:
        who, sep, text = str(item).partition(":")
        who, text = who.strip(), text.strip()
        if not sep or not who or not text:
            raise SystemExit(f"Expected <who>:<text>, got “{item}”.")
        if who not in known:
            raise SystemExit(
                f"“{who}” is not in this chain. Members: {', '.join(m.label for m in members)}")
        for m in members:
            if who in (m.label, m.pack, m.ref):
                out_[m.label] = text
    return out_
