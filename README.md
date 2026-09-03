# VeriFlow Agency

Specialists for a repository. Attended, on your own login, with evidence-backed
findings that stay.

A specialist is not something you install — it is a **skill that lives in the
target project**, next to the code it works on:
`.claude/skills/agency-<name>/pack.json` beside its `SKILL.md`. Nothing hires
it, nothing configures it. What it knows about the project — which repo,
which board, which staging URL, which law applies — is written into the skill
as fact, the same way the code itself is project-specific. A second project
gets a **copy** of the pack and rewrites its facts, not a shared parameter.

## The five workflows over `main-panel`

This is the whole product. `agency` runs specialists against one project;
what each one finds goes through a gate (evidence required, no duplicates),
gets a decision from a human, and stays in the project's own memory.

**W1 — Review a pull request**

```
agency run review-graph --pr 479
```

Prepares a throwaway worktree on the PR's head commit, has the code graph
compute blast radius, and gives you the command to launch the agent — in this
terminal, or with `--wait` to launch and gate it in one step. When it is
done:

```
agency findings                     # what is waiting for a decision
agency triage accept 01M1…          # or reject --reason by-design, or defer
agency export --project 1           # accepted findings → GitHub Project drafts, once each
```

The same thing in the editor: findings sit next to the line of code, with
Accept / Reject / Defer buttons.

**W2 — Review with a product judgment**

```
agency chain review-graph po --pr 479 --prompt "does this change make product sense?"
```

The reviewer runs first; the product owner gets its findings **as its
brief** — decides each one (accept / reject with a reason / defer), answers
the question, and writes what that means for the queue. A human sees a
judged queue, not a raw one.

**W3 — Backlog grooming**

```
agency run po --prompt "what should build now, given we're waiting on the s.r.o. filing and rolling out payments"
```

The product owner snapshots the board — open issues with milestones, drafts
with their fields, the nearest open milestone as the current cycle — decides
each item against one of five dispositions (`BUILD-NOW`, `FIX-REMOVE-NOW`,
`VALIDATE-CHEAPLY`, `DEFER-WITH-TRIGGER`, `REJECT`), and **writes the
decision on the board itself**: a signed comment, a status move, a priority
label, a draft promoted to an issue. Only what is wrong with the queue
itself becomes a finding.

**W4 — QA session on staging**

```
agency run qa --prompt "booking and cancelling a lesson, on mobile"
```

Explores the running staging application as a written-out persona, in a
clean browser session. Every finding is reproduced before it is written, and
anchored to the line of code that causes it.

**W5 — Legal review**

```
agency run legal --prompt "terms of service for instructors before online payments launch"
```

Walks the legal surface of the product against what Czech and EU law
actually say, citing the provision from the primary source. It also reports
duties the product invented for itself — a re-consent screen for a change
already covered by an existing mechanism, for instance — because a model
tuned to be careful about law tends to over-comply, and over-compliance is
a cost too.

### Memory anyone can read

`.agency/knowledge/` is a **committed** directory of markdown: a ledger of
findings generated from runs, and pages written by the specialists
themselves (`pages/po/decisions.md`, `pages/qa/coverage.md`,
`pages/legal/applicability.md`, …). A plain Claude Code or Codex session in
the repo reads it. So does a colleague in an editor. So does `agency
knowledge`.

## Installation

```powershell
pwsh scripts/install.ps1
```

Installs the core via `uv` (editable) and the extension as a VSIX. Individually:
`-Core`, `-Extension`.

Prerequisites: `git`, `uv`, VS Code 1.85+; a reviewer additionally needs `gh`
(logged in) and a code graph tool; QA needs Playwright's browsers installed.
`agency doctor` checks all of it — **before** a run, not halfway through —
and only asks about what the packs actually in the project need.

## Shape

Three things, each with one responsibility. The boundary between them is a
contract, not configuration.

