# Dimensions — the part that decides whether the pack is worth running

A pack's `pack.json` can be perfect and the pack still worthless. What separates the two is the dimension list, so this is the one thing worth arguing about with the founder before any file is written.

## The test

**A dimension is one question whose answer can come back false, about something a finding can point a line number at.**

Three parts, and all three have to hold:

1. **One question.** Not a topic, not an area of concern. If you cannot phrase it as a question, it is a chapter heading.
2. **Can come back false.** There has to be a describable state of the code in which the honest answer is "no, this is fine". A dimension nothing can satisfy will always produce findings, which means its findings carry no information.
3. **Points at a line.** `agency ingest` drops a finding whose anchor does not resolve to a real file at the run's commit. A dimension about something with no location — "the team communicates badly", "the architecture is dated" — cannot produce a finding that survives the gate, so it produces nothing at all.

## Rewrites

| Fails | Why | Holds |
|---|---|---|
| `quality` — Code quality | Not a question. Nothing is false about it. | `duplication` — Logic that already exists somewhere else in the codebase |
| `perf` — Performance | A topic. Everything is "about performance" if you squint. | `perf` — Queries on a request path with no index behind them |
| `security` — Security review | Too wide to run; every finding is arguable. | `authz` — An endpoint that checks authentication but never ownership |
| `docs` — Documentation | No failure state. Docs can always be more. | `docs` — A public function whose documented behaviour and code disagree |
| `ux` — User experience | No anchor. Taste, not a claim. | `errors` — A failure the user sees as nothing happening |
| `tests` — Test coverage | A number, not a judgement — and CI already prints it. | `tests` — Branches that only ever run in the happy path |
| `arch` — Architectural fit | Nothing can falsify it. | `layering` — Domain code reaching for the HTTP request object |

The pattern in every row: the version that holds names **a specific wrong state**, and a reader can imagine the code that is not in it.

## How many

**Four to seven.**

Under four, the pack is one check and would be cheaper as a lint rule or a CI step — and a specialist that duplicates CI teaches the founder to ignore it.

Over seven, no single run gets to all of them. The last two or three never fire, the panel shows dimensions that have produced nothing for months, and nobody can tell whether that means the code is clean or the dimension is dead.

## Ids are permanent

The `id` goes into every finding, into `.agency/knowledge/`, and into the per-dimension breakdown in `agency metrics`. Renaming it later does not migrate the history — the old findings keep the old id and the metrics split in two.

So: short, kebab-case, and about the **question**, not the technology. `n-plus-one` dies with the ORM; `perf` outlives it.

## Do not take a question another pack already owns

Before proposing a list, read the `SKILL.md` of every pack already in the project — the dimension titles alone are not enough, because two packs can word the same question differently.

Overlap does not fail loudly. It produces the same finding twice, the dedup ratio quietly absorbs it, and the founder reads it twice and trusts the queue less. Where a subject genuinely straddles two packs, the boundary is written into **both** descriptions in words: *"contract changes are `agency-api`'s; how they are rolled out is here."*

## Severity is not a dimension

`blocker` / `high` / `medium` / `low` is a property of a single finding, decided at the time it is written. A dimension called `critical-issues` collapses the two and leaves the pack unable to report a low-severity finding about the thing that dimension covers.

## The honest check, after the first run

The dimensions agreed in the interview are a guess. The first real run turns them into evidence:

- a dimension that produced **nothing** — is the code clean there, or is the question unanswerable as phrased?
- a dimension that produced findings the founder rejected as `by-design` or a matter of taste — it is too wide; narrow it to the wrong state that is actually wrong here.
- a dimension whose findings all landed — it earns its place, and probably deserves a second question split out of it.

Cutting a dimension after one run is a success, not a retraction. A five-dimension pack whose five all land beats a seven-dimension pack whose last two are read past.
