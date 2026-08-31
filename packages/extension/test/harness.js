// Smoke test extension bez spuštěného VS Code.
//
//   node packages/extension/test/harness.js
//
// Ověřuje to, co ověřit lze strojově: že se moduly načtou, že stromy postaví
// z reálného tvaru dat správné uzly a že se do HTML nedostane neescapovaný
// vstup. Renderování vláken a tlačítka chtějí F5 — to tenhle soubor nepředstírá.
//
// Falešný `vscode` je záměrně hloupý. Kdyby se do něj musela dopisovat logika,
// znamenalo by to, že se logika stěhuje z jádra do extension.

const Module = require('module');
const assert = require('assert');
const path = require('path');

// ------------------------------------------------------------- falešný vscode
class EventEmitter {
  constructor() { this.handlers = []; }
  get event() { return (fn) => { this.handlers.push(fn); return { dispose() {} }; }; }
  fire(...a) { this.handlers.forEach((h) => h(...a)); }
}

const fake = {
  EventEmitter,
  ThemeIcon: class { constructor(id, color) { this.id = id; this.color = color; } },
  ThemeColor: class { constructor(id) { this.id = id; } },
  MarkdownString: class {
    constructor(v = '') { this.value = v; }
    appendMarkdown(s) { this.value += s; return this; }
  },
  TreeItem: class {
    constructor(label, collapsibleState) { this.label = label; this.collapsibleState = collapsibleState; }
  },
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
  QuickPickItemKind: { Separator: -1 },
  Uri: {
    file: (p) => ({ scheme: 'file', fsPath: p, path: String(p).replace(/\\/g, '/') }),
    from: (o) => ({ ...o, fsPath: o.path, toString: () => `${o.scheme}:${o.path}?${o.query}` }),
  },
  workspace: {
    workspaceFolders: [{ uri: { fsPath: 'C:/projekt' } }],
    getConfiguration: () => ({ get: (k) => ({ cliPath: 'agency', pack: 'review-graph' }[k]) }),
    registerTextDocumentContentProvider: () => ({ dispose() {} }),
    createFileSystemWatcher: () => ({
      onDidChange() {}, onDidCreate() {}, onDidDelete() {}, dispose() {},
    }),
    onDidChangeWorkspaceFolders: () => ({ dispose() {} }),
    onDidChangeConfiguration: () => ({ dispose() {} }),
  },
  window: {
    createOutputChannel: () => ({ appendLine() {}, dispose() {} }),
    createStatusBarItem: () => ({ show() {}, dispose() {} }),
    createTreeView: () => ({ dispose() {} }),
    registerTreeDataProvider: () => ({ dispose() {} }),
    createWebviewPanel: () => ({ webview: {}, onDidDispose() {}, dispose() {} }),
    showErrorMessage() {}, showWarningMessage() {}, showInformationMessage() {},
    setStatusBarMessage() {}, showTextDocument() {}, showQuickPick() {},
    withProgress: (_o, fn) => fn({ report() {} }),
  },
  commands: { registerCommand: () => ({ dispose() {} }), executeCommand() {} },
  comments: {
    createCommentController: () => ({
      commentingRangeProvider: null, createCommentThread: () => ({}), dispose() {},
    }),
  },
  CommentMode: { Preview: 1 },
  CommentThreadCollapsibleState: { Collapsed: 0, Expanded: 1 },
  CommentThreadState: { Unresolved: 0, Resolved: 1 },
  StatusBarAlignment: { Left: 1 },
  ViewColumn: { Active: -1 },
  ProgressLocation: { Window: 10, Notification: 15 },
  Range: class { constructor(a, b, c, d) { Object.assign(this, { a, b, c, d }); } },
  Selection: class {},
  TextEditorRevealType: { InCenter: 2 },
};

const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === 'vscode') return 'vscode';
  return origResolve.call(this, request, ...rest);
};
require.cache.vscode = { id: 'vscode', filename: 'vscode', loaded: true, exports: fake };

// ------------------------------------------------------------------ vzorek
const SRC = path.join(__dirname, '..', 'src');
const panel = require(path.join(SRC, 'panel.js'));
const views = require(path.join(SRC, 'views.js'));
const state = require(path.join(SRC, 'state.js'));

const FINDING = {
  id: '01M1BTSC00000000000000000A',
  runId: '01M1BT1TX2G11HZ8SQC0FZCDAE',
  pack: 'review-graph@0.1.0',
  dimension: 'correctness',
  severity: 'high',
  title: 'Návrh adresy přežije neúspěšný geokód',
  body: 'Diff zavádí stav `addressSuggestion`.\n\n- první bod\n- druhý bod',
  file: 'src/components/Fields.tsx',
  line: 185,
  anchor: {
    file: 'src/components/Fields.tsx', line: 185, endLine: 190,
    commit: 'f7dd184fd40a159524a55df3ab5e581980c01b33',
    symbol: { name: 'InstructorVenueLocationFields', range: [47, 416] },
    snippet: 'if (generation !== ref.current) return;',
  },
  evidence: [{ kind: 'diff', detail: 'Dva early returny návrh neruší.', source: 'git diff' }],
  drift: 'touched',
  resolved: { line: 170, via: 'snippet', note: 'posun 185 → 170' },
  score: 90,
  state: 'candidate',
  decision: null,
  history: [],
  target: { pr: 467, url: 'https://github.com/x/y/pull/467' },
};

let failed = 0;
function check(name, fn) {
  try { fn(); console.log(`  ok   ${name}`); }
  catch (e) { failed += 1; console.log(`  FAIL ${name}\n       ${e.message}`); }
}

console.log('\nAgency — smoke test extension\n');

