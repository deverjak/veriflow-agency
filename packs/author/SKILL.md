---
name: agency-author
description: "Use when this project needs a specialist it does not have — 'an agent that watches our database migrations', 'someone to review our API contracts', 'a pack for accessibility'. Triggered by `agency run author --prompt \"…\"`, which resolves the project and writes a context bundle; this skill then reads the repository to learn what it is and what its existing packs already cover, asks the founder only what the repository cannot answer, agrees the dimensions out loud, and writes `.claude/skills/agency-<name>/` — pack.json, SKILL.md and its references. Also usable directly: 'write me a pack for X', 'why does agency-qa not see Y', 'this pack's dimensions are too vague, rewrite them'. It never runs the pack it wrote and never commits — the first real run and the commit are the founder's."

---

# Pack author

Every specialist in this system is a directory in the repository — `pack.json` next to `SKILL.md`, under `.claude/skills/agency-<name>/`. Nothing installs it, nothing versions it, there is no registry and no configuration file. **Writing one is a code-writing task**, and this is the pack that does it.

The failure this exists to prevent is not a broken `pack.json` — that one announces itself on the next run. It is a pack that **loads perfectly and judges nothing**: dimensions like "code quality", findings nobody can act on, a `sink` pointed at a board that does not exist. Such a pack passes every check, produces noise, drags the project's precision number down, and teaches the founder to stop reading the panel. Preventing that is the whole job, and it is done in the interview, not in the JSON.

**You produce one thing, and it is source code.**

| | What it is | Where it goes |
|---|---|---|
| **The pack** | `pack.json`, `SKILL.md`, `references/`, sometimes `scripts/` | `.claude/skills/agency-<name>/` — **uncommitted**, in the working tree |
| **The record** | what you settled, what you assumed, what is still open | `<RUN_DIR>/summary.md` |
| **The memory** | which specialists this project has and why, so the next one does not overlap | `.agency/knowledge/pages/author/roster.md` |

**You write no findings.** `<RUN_DIR>/findings.json` is `[]`, and that is the correct outcome — the run finishes as `no-findings` in the panel, because this run was not looking for anything. Two reasons, both real: the pack you just wrote is not committed, so an anchor into it would not exist at `target.headRefOid` and the gate would drop it; and what you would want to report — "the board does not exist", "this dimension is vague" — is something the founder can answer *now*, in the terminal, not in three days on a board. Say it out loud instead.

## What you get ready

`agency run author` did the deterministic part. **Do not do it again.** Read:

```
<RUN_DIR>/context.json                 the prompt, the project, the state of the working copy
<RUN_DIR>/evidence/recent-commits.txt  what has been happening in this project lately
<RUN_DIR>/evidence/changes.txt         the diff against the base branch, when there is one
<RUN_DIR>/evidence/known-pages.json    your own pages: which specialists were written before, and why
<RUN_DIR>/evidence/known-findings.json what this project's existing packs actually find
<RUN_DIR>/evidence/do-not-report.md   what this project already rejected — read it first
<RUN_DIR>/evidence/known-here.json    what was ever found in the code this run touches
<RUN_DIR>/run.json                     the run record you complete at the end
```

`context.json` carries, among other things:

| Key | Meaning |
|---|---|
| `prompt` | the description of the specialist to write — free text, **required** for this pack |
| `project.root` | the project you are writing for. `.claude/skills/` is under it |
| `pages` | where your own conclusions go (`.agency/knowledge/pages/author`) |
| `knowledge` | the project's committed memory (`.agency/knowledge/`) — start at `index.md` |
| `review.dimensions` | **your** interview agenda, below — not the new pack's dimensions |
| `worktreeOwned` | `false` — you are in the founder's working copy |
| `chain` | `null`. This pack is never a chain member; see *Boundaries* |

When `context.json` is missing you are running outside `agency run`. That is fine — this skill is usable directly. Read the project yourself, and skip only the parts that name `<RUN_DIR>`.

## Boundaries that do not move

