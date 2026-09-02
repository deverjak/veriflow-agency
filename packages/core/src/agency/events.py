"""What the agent is doing right now, translated out of its runner's stream.

`unattended.md` Step 3. Until 2026-09-02 the orchestrator knew exactly one thing
about an agent: when it stopped. So the user saw `launching claude…` and then
twelve minutes of nothing — and what had actually happened in the meantime (five
refused `findings.json` writes in a row) could only be dug out of the provider's
own transcript under `~/.claude/projects`.

The runners publish all of it, nobody was asking. Both `claude -p --output-format
stream-json --verbose` and `codex exec --json` write JSONL to stdout, and it
carries everything that matters: which tool the agent is calling, what it was
refused, how many turns it took, what it cost.

This module is **only a translator**. It decides nothing, prints nothing, writes
nothing — it turns a line into an `Event`. The reason is the same one behind
`providers.py`: another tool's shape is data, not a branch in the orchestrator.
When a dialect changes or a third one appears, the table changes and `runs.py`
does not.

An unknown line is **dropped silently**. A runner puts things into its stream
this tool will never learn, and crashing on someone else's new event type would
mean a provider upgrade breaking a run that would otherwise have finished.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Event:
    """One thing that happened during a session.

    `kind` is a small closed vocabulary, so dialects stay comparable:

      * `start`   — the session began; `session` carries the runner's id
      * `tool`    — the agent is calling a tool; `tool` and `detail`
      * `denied`  — a tool call was refused (this is the one that matters)
      * `text`    — the agent said something; `detail` is the text
      * `done`    — the end; `turns`, `usd`, `denials`, `detail` = last message
    """
    kind: str
    tool: str | None = None
    detail: str | None = None
    session: str | None = None
    turns: int | None = None
    usd: float | None = None
    denials: list[str] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)


#: How many characters of a tool's argument fit on a progress line. A longer
#: path or command tells the user nothing beyond "something is happening".
DETAIL = 78


def _clip(text) -> str | None:
    if text is None:
        return None
    s = " ".join(str(text).split())
    return s if len(s) <= DETAIL else s[:DETAIL - 1] + "…"


def _tool_detail(name: str, inp: dict) -> str | None:
    """The most telling field of the input. Tools differ, but there is always
    exactly one field that says what is going on."""
    if not isinstance(inp, dict):
        return None
    for key in ("command", "file_path", "path", "pattern", "skill",
                "query", "url", "description", "prompt"):
        if inp.get(key):
            return _clip(inp[key])
    return None


def claude(line: str) -> list[Event]:
    """`claude -p --output-format stream-json --verbose`.

    Verified against claude 2.1.258. The point worth remembering is that **a
    denial is not an error**: the closing `result` carries `is_error: false`
    even when the system refused the agent every single write. The only signal
    is `permission_denials[]` — which is why this translator lifts it out
    separately instead of letting it hide inside the text.
    """
    try:
        o = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(o, dict):
        return []
    kind = o.get("type")

    if kind == "system" and o.get("subtype") == "init":
        return [Event("start", session=o.get("session_id"))]

    if kind == "assistant":
        out_: list[Event] = []
        for b in ((o.get("message") or {}).get("content") or []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                out_.append(Event("tool", tool=b.get("name"),
                                  detail=_tool_detail(b.get("name") or "", b.get("input") or {})))
            elif b.get("type") == "text" and b.get("text", "").strip():
                out_.append(Event("text", detail=b["text"]))
        return out_

    if kind == "result":
        denials = [d.get("tool_name") for d in (o.get("permission_denials") or [])
                   if isinstance(d, dict) and d.get("tool_name")]
        usage = o.get("usage") or {}
        return [Event("done",
                      detail=o.get("result"),
                      session=o.get("session_id"),
                      turns=o.get("num_turns"),
                      usd=o.get("total_cost_usd"),
                      denials=denials,
                      tokens={"input": usage.get("input_tokens"),
                              "output": usage.get("output_tokens")})]
    return []


def codex(line: str) -> list[Event]:
    """`codex exec --json`.

    A different shape from claude's — events are `item.*` and a run closes with
    `turn.completed`. Written from the 0.144.3 help and **not verified by a real
    run**: the user's roster is entirely `@claude` today. An unknown event is
    dropped, so the worst case is progress without lines, not a crash.
    """
    try:
        o = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(o, dict):
        return []
    kind = str(o.get("type") or "")
    item = o.get("item") or o

    if kind in ("session.created", "thread.started"):
        return [Event("start", session=o.get("session_id") or o.get("thread_id"))]

    if kind.startswith("item.") and isinstance(item, dict):
        it = str(item.get("type") or item.get("item_type") or "")
        if "command" in it or "tool" in it or "exec" in it:
            return [Event("tool", tool=item.get("name") or "Bash",
                          detail=_tool_detail(it, item))]
        if "message" in it and item.get("text"):
            return [Event("text", detail=item["text"])]
        return []

    if kind in ("turn.completed", "turn.failed"):
        usage = o.get("usage") or (o.get("turn") or {}).get("usage") or {}
        return [Event("done",
                      turns=o.get("num_turns"),
                      usd=o.get("total_cost_usd"),
                      tokens={"input": usage.get("input_tokens"),
                              "output": usage.get("output_tokens")})]
    return []


#: Which translator belongs to which dialect. The dialect's name lives in
#: `providers.py` as data — so adding a runner means adding a row there and a row
#: here, not reaching into the orchestrator.
DIALECTS = {"claude-stream-json": claude, "codex-jsonl": codex}


def parse(dialect: str, line: str) -> list[Event]:
    fn = DIALECTS.get(dialect)
    return fn(line) if fn else []


def summarize(events: list[Event]) -> dict:
    """What belongs in the run record once the session is over.

    Sums across every `done` event, not just the last one: codex emits several
    over a multi-turn run, and adding them up is the only way to get the cost of
    the whole session rather than of its final turn.
    """
    out_: dict = {"session": None, "turns": None, "usd": None,
                  "denied": [], "tokens": {}, "last": None}
    tools: list[str] = []
    for e in events:
        if e.session:
            out_["session"] = e.session
        for d in e.denials:
            if d not in tools:
                tools.append(d)
        if e.kind == "denied" and e.tool and e.tool not in tools:
            tools.append(e.tool)
        if e.kind == "done":
            if e.turns is not None:
                out_["turns"] = (out_["turns"] or 0) + e.turns
            if e.usd is not None:
                out_["usd"] = round((out_["usd"] or 0) + e.usd, 6)
            for k, v in (e.tokens or {}).items():
                if v is not None:
                    out_["tokens"][k] = (out_["tokens"].get(k) or 0) + v
            if e.detail:
                out_["last"] = e.detail
    out_["denied"] = tools
    return out_


def denial_count(events: list[Event]) -> int:
    """How many calls were refused. Counted from `permission_denials`, not from
    the number of distinct tools: five refused Writes are five missing
    permissions, not one."""
    n = 0
    for e in events:
        n += len(e.denials)
        if e.kind == "denied":
            n += 1
    return n
