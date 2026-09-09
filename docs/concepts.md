# The concepts

What Agency is made of, after the outputs shift of 8 September 2026. Six
diagrams and the six ideas behind them: where things live, what an output is,
what happens to one, what the gate refuses, where an output sits, and how a
verdict on it becomes a number.

This is the *what*. The *why* is in [`plans/outputs.md`](plans/outputs.md) —
eleven steps with a retrospective after each — and its acceptance,
[`prejimka-outputs.md`](prejimka-outputs.md), which also records the five
places the plan turned out to be wrong. [`../README.md`](../README.md) is the
command surface and the exact shape on disk.

Every diagram here is a file in [`diagrams/`](diagrams/). The `.svg` is the
source and carries its own light and dark palette; `build.py` wraps each one in
a page you can open, and inlines it into the site.

| | Diagram | Open it |
|---|---|---|
| 1 | Where the three parts live | [`shape.html`](diagrams/shape.html) |
| 2 | What an output is made of | [`an-output.html`](diagrams/an-output.html) |
| 3 | From a run to a board and back | [`run-to-board.html`](diagrams/run-to-board.html) |
| 4 | The gate, and the reason it refuses | [`the-gate.html`](diagrams/the-gate.html) |
| 5 | Where an output sits | [`where-it-sits.html`](diagrams/where-it-sits.html) |
| 6 | Two questions about one bet | [`two-questions.html`](diagrams/two-questions.html) |

---

## 1. A specialist is a skill in the project

![Where the three parts of Agency live](diagrams/shape.svg)

There are three programs and one place. The **runner** (`agency`) prepares a
run, records it, gates what comes back and remembers it. The **viewer** (the VS
Code extension) shows runs and outputs next to the line of code, read-only. A
**paired phone** does the same from somewhere else while `agency serve` is up.
Both clients speak to the runner only through `agency … --json`, shaped by
`run.v1` and `finding.v1`. That is the whole boundary.

The place is the target project, and it holds everything that is specific to
it. A **pack** is a skill directory — `pack.json` next to `SKILL.md` — sitting
where Claude Code already looks for skills. It is committed with the code and
versioned with it. There is no `~/.agency/`, no project configuration file, and
no registry of who is hired: what a specialist knows about this project is
written into its `SKILL.md` as fact, the same way the code is project-specific.

Beside it, `.agency/knowledge/` is committed markdown anyone can read without
Agency, and `.agency/runs/<ULID>/` holds the run records, which are gitignored
because they are large, per-run and rebuildable.

## 2. An output, and the type that governs it

![What an output is made of](diagrams/an-output.svg)

Until this shift the core knew exactly one shape: a finding with an anchor. So
everything else either deformed itself to fit — a strategic claim anchored to
`footer.tsx` — or went around the core entirely.

The way out was **not** to teach the core what a bet is. It was to let the pack
say how its outputs are to be handled *mechanically*, and let the core know
nothing else. `BUILD-NOW`, `distribution`, `stakeholder`: none of that reaches
the core, and the day it does, every future specialist has to pretend to be a
code reviewer again.

So a pack declares its types in `pack.json`:

```json
"outputs": {
  "bet": {
    "cardinality": "many",
    "limit": 3,
    "anchor": "none",
    "dedup": true,
    "evidence": { "required": ["web_snapshot", "document"], "min": 1 },
    "actions": "none",
    "memory": "proposes",
    "feedback": {
      "selection": { "metric": "selection_rate",
                     "kinds": { "selected": "positive", "rejected": "negative" } },
      "outcome":   { "metric": "success_rate", "requires": "selection.selected",
                     "kinds": { "successful": "positive", "failed": "negative",
                                "abandoned": "neutral" } }
    }
  }
}
```

| Key | What the core does with it |
|---|---|
| `cardinality` | `one` or `many`; `one` is a ceiling of one |
| `limit` | how many of this type one run may produce |
| `anchor` | `required` — it must point at a file and a line — or `none` |
| `dedup` | whether two of these in the same place are the same one |
| `evidence` | which kinds will do (`required`, any one of), and how many (`min`) |
| `actions` | `sink` — it may act in the world — or `none` |
| `memory` | `proposes` — it may become a page in the knowledge — or `never` |
| `feedback` | the questions that can be asked about it, and their answers |