check('markdown escapuje HTML ze vstupu', () => {
  const html = panel.md('<img src=x onerror="alert(1)"> a `kód`');
  assert.ok(!html.includes('<img'), 'neescapovaný tag prošel do HTML');
  assert.ok(html.includes('<code>kód</code>'));
});

check('detail nálezu vykreslí tvrzení, evidenci i kotvu', () => {
  const html = panel.findingHtml(FINDING);
  assert.ok(html.includes('Návrh adresy přežije'), 'chybí titulek');
  assert.ok(html.includes('Čím to dokládá'), 'chybí sekce evidence');
  assert.ok(html.includes('early returny'), 'chybí text evidence');
  assert.ok(html.includes('InstructorVenueLocationFields'), 'chybí symbol z kotvy');
  assert.ok(html.includes('185') && html.includes('170'), 'chybí posun kotvy');
  assert.ok(html.includes('Porovnat s dneškem'),
    'u dotčeného nálezu chybí diff — přítomnost toho tlačítka JE signál driftu');
});

check('u nedotčeného nálezu se diff nenabízí', () => {
  const html = panel.findingHtml({ ...FINDING, drift: 'untouched' });
  assert.ok(!html.includes('Porovnat s dneškem'),
    'diff proti pracovní kopii by ukázal tentýž obsah dvakrát');
});

check('detail nálezu má akce rozhodnutí i pole poznámky', () => {
  const html = panel.findingHtml(FINDING);
  for (const cmd of ['accept', 'defer', 'reject', 'note']) {
    assert.ok(html.includes(`data-cmd="${cmd}"`), `chybí akce ${cmd}`);
  }
  assert.ok(html.includes('id="reason"'), 'chybí výběr důvodu zamítnutí');
});

check('metriky bez dat ukážou pomlčku, ne nulu', () => {
  const html = panel.metricsHtml({
    project: { name: 'p' }, runs: 1,
    triage: { accepted: 0, rejected: 0, deferred: 0, undecided: 3, precision: null },
    findings: { raw: 3, kept: 3, duplicates: 0, dedupRatio: null, gateYield: 1, gatedBy: null },
    queue: { undecided: 3, medianAgeDays: 0.1, oldestDays: 0.1 },
    cost: { secondsPerKeptFinding: 276 },
    byDimension: {}, bySeverity: {}, byModel: {}, rejectReasons: null,
  });
  assert.ok(html.includes('—'), 'nula z nuly se vykreslila jako číslo');
});

check('strom nálezů rozdělí frontu, rozhodnuté a duplicity', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt', runs: [], packs: [], project: null, metrics: null,
    findings: [
      FINDING,
      { ...FINDING, id: 'B', decision: 'accepted' },
      { ...FINDING, id: 'C', state: 'duplicate' },
    ],
  });
  const roots = new views.FindingsTree().roots();
  const labels = roots.map((r) => r.item.label);
  assert.deepStrictEqual(labels, ['K rozhodnutí', 'Rozhodnuté', 'Duplicity']);
  assert.strictEqual(roots[0].children.length, 1);
});

check('fronta řadí nedotčené nálezy nahoru', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    findings: [
      { ...FINDING, id: 'A', drift: 'touched', severity: 'high' },
      { ...FINDING, id: 'B', drift: 'untouched', severity: 'medium' },
    ],
  });
  const open = new views.FindingsTree().roots()[0];
  assert.strictEqual(open.children[0].item.id, 'finding:B',
    'nahoře má být nález na kódu, na který se nesáhlo — ten platí doslova');
});

check('přehled ukáže frontu i precision', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt', loadedAt: new Date(),
    project: { slug: 'org/repo' }, doctor: [{ name: 'gh', ok: true, detail: '' }],
    packs: [{ name: 'review-graph', installed: 'review-graph@0.1.0' }],
    runs: [{ id: 'R', target: 467, findings: 3, status: 'ok', startedAt: new Date().toISOString() }],
    findings: [FINDING],
    metrics: { triage: { precision: 0.8, accepted: 4, rejected: 1 } },
  });
  const labels = new views.OverviewTree().roots().map((r) => r.item.label);
  for (const want of ['Projekt', 'Předpoklady', 'Specialisté', 'Poslední běh',
    'Fronta k rozhodnutí', 'Precision']) {
    assert.ok(labels.includes(want), `v přehledu chybí „${want}"`);
  }
});

check('bez CLI se stromy nevykreslí prázdné položky', () => {
  Object.assign(state.snapshot, { probe: { ok: false, reason: 'no-cli' }, findings: [] });
  assert.deepStrictEqual(new views.FindingsTree().roots(), []);
  assert.deepStrictEqual(new views.OverviewTree().roots(), []);
});

check('doctor z CLI chodí jako {checks:[…]}, strom čeká pole', () => {
  // Nesoulad, který by shodil celý Přehled na `.filter is not a function`.
  // Rozbaluje se v cli.js, na jednom místě — proto na to stačí jeden test.
  const cli = require(path.join(SRC, 'cli.js'));
  assert.strictEqual(typeof cli.doctor, 'function');
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt', loadedAt: new Date(),
    project: { slug: 'org/repo' },
    doctor: [{ name: 'gh auth', ok: false, detail: 'nepřihlášen', fatal: true }],
    packs: [], runs: [], findings: [], metrics: null,
  });
  const rows = new views.OverviewTree().roots();
  const req = rows.find((r) => r.item.label === 'Předpoklady');
  assert.strictEqual(req.item.description, '1 problém');
});

console.log(failed ? `\n${failed} selhalo\n` : '\nvšechno prošlo\n');
process.exit(failed ? 1 : 0);
