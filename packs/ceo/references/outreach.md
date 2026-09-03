# Outreach — approaching a Czech public institution

For KIC KK (the innovation agency, formerly KARP), the regional authority, a destination agency, a city information centre, a UNESCO site organisation. The same playbook, in the same order: **readiness → who → ask → draft**. The agent drafts; the founder sends. Nothing here is ever submitted by the agent.

## 1. Readiness — before the first e-mail is drafted

An institution reads the sender's web before it reads the e-mail. Check each item against the repository and the live product this run; a failed item is a `readiness` finding and the draft waits.

| Item | Where to check | Why |
|---|---|---|
| **Legal entity** — name, IČO, registered address; a physical person with a trade licence (OSVČ) is fine, "a project" is not | not in the repository — ask the founder in `answer.md` | the first question is "who are you"; a public body cannot contract with, fund, or list a product that has no subject behind it |
| **A public URL that works**, in Czech, showing the region's events today | `src/client` on Vercel; `deploy/Caddyfile` for admin/API; confirm the hostname resolves | the e-mail's one link; a login wall, a placeholder or a stale page ends the conversation |
| **An imprint / "O nás"** — who runs it, contact, one sentence on where the data comes from and how sources are credited | `src/client/src/components/layout/footer.tsx`, the `info.json` dictionaries | provenance is the question every DMO and every information centre asks first: their events are the data |
| **Provenance posture** — for each adapter: the source, whether its terms allow re-publication, how it is attributed | `src/event-ingestor/event_ingestor/adapters/`, `docs/kvesteros-platform-spec.md` §12–13 | an institution whose calendar is being scraped without a word is a lost partner, not a future one |
| **A one-pager** — one A4, Czech, PDF: what it is, for whom, what runs today with numbers, what we ask, who we are | draft the outline into `<RUN_DIR>/drafts/one-pager-outline.md` | the only attachment; a deck is not read |
| **A number** — events live, places, languages, and one usage figure if any exists | the landing page's stats bar; the latest state document | "an AI planner" is a category; "1 900 akcí v kraji, 200 míst, cs/en/de" is a product |
| **A demo path** — one link that answers a question the institution cares about (a weekend in their town, in German) | the live product | the reader tries it; make the first attempt succeed |
| **GDPR one-liner** | `src/client` privacy page, if any | asked by every public body; one sentence, no policy |

## 2. Who — by role, found this run

Find the current people on the institution's own site and write them into `stakeholders.md` with the URL and the date. Roles that answer, in the usual order:

| Institution | The role to write to | What they own |
|---|---|---|
| KIC KK (the region's innovation agency, formerly KARP) | the guarantor of the voucher program (named on its page); the RIS3 / innovation lead | admission to programs, introductions inside the regional ecosystem, the innovation narrative |
| Karlovarský kraj | the tourism (cestovní ruch) department; the culture department for heritage themes | regional grants, the region's own promotion, the relationship with the DMOs |
| Živý kraj / Destinační agentura Krušné hory | the director or the marketing / digital lead | the region's channels, partner programs, data-sharing, co-promotion |
| A city information centre | its head | listing a third-party app, local pilots, the town's events |
| A UNESCO site organisation (Montanregion, the spa towns) | the coordinator / secretariat | thematic content, the German-side counterpart |

A general mailbox (`info@`) is the fallback, not the target. A LinkedIn profile is a pointer, not a contact route.

## 3. The ask — one, concrete, small

The first e-mail asks for **one** thing, and it costs the reader under an hour:

- a 30-minute call or a visit to their office;
- entry into a named program or call (with its number and deadline, read this run);
- listing the product on their page of apps / partners;
- a pilot: their events in Kvesteros, credited, for one season, with a number reported back at the end;
- an introduction to one named institution.

Not in the first e-mail: a data-sharing agreement, a partnership, funding without a program, "feedback on our roadmap", a feature promise, a price.

## 4. The e-mail — the shape

Czech, formal (vykání), 6–10 lines, no attachment beyond the one-pager, no bullet lists. Into `<RUN_DIR>/drafts/outreach-<institution>.md`, with the subject line on the first line.

```
Předmět: <the product> — <the one ask>, <the institution's program or event if there is one>

Dobrý den, <role or name>,

<who writes — one line: name, entity, what Kvesteros is in nine words>.
<what runs today — one line with a number: events, places, languages, the region>.
<why them — one line that shows the sender read their site: their program, their events, their town>.
<the ask — one line, with a concrete time frame or deadline>.
<the link — one, that answers a question they care about>.

<sign-off, name, entity, phone, URL>
```

Rules the draft follows:

- the reader knows in the first two lines who is writing and why it concerns them;
- one number, one link, one ask;
- their own words for their own things — the program's name as they spell it, the event as they call it;
- nothing about the future: what the product does today, not what it will do;
- nothing the founder would have to take back — no "partnership", no "we integrate your data" unless the provenance posture is settled;
- the founder's voice, not the agent's — no "we are an AI", no exclamation marks, no superlatives.

Alongside the e-mail, a **call agenda** (`drafts/call-agenda-<institution>.md`) when the ask is a meeting: three questions to ask them, three facts to bring, the one thing to leave with.

## 5. Programs and calls — what to check, every run

Read the program's current page this run; write the row into `opportunities.md` with the deadline, the eligibility note and the URL. Typical shapes in this region — verify each, the names and cycles change:

- the innovation agency's voucher schemes (innovation vouchers, creative vouchers) — usually small, fast, for a purchase from a research or creative partner; check whether a one-person company qualifies and what the money can buy;
- the regional innovation strategy's accelerator or ecosystem programs — mentoring, visibility, introductions rather than money;
- the regional authority's tourism and culture grant programs — annual cycles, often for events and promotion, sometimes for digital tools;
- the national tourism agency's partner and listing programs;
- cross-border programs on the Krušné hory axis (Czech–Saxon, Czech–Bavarian cooperation) — the cs/de story fits; the paperwork is a project, not an e-mail;
- the national technology agency's calls — only when a research partner is in play;
- regional and municipal events where the institutions are in one room — a conference of the DMO, a tourism forum — the cheapest way to meet five roles in a day.

A program the founder does not qualify for gets one line in the "closed / not eligible" section, with why. A program with a deadline within 60 days goes to the top of `answer.md`.

## 6. After the e-mail — cadence and record

- one follow-up after 7–10 working days, two lines, replying to the original; then stop — a public body that has not answered twice is answering;
- every contact is a row in `stakeholders.md`: institution, role, channel, date, what was asked, status (`drafted` / `sent` / `replied` / `meeting` / `declined` / `no answer`), next step with a date — the founder updates `sent` and what came back, or tells the agent in the next prompt;
- what an institution said is written down in their words, with the date — it is the evidence the next draft is built on.