- **You may write into `.claude/skills/agency-<name>/` and nowhere else in the source.** That directory is new and yours. Everything else in the working copy is for reading. Do not touch another pack unless the founder asked you to fix that pack.
- **You do not commit, do not stage, do not branch.** The pack is a draft in the working tree and git is the review — the founder reads the diff in Source Control like any other change. Say so when you finish; do not offer to commit.
- **You cannot run the pack you wrote.** `agency run` and `agency chain` refuse to start inside an agent — a run is a leaf, and one an agent started would have no terminal and no authorization behind it. The dry run is the last line of your summary, for the founder to paste. Do not attempt it and then report the refusal as a problem.
- **You do not invent facts about the project.** Every concrete claim that ends up in the new `SKILL.md` — a URL, a board, a command, a credential path, a role — was either read out of the repository this run or answered by the founder this run. Anything else is written as *unverified, confirm before relying on it*, exactly the way `packs/ceo/SKILL.md` marks its own starting register.
- **One pack per run.** If the prompt describes three specialists, say which one you are writing and why that one first.

## 1. Read the project before you ask anything

The prompt says what kind of specialist is wanted. It steers *what you read*, not whether you read. Work outwards from cheapest:

```bash
agency packs --json          # which specialists exist, their dimensions, targets, sinks
agency doctor --json         # what this project's prerequisites actually look like
git log --oneline -n 40      # or evidence/recent-commits.txt, already collected
```

Then the repository itself, steered by the prompt:

- **What is this project.** `README*`, `CLAUDE.md`, `docs/`, `package.json` / `pyproject.toml` / `go.mod` — language, stack, how it is built, how it is tested, how it is deployed.
- **What already runs against it.** CI workflows, lint and typecheck commands, existing test suites. **A finding CI would already catch is noise** — the new pack has to know what to stay off, and that knowledge belongs in its `SKILL.md` as a named command, the way `agency-qa` names `npm run verify`.
- **Whether there is a board.** This decides `sink`, and getting it wrong is the most expensive mistake on the list:

  ```bash
  gh repo view --json name,owner,hasIssuesEnabled
  gh issue list --limit 5
  gh project list --owner <owner> --limit 10
  ```

  No board is a completely normal answer — `packs/ceo/pack.json` has no `sink` for exactly that reason, and its findings rest as `candidate` in the committed knowledge. Do not invent a board, and do not write a `sink` that shells out to a script you also invented.
- **What the existing packs already cover.** Read their `SKILL.md` files, not just their dimension titles. **The new pack must not re-ask a question another pack already owns** — overlapping dimensions produce duplicate findings, the dedup ratio absorbs them, and the founder reads the same thing twice. Where the subject genuinely touches an existing pack, the boundary goes into both descriptions in words.
- **Its own memory.** `evidence/known-pages.json` holds what past authoring runs concluded about this project's roster. `evidence/known-findings.json` shows what the existing packs actually find — that is the best available evidence of what this project's findings look like when they are good.

Write what you learned into `<RUN_DIR>/notes.md` as you go. It is your scratch, not a deliverable.

## 2. Ask only what the repository cannot answer

**Hard rule: never ask a question the repository already answers.** A wizard that asks the founder to type the test command that is sitting in `package.json` has learned nothing and wasted their attention — and attention is the scarce thing here, the same way it is in `packs/ceo/SKILL.md`.

Ask **in one batch**, numbered, with your own best guess next to each so the founder can answer "1, 3 yes, 2 is actually X" instead of writing an essay. You are in a visible terminal and the run is attended by design — this is a conversation, not a form.

What genuinely needs asking, in roughly this order:

| Dimension | The question behind it |
|---|---|
| `subject` | What does this specialist judge — and what, that a reader might expect, is **not** its job? |
| `facts` | What is true about this project that a fresh reader of the repository would get wrong? Staging hosts, which environment is safe to touch, which service is authoritative, who the users are. |
| `dimensions` | For each candidate question: what does a **bad** answer look like here? If you cannot describe one, it is not a dimension. |
| `evidence` | What would convince you? A failing test, a log line, a diff, a cited page? What would you refuse to accept? |
| `sink` | When it finds something real, where should that land — and who reads it there? |
| `boundaries` | What must this specialist never do? Never deploy, never write to production, never send anything, never open an issue itself. |

If the founder's answer contradicts what you read in the repository, say both and let them settle it. They may be describing where the project is going rather than where it is; that belongs in the new `SKILL.md` marked as intent, not as fact.

## 3. Agree the dimensions out loud — this is the checkpoint

Do not skip this and do not fold it into the writing step. Show the proposed dimensions, get them cut, renamed or replaced, and only then write files.

A dimension is **one question whose answer can come back false, about something a finding can point a line number at.** The full rules and worked rewrites are in [`references/dimensions.md`](references/dimensions.md); the short form:

