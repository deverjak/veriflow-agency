// Starting a run — from picking a target to a running agent.
//
// The target is not always a pull request. What a pack runs against is its
// own run policy from `agency packs --json` (`run.target`, `run.prompt`):
// a reviewer asks for a PR, QA asks for a prompt. If the extension decided
// this from a pack's name, every new specialist would be a change to the
// client.
//
// A review runs in the integrated terminal, not in the background. That is
// not laziness — attended is meant to be a property of the system, not an
// intention. When you can see a run going and can talk to it, that is
// attended operation. If the extension launched it in the background, the
// attended/unattended boundary would live only in your memory.
//
// Unsupervised is the one deliberate exception, and it is still visible: a
// pack that declares `needsUnattended` asks which way this run goes, and
// the unsupervised answer hands the whole thing to `agency run …
// --unattended --wait` in a terminal you can watch. What changes is who
// gets asked before it acts, not whether you can see it happen.
//
// The shape of the launch command belongs to the CLI. `agency run --json`
// returns a ready `launch` argv and the extension only sends it to a
// terminal — if it assembled it too, there would be a second place to set
// the model, and the run record would lie about it.

const vscode = require('vscode');
const cli = require('./cli.js');
const state = require('./state.js');

const STATE_ICON = { open: '$(git-pull-request)', merged: '$(git-merge)' };

// The one pack this client knows by name. It has to: "write me a new
// specialist" is a run over a pack that does not exist yet, so there is
// nothing on a row to start it from. Everything after the name is ordinary
// — it is discovered through `agency packs` like the rest, and a project
// without it simply does not offer the command.
const AUTHOR_PACK = 'author';

function items(prs) {
  const open = prs.filter((p) => p.state === 'open');
  const merged = prs.filter((p) => p.state === 'merged');
  const list = [];

  const push = (p) => list.push({
    label: `${STATE_ICON[p.state]} #${p.number}  ${p.title || ''}`,
    description: p.reviewed ? '$(check) already reviewed' : undefined,
    detail: p.state === 'merged'
      // A retrospective audit is a full mode, not an exception — on a
      // project with a single merged PR a pack would otherwise have
      // nothing to do.
      ? `retrospective audit · ${(p.mergedAt || '').slice(0, 10)} · ${p.author || ''}`
      : `open · ${(p.updatedAt || '').slice(0, 10)} · ${p.author || ''}`,
    pr: p,
  });

  if (open.length) {
    list.push({ label: 'Open', kind: vscode.QuickPickItemKind.Separator });
    open.forEach(push);
  }
  if (merged.length) {
    list.push({ label: 'Merged — retrospective audit', kind: vscode.QuickPickItemKind.Separator });
    merged.forEach(push);
  }
  return list;
}

/** Pack metadata from the snapshot — run policy, dimensions. */
function packInfo(name) {
  return (state.snapshot.packs || []).find((p) => p.name === name) || null;
}

/** Packs whose method runs over the project rather than over a pull request. */
function workspacePacks() {
  return (state.snapshot.packs || []).filter((p) => p.run && p.run.target === 'workspace');
}

/** Packs whose method walks a pull request. */
function reviewPacks() {
  return (state.snapshot.packs || []).filter((p) => !(p.run && p.run.target === 'workspace'));
}

/**
 * Which specialists should take this. Several may.
 *
 * Multi-select rather than a single pick: two packs reviewing the same code
 * is a legitimate setup, and asking twice would make the cheap thing feel
 * expensive. One available pack skips the dialog entirely.
 */
