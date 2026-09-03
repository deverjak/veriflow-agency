---
name: agency-qa
description: "Use when asked to test the running NaLekci staging application against a written brief and record what is broken durably. Triggered by `agency run qa --prompt \"…\"`, which resolves the project and writes a context bundle; this skill then explores staging as the configured personas — through Playwright — reproduces every problem in a failing spec, anchors it to the responsible code and writes findings.json. Also usable directly: 'QA session on the booking flow', 'test the checkout as a logged-out user'. Not for reviewing a diff or a pull request — use the agency-review-graph pack for that."
---

# QA session against a brief — NaLekci

Exploration of the **running staging application** against a brief a human wrote. The method is always the same; what to try is the prompt — the only difference between two sessions on this project.

**The output is not a report. The output is `findings.json`.** Every finding is reproduced and anchored to the line of code that causes it. An unreproduced observation is not a finding; a finding with no anchor is one nobody finds again in a month.

**Findings go to the board through the core.** Write findings to `RUN_DIR/findings.json`. Do not create board items, PR comments or issues for a finding yourself — `agency ingest` sends what passes the gate through `backlog.py draft --finding`. In a chain, judge the upstream findings with `agency triage accept <id>` (it goes to the board) or `agency triage reject <id> --reason <r>` (it is remembered, never reported again). There is no `defer`: what you do not reject goes to the board when the chain ends.

## Project facts

Read this section instead of a configuration file — there isn't one.

- **Target: staging only, always.** `https://nalekci-staging.chytre.digital`. Never production, never a second host. Basic-auth credentials come from `main-panel/.env.local` (`STAGING_BASIC_AUTH_USER` / `STAGING_BASIC_AUTH_PASSWORD`), read from the environment, never printed or written to a finding.
- **Personas and their credentials** live in `.agency/qa-accounts.local.json` (gitignored — it holds staging-only test identities, never real ones):

  | id | role |
  |---|---|
  | `guest` | anonymous visitor, no login |
  | `customer-a`, `customer-b` | booking customers |
  | `trainer-a`, `trainer-b` | instructors |

  **If the file does not exist**, the session explores only as `guest` and says so in `run.json → exitReason` rather than inventing credentials.
- **One Playwright browser process per persona, always sequential, never concurrent.** A shared browser context crossing personas is how a past session mixed up two instructors' actions — treat this as a hard rule, not a style preference. Close the browser, clear cookies/localStorage/sessionStorage between personas.
- **Viewports:** desktop 1440×960 and mobile 390×844. **Locale:** Czech first, then an English pass when the session budget allows.
- **This project's own Playwright setup (`spec/`, playwright-bdd) is the executable specification tied to `npm run spec` and feature files — it is NOT a fixture library for ad-hoc QA.** Read `spec/support/*.ts` once at the start of a session for how login and test data are set up in this project's own dialect (so a reproduction spec does not invent a second way to log in), but do not run the suite and do not write into `spec/`. Scaffold your own throwaway Playwright config inside the run directory (`scaffold: run-dir`, below) for every session.
- **Safety, without exception:** never a real payment (Stripe test mode is what staging has), never an email/SMS/notification to a real address, never `npm run db:reset` (breaks grants outside `globalSetup`, see `CLAUDE.md`), never change or delete data outside the test accounts above.
- **What CI does:** `npm run verify` — used to drop findings CI would already catch, never run yourself.
- **Language:** findings and page updates are in Czech — this is a Czech product. This document is in English.
- **Session budget:** 40 minutes, up to 12 findings. Zero findings is a valid result.

## What you get ready

`agency run qa` did the deterministic part. **Do not do it again.** Read:

```
<RUN_DIR>/context.json                 the prompt, the state of the working copy
<RUN_DIR>/evidence/known-findings.json what this project already found and how it ended
<RUN_DIR>/evidence/known-specs.json    reproduction tests from earlier runs — runnable again
<RUN_DIR>/evidence/known-pages.json    your own pages: what past sessions concluded
<RUN_DIR>/evidence/recent-commits.txt  what has been happening in the project lately
<RUN_DIR>/evidence/changes.txt         the diff against the base branch, when there is one
<RUN_DIR>/run.json                     the run record you complete at the end
```