- **`perf` — "Performance"** is not a dimension. Nothing is false about it.
- **`perf` — "Queries on a request path with no index behind them"** is one. It is wrong when the index exists, and it lands on a file and a line.

Four to seven of them. Fewer than four and the pack is a single check that would be better as a lint rule; more than seven and no run covers them all, so the last two silently never fire.

Each dimension gets an `id` (short, kebab-case, stable — it is written into every finding and into the metrics, so renaming it later breaks the history) and a `title` that states the question in the founder's own vocabulary.

## 4. Write the pack

Create `<project.root>/.claude/skills/agency-<name>/`. The directory name and the `name` in `pack.json` have to agree: skill `agency-migrations` ↔ `"name": "migrations"` ↔ `agency run migrations`.

### `pack.json` — only what the runner needs

Everything here is read by the core. Anything the *agent* acts on belongs in `SKILL.md` instead — there is no configuration file in this system, and adding a key the runner does not read is how one starts.

| Key | What it does |
|---|---|
| `name` | `<name>` from the directory. The word after `agency run`. |
| `title` | What the panel shows. `"QA engineer · NaLekci"` — the role, then the project. |
| `description` | One paragraph, for the panel's tooltip and the pack picker. What it does and what it refuses. |
| `requires` | Binaries `agency doctor` checks **before** a run starts — `["git"]`, `["git", "gh"]`, `["git", "npx"]`. |
| `target` | `"workspace"` (the project as it is, uncommitted work included) or `"pull-request"`. |
| `worktree` | `true` only for a pull-request pack that needs a throwaway checkout. `false` means it reads the founder's working copy — and then the source is **read only**. |
| `graph` | `false`, or `{"required": […], "optional": […]}` when dimensions need the code graph. A missing capability degrades a dimension, and `agency doctor` says so up front. |
| `prompt` | `"required"` (it cannot work without an assignment), `"optional"` (a prompt narrows it), `"none"`. |
| `needs` | The commands the agent is allowed to run, as **prefixes**: `"git"`, `"gh issue list"`, `"npx playwright test"`. Web access is a tool rule, not a command: `"WebSearch"`, `"WebFetch"`. Write and Edit are granted already — do not list them. |
| `needsUnattended` | Consequential commands granted **only** when nobody could answer a prompt (a chain member, or `--unattended`). A command here keeps asking on a normal attended run. This is where `promote`, `decide`, anything hard to undo belongs. |
| `minScore` | The gate's threshold, default 70. Raise it for a domain where a weak finding costs more than a missed one. |
| `budget` | `{"turns": 60, "minutes": 25}` — what a NORMAL run of this pack costs. Both optional. It is a declaration, not a limit: over it the run is flagged and carries on, and only at three times over is it stopped as a runaway. Guess from what the method actually does — a pack that reads one diff is not a pack that drives a browser — and expect to correct it once real runs exist. |
| `sink` | The command that puts one gated finding on the board, with `{id}` and `{runDir}`. **Omit it entirely when there is no board.** |
| `dimensions` | `[{"id": …, "title": …}]` from step 3. |

Two things about `sink` that are easy to get wrong: the command runs from the project root with `AGENCY_RUN` in its environment, and it must **exit 0 and print JSON** carrying `item` or `ref` (and `url` when it has one) — anything else and the finding stays `candidate` and `agency ingest` retries later. So it also has to be **idempotent**, which is what the marker comment in `packs/po/scripts/backlog.py` is for. If the project has a board but no such script yet, say so plainly: leave `sink` out, tell the founder the pack will hold its findings in the knowledge until a sink script exists, and make that the next piece of work rather than shipping a sink that half-posts.

### `SKILL.md` — where the value actually is

Frontmatter is two keys, and `name` must be the skill directory's name:

```yaml
---
name: agency-<name>
description: "Use when … Triggered by `agency run <name>`, which resolves the project and writes a context bundle; this skill then … Also usable directly: '…', '…'. Not for … — use the agency-<other> pack for that."
---
```

The body follows the shape the existing packs share, because a founder reading their third pack should not have to learn a third layout. Read `packs/qa/SKILL.md` and `packs/ceo/SKILL.md` side by side before you write — they are the reference, and the sections below are what they have in common:

1. **The opening** — the failure this specialist exists to prevent, in the project's own terms. Not "reviews the code" but the concrete bad outcome.
2. **Project facts** — *"Read this section instead of a configuration file — there isn't one."* Hosts, credentials paths, safety rules, what CI already covers, which language findings are written in, the session budget. **This section is why a pack is worth writing at all**; without it the pack is a generic prompt. Mark anything unverified as unverified.
3. **What you get ready** — the `<RUN_DIR>` listing and the `context.json` table, adapted to what this pack actually reads. Copy the shape; do not invent keys.
4. **Boundaries that do not move** — what it must never do, stated as rules rather than preferences, with the reason attached. A rule whose reason is written down survives a model change; one without it gets rationalised away.
5. **The method, numbered** — how it works, one step per heading, ending in a deterministic gate: what must be true before an observation is allowed to become a finding, and the explicit list of what to drop (already caught by CI, already rejected before, environmental, a matter of taste).
6. **Anchoring** — `file` + `line` relative to the project root, `commit` = **all 40 characters** of `target.headRefOid`, `endLine`, `snippet` of the whole block, `symbol` where the graph can give one. A finding with no valid anchor does not survive `agency ingest`, so this section is not decoration.
7. **Writing `findings.json`** — one worked `finding.v1` example with this pack's own dimension and its own kind of evidence. Concrete beats abstract.
8. **The project's memory** — `.agency/knowledge/pages/<name>/`, plain markdown, first line `Last reviewed: <date>`, then a `# Heading` — the index takes the page title from that heading. **Conclusions, not a diary**: the chronology is already in `log.md`, and a page that repeats it will eventually contradict it.
9. **When you are running in a chain** — how to write `handoff.md`, and that starting other runs is refused.
10. **When you cannot go on** — `blocked.md`, and it is not optional. Copy the section from `packs/qa/SKILL.md` with this pack's own examples of a wall (its staging, its board, its login). Without it the pack has no word for "I hit something I cannot get past", so it writes an empty `findings.json` instead and the run is recorded as `no-findings` — the same status a pack gets for looking honestly and finding nothing. A specialist that cannot tell those two apart cannot be run unattended, which is most of what a specialist is for.

Put anything long — a decision method, a domain checklist, a playbook — in `references/*.md` and link it, the way `packs/ceo/` does. `SKILL.md` stays the method.

## 5. Verify it loads

```bash
agency packs --json
```

The new pack appears in that list, with the title you wrote, or it does not load — that command parses `pack.json` and validates `prompt` against the three legal modes, so it is a real check and not a formality. Then:

```bash
agency doctor --json
```

which checks `requires` and, when you wrote one, that the `sink`'s first token exists on this machine.

Fix what either one says before you finish. A pack that does not appear in `agency packs` is not a draft, it is a broken file.

## Revising a pack that already exists

`context.json` → `revise` is `null` for everything above. When it is not, this run is **not** writing a new specialist: it is rewriting the method of one that has been running, against its own record. Everything in sections 1–6 gives way to this section.

You get:

| Where | What |
|---|---|
| `revise.pack` | which pack's method you are rewriting |
| `revise.brief` | `evidence/for-author.md` — **read this first, whole** |
| `revise.briefData` | the same as JSON, when you need a number rather than a sentence |
| `revise.skill` | the pack's directory: `SKILL.md`, `pack.json`, `references/` |

The brief is what this run is for. It carries precision per dimension **with counts**, which dimensions have found nothing for twenty runs, why the gate dropped things, canonical examples of findings that held up and findings that did not, runs that ended `blocked`, tools the pack was refused, and what happened after each previous change to the method.

**The run refuses to start below ten decided findings**, so if you are reading this, there is enough to work from. That does not make every number in the brief a signal: a dimension with one decided finding is one finding, the brief says so on every row, and treating it as a precision is the single most likely way to make this pack worse.

### What you may change, and what you may not

| May | May not |
|---|---|
| dimensions — rephrase, split, merge, delete | `sink`, `needs`, `name` |
| `evidence` on a dimension (which kinds of proof it stands on) | anything outside `.claude/skills/agency-<pack>/` |
| `minScore`, `budget` | facts this run did not read in the repository or hear from the founder |
| *Project facts* — only facts you verified this run | any other pack |
| the method's steps, its filters, its examples | the pack's subject: a reviewer does not become a QA engineer |

`needs` and `sink` are out of bounds because they are authorization and delivery — they decide what the pack is allowed to do and where its findings go, and neither is something a record of past findings can argue about. If the brief shows a tool being refused every run, that goes in `summary.md` as a recommendation for the founder, not into `pack.json` by your hand.

### How to decide what to change

Work from the brief, one claim at a time, and be able to name the rows behind each change:

- **A dimension with low precision and enough decided findings** is either asking a question this project does not care about, or asking it too loosely. Read the rejected examples: if they were rejected as `by-design`, the dimension is judging a deliberate choice and should be narrowed or dropped. If they were `wrong-diagnosis`, the dimension is right and the method for it is weak — that is a step to rewrite, not a dimension to delete.
- **A dimension that has found nothing for twenty runs** is a candidate for deletion. Not automatically: it may be rare and right. Say which you think it is and why.
- **`weak-evidence` or `unproven-source` in the gate reasons** means the method lets the pack cite the wrong kind of proof. Fix the step that produces it, and consider declaring `evidence` on that dimension.
- **`stopBlocks` above zero on most runs** means the method's output section is not clear enough — the pack is writing `findings.json` wrong and being sent back.
- **Repeated `blocked` runs** are a wall the method walks into. That is usually one sentence in *Project facts* ("staging is behind the VPN; check it answers before you plan around it") rather than a new dimension.

### What you write

The same shape as writing a new pack, with one addition: **every change has a reason from the brief.**

- The edited `SKILL.md` / `pack.json`, **uncommitted, in the working tree.** Git is the review — the founder reads the diff in Source Control like any other change. Do not commit, do not stage, do not branch.
- `<RUN_DIR>/summary.md`, and here it matters more than anywhere else. One line per change: what you changed, and the number or the example that made you change it. A change you cannot attribute to a row in the brief is a change you invented — either find the row or drop the change.
- Say what you **deliberately left alone**, too. A pack whose numbers are fine does not need rewriting, and "nothing here should change yet" is an honest and complete result for this run.
- `<RUN_DIR>/findings.json` → `[]`.

**One thing that is not yours to decide:** whether the revision was an improvement. That is what `agency replay` answers, over the fixtures pinned from real runs, and its rule is absolute — a change that brings back a previously rejected finding is a regression and does not ship. Say in `summary.md` that the founder should replay before committing.

## When you cannot go on

Some runs end at a wall rather than at an answer: staging does not respond, `gh` is not logged in, the board has no field this method assumes exists. Say so — write `<RUN_DIR>/blocked.md`:

```markdown
# Blocked

**What I could not do:** verify the cancellation flow on staging.
**Why:** https://staging.example.com returned 502 on every attempt (12 tries, 10 min).
**What would unblock me:** a staging URL that answers, or permission to run it locally.
**What I did instead:** nothing — the remaining dimensions all depend on this one.
```

The run is then recorded as `blocked` instead of `no-findings`, and that distinction is the whole point. An empty `findings.json` on its own says "I looked and there is nothing there" — which is a good result — and nobody reading it can tell that apart from "I never got started". **Silence is not a result.**

Three rules:

- **It is not a question.** Nothing waits for an answer; a run nobody is watching has nobody to ask. Write the file and finish.
- **What you did manage still counts.** Write those findings as usual — being blocked does not throw them away, and a partial answer beats no answer.
- **Only for a wall you actually hit.** A dimension that honestly found nothing is finished, not blocked. Claiming otherwise turns the one word for "fix something" into noise.

## 6. Hand it over

Write `<RUN_DIR>/summary.md` — **at most 30 lines**, plain words:

- what you wrote, and the one-sentence version of what it judges;
- the dimensions, with the reason for anything the founder cut or renamed;
- **every assumption still standing** — each fact you could not verify and marked as unverified in the new `SKILL.md`;
- what is deliberately missing: no sink because there is no board, no `scripts/` because nothing needed one;
- the exact command to try it, on its own line, for the founder to paste:

  ```
  agency run <name> --prompt "…"
  ```

Then `.agency/knowledge/pages/author/roster.md` — `Last reviewed: <date>`, a `# Heading`, and one short section per specialist this project has: what it judges, what it deliberately does not, and where its boundary with the neighbouring pack runs. This is what stops the fourth pack from overlapping the second. Rewrite entries that stopped being true; do not append a new one next to a stale one.

Complete `run.json` — `status`, `finishedAt`, `counts`, `cost` — and write `[]` into `<RUN_DIR>/findings.json`.

Finish by telling the founder, in the terminal, three things: the pack is **uncommitted** and sitting in their working tree for review, the dry-run command, and that **a pack is not real until its first run has been read** — the dimensions are a guess until findings come back and either land or turn out to be noise. Offer to come back and cut the ones that produced nothing.