async function pickPacks(candidates, { title, canMultiSelect = true } = {}) {
  if (!candidates.length) return [];
  if (candidates.length === 1) return candidates;

  const picked = await vscode.window.showQuickPick(
    candidates.map((p) => ({
      label: `$(person) ${p.title || p.name}`,
      description: p.name,
      detail: p.description,
      pack: p,
    })),
    {
      title,
      placeHolder: canMultiSelect
        ? 'Pick more than one to run them side by side — they share the queue and dedup'
        : 'One specialist',
      canPickMany: canMultiSelect,
      matchOnDescription: true,
      matchOnDetail: true,
    });

  if (!picked) return null;                       // Esc = walked away
  return (Array.isArray(picked) ? picked : [picked]).map((x) => x.pack);
}

/**
 * Asks for a prompt — free text, this run only.
 *
 * Returns `{prompt}`, or null when the user walked away.
 */
async function askPrompt(pack, who) {
  const info = packInfo(pack) || {};
  const policy = (info.run && info.run.prompt) || 'none';
  if (policy === 'none') return { prompt: undefined };

  const typed = await vscode.window.showInputBox({
    // In a chain we ask per member, so the title has to say WHO. One field
    // for everyone is exactly the mistake that once had a reviewer answer
    // questions written for the product owner.
    title: who ? `${who} — what is its part?` : 'What should this run focus on?',
    placeHolder: 'e.g. the checkout flow as a logged-out user',
    prompt: 'Free text. It is written into the run record — "which prompt produces '
      + 'better findings" is a question worth answering with numbers.',
    ignoreFocusOut: true,
  });
  if (typed === undefined) return null;
  if (!typed.trim() && policy === 'required') {
    vscode.window.showWarningMessage(
      'Agency: this specialist needs to know what to work on — the run was not started.');
    return null;
  }
  return { prompt: typed.trim() || undefined };
}

/**
 * Supervised, or on its own? Asked ONLY for a pack that declares
 * `needsUnattended` — for any other one the answer changes nothing, so the
 * question would be pure noise.
 *
 * Supervised is the default and the safe one: the pack's consequential
 * commands stay ungranted, so Claude Code stops and asks the person
 * watching before it promotes a draft or signs a disposition. Unsupervised
 * grants them up front — which also means print mode, because a run nobody
 * is asked about is a run nobody can answer either.
 *
 * Returns a map of pack name → unattended, or null when the user walked away.
 */
async function askSupervision(packs) {
  const answers = new Map();
  for (const p of packs) {
    if (!((p.run && p.run.needsUnattended) || []).length) continue;
    const picked = await vscode.window.showQuickPick(
      [
        {
          label: '$(eye) Supervised',
          description: 'you approve each one',
          detail: `You are asked before ${p.title || p.name} runs anything that leaves a `
            + 'mark someone else sees — promoting a draft to an issue, signing a decision.',
          unattended: false,
        },
        {
          label: '$(rocket) Unsupervised',
          description: 'complete trust',
          detail: 'It acts on its own and nothing stops to ask. The run switches to print '
            + 'mode, so you watch a stream of what it did instead of talking to it.',
          unattended: true,
        },
      ],
      {
        title: `${p.title || p.name} — supervised, or on its own?`,
        placeHolder: 'This specialist can act outward — promote a draft, sign a decision',
        ignoreFocusOut: true,
      });
    if (!picked) return null;                     // Esc = walked away
    answers.set(p.name, picked.unattended);
  }
  return answers;
}

/**
 * An unsupervised run hands the whole thing to the CLI in one terminal
 * command, the way a chain already does: `agency run … --unattended --wait`
 * prints its own progress from the agent's event stream and runs the gate
 * itself when it ends. Preparing it here and sending the bare `claude -p …`
 * argv instead would put raw JSONL in front of the user.
 */