`context.json` carries, among other things:

| Key | Meaning |
|---|---|
| `prompt` | the assignment for this run — free text |
| `by` | how to sign a decision on a finding (`agency triage … --by <by>`). Ready-made by the core — do not assemble it yourself. |
| `knowledge` | path to the project's committed memory (`.agency/knowledge/`) — findings across runs and packs as markdown, start at `index.md`. Read-only — `findings/` is generated by `agency ingest`. |
| `pages` | the directory you write your own conclusions into (`.agency/knowledge/pages/qa`). What they say right now is in `evidence/known-pages.json`. |
| `review.dimensions` / `review.minScore` | which dimensions to run and the score threshold |
| `target.headRefOid` | the commit findings are anchored to — **all 40 characters** |
| `files[]` | what changed against the base branch. **A hint about where to look first, not a boundary.** |
| `worktreeOwned` | `false` — you are running in the user's working copy, see below |

When `context.json` is missing you are running outside `agency run`. Say so and offer `agency run qa --prompt "…"`. Do not simulate the preparation by hand.

## Boundaries that do not move

- **The working copy is not yours.** `worktreeOwned: false` means you are in the repository the user is working in right now. Source code is for **reading**. You write to `<RUN_DIR>/` and to `.agency/knowledge/pages/qa/`, nowhere else. Do not commit, do not switch branches, do not touch work in progress.
- **Staging must answer before anything else.** If it does not, the run **ends** with `status: "failed"` and `exitReason` naming what curl returned. Do not guess behavior from the code — that is the reviewer's job, not QA's.
- **`safety` above is literal.** No deleting, no cancelling, no paying. When a flow cannot be completed without a destructive step, record it as uncovered, not as a finding.

## 1. Read the prompt and the project's memory

1. `prompt`. If it conflicts with what a past `coverage.md` page says was already thoroughly checked, the prompt wins — mention the conflict in `run.json → exitReason`.
2. `evidence/known-pages.json` — your own pages, as the last session left them: what is covered and what keeps coming back. Empty means the project has no memory yet; you start it in step 8.
3. `evidence/known-findings.json` — **before you start.** Do not report a finding this project already rejected with `by-design`. Dedup after ingest is a safety net, not a substitute for this.
4. `files[]` and `evidence/recent-commits.txt` — what has moved in the code lately. That is where most things break.

Build a **session plan** from this into `<RUN_DIR>/plan.md`: a list of concrete passes (persona → goal → expected result), not prose. Keep it short and let it show what was left untried.

## 2. Verify staging answers

```bash
curl -sS -o /dev/null -w "%{http_code}" -u "$STAGING_BASIC_AUTH_USER:$STAGING_BASIC_AUTH_PASSWORD" https://nalekci-staging.chytre.digital
```

An unreachable staging is the end of the run, `status: "failed"`, with what curl returned in `exitReason`.

## 3. Browser: your own scaffold, this project's dialect

