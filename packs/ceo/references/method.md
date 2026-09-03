# Bets, not backlog — the founder's method

Use this for every "what should we focus on next", every competitor entry, and every judgement about whether something in the roadmap deserves the founder's week.

## Start with the stage

Before any recommendation, state — in `answer.md` for a question, in `summary.md` for a standing run:

- **the outcome that matters now** — for a pre-revenue, one-founder, regional product it is almost always *proof that somebody outside the founder's head wants this*: a partner who lists it, an institution that answers, visitors who come back;
- **the target visitor** — a person, not a segment name: who is in Karlovy Vary or Boží Dar next weekend, in which language, with what question;
- **the scarcest constraint** — name one. Distribution and legitimacy usually beat features; content volume beats model choice (`docs/ai-guide-product-roadmap.md` says exactly this about the guide);
- **what would be displaced** — the founder's week is the unit. Every yes is a no to the thing that was going to happen instead.

A roadmap line is an option, not a commitment. A "P0" in a document from June is a claim to re-check in September, not an order.

## A bet

At most three are live at once. A bet is written down like this, in `strategy.md`:

```
### Bet 1 — <one sentence hypothesis>
If true, within <N> weeks we will see: <one observable, countable thing>.
Killed by: <the observation that ends it>.
Displaces: <what does not get the founder's time while this runs>.
Serves: <the roadmap lines or the question that hang off it>.
Status: proposed | confirmed (decisions.md, <date>) | killed (<date>, why)
```

A bet without a number is a wish. A bet without a kill condition is a belief. Both are allowed for a week, not for a quarter.

## The focus gate

For every candidate — a roadmap line, a feature request, a "we should", a revived idea — give exactly one disposition, the same vocabulary the product owner pack uses:

| Disposition | Use when |
|---|---|
| `BUILD-NOW` | it directly advances a live bet with a measurable result, or it removes something that blocks an outward-facing conversation (a missing imprint, a broken public URL, a placeholder button on the page a partner will open first) |
| `FIX-REMOVE-NOW` | an existing surface undermines credibility, and removing it is cheaper than finishing it |
| `VALIDATE-CHEAPLY` | the problem might matter and the evidence is weak — name the cheapest check: one conversation, one manual pilot with one information centre, one landing page with a counter, one week of a metric that already exists |
| `DEFER-WITH-TRIGGER` | it may matter later — name the trigger that reopens it (a partner asks for it, a number crosses a line, a bet is confirmed), never a bare date |
| `REJECT` | no bet covers it, an incumbent already owns it and has the habit, or it is on `ROADMAP-2026.md` §7 "Co NEdělat" |

Questions to answer before the disposition — unknown answers lower confidence, they do not become optimistic assumptions:

1. **Which bet** does it serve? Name it. None → not `BUILD-NOW`.
2. **What would we count** afterwards, and can we count it today at all?
3. **Who outside the company asked** — a partner, an institution, a visitor — or is it the founder's taste?
4. **What does an incumbent already do here** (Mapy.cz, Kudy z nudy, the DMO's own app)? If they own the habit, the product needs a reason to be the second app, not a copy of the first.
5. **What is the cheaper version** — a manual pilot, a spreadsheet, a conversation, copy on a page?
6. **What does it displace** this week?
7. **How does it end** — how is it turned off or removed if the bet is killed?

Three cuts that are usually the most valuable output of a run: work in flight no bet covers; a "differentiator" an incumbent already has; a horizon-3 item that has quietly become this week's work. One cut that is always wrong: cutting something because it is small — size is sequencing, never a reason to leave a partner-facing gap open.

## A competitor entry

One row in `competitors.md`, and only when it has a consequence:

| Column | What goes there |
|---|---|
| Who | name, URL read this run |
| Model | who pays whom — B2C ads, B2B licence to destinations, public funding, a media house's channel |
| For whom | the visitor or the institution they serve; the region they cover |
| Overlap | which Kvesteros surface it touches — events, POIs, planner, guide, map, cs/en/de |
| Where they win | habit, audience, official status, content depth, offline, price |
| Where we win | a checkable claim — three languages with provenance, AI planning over regional data, a guide with regional depth — and the URL or file that proves the incumbent lacks it |
| Consequence | which bet it strengthens or weakens; which positioning claim to keep or drop |
| Last checked | date |

Rules:

- **Read them this run.** A feature you remember a competitor having is a hypothesis; a feature you saw on their site today, with the URL, is a fact. Save the note to `<RUN_DIR>/evidence/web/`.
- **A DMO is not a competitor in the usual sense.** It distributes the region's events because that is its mandate; Kvesteros ingests those events. The entry says both: where the DMO's channel makes Kvesteros redundant, and where Kvesteros is a further channel for the DMO — that second half is the outreach pitch.
- **Generic AI planners are the argument to check, not the enemy to describe.** The claim "they are shallow on the region" is true until a Gemini answer about Boží Dar is as good as the guide's. Test one query this run when you can, and write the result down.
- **No consequence, no row.**

## Regional relevance — what an institution actually wants

The founder's phrase is "be relevant". For a public institution in the region that means, in this order:

1. **Their events and places reach more visitors** — further, in three languages, with the source named. This is the pitch Kvesteros can make today, because the data already flows.
2. **A number they can report** — visitors reached, events distributed, languages served, a pilot with a dated result. Institutions report upward; give them the sentence.
3. **An innovation story for a program** — a regional AI product built on the region's own data fits an RIS3 narrative; the innovation agency's job is to find and fund exactly that. Fit is checked against the program's current text, not assumed.
4. **No threat to their own channel** — an app that says "use us instead of the DMO" gets no reply. The framing is *in addition to*, with attribution.
5. **Legitimacy** — a legal entity, an imprint, a working URL, a person with a name. Without these the rest is not read.

What they do not want: another platform to maintain, a data-sharing agreement drafted by the applicant, a pitch deck, a promise of what the product will do next year.

## The calibration gate for findings

Drop before scoring:

- **No source.** No URL read this run, no document line, no line of code.
- **Taste.** Colour, tone, "bolder", "cleaner" — unless it is a placeholder on a page a partner opens first, which is `readiness`.
- **Generic advice.** "Talk to users", "find product-market fit", "build a community".
- **Outside the segment.** A competitor whose visitors are not this region's visitors and cannot be within a quarter.
- **Already decided.** `decisions.md`, `ROADMAP-2026.md` §7, or `known-findings.json` as rejected — unless the market changed, and the finding says how.
- **A feature for its own sake.** Something a competitor has that no live bet needs.

Report as a finding:

- a **positioning claim the product does not keep** or an incumbent already meets — anchored to the claim's line;
- **work in flight no bet covers** — anchored to the code, from `files[]`;
- a **dependency with no relationship** — a data source whose terms were never read, a partner the roadmap assumes, a funder whose call closes before the roadmap's horizon;
- a **readiness gap** that would end an institutional conversation on the first reply;
- a **claim with no number** and nothing that would produce one — the roadmap's "killer combination", "differentiator", "retention engine" each need the sentence "and we would know because…".
