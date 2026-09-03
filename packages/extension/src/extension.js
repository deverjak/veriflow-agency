// Agency — activation and wiring.
//
// This file is NOT meant to hold logic. It is where these meet:
//
//   cli.js      calls into `agency` — the only path to data
//   state.js    one snapshot every view reads from
//   views.js    the four trees in the side panel
//   panel.js    finding detail, metrics and prerequisites in the editor
//   threads.js  findings as inline comments on the line
//   review.js   picking a target (PR or prompt) and starting an agent
//   git.js      the code as of the day of the analysis (`agency:` scheme)
//
// The boundary that holds it all together: the extension is a viewer and a
// command issuer, never an owner of state. A decision comes into being in
// `.agency/runs/<id>/decisions.jsonl`, written by `agency triage` — whether
// a click here called it, or the terminal, or an agent.

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

const cli = require('./cli.js');
const state = require('./state.js');
const views = require('./views.js');
const panel = require('./panel.js');
const gitx = require('./git.js');
const review = require('./review.js');
const { Threads, threadOf, replyTextOf } = require('./threads.js');

/** @type {vscode.OutputChannel} */
let log;
/** @type {Threads} */
let threads;
/** @type {vscode.StatusBarItem} */
let status;
/** Panels open in the editor — one per kind, so a tab does not clone itself
 *  on every click. */
const panels = new Map();
const trees = {};

// ---------------------------------------------------------------- panels

function showPanel(key, title, html, onMessage) {
  let p = panels.get(key);
  if (p) {
    p.title = title;
    p.webview.html = html;
    p.reveal(vscode.ViewColumn.Active, true);
    return p;
  }
  p = vscode.window.createWebviewPanel(`agency.${key}`, title,
    { viewColumn: vscode.ViewColumn.Active, preserveFocus: true },
    { enableScripts: true, retainContextWhenHidden: false });
  p.webview.html = html;
  if (onMessage) p.webview.onDidReceiveMessage(onMessage);
  p.onDidDispose(() => panels.delete(key));
  panels.set(key, p);
  return p;
}

async function openFinding(findingId) {
  const f = state.findingById(findingId);
  if (!f) return;
  showPanel(`finding:${findingId}`, f.title || 'Finding', panel.findingHtml(f), async (msg) => {
    const note = msg.note || undefined;
    if (msg.cmd === 'accept') await decide(findingId, 'accept', { note });
    else if (msg.cmd === 'defer') await decide(findingId, 'defer', { note });
    else if (msg.cmd === 'reject') await decide(findingId, 'reject', { reason: msg.reason, note });
    else if (msg.cmd === 'note') await addNote(findingId, msg.note);
    else if (msg.cmd === 'open') await revealFinding(findingId, 'working-tree');
    else if (msg.cmd === 'atCommit') await revealFinding(findingId, 'at-commit');
    else if (msg.cmd === 'diff') await diffFinding(findingId);
  });
}

// ------------------------------------------------------------ decisions

/**
 * The ONLY path by which a decision comes into being inside the extension.
 * It goes through `agency triage`, the same layer an agent calls — if it
 * were an editor command instead, an agent could not triage and would not
 * be an equal client.
 */
async function decide(findingId, action, opts = {}) {
  const res = await cli.triage(state.snapshot.cwd, findingId, action, opts);
  if (!res.ok) {
    vscode.window.showErrorMessage(`Agency: ${res.error}`);
    log.appendLine(`[decision] REFUSED ${findingId}: ${res.error}`);
    return null;
  }
  log.appendLine(`[decision] ${findingId} → ${action}`
    + (opts.reason ? ` · ${opts.reason}` : ''));
  // A full reload, not a light one: a decision changes precision in the overview too.
  await refresh();
  const f = state.findingById(findingId);
  if (f && panels.has(`finding:${findingId}`)) {
    panels.get(`finding:${findingId}`).webview.html = panel.findingHtml(f);
  }
  vscode.window.setStatusBarMessage(`Agency: ${action}`, 3000);
  return res.data;
}