function runUnsupervised(cwd, pack, opts, log) {
  const args = ['run', pack.name, '--unattended', '--wait'];
  if (opts.pr) args.push('--pr', String(opts.pr));
  if (opts.latestMerged) args.push('--latest-merged');
  if (opts.force) args.push('--force');
  if (opts.provider) args.push('--provider', opts.provider);
  if (opts.model) args.push('--model', opts.model);
  if (opts.since) args.push('--since', opts.since);
  if (opts.prompt) args.push('--prompt', opts.prompt);
  // Unsupervised and unguarded are two different things, and both of them
  // are the user's choice. Dropping this here would silently give the
  // second arrow the first arrow's authorization.
  if (opts.bypass) args.push('--bypass');

  const term = vscode.window.createTerminal({
    name: `Agency · ${pack.title || pack.name} · unsupervised`
      + (opts.bypass ? ' · bypass' : ''), cwd });
  term.show(true);
  term.sendText([cli.bin(), ...args].map(quote).join(' '));

  if (log) log.appendLine(`[run] unsupervised: ${args.join(' ')}`);
  vscode.window.showInformationMessage(
    `Agency: ${pack.title || pack.name} is running unsupervised — it will not ask before `
    + 'it acts, and the gate runs by itself when it finishes.'
    + (opts.bypass ? ' Its runner has no permission checks left either.' : ''));
  return { pack: pack.name, unattended: true };
}

/**
 * Prepares one run per specialist and starts each in its own terminal.
 *
 * Preparation is SEQUENTIAL on purpose even though the runs themselves are
 * parallel: `agency run` claims a worktree path, and letting two
 * preparations race would mean the guard in the core sees an empty record
 * and hands both of them the same directory. The agents then run side by
 * side, which is the part that actually costs wall-clock time.
 */
async function runEach(cwd, packs, opts, log) {
  const supervision = await askSupervision(packs);
  if (!supervision) return null;                  // Esc = walked away

  const started = [];
  for (const p of packs.filter((x) => supervision.get(x.name))) {
    started.push(runUnsupervised(cwd, p, opts, log));
  }

  const supervised = packs.filter((x) => !supervision.get(x.name));
  if (supervised.length) await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: supervised.length > 1
        ? `Agency: preparing ${supervised.length} runs`
        : `Agency: preparing a ${supervised[0].title || supervised[0].name} run`,
      cancellable: false,
    },
    async (progress) => {
      for (const p of supervised) {
        progress.report({ message: p.title || p.name });
        const result = await cli.run(cwd, p.name, opts);
        if (!result.ok) {
          const msg = result.error || 'preparation failed';
          if (result.reason === 'already-reviewed' && !opts.force) {
            const again = await vscode.window.showWarningMessage(
              `${p.title || p.name}: ${msg}`, 'Run anyway');
            if (again) {
              const forced = await cli.run(cwd, p.name, { ...opts, force: true });
              if (forced.ok) started.push(launch(forced.data, p, log));
              continue;
            }
            continue;
          }
          vscode.window.showErrorMessage(`Agency · ${p.title || p.name}: ${msg}`);
          if (log) log.appendLine(`[run] ${p.name} failed: ${msg}`);
          continue;
        }
        started.push(launch(result.data, p, log));
      }
    });

  if (started.length > 1) {
    vscode.window.showInformationMessage(
      `Agency: ${started.length} specialists are running side by side. They share one `
      + 'queue of findings, so whatever the second one repeats is marked as a duplicate '
      + 'rather than asked about twice.');
  }
  return started.length ? started[0] : null;
}

/**
 * A run over the project as it is right now. No pull request, no worktree —
 * QA tries the running application, and that runs over the working copy.
 *
 * `extra` carries a preset's `provider`/`model`, when the run was started
 * from one — merged in ahead of the prompt, never overriding it.
 */
async function runOverWorkspace(cwd, pack, log, extra = {}) {
  let chosen = pack ? [pack] : null;

  if (!chosen) {
    const candidates = workspacePacks();
    if (!candidates.length) return null;
    // A session drives the running application, so two of them at once
    // would fight over the same browser, the same database and the same
    // fixtures. One at a time is the honest default here.
    chosen = await pickPacks(candidates, {
      title: 'Which specialist should run the session?',
      canMultiSelect: false,
    });
    if (!chosen || !chosen.length) return null;
  }

  const asked = await askPrompt(chosen[0].name);
  if (!asked) return null;

  return runEach(cwd, chosen.slice(0, 1), { ...extra, prompt: asked.prompt }, log);
}

