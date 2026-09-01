"""The product queue as a sink: GitHub issues and Project draft items.

This module is coupled to GitHub on purpose, the same way `export.py` is. The
product owner has to write somewhere, and one backend that actually works beats
a driver interface designed against a single implementation. What keeps the
coupling cheap is where the line was drawn: everything above it — the roadmap,
the decision, the reason — is backend-free, and `board.*` in the pack
configuration is the only block that names GitHub. A second backend replaces
this file and nothing else.

**The agent does not call `gh`.** It calls `agency backlog …`, and this module
does the writing. That is not ceremony, it buys four things the pack could not
have otherwise:

  1. **The signature.** Everything posted says an agent wrote it, in one shape,
     from one place. A pack composing its own footer would drift, and an
     unsigned agent comment on somebody's ticket is how this loses the right to
     post at all.
  2. **Idempotence.** Every write carries a marker, and the second run finds
     what the first one posted instead of posting it again. A duplicated ticket
     is exactly the manual work this tool exists to remove.
  3. **The write gate.** `writes.*` is a per-project switch, and an outward-
     facing action nobody enabled does not happen — the refusal is a message,
     not an exception.
  4. **The ledger.** What was posted is appended to the run directory, which is
     in the repository. GitHub is the sink; the run record stays the truth.

Idempotence has the same two independent legs as the export:

  1. the ledger in `<RUN_DIR>/backlog.jsonl` — local, works offline;
  2. the marker `<!-- agency:po:<key> -->` in the body — survives the run
     record being lost, and is what a second machine sees.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import export, proc
from .config import Project
from .runs import Run

MARKER = "<!-- agency:po:{key} -->"
MARKER_RE = re.compile(r"<!-- agency:po:([a-z0-9][a-z0-9._@:-]{0,120}) -->")

# What each action needs switched on. The keys are the `writes` block, so the
# refusal can name the exact line to change instead of saying "not allowed".
WRITE_GATE = {
    "comment": "comments",
    "draft": "draftIssues",
    "issue": "issues",
    "promote": "promote",
    "label": "labels",
    "status": "labels",
    "close": "close",
}

DECISIONS = ("now", "next", "not-now")

# Heading of the comment a decision posts. The wording is deliberate: this is a
# sequencing call about one cycle, not a verdict on the idea.
DECISION_HEADING = {
    "now": "Decision: build it now",
    "next": "Decision: not this cycle — next",
    "not-now": "Decision: not now",
}


class BacklogError(RuntimeError):
    """A GitHub call failed. Carries what `gh` said, trimmed."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- keys