async function addNote(findingId, text) {
  if (!text || !text.trim()) {
    vscode.window.showWarningMessage('The note is empty — write something and save again.');
    return;
  }
  const res = await cli.note(state.snapshot.cwd, findingId, text.trim());
  if (!res.ok) {
    vscode.window.showErrorMessage(`Agency: ${res.error}`);
    return;
  }
  log.appendLine(`[note] ${findingId}: ${text.trim()}`);
  await refresh({ light: true });
  const f = state.findingById(findingId);
  if (f && panels.has(`finding:${findingId}`)) {
    panels.get(`finding:${findingId}`).webview.html = panel.findingHtml(f);
  }
}

// -------------------------------------------------------------- navigation

async function revealFinding(findingId, prefer) {
  const f = state.findingById(findingId);
  if (!f || !f.anchor) return;
  const repo = state.snapshot.cwd;
  const a = f.anchor;
  const resolved = f.resolved || {};

  let uri = null;
  let line = a.line;
  if (prefer !== 'at-commit' && resolved.line && fs.existsSync(path.join(repo, a.file))) {
    uri = vscode.Uri.file(path.join(repo, a.file));
    line = resolved.line;
  } else if (await gitx.commitExists(repo, a.commit)) {
    uri = gitx.commitUri(repo, a.commit, a.file);
  }
  if (!uri) {
    vscode.window.showWarningMessage(
      `“${f.title}” cannot be placed — ${(resolved.note || 'neither the file nor the commit is available')}. `
      + 'The body of the function as of the analysis is stored in the finding detail.');
    return;
  }
  const doc = await vscode.workspace.openTextDocument(uri);
  const ed = await vscode.window.showTextDocument(doc, { preview: false });
  const l = Math.min(Math.max(line, 1), doc.lineCount) - 1;
  ed.revealRange(new vscode.Range(l, 0, l, 0), vscode.TextEditorRevealType.InCenter);
  ed.selection = new vscode.Selection(l, 0, l, 0);
}

async function diffFinding(findingId) {
  const f = state.findingById(findingId);
  if (!f || !f.anchor) return;
  const repo = state.snapshot.cwd;
  const a = f.anchor;
  const right = vscode.Uri.file(path.join(repo, a.file));
  if (!fs.existsSync(right.fsPath)) {
    vscode.window.showWarningMessage('The file does not exist in the working tree — there is nothing to compare with.');
    return;
  }
  await vscode.commands.executeCommand('vscode.diff',
    gitx.commitUri(repo, a.commit, a.file), right,
    `${path.basename(a.file)} — ${String(a.commit).slice(0, 8)} ↔ working tree`);
}

// ------------------------------------------------------------- redraw

function updateStatusBar() {
  const s = state.snapshot;
  if (!status) return;
  if (!s.probe.ok) {
    status.text = '$(tools) Agency';
    status.tooltip = s.probe.error || 'Agency is not ready';
  } else {
    const q = state.queue().length;
    status.text = q ? `$(inbox) Agency: ${q}` : '$(check-all) Agency';
    status.tooltip = q
      ? `${q} findings waiting for a decision`
      : 'No finding is waiting for a decision';
  }
  status.command = 'agency.view.findings.focus';
  status.show();
}

async function refresh(opts = {}) {
  await state.refresh(opts);
  updateStatusBar();
  // Context drives which welcome screen shows. An empty panel with no
  // explanation is the worst state this tool can be in — the user cannot
  // tell whether nothing was found or nothing ran.
  const ctx = vscode.commands.executeCommand.bind(vscode.commands);
  ctx('setContext', 'agency.ready', state.snapshot.probe.ok);
  ctx('setContext', 'agency.reason', state.snapshot.probe.reason);
  ctx('setContext', 'agency.hasRuns', (state.snapshot.runs || []).length > 0);
  ctx('setContext', 'agency.hasFindings', (state.snapshot.findings || []).length > 0);

  if (vscode.workspace.getConfiguration('agency').get('commentThreads') !== false
    && state.snapshot.probe.ok && state.snapshot.cwd) {
    await threads.build(state.snapshot.cwd, state.snapshot.findings);
  } else {
    threads.clear();
  }
}

