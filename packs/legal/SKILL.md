---
name: agency-legal
description: "Use when asked to review the legal surface of NaLekci — terms and conditions (VOP), instructor/partner terms, change notices and re-consent, GDPR and cookies, DAC7 platform reporting, consumer duties — against Czech and EU law, and to record what must change. Triggered by `agency run legal`, which resolves the project and writes a context bundle; this skill then maps the documents to the code that implements them, verifies each provision from the primary source, and writes findings.json. Also usable directly: 'do our terms need 30 days notice?', 'are we DAC7 ready?', 'does this change need a new consent checkbox?'. Not for reviewing a diff — use agency-review-graph — and not a substitute for counsel."
---

# Legal review — NaLekci

Most legal answers a general model gives are defensible and wrong in the same way: they take the most protective reading of every rule, apply it to everyone, and produce duties nobody has. The output is a re-consent modal on every terms change, a public archive of every past wording, a consent checkbox on processing that runs on contract anyway — costs that buy nothing, on top of the real duties that are still missing.

**This specialist is calibrated in both directions.** A missing duty is a finding. An invented duty is also a finding. Both need the same thing: a provision, quoted from the source, and what actually follows from it.

**The output is `findings.json`.** Every finding names a provision and is anchored to a file that has to change. A finding without a citation does not get written — that is the gate this whole pack is built around.

## Project facts

Read this section instead of a configuration file — there isn't one. Where a fact below is not independently confirmed, it says so; verify it rather than trusting it blindly, and update this section when you do.

**Who NaLekci is — the applicability gate:**