Write `<RUN_DIR>/playwright.config.ts` and add nothing anywhere else:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  outputDir: './evidence/playwright',
  reporter: [['list'], ['json', { outputFile: './evidence/playwright-report.json' }]],
  use: {
    baseURL: 'https://nalekci-staging.chytre.digital',
    httpCredentials: { username: process.env.STAGING_BASIC_AUTH_USER!, password: process.env.STAGING_BASIC_AUTH_PASSWORD! },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    // set once your own auth setup below has written it
    storageState: undefined,
  },
});
```

Run with:

```bash
npx playwright test --config <RUN_DIR>/playwright.config.ts --project=chromium
```

If `@playwright/test` is not already available, `npx --yes playwright@latest test …` fetches it into the npx cache — nothing is added to the repository. Browsers install the same way (`npx playwright install chromium`), into the user cache, also outside the project.

**Do not invent your own login flow if the project already has a working one.** Read `spec/support/*.ts` for how this project's own executable specification logs each role in, and follow the same pattern in `<RUN_DIR>/specs/auth.setup.ts`, saving state to a file under `<RUN_DIR>/` — never commit it, never write it into `.agency/qa-storage-state.local.json` in the repository.

## 4. Exploration: a persona, not clicking around

For each persona from Project facts, walk the goals from the plan. With no persona named in the prompt, default to `guest` plus one signed-in persona relevant to the prompt.

| Dimension | What it looks at |
|---|---|
| `happy-path` | does the main flow do what it promises, all the way through |
| `edge-cases` | empty state, boundary, long text, diacritics, double-click, browser back |
| `errors` | does it fail legibly? can you recover? or does it just silently do nothing |
| `data` | does the result survive a reload, a second tab, logout |
| `access` | what a role **must not** be able to do — someone else's record via URL, an action hidden only in the UI |
| `regression` | what is in `known-regressions.md`; specs from `known-specs.json` can be run again directly |

Collect **evidence, not impressions**: exact steps, URL, console errors, response statuses, a screenshot into `<RUN_DIR>/evidence/`. Nothing without steps is a reproduction.

Regression has an advantage over the other dimensions: an older finding with a saved spec is verified by running it, not by a fresh exploration. When such a spec **passes**, that is a status update ("looks fixed"), not a finding — write it as a note through `agency note <id> "…"`, not into `findings.json`.

## 5. The deterministic gate: reproduction is a spec, not a paragraph

Before an observation becomes a finding, **write a spec for it and let it fail on exactly what is broken.**

```
<RUN_DIR>/specs/<finding-slug>.spec.ts
```

The rules this stands on:

- **One spec = one finding.** The file name is the title's slug, so it can be found again a year later.
- **A clean context.** Playwright gives every test a new browser context on its own — do not rely on state from a previous test and do not write order-dependent specs. This is exactly the isolation manual clicking does not have.
- **It has to fail for the right reason.** An assertion on behavior (`await expect(page.getByText('Rezervace potvrzena')).toBeVisible()`), not a timeout on a selector. A spec that fails on a missing button claims something other than what you mean to claim.
- **Run it twice.** A test that passes once and fails once is not a finding, it is a flaky test — or you found a race condition, in which case say so and back it up.
- **No destruction.** The safety rules apply to specs too. Clean up any data a spec creates, in `afterEach` where possible.

Drop everything that:

- **could not be reproduced** — belongs in `plan.md` as an uncertain observation, not in findings;
- **is a property of the environment**, not the application: a dead seed, an integration switched off on staging, an expired test account;
- **is caught by CI** — `npm run verify` already does typecheck/lint/tests, do not re-derive it;
- **the project already knows** — in `known-findings.json` or `known-regressions.md`;
- **is a matter of taste** with no basis in the prompt, the documentation, or behavior the application itself promises.

Score what survives 0–100 and keep `>= review.minScore`. **Zero findings is a valid result**, not a failed run.

## 6. Anchor into the code

A finding from the UI has to point at code, or nobody can turn it into a fix. From symptom to source:

```bash
rg -n "<string from the UI>" --glob '!node_modules'
agency graph locate "<name>" --repo <project.root>
agency graph neighbors <name> --direction in --repo <project.root>
```

A failed spec's trace helps too — it carries the last request, its status and a stack, and from there it is one step to the handler.

`anchor` needs:

- **`file` + `line`** — POSIX path relative to the project root, the line that causes the behavior. Not the test, not configuration, not merely where it shows up.
- **`commit`** — `target.headRefOid`, **all 40 characters**.
- **`snippet`** — the whole `line..endLine` block, not one line.
- **`symbol`** — the one layer of the anchor that survives a refactor. Fill it from the graph, not by guessing.

When you genuinely cannot find the anchor — the fault is in data or in an external service — anchor to where the application consumes that result, and say so in `body`. A finding with no anchor does not pass the gate in `agency ingest`, so it would be wasted work.

## 7. Write `findings.json`

The only mandatory output. Into `<RUN_DIR>/findings.json`, an array of `finding.v1` objects:

```jsonc
{
  "id": "<ULID>",
  "runId": "<from run.json>",
  "pack": "qa",
  "dimension": "happy-path",
  "severity": "high",
  "title": "One-sentence claim of what is broken",
  "body": "Markdown: what happened, what should have happened, and STEPS: 1. … 2. … 3. → empty page instead of a confirmation.",
  "anchor": {
    "file": "src/application/booking/createBooking.ts",
    "line": 142,
    "endLine": 158,
    "commit": "<all 40 characters of target.headRefOid>",
    "snippet": "<text of the 142..158 block>",
    "symbol": { "name": "createBooking", "range": [128, 171] },
    "body": "<the symbol's body, capped at 8 kB>"
  },
  "evidence": [
    { "kind": "runtime", "detail": "spec fails 2/2 runs: expected confirmation, got 500", "source": "specs/rezervace-prazdna-stranka.spec.ts" },
    { "kind": "runtime", "detail": "trace: POST /api/booking → 500, TypeError in console", "source": "evidence/playwright/…/trace.zip" }
  ],
  "score": 88,
  "state": "candidate"
}
```

- `kind: "runtime"` is QA's primary evidence — observed behavior. At least one item is mandatory, or the finding does not pass the gate.
- **`source` for a reproduction is the spec's path**, relative to `RUN_DIR`. That is what makes the reproduction runnable: `npx playwright test <that file>` answers "is it fixed?" a year from now better than any paragraph.
- Trace, screenshot and video paths come from `evidence/playwright-report.json`.
- Write findings in Czech.

Complete `run.json`: `status`, `finishedAt`, `counts` and `cost` (provider, model, number of dimensions, duration).

And write `<RUN_DIR>/summary.md` — **at most 30 lines** in your own words.

## 8. The project's memory

Into `.agency/knowledge/pages/qa/` — plain markdown, one convention: a leading `Last reviewed: <date>` line. No frontmatter, nothing to parse.

- **`coverage.md`** — what is explored and what is not. **State, not a diary**: the session chronology is `.agency/knowledge/log.md`, built from `summary.md` — writing it a second time here means one of the two copies will eventually lie. "Card payment passes, 3D Secure untested" belongs here, not "on 1 September I tried payments".
- **`known-regressions.md`** — add only what came back **a second time**. A list everything gets written into is a list nobody reads.

**Conclusions, not a log.** When a conclusion stops holding, rewrite it — or mark it and leave the reason next to it, updating the `Last reviewed:` line.

Specs stay in the run directory and are committed with it — they are reproductions of findings, not the project's test suite. Moving a spec into the project's own suite is a human's decision, made once a finding is accepted; offer it, do not do it yourself.

## 8b. When you are running in a chain

`context.json` → `chain` is `null` for a standalone run. When it is not, you are one member of a team.

**You do not start other runs** — no `agency run`, no `agency chain`; the core refuses it. If the prompt names another specialist, that sentence is for the chain, not for you.

**When someone runs after you** (`chain.position < chain.of`), write `<RUN_DIR>/handoff.md`: what you could not reproduce and why, what you left behind in the application, which findings rest on an assumption about intended behavior — that assumption is theirs to confirm, not yours. The whole file goes into their prompt.

## 9. Cleanup

Leave the application the way you found it: log out, close the browser, return any test data that could be safely restored. If you left something behind (an unfinished booking, a test account), write it at the end of `plan.md` — otherwise the next session finds it as a finding.

Nothing you did not create with permission belongs in the project: no extra `playwright.config.ts`, no `node_modules` in the repository, no committed `storageState`.

This pack has no worktree, so there is nothing to clean up there. `agency cleanup` deliberately does nothing to such a run.