// ------------------------------------------------------------------ activation

function activate(context) {
  log = vscode.window.createOutputChannel('Agency');
  context.subscriptions.push(log);
  log.appendLine(`[activation] ${new Date().toISOString()}`);

  threads = new Threads(log);
  context.subscriptions.push({ dispose: () => threads.dispose() });

  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(
    gitx.SCHEME, new gitx.CommitContentProvider()));

  trees.overview = new views.OverviewTree();
  trees.tools = new views.ToolsTree();
  trees.runs = new views.RunsTree();
  trees.findings = new views.FindingsTree();
  const findingsView = vscode.window.createTreeView('agency.findings', {
    treeDataProvider: trees.findings, showCollapseAll: true,
  });
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('agency.overview', trees.overview),
    vscode.window.registerTreeDataProvider('agency.tools', trees.tools),
    vscode.window.registerTreeDataProvider('agency.runs', trees.runs),
    findingsView);

  // A badge with the number waiting. The backlog has to be visible without a
  // click — it is provably the most expensive place in the whole system.
  state.onDidChange(() => {
    const q = state.queue().length;
    findingsView.badge = q
      ? { value: q, tooltip: `${q} findings waiting for a decision` } : undefined;
  });

  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  context.subscriptions.push(status);

  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  // --- main actions
  reg('agency.refresh', () => refresh());

  reg('agency.review.pick', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) {
      return showNotReady();
    }
    const d = await review.pickAndRun(state.snapshot.cwd, log);
    if (d) setTimeout(() => refresh(), 2000);
  });

  // A team: specialists in sequence, each judging what the previous one
  // found. Orchestration stays with the CLI — `agency chain` runs the steps
  // itself, so this only assembles the command for the terminal.
  // Orchestrating it in JS would be a second place a run comes into being.
  reg('agency.chain.run', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) return showNotReady();

    const team = await review.pickAndChain(state.snapshot.cwd, log);
    // A longer delay than for a single run: a chain returns nothing until
    // its first member finishes, and there is nothing to reload before that.
    if (team) setTimeout(() => refresh(), 5000);
  });

  // QA and other packs that work over the project, not over a pull request.
  // One general command — which pack actually runs is decided by its own
  // run policy.
  reg('agency.qa.run', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) return showNotReady();

    if (!review.workspacePacks().length) {
      vscode.window.showInformationMessage(
        'Agency: no specialist that works over the running project is in this repository yet.');
      return;
    }
    const d = await review.runOverWorkspace(state.snapshot.cwd, null, log);
    if (d) setTimeout(() => refresh(), 2000);
  });

  reg('agency.ingest', async () => {
    const runId = await pickRun('Which run should be processed?');
    if (runId === undefined) return;
    const res = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'Agency: gate over the run output' },
      () => cli.ingest(state.snapshot.cwd, runId));
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    const c = res.data.counts;
    vscode.window.showInformationMessage(
      `Agency: ${c.raw} written · ${c.gated} dropped by the gate · `
      + `${c.duplicates} duplicates · ${c.kept} to decide`);
    await refresh();
  });

  // Closing a run is never automatic. The agent runs in a terminal this
  // process did not start and cannot watch, so "is it still going?" has no
  // honest answer here — only the person who closed the terminal knows.
  reg('agency.run.close', async (arg) => {
    const id = runIdOf(arg);
    const res = await cli.cleanup(state.snapshot.cwd, id ? { run: id } : { unfinished: true });
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    const closed = (res.data.closed || []).filter((c) => c.action === 'abandoned');
    log.appendLine(`[cleanup] closed ${closed.map((c) => c.run).join(', ') || 'nothing'}`);
    vscode.window.setStatusBarMessage(
      closed.length ? `Agency: ${closed.length} run(s) closed` : 'Agency: nothing was open', 4000);
    await refresh();
  });

  reg('agency.chain.discard', async (arg) => {
    const chainId = chainIdOf(arg);
    if (!chainId) return;
    const members = (state.snapshot.runs || [])
      .filter((r) => r.chain && r.chain.id === chainId)
      .sort((a, b) => a.chain.position - b.chain.position);
    if (!members.length) return;

    // The same rule as for one run, summed across the whole chain: a
    // decision is work somebody did, and the precision numbers are computed
    // from it.
    const decided = members.reduce(
      (n, r) => n + Math.max((r.findings || 0) - (r.undecided || 0), 0), 0);
    if (decided) {
      vscode.window.showWarningMessage(
        `Agency: the team carries ${decided} decision(s) — discarding it would take `
        + 'the numbers with it. Discard the individual runs that have none, or close them.');
      return;
    }

    const findings = members.reduce((n, r) => n + (r.findings || 0), 0);
    const running = members.filter((r) => r.status === 'running').length;
    const yes = await vscode.window.showWarningMessage(
      `Discard the whole team — ${members.length} run(s)?`,
      { modal: true,
        detail: members.map((r) => `${r.chain.position}/${r.chain.of}  ${r.pack}`
          + ` — ${r.targetLabel || ''}`).join('\n')
          + `\n\nThe records, their evidence and ${findings} finding(s) are deleted.`
          + (running ? `\n${running} of them is still marked running.` : '') },
      'Discard');
    if (yes !== 'Discard') return;

    for (const r of members) {
      const res = await cli.cleanup(state.snapshot.cwd, { run: r.id, discard: true });
      if (!res.ok) {
        // Stop at the first failure: finishing the rest blindly would leave
        // the chain half-discarded and the user would not know what remains.
        vscode.window.showErrorMessage(
          `Agency: ${r.id.slice(0, 10)} — ${res.error}. The rest of the team was left alone.`);
        await refresh();
        return;
      }
      log.appendLine(`[cleanup] discarded ${r.id} (chain ${chainId.slice(0, 10)})`);
    }
    await refresh();
  });

  reg('agency.run.discard', async (arg) => {
    const id = runIdOf(arg);
    if (!id) return;
    const r = (state.snapshot.runs || []).find((x) => x.id === id) || {};
    const decided = Math.max((r.findings || 0) - (r.undecided || 0), 0);
    if (decided) {
      vscode.window.showWarningMessage(
        `Agency: ${r.targetLabel || id.slice(0, 10)} carries ${decided} decision(s) — `
        + 'discarding it would take the numbers with it. Close the run instead.');
      return;
    }
    const yes = await vscode.window.showWarningMessage(
      `Discard ${r.targetLabel || id.slice(0, 10)}?`,
      { modal: true,
        detail: `The run record, its evidence and ${r.findings || 0} finding(s) are `
          + 'deleted from the project. Closing the run instead keeps the record and '
          + 'still frees the worktree.' },
      'Discard');
    if (yes !== 'Discard') return;
    const res = await cli.cleanup(state.snapshot.cwd, { run: id, discard: true });
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    log.appendLine(`[cleanup] discarded ${id}`);
    await refresh();
  });

  reg('agency.doctor', async () => {
    const checks = await cli.doctor(state.snapshot.cwd);
    showPanel('doctor', 'Agency — prerequisites', panel.doctorHtml(checks));
  });

  reg('agency.metrics', async () => {
    const m = await cli.metrics(state.snapshot.cwd);
    showPanel('metrics', 'Agency — metrics', panel.metricsHtml(m));
  });

  reg('agency.openSettings', () =>
    vscode.commands.executeCommand('workbench.action.openSettings', 'agency'));

  reg('agency.view.findings.focus', () =>
    vscode.commands.executeCommand('agency.findings.focus'));

  reg('agency.view.tools.focus', () =>
    vscode.commands.executeCommand('agency.tools.focus'));

  // One specialist, started from its own row in the Specialists view.
  reg('agency.pack.run', async (arg) => {
    if (!state.snapshot.probe.ok) return showNotReady();
    const name = packNameOf(arg);
    const p = (state.snapshot.packs || []).find((x) => x.name === name);
    if (!p) return;
    const d = (p.run && p.run.target === 'workspace')
      ? await review.runOverWorkspace(state.snapshot.cwd, p, log)
      : await runOneOverPr(p);
    if (d) setTimeout(() => refresh(), 2000);
  });

  // --- findings
  reg('agency.finding.open', (arg) => {
    const id = typeof arg === 'string' ? arg : findingIdOf(arg);
    if (id) openFinding(id);
  });
  reg('agency.finding.reveal', (arg) => {
    const id = typeof arg === 'string' ? arg : findingIdOf(arg);
    if (id) revealFinding(id);
  });
  reg('agency.finding.accept', (arg) => withFinding(arg, (id, note) =>
    decide(id, 'accept', { note })));
  reg('agency.finding.defer', (arg) => withFinding(arg, (id, note) =>
    decide(id, 'defer', { note })));
  for (const [reason] of panel.REASONS) {
    reg(`agency.finding.reject.${reason}`, (arg) => withFinding(arg, (id, note) =>
      decide(id, 'reject', { reason, note })));
  }
  reg('agency.finding.rejectPick', async (arg) => {
    const id = findingIdOf(arg) || (typeof arg === 'string' ? arg : null);
    if (!id) return;
    const typed = replyTextOf(arg);
    const pick = await vscode.window.showQuickPick(
      panel.REASONS.map(([value, label]) => ({ label, detail: value, value })),
      { title: 'Reason for rejection', placeHolder: 'An enum, not free text — precision is computed from it' });
    if (!pick) return;
    decide(id, 'reject', { reason: pick.value, note: typed || undefined });
  });
  reg('agency.finding.addNote', (arg) => {
    const id = findingIdOf(arg);
    const text = replyTextOf(arg);
    if (id) addNote(id, text);
  });
  reg('agency.finding.openAtCommit', (arg) => {
    const id = findingIdOf(arg) || (typeof arg === 'string' ? arg : null);
    if (id) revealFinding(id, 'at-commit');
  });
  reg('agency.finding.diffAgainstHead', (arg) => {
    const id = findingIdOf(arg) || (typeof arg === 'string' ? arg : null);
    if (id) diffFinding(id);
  });

  // A programmatic path for anything inside the extension host. An agent
  // outside VS Code calls `agency triage` — both end up in the same store.
  reg('agency.decision.apply', (p) => {
    if (!p || !p.findingId || !p.action) {
      throw new Error('agency.decision.apply expects { findingId, action, reason?, note? }');
    }
    return decide(p.findingId, p.action, p);
  });

  // --- watching for outside changes. A write from the terminal or from an
  //     agent must show up in the UI without a reload; it is also the most
  //     honest proof that the extension does not own decisions.
  if (vscode.workspace.getConfiguration('agency').get('autoRefresh') !== false) {
    const watcher = vscode.workspace.createFileSystemWatcher('**/.agency/runs/**');
    let debounce = null;
    const bump = () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        log.appendLine('[watch] .agency changed — reloading');
        refresh({ light: true });
      }, 400);
    };
    watcher.onDidChange(bump); watcher.onDidCreate(bump); watcher.onDidDelete(bump);
    context.subscriptions.push(watcher, { dispose: () => clearTimeout(debounce) });
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => refresh()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('agency')) refresh();
    }));

  refresh().then(() => {
    const s = state.snapshot;
    log.appendLine(`[activation] ${s.findings.length} findings, ${s.runs.length} runs, `
      + `CLI ${s.probe.ok ? 'ok' : s.probe.reason}`);
  }).catch((e) => {
    log.appendLine(`[activation] failed: ${e && e.stack}`);
    vscode.window.showErrorMessage(`Agency: ${e && e.message} — details in Output → Agency.`);
  });
}