A pack that declares nothing keeps the policy `finding` has always had:
anchored, deduplicated, dispatched through a sink, triaged into `precision`.
That is why the whole shift landed without touching a pack that had not been
rewritten.

**Three fields on the output itself are new.** `type` says which policy
applies. `subject` (`{ kind, ref }`) says what the output is *about* when it is
not about a line of code. `actions[]` records what it did in the world, one
entry per attempt, failures included — the pack's own verb, whether it worked,
what it produced, and when.

**Evidence carries a locator.** An evidence item used to be `{kind, detail,
source}` — a claim about proof rather than a pointer to it. It now carries a
`locator`, which is checked **offline** against what the run actually stored: a
file and a line at a commit, a command, a URL that was fetched, an artifact in
the run directory.

**The anchor is now one kind of evidence.** Pointing at source is
`evidence.kind = code` with a locator carrying `file`, `line`, `commit` and
`symbol`. The top-level `anchor` field is superseded but still read: three
repositories have it in committed history. See §7.

## 3. What happens to one output

![From a run to a board and back](diagrams/run-to-board.svg)

`agency run <pack>` prepares the run — `context.json`, an `evidence/`
directory, the prompt — and the agent works in a terminal or, unattended, in
print mode. What it writes is `findings.json`.

Then `agency ingest` runs the gate (§4), gives every survivor a fingerprint,
marks the duplicates (§5) and dispatches what is left through the pack's own
`sink`. A dispatch that lands writes an `actions[]` entry carrying the pack's
own verb; a dispatch that fails writes one carrying the error, and the output
stays `candidate` for the next attempt. The pack with no sink has its outputs
rest as `candidate` in the committed knowledge, which is the honest shape for a
project with no board.

`agency outputs` says what happened to each one. The command was called
`findings` and still answers to it, permanently — a reviewer's outputs *are*
findings, and eleven steps of generalising the core is no reason to make
anyone relearn a command they type every day.

```
agency outputs                 # everything from the last run
agency outputs --type bet      # only the bets
agency outputs --all           # across every run
```

An output's `state` is the core's own bookkeeping, and there are five values:
`candidate`, `held` (a chain member found it and the next one has not judged
it yet), `sent`, `rejected`, `duplicate`. What the gate refused never becomes
an output at all: it goes to `gated.json` with its reason, and to the trail as
`gated-out`.

## 4. The gate

![The gate, and the reason it refuses](diagrams/the-gate.svg)

Every check asks the same question — **can this be true** — and none of them
asks how good it is. Nine named reasons, in a fixed order:

| Reason | It means |
|---|---|
| `schema` | does not match `finding.v1` |
| `unknown-type` | an output of a type this pack does not declare |
| `missing-anchor` | a type whose claims must point at source, pointing at nothing |
| `phantom-file` | the file does not exist at the analysed commit |
| `phantom-line` | the line is past the end of the file as of the analysis |
| `weak-evidence` | not the kind of proof this dimension or type stands or falls on |
| `unproven-source` | evidence cites a command that never ran in this run |
| `unverified-evidence` | the evidence locator points at something this run did not produce |
| `over-cardinality` | more of this type in one run than the ceiling allows |

Two things about that order are deliberate. The provenance check comes **before**
the locator check, because a fabricated command is the older and better
understood lie, and reading it as the newer one would make the two populations
in `gatedBy` impossible to tell apart. And the ceiling is applied **last**, over
everything that survived, because a ceiling is not a statement about one output
— it is about how many came with it. Judging the eleventh against a full quota
before asking whether it is honest would hide a broken pack behind its own
volume.

**Score no longer refuses anything.** Until 8 September 2026 a score below the
pack's `minScore` was dropped, which let a number the model gave itself decide
what a person got to see. Score now decides an *order*, and only where more
came than the ceiling allows: which ones, never whether. A pack that scores
everything 90 loses nothing by it — the ceiling still holds, and the tie falls
back to the order the pack wrote them in.

A pack that names no ceiling gets `RUNAWAY = 25`, which is a backstop and not a
working limit. It was measured, not guessed: `baseline.md` records 51 findings
across the whole period, 36 of them from the busiest pack, and the last
structured run produced three new ones with dedup suppressing 80% of the rest.

