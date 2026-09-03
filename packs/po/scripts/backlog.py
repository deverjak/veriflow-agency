#!/usr/bin/env python3
"""The only way this pack writes to GitHub — main-panel's board and issues.

This script belongs to the project, not to the Agency tool: the constants
below (repository, board, fields, labels) are main-panel's, hardcoded, and
this file is copied whole into another project rather than reused with a
different configuration.

Why the agent does not call `gh` itself: four things live here that a prompt
cannot enforce —

  1. the signature — every write says it was an agent, in one shape;
  2. the idempotence marker — the next run finds what this run posted;
  3. the write gate — this file's subcommands ARE the gate: there is no
     `issue` or `close` subcommand, so those actions cannot happen at all;
  4. the ledger — what was posted, appended to the run directory.

Subcommands:

    snapshot   [--run-dir DIR]                    the queue, frozen, to evidence/backlog.json
    comment    --ref REF --key KEY --body-file F [--run-dir DIR] [--dry-run]
    draft      --title T --key KEY --body-file F [--run-dir DIR] [--dry-run]
    promote    --ref PVTI_xxx [--label L ...] [--run-dir DIR] [--dry-run]
    decide     --ref REF --disposition D --because-file F [--commitment TEXT]
               [--label L ...] [--status NAME] [--run-dir DIR] [--dry-run]

REF is an issue number (`41`, `#41`), an issue URL, or a board item id
(`PVTI_…`). All writes carry a stable key so a second run recognises what the
first one already posted instead of posting it again — pass the same --key
for the same request across runs, or a derived one from the title is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- project facts

OWNER = "Chci-na-lekci"
REPO = "main-panel"
SLUG = f"{OWNER}/{REPO}"
PROJECT_NUMBER = 1

# The board has two single-select fields that both say "state" and mean
# different things. `Stav` is the observation lifecycle for feedback and
# drafts (New → Observed → Worth exploring → Converted to issue | Rejected |
# Archived) — this pack's decisions move THIS one. `Status` (Todo / In
# Progress / Done) is delivery status once something is actually being built,
# and is not this pack's to set.
STATUS_FIELD = "Stav"
REASON_FIELD = "Reason"

PRIORITY_LABELS = {"P0": "priority:P0", "P1": "priority:P1", "P2": "priority:P2",
                   "P3": "priority:P3", "P4": "priority:P4"}

MARKER = "<!-- agency:po:{key} -->"
MARKER_RE = re.compile(r"<!-- agency:po:([a-z0-9][a-z0-9._@:-]{0,120}) -->")

SIGNATURE_NAME = "Product owner"
ESCALATE = "the repository owner"

# Disposition (from references/feature-admission.md) → what happens to the
# board's `Stav` field and, for issues, the priority label. A draft moves to
# `Worth exploring` when it is validated cheaply rather than decided outright
# — everything else is either promoted (BUILD NOW / FIX-REMOVE NOW) or given
# a terminal `Stav`.
DISPOSITIONS = ("BUILD-NOW", "FIX-REMOVE-NOW", "VALIDATE-CHEAPLY", "DEFER-WITH-TRIGGER", "REJECT")
DISPOSITION_STATUS = {
    "BUILD-NOW": "Converted to issue",
    "FIX-REMOVE-NOW": "Converted to issue",
    "VALIDATE-CHEAPLY": "Worth exploring",
    "DEFER-WITH-TRIGGER": "Observed",
    "REJECT": "Rejected",
}
DISPOSITION_PRIORITY = {"BUILD-NOW": "P1", "FIX-REMOVE-NOW": "P0"}
DISPOSITION_HEADING = {
    "BUILD-NOW": "Decision: build it now",
    "FIX-REMOVE-NOW": "Decision: fix or remove now",
    "VALIDATE-CHEAPLY": "Decision: validate cheaply first",
    "DEFER-WITH-TRIGGER": "Decision: defer, with a trigger to reopen",
    "REJECT": "Decision: reject",
}


# ---------------------------------------------------------------- gh wrapper

class BacklogError(RuntimeError):
    pass


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise BacklogError((r.stderr or r.stdout).strip()[:600])
    return r.stdout


def gh_json(*args: str):
    return json.loads(gh(*args, "--format", "json"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- keys & marker

def key_for(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:64].rstrip("-") or "item"


def key_for_text(text: str) -> str:
    body = (text or "").strip()
    first = body.splitlines()[0] if body else "note"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"{key_for(first)[:40].rstrip('-')}-{digest}"


def marker_in(text: str | None) -> str | None:
    m = MARKER_RE.search(text or "")
    return m.group(1) if m else None


def signature(run_id: str | None) -> str:
    bits = ["`agency po`"]
    if run_id:
        bits.append(f"run `{run_id}`")
    return ("\n\n---\n"
            f"**{SIGNATURE_NAME}** — written by an agent, not a person. " + " · ".join(bits) +
            f"\nIf this call is wrong, say so here — {ESCALATE} has the last word.")


def compose(body: str, key: str, run_id: str | None) -> str:
    return "\n".join([MARKER.format(key=key), (body or "").strip(),
                      signature(run_id)]).rstrip() + "\n"


# ---------------------------------------------------------------- reads

def _is_draft(item: dict) -> bool:
    content = item.get("content") or {}
    kind = (content.get("type") or item.get("type") or "").lower()
    if kind:
        return kind.startswith("draft")
    return not content.get("number")


class Board:
    def __init__(self):
        self._issues: list[dict] | None = None
        self._items: list[dict] | None = None
        self._meta: dict | None = None

    def issues(self) -> list[dict]:
        if self._issues is None:
            self._issues = json.loads(gh(
                "issue", "list", "--repo", SLUG, "--state", "all", "--limit", "300",
                "--json", "number,title,body,url,state,labels,milestone,updatedAt,author,comments"))
        return self._issues

    def items(self) -> list[dict]:
        if self._items is None:
            data = gh_json("project", "item-list", str(PROJECT_NUMBER), "--owner", OWNER,
                           "--limit", "500")
            rows = data.get("items") if isinstance(data, dict) else data
            self._items = rows or []
        return self._items

    def meta(self) -> dict:
        """Project id and fields, looked up by NAME — the id changes per board."""
        if self._meta is None:
            view = gh_json("project", "view", str(PROJECT_NUMBER), "--owner", OWNER)
            fields = gh_json("project", "field-list", str(PROJECT_NUMBER), "--owner", OWNER)
            rows = fields.get("fields") if isinstance(fields, dict) else fields
            self._meta = {"id": view.get("id"),
                          "fields": {f["name"]: f for f in (rows or [])}}
        return self._meta

    def by_key(self, key: str) -> dict | None:
        for row in self.issues():
            if marker_in(row.get("body")) == key:
                return {"kind": "issue", "number": row.get("number"), "url": row.get("url"),
                        "title": row.get("title")}
        for it in self.items():
            content = it.get("content") or {}
            if marker_in(content.get("body")) == key:
                return _ref_from_item(it)
        return None


def option_id(field: dict | None, name: str) -> str | None:
    for o in (field or {}).get("options") or []:
        if o.get("name", "").lower() == str(name).lower():
            return o.get("id")
    return None


def _ref_from_item(it: dict) -> dict:
    """A board row as a ref — carrying BOTH ids a draft has.

    `item` (`PVTI_…`) is the position on the board: it is what `--field-id`
    writes and what `promote` converts. `draftId` (`DI_…`) is the draft's own
    content: it is what `--body` writes. Confusing them is not a typo either
    way — `gh project item-edit --id <PVTI_…> --body …` fails outright, and
    a run on 2026-09-02 lost every draft comment to exactly this before the
    fix. `gh project item-list --format json` returns both on the same row.
    """
    content = it.get("content") or {}
    draft = _is_draft(it)
    return {"kind": "draft" if draft else "issue",
            "item": it.get("id"),
            "draftId": content.get("id") if draft else None,
            "number": content.get("number"), "url": content.get("url"),
            "title": it.get("title") or content.get("title"),
            "body": content.get("body")}


def resolve_ref(board: Board, ref: str) -> dict:
    raw = (ref or "").strip()
    if raw.startswith("PVTI_") or raw.startswith("PVT_"):
        for it in board.items():
            if it.get("id") == raw:
                return _ref_from_item(it)
        raise BacklogError(f"No item “{raw}” on board #{PROJECT_NUMBER}.")
    m = re.search(r"(?:^#?|/issues/)(\d+)$", raw)
    if not m:
        raise BacklogError(f"“{ref}” is neither an issue number nor a board item id.")
    number = int(m.group(1))
    data = json.loads(gh("issue", "view", str(number), "--repo", SLUG,
                         "--json", "number,title,body,url,state,labels,milestone"))
    return {"kind": "issue", "item": None, "draftId": None, "number": data.get("number"),
            "url": data.get("url"), "title": data.get("title"), "body": data.get("body")}


# ---------------------------------------------------------------- ledger

def ledger_path(run_dir: str | None) -> Path | None:
    return Path(run_dir) / "backlog.jsonl" if run_dir else None


def append(run_dir: str | None, event: dict) -> dict:
    event = {"at": now(), **event}
    path = ledger_path(run_dir)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def run_id_of(run_dir: str | None) -> str | None:
    return Path(run_dir).name if run_dir else None


# ---------------------------------------------------------------- subcommands

def cmd_snapshot(args) -> dict:
    board = Board()
    rows = []
    for issue in board.issues():
        rows.append({
            "kind": "issue", "number": issue.get("number"), "title": issue.get("title"),
            "url": issue.get("url"), "state": issue.get("state"),
            "labels": [x.get("name") for x in issue.get("labels") or []],
            "milestone": (issue.get("milestone") or {}).get("title"),
            "updatedAt": issue.get("updatedAt"),
            "agencyKey": marker_in(issue.get("body")),
            "body": (issue.get("body") or "")[:4000],
        })
    for it in board.items():
        if not _is_draft(it):
            continue
        ref = _ref_from_item(it)
        rows.append({"kind": "draft", "item": ref["item"], "draftId": ref["draftId"],
                     "title": ref["title"], "agencyKey": marker_in(ref["body"]),
                     "body": (ref["body"] or "")[:4000]})

    milestones = json.loads(gh("api", f"repos/{SLUG}/milestones?state=open", "--method", "GET"))
    milestones = sorted(
        [{"number": m["number"], "title": m["title"], "dueOn": m.get("due_on"),
          "openIssues": m.get("open_issues")} for m in milestones],
        key=lambda m: m["dueOn"] or "9999")

    result = {"board": {"repo": SLUG, "projectNumber": PROJECT_NUMBER, "owner": OWNER},
              "items": rows, "issues": sum(1 for r in rows if r["kind"] == "issue"),
              "drafts": sum(1 for r in rows if r["kind"] == "draft"),
              "milestones": milestones,
              "cycle": milestones[0]["title"] if milestones else None}
    if getattr(args, "run_dir", None):
        out = Path(args.run_dir) / "evidence" / "backlog.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _body_file(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise BacklogError(f"--body-file “{path}” does not exist.")
    return p.read_text(encoding="utf-8")


def cmd_comment(args) -> dict:
    board = Board()
    ref = resolve_ref(board, args.ref)
    key = args.key or key_for_text(_body_file(args.body_file))
    body = _body_file(args.body_file)
    text = compose(body, key, run_id_of(args.run_dir))

    if ref["kind"] == "issue" and ref.get("number"):
        for c in json.loads(gh("issue", "view", str(ref["number"]), "--repo", SLUG,
                               "--json", "comments")).get("comments") or []:
            if marker_in(c.get("body")) == key:
                res = {"action": "exists", "kind": "comment", "key": key, "url": c.get("url")}
                return append(args.run_dir, {"kind": "comment", **res})
        if args.dry_run:
            return {"action": "would-comment", "key": key, "body": text}
        gh("issue", "comment", str(ref["number"]), "--repo", SLUG, "--body", text)
        res = {"action": "commented", "kind": "comment", "key": key, "number": ref["number"]}
        return append(args.run_dir, res)

    # A draft has no comment thread — the note is appended to its body.
    if marker_in(ref.get("body")) == key:
        res = {"action": "exists", "kind": "draft-note", "key": key, "item": ref["item"]}
        return append(args.run_dir, res)
    merged = ((ref.get("body") or "").rstrip() + "\n\n" + text).strip() + "\n"
    if args.dry_run:
        return {"action": "would-comment", "key": key, "body": merged}
    gh("project", "item-edit", "--id", ref["draftId"] or ref["item"], "--body", merged)
    res = {"action": "commented", "kind": "draft-note", "key": key, "item": ref["item"]}
    return append(args.run_dir, res)


def cmd_draft(args) -> dict:
    board = Board()
    key = args.key or key_for(args.title)
    existing = board.by_key(key)
    if existing:
        return append(args.run_dir, {"kind": "draft", "action": "exists", "key": key, **existing})

    text = compose(_body_file(args.body_file), key, run_id_of(args.run_dir))
    if args.dry_run:
        return {"action": "would-create", "key": key, "title": args.title, "body": text}
    data = gh_json("project", "item-create", str(PROJECT_NUMBER), "--owner", OWNER,
                   "--title", args.title, "--body", text)
    res = {"action": "created", "kind": "draft", "key": key, "item": data.get("id"),
           "title": args.title}
    return append(args.run_dir, res)


def cmd_promote(args) -> dict:
    board = Board()
    ref = resolve_ref(board, args.ref)
    if ref["kind"] != "draft":
        return {"action": "already-an-issue", "number": ref.get("number"), "url": ref.get("url")}
    if args.dry_run:
        return {"action": "would-promote", "item": ref["item"], "title": ref["title"]}

    node = gh("api", f"repos/{SLUG}", "--jq", ".node_id").strip()
    query = ("mutation($item:ID!,$repo:ID!){"
             "convertProjectV2DraftIssueItemToIssue(input:{itemId:$item,repositoryId:$repo}){"
             "item{id content{... on Issue{number url}}}}}")
    data = json.loads(gh("api", "graphql", "-f", f"query={query}",
                         "-F", f"item={ref['item']}", "-F", f"repo={node}"))
    content = ((data.get("data") or {}).get("convertProjectV2DraftIssueItemToIssue") or {}) \
        .get("item", {}).get("content") or {}
    res = {"action": "promoted", "item": ref["item"], "number": content.get("number"),
           "url": content.get("url"), "title": ref["title"]}
    if args.label and content.get("number"):
        flags = sum((["--add-label", lbl] for lbl in args.label), [])
        gh("issue", "edit", str(content["number"]), "--repo", SLUG, *flags)
        res["labels"] = args.label
    return append(args.run_dir, res)


def cmd_decide(args) -> dict:
    if args.disposition not in DISPOSITIONS:
        raise BacklogError(f"--disposition must be one of {', '.join(DISPOSITIONS)}")
    board = Board()
    ref = resolve_ref(board, args.ref)
    because = _body_file(args.because_file)

    lines = [f"### {DISPOSITION_HEADING[args.disposition]}", "", because.strip(), ""]
    lines.append(f"- **Commitment:** {args.commitment or 'none named'}")
    lines.append(f"- **Cycle:** {args.cycle or 'not set — see the standing brief'}")
    body = "\n".join(lines)
    key = args.key or f"decision-{args.disposition.lower()}-{key_for(ref.get('title') or args.ref)}"
    text = compose(body, key, run_id_of(args.run_dir))

    result: dict = {"disposition": args.disposition, "ref": args.ref,
                    "number": ref.get("number"), "item": ref.get("item")}

    if args.dry_run:
        result["comment"] = {"action": "would-comment", "body": text}
    elif ref["kind"] == "issue" and ref.get("number"):
        gh("issue", "comment", str(ref["number"]), "--repo", SLUG, "--body", text)
        result["comment"] = {"action": "commented"}
    else:
        merged = ((ref.get("body") or "").rstrip() + "\n\n" + text).strip() + "\n"
        gh("project", "item-edit", "--id", ref["draftId"] or ref["item"], "--body", merged)
        result["comment"] = {"action": "commented"}

    # Move `Stav` to match the disposition, for a draft or an issue alike —
    # both are board items and both carry the field.
    status_name = DISPOSITION_STATUS[args.disposition]
    if ref.get("item"):
        meta = board.meta()
        fld = meta["fields"].get(STATUS_FIELD)
        opt = option_id(fld, status_name)
        if args.dry_run:
            result["status"] = {"action": "would-move", "to": status_name}
        elif opt:
            gh("project", "item-edit", "--id", ref["item"], "--project-id", meta["id"],
              "--field-id", fld["id"], "--single-select-option-id", opt)
            result["status"] = {"action": "moved", "to": status_name}
        else:
            result["status"] = {"action": "skipped",
                                "why": f"“{STATUS_FIELD}” has no option “{status_name}”"}
    else:
        result["status"] = {"action": "skipped", "why": "not on the board"}

    # BUILD-NOW / FIX-REMOVE-NOW get a priority label once they are (or become) an issue.
    priority = DISPOSITION_PRIORITY.get(args.disposition)
    number = result.get("number") or ref.get("number")
    if priority and number and not args.dry_run:
        gh("issue", "edit", str(number), "--repo", SLUG, "--add-label", PRIORITY_LABELS[priority])
        result["label"] = PRIORITY_LABELS[priority]

    return append(args.run_dir, {"kind": "decide", "key": key, **result})


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    # A shared parent so `--run-dir` and `--dry-run` work on either side of
    # the subcommand name — argparse only honours a parser's own options
    # before its subcommand, and an agent should not have to remember that.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run-dir", help="RUN_DIR from context.json — where the ledger and "
                                          "evidence/backlog.json are written")
    common.add_argument("--dry-run", action="store_true",
                        help="show exactly what would be posted, post nothing")

    p = argparse.ArgumentParser(description=__doc__, parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot", parents=[common]).set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("comment", parents=[common])
    s.add_argument("--ref", required=True)
    s.add_argument("--key")
    s.add_argument("--body-file", required=True)
    s.set_defaults(fn=cmd_comment)

    s = sub.add_parser("draft", parents=[common])
    s.add_argument("--title", required=True)
    s.add_argument("--key")
    s.add_argument("--body-file", required=True)
    s.set_defaults(fn=cmd_draft)

    s = sub.add_parser("promote", parents=[common])
    s.add_argument("--ref", required=True)
    s.add_argument("--label", action="append")
    s.set_defaults(fn=cmd_promote)

    s = sub.add_parser("decide", parents=[common])
    s.add_argument("--ref", required=True)
    s.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    s.add_argument("--because-file", required=True)
    s.add_argument("--commitment")
    s.add_argument("--cycle")
    s.add_argument("--key")
    s.set_defaults(fn=cmd_decide)

    return p


def _force_utf8() -> None:
    """Windows consoles and pipes default to cp1250; Czech text in a board
    body or an issue title comes out as UnicodeEncodeError otherwise."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and not getattr(stream, "encoding", "").lower().startswith("utf"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv=None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    try:
        result = args.fn(args)
    except BacklogError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **result} if isinstance(result, dict) else result,
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