// ---------------------------------------------------------------- helpers

// A command reached from a tree row is handed the NODE, not a name.
//
// Everything under `view/item/context` in package.json goes through these.
// Without them the node object reaches the CLI, `execFile` stringifies it,
// and the run dies on `Unknown pack "[object Object]"` — an error that says
// nothing about where it came from.

/** Name of the pack behind a command argument. */
function packNameOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;
  if (!id) return null;
  return String(id).startsWith('pack:') ? String(id).slice(5) : null;
}

/**
 * One specialist over a pull request, started from the Specialists view.
 *
 * It goes through the same picker and the same `runEach` as the button
 * does — a second path that assembled the run itself would be a second
 * place where a model could be chosen, and the run record would then be
 * lying about one of them.
 */
async function runOneOverPr(pack) {
  const prs = await cli.prs(state.snapshot.cwd, { state: 'all', limit: 30 });
  if (!prs.length) {
    vscode.window.showWarningMessage(
      'Agency: no pull requests. Check `gh auth status` and that this repo has a remote.');
    return null;
  }
  const picked = await vscode.window.showQuickPick(review.items(prs), {
    title: `${pack.title || pack.name} — which pull request?`,
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!picked || !picked.pr) return null;
  return review.runEach(state.snapshot.cwd, [pack],
    { pr: picked.pr.number, force: picked.pr.reviewed || undefined }, null);
}

/** Id of a run out of a tree item or a plain string. */
function runIdOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;         // node id: "run:<id>"
  if (id && String(id).startsWith('run:')) return String(id).slice(4);
  return null;
}

function chainIdOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;         // node id: "chain:<id>"
  if (id && String(id).startsWith('chain:')) return String(id).slice(6);
  return null;
}

function findingIdOf(arg) {
  const t = threadOf(arg);
  return t && t._agency ? t._agency.finding.id : null;
}

/** An action from a thread: finding id + the reply box text, when one just arrived. */
function withFinding(arg, fn) {
  const id = findingIdOf(arg) || (typeof arg === 'string' ? arg : null);
  if (!id) return;
  return fn(id, replyTextOf(arg) || undefined);
}

async function pickRun(title) {
  const runs = state.snapshot.runs || [];
  if (!runs.length) {
    vscode.window.showWarningMessage('Agency: no run yet.');
    return undefined;
  }
  if (runs.length === 1) return runs[0].id;
  const pick = await vscode.window.showQuickPick(
    runs.map((r) => ({
      label: r.targetLabel || r.id.slice(0, 10),
      description: `${r.findings} findings · ${r.status}`,
      detail: `${views.ago(r.startedAt)} · ${r.id}`,
      id: r.id,
    })), { title });
  return pick ? pick.id : undefined;
}

function showNotReady() {
  const s = state.snapshot.probe;
  if (s.reason === 'no-cli') {
    vscode.window.showErrorMessage(
      `Agency: \`${cli.bin()}\` is not on PATH.`,
      'How to install', 'Settings',
    ).then((a) => {
      if (a === 'Settings') vscode.commands.executeCommand('agency.openSettings');
      if (a === 'How to install') {
        vscode.window.showInformationMessage(
          'uv tool install --editable <veriflow-agency>/packages/core');
      }
    });
    return;
  }
  vscode.window.showErrorMessage(`Agency: ${s.error || 'not ready'}`);
}

function deactivate() {
  if (threads) threads.clear();
}

module.exports = { activate, deactivate };
