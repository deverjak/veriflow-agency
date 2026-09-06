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

## The workflows — five over `main-panel`, one over `kvesteros-platform`, one that writes the next

This is the whole product. `agency` runs specialists against one project;
what each one finds goes through a gate (evidence required, no duplicates)
and, when the pack has one, out through its own **sink** onto a board — no
export step, no human in between. A finding with nowhere to go rests in the
project's own committed memory instead.

**W1 — Review a pull request**

```
agency run review-graph --pr 479
```

Prepares a throwaway worktree on the PR's head commit, has the code graph
compute blast radius, and gives you the command to launch the agent — in this
terminal, or with `--wait` to launch and gate it in one step. When it is
done, `agency ingest` runs the gate and sends what passes it straight to the
board through the pack's `sink`:

```
agency findings                     # what happened to each one — sent, or why not
```

The same thing in the editor: findings sit next to the line of code,
**read-only** — each one showing its board reference, or that this pack has
no board to send it to.

**W2 — Review with a product judgment**

```
agency chain review-graph po --pr 479 --prompt "does this change make product sense?"
```

The reviewer runs first; the product owner gets its findings **as its
brief** — judges each one (`agency triage accept <id>` sends it to the board
right away, `agency triage reject <id> --reason …` remembers not to report it
again), answers the question, and writes what that means for the queue.
There is no `defer`: whatever neither member judges still reaches the board
once the chain ends, never silently dropped.

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

**W6 — Strategy with a founder** (`kvesteros-platform`)

```
agency run ceo --prompt "how do I approach the region's innovation agency, and what do we ask for?"
```

The founder's strategy partner. Reads the roadmap before the web, then the
web this run — the region's destination agencies, its innovation agency, the
national portals, the AI trip planners — answers the question in
`answer.md`, proposes at most three bets, and drafts every outward-facing
step (an e-mail, a one-pager outline, a call agenda) into `drafts/` for the
founder to send. Findings are what is wrong with the strategy itself: a
claim of difference an incumbent already meets, work no bet covers, a gap
that would end an institutional conversation on the first reply. The pack
has no `sink` — the project has no board — so they rest in the committed
knowledge. `needs` names `WebSearch` and `WebFetch` by tool name: an
unsupervised run has nobody to approve a fetch, and a founder pack that
cannot read the web is a memoir.

**W7 — Write a specialist this project does not have yet**

```
agency run author --prompt "watch our database migrations for anything that cannot be rolled back"
```

A pack is source in the repository, so writing one is a code-writing task
and an agent does it. It reads the project — stack, CI, docs, whether `gh`
sees a board, what the existing packs already cover — then asks, in the
terminal, only what the repository could not answer, agrees the dimensions
out loud, and writes `.claude/skills/agency-<name>/`. What it leaves behind
is **uncommitted source in the working tree**: git is the review, and the
first real run is yours to start (`agency run` refuses to start inside an
agent, so it cannot try its own pack).

It writes no findings, and `no-findings` in the panel is the correct
outcome — a run that produced a directory was not looking for anything. The
value is not the JSON, which any template could emit; it is the **Project
facts** section and the dimensions. A dimension is one question whose answer
can come back false, about something a finding can point a line number at:
"Performance" is not one, "queries on a request path with no index behind
them" is. `packs/author/references/dimensions.md` is the argument, with the
rewrites.

In the extension it is **Write a new specialist…** on the Specialists view,
which asks for the description and for which runner writes it — the one
task worth choosing a model for by hand, since a `SKILL.md` decides what
that specialist finds for months.

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

Then, once per project:

```
cd <project>
agency init
```

That copies `author` into `.claude/skills/agency-author/` and writes
`.agency/.gitignore` so run records stay out of git. Nothing else is
installed and nothing is configured: from here on the project writes its own
specialists with `agency run author --prompt "…"`, or with **Write a new
specialist…** in the panel, which offers the same thing when the pack is
missing.

(In *this* repository the same command would put a second copy of
`packs/author` under `.claude/skills/` — the source and the copy would then
drift apart, so run it in the projects being worked on, not here.)

Prerequisites: `git`, `uv`, VS Code 1.85+; a reviewer additionally needs `gh`
(logged in) and a code graph tool; QA needs Playwright's browsers installed.
`agency doctor` checks all of it — **before** a run, not halfway through —
and only asks about what the packs actually in the project need.

It also reads the project's own `CLAUDE.md` and `AGENTS.md`. Those reach the
specialist on their own — the runner starts the agent in the project, or in a
worktree carrying the committed copy, and never passes or overrides that file
— so a specialist works under two sets of instructions at once. Where they
disagree is the founder's business, with one exception `doctor` will name: a
house rule forbidding a tool a hired pack stands on. It quotes the sentence
and its line, and stops there. Which of the two gives is not a runner's call.

