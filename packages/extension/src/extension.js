// Agency — CommentController spike
//
// Zjišťuje jedinou věc, na které stojí rozhodnutí v docs/ui-surface-decision.md:
// unese VS Code Comments API nález zakotvený na JINÝ commit, než je working tree?
//
// Testuje čtyři případy z reálných dat main-panelu (viz fixtures.json):
//   no-drift      nález z PR #460, soubor se od té doby nezměnil
//   drifted       řádek se posunul 62 -> 47 v souboru s +1012/-865
//   deleted       soubor byl od té doby smazán
//   out-of-bounds číslo řádku je za koncem souboru
//
// Plain JS, nula závislostí, žádný build step — spike má odpovědět dnes, ne být hezký.

const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');
const fs = require('fs');
const store = require('./store.js');

const SCHEME = 'agency';
const CONTROLLER_ID = 'agency.findings';

/** @type {vscode.CommentController} */
let controller;
/** @type {vscode.CommentThread[]} */
let threads = [];
/** @type {vscode.OutputChannel} */
let log;
/** @type {vscode.StatusBarItem} */
let status;
/** poslední výsledek buildThreads(), krmí strom v sidebaru */
let lastResults = [];
/** Rozhodnutí NEDRŽÍ extension. Vlastníkem je soubor ve store.js, do kterého
 *  zapisuje i CLI (tools/triage.js) — viz §3.4 plánu. Tohle je jen cache. */
let decisions = new Map();

// ---------------------------------------------------------------- git helpers

function git(repo, args) {
  return new Promise((resolve) => {
    cp.execFile('git', ['-C', repo, ...args], { maxBuffer: 32 * 1024 * 1024, encoding: 'utf8' },
      (err, stdout, stderr) => resolve({ ok: !err, stdout: stdout || '', stderr: stderr || '' }));
  });
}

async function gitShow(repo, commit, relPath) {
  const r = await git(repo, ['show', `${commit}:${relPath}`]);
  return r.ok ? r.stdout : null;
}

async function commitExists(repo, commit) {
  const r = await git(repo, ['cat-file', '-e', `${commit}^{commit}`]);
  return r.ok;
}

/**
 * Test driftu (krok 3, bod 5 plánu): sáhl někdo od analýzy na ten rozsah řádků?
 * Vrací 'untouched' | 'touched' | 'deleted' | 'unknown'.
 */
async function driftCheck(repo, anchor) {
  if (!(await commitExists(repo, anchor.commit))) return 'unknown';
  const abs = path.join(repo, anchor.file);
  if (!fs.existsSync(abs)) return 'deleted';
  const r = await git(repo, ['diff', '-U0', `${anchor.commit}..HEAD`, '--', anchor.file]);
  if (!r.ok) return 'unknown';
  if (!r.stdout.trim()) return 'untouched';
  // hunk hlavička: @@ -staraStart,staryPocet +novyStart,novyPocet @@
  const from = anchor.line;
  const to = anchor.endLine || anchor.line;
  for (const m of r.stdout.matchAll(/^@@ -(\d+)(?:,(\d+))? /gm)) {
    const start = parseInt(m[1], 10);
    const count = m[2] === undefined ? 1 : parseInt(m[2], 10);
    const end = start + Math.max(count, 1) - 1;
    if (start <= to && end >= from) return 'touched';
  }
  return 'untouched';
}

// ------------------------------------------------------- rozlišení kotvy (§3)

/** Nezměnil se ten SOUBOR mezi analyzovaným commitem a HEAD? */
async function fileUnchanged(repo, commit, relPath) {
  const r = await git(repo, ['diff', '--quiet', `${commit}..HEAD`, '--', relPath]);
  return r.ok; // --quiet: exit 0 = beze změny
}

/**
 * Vybere z bloku [line..endLine] nejcharakterističtější řádek — ten nejdelší,
 * který není samá interpunkce. Docblok začíná na `/**`, což je k nalezení k ničemu;
 * jeho třetí řádek už je unikátní věta. Vrací {text, offset} vůči anchor.line.
 */