```
veriflow-agency/                     this repository
  packages/core/     → `agency`      RUNNER — run, record, gate, triage, dedup, memory, chain, providers.
                                     Knows nothing about any target project.
  packages/extension/                VIEWER — runs, findings next to the line, triage by clicking.
                                     Talks only to `agency … --json`.
  packs/                             EXAMPLES — reference copies of main-panel's packs, for the next project.
                                     Not bundled, not installed.

<target-project>/
  .claude/skills/agency-po/          PACK = skill. Committed and versioned with the project.
    pack.json                          what the runner needs to know
    SKILL.md                           the method + Project facts, in English
    references/                        policy documents (feature-admission.md, severity.md, …)
    scripts/backlog.py                 the pack's own tool — called by the agent, not by the runner
  .claude/skills/agency-qa/  … agency-legal/  … agency-review-graph/
  .agency/
    knowledge/                       MEMORY, committed
    runs/<ULID>/                     RECORDS, gitignored (evidence, transcripts, findings.json, run.json)
```

There is no `~/.agency/`. There is no project configuration file. A pack
lives where Claude Code already looks for a skill, and the runner finds it
there too — `pack.json` next to `SKILL.md`. No `agency add`, no
`installed.json`, no install step at all.

### The runner — `agency --help`

```
agency — specialists for this repository — skills in .claude/skills/agency-<name>/.
Attended, on your own login, with evidence-backed findings that stay.

  packs       the specialists in this project
  doctor      check the prerequisites BEFORE a run starts
  prs         pull requests to review — open and merged
  run         run a pack — over a pull request, or over the project as it is
  chain       run specialists one after another, each judging what the previous one found
  validate    check findings.json against the contract and the anchors against the code
  graph       ask the code graph — one door for the core and the agent, JSON out
  ingest      the gate: contract, existence, threshold, dedup — BEFORE a finding becomes a finding
  knowledge   what the project knows, as committed markdown — readable without Agency
  metrics     precision, dedup, queue age — by dimension, severity and provider
  export      one-way push of decided findings into a GitHub Project
  cleanup     close a run that is not coming back and remove its worktree
  findings    findings and their decisions
  triage      decide on a finding — an agent calls this too
  note        a note on a finding — free text, not a decision
  status      overview of the project's runs
```

Sixteen commands. There is no `init`, `add`, `hire`, `fire`, `roster`,
`providers`, `projects`, `config`, `brief`, or `backlog`. `agency run <pack>`
prepares the run and prints the ready command; `--wait` launches the agent
and runs the gate itself when it finishes; `--launch` hands this terminal
over to the agent directly; `--json` only prepares, for the extension.

Providers are **two, and they are in code** — a table of `claude` and
`codex` in `providers.py`: binary, flags, authorization shape, streaming
dialect. A third runner is a row in that table, not a registry. Every run
is authorized to write into its own worktree and `.agency/`, plus whatever
its pack's `needs` names; `--bypass` turns that check off entirely, for a
sandbox that will not otherwise let the agent run its own binary.

### A pack — `pack.json`

```json
{
  "name": "po",
  "title": "Product owner · NaLekci",
  "description": "Holds the roadmap against what is actually being built…",
  "requires": ["git", "gh"],
  "target": "workspace",
  "worktree": false,
  "graph": false,
  "prompt": "required",
  "needs": ["agency triage", "agency note", "agency findings",
            "git", "gh issue view",
            "python .claude/skills/agency-po/scripts/backlog.py"],
  "minScore": 75,
  "dimensions": [{ "id": "scope", "title": "Work in flight that no commitment covers" }, "…"]
}
```

Every key is read by the runner: `requires` feeds `doctor`; `target` /
`worktree` / `graph` shape the run preparation; `prompt` (`required` |
`optional` | `none`) validates `--prompt`; `needs` is the agent's allowlist;
`minScore` is the gate's threshold; `dimensions` validates findings and
labels the extension's tree. There is no version — a pack is versioned with
the project's own git history, not separately.

