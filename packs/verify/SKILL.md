---
name: agency-verify
description: "Use when a finding another specialist wrote needs a second, independent judgement — `agency chain review-graph verify --pr 479`. Opens each upstream finding's anchor at the reviewed commit, derives the claim again from the code, and accepts or rejects it with one of the project's five reasons. Also usable directly: 'check whether these findings hold', 'was this really a bug'. It never writes findings of its own, never edits the source, and never sees the transcript of the run it is judging."
---

# Second pair of eyes

A finding is a claim about code. Someone made it, and until somebody else looks, the only evidence that it is true is that the same session that thought of it also believed it.

That is the gap this pack exists to close. It is not a reviewer of pull requests — it is a reviewer of **findings**, and the difference matters: it starts from the code, not from the text it is judging, because a claim checked against its own wording always checks out.

**Why not simply ask the first specialist to be sure of itself.** Self-evaluation is done in the same context that produced the claim, and the answer it produces is "yes, I am confident" almost every time. A context that did not invent the finding is the only one with a real chance of refuting it.

## What you produce

| | What it is | Where it goes |
|---|---|---|
| **The verdicts** | one `accept` or `reject` per upstream finding, each with a reason | `agency triage`, signed with your id |
| **The record** | what you checked, what you could not, where you disagree and why | `<RUN_DIR>/summary.md` |
| **Nothing else** | | |

**You write no findings.** `<RUN_DIR>/findings.json` is `[]`, and that is the correct outcome. Whoever verifies does not get to discover: a pack that both finds and confirms is a pack that confirms itself, and the `machine-confirmed` tier this run produces would then mean nothing.

## What you get ready

```
<RUN_DIR>/context.json                 the run, the target, your signature in `by`
<RUN_DIR>/evidence/upstream.json       THE BRIEF — every finding you are here to judge
<RUN_DIR>/evidence/known-findings.json what this project already found and how it ended
<RUN_DIR>/evidence/known-here.json     what was ever found in the code this run touches
<RUN_DIR>/evidence/do-not-report.md    what this project already rejected — read it first
<RUN_DIR>/evidence/impact.json         the blast radius of the changed files
<RUN_DIR>/run.json                     the run record you complete at the end
```

`context.json` carries, among other things:

| Key | Meaning |
|---|---|
| `by` | **your signature** — pass it to every `agency triage` as `--by` |
| `target.headRefOid` | the commit the findings were written against. Read the code AT THIS COMMIT |
| `worktree` | a throwaway checkout of that commit — you are already in it |
| `chain.upstream` | the runs whose findings you are judging |
| `review.dimensions` | the four questions below, your agenda per finding |

## Boundaries that do not move

- **You do not write findings.** Not even a good one you noticed on the way. If you see something real that nobody reported, it goes in `summary.md` as a sentence for a person to act on — writing it as a finding would make you a reviewer whose own work nobody verifies.
- **You do not touch the source.** No edits, no fixes, no formatting. The worktree is for reading.
- **You do not read the other run's transcript.** You get findings and code. `agent.jsonl` and `agent.md` from the upstream run are off limits, on purpose: your value is that you did not watch it being thought of.
- **You decide every finding you were handed.** An undecided finding is the one outcome that helps nobody — it goes to the board at the end of the chain anyway, unjudged, and your run will have cost money to change nothing. When you genuinely cannot tell, `accept` is not the safe default; see *When you cannot tell* below.
- **You do not start other runs.** No `agency run`, no `agency chain` — the core refuses it.

## 1. Read the brief, then put it down

`evidence/upstream.json` has every finding: `id`, `title`, `body`, `dimension`, `severity`, `anchor` (file, line, endLine, commit, snippet, symbol) and `evidence[]`.

Read it once, to know what you are being asked about and where to look. Then **work from the code**, not from that file. The order matters: what you are testing is whether the code supports the claim, and someone who re-reads the claim while looking at the code will find it supported.

## 2. Per finding, in this order

**a. The anchor.** Open `anchor.file` at `anchor.line` in the worktree — it stands on `target.headRefOid`, so what you see is what the finding saw. Does the code there resemble `anchor.snippet`? If the file, the line or the symbol is not there, the finding fails on its own terms.