def key_for(text: str) -> str:
    """A stable idempotence key from a title.

    Derived from the title rather than random, because the point is that the
    NEXT run — a different process, possibly a different machine — recognises
    the ticket it already wrote. A random id would be unique and useless.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:64].rstrip("-") or "item")


def key_for_text(text: str) -> str:
    """An idempotence key for a free-form comment.

    A readable prefix from the first line plus a digest of the whole text. The
    prefix alone would be wrong in the dangerous direction: two different
    comments that happen to open with the same sentence would collide, and the
    second one would be silently dropped as “already posted”. The digest makes
    identical text idempotent and different text distinct, which is exactly the
    rule a comment needs.
    """
    body = (text or "").strip()
    first = body.splitlines()[0] if body else "note"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"{key_for(first)[:40].rstrip('-')}-{digest}"


def marker_in(text: str | None) -> str | None:
    m = MARKER_RE.search(text or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- signature

def signature(cfg: dict, run: Run | None = None, hire: dict | None = None) -> str:
    """The footer under everything this pack posts.

    Says three things, in this order, because that is the order a reader needs
    them in: who wrote it, that it was an agent, and who to argue with.
    """
    sig = cfg.get("signature") or {}
    if not sig.get("disclose", True):
        # Left in reach because a project may have its own disclosure elsewhere.
        # It is not a shortcut: nothing else in this module changes, so the
        # marker and the ledger still hold.
        return ""

    name = sig.get("name") or "Product owner"
    pack = (cfg.get("pack") or "po@0.1.0")
    bits = [f"`agency {pack}`"]
    if run is not None:
        bits.append(f"run `{run.id}`")
    if hire:
        who = hire.get("model") or hire.get("provider")
        if who:
            bits.append(f"`{who}`")

    lines = ["", "---",
             f"**{name}** — written by an agent, not a person. " + " · ".join(bits)]

    escalate = (cfg.get("policy") or {}).get("escalate")
    lines.append(
        f"If this call is wrong, say so here — {escalate} has the last word."
        if escalate else
        "If this call is wrong, say so here; a human decides."
    )
    if sig.get("note"):
        lines.append(str(sig["note"]))
    return "\n".join(lines)


def compose(cfg: dict, body: str, key: str, run: Run | None = None,
            hire: dict | None = None) -> str:
    """Marker, body, signature — in that order, always."""
    return "\n".join([MARKER.format(key=key), (body or "").strip(),
                      signature(cfg, run, hire)]).rstrip() + "\n"


def decision_body(cfg: dict, decision: str, because: str,
                  commitment: str | None = None, revisit: str | None = None) -> str:
    """The body of a cut, or of a green light.

    The prose is the agent's; the frame is not. A decision that does not name
    the commitment it was measured against cannot be argued with, and one that
    does not say when it will be looked at again reads as a refusal instead of
    a sequencing call.
    """
    road = cfg.get("roadmap") or {}
    cycle = road.get("cycle")
    if cycle and road.get("cycleEnds"):
        cycle = f"{cycle} (ends {road['cycleEnds']})"

    lines = [f"### {DECISION_HEADING.get(decision, decision)}", "", (because or "").strip(), ""]
    facts = [
        ("Commitment", commitment or "none — nothing in the roadmap covers this"),
        ("Cycle", cycle or "not set in the configuration"),
        ("Revisit", revisit or ("at the next cycle boundary" if decision != "now"
                                else "on delivery")),
    ]
    lines += [f"- **{k}:** {v}" for k, v in facts]
    return "\n".join(lines)


# ---------------------------------------------------------------- board

@dataclass
class Board:
    """Where the queue lives, plus the remote state, fetched at most once.

    The indexes are cached because idempotence needs the whole list, not a
    lookup: a marker is found by reading bodies, and reading them once per
    command is the difference between a usable CLI and one that spends its time
    on the network.
    """
    slug: str
    project_number: int | None = None
    owner: str | None = None
    cfg: dict = field(default_factory=dict)

    _issues: list | None = None
    _items: dict | None = None
    _meta: dict | None = None

    # ---------------------------------------------------------- construction

    @classmethod
    def of(cls, project: Project, cfg: dict) -> "Board":
        b = cfg.get("board") or {}
        slug = (cfg.get("repo") or {}).get("slug") or project.slug
        if not slug:
            raise BacklogError(
                "This project has no owner/repo — set it with "
                "`agency config po --set repo.slug=owner/repo`.")
        number = b.get("projectNumber")
        return cls(slug=slug, project_number=int(number) if number else None,
                   owner=b.get("owner") or slug.split("/")[0], cfg=cfg)

    @property
    def has_project(self) -> bool:
        return self.project_number is not None

    def require_project(self, what: str) -> None:
        if not self.has_project:
            raise BacklogError(
                f"{what} lives inside a GitHub Project and this project has no board — "
                "set it with `agency config po --set board.projectNumber=<n>`.")

    # ---------------------------------------------------------------- reads

    def issues(self, state: str = "all", limit: int = 200) -> list[dict]:
        """Issues with their bodies, fetched once and filtered locally.

        Always fetched as `--state all`, whatever the caller asked for. Bodies
        are the point — the marker lives in them — and a CLOSED issue carrying
        a key still counts as written: re-filing it because the query only
        looked at open ones is the duplicate this module exists to prevent.
        """
        if self._issues is None:
            r = proc.gh("issue", "list", "--repo", self.slug, "--state", "all",
                        "--limit", str(limit), "--json",
                        "number,title,body,url,state,labels,updatedAt,author,comments")
            if not r.ok:
                raise BacklogError((r.stderr or r.stdout).strip()[:400])
            self._issues = r.json(default=[]) or []
        if state == "all":
            return self._issues
        want = state.upper()
        return [row for row in self._issues
                if str(row.get("state") or "").upper() == want]

    def items(self, limit: int = 500) -> list[dict]:
        """Everything on the board, drafts included."""
        if not self.has_project:
            return []
        if self._items is not None:
            return self._items
        r = proc.gh("project", "item-list", str(self.project_number),
                    "--owner", self.owner, "--limit", str(limit), "--format", "json")
        if not r.ok:
            raise BacklogError((r.stderr or r.stdout).strip()[:400])
        data = r.json(default={}) or {}
        rows = data.get("items") if isinstance(data, dict) else data
        self._items = rows or []
        return self._items

    def meta(self) -> dict:
        """Project id and fields, looked up by NAME. Shared with the export —
        the rule that a hardcoded field id survives exactly one project is the
        same rule here."""
        self.require_project("The status field")
        if self._meta is None:
            try:
                self._meta = export.project_meta(self.project_number, self.owner)
            except export.ExportError as e:
                raise BacklogError(str(e)) from e
        return self._meta

    # ------------------------------------------------------------ idempotence

    def by_key(self, key: str) -> dict | None:
        """Has anything with this key already been written?

        Issues first: a promoted draft exists in both places, and the issue is
        the one a human will open.
        """
        for row in self.issues():
            if marker_in(row.get("body")) == key:
                return {"kind": "issue", "number": row.get("number"),
                        "url": row.get("url"), "title": row.get("title"),
                        "state": row.get("state")}
        for it in self.items():
            content = it.get("content") or {}
            if marker_in(content.get("body")) == key:
                return {"kind": "draft" if _is_draft(it) else "issue",
                        "item": it.get("id"), "number": content.get("number"),
                        "url": content.get("url"), "title": it.get("title")
                        or content.get("title")}
        return None

    def comment_by_key(self, number: int, key: str) -> dict | None:
        r = proc.gh("issue", "view", str(number), "--repo", self.slug,
                    "--json", "comments")
        if not r.ok:
            return None
        for c in (r.json(default={}) or {}).get("comments") or []:
            if marker_in(c.get("body")) == key:
                return {"url": c.get("url"), "at": c.get("createdAt")}
        return None


def _url_of(result) -> str | None:
    """The URL `gh` prints after creating something.

    Guarded because an empty stdout is not impossible — a `gh` that succeeds
    and says nothing would otherwise take the whole command down with an
    IndexError, after the ticket has already been created. Losing the link to
    something that now exists is the worst shape this failure could take.
    """
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _is_draft(item: dict) -> bool:
    content = item.get("content") or {}
    kind = (content.get("type") or item.get("type") or "").lower()
    if kind:
        return kind.startswith("draft")
    # An item with no number is a draft: an issue and a pull request both have
    # one. Guessing from the type string alone would break the day gh renames it.
    return not content.get("number")


# ---------------------------------------------------------------- refs

def resolve_ref(board: Board, ref: str) -> dict:
    """`41`, `#41`, an issue URL or a `PVTI_…` item id — all name one thing."""
    raw = (ref or "").strip()
    if not raw:
        raise BacklogError("Which ticket? Give an issue number or a board item id.")

    if raw.startswith("PVTI_") or raw.startswith("PVT_"):
        for it in board.items():
            if it.get("id") == raw:
                content = it.get("content") or {}
                return {"kind": "draft" if _is_draft(it) else "issue",
                        "item": raw, "number": content.get("number"),
                        "url": content.get("url"),
                        "title": it.get("title") or content.get("title"),
                        "body": content.get("body")}
        raise BacklogError(f"No item “{raw}” on board #{board.project_number}.")

    m = re.search(r"(?:^#?|/issues/)(\d+)$", raw)
    if not m:
        raise BacklogError(
            f"“{ref}” is neither an issue number nor a board item id.")
    number = int(m.group(1))
    r = proc.gh("issue", "view", str(number), "--repo", board.slug,
                "--json", "number,title,body,url,state,labels")
    if not r.ok:
        raise BacklogError(f"Issue #{number} could not be read: "
                           + (r.stderr or r.stdout).strip()[:200])
    data = r.json(default={}) or {}
    return {"kind": "issue", "item": None, "number": data.get("number"),
            "url": data.get("url"), "title": data.get("title"),
            "body": data.get("body"), "state": data.get("state"),
            "labels": [x.get("name") for x in data.get("labels") or []]}


# ---------------------------------------------------------------- write gate

def allowed(cfg: dict, action: str) -> tuple[bool, str]:
    """May this pack do that here?

    A refusal names the switch. "Not allowed" with no way forward is the same
    as a crash, only quieter.
    """
    switch = WRITE_GATE.get(action)
    if switch is None:
        return True, ""
    writes = cfg.get("writes") or {}
    if writes.get(switch):
        return True, ""
    return False, (
        f"`writes.{switch}` is off in this project, so nothing was posted.\n"
        f"Turn it on when you want it: `agency config po --set writes.{switch}=true`")


def is_rehearsal(cfg: dict) -> bool:
    return bool((cfg.get("writes") or {}).get("dryRun"))


# ---------------------------------------------------------------- writes

def create_issue(board: Board, cfg: dict, title: str, body: str, key: str,
                 labels: list[str] | None = None, run: Run | None = None,
                 hire: dict | None = None, dry_run: bool = False) -> dict:
    existing = board.by_key(key)
    if existing:
        return {"action": "exists", "key": key, **existing}

    text = compose(cfg, body, key, run, hire)
    wanted = _labels(cfg, labels)
    if dry_run:
        return {"action": "would-create", "kind": "issue", "key": key,
                "title": title, "body": text, "labels": wanted}

    args = ["issue", "create", "--repo", board.slug, "--title", title, "--body", text]
    for name in wanted:
        args += ["--label", name]
    r = proc.gh(*args)
    if not r.ok:
        # A missing label is the usual cause and it is not worth losing the
        # ticket over — retry once without labels and say which ones were lost.
        if wanted and "label" in (r.stderr or "").lower():
            r2 = proc.gh("issue", "create", "--repo", board.slug,
                         "--title", title, "--body", text)
            if r2.ok:
                return {"action": "created", "kind": "issue", "key": key,
                        "url": _url_of(r2), "title": title,
                        "labelsSkipped": wanted,
                        "why": "the labels do not exist in this repository"}
        raise BacklogError((r.stderr or r.stdout).strip()[:400])

    url = _url_of(r)
    out = {"action": "created", "kind": "issue", "key": key, "url": url, "title": title,
           "labels": wanted}
    if board.has_project and url:
        add = proc.gh("project", "item-add", str(board.project_number),
                      "--owner", board.owner, "--url", url, "--format", "json")
        out["board"] = (add.json(default={}) or {}).get("id") if add.ok else None
        if not add.ok:
            out["boardError"] = (add.stderr or "").strip()[:200]
    return out


def create_draft(board: Board, cfg: dict, title: str, body: str, key: str,
                 run: Run | None = None, hire: dict | None = None,
                 dry_run: bool = False) -> dict:
    board.require_project("A draft issue")
    existing = board.by_key(key)
    if existing:
        return {"action": "exists", "key": key, **existing}

    text = compose(cfg, body, key, run, hire)
    if dry_run:
        return {"action": "would-create", "kind": "draft", "key": key,
                "title": title, "body": text}

    r = proc.gh("project", "item-create", str(board.project_number),
                "--owner", board.owner, "--title", title, "--body", text,
                "--format", "json")
    if not r.ok:
        raise BacklogError((r.stderr or r.stdout).strip()[:400])
    data = r.json(default={}) or {}
    return {"action": "created", "kind": "draft", "key": key,
            "item": data.get("id"), "title": title}


def promote(board: Board, cfg: dict, ref: dict, labels: list[str] | None = None,
            dry_run: bool = False) -> dict:
    """Draft → real issue, in place, keeping the board item.

    This is the moment a note becomes a commitment, which is why it has its own
    switch and its own command. Conversion is done by GitHub itself
    (`convertProjectV2DraftIssueItemToIssue`), so the item keeps its id, its
    column and its field values. Creating a fresh issue and deleting the draft
    would look the same in a screenshot and lose all three.
    """
    board.require_project("Promotion")
    if ref.get("kind") != "draft":
        return {"action": "already-an-issue", "number": ref.get("number"),
                "url": ref.get("url")}
    if dry_run:
        return {"action": "would-promote", "item": ref.get("item"),
                "title": ref.get("title"), "repo": board.slug}

    node = proc.gh("api", f"repos/{board.slug}", "--jq", ".node_id")
    if not node.ok:
        raise BacklogError(f"Repository {board.slug} could not be read: "
                           + (node.stderr or "").strip()[:200])

    query = (
        "mutation($item:ID!,$repo:ID!){"
        "convertProjectV2DraftIssueItemToIssue(input:{itemId:$item,repositoryId:$repo}){"
        "item{id content{... on Issue{number url}}}}}"
    )
    r = proc.gh("api", "graphql", "-f", f"query={query}",
                "-F", f"item={ref['item']}", "-F", f"repo={node.stdout.strip()}")
    if not r.ok:
        raise BacklogError(
            "The draft could not be converted: " + (r.stderr or r.stdout).strip()[:300])
    payload = ((r.json(default={}) or {}).get("data") or {}) \
        .get("convertProjectV2DraftIssueItemToIssue") or {}
    content = (payload.get("item") or {}).get("content") or {}

    out = {"action": "promoted", "item": ref.get("item"),
           "number": content.get("number"), "url": content.get("url"),
           "title": ref.get("title")}
    wanted = _labels(cfg, labels)
    if wanted and content.get("number"):
        lab = proc.gh("issue", "edit", str(content["number"]), "--repo", board.slug,
                      *sum((["--add-label", n] for n in wanted), []))
        out["labels"] = wanted if lab.ok else []
        if not lab.ok:
            out["labelsSkipped"] = wanted
            out["why"] = "the labels do not exist in this repository"
    return out


def comment(board: Board, cfg: dict, ref: dict, body: str, key: str,
            run: Run | None = None, hire: dict | None = None,
            dry_run: bool = False) -> dict:
    """A signed comment on an issue, or an appended note on a draft.

    A draft item has no comment thread — GitHub gives it a body and nothing
    else. So a note on a draft is appended to its body under a rule, which is
    honest about what it is and still readable on the card.
    """
    text = compose(cfg, body, key, run, hire)

    if ref.get("kind") == "issue" and ref.get("number"):
        seen = board.comment_by_key(ref["number"], key)
        if seen:
            return {"action": "exists", "kind": "comment", "key": key, **seen}
        if dry_run:
            return {"action": "would-comment", "kind": "comment", "key": key,
                    "number": ref["number"], "body": text}
        r = proc.gh("issue", "comment", str(ref["number"]), "--repo", board.slug,
                    "--body", text)
        if not r.ok:
            raise BacklogError((r.stderr or r.stdout).strip()[:400])
        return {"action": "commented", "kind": "comment", "key": key,
                "number": ref["number"], "url": _url_of(r)}

    board.require_project("A note on a draft")
    current = ref.get("body") or ""
    if marker_in(current) == key or MARKER.format(key=key) in current:
        return {"action": "exists", "kind": "draft-note", "key": key,
                "item": ref.get("item")}
    merged = (current.rstrip() + "\n\n" + text).strip() + "\n"
    if dry_run:
        return {"action": "would-comment", "kind": "draft-note", "key": key,
                "item": ref.get("item"), "body": merged}
    r = proc.gh("project", "item-edit", "--id", ref["item"],
                "--body", merged, "--format", "json")
    if not r.ok:
        raise BacklogError((r.stderr or r.stdout).strip()[:400])
    return {"action": "commented", "kind": "draft-note", "key": key,
            "item": ref.get("item")}


def set_status(board: Board, cfg: dict, ref: dict, decision: str,
               dry_run: bool = False) -> dict:
    """Move the item into the column that matches the decision.

    Column names differ between boards, so the configuration lists candidates
    and the first one the project actually has wins. A board without a matching
    column is reported — inventing an option would be a schema change nobody
    asked for.
    """
    if not (board.has_project and ref.get("item")):
        return {"action": "skipped", "why": "the item is not on a board"}

    field_name = (cfg.get("board") or {}).get("statusField") or "Status"
    candidates = ((cfg.get("board") or {}).get("status") or {}).get(decision) or []
    meta = board.meta()
    fld = meta["fields"].get(field_name)
    if not fld:
        return {"action": "skipped", "why": f"the board has no field “{field_name}”"}

    for name in candidates:
        opt = export.option_id(fld, name)
        if not opt:
            continue
        if dry_run:
            return {"action": "would-move", "field": field_name, "to": name}
        r = proc.gh("project", "item-edit", "--id", ref["item"],
                    "--project-id", meta["id"], "--field-id", fld["id"],
                    "--single-select-option-id", opt)
        if not r.ok:
            return {"action": "failed", "field": field_name, "to": name,
                    "why": (r.stderr or "").strip()[:200]}
        return {"action": "moved", "field": field_name, "to": name}

    return {"action": "skipped",
            "why": f"“{field_name}” has none of {', '.join(candidates) or '(no candidates configured)'}"}


def set_labels(board: Board, cfg: dict, ref: dict, decision: str,
               dry_run: bool = False) -> dict:
    wanted = _labels(cfg, None, decision=decision)
    if not wanted:
        return {"action": "skipped", "why": "no labels configured for this decision"}
    if ref.get("kind") != "issue" or not ref.get("number"):
        return {"action": "skipped", "why": "a draft item cannot carry labels"}
    if dry_run:
        return {"action": "would-label", "labels": wanted}
    r = proc.gh("issue", "edit", str(ref["number"]), "--repo", board.slug,
                *sum((["--add-label", n] for n in wanted), []))
    if not r.ok:
        return {"action": "failed", "labels": wanted,
                "why": "the labels do not exist in this repository"}
    return {"action": "labelled", "labels": wanted}


def _labels(cfg: dict, explicit: list[str] | None,
            decision: str | None = None) -> list[str]:
    """Explicit labels plus the ones the configuration attaches by role."""
    conf = (cfg.get("board") or {}).get("labels") or {}
    out = list(explicit or [])
    if decision:
        role = {"now": "now", "next": "next", "not-now": "notNow"}.get(decision)
        if role and conf.get(role):
            out.append(str(conf[role]))
    if conf.get("agent"):
        out.append(str(conf["agent"]))
    # Order preserved, duplicates dropped — `gh` refuses a repeated --label.
    seen, uniq = set(), []
    for name in out:
        if name and name not in seen:
            seen.add(name)
            uniq.append(name)
    return uniq


# ---------------------------------------------------------------- ledger

def ledger_path(run: Run):
    return run.dir / "backlog.jsonl"


def append(run: Run | None, event: dict) -> dict:
    """What was written, appended to the run directory.

    Append-only and in the repository, exactly like `decisions.jsonl`. GitHub
    is a sink: if it is unreachable, or somebody deletes the ticket, what this
    pack decided is still reviewable in the pull request that carries the run.
    """
    event = {"at": now(), **event}
    if run is None:
        return event
    run.dir.mkdir(parents=True, exist_ok=True)
    with open(ledger_path(run), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def ledger(run: Run) -> list[dict]:
    path = ledger_path(run)
    if not path.is_file():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ---------------------------------------------------------------- evidence

def snapshot(board: Board, cfg: dict, state: str = "open") -> dict:
    """The queue as it is right now, for the run to start from.

    Deterministic preparation, so it belongs to the core and not to the pack:
    a session that opens by listing tickets itself spends its first minutes on
    something that is testable without a model.
    """
    rows: list[dict] = []
    stats = {"issues": 0, "drafts": 0}

    for issue in board.issues(state=state):
        rows.append({
            "kind": "issue", "number": issue.get("number"), "title": issue.get("title"),
            "url": issue.get("url"), "state": issue.get("state"),
            "labels": [x.get("name") for x in issue.get("labels") or []],
            "updatedAt": issue.get("updatedAt"),
            "author": (issue.get("author") or {}).get("login"),
            "comments": len(issue.get("comments") or []),
            "agencyKey": marker_in(issue.get("body")),
            "body": (issue.get("body") or "")[:4000],
        })
        stats["issues"] += 1

    for it in board.items():
        content = it.get("content") or {}
        if not _is_draft(it):
            continue
        rows.append({
            "kind": "draft", "item": it.get("id"),
            "title": it.get("title") or content.get("title"),
            "agencyKey": marker_in(content.get("body")),
            "body": (content.get("body") or "")[:4000],
        })
        stats["drafts"] += 1

    return {"board": {"repo": board.slug, "projectNumber": board.project_number,
                      "owner": board.owner},
            "items": rows, **stats}