/**
 * Which pull request. One place for both a single run and a chain.
 *
 * Skipping this step would mean the target is taken from the current
 * branch — and a user who started a review from the panel was not thinking
 * about any current branch. Typing a PR number into the prompt does not
 * change that target either: the prompt is read by the agent, the target is
 * picked by the preparation.
 */
async function pickPr(cwd, title) {
  const picked = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: 'Agency: loading pull requests…' },
    async () => {
      const prs = await cli.prs(cwd, { state: 'all', limit: 30 });
      if (!prs.length) {
        vscode.window.showWarningMessage(
          'Agency: no pull requests. Check `gh auth status` and that this repo has a remote.');
        return null;
      }
      return vscode.window.showQuickPick(items(prs), {
        title,
        placeHolder: 'Open and merged — merged ones get a retrospective audit',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    });
  return (picked && picked.pr) || null;
}

async function pickAndRun(cwd, log) {
  const candidates = reviewPacks();
  if (!candidates.length) {
    // No pack works over a pull request — fall back to whatever works over
    // the project, so the button never dead-ends on a project that only has QA.
    if (workspacePacks().length) return runOverWorkspace(cwd, null, log);
    vscode.window.showWarningMessage('Agency: no specialist in this project.');
    return null;
  }

  const pr = await pickPr(cwd, 'Which pull request should be reviewed?');
  if (!pr) return null;

  const chosen = await pickPacks(candidates, {
    title: `PR #${pr.number} — which specialists should review it?`,
  });
  if (!chosen || !chosen.length) return null;

  // An optional focus for the review. An empty one is the common case — a
  // reviewer covers the whole PR on its own, and a prompt only changes order
  // and depth, not the rules.
  let focus;
  const info = chosen[0];
  if (info.run && info.run.prompt && info.run.prompt !== 'none') {
    focus = await vscode.window.showInputBox({
      title: `Review of PR #${pr.number} — anything to focus on?`,
      placeHolder: 'Leave empty for a full review',
      prompt: chosen.length > 1
        ? `The same prompt goes to all ${chosen.length} specialists.`
        : undefined,
      ignoreFocusOut: true,
    });
    if (focus === undefined) return null;   // Esc = walked away, not an empty prompt
  }

  return runEach(cwd, chosen, {
    pr: pr.number,
    force: pr.reviewed || undefined,
    prompt: focus || undefined,
  }, log);
}

/** Sends the CLI's ready-made command to a terminal. Assembling it here
 *  would be a mistake. */
function launch(data, pack, log) {
  const agent = data.agent || {};
  const target = data.target || {};
  const what = target.pr ? `PR #${target.pr}` : (target.ref || 'session');
  const who = agent.provider ? (agent.model ? `${agent.provider}/${agent.model}` : agent.provider) : '';
  const bypassed = agent.authorized === 'bypass';
  const name = `Agency · ${what}` + (pack ? ` · ${pack.title || pack.name}` : '')
    + (who ? ` · ${who}` : '') + (bypassed ? ' · bypass' : '');
  const term = vscode.window.createTerminal({ name, cwd: data.worktree });
  term.show(true);
  term.sendText(data.launch.map(quote).join(' '));

  if (log) {
    log.appendLine(`[run] ${data.runId} · ${(pack && pack.name) || agent.provider}`
      + ` · worktree ${data.worktree}`);
    log.appendLine(`[run] ${data.launch.join(' ')}`);
  }
  vscode.window.showInformationMessage(
    `Agency: run ${String(data.runId).slice(0, 10)} is ready — it is running in the terminal. `
    + (bypassed
      ? 'It starts with no permission checks at all, so it will not stop to ask you about '
        + 'anything. '
      : '')
    + 'When it finishes, run “Agency: Process run output”.');
  return data;
}