Facts about the project itself — which repository, which board fields,
which staging URL, which law applies — go in `SKILL.md`, under a **Project
facts** heading near the top, where the agent reads them. The runner never
does; that is the whole point of the split.

### Setting up a pack for another project

```
cp -r packs/po <target-project>/.claude/skills/agency-po
```

Then rewrite the **Project facts** section of `SKILL.md` for the new
project, and its `scripts/` if it has any (the PO pack's `backlog.py`, for
instance, has the board's field names and constants written into it — copy
it and change the constants). Run `agency doctor` in the target project;
it reports what is still missing.

### Contracts

The only places two of these three things touch. Nothing else is shared.

| contract | between | shape |
|---|---|---|
| `pack.json` | pack → runner | above |
| the run directory | runner → pack → runner | `context.json`, `evidence/`, `prompt.txt` in; `findings.json` (`finding.v1`), `summary.md`, `handoff.md` in a chain, back out |
| `finding.v1`, `run.v1` | pack → gate; runner → extension | the two schemas, nothing else |
| `agency … --json` | runner → extension | everything the extension reads |

### Memory as committed markdown

```
.agency/knowledge/
  index.md            overview — what the project knows, who decided what
  log.md               chronology: what each run looked at, in its own words
  findings/<id>.md    findings across runs, packs and specialists — generated
  pages/<pack>/       a specialist's own conclusions about this project
```

`agency ingest` regenerates `findings/` from the run records after the gate;
`agency knowledge --rebuild` rebuilds the whole bundle from `.agency/runs/`
— the source of truth stays in the runs, and the bundle can always be thrown
away and rebuilt. A page in `pages/<pack>/` is plain markdown with one
convention: a `Last reviewed: <date>` line at the top, and a rule every
pack's `SKILL.md` repeats — write conclusions, not a log; rewrite what
stopped being true rather than adding to it.

### Three rules the whole thing stands on

**Truth lives in the project, not in the tool.** Runs, findings and
decisions live in `<project>/.agency/` and are committed. They survive a
reinstall of the tool and a fresh clone of the repository, and can be
reviewed in a pull request.

**Only JSON crosses the core↔client boundary**, shaped by `run.v1` and
`finding.v1`. The extension does not know what language the core is
written in.

**A decision is an operation on storage, not a UI command.** A click in VS
Code, `agency triage` in a terminal, and a call from an agent all go through
the same path and write to the same append-only file.

## Structure

| Path | What is inside |
|---|---|
| `packages/core/` | the runner and CLI (Python, `uv`) |
| `packages/extension/` | the VS Code extension (plain JS, no build step) |
| `packs/` | reference copies of `main-panel`'s packs, for the next project to copy |
| `schemas/` | `run.v1`, `finding.v1` — the contract across the boundary |
| `docs/` | decisions and plans, including what changed in them and why |

## Tests

```powershell
pwsh scripts/test.ps1
```

The core is tested over a throwaway git repository that is created and torn
down inside each test, so the suite can run hundreds of times in a row
without touching a real project. The extension has a smoke test against a
stubbed `vscode` module; comment threads and buttons need `F5`.

## Where the method and memory used to live

`agency-po` and `agency-qa` in `main-panel` grew out of two standalone
agents that predate this tool — see the note near the top of
[`nalekci-po-agent`](../nalekci-po-agent) and
[`nalekci-qa-agent`](../nalekci-qa-agent) for where their method and memory
moved to.

## Further reading

[`docs/plans/agency-v1.md`](docs/plans/agency-v1.md) — the redesign this
version is built from, and why an earlier, more configurable version of this
same tool was cut down rather than extended.
[`docs/product-brief.md`](docs/product-brief.md) — what this is and why, for
someone who has never seen the code.
[`docs/ui-surface-decision.md`](docs/ui-surface-decision.md) — why VS Code
and not a desktop app.