function distinctiveLine(anchor) {
  const block = String(anchor.body || anchor.snippet || '').split('\n');
  let best = null;
  for (let i = 0; i < block.length; i++) {
    const t = block[i].trim();
    if (t.length < 12) continue;
    if (!/[A-Za-z0-9_]{4}/.test(t)) continue; // samé závorky a hvězdičky nepomůžou
    if (!best || t.length > best.text.length) best = { text: t, offset: i };
  }
  return best;
}

/**
 * Čtyřvrstvá kotva z plánu, krok 3 bod 4. Postupuje shora dolů,
 * zastaví se na první vrstvě, která uspěje.
 */
async function resolveAnchor(repo, anchor) {
  const abs = path.join(repo, anchor.file);
  if (!fs.existsSync(abs)) {
    return { line: null, via: 'none', note: 'soubor v pracovní kopii neexistuje' };
  }
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(abs));

  // 1. přesná shoda — soubor se od analýzy nezměnil, čísla řádků platí doslova.
  //    Pozor: rozhoduje neměnnost SOUBORU, ne to, jestli commit == HEAD.
  //    (Kdyby se testoval celý repozitář, propadne sem i nález na netknutém souboru.)
  if (anchor.commit && await fileUnchanged(repo, anchor.commit, anchor.file)) {
    if (anchor.line <= doc.lineCount) {
      return { line: anchor.line, via: 'exact', note: 'soubor beze změny' };
    }
    return { line: null, via: 'none', note: `řádek ${anchor.line} je za koncem souboru (${doc.lineCount} řádků)` };
  }

  // 2. text — hledá se nejcharakterističtější řádek bloku, ne první řádek kotvy.
  //    Jednořádkový snippet selže na `/**`, `}` a podobné boilerplatu.
  const d = distinctiveLine(anchor);
  if (d) {
    const hits = [];
    for (let i = 0; i < doc.lineCount; i++) {
      if (doc.lineAt(i).text.trim() === d.text) hits.push(i + 1);
    }
    const toAnchor = (found) => Math.max(1, found - d.offset);
    if (hits.length === 1) {
      const line = toAnchor(hits[0]);
      return {
        line,
        via: line === anchor.line ? 'snippet (beze změny)' : 'snippet',
        note: line === anchor.line ? '' : `posun ${anchor.line} → ${line}`,
      };
    }
    if (hits.length > 1) {
      const best = hits.reduce((a, b) =>
        Math.abs(toAnchor(b) - anchor.line) < Math.abs(toAnchor(a) - anchor.line) ? b : a);
      return {
        line: toAnchor(best), via: 'snippet (nejednoznačné)',
        note: `${hits.length} shod, vybrána nejbližší`,
      };
    }
  }

  // 3. symbol — dotaz do code-review-graph. Ve spiku neimplementováno.
  //    V ostrém nástroji sem přijde `code-review-graph query`; je to vrstva,
  //    která přežije refaktor tam, kde text řádku ne.

  // 4. selhání — degraduj, neztrať
  if (anchor.line > doc.lineCount) {
    return { line: null, via: 'none', note: `řádek ${anchor.line} je za koncem souboru (${doc.lineCount} řádků)` };
  }
  return { line: null, via: 'none', note: 'text bloku se v souboru nenašel a symbol se nehledal' };
}

// ------------------------------------------------ virtuální dokument z commitu