// ---------------------------------------------------------------- team

async function pickAndChain(cwd, log) {
  const candidates = state.snapshot.packs || [];
  if (candidates.length < 2) {
    vscode.window.showWarningMessage(
      'Agency: a team needs at least two specialists in this project.');
    return null;
  }

  // Order is the whole point of a chain, and QuickPick does not guarantee
  // it — so it is picked one at a time. Two more clicks, in exchange for
  // seeing who judges whom.
  const order = [];
  while (true) {
    const left = candidates.filter((p) => !order.includes(p));
    if (!left.length) break;
    const step = order.length + 1;
    const picked = await vscode.window.showQuickPick(
      [
        ...left.map((p) => ({
          label: `$(person) ${p.title || p.name}`,
          description: p.name,
          detail: p.description,
          pack: p,
        })),
        ...(order.length >= 2
          ? [{ label: '', kind: vscode.QuickPickItemKind.Separator },
             { label: '$(check) Run the team', done: true }]
          : []),
      ],
      {
        title: `Team — step ${step}`,
        placeHolder: order.length
          ? `After ${order.map((p) => p.title || p.name).join(' → ')}. Each member judges what the previous one found.`
          : 'Who goes first? Whatever they find is handed to the next one.',
        matchOnDescription: true,
      });
    if (!picked) return null;                     // Esc = walked away
    if (picked.done) break;
    order.push(picked.pack);
  }

  if (order.length < 2) return null;

  // The target has to be picked, not derived. If someone in the team
  // reviews a pull request and nobody is asked, the PR of the current
  // branch is taken — and a number typed into a prompt would not change
  // that, because the prompt is read by the agent while the target is
  // picked by the deterministic preparation. Members over the project just
  // ignore `--pr`.
  const reviewsPr = order.some((p) => p.run && p.run.target !== 'workspace');
  let pr = null;
  if (reviewsPr) {
    pr = await pickPr(cwd, `Team ${order.map((p) => p.title || p.name).join(' → ')} — which pull request?`);
    if (!pr) return null;
  }

  // A prompt per member, not one for everyone. A shared sentence speaks to
  // two people at once, and whoever it is not addressed to answers it
  // anyway — seen on the first real chain.
  const focus = [];
  for (const p of order) {
    const asked = await askPrompt(p.name, p.title || p.name);
    if (asked === null) return null;               // Esc or a missing required prompt
    if (asked.prompt) focus.push(`${p.name}:${asked.prompt}`);
  }

  const args = ['chain', ...order.map((p) => p.name)];
  if (pr) args.push('--pr', String(pr.number));
  // An already-reviewed commit would stop the chain at its first step. The
  // user just picked it from a list where it was marked as such — that is a
  // choice, not a mistake.
  if (pr && pr.reviewed) args.push('--force');
  for (const f of focus) args.push('--focus', f);

  const name = `Agency · team · ${order.map((p) => p.title || p.name).join(' → ')}`;
  const term = vscode.window.createTerminal({ name, cwd });
  term.show(true);
  term.sendText([cli.bin(), ...args].map(quote).join(' '));

  if (log) log.appendLine(`[chain] ${args.join(' ')}`);
  vscode.window.showInformationMessage(
    `Agency: the team is running in the terminal — ${order.length} specialists, one after another. `
    + 'Each one waits for the previous to finish.');
  return order;
}

function quote(arg) {
  const s = String(arg);
  return /[\s"']/.test(s) ? JSON.stringify(s) : s;
}

module.exports = {
  pickAndRun, pickAndChain, runOverWorkspace, askPrompt, runEach, pickPacks,
  askSupervision, runUnsupervised,
  workspacePacks, reviewPacks, items, launch, AUTHOR_PACK,
};
