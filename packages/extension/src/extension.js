// Agency — aktivace a zapojení.
//
// Tenhle soubor NEMÁ obsahovat logiku. Je to jen místo, kde se potkají:
//
//   cli.js      volání `agency` — jediná cesta k datům
//   state.js    jeden snímek, ze kterého čtou všechny pohledy
//   views.js    čtyři stromy v postranním panelu
//   panel.js    detail nálezu, metriky a předpoklady v editoru
//   threads.js  nálezy jako inline komentáře u řádku
//   review.js   výběr PR a spuštění agenta
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
  showPanel(`finding:${findingId}`, f.title || 'Nález', panel.findingHtml(f), async (msg) => {
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
    log.appendLine(`[rozhodnutí] ODMÍTNUTO ${findingId}: ${res.error}`);
    return null;
  }
  log.appendLine(`[rozhodnutí] ${findingId} → ${action}`
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
    vscode.window.showWarningMessage('Poznámka je prázdná — napiš text a ulož znovu.');
    return;
  }
  const res = await cli.note(state.snapshot.cwd, findingId, text.trim());
  if (!res.ok) {
    vscode.window.showErrorMessage(`Agency: ${res.error}`);
    return;
  }
  log.appendLine(`[poznámka] ${findingId}: ${text.trim()}`);
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
      `„${f.title}" nejde umístit — ${(resolved.note || 'soubor ani commit nejsou k dispozici')}. `
      + 'Tělo funkce v den analýzy je uložené v detailu nálezu.');
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
    vscode.window.showWarningMessage('Soubor v pracovní kopii neexistuje — porovnávat není s čím.');
    return;
  }
  await vscode.commands.executeCommand('vscode.diff',
    gitx.commitUri(repo, a.commit, a.file), right,
    `${path.basename(a.file)} — ${String(a.commit).slice(0, 8)} ↔ pracovní kopie`);
}

// ------------------------------------------------------------- překreslení

function updateStatusBar() {
  const s = state.snapshot;
  if (!status) return;
  if (!s.probe.ok) {
    status.text = '$(tools) Agency';
    status.tooltip = s.probe.error || 'Agency není připravená';
  } else {
    const q = state.queue().length;
    status.text = q ? `$(inbox) Agency: ${q}` : '$(check-all) Agency';
    status.tooltip = q
      ? `${q} nálezů čeká na rozhodnutí`
      : 'Žádný nález nečeká na rozhodnutí';
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
  log.appendLine(`[aktivace] ${new Date().toISOString()}`);

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
      ? { value: q, tooltip: `${q} nálezů čeká na rozhodnutí` } : undefined;
  });

  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  context.subscriptions.push(status);

  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  // --- hlavní akce
  reg('agency.refresh', () => refresh());

  reg('agency.review.pick', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: otevři nejdřív složku projektu.');
      return;
    }
    if (!state.snapshot.probe.ok) {
      return showNotReady();
    }
    const d = await review.pickAndRun(state.snapshot.cwd, log);
    if (d) setTimeout(() => refresh(), 2000);
  });

  reg('agency.ingest', async () => {
    const runId = await pickRun('Který běh zpracovat?');
    if (runId === undefined) return;
    const res = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'Agency: brána nad výsledkem běhu' },
      () => cli.ingest(state.snapshot.cwd, runId));
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    const c = res.data.counts;
    vscode.window.showInformationMessage(
      `Agency: ${c.raw} zapsáno · ${c.gated} vyřazeno bránou · `
      + `${c.duplicates} duplicit · ${c.kept} k rozhodnutí`);
    await refresh();
  });

  reg('agency.doctor', async () => {
    const checks = await cli.doctor(state.snapshot.cwd);
    showPanel('doctor', 'Agency — předpoklady', panel.doctorHtml(checks));
  });

  reg('agency.metrics', async () => {
    const m = await cli.metrics(state.snapshot.cwd);
    showPanel('metrics', 'Agency — metriky', panel.metricsHtml(m));
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
      { title: 'Kterého specialistu najmout?' });
    if (!pick) return;
    const res = await cli.addPack(state.snapshot.cwd, pick.pack);
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    vscode.window.showInformationMessage(`Agency: ${pick.pack} nainstalován.`);
    await refresh();
  });

  reg('agency.pack.openConfig', async (packName) => {
    const p = path.join(state.snapshot.cwd, '.agency', `${packName}.json`);
    if (!fs.existsSync(p)) {
      vscode.window.showWarningMessage(`Konfigurace ${packName} zatím není — nainstaluj pack.`);
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
      { title: 'Důvod zamítnutí', placeHolder: 'Enum, ne volný text — počítá se z něj precision' });
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
      throw new Error('agency.decision.apply čeká { findingId, action, reason?, note? }');
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
        log.appendLine('[sledování] .agency se změnilo — přenačítám');
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
    log.appendLine(`[aktivace] ${s.findings.length} nálezů, ${s.runs.length} běhů, `
      + `CLI ${s.probe.ok ? 'ok' : s.probe.reason}`);
  }).catch((e) => {
    log.appendLine(`[aktivace] selhalo: ${e && e.stack}`);
    vscode.window.showErrorMessage(`Agency: ${e && e.message} — detail v Output → Agency.`);
  });
}

// ---------------------------------------------------------------- pomocníci

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
    vscode.window.showWarningMessage('Agency: zatím žádný běh.');
    return undefined;
  }
  if (runs.length === 1) return runs[0].id;
  const pick = await vscode.window.showQuickPick(
    runs.map((r) => ({
      label: r.target ? `PR #${r.target}` : r.id.slice(0, 10),
      description: `${r.findings} nálezů · ${r.status}`,
      detail: `${views.ago(r.startedAt)} · ${r.id}`,
      id: r.id,
    })), { title });
  return pick ? pick.id : undefined;
}

function showNotReady() {
  const s = state.snapshot.probe;
  if (s.reason === 'no-cli') {
    vscode.window.showErrorMessage(
      `Agency: \`${cli.bin()}\` není v PATH.`,
      'Jak nainstalovat', 'Nastavení',
    ).then((a) => {
      if (a === 'Nastavení') vscode.commands.executeCommand('agency.openSettings');
      if (a === 'Jak nainstalovat') {
        vscode.window.showInformationMessage(
          'uv tool install --editable <veriflow-agency>/packages/core');
      }
    });
    return;
  }
  vscode.window.showErrorMessage(`Agency: ${s.error || 'nepřipraveno'}`);
}

function deactivate() {
  if (threads) threads.clear();
}

module.exports = { activate, deactivate };
