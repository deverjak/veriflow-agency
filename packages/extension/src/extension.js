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

  // Tým: specialisté za sebou, každý soudí, co našel předchozí. Orchestruje
  // pořád CLI — `agency chain` si běhy pouští sám, takže tady se jen skládá
  // příkaz do terminálu. Orchestrace v JS by byla druhé místo, kde vzniká běh.
  reg('agency.chain.run', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) return showNotReady();

    const team = await review.pickAndChain(state.snapshot.cwd, log);
    // Delší prodleva než u jednoho běhu: chain nevrátí nic, dokud nedoběhne
    // první člen, a než se objeví, nemá se co obnovovat.
    if (team) setTimeout(() => refresh(), 5000);
  });

  // QA a další packy, které pracují nad projektem, ne nad pull requestem.
  // Příkaz je jeden a obecný — co se pouští, rozhoduje běhová politika packu.
  reg('agency.qa.run', async () => {
    if (!state.snapshot.cwd) {
      vscode.window.showWarningMessage('Agency: open a project folder first.');
      return;
    }
    if (!state.snapshot.probe.ok) return showNotReady();

    if (!review.workspaceHires().length) {
      const hire = await vscode.window.showInformationMessage(
        'Agency: no specialist that works over the running project is hired here yet.',
        'Hire the QA engineer');
      if (hire) await vscode.commands.executeCommand('agency.hire.add');
      return;
    }
    // Which worker takes it is asked inside — a method hired on two providers
    // gives two candidates, and picking between them is the same question here
    // as it is for a review.
    const d = await review.runOverWorkspace(state.snapshot.cwd, null, log);
    if (d) setTimeout(() => refresh(), 2000);
  });

  // Nastavení prohlížeče pro QA. Formulář, protože tohle je jediné místo, kde
  // uživatel mění chování běhu a nemá důvod znát jména klíčů v konfiguraci.
  reg('agency.qa.playwright', async (arg) => {
    if (!state.snapshot.probe.ok) return showNotReady();
    const pack = packNameOf(arg) || pickBrowserPack();
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
  reg('agency.pack.brief', async (arg) => {
    const withBrief = (state.snapshot.packs || []).filter(
      (p) => p.installed && p.run && p.run.prompt && p.run.prompt.accepts);
    let pack = packNameOf(arg);
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

  reg('agency.run.discard', async (arg) => {
    const id = runIdOf(arg);
    if (!id) return;
    const r = (state.snapshot.runs || []).find((x) => x.id === id) || {};
    const decided = Math.max((r.findings || 0) - (r.undecided || 0), 0);
    if (decided) {
      // A decision is work somebody did, and the precision numbers are computed
      // from it. Losing that silently would corrupt the one measurement this
      // whole tool exists to produce.
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

  // Hiring is method + runner, asked in that order.
  //
  // Two questions rather than one, because they are answered from different
  // knowledge: which method you want is about the work, which runner you want
  // is about what is installed on this machine. Hiring the same method a second
  // time on another provider is the same command with a different second answer.
  reg('agency.hire.add', async (arg) => {
    if (!state.snapshot.probe.ok) return showNotReady();
    const packs = state.snapshot.packs || [];
    let pack = packNameOf(arg);

    if (!pack) {
      const pick = await vscode.window.showQuickPick(
        packs.map((p) => {
          const mine = state.hiresOf(p.name);
          return {
            label: p.title || p.name,
            description: mine.length
              ? `already hired: ${mine.map((h) => h.label).join(', ')}` : undefined,
            detail: p.description,
            pack: p.name,
          };
        }),
        { title: 'Which method should be hired?', matchOnDetail: true });
      if (!pick) return;
      pack = pick.pack;
    }

    const taken = new Set(state.hiresOf(pack).map((h) => `${h.provider}/${h.model || ''}`));
    const runners = (state.snapshot.providers || []);
    const chosen = await vscode.window.showQuickPick(
      runners.map((p) => ({
        label: `${p.installed ? '$(rocket)' : '$(warning)'} ${p.title}`,
        description: p.installed ? p.id : `${p.id} — \`${p.bin}\` is not on PATH`,
        detail: p.models && p.models.length ? p.models.join(' · ') : undefined,
        provider: p,
      })).concat([
        { label: '', kind: vscode.QuickPickItemKind.Separator },
        { label: '$(add) Register another runner…', fresh: true },
      ]),
      {
        title: `Hire ${pack} — which runner does the work?`,
        placeHolder: 'Hiring the same method on a second runner gives you two opinions '
          + 'on the same code',
        matchOnDescription: true,
      });
    if (!chosen) return;
    if (chosen.fresh) {
      await vscode.commands.executeCommand('agency.provider.add');
      return;
    }

    // Only offer models the runner declares. An empty list means the runner
    // never told us any, and guessing a name here would produce a launch flag
    // that fails on the first run.
    let model;
    const models = chosen.provider.models || [];
    if (models.length) {
      const pickModel = await vscode.window.showQuickPick(
        models.map((m) => ({ label: m, model: m, description: taken.has(
          `${chosen.provider.id}/${m}`) ? 'already hired' : undefined }))
          .concat([{ label: '$(circle-slash) provider default', model: null }]),
        { title: `Hire ${pack} on ${chosen.provider.id} — which model?` });
      if (!pickModel) return;
      model = pickModel.model || undefined;
    }

    const res = await cli.hire(state.snapshot.cwd, pack, {
      provider: chosen.provider.id, model,
    });
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    const made = res.data && res.data.hire;
    log.appendLine(`[hire] ${made ? made.id : pack}`);
    vscode.window.showInformationMessage(
      made ? `Agency: hired ${made.id}.` : `Agency: ${pack} installed.`);
    await refresh();
  });

  // Kept under the old id so existing keybindings and the welcome screens
  // still work — hiring is what "add a specialist" always meant.
  reg('agency.pack.add', (arg) =>
    vscode.commands.executeCommand('agency.hire.add', packNameOf(arg) || undefined));

  reg('agency.hire.remove', async (arg) => {
    const id = hireIdOf(arg);
    if (!id) return;
    const h = (state.snapshot.hires || []).find((x) => x.id === id);
    if (h && h.implicit) {
      vscode.window.showWarningMessage(
        `Agency: ${id} is the default worker of the ${h.pack} method, taken from its `
        + 'configuration — there is no roster entry to dismiss.');
      return;
    }
    const yes = await vscode.window.showWarningMessage(
      `Dismiss ${id}?`,
      { modal: true, detail: 'The method, its configuration and every past run stay. '
        + 'Findings this specialist produced keep counting towards the metrics.' },
      'Dismiss');
    if (yes !== 'Dismiss') return;
    const res = await cli.fire(state.snapshot.cwd, id);
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    log.appendLine(`[hire] fired ${id}`);
    await refresh();
  });

  reg('agency.hire.run', async (arg) => {
    if (!state.snapshot.probe.ok) return showNotReady();
    const id = hireIdOf(arg);
    const h = (state.snapshot.hires || []).find((x) => x.id === id);
    if (!h) return;
    if (!h.available) {
      vscode.window.showErrorMessage(
        `Agency: \`${h.bin}\` is not on PATH — ${h.id} cannot run on this machine.`);
      return;
    }
    // The worker is already decided — this command IS their row. Only the
    // target is still open, so that is the only thing either branch asks about.
    const pack = state.packOf(h);
    const d = (pack && pack.run && pack.run.target === 'workspace')
      ? await review.runOverWorkspace(state.snapshot.cwd, h, log)
      : await runOneOverPr(h);
    if (d) setTimeout(() => refresh(), 2000);
  });

  // A runner is a property of the machine, so registering one is not a project
  // change: once `grok` is on PATH and registered, it is hireable everywhere.
  reg('agency.provider.add', async () => {
    const id = await vscode.window.showInputBox({
      title: 'Register a runner',
      prompt: 'Its id, e.g. grok. Anything with a command-line agent fits: the id is '
        + 'the name, the command is what actually runs.',
      placeHolder: 'grok',
      ignoreFocusOut: true,
    });
    if (!id || !id.trim()) return;
    const bin = await vscode.window.showInputBox({
      title: `Register ${id.trim()} — the command to run`,
      value: id.trim(),
      prompt: 'What you would type in a terminal. It has to be on PATH.',
      ignoreFocusOut: true,
    });
    if (bin === undefined) return;
    const models = await vscode.window.showInputBox({
      title: `Register ${id.trim()} — models to offer (optional)`,
      placeHolder: 'fast, heavy',
      prompt: 'Comma-separated. They only fill the picker; leave it empty to always '
        + 'use the runner default.',
      ignoreFocusOut: true,
    });
    if (models === undefined) return;
    const res = await cli.addProvider(state.snapshot.cwd, id.trim(),
      { bin: bin.trim() || id.trim(), models: models.trim() || undefined });
    if (!res.ok) {
      vscode.window.showErrorMessage(`Agency: ${res.error}`);
      return;
    }
    log.appendLine(`[provider] registered ${id.trim()}`);
    await refresh();
    const now = await vscode.window.showInformationMessage(
      `Agency: ${id.trim()} registered.`, 'Hire a specialist on it');
    if (now) await vscode.commands.executeCommand('agency.hire.add');
  });

  reg('agency.pack.openConfig', async (arg) => {
    const packName = packNameOf(arg);
    const p = packName && path.join(state.snapshot.cwd, '.agency', `${packName}.json`);
    if (!p || !fs.existsSync(p)) {
      vscode.window.showWarningMessage(
        `There is no ${packName || 'pack'} configuration yet — hire a specialist for it first.`);
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

// A command reached from a tree row is handed the NODE, not a name.
//
// Everything under `view/item/context` in package.json goes through these two.
// Without them the node object reaches the CLI, `execFile` stringifies it, and
// the run dies on `Unknown pack "[object Object]"` — an error that says nothing
// about where it came from.

/** Id of a hire out of a tree item, a plain string, or the run picker. */
function hireIdOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;         // node id: "hire:<id>"
  if (id && String(id).startsWith('hire:')) return String(id).slice(5);
  return null;
}

/**
 * Name of the pack behind a command argument.
 *
 * A hire row resolves to the method it follows: brief, browser and
 * configuration belong to the method, so acting on them from a worker's row is
 * the same act as from the method's own.
 */
function packNameOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;
  if (!id) return null;
  if (String(id).startsWith('pack:')) return String(id).slice(5);
  if (String(id).startsWith('hire:')) {
    const h = (state.snapshot.hires || []).find((x) => x.id === String(id).slice(5));
    return h ? h.pack : null;
  }
  return null;
}

/**
 * One worker over a pull request, started from the Specialists view.
 *
 * It goes through the same picker and the same `runEach` as the button does —
 * a second path that assembled the run itself would be a second place where a
 * model could be chosen, and the run record would then be lying about one of them.
 */
async function runOneOverPr(hire) {
  const prs = await cli.prs(state.snapshot.cwd, { state: 'all', limit: 30 });
  if (!prs.length) {
    vscode.window.showWarningMessage(
      'Agency: no pull requests. Check `gh auth status` and that this repo has a remote.');
    return null;
  }
  const picked = await vscode.window.showQuickPick(review.items(prs), {
    title: `${hire.display} — which pull request?`,
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!picked || !picked.pr) return null;
  return review.runEach(state.snapshot.cwd, [hire],
    { pr: picked.pr.number, force: picked.pr.reviewed || undefined }, log);
}

/** Který pack má v konfiguraci prohlížeč. Jméno packu se nikde nehádá. */
function pickBrowserPack() {
  const withBrowser = (state.snapshot.packs || []).filter((p) => p.installed && p.playwright);
  return withBrowser.length ? withBrowser[0].name : null;
}

/** Id of a run out of a tree item or a plain string. */
function runIdOf(arg) {
  if (typeof arg === 'string') return arg;
  const id = arg && arg.item && arg.item.id;         // node id: "run:<id>"
  if (id && String(id).startsWith('run:')) return String(id).slice(4);
  return null;
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