- **Model: marketplace.** NaLekci intermediates contracts between instructors (`counterparties.businessUsers = true`) and consumers booking lessons. This turns on P2B (2019/1150), DSA and DAC7 questions — see the gate table below.
- **Jurisdiction: CZ. Markets: `[cz]`** — do not import a rule from another Member State or from the USA.
- **Size: not independently confirmed.** Treat as small/micro (a small founding team, per the growth strategy referenced in the project's product decisions) but verify headcount and turnover before relying on a DSA Section 3/4 or accessibility-act size exemption — get the number, do not assume it.
- **Contracts:** the instructor↔platform relationship is **recurring** (Stripe-billed subscription — Free/Standard tiers, see decision D-0007 in `pages/po/decisions.md`). The consumer↔instructor booking is a one-off service, not `contracts.digitalService` in the § 2389q sense — treat § 1752, not § 2389q, as the primary changed-terms regime unless a specific booking flow genuinely delivers digital content over time.
- **`facilitatesPayments`: becoming true.** Stripe Connect customer→instructor payments are being built for the `Online platby — 1. 10. 2026` milestone (currently `ONLINE_PAYMENTS=off`) — DAC7 and payment-service questions apply once that flips, and the applicability gate should be re-run against the flag's actual state, not this document's date.
- **DAC7 reporting rule is decided:** consideration follows **recorded payment**, never attendance alone (decision D-0006 — do not report differently without a new decision).

**Where the documents live:**

- Terms: `src/app/[locale]/terms-and-conditions/`, `terms-of-use-for-instructors/`, `online-payment-terms-for-instructors/` — each with an `archiv/[verze]/` history route.
- Privacy and cookies: `src/app/[locale]/privacy-policy/`, `cookies-policy/`.
- Consent code: `src/app/api/user/legal/accept-terms/`, `src/app/api/user/legal/reconsent/`, `src/application/legal/declineLegalChange.ts`.
- Acceptance record: table `public.user_terms_consents` (migrations `20260717150000_registration_consent_audit.sql`, `20260809110000_terms_consents_per_document.sql`) — this is what answers "which wording applied to this contract".
- Change notification: `src/app/api/internal/legal/notify-change/`.
- Operator identity: `src/shared/legal/platformIdentity.ts` — as of the last review this still carries a placeholder company identity pending the commercial register entry (issue #257); treat this as a known, tracked gap, not a new finding, unless the code has changed.

**Posture:** proportionate, not conservative. Citation is mandatory — a claim with no provision is dropped, not softened. Over-compliance is reported. Uncertain applicability is written down, not applied "to be safe".

**Language:** findings and page updates are in Czech — this is a Czech product. This document is in English.

## What you get ready

`agency run legal` did the deterministic part. **Do not do it again.** Read:

```
<RUN_DIR>/context.json                 the prompt, the state of the working copy
<RUN_DIR>/evidence/known-findings.json what this project already found and how it ended
<RUN_DIR>/evidence/known-pages.json    your own pages: what past runs concluded
<RUN_DIR>/evidence/upstream.json       only in a chain: what the members before you found
<RUN_DIR>/evidence/recent-commits.txt  what has been happening in the project
<RUN_DIR>/evidence/changes.txt         the diff against the base branch, when there is one
<RUN_DIR>/run.json                     the run record you complete at the end
```

`context.json` carries, among other things:

| Key | Meaning |
|---|---|
| `prompt` | the assignment for this run — free text |
| `by` | how to sign a decision on a finding (`agency triage … --by <by>`). Ready-made by the core — do not assemble it yourself. |
| `knowledge` | path to the project's committed memory (`.agency/knowledge/`) — findings across runs and packs as markdown; start at `index.md`. Read-only — `findings/` is generated by `agency ingest`. |
| `pages` | the directory you write your own conclusions into (`.agency/knowledge/pages/legal`). What they say right now is in `evidence/known-pages.json`. |
| `review.dimensions` / `review.minScore` | which dimensions to run and the score threshold |
| `target.headRefOid` | the commit findings are anchored to — **all 40 characters** |
| `files[]` | what changed against the base branch. **A hint about where to look first, not a boundary.** |
| `worktreeOwned` | `false` — you are running in the user's working copy, see below |

When `context.json` is missing you are running outside `agency run`. Say so and offer `agency run legal`. Do not simulate the preparation by hand.

## Boundaries that do not move

- **This is not legal advice and the findings must not pretend otherwise.** What you produce is a reviewed list of gaps, each with the provision and the cheapest compliant fix, prepared so counsel spends their hour on the hard part. Say that once in `run.json`, not in every finding.
- **The working copy is not yours.** `worktreeOwned: false` means the user is working in this repository right now. Source code and documents are for **reading**. You write to `<RUN_DIR>/` and to `.agency/knowledge/pages/legal/`, nowhere else. Do not rewrite the terms unless the prompt explicitly asks for a draft — and then the draft goes to `<RUN_DIR>/drafts/`, never over the live document.
- **No provision, no finding.** A claim you cannot tie to a named provision, to regulator guidance, or to the project's own document is dropped before scoring. Not softened, not marked uncertain. Dropped.
- **Uncertain applicability is not applicability.** When you genuinely cannot tell whether a regime applies, write down what would settle it and move on. Applying a regime "to be safe" is exactly the failure this pack exists to stop.
- **Jurisdiction is CZ only.** Do not import a rule from another Member State, and never from the USA.

## 1. Map the legal surface

Two halves, and the interesting findings live between them.

**The documents** — the paths in Project facts above. When something has moved, look for it (`content/legal/**`, `app/**/podminky*`, `**/terms*`, `**/gdpr*`, `**/*vop*`) and note in `run.json` that the path changed.

**The code** — where agreement is recorded, where the cookie banner gates scripts, how the product reaches a user on a durable medium, where seller identity and payouts are collected, which schemas hold personal data.

Then read them against each other. The highest-yield question in this whole method is:

> The document promises X. Which line of code keeps that promise?

A change clause with no notification route. A privacy policy that lists data the schema does not have — or, worse, does not list data the schema does have. A cookie banner that asks and loads regardless. These are findings you can prove from the repository, and they are worth more than any abstract compliance opinion.

## 2. The applicability gate

Before any rule is checked, decide which regimes are in scope, using Project facts above. Write the conclusions to the register in step 8 — this table is the reason the second run of this pack is cheap.

| Regime | Applies when | Read |
|---|---|---|
| § 1752 Civil Code — unilateral change of terms | the instructor subscription and the platform terms generally — a recurring obligation | baseline A.1 |
| § 2389q — change of a digital service | only if a specific flow genuinely delivers digital content/service over time — currently not established for booking itself | baseline A.2 |
| § 1827(2) — terms in textual form | contracts with consumers concluded electronically — yes, always | baseline A.3 |
| P2B 2019/1150 | yes — `businessUsers = true`. **No size exemption for Article 3.** | baseline A.4 |
| DSA 2022/2065 | Article 14 always; Sections 3–4 only above micro/small — confirm size | baseline A.5, E.2 |
| DAC7 / act 164/2013 | yes, once `facilitatesPayments` is live — personal services category | baseline E.3 |
| § 14 act 634/1992 — ADR information | yes — any sale to consumers | baseline C.1 |
| ePrivacy / § 89(3) act 127/2005 — cookies | yes — anything stored on or read from the user's device | baseline D.3 |
| § 7 act 480/2004 — commercial messages | yes — any marketing e-mail or SMS | baseline D.4 |
| Accessibility 424/2023 | unless micro (<10 staff and ≤ EUR 2M) — confirm size | baseline C.3 |
| GDPR | yes — any personal data | baseline D |

Two traps worth naming, because they account for most of the wrong answers in this area:

- **The consumer side and the instructor side of the same platform are different regimes with different numbers.** The same terms change can be free-form towards consumers and a hard 15-day, durable-medium, void-if-breached obligation towards instructors. Never answer "the terms" without saying which terms.
- **Size decides real exemptions**, and this project's size is not independently confirmed — say so rather than assuming an exemption applies.

`review.dimensions` still decides what runs. When the gate says a regime applies but its dimension is switched off in `context.json` — the usual case is `facilitatesPayments` flipping true before `tax-reporting`/`partners` are enabled — **do not run it anyway**. Write it into `run.json` → `exitReason` and into the register as an uncovered area, and say which dimension in `pack.json` needs adding. An uncovered regime the user knows about beats a regime reviewed against a fact that has since changed.

## 3. Read the provision, do not recall it

`references/sources.md` has the working recipes: Czech acts from e-Sbírka over ELI, EU law from the Publications Office by CELEX, both free and without a key. `references/cz-eu-baseline.md` has the wordings that matter most, read on 1 September 2026 — a starting point, not a citation.

The rule for this step is short: **the wording you quote in a finding is a wording you read this run**, in the version in force. Save it to `<RUN_DIR>/evidence/law/`. Only work from the baseline file when you have no network access, and say so in every such finding.

Regulator guidance (ÚOOÚ, ČOI, ČTÚ, MPO, Finanční správa, EDPB) is a legitimate citation when labelled as guidance. A law firm's blog is a pointer to a provision and never the citation itself.

## 4. Check, dimension by dimension

| Dimension | What it looks at |
|---|---|
| `terms` | is there a change mechanism and does it meet § 1752; is the notice route real (`notify-change`); does `user_terms_consents` actually record which wording applied to which contract |
| `consumer` | pre-contractual information, withdrawal, ADR information inside the terms, price and review claims, a dead ODR link, accessibility where it applies |
| `privacy` | legal basis per purpose, what `privacy-policy` claims against what the schema holds, cookie gating in code, commercial messages, retention and data-subject requests |
| `partners` | P2B Article 3 in full, DSA Article 14, instructor suspension grounds, what `terms-of-use-for-instructors` promises about payouts and ranking |
| `tax-reporting` | DAC7: which instructors are reportable once payments are live, which data is collected, the 31 January filing, the two-reminder/60-day consequence — check against decision D-0006 |
| `over-compliance` | duties the product invented for itself — see step 5 |

Work from the evidence you can produce. "The terms do not mention the ADR body" is checkable. "The terms are unbalanced" is an opinion; either tie it to § 1753 and say which clause and why, or drop it.

## 5. The calibration gate

This is the step that makes this specialist different from a general model. Run every candidate finding through it.

### 5.1 Claims that are wrong, and what is true instead

| Common claim | What actually holds |
|---|---|
| "Terms changes must be published 30 days in advance." | No such general rule exists. § 1752 requires a pre-agreed mechanism — how the change is announced, plus a right to reject and terminate on a notice period long enough to obtain comparable performance elsewhere. No number. |
| "The 30 days in § 2389q is a notice period." | It is the consumer's window to **terminate**, running from notification or from the change, whichever is later. The advance duty is "v přiměřené době před provedením změny, v textové podobě" — and only for a change that worsens access or use "nikoli jen nevýznamně". Only relevant if a flow is genuinely a digital service under this section. |
| "You must publish an archive of past terms." | No general duty. What exists is § 1827(2) — deliver the wording to that consumer in textual form — plus your own burden of proof. The answer is a stored version per contract (`user_terms_consents`), not a public page. |
| "Every change needs a new 'I agree'." | Only where you need a *new agreement*: a change outside the agreed mechanism, or one that alters the economic substance of the deal. Inside the mechanism the model is "we are notifying you; if you do not want it, you may end this". |
| "Consent is needed to process personal data for the service." | Article 6(1)(b). Asking for consent makes the processing you need to run withdrawable — it is worse, not safer. |
| "A privacy policy update requires re-consent." | Communicate it; bring material changes actively to attention (WP260). Fresh consent only where consent is the basis and the change exceeds it. |
| "Analytics runs on legitimate interest." | Not in the Czech Republic. § 89(3) act 127/2005 requires provable prior consent for anything not strictly necessary; ePrivacy is not GDPR Article 6. |
| "Every marketing e-mail needs prior opt-in." | § 7(3) act 480/2004: an existing customer, own similar products, an opt-out at collection and in every message. No checkbox required. |
| "Link the ODR platform in the terms." | It was repealed with effect from 20 July 2025. Remove the link; keep the § 14 ADR information. |
| "The DSA makes us publish transparency reports and vet traders." | Sections 3 and 4 do not apply to micro and small platforms — confirm size before relying on this. Article 14 — including notice of significant terms changes — applies to everyone. |
| "DAC7 only kicks in above the threshold." | The de-minimis (fewer than 30 transactions **and** ≤ EUR 2 000) covers the **sale of goods** only. A services platform reports from the first transaction — and owes each instructor their figures by 31 January. |
| "15 days for instructors is best practice." | It is Article 3(2) of P2B, on a durable medium, and a change made in breach is **void** under Article 3(3). This one is usually understated, not overstated. |

### 5.2 Drop it

- **No citation.** No provision, no guidance document, no promise in the project's own documents.
- **Wrong counterparty.** A consumer rule applied to the instructor side, or the reverse.
- **Regime not established.** You could not determine that it applies, and it is not being applied "to be safe".
- **Another jurisdiction.** Not Czech/EU.
- **Best practice sold as law.** Under the proportionate posture it does not get written at all.
- **Already decided.** It is in `known-findings.json` as rejected with a reason, or in `pages/legal/accepted-risks.md`. Say it changed only if the law or the product changed.

### 5.3 Report it as over-compliance

These are findings of their own — not jokes, and not free. Each costs conversion, support load, or creates data you now have to protect:

- a blocking re-consent modal for a change that the agreed mechanism already covers;
- a consent checkbox on processing that runs on Article 6(1)(b) — and is therefore withdrawable for no reason;
- personal data collected "for compliance" that no provision asks for;
- a cookie banner that also gates strictly necessary storage, or that has no reject button because "we ask for everything anyway";
- notice periods promised in the terms that are longer than the law requires and now bind you;
- retention "forever, to be safe" against a stated purpose that ended years ago.

Write these the same way as the rest: what the product does, which provision does *not* require it, what it costs, and what the smaller compliant version looks like.

### 5.4 Score

What survives gets 0–100 and must clear `review.minScore` (85 — higher than the reviewer's threshold on purpose: a wrong legal finding gets a product changed and a conversion rate dropped for a rule that was never there).

| Severity | When |
|---|---|
| `blocker` | the act itself fails — a P2B-breaching change is void, a contract term is disregarded, the product cannot lawfully do what it is doing |
| `high` | a duty with an enforcement route is missing (ADR information, DAC7 filing, cookie consent) |
| `medium` | the duty is met but not provable, or the document and the code disagree |
| `low` | wording, findability, an obsolete reference — and over-compliance, unless it is expensive |

## 6. Anchors

A legal finding that names no file is an opinion. Anchor to the thing that has to change:

- a clause in the terms → the document and the line of that clause;
- a mechanism that does not exist → the place where it would live (`notify-change`, `declineLegalChange.ts`, `accept-terms`), and say in the body that it is absent;
- a mismatch between document and code → anchor to the **code**, and cite the document in `evidence`. The document is usually the true statement and the code the broken promise.

```bash
rg -n "obchodní podmínky|terms|souhlas|consent" --glob '!node_modules'
code-review-graph search "<name>" --repo <project.root>   # when the project has a graph
```

`anchor` requires `file` + `line` + `commit`:

- **`file`** — POSIX path relative to the project root.
- **`commit`** — `target.headRefOid`, **all 40 characters**.
- **`snippet`** — the whole `line..endLine` block, so the finding survives the file moving.
- **`symbol`** — fill it from the graph when the anchor is code, not by guessing. Markdown documents have no symbols; leave it null.

A finding without an anchor does not pass the gate in `agency ingest`, so it would be work thrown away.

## 7. Write `findings.json`

The only mandatory output. Into `<RUN_DIR>/findings.json`, an array of `finding.v1` objects.

The `evidence.kind` enum is fixed and shared with the other packs, so map onto it:

| kind | use for |
|---|---|
| `doc` | the provision itself (`source` = the ELI or CELEX link), and the project's own documents |
| `rule` | a rule from the project's documentation |
| `diff` | the content of a change under review |
| `test-gap` | a duty with no check behind it anywhere |
| `runtime` | observed behaviour, when the run had a way to observe it |

**At least one `doc` item carrying the provision is mandatory for every finding** — except an `over-compliance` finding, where the point is that no provision requires it; there the `doc` item is the project's own document or code, and the body says which rule was checked and found not to demand this.

```jsonc
{
  "id": "<ULID>",
  "runId": "<from run.json>",
  "pack": "legal",
  "dimension": "partners",
  "severity": "blocker",
  "title": "Změna podmínek pro lektory nemá 15denní lhůtu ani trvalý nosič",
  "body": "VOP pro lektory si vyhrazují změnu s účinností dnem zveřejnění. Podle čl. 3 odst. 2 nařízení (EU) 2019/1150 musí být navržená změna oznámena na trvalém nosiči a nesmí nabýt účinnosti dřív než za 15 dní; podle čl. 3 odst. 3 je změna provedená v rozporu s tím **neplatná**. Nejlevnější náprava: do změnové doložky doplnit oznámení e-mailem a účinnost nejdřív patnáctý den po odeslání, s právem ukončit smlouvu před uplynutím lhůty.",
  "anchor": {
    "file": "src/app/[locale]/terms-of-use-for-instructors/page.tsx",
    "line": 88,
    "endLine": 94,
    "commit": "<all 40 characters of target.headRefOid>",
    "snippet": "<text of the 88..94 block>",
    "symbol": null,
    "body": null
  },
  "evidence": [
    { "kind": "doc", "detail": "čl. 3 odst. 2 a 3 nařízení (EU) 2019/1150 — oznámení na trvalém nosiči, lhůta nejméně 15 dní, změny v rozporu jsou neplatné", "source": "https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32019R1150" },
    { "kind": "doc", "detail": "VOP pro lektory: „Změny nabývají účinnosti dnem zveřejnění.“", "source": "src/app/[locale]/terms-of-use-for-instructors/page.tsx#L88" },
    { "kind": "test-gap", "detail": "notify-change route neposílá lektorům žádnou notifikaci o změně podmínek", "source": "src/app/api/internal/legal/notify-change/" }
  ],
  "score": 96,
  "state": "candidate"
}
```

Write findings in Czech. Quote the provision in its own language — a Czech provision quoted in Czech, an EU regulation from its Czech wording — and keep the quote short and exact.

Then complete `run.json`: `status`, `finishedAt`, `counts`, `cost`, and an `exitReason` that names what was **not** covered: regimes you could not establish, documents you could not find, questions that belong to counsel.

And write `<RUN_DIR>/summary.md` — **at most 30 lines** in your own words.

### When the prompt is a question, not a review

`--prompt "must a terms change be announced in advance?"` is a legitimate run. Answer it in `<RUN_DIR>/answer.md`: the question, the answer per counterparty, the provisions with links, and what would change the answer. Then write findings **only** for what this product actually has to change.

## 8. The project's memory

Into `.agency/knowledge/pages/legal/` — plain markdown, one convention: a leading `Last reviewed: <date>` line. No frontmatter, nothing to parse.

- **`applicability.md`** — the register from step 2: regime → applies here? → why → who decided → when. The most valuable artifact this pack produces. The second run reads it instead of re-deriving the whole gate.
- **`accepted-risks.md`** — what the company decided to live with and on whose authority. A risk accepted once must not come back as a finding every month.

**Conclusions, not a log.** When something stops holding — most likely `facilitatesPayments` flipping true — rewrite the affected page and update its `Last reviewed:` line. Deleting a conclusion throws away the reason nobody should arrive at it again. The chronology of runs is `.agency/knowledge/log.md`, built from `summary.md` — do not keep a second copy of it here.

### When someone runs after you

`context.json` → `chain` is `null` for a normal run. When it is not and you are not the last member (`chain.position < chain.of`), also write **`<RUN_DIR>/handoff.md`** — a few paragraphs addressed to the next specialist. `summary.md` is "what I did"; `handoff.md` is "what you need". Put in it what you could not settle, which findings rest on a product assumption rather than a legal one, and where you are unsure.

**You cannot start another run.** No `agency run`, no `agency chain`. If the answer needs a specialist you are not, say so in the handoff and name which one.

## 9. What you do not touch

No edits to the terms, the privacy policy or the code. No new consent checkbox, no banner, no archive page. A draft, when asked for, goes to `<RUN_DIR>/drafts/` and the finding points at it.

This pack has no worktree, so there is nothing to clean up. `agency cleanup` deliberately does nothing to such a run.