**A missing hook makes the gate looser, silently.** The provenance checks read
`tool-calls.jsonl`, and when nothing recorded the run there is no file, so both
checks are skipped rather than failed — never drop a finding because a hook did
not run. It is the first thing to verify on a live run; see
[`overeni-v-provozu.md`](overeni-v-provozu.md).

## 5. Where an output sits

![Where an output sits, and how dedup finds out](diagrams/where-it-sits.svg)

Dedup needs a *place*, because the rule underneath it is that two claims in two
different places are two claims. Three questions are asked in order, and the
first that answers wins: the `subject` the pack declared, then a `symbol` from
the anchor, then a `file`.

An explicit subject wins over the anchor because it is the pack saying it. The
anchor-derived shapes stay `sym:` and `file:` rather than being renamed in one
generalising sweep, so every fingerprint already in committed history keeps its
value.

An output that answers none of the three has **no place**, and that is not the
same as a shared placeholder. This is the most expensive thing the shift found,
and a run found it rather than an argument: `dedup.symbol_key` used to fall back
to `file:?`, so every anchorless output shared one place, and four differently
worded bets collapsed into one. The guard turned into its own opposite. Which is
also why `subject` stopped being an improvement and became a necessity.

The same reading applies to a pack that migrates from the `anchor` field to a
`code` evidence item: `anchor.of()` reads both shapes, so the key is unchanged —
**provided the locator carries the symbol**. Lose the symbol and the key
collapses from `sym:getUser` to `file:src/auth.ts`, and the pack re-reports its
whole backlog. The only visible sign is `counts.duplicates` falling from around
80% to zero on the second run.

## 6. What came of it

![Two questions about one bet, counted apart](diagrams/two-questions.svg)

A type declares **lifecycles** — questions that can be asked about one of its
outputs, each with its own named answers, each answer with a polarity, and at
most one metric per question.

A bet has two questions, and they must not be counted together. `(selected +
successful) / everything` is neither a selection rate nor a success rate; it is
a number that looks like a metric. `requires` keeps the second question from
being asked about an output that failed the first: a rejected bet is never asked
how it turned out, and without that it would sit in `success_rate`'s denominator
for ever, undecided, dragging the ratio down with every bet nobody took.

```
agency feedback <id> selected          # the founder took it
agency feedback <id> successful        # and it worked
agency triage accept|reject <id>       # the same file, for the types that have a triage lifecycle
```

Each rate is `positive / (positive + negative)`. A neutral answer is recorded
and left out of the ratio. A question nobody answered is `undecided`, counted
apart, and never a failure.

Two distinctions worth holding on to:

* **`decisions()` is not `verdicts()`.** "Did anybody decide about this at all"
  is a different question from "how did question X come out", and the metrics
  need both.
* **The core is never a source of feedback.** `duplicate` is a state in the
  pipeline, not a verdict. If the core wrote its own bookkeeping as feedback,
  precision would be counting decisions nobody made. A test holds that shut.

## 7. Superseded, and still read

Nothing here is dead code, and none of it should be written into anything new.

| Thing | Status |
|---|---|
| `anchor` on an output | **still correct**, just not written into anything new — use a `code` evidence item with a locator |
| `sinks` in `finding.v1` | replaced by `actions[]`, which records attempts rather than results |
| `minScore` in `pack.json` | does nothing; `agency doctor` says so. Not an error — a manifest has no schema |
| `findings` as a command | a permanent alias for `agency outputs` |
| `finding.v1`, `findings.json` | unchanged file and schema names; the *word* is now output |

Two things are open on purpose. `stop_errors()` does not check artefact
locators, so an unsaved `web_snapshot` is something the agent hears about from
the gate rather than from the hook. And the CEO pack's registries stayed memory
pages instead of becoming an output type, because that would duplicate a
mechanism `knowledge/pages/` already provides.

## Where to read more

| For | Read |
|---|---|
| the command surface, and the shape on disk | [`../README.md`](../README.md) |
| why each step is the way it is | [`plans/outputs.md`](plans/outputs.md) |
| what was accepted, and where the plan was wrong | [`prejimka-outputs.md`](prejimka-outputs.md) |
| what only a live run can tell you | [`overeni-v-provozu.md`](overeni-v-provozu.md) |
| what the numbers were before any of this | [`baseline.md`](baseline.md) |
| the diagrams, and how to change one | [`diagrams/README.md`](diagrams/README.md) |