class CommitContentProvider {
  /** @param {vscode.Uri} uri agency:/<relPath>?repo=<abs>&commit=<sha> */
  async provideTextDocumentContent(uri) {
    const q = new URLSearchParams(uri.query);
    const repo = q.get('repo');
    const commit = q.get('commit');
    const rel = decodeURIComponent(uri.path.replace(/^\//, ''));
    const content = await gitShow(repo, commit, rel);
    if (content !== null) return content;
    return `// Commit ${String(commit).slice(0, 8)} není v tomhle klonu dostupný.\n` +
      `// Zkus: git fetch origin ${commit}\n` +
      `// Fallback na anchor.body je v ostrém nástroji, spike ho tady jen hlásí.\n`;
  }
}

function commitUri(repo, commit, relPath) {
  return vscode.Uri.from({
    scheme: SCHEME,
    path: '/' + relPath,
    query: `repo=${encodeURIComponent(repo)}&commit=${encodeURIComponent(commit)}`,
  });
}

// ------------------------------------------------------------------- fixtures

function loadFixtures() {
  const p = path.join(__dirname, 'fixtures.json');
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function severityIcon(sev) {
  return sev === 'high' ? '🔴' : sev === 'medium' ? '🟠' : '🟡';
}

// ------------------------------------------------------------------- vlákna

function makeBody(finding, resolution, drift) {
  const a = finding.anchor;
  const md = new vscode.MarkdownString();
  md.supportHtml = false;
  md.isTrusted = true;
  md.appendMarkdown(`**${finding.title}**\n\n`);
  md.appendMarkdown(`---\n\n`);
  md.appendMarkdown(`Nalezeno na \`${a.commit.slice(0, 8)}\` · \`${a.file}:${a.line}\`\n\n`);
  const driftLabel = {
    untouched: '✅ **Kód je od analýzy nezměněný** — nález platí doslova.',
    touched: '⚠️ **Na tenhle kód se od analýzy sáhlo** — může být opravené, podívej se na diff.',
    deleted: '🗑️ **Soubor byl od analýzy smazán.**',
    unknown: '❔ Commit není v klonu, drift se nedá vyhodnotit.',
  }[drift];
  md.appendMarkdown(`${driftLabel}\n\n`);
  md.appendMarkdown(`Kotva: \`${resolution.via}\``);
  if (resolution.note) md.appendMarkdown(` — ${resolution.note}`);
  return md;
}

/**
 * Generace běhu. buildThreads() je asynchronní a dá se spustit dvakrát naráz
 * (aktivace + ruční příkaz). Bez tohohle druhý běh uklidí vlákna prvního,
 * ale ta, co má první rozdělaná, vzniknou až PO úklidu a přežijí jako duplikáty.
 */
let generation = 0;

async function buildThreads() {
  const gen = ++generation;
  clearThreads();
  const fx = loadFixtures();
  const repo = fx.repo;
  const results = [];

  for (const f of fx.findings) {
    const a = f.anchor;
    const drift = await driftCheck(repo, a);
    const resolution = await resolveAnchor(repo, a);

    let placed = 'none';
    let uri = null;
    let line = null;

    // Případ A — vlákno na skutečném souboru v pracovní kopii
    if (resolution.line !== null) {
      uri = vscode.Uri.file(path.join(repo, a.file));
      line = resolution.line;
      placed = 'working-tree';
    } else {
      // Případ B — vlákno na read-only dokumentu z commitu analýzy
      if (await commitExists(repo, a.commit)) {
        const content = await gitShow(repo, a.commit, a.file);
        if (content !== null) {
          const lc = content.split('\n').length;
          if (a.line <= lc) {
            uri = commitUri(repo, a.commit, a.file);
            line = a.line;
            placed = 'at-commit';
          }
        }
      }
    }

    if (gen !== generation) {
      log.appendLine(`[build] generace ${gen} zrušena novějším během ${generation}`);
      return { fx, results, cancelled: true };
    }

    if (uri && line !== null) {
      const doc = await vscode.workspace.openTextDocument(uri);
      if (gen !== generation) return { fx, results, cancelled: true };
      const safeLine = Math.min(Math.max(line, 1), doc.lineCount) - 1;
      const range = new vscode.Range(safeLine, 0, safeLine, 0);
      const thread = controller.createCommentThread(uri, range, [{
        body: makeBody(f, resolution, drift),
        mode: vscode.CommentMode.Preview,
        author: { name: `${severityIcon(f.severity)} review-graph` },
        contextValue: 'agencyFinding',
      }]);
      thread.collapsibleState = vscode.CommentThreadCollapsibleState.Collapsed;
      thread.canReply = true;
      thread.contextValue = 'agencyFinding';
      // vlastní data pro handlery příkazů
      thread._agency = { finding: f, resolution, drift, repo, placed, baseLabel: f.title.slice(0, 70) };
      threads.push(thread);
    }

    results.push({ f, drift, resolution, placed, uri, line });
  }
  lastResults = results;
  if (tree) tree.refresh();
  updateStatus();

  // Pojistka: kdyby se generační kontrola někdy prolomila, ať to není tichý duplikát.
  const seen = new Set();
  for (const t of threads) {
    const key = `${t.uri.toString()}#${t.range.start.line}`;
    if (seen.has(key)) log.appendLine(`[build] POZOR duplicitní vlákno na ${key}`);
    seen.add(key);
  }
  return { fx, results, cancelled: false };
}

function clearThreads() {
  for (const t of threads) { try { t.dispose(); } catch (_) { /* už zaniklo */ } }
  threads = [];
}

// ------------------------------------------------- sidebar (předtest §3 UI)

class FindingsTree {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
  }
  refresh() { this._emitter.fire(); }
  getChildren() {
    return lastResults.map((r, i) => ({ r, i }));
  }
  /** @returns {vscode.TreeItem} */
  getTreeItem(node) {
    const { r } = node;
    const d = decisions.get(r.f.id);
    const item = new vscode.TreeItem(
      `${severityIcon(r.f.severity)} ${r.f.title}`,
      vscode.TreeItemCollapsibleState.None);
    const loc = r.resolution.line !== null
      ? `${path.basename(r.f.anchor.file)}:${r.resolution.line}`
      : `${path.basename(r.f.anchor.file)} — neumístěno`;
    item.description = `${loc} · ${r.placed}`;
    const md = new vscode.MarkdownString();
    md.appendMarkdown(`**${r.f.title}**\n\n`);
    md.appendMarkdown(`- soubor: \`${r.f.anchor.file}\`\n`);
    md.appendMarkdown(`- commit: \`${r.f.anchor.commit.slice(0, 8)}\`, řádek ${r.f.anchor.line}\n`);
    md.appendMarkdown(`- drift: \`${r.drift}\`\n`);
    md.appendMarkdown(`- kotva: \`${r.resolution.via}\`${r.resolution.note ? ' — ' + r.resolution.note : ''}\n`);
    if (d) md.appendMarkdown(`- rozhodnutí: **${d.state}**${d.reason ? ' — ' + d.reason : ''}\n`);
    item.tooltip = md;
    item.iconPath = new vscode.ThemeIcon(
      d ? (d.state === 'accepted' ? 'check' : d.state === 'rejected' ? 'x' : 'clock')
        : r.placed === 'none' ? 'warning' : r.drift === 'touched' ? 'git-compare' : 'circle-outline');
    item.command = { command: 'agency.spike.reveal', title: 'Otevřít', arguments: [node.i] };
    return item;
  }
}

/** @type {FindingsTree} */
let tree;

function updateStatus() {
  if (!status) return;
  const placed = lastResults.filter(r => r.placed !== 'none').length;
  status.text = `$(search) Agency: ${placed}/${lastResults.length} nálezů`;
  status.tooltip = 'Agency spike — klikni pro report';
  status.command = 'agency.spike.run';
  status.show();
}

// -------------------------------------------------------------------- report

function verdictLine(ok, text) { return `${ok ? '✅' : '❌'} ${text}`; }

async function runAllChecks() {
  const { fx, results, cancelled } = await buildThreads();
  if (cancelled) {
    vscode.window.showWarningMessage('Agency: běh byl přerušen novějším. Spusť znovu.');
    return results;
  }

  const workingTree = results.filter(r => r.placed === 'working-tree');
  const atCommit = results.filter(r => r.placed === 'at-commit');
  const nowhere = results.filter(r => r.placed === 'none');
  const drifted = results.find(r => r.f.case === 'drifted');
  const deleted = results.find(r => r.f.case === 'deleted');
  const oob = results.find(r => r.f.case === 'out-of-bounds');

  const L = [];
  L.push('# CommentController spike — výsledek');
  L.push('');
  L.push(`Repo: \`${fx.repo}\`  `);
  L.push(`HEAD: \`${fx.head.slice(0, 8)}\`  `);
  L.push(`Nálezů: ${results.length} (5 skutečných z PR #460, 3 zkonstruované hraniční případy)`);
  L.push('');
  L.push('## Verdikt');
  L.push('');
  L.push(verdictLine(workingTree.length > 0,
    `**Případ A — vlákna na pracovní kopii:** ${workingTree.length} z ${results.length}`));
  L.push(verdictLine(atCommit.length > 0,
    `**Případ B — vlákna na read-only dokumentu z commitu:** ${atCommit.length} z ${results.length}`));
  if (drifted) {
    const ok = drifted.resolution.line === (drifted.f.expect && drifted.f.expect.resolvedLine);
    L.push(verdictLine(ok, `**Drift:** očekáván řádek ${drifted.f.expect.resolvedLine}, ` +
      `kotva vrátila ${drifted.resolution.line} přes \`${drifted.resolution.via}\``));
  }
  if (deleted) {
    L.push(verdictLine(deleted.drift === 'deleted' || deleted.placed === 'at-commit',
      `**Smazaný soubor:** drift=\`${deleted.drift}\`, umístění=\`${deleted.placed}\` (degradace, ne pád)`));
  }
  if (oob) {
    L.push(verdictLine(oob.placed !== 'working-tree',
      `**Řádek za koncem souboru:** umístění=\`${oob.placed}\` — nesmí tiše přistát v pracovní kopii`));
  }
  L.push('');
  L.push('## Po nálezech');
  L.push('');
  L.push('| # | případ | drift | kotva | umístěno | řádek |');
  L.push('|---|---|---|---|---|---|');
  for (const r of results) {
    L.push(`| ${r.f.id} | ${r.f.case} | \`${r.drift}\` | \`${r.resolution.via}\` | ` +
      `\`${r.placed}\` | ${r.resolution.line ?? '—'} ${r.resolution.note ? '· ' + r.resolution.note : ''} |`);
  }
  L.push('');
  if (nowhere.length) {
    L.push(`> ${nowhere.length} nález(ů) se nepodařilo umístit nikam. V ostrém nástroji sem patří ` +
      `vrstva 3 (symbol z code-review-graph) a vrstva 4 (\`anchor.body\`).`);
    L.push('');
  }
  L.push('## Co ještě ověřit rukou');
  L.push('');
  L.push('1. Otevři některý ze souborů výše — vlákno musí být vidět u řádku.');
  L.push('2. V hlavičce vlákna musí být čtyři ikony: Přijmout, Odložit, Historie, Porovnat.');
  L.push('3. Napiš do odpovědi text a klikni Zamítnout — důvod se musí dostat do příkazu.');
  L.push('4. Reload okna (`Developer: Reload Window`) — vlákna musí zmizet, ne zdvojit se.');
  L.push('');

  const doc = await vscode.workspace.openTextDocument({ content: L.join('\n'), language: 'markdown' });
  await vscode.window.showTextDocument(doc, { preview: false });

  log.appendLine(L.join('\n'));
  return results;
}

// ------------------------------------------------------------------ aktivace

function threadOf(arg) {
  if (!arg) return null;
  if (arg.thread) return arg.thread;      // CommentReply z comments/commentThread/context
  if (arg.uri && arg.range) return arg;   // CommentThread z comments/commentThread/title
  return null;
}

/** Přečte úložiště a promítne stav do vláken i stromu. Volá se i po zápisu z CLI. */
function refreshDecisions() {
  decisions = store.current();
  for (const t of threads) {
    const m = t._agency;
    if (!m) continue;
    const d = decisions.get(m.finding.id);
    const mark = !d ? '' : d.state === 'accepted' ? '✔ ' : d.state === 'rejected' ? '✘ ' : '⏱ ';
    t.label = mark + m.baseLabel;   // z baseLabel, ne z t.label — jinak se značky hromadí
    t.state = d && d.state === 'accepted'
      ? vscode.CommentThreadState.Resolved
      : vscode.CommentThreadState.Unresolved;
  }
  if (tree) tree.refresh();
}

/**
 * JEDINÁ cesta, jak vzniká rozhodnutí uvnitř extension. Zapisuje do téhož
 * úložiště jako `node tools/triage.js`, takže člověk i agent jsou rovnocenní.
 */
function applyDecision(findingId, state, opts = {}) {
  try {
    const ev = store.append(findingId, state, { ...opts, by: opts.by || 'vscode' });
    log.appendLine(`[rozhodnutí] ${findingId} → ${ev.state}` +
      `${ev.reason ? ' · ' + ev.reason : ''}${ev.note ? ' · ' + ev.note : ''} (${ev.by})`);
    refreshDecisions();
    vscode.window.setStatusBarMessage(`Agency: ${findingId} → ${ev.state}`, 4000);
    return ev;
  } catch (e) {
    vscode.window.showErrorMessage(`Agency: ${e.message}`);
    log.appendLine(`[rozhodnutí] ODMÍTNUTO ${findingId}: ${e.message}`);
    return null;
  }
}

function findingIdOf(arg) {
  const t = threadOf(arg);
  return t && t._agency ? t._agency.finding.id : null;
}

/** Text z pole odpovědi. VS Code ho předá jen když je editor odpovědi rozbalený,
 *  takže může chybět — bere se jako bonus, ne jako vstup, na kterém se stojí. */
function replyTextOf(arg) {
  if (!arg || typeof arg.text !== 'string') return null;
  const t = arg.text.trim();
  return t.length ? t : null;
}

const REASON_HINTS = {
  'not-reproducible': 'nepodařilo se zopakovat',
  'by-design': 'chová se tak záměrně',
  'wrong-diagnosis': 'problém existuje, ale příčina je jinde',
  'duplicate-missed': 'duplicita, kterou dedup nechytil',
  'out-of-scope': 'mimo rozsah projektu',
};

function activate(context) {
  log = vscode.window.createOutputChannel('Agency Spike');
  context.subscriptions.push(log);
  log.appendLine(`[aktivace] ${new Date().toISOString()}`);

  controller = vscode.comments.createCommentController(CONTROLLER_ID, 'Agency — nálezy');
  controller.commentingRangeProvider = { provideCommentingRanges: () => [] }; // uživatel nezakládá vlastní
  context.subscriptions.push(controller);

  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(
    SCHEME, new CommitContentProvider()));

  tree = new FindingsTree();
  context.subscriptions.push(vscode.window.registerTreeDataProvider('agency.findings.view', tree));

  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.text = '$(search) Agency: načítám…';
  status.show();
  context.subscriptions.push(status);

  const reg = (id, fn) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg('agency.spike.run', async () => {
    try { await runAllChecks(); }
    catch (e) { vscode.window.showErrorMessage(`Spike spadl: ${e && e.message}`); log.appendLine(String(e && e.stack)); }
  });
  reg('agency.spike.showThreads', async () => {
    const { results } = await buildThreads();
    vscode.window.showInformationMessage(`Agency: ${threads.length} vláken z ${results.length} nálezů.`);
  });
  reg('agency.spike.clear', () => { clearThreads(); vscode.window.showInformationMessage('Agency: vlákna zahozena.'); });

  reg('agency.finding.accept', (arg) => {
    const id = findingIdOf(arg);
    if (id) applyDecision(id, 'accepted', { note: replyTextOf(arg) });
  });
  reg('agency.finding.defer', (arg) => {
    const id = findingIdOf(arg);
    if (id) applyDecision(id, 'deferred', { note: replyTextOf(arg) });
  });

  reg('agency.finding.reject', async (arg) => {
    const id = findingIdOf(arg);
    if (!id) return;
    const typed = replyTextOf(arg);
    log.appendLine(`[reject] arg.text = ${typed === null ? '(nepřišel)' : JSON.stringify(typed)}`);

    // Důvod je enum z baseline.md §7.1, ne volný text — jinak precision nejde spočítat.
    // Text z pole odpovědi se použije jako poznámka, když dorazí; nespoléhá se na něj.
    const pick = await vscode.window.showQuickPick(
      store.REASONS.map(r => ({ label: r, description: REASON_HINTS[r] || '' })),
      { title: `Zamítnout ${id} — důvod`, placeHolder: 'Vyber důvod zamítnutí' });
    if (!pick) return;
    applyDecision(id, 'rejected', { reason: pick.label, note: typed || undefined });
  });

  // Programatická cesta pro cokoli uvnitř extension hostu. Agent mimo VS Code
  // volá `node tools/triage.js` — obojí končí ve stejném úložišti.
  reg('agency.decision.apply', (payload) => {
    if (!payload || !payload.findingId || !payload.state) {
      throw new Error('agency.decision.apply čeká { findingId, state, reason?, note?, by? }');
    }
    return applyDecision(payload.findingId, payload.state, payload);
  });

  reg('agency.finding.openAtCommit', async (arg) => {
    const t = threadOf(arg); const m = t && t._agency; if (!m) return;
    const a = m.finding.anchor;
    const uri = commitUri(m.repo, a.commit, a.file);
    const doc = await vscode.workspace.openTextDocument(uri);
    const ed = await vscode.window.showTextDocument(doc, { preview: true });
    const l = Math.min(a.line, doc.lineCount) - 1;
    ed.revealRange(new vscode.Range(l, 0, l, 0), vscode.TextEditorRevealType.InCenter);
    ed.selection = new vscode.Selection(l, 0, l, 0);
  });

  reg('agency.finding.diffAgainstHead', async (arg) => {
    const t = threadOf(arg); const m = t && t._agency; if (!m) return;
    const a = m.finding.anchor;
    const left = commitUri(m.repo, a.commit, a.file);
    const right = vscode.Uri.file(path.join(m.repo, a.file));
    if (!fs.existsSync(right.fsPath)) {
      vscode.window.showWarningMessage('Soubor v pracovní kopii neexistuje — porovnávat není s čím.');
      return;
    }
    await vscode.commands.executeCommand('vscode.diff', left, right,
      `${path.basename(a.file)} — ${a.commit.slice(0, 8)} ↔ pracovní kopie`);
  });

  reg('agency.spike.reveal', async (idx) => {
    const r = lastResults[idx];
    if (!r) return;
    if (!r.uri || r.line === null) {
      vscode.window.showWarningMessage(
        `„${r.f.title}" se nepodařilo umístit — ${r.resolution.note}`);
      return;
    }
    const doc = await vscode.workspace.openTextDocument(r.uri);
    const ed = await vscode.window.showTextDocument(doc, { preview: false });
    const l = Math.min(Math.max(r.line, 1), doc.lineCount) - 1;
    ed.revealRange(new vscode.Range(l, 0, l, 0), vscode.TextEditorRevealType.InCenter);
    ed.selection = new vscode.Selection(l, 0, l, 0);
  });

  // Úložiště sleduj, ať se zápis z CLI projeví v UI bez reloadu.
  // Tohle je vlastní důkaz, že extension není vlastník rozhodnutí.
  try {
    const dir = path.dirname(store.storePath());
    fs.mkdirSync(dir, { recursive: true });
    let debounce = null;
    const watcher = fs.watch(dir, () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        log.appendLine('[store] změna zvenčí — přenačítám rozhodnutí');
        refreshDecisions();
      }, 120);
    });
    context.subscriptions.push({ dispose: () => { clearTimeout(debounce); watcher.close(); } });
  } catch (e) {
    log.appendLine(`[store] sledování selhalo: ${e && e.message}`);
  }
  refreshDecisions();

  // Vlákna se staví hned po aktivaci — jinak vypadá spike jako by se nenačetl.
  buildThreads().then(({ results }) => {
    log.appendLine(`[aktivace] ${threads.length} vláken z ${results.length} nálezů`);
  }).catch(e => {
    log.appendLine(`[aktivace] selhalo: ${e && e.stack}`);
    if (status) { status.text = '$(error) Agency: chyba'; status.tooltip = String(e && e.message); }
    vscode.window.showErrorMessage(`Agency spike: ${e && e.message} — detail v Output → Agency Spike.`);
  });

  log.appendLine('Agency spike aktivní. Ikona v activity baru vlevo, nebo paleta → „Agency".');
}

function deactivate() { clearThreads(); }

module.exports = { activate, deactivate };

// Vystaveno pro harness v test/ — spike musí jít vyhodnotit i bez spuštěného VS Code.
module.exports._internal = { driftCheck, resolveAnchor, loadFixtures, gitShow, commitExists, git };