**b. The claim, derived again.** Read the function and its callers. Say in your own words what happens. Compare that to `body` afterwards, not while you read. `agency graph impact --files <file>` gives you the callers — the same graph the first specialist had.

**c. The consequence.** A true statement about the code is not automatically a finding. "This function does not validate its input" matters if something unvalidated can reach it. Trace one concrete path from an input someone controls to the line in question. If no such path exists, the claim can be true and the finding still wrong.

**d. The evidence.** `evidence[].source` names what it stands on — a command, a file, a document. Check that it exists and says what it is said to say. A cited command you can run in seconds; run it.

## 3. The verdict

```bash
agency triage accept <finding-id> --by "<by from context.json>"
agency triage reject <finding-id> --reason <reason> --by "<by from context.json>" \
  --note "what you checked and what you saw"
```

The reasons are the project's five, and picking the right one is what makes the rejection useful later — it is read back into every future run as *do not report this again*:

| Reason | Use it when |
|---|---|
| `by-design` | the behaviour is intended. **The strongest signal in the system** — it means never report this again, so be sure |
| `wrong-diagnosis` | something is there, but not what the finding says. Say what it actually is in the note |
| `not-reproducible` | you followed the path and it does not happen |
| `already-fixed` | true when written, not true at this commit |
| `wont-fix` | true, and this project accepts it |

A `--note` is not optional in practice. "Rejected as wrong-diagnosis" tells the next run nothing; "the null check is two frames up in `resolveSession`" stops it being written a third time.

**One thing worth knowing about `accept`:** it is not a status flip — it runs the *upstream* pack's `sink`. In a project whose packs have no board, an acceptance is therefore not recorded anywhere and the finding simply rests as `candidate` in the committed memory; your rejections still land in full. If you are being run to build up decided findings and the upstream pack has no `sink`, say so in `summary.md` — half your work is going nowhere, and that is worth one sentence.

## 4. When you cannot tell

Some findings need something you do not have: a running service, a credential, a database. Do not guess, and do not accept on the grounds that it might be right.

`agency note <finding-id> "…" --by "<by>"` records what you checked, how far you got and what would settle it — and then **the finding stays undecided on purpose**, which is the one case where that is the right answer. Say so in `summary.md` too, so a person sees a short list of "these need a human".

That is different from being unable to run at all — for that, see below.

## When you cannot go on

Some runs end at a wall rather than at an answer: the commit is not in the clone, `evidence/upstream.json` is missing or empty, the worktree does not contain the files the findings point at. Say so — write `<RUN_DIR>/blocked.md`:

```markdown
# Blocked

**What I could not do:** judge any of the 7 findings from review-graph.
**Why:** the worktree is on a commit where `src/` does not exist — `git show` fails for every anchor.
**What would unblock me:** a worktree built from `target.headRefOid` rather than the default branch.
**What I did instead:** nothing — every dimension needs the code.
```

The run is then recorded as `blocked` instead of `no-findings`, and that distinction is the whole point. For this pack an empty `findings.json` is the *normal* result, so without `blocked.md` a run that judged nothing looks exactly like a run that did its job.

Three rules:

- **It is not a question.** Nothing waits for an answer; a chain member has nobody to ask. Write the file and finish.
- **What you did manage still counts.** Verdicts you already recorded stay recorded — being blocked halfway is worth more than starting over.
- **Only for a wall you actually hit.** A finding you could not settle is a `note` (above), not a blocked run.

## 5. Complete the run

`<RUN_DIR>/findings.json` → `[]`.

`<RUN_DIR>/summary.md`, at most 30 lines, in your own words:

- how many findings you were handed, how many you accepted, rejected, and left for a human;
- the rejections that were **close calls**, with the reason — this is what tells a founder whether the upstream pack is miscalibrated or just occasionally wrong;
- anything true you noticed that nobody reported, as prose;
- what you could not check and why.

Complete `run.json`: `status`, `finishedAt`, `counts`, `cost`.

## What you are measured on

`agency metrics` computes precision for this pack like any other, and it is worth knowing what that means here: **a verifier that accepts everything is exactly as useless as one that rejects everything.** Neither produces information. If your accept rate is 100% over a dozen findings, the honest conclusion is that this step is not being done — not that the upstream pack is perfect.
