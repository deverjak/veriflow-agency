// Agency — aktivace a zapojení.
//
// Tenhle soubor NEMÁ obsahovat logiku. Je to jen místo, kde se potkají:
//
//   cli.js      volání `agency` — jediná cesta k datům
//   state.js    jeden snímek, ze kterého čtou všechny pohledy
//   views.js    čtyři stromy v postranním panelu
//   panel.js    detail nálezu, metriky a předpoklady v editoru
//   threads.js  nálezy jako inline komentáře u řádku
//   review.js   výběr cíle (PR nebo zadání) a spuštění agenta
//   git.js      kód v den analýzy (`agency:` scheme)
//
// Hranice, která to celé drží: extension je viewer a zadavatel příkazů, nikdy
// vlastník stavu. Rozhodnutí vzniká v `.agency/runs/<id>/decisions.jsonl` a
// zapisuje ho `agency triage` — ať už ho zavolá klik tady, terminál, nebo agent.

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
/** Panely v editoru — jeden na druh, aby se tab neklonoval při každém kliknutí. */
const panels = new Map();
const trees = {};

// ---------------------------------------------------------------- panely

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

// ------------------------------------------------------------ rozhodnutí

/**
 * JEDINÁ cesta, jak uvnitř extension vzniká rozhodnutí. Jde přes `agency triage`,
 * tedy tutéž vrstvu, kterou volá agent — kdyby to byl příkaz editoru, agent by
 * triage neuměl a nebyl by rovnocenný klient.
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
  // Plné načtení, ne light: rozhodnutím se mění i precision v přehledu.
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

// -------------------------------------------------------------- navigace

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

// ------------------------------------------------------------- překreslení

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
  // Kontext řídí, která uvítací obrazovka se ukáže. Prázdný panel bez
  // vysvětlení je nejhorší stav, ve kterém nástroj může být — uživatel nepozná,
  // jestli nic nenašel, nebo jestli se něco nespustilo.
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

// ------------------------------------------------------------------ aktivace

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

  // Odznak s počtem čekajících nálezů. Zácpa musí být vidět bez rozkliknutí —
  // je to prokazatelně nejdražší místo celého systému.
  state.onDidChange(() => {
    const q = state.queue().length;
    findingsView.badge = q
      ? { value: q, tooltip: `${q} findings waiting for a decision` } : undefined;
  });

  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  context.subscriptions.push(status);

  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  // --- hlavní akce
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

  // QA a další packy, které pracují nad projektem, ne nad pull requestem.
  // Příkaz je jeden a obecný — co se pouští, rozhoduje běhová politika packu.
  reg('agency.qa.run', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) return showNotReady();

    const packs = review.workspacePacks();
    if (!packs.length) {
      const hire = await vscode.window.showInformationMessage(
        'Agency: no specialist that works over the running project is hired here yet.',
        'Hire the QA engineer');
      if (hire) await vscode.commands.executeCommand('agency.pack.add');
      return;
    }
    let pack = packs[0].name;
    if (packs.length > 1) {
      const pick = await vscode.window.showQuickPick(
        packs.map((x) => ({ label: x.title || x.name, detail: x.description, pack: x.name })),
        { title: 'Which specialist should run?' });
      if (!pick) return;
      pack = pick.pack;
    }
    const d = await review.runOverWorkspace(state.snapshot.cwd, pack, log);
    if (d) setTimeout(() => refresh(), 2000);
  });

  // Nastavení prohlížeče pro QA. Formulář, protože tohle je jediné místo, kde
  // uživatel mění chování běhu a nemá důvod znát jména klíčů v konfiguraci.
  reg('agency.qa.playwright', async (packName) => {
    if (!state.snapshot.probe.ok) return showNotReady();
    const pack = packName || pickBrowserPack();
    if (!pack) {
      vscode.window.showWarningMessage(
        'Agency: no installed specialist drives a browser — hire the QA engineer first.');
      return;
    }
    const res = await cli.packConfig(state.snapshot.cwd, pack);
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    const render = (data) => showPanel(`playwright:${pack}`, `${pack} — browser`,
      panel.playwrightHtml({ pack, config: data.config, detected: data.detected }),
      async (msg) => {
        if (msg.cmd === 'open') {
          await vscode.commands.executeCommand('agency.pack.openConfig', pack);
          return;
        }
        if (msg.cmd !== 'save') return;
        const saved = await cli.setConfig(state.snapshot.cwd, pack, msg.values);
        if (!saved.ok) {
          vscode.window.showErrorMessage(`Agency: ${saved.error}`);
          return;
        }
        log.appendLine(`[config] ${pack}: ${(saved.data.changed || []).join(', ')}`);
        const p = panels.get(`playwright:${pack}`);
        if (p) p.webview.postMessage({ saved: 'saved to .agency/' + pack + '.json' });
        await refresh();
      });
    render(res.data);
  });

  // Trvalé zadání packu. Žije v konfiguraci projektu, takže platí i pro běh
  // z terminálu a pro agenta — editor je jen jedno ze tří míst, odkud se mění.
  reg('agency.pack.brief', async (packName) => {
    const withBrief = (state.snapshot.packs || []).filter(
      (p) => p.installed && p.run && p.run.prompt && p.run.prompt.accepts);
    let pack = packName;
    if (!pack) {
      if (!withBrief.length) {
        vscode.window.showWarningMessage('Agency: no installed specialist takes a brief.');
        return;
      }
      if (withBrief.length === 1) pack = withBrief[0].name;
      else {
        const pick = await vscode.window.showQuickPick(
          withBrief.map((x) => ({
            label: x.title || x.name,
            detail: (x.brief && x.brief.standing) || 'no standing brief yet',
            pack: x.name,
          })), { title: 'Whose standing brief should be changed?' });
        if (!pick) return;
        pack = pick.pack;
      }
    }
    const info = (state.snapshot.packs || []).find((x) => x.name === pack) || {};
    const current = (info.brief && info.brief.standing) || '';
    const text = await vscode.window.showInputBox({
      title: `Standing brief — ${pack}`,
      value: current,
      prompt: 'Applies to every run of this specialist on this project. A one-off '
        + 'assignment belongs in the run itself, not here.',
      ignoreFocusOut: true,
    });
    if (text === undefined) return;
    const res = await cli.brief(state.snapshot.cwd, pack, { set: text.trim() });
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    log.appendLine(`[brief] ${pack} standing brief updated`);
    await refresh();
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

  reg('agency.pack.add', async () => {
    const available = (state.snapshot.packs || []).filter((p) => !p.installed);
    const list = available.length ? available : state.snapshot.packs || [];
    const pick = await vscode.window.showQuickPick(
      list.map((p) => ({ label: p.title || p.name, detail: p.description, pack: p.name })),
      { title: 'Which specialist should be hired?' });
    if (!pick) return;
    const res = await cli.addPack(state.snapshot.cwd, pick.pack);
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    vscode.window.showInformationMessage(`Agency: ${pick.pack} installed.`);
    await refresh();
  });

  reg('agency.pack.openConfig', async (packName) => {
    const p = path.join(state.snapshot.cwd, '.agency', `${packName}.json`);
    if (!fs.existsSync(p)) {
      vscode.window.showWarningMessage(`There is no ${packName} configuration yet — install the pack.`);
      return;
    }
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(p));
  });

  // --- nálezy
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

  // Programatická cesta pro cokoli uvnitř extension hostu. Agent mimo VS Code
  // volá `agency triage` — obojí končí ve stejném úložišti.
  reg('agency.decision.apply', (p) => {
    if (!p || !p.findingId || !p.action) {
      throw new Error('agency.decision.apply expects { findingId, action, reason?, note? }');
    }
    return decide(p.findingId, p.action, p);
  });

  // --- sledování změn zvenčí. Zápis z terminálu nebo od agenta se musí
  //     projevit v UI bez reloadu; je to zároveň jediný poctivý důkaz, že
  //     vlastníkem rozhodnutí není extension.
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

// ---------------------------------------------------------------- pomocníci

/** Který pack má v konfiguraci prohlížeč. Jméno packu se nikde nehádá. */
function pickBrowserPack() {
  const withBrowser = (state.snapshot.packs || []).filter((p) => p.installed && p.playwright);
  return withBrowser.length ? withBrowser[0].name : null;
}

function findingIdOf(arg) {
  const t = threadOf(arg);
  return t && t._agency ? t._agency.finding.id : null;
}

/** Akce z vlákna: id nálezu + text z pole odpovědi, když zrovna dorazil. */
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