## Shape

Three things, each with one responsibility. The boundary between them is a
contract, not configuration.

```
veriflow-agency/                     this repository
  packages/core/     → `agency`      RUNNER — run, record, gate, triage, dedup, memory, chain, providers.
                                     Knows nothing about any target project.
  packages/extension/                VIEWER — runs, findings next to the line, read-only.
                                     Talks only to `agency … --json`.
  packs/                             EXAMPLES — reference copies of main-panel's and kvesteros-platform's packs, for the next project.
                                     Not bundled, not installed — except `author/`, which is generic, ships with the
                                     core, is what `agency init` copies in, and is what writes all the others.

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
`installed.json`, no registry of who is hired.

The one exception is the bootstrap, and it is an exception on purpose: a
fresh repository has no pack, and the pack that writes packs cannot write
itself. `agency init` copies `author` in — one skill directory, uncommitted,
for you to read and commit like any other source — and everything after that
is written by it, here, against this repository.

### The runner — `agency --help`

```
agency — specialists for this repository — skills in .claude/skills/agency-<name>/.
Attended, on your own login, with evidence-backed findings that stay.

  init        put the one generic pack — `author` — into this project
  packs       the specialists in this project
  doctor      check the prerequisites BEFORE a run starts
  prs         pull requests to review — open and merged
  run         run a pack — over a pull request, or over the project as it is
  chain       run specialists one after another, each judging what the previous one found
  validate    check findings.json against the contract and the anchors against the code
  graph       ask the code graph — one door for the core and the agent, JSON out
  ingest      the gate: contract, existence, threshold, dedup, dispatch — BEFORE a finding becomes a finding
  knowledge   what the project knows, as committed markdown — readable without Agency
  metrics     precision, dedup, queue age — by dimension, severity and provider
  cleanup     close a run that is not coming back and remove its worktree — `--all` for every finished one
  findings    findings and where they went
  triage      accept (send to the board) or reject a finding — an agent calls this too
  note        a note on a finding — free text, not a decision
  status      overview of the project's runs
  follow      ask the specialist of a finished run one more thing — the same session
  serve       open this project to a paired phone on the tailnet, for a while
```

Eighteen commands. `init` is the whole of the setup and it takes no
decisions: it copies the one generic pack into the project and keeps run
records out of git. There is no `add`, `hire`, `fire`, `roster`,
`providers`, `projects`, `config`, `brief`, `backlog`, or `export` — a
one-way push to a board is the pack's own `sink`, called by `ingest`, not a
separate step. `agency run <pack>`
prepares the run and prints the ready command; `--wait` launches the agent
and runs the gate itself when it finishes; `--launch` hands this terminal
over to the agent directly; `--remote-control` starts it as a session the
Claude app can drive; `--json` only prepares, for the extension.

### Supervised, or on its own

A run is supervised by default: the agent sits in an interactive terminal,
and anything its pack did **not** pre-authorize stops and asks the person
watching. A pack lists those hold-backs in `pack.json` as `needsUnattended`
— for the product owner, `backlog.py promote` and `decide`, the two that
notify people or sign a disposition. Everything reversible (`snapshot`,
`comment`, `draft`) stays in the ordinary `needs` grant.

```
agency run po --unattended --wait --prompt "…"
```

`--unattended` says nobody is going to be asked: `needsUnattended` joins the
grant, the agent runs in print mode, and the core reads its event stream and
prints progress rather than handing over the terminal. A chain member is
always unattended for the same reason — the orchestrator is blocked waiting
for it, so there is nobody there to answer. The run record says which it was
(`trigger.attended`), because that is not something to reconstruct later.

In the extension the same choice is a question: a pack that declares
`needsUnattended` asks **Supervised** or **Unsupervised** when you start it,
and any other pack is never asked, because for it the answer changes nothing.

### One more question — `agency follow`

An unattended run answers once and the process ends. What it worked out along
the way — the target, what it read, why it wrote what it wrote — is not gone
though: the runner keeps the session, and the run record keeps its id.

```
agency follow --prompt "and what does that mean for the migration?"
agency follow --run 01K5M2RR --remote-control
```

The first resumes that session with another question, prints the answer as it
arrives and leaves it in `RUN_DIR/answer-1.md`. The second reopens the same
session as one you can talk to, named `agency-<pack>-<run>` so it can be found
in the Claude app.

It is the run continuing, not a new one: the stream is **appended** to the same
`agent.jsonl`, and turns, tokens and cost are **added** to the run's totals
rather than replacing them — a run whose cost quietly became the cost of its
last question would answer "which model is worth it" wrong, and nothing would
look broken. What a follow-up does not do is re-gate: the run keeps the status
the gate gave it, and `agency ingest --run <id>` is the step that says the
findings changed. A run started in a terminal has no session id to resume,
because nothing streamed one; `follow` says so rather than starting an agent
with an empty context.

Providers are **two, and they are in code** — a table of `claude` and
`codex` in `providers.py`: binary, flags, authorization shape, streaming
dialect. A third runner is a row in that table, not a registry. Every run
is authorized to write into its own worktree and `.agency/`, plus whatever
its pack's `needs` names; `--bypass` turns that check off entirely, for a
sandbox that will not otherwise let the agent run its own binary.

In the extension that is the **second arrow** on a specialist's row: ▶ runs
it authorized as usual, ▶▶ runs exactly the same thing with `--bypass` —
`--dangerously-skip-permissions` for Claude Code,
`--dangerously-bypass-approvals-and-sandbox` for Codex. It is a separate
icon rather than a checkbox on the first one, because a method that reads a
whole project has no short `needs` list (a strategy pack asked about fifty
separate commands in a single run), and the honest answer to that is either
a manifest nobody can keep true or a run you knowingly start unguarded. The
run record says which it was: `agent.authorized` is `grant` or `bypass`.

The model is **named, never inherited**. A run with no `--model` used to
pass no model flag at all, which means the runner's own session default —
so a run could go to a model nobody chose for that specialist, and the
record kept `model: null`, leaving "which model produces better findings"
with a bucket full of unknowns. The table names the default instead
(`claude` → `sonnet`, the ordinary run), and anything worth more says so in
`--model`, in a preset, or in the question the extension asks.

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
  "sink": "python .claude/skills/agency-po/scripts/backlog.py draft --finding {id} --run-dir {runDir}",
  "dimensions": [{ "id": "scope", "title": "Work in flight that no commitment covers" }, "…"]
}
```

