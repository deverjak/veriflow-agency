# `agency backlog` — the only way this pack writes

Every outward-facing write goes through this command. Not because `gh` is
forbidden, but because four things live here and cannot live in a prompt:

1. **The signature.** One shape, from `config.signature`, on everything.
2. **The idempotence marker.** `<!-- agency:po:<key> -->` in every body. The
   next run finds what this run posted instead of posting it again.
3. **The write gate.** `config.writes.*` decides what may happen at all.
4. **The ledger.** `<RUN_DIR>/backlog.jsonl` records what was posted, in the
   repository, where it survives the ticket being deleted.

Call `gh` yourself and you get an unsigned duplicate that no later run can
recognise. There is no situation in which that is the right trade.

---

## Reading

```bash
agency backlog list --json                 # issues and drafts, with bodies
agency backlog list --mine                 # only what this pack has written
```

During a run you do not need this: `<RUN_DIR>/evidence/backlog.json` is the
same snapshot, frozen at the moment the run started, and
`<RUN_DIR>/evidence/backlog-written.json` is what past runs posted.

## Writing

```bash
# a note on the board — notifies nobody, costs nothing to delete
agency backlog draft --title "…" --body-file <RUN_DIR>/drafts/referral.md

# a real issue — lands in inboxes
agency backlog issue --title "…" --body-file <RUN_DIR>/drafts/hotfix.md --label bug

# a note becomes a commitment; the item keeps its id, column and fields
agency backlog promote PVTI_xxx --label enhancement

# a signed comment (on a draft it is appended to the body — drafts have no thread)
agency backlog comment 41 --text-file <RUN_DIR>/drafts/note.md

# the decision, with the reason, in public
agency backlog decide 41 not-now \
  --because "…" \
  --commitment "docs/roadmap.md#L18 — first booking under five minutes" \
  --revisit "at the 2026-Q4 boundary"
```

**Always `--body-file` / `--text-file` for anything with newlines.** Markdown on
a Windows command line arrives mangled, and the file is worth keeping: it is
exactly what was posted.

`decide` does up to three things in one call — comment, board column, labels —
and each only where `config.writes` allows it. What it could not do it reports
in its output; that belongs in `run.json`, not in a workaround.

## Idempotence

Every write carries a key. Without `--key` it is derived from the title, which
is what makes it stable across runs and machines: a random id would be unique
and useless.

A write whose key already exists returns `{"action": "exists", …}` and posts
nothing. That is a success, not an error — do not retry it with a changed
title to get past it.

```bash
agency backlog draft --title "Referral programme" --key referral-q4 --body-file …
```

Pass `--key` explicitly when the title is likely to be reworded and the thing
is still the same thing.

## Rehearsal

```bash
agency backlog draft --title "…" --body-file … --dry-run
```

Prints the exact body, including the signature, and posts nothing.
`writes.dryRun: true` in the configuration does the same for every write in the
project — which is how a new installation is meant to be run for a few days.

## When it refuses

| Message | What it means | What to do |
|---|---|---|
| `` `writes.issues` is off `` | the project has not allowed this action | record it in `run.json` and name the switch. Do not route around it |
| `board.projectNumber` missing | drafts live inside a Project and this project has no board | issues still work; say so |
| `{"action": "exists"}` | already written, by this run or an earlier one | nothing. It is done |
| the gh token has no `project` scope | reading works, board writes do not | `gh auth refresh -s project` — a human runs it |

## What it never does

- Close a ticket. `writes.close` exists and defaults off; a cut is a comment
  and a column, so that somebody can find the conversation later.
- Create a label. A label that does not exist in the repository is reported and
  skipped, and the ticket is still filed.
- Delete a draft. Including on promotion — GitHub converts the item in place,
  so it keeps its id, its column and its field values.
- Edit someone else's comment.