Every key is read by the runner: `requires` feeds `doctor`; `target` /
`worktree` / `graph` shape the run preparation; `prompt` (`required` |
`optional` | `none`) validates `--prompt`; `needs` is the agent's allowlist — shell commands, or a Claude Code tool by its
PascalCase name (`WebSearch`, `WebFetch(domain:…)`) for a pack that works on
the web;
`minScore` is the gate's threshold; `sink` is where a gated finding goes —
absent, it just rests as `candidate` in the committed knowledge, a project
with no board; `dimensions` validates findings and labels the extension's
tree. There is no version — a pack is versioned with the project's own git
history, not separately.

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

The one pack that is never copied by hand is `author` — it is the only
generic one, because its subject is this system rather than any project, so
it ships with the core and a command puts it in place:

```
agency init
```

After that, `agency run author --prompt "…"` writes the project's own
specialists in place, and there is nothing left to copy at all. This is also
why the extension knows one pack by name: a run that writes a specialist
cannot be started from a row that does not exist yet — so the row's absence
is what offers the bootstrap.

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
  trail.jsonl         append-only: what a finding became and where it went,
                      per line — the one thing that survives a discarded run
  index.md            overview — what the project knows, sorted by outcome
  log.md               chronology: what each run looked at, in its own words
  findings/<id>.md    findings across runs, packs and specialists — generated
  pages/<pack>/       a specialist's own conclusions about this project
```

`agency ingest` regenerates `findings/` from the run records and the trail
after the gate; `agency knowledge --rebuild` rebuilds the whole bundle —
the source of truth stays in the runs and the trail, and the bundle can
always be thrown away and rebuilt. Discarding a run (`agency cleanup
--discard`, or **Discard all finished runs…** in the extension) never loses
what it sent to a board or had rejected — the trail already has it, and
`trail.jsonl` is never touched by cleanup. A page in `pages/<pack>/` is
plain markdown with one convention: a `Last reviewed: <date>` line at the
top, and a rule every pack's `SKILL.md` repeats — write conclusions, not a
log; rewrite what stopped being true rather than adding to it.

### The extension — a preset for which runner

A pack's row in **Specialists** can carry saved presets: `provider` and
`model` chosen ahead of time, so starting a run does not stop to ask (a real
reason this exists: a subscription limit hit mid-team, and the next run
needs a different provider). A preset is a VS Code setting
(`agency.presets`, per workspace) spelling out `agency run <pack>
--provider … --model …` in advance — the core knows nothing about it, and
there is no `.agency/*.json` for it either.

A row with no preset **asks once**: which runner, which model, and then it
offers to keep the answer. Saying no means being asked again — an answer
worth keeping is a preset, and a preset is the thing that stops the
question. A row that has one runs on its first preset and says so where the
skill directory used to sit, so what a click starts is readable without
opening anything. Every preset row carries the same two arrows as the pack
above it: a preset pins the runner, never whether the run is supervised.

**Runs → Discard all finished runs…** clears every run whose terminal is
gone in one step (`agency cleanup --all --discard`). Safe by construction:
the committed trail keeps what any of them sent to a board or had rejected,
so nothing that mattered is deleted with the record.

### From somewhere else — `agency serve`

The third client, for the case where the person is not at the machine. The PC
is on, the projects are open, and a specialist should start now rather than
tonight:

```
agency serve --scan ~/Documents/coding --save --hours 8
```

The command **is** the activation: while it runs, those projects can be worked
on from a phone, and when it stops, they cannot. It prints a pairing code the
phone types once; what comes back is a per-device token, kept outside the
project (a token in `.agency/` is a token in a pull request) next to
`remote.jsonl`, where every remote action lands as a line. Starting a run
with the authorization checks off is a right a device is paired with, not a
checkbox in a request: `agency serve --allow-bypass` opens a pairing window
that grants it, and without that flag no device has it and no request can ask
for one. That last half is not decoration — the right used to be read off the
pairing request itself, which meant anybody holding the code could claim it
while the page below the form promised the opposite.

**Which projects, and where that is written down: nowhere.** `--scan` walks a
tree two levels deep and opens every repository that has a specialist in it —
skipping a run's throwaway worktree, whose `.git` is a file rather than a
directory, and never descending into a repository. `--save` stores that
question (not its answer, which would go stale the day something is cloned),
so a bare `agency serve` opens the same set next time. `--project <path>`
adds one from outside the scanned trees, specialists or not. This is the one
command that knows about more than one project: `run`, `findings` and the
rest still resolve from the current directory, because you are standing in a
project when you use them — and on a phone you are not standing anywhere.

It listens on the **loopback**, and what publishes it is `tailscale serve`,
which terminates TLS and knows who is on the other end. No public IP, no port
forwarding, nothing exposed — and never `tailscale funnel`, which is the same
command for the opposite thing.

```bash
tailscale serve --bg 7777            # https://<machine>.<tailnet>.ts.net/
tailscale serve --bg --http=80 7777  # so the app's http link lands there too
```

The second line is worth the trouble: the Tailscale app offers the http
address first, and http and https are separate origins with separate
`localStorage`, so without it the same phone pairs twice and looks unpaired
whenever it takes the other link. Published on both, the daemon answers a
plain-http request with a redirect to the https address — it can tell, because
the proxy sets `X-Forwarded-Proto` only on the https side. A request straight
to the loopback carries no forwarded headers at all and is served as it is.

The daemon has no judgement of its own: it authenticates the device, knows
which projects are open, and hands everything else to `agency … --json` as a
subprocess. The run it starts is the run the terminal starts, plus who asked
and from where — `trigger.origin` in the record is `cli`, `extension` or
`remote`, and a remote run also names the device. Progress is the agent's own
stream, tailed out of the run's `agent.jsonl` and translated by the same
`events.py` the terminal prints from; nothing is recorded twice.

What the phone opens is one page the daemon serves from the install: **every
project with its specialists on one screen**, plus what is running in each
right now. Tap a specialist, write the prompt or choose the pull request,
watch. One request builds that screen — the projects are asked in parallel and
their pack lists cached for a minute — because a phone that makes eight round
trips before it shows anything shows a spinner. No build step and no deploy:
the page is a file read off disk on every request, so an edit at the machine
is live on the next refresh. A connection lost in a lift resumes where it
stopped, because the browser sends `Last-Event-ID` by itself and the daemon
reads it.

Every screen has a URL — `/p/<project>/run/<id>`, down to the document being
read. That is not decoration on a phone: without it the back gesture leaves the
site instead of going back one screen, which is what it did until the page
learned to route, and a run being watched could not be reloaded or reopened
from the home screen. The daemon serves the page for every path that is not the
API, so those URLs survive a refresh.

**Two ways to start a specialist, because supervision is a choice and not a
property of the pack.** *Run unsupervised* is the one above: nobody can answer
it, so it never asks, it streams to the phone, and the gate runs by itself when
it ends. *Open a session I can talk to* starts the same run with Claude Code's
**Remote Control** — a window opens on the machine and the session is named
`agency-<pack>-<run>`, which is what you look for in the Claude app. That mode
shows no live progress and says so: an interactive `claude` publishes no
machine-readable stream, and inventing one would mean showing progress for a
session this daemon knows nothing about. It also does not end by itself, so the
phone gets the gate as a button.

**Which model does the work is a choice on that screen, not a default nobody
sees.** The dropdown under the prompt is filled from the same table the launch
flag is built from — the machine says which models it offers and which one it
would have picked anyway, so the page keeps no list of its own — and it opens
on `sonnet`, the ordinary run. A heavier model for work worth more, and the
record keeps the answer either way, which is what makes “which model produces
better findings” a question with numbers behind it.

**Turning the authorization checks off is a checkbox above those buttons, not
a button of its own.** It was one for a while — *Open one with no permission
checks*, a third button beside the other two — and that shape was wrong twice
over: it made the same session look like a different thing to start, and it
covered only the interactive shape, so an unsupervised run could not be given
the same freedom at all. As a box it is what it always was, a property of
whichever run you press. It appears only for a device paired with that right,
and a device without it is told so on that screen rather than left to puzzle
over something that is not there.

**What a session asks before it starts is the thing that breaks it.** Probed by
reading the console of a real `claude`: a project whose `.mcp.json` servers
nobody has decided about stops on *"New MCP server found in this project"*, and
a directory Claude Code has never been opened in stops on *"Is this a project
you trust?"* — which `--dangerously-skip-permissions` does not skip either. Both
land in front of a person who is not there. So a session started from a phone is
launched with `--strict-mcp-config` (the MCP question cannot arise; the price is
that the project's MCP servers are off), and the trust answer is **read in
advance** out of `~/.claude.json`: when the directory is one the runner has
never been let into — a specialist that works in a throwaway worktree is a new
directory every time — the run is closed with that as its reason instead of
opening a window that hangs. If that answer cannot be read at all, the launch
goes ahead: a guess that refuses a session which would have worked is worse than
the hang it was avoiding.

**A finished run can be asked one more thing.** The run screen of an unattended
run carries a question box: *Ask* resumes the session and the answer arrives in
the same feed the run was watched in (the page reopens the stream where it
stopped reading, so nothing is replayed), and *Carry on in the Claude app*
reopens that same session with Remote Control instead. Both are `agency follow`
on the machine — the daemon adds who asked and nothing else.

**And a run can be ended from the phone.** A session handed to the Claude app
does not finish by itself: the window waits on the machine for somebody to
close it, and until they do, the project is busy, the worktree is claimed and
the run says `running`. From a train there was nothing to do about that. The
run screen now carries *Close the session and its window* — a second tap
confirms, because it kills the agent where it stands — and the daemon ends the
whole process tree it started. On Windows that closes the window too: the
console belongs to the group, not to one process, so killing only the parent
would leave `claude` working in a window that answers to nobody. Then, and only
then, the run is closed as `abandoned` and the worktree is freed — that order
is the safety of it, since freeing a worktree first would delete a directory an
agent is still writing in.

The button appears only where the press will do something. A daemon can stop
what it is holding a process handle for; a run started at the machine, or one
from before a restart, may be genuinely working right now, and the record alone
cannot tell the difference — so that one is refused with `agency cleanup --run
<id>` as the answer, at the machine where its window is. It is a kill, not a
goodbye: there is no way to send Ctrl-C into another console's process group, so
whatever the agent was in the middle of stops there. Like every other remote
action, the stop is a line in `remote.jsonl` with the device that asked.

### Three rules the whole thing stands on

**Truth lives in the project, not in the tool.** Runs, findings and
decisions live in `<project>/.agency/` and are committed. They survive a
reinstall of the tool and a fresh clone of the repository, and can be
reviewed in a pull request.

**Only JSON crosses the core↔client boundary**, shaped by `run.v1` and
`finding.v1`. The extension does not know what language the core is
written in.

**A decision is an operation on storage, not a UI command.** `agency
triage` — called by a chain member judging what an upstream one found, or
typed by a person in a terminal — writes to the same append-only file an
agent's own call does. VS Code no longer makes this call at all: it reads
what happened and shows it, it does not decide.

## Structure

| Path | What is inside |
|---|---|
| `packages/core/` | the runner and CLI (Python, `uv`) |
| `packages/extension/` | the VS Code extension (plain JS, no build step) |
| `packs/` | reference copies of packs living in `main-panel` and `kvesteros-platform`, for the next project to copy — plus `author/`, the generic one, which ships with the core and is what `agency init` puts into a project |
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
