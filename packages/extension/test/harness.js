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
    createTerminal: () => ({ show() {}, sendText() {}, dispose() {} }),
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

// Spuštění běhu je řetěz promisů. Asynchronní kontroly se posbírají a doběhnou
// až na konci, aby souhrn nevypsal „prošlo" dřív, než se to dozví.
const pending = [];
function checkAsync(name, fn) { pending.push([name, fn]); }

console.log('\nAgency — smoke test extension\n');

check('markdown escapuje HTML ze vstupu', () => {
  const html = panel.md('<img src=x onerror="alert(1)"> a `kód`');
  assert.ok(!html.includes('<img'), 'neescapovaný tag prošel do HTML');
  assert.ok(html.includes('<code>kód</code>'));
});

check('detail nálezu vykreslí tvrzení, evidenci i kotvu', () => {
  const html = panel.findingHtml(FINDING);
  assert.ok(html.includes('Návrh adresy přežije'), 'chybí titulek');
  assert.ok(html.includes('What backs it up'), 'chybí sekce evidence');
  assert.ok(html.includes('early returny'), 'chybí text evidence');
  assert.ok(html.includes('InstructorVenueLocationFields'), 'chybí symbol z kotvy');
  assert.ok(html.includes('185') && html.includes('170'), 'chybí posun kotvy');
  assert.ok(html.includes('Compare with today'),
    'u dotčeného nálezu chybí diff — přítomnost toho tlačítka JE signál driftu');
});

check('u nedotčeného nálezu se diff nenabízí', () => {
  const html = panel.findingHtml({ ...FINDING, drift: 'untouched' });
  assert.ok(!html.includes('Compare with today'),
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
  assert.deepStrictEqual(labels, ['To decide', 'Decided', 'Duplicates']);
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
    runs: [{ id: 'R', target: 467, targetLabel: 'PR #467', findings: 3, status: 'ok', startedAt: new Date().toISOString() }],
    findings: [FINDING],
    metrics: { triage: { precision: 0.8, accepted: 4, rejected: 1 } },
  });
  const labels = new views.OverviewTree().roots().map((r) => r.item.label);
  for (const want of ['Project', 'Prerequisites', 'Specialists', 'Last run',
    'Decision queue', 'Precision']) {
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
  const req = rows.find((r) => r.item.label === 'Prerequisites');
  assert.strictEqual(req.item.description, '1 problem');
});

const QA_PACK = {
  name: 'qa',
  title: 'QA engineer',
  version: '0.1.0',
  description: 'Explores the running application.',
  installed: 'qa@0.1.0',
  run: {
    target: 'workspace',
    worktree: false,
    graph: false,
    prompt: { accepts: true, required: true, label: 'What should be tested?', placeholder: '' },
  },
  agent: { provider: 'claude', model: 'sonnet' },
  brief: {
    standing: 'Rezervační aplikace pro lekce.',
    scenarios: [{ name: 'smoke', text: 'Přihlášení, dashboard, jedna rezervace.' }],
  },
  dimensions: [{ id: 'happy-path', title: 'The main flows do what they promise' }],
};

check('spouštěč pozná pack podle politiky, ne podle jména', () => {
  // Kdyby extension větvila podle jména packu, byl by každý další specialista
  // zásahem do klienta. Rozhoduje `run.target` z manifestu.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [
      QA_PACK,
      { name: 'review-graph', installed: 'review-graph@0.1.0', run: { target: 'pull-request' } },
      { name: 'qa-nenainstalovany', installed: null, run: { target: 'workspace' } },
    ],
  });
  const found = review.workspacePacks().map((p) => p.name);
  assert.deepStrictEqual(found, ['qa'],
    'nabízet se má jen nainstalovaný pack, který pracuje nad projektem');
});

check('specialista nad projektem ukáže zadání i scénáře', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [QA_PACK],
    hires: [{ id: 'qa@claude', pack: 'qa', provider: 'claude', model: 'sonnet',
      label: 'sonnet', display: 'QA engineer · sonnet', bin: 'claude', available: true }],
  });
  const pack = new views.ToolsTree().roots()[0];
  const labels = pack.children.map((c) => c.item.label);
  assert.ok(labels.includes('Brief'), 'chybí uzel se zadáním');
  assert.ok(labels.includes('What it works on'), 'není vidět, nad čím pack pracuje');

  const kde = pack.children.find((c) => c.item.label === 'What it works on');
  assert.strictEqual(kde.item.description, 'the project as it is');
  const brief = pack.children.find((c) => c.item.label === 'Brief');
  assert.ok(String(brief.item.description).startsWith('Rezervační'), 'chybí trvalé zadání');
  assert.strictEqual(brief.children[0].item.label, 'smoke', 'chybí uložený scénář');
  assert.strictEqual(brief.item.command.command, 'agency.pack.brief');
});

check('recenzent bez zadání uzel Brief nemá prázdný, ale má ho', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [{
      name: 'review-graph', title: 'Reviewer', version: '0.1.0', installed: 'review-graph@0.1.0',
      run: { target: 'pull-request', prompt: { accepts: true, required: false } },
      brief: { standing: null, scenarios: [] },
    }],
    hires: [{ id: 'review-graph@claude', pack: 'review-graph', provider: 'claude',
      model: 'sonnet', label: 'sonnet', display: 'Reviewer · sonnet', bin: 'claude',
      available: true }],
  });
  const pack = new views.ToolsTree().roots()[0];
  const brief = pack.children.find((c) => c.item.label === 'Brief');
  assert.strictEqual(brief.item.description, 'not set');
  const kde = pack.children.find((c) => c.item.label === 'What it works on');
  assert.strictEqual(kde.item.description, 'a pull request');
});

check('běh bez pull requestu se nejmenuje holým ULID', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [{
      id: '01M1CGN9HAMBKK63SASPP2EYWJ', pack: 'qa@0.1.0', status: 'ok',
      target: null, targetLabel: 'main', kind: 'workspace',
      brief: 'vyzkoušej rušení rezervace', findings: 1, undecided: 1,
      startedAt: new Date().toISOString(),
    }],
  });
  const run = new views.RunsTree().roots()[0];
  assert.strictEqual(run.item.label, 'main');
  assert.ok(run.item.tooltip.value.includes('over the project as it was'),
    'v tooltipu chybí, že běh jel nad projektem');
  assert.ok(run.item.tooltip.value.includes('rušení rezervace'),
    'v tooltipu chybí zadání, se kterým běh vznikl');
});

check('nastavení prohlížeče je formulář, ne prosba o editaci JSONu', () => {
  const html = panel.playwrightHtml({
    pack: 'qa',
    config: {
      app: { baseUrl: 'http://localhost:3000', startPolicy: 'manual' },
      playwright: {
        enabled: true, configFile: 'playwright.config.ts', projectTestDir: 'e2e',
        specTarget: 'run', scaffold: 'run-dir', browsers: ['chromium', 'webkit'],
        artifacts: { trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'off' },
      },
    },
    detected: { playwright: { present: true, configFile: 'playwright.config.ts', testDir: 'e2e', specs: 4 } },
  });
  assert.ok(html.includes('data-key="playwright.enabled"'), 'chybí přepínač prohlížeče');
  assert.ok(/data-key="playwright.enabled"[^>]*checked/.test(html), 'zapnutý stav se nepropsal');
  assert.ok(html.includes('chromium, webkit'), 'seznam prohlížečů se nevykreslil');
  assert.ok(html.includes('http://localhost:3000'), 'chybí adresa aplikace');
  assert.ok(html.includes('The project already has Playwright'),
    'nalezený Playwright se má oznámit — sezení ho má použít, ne postavit vedle');
  assert.ok(html.includes('data-key="playwright.artifacts.trace"'), 'chybí volba trace');
});

check('bez Playwrightu panel řekne, co se stane místo toho', () => {
  const html = panel.playwrightHtml({
    pack: 'qa', config: { playwright: { enabled: false, scaffold: 'run-dir' } },
    detected: { playwright: { present: false } },
  });
  assert.ok(html.includes('The project has no Playwright'));
  assert.ok(!/data-key="playwright.enabled"[^>]*checked/.test(html));
});

check('specialista s prohlížečem má v pohledu uzel Browser', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [{
      ...QA_PACK,
      playwright: { enabled: true, configFile: 'playwright.config.ts', specTarget: 'run', scaffold: 'run-dir' },
    }],
    hires: [{ id: 'qa@claude', pack: 'qa', provider: 'claude', model: 'sonnet',
      label: 'sonnet', display: 'QA engineer · sonnet', bin: 'claude', available: true }],
  });
  const pack = new views.ToolsTree().roots()[0];
  const browser = pack.children.find((c) => c.item.label === 'Browser');
  assert.ok(browser, 'chybí uzel Browser');
  assert.strictEqual(browser.item.command.command, 'agency.qa.playwright');
  assert.ok(String(browser.item.description).includes('Playwright'));
});

// Product owner je první specialista, který píše VEN. Co smí, se musí dát
// přečíst z jeho řádku — ne až z .agency/po.json, do kterého se nikdo nedívá.
const PO_PACK = {
  name: 'po',
  title: 'Product owner',
  version: '0.1.0',
  description: 'Holds the roadmap against what is actually being built.',
  installed: 'po@0.1.0',
  run: {
    target: 'workspace',
    worktree: false,
    graph: false,
    backlog: true,
    prompt: { accepts: true, required: false, label: '', placeholder: '' },
  },
  agent: { provider: 'claude', model: 'sonnet' },
  brief: { standing: null, scenarios: [] },
  dimensions: [{ id: 'scope', title: 'Work in flight that no commitment covers' }],
};

const PO_HIRE = [{ id: 'po@claude', pack: 'po', provider: 'claude', model: 'sonnet',
  label: 'sonnet', display: 'Product owner · sonnet', bin: 'claude', available: true }];

check('specialista, který píše ven, má na řádku napsáno co smí', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [{
      ...PO_PACK,
      backlog: {
        repo: 'chytre/veriflow', projectNumber: 7, roadmap: 'docs/roadmap.md',
        cycle: '2026-Q3', writes: ['comments', 'draftIssues'], dryRun: false,
      },
    }],
    hires: PO_HIRE,
  });
  const pack = new views.ToolsTree().roots()[0];
  const backlog = pack.children.find((c) => c.item.label === 'Backlog');
  assert.ok(backlog, 'chybí uzel Backlog');
  const popis = String(backlog.item.description);
  assert.ok(popis.includes('board #7'));
  assert.ok(popis.includes('may comments, draftIssues'));
  // Roadmapa je to, proti čemu se rozhoduje — patří vedle, ne dovnitř.
  const roadmap = pack.children.find((c) => c.item.label === 'Roadmap');
  assert.ok(String(roadmap.item.description).includes('2026-Q3'));
});

check('nanečisto se pozná na první pohled, ne až z konfigurace', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [{ ...PO_PACK, backlog: { repo: 'chytre/veriflow', projectNumber: null,
      roadmap: null, cycle: null, writes: ['comments'], dryRun: true } }],
    hires: PO_HIRE,
  });
  const pack = new views.ToolsTree().roots()[0];
  const backlog = pack.children.find((c) => c.item.label === 'Backlog');
  assert.ok(String(backlog.item.description).includes('rehearsal only'));
  // Bez roadmapy se řádek neukazuje prázdný — prostě tam není.
  assert.ok(!pack.children.some((c) => c.item.label === 'Roadmap'));
});

check('specialista, který ven nepíše, uzel Backlog nemá', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [QA_PACK],
    hires: [{ id: 'qa@claude', pack: 'qa', provider: 'claude', model: 'sonnet',
      label: 'sonnet', display: 'QA engineer · sonnet', bin: 'claude', available: true }],
  });
  const pack = new views.ToolsTree().roots()[0];
  assert.ok(!pack.children.some((c) => c.item.label === 'Backlog'));
});

// ------------------------------------------------------------------- roster
//
// A method can be hired once per runner. Everything below guards the one rule
// the feature stands on: the view lists WORKERS, while brief, configuration and
// findings stay with the method they share.

const RG_PACK = {
  name: 'review-graph',
  title: 'Reviewer',
  version: '0.1.0',
  description: 'Walks a pull request.',
  installed: 'review-graph@0.1.0',
  run: { target: 'pull-request', prompt: { accepts: true, required: false } },
  brief: { standing: null, scenarios: [] },
  dimensions: [{ id: 'correctness', title: 'Correctness and blast radius' }],
};

const HIRE = (over) => ({
  id: 'review-graph@claude',
  pack: 'review-graph',
  provider: 'claude',
  model: 'sonnet',
  label: 'sonnet',
  display: 'Reviewer · sonnet',
  packTitle: 'Reviewer',
  packInstalled: true,
  providerTitle: 'Claude Code',
  bin: 'claude',
  available: true,
  ...over,
});

check('pohled Specialisté ukazuje pracovníky, ne metody', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [RG_PACK],
    hires: [
      HIRE(),
      HIRE({ id: 'review-graph@codex', provider: 'codex', model: null, label: 'codex',
        display: 'Reviewer · codex', providerTitle: 'Codex CLI', bin: 'codex' }),
    ],
  });
  const rows = new views.ToolsTree().roots();
  assert.deepStrictEqual(rows.map((r) => r.item.label),
    ['Reviewer · sonnet', 'Reviewer · codex'],
    'dva providery nad jednou metodou musí být dva řádky — jinak se mezi nimi nedá vybrat');
  assert.deepStrictEqual(rows.map((r) => r.item.id),
    ['hire:review-graph@claude', 'hire:review-graph@codex']);
  for (const r of rows) assert.strictEqual(r.item.contextValue, 'agencyHire');
});

check('pracovník nese runner, metoda nese zadání i konfiguraci', () => {
  const rows = new views.ToolsTree().roots();
  const kdo = rows[0].children.find((c) => c.item.label === 'Who handles it');
  assert.strictEqual(kdo.item.description, 'claude · sonnet');
  // Informativní řádek NESMÍ nic spouštět: `command` na TreeItem se pouští
  // obyčejným kliknutím, takže by se agent rozjel jen tím, že si panel čteš.
  assert.strictEqual(kdo.item.command, undefined,
    'čtení panelu nesmí otevřít terminál');

  const codex = rows[1].children.find((c) => c.item.label === 'Who handles it');
  assert.strictEqual(codex.item.description, 'codex',
    'hire bez modelu nesmí zdědit model psaný pro jiného providera');

  // Sdílené věci jsou u obou a míří na tentýž pack — na tom stojí sdílená paměť.
  for (const r of rows) {
    const cfg = r.children.find((c) => c.item.label === 'Configuration');
    assert.strictEqual(cfg.item.description, '.agency/review-graph.json');
    assert.ok(cfg.item.tooltip.value.includes('Shared by every specialist'),
      'u druhého pracovníka musí být vidět, že konfigurace je společná');
  }
});

check('metoda, kterou nikdo nedělá, jde pořád najmout', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, packs: [RG_PACK, QA_PACK], hires: [HIRE()],
  });
  const rows = new views.ToolsTree().roots();
  const qa = rows.find((r) => r.item.id === 'pack:qa');
  assert.ok(qa, 'nenajatá metoda musí zůstat vidět, jinak není kde najmout prvního');
  assert.strictEqual(qa.item.contextValue, 'agencyPack.available');
  assert.strictEqual(qa.item.description, 'installed, nobody hired');
});

check('pracovník bez binárky je označený, ne skrytý', () => {
  // Roster cestuje s repozitářem, binárky ne. Kolega, který si repo naklonuje,
  // se musí dozvědět, který specialista u něj běžet nemůže — a proč.
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [RG_PACK],
    hires: [HIRE({ id: 'review-graph@grok', provider: 'grok', model: 'grok-heavy',
      label: 'grok-heavy', display: 'Reviewer · grok-heavy', bin: 'grok', available: false })],
  });
  const row = new views.ToolsTree().roots()[0];
  assert.ok(String(row.item.description).includes('not on PATH'));
  const kdo = row.children.find((c) => c.item.label === 'Who handles it');
  assert.ok(kdo.item.tooltip.value.includes('not on PATH'));
});

check('přehled shrne roster, ne seznam packů', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt', loadedAt: new Date(),
    project: { slug: 'org/repo' }, doctor: [], runs: [], findings: [], metrics: null,
    packs: [RG_PACK],
    hires: [
      HIRE(),
      HIRE({ id: 'review-graph@grok', label: 'grok-heavy', available: false, bin: 'grok' }),
    ],
  });
  const row = new views.OverviewTree().roots().find((r) => r.item.label === 'Specialists');
  assert.ok(String(row.item.description).includes('sonnet'));
  assert.ok(String(row.item.description).includes('1 not on PATH'),
    'nedostupný specialista se musí ohlásit dřív, než ho někdo spustí');
});

check('dva běhy nad týmž PR jde od sebe rozeznat', () => {
  // Bez jména specialisty jsou to v seznamu dva shodné řádky „PR #467" — a
  // porovnat dva providery je přesně ten důvod, proč běhy vznikly dva.
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'review-graph@0.1.0', status: 'ok',
        target: 467, targetLabel: 'PR #467', kind: 'pull-request',
        hire: 'review-graph@claude', model: 'sonnet', provider: 'claude',
        findings: 3, undecided: 3, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'review-graph@0.1.0', status: 'ok',
        target: 467, targetLabel: 'PR #467', kind: 'pull-request',
        hire: 'review-graph@codex', model: null, provider: 'codex',
        findings: 2, undecided: 2, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.ok(String(rows[0].item.description).startsWith('claude ·'));
  assert.ok(String(rows[1].item.description).startsWith('codex ·'));
  assert.ok(rows[0].item.tooltip.value.includes('review-graph@claude'));
});

check('běhy jednoho týmu drží pohromadě', () => {
  // Bez seskupení vypadá tým jako dva nesouvisející běhy a to, že druhý soudil
  // prvního, není odkud vyčíst.
  const chain = { id: '01M1TEAM0000000000000000AA', of: 2 };
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'po@0.1.0', status: 'ok',
        targetLabel: 'main', kind: 'workspace', hire: 'po@claude',
        chain: { ...chain, position: 2, upstream: ['01M1CGN9HAMBKK63SASPP2EYWA'] },
        findings: 2, undecided: 1, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'legal@0.1.0', status: 'ok',
        targetLabel: 'main', kind: 'workspace', hire: 'legal@claude',
        chain: { ...chain, position: 1, upstream: [] },
        findings: 3, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();

  assert.strictEqual(rows.length, 1, 'dva běhy jednoho řetězu jsou jeden uzel');
  assert.strictEqual(rows[0].item.label, 'legal → po', 'pořadí je podle pozice, ne podle času');
  assert.ok(String(rows[0].item.description).includes('2/2 steps'));
  assert.ok(String(rows[0].item.description).includes('5 findings'), 'počty se sčítají');
  assert.strictEqual(rows[0].children.length, 2);
  assert.ok(String(rows[0].children[0].item.description).startsWith('step 1/2'));
});

check('nedoběhnutý tým se netváří jako hotový', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'legal@0.1.0', status: 'failed',
        targetLabel: 'main', kind: 'workspace', hire: 'legal@claude',
        chain: { id: '01M1TEAM0000000000000000BB', position: 1, of: 3, upstream: [] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.ok(String(rows[0].item.description).includes('1/3 steps'));
  assert.ok(rows[0].item.tooltip.value.includes('stopped after 1 of 3'));
});

check('samostatný běh se do týmu nezabalí', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'qa@0.1.0', status: 'ok',
        targetLabel: 'main', kind: 'workspace', hire: 'qa@claude', chain: null,
        findings: 1, undecided: 1, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.strictEqual(rows[0].item.label, 'main');
  assert.ok(!String(rows[0].item.id).startsWith('chain:'));
});

check('výběr pracovníka jde podle politiky metody, ne podle jména', () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [QA_PACK, RG_PACK, { name: 'nenainstalovany', installed: null, run: { target: 'workspace' } }],
    hires: [
      HIRE(),
      HIRE({ id: 'qa@claude', pack: 'qa', display: 'QA engineer · sonnet' }),
      HIRE({ id: 'duch@claude', pack: 'nenainstalovany', display: 'Duch · sonnet' }),
    ],
  });
  assert.deepStrictEqual(review.reviewHires().map((h) => h.id), ['review-graph@claude']);
  assert.deepStrictEqual(review.workspaceHires().map((h) => h.id), ['qa@claude'],
    'nabízet se má jen pracovník nainstalované metody');
});

check('shoda dvou specialistů se ukáže, až když jsou dva', () => {
  const base = {
    project: { name: 'p' }, runs: 2,
    triage: { accepted: 1, rejected: 0, deferred: 0, undecided: 0, precision: 1 },
    findings: { raw: 2, kept: 1, duplicates: 1, dedupRatio: 0.5, gateYield: 0.5, gatedBy: null },
    queue: { undecided: 0, medianAgeDays: null, oldestDays: null },
    cost: { secondsPerKeptFinding: null },
    byDimension: {}, bySeverity: {}, byModel: {}, rejectReasons: null,
    byHire: {
      'review-graph@claude': { accepted: 1, rejected: 0, deferred: 0, undecided: 0, precision: 1 },
      'review-graph@codex': { accepted: 1, rejected: 0, deferred: 0, undecided: 0, precision: 1 },
    },
  };

  const dva = panel.metricsHtml({ ...base, agreement: { crossHire: 1, sameHire: 0, hires: 2 } });
  assert.ok(dva.includes('By specialist'), 'chybí rozpad po specialistech');
  assert.ok(dva.includes('review-graph@codex'), 'druhý specialista se nevykreslil');
  assert.ok(dva.includes('Agreement'), 'chybí shoda dvou specialistů');

  // S jedním pracovníkem je shoda vždycky nula a četla by se jako selhání.
  const jeden = panel.metricsHtml({ ...base, agreement: { crossHire: 0, sameHire: 0, hires: 1 } });
  assert.ok(!jeden.includes('Agreement'));

  // Starší data pole vůbec nemají — panel na tom nesmí spadnout.
  assert.ok(!panel.metricsHtml(base).includes('Agreement'));
});

check('uzel stromu nese jméno, ne objekt', () => {
  // Příkaz spuštěný z řádku stromu dostane UZEL, ne řetězec. Bez rozbalení
  // doletí objekt až do execFile, zestringovatí se a běh zemře na
  // `Unknown pack "[object Object]"` — chybě, která neřekne, odkud přišla.
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [RG_PACK, QA_PACK],
    hires: [HIRE()],
  });
  const rows = new views.ToolsTree().roots();
  const hireRow = rows.find((r) => r.item.id === 'hire:review-graph@claude');
  const packRow = rows.find((r) => r.item.id === 'pack:qa');

  // Tvar id uzlů je kontrakt mezi stromem a příkazy — extension.js z něj
  // jméno rozbaluje a nic jiného k dispozici nemá.
  assert.strictEqual(typeof hireRow.item.id, 'string');
  assert.ok(hireRow.item.id.startsWith('hire:'));
  assert.ok(packRow.item.id.startsWith('pack:'));

  // Akce, které klikatelné jsou, předávají jméno explicitně, ne jako uzel.
  const cfg = hireRow.children.find((c) => c.item.label === 'Configuration');
  assert.deepStrictEqual(cfg.item.command.arguments, ['review-graph'],
    'konfigurace patří metodě, takže se předává jméno packu, ne pracovníka');
});

check('každý pracovník jde propustit', () => {
  // Do 1. 9. 2026 tu byl „odvozený" pracovník, kterému koš chyběl: nebyl zápis
  // v rosteru, tak nebylo co smazat. V panelu to byl řádek, který vypadá jako
  // ostatní a chová se jinak — a po propuštění posledního skutečného se navíc
  // vracel sám. Roster teď obsahuje jen skutečné pracovníky, takže na každého
  // platí totéž.
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [RG_PACK],
    hires: [HIRE()],
  });
  const row = new views.ToolsTree().roots()[0];
  assert.strictEqual(row.item.contextValue, 'agencyHire');

  const menus = require(path.join(SRC, '..', 'package.json'))
    .contributes.menus['view/item/context'];
  for (const cmd of ['agency.hire.remove', 'agency.hire.run', 'agency.pack.brief']) {
    assert.strictEqual(menus.find((m) => m.command === cmd && /agencyHire/.test(m.when)).when,
      'viewItem == agencyHire', `${cmd} má platit na každého pracovníka`);
  }
});

// --------------------------------------------------------------- spuštění

/**
 * Podstrčí odpovědi na quick picky a spočítá, na co se kdo ptal.
 *
 * `cli.run` se zároveň nahradí, aby test nespouštěl skutečný `agency` — zkoumá
 * se, na co se UI ptá, ne co dělá jádro.
 */
function askedAbout(answers) {
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  const asked = [];
  const queue = [...answers];
  cli.run = async (cwd, who) => ({
    ok: true,
    data: {
      runId: '01M1CGN9HAMBKK63SASPP2EYWJ', worktree: 'C:/projekt',
      hire: { id: who, label: 'sonnet' }, agent: { provider: 'claude', model: 'sonnet' },
      target: { ref: 'main' }, launch: ['claude', 'go'],
    },
  });
  vscode.window.showQuickPick = async (items, opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  vscode.window.showInputBox = async (opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  return asked;
}

checkAsync('spuštění z řádku pracovníka se už neptá, koho pustit', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt',
    packs: [QA_PACK],
    hires: [
      HIRE({ id: 'qa@claude', pack: 'qa', display: 'QA engineer · sonnet' }),
      HIRE({ id: 'qa@codex', pack: 'qa', provider: 'codex', model: null, label: 'codex',
        display: 'QA engineer · codex', bin: 'codex' }),
    ],
  });

  // Klik na ▶ u „QA engineer · sonnet" — pracovník je tím kliknutím vybraný.
  const asked = askedAbout([{ label: '$(bookmark) smoke', scenario: 'smoke' }]);
  const kdo = state.snapshot.hires[0];
  await review.runOverWorkspace('C:/projekt', kdo, { appendLine() {} });

  assert.deepStrictEqual(asked, ['What should be tested?'],
    'zeptat se znovu, koho pustit, je otázka, na kterou ten klik už odpověděl');
});

checkAsync('obecné spuštění se na pracovníka ptát musí', async () => {
  const review = require(path.join(SRC, 'review.js'));
  const asked = askedAbout([
    { label: 'QA engineer · sonnet', hire: state.snapshot.hires[0] },
    { label: '$(bookmark) smoke', scenario: 'smoke' },
  ]);

  await review.runOverWorkspace('C:/projekt', null, { appendLine() {} });

  assert.strictEqual(asked[0], 'Which specialist should run the session?',
    'bez vybraného pracovníka se zeptat musí — dva najatí nejsou jeden');
});

check('popisek řádku se neopakuje', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [QA_PACK],
    hires: [
      HIRE({ id: 'qa@claude', pack: 'qa', display: 'QA engineer · sonnet' }),
      HIRE({ id: 'qa@codex', pack: 'qa', provider: 'codex', model: null, label: 'codex',
        display: 'QA engineer · codex', bin: 'codex' }),
    ],
  });
  const rows = new views.ToolsTree().roots();
  assert.strictEqual(rows[0].item.description, 'claude',
    '„QA engineer · sonnet   sonnet" je šum; runner za tím modelem je informace');
  assert.strictEqual(rows[1].item.description, '',
    'když je popisek rovnou runner, není co dopisovat');
});

check('propuštění je na řádku, ne schované v pravém tlačítku', () => {
  const menus = require(path.join(SRC, '..', 'package.json'))
    .contributes.menus['view/item/context'];
  const dismiss = menus.find((m) => m.command === 'agency.hire.remove');
  assert.ok(dismiss.group.startsWith('inline'),
    'akce jen v kontextovém menu je akce, kterou nikdo nenajde');
  assert.strictEqual(dismiss.when, 'viewItem == agencyHire',
    'propustit jde každý pracovník — v rosteru jsou jen skuteční');
});

/** Tým, který sestaví terminálový příkaz místo spuštění běhu — `agency chain`
 *  si běhy pouští sám, takže se tady zkoumá, co se pošle do terminálu. */
function chainAskedAbout(answers) {
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  const asked = [];
  const sent = [];
  const queue = [...answers];
  cli.prs = async () => [
    { number: 479, title: 'Generátor odmítne placeholder identitu', state: 'merged',
      reviewed: false, mergedAt: '2026-09-02', author: 'kuba' },
    { number: 474, title: 'CTA poptávky míří na kotvu formuláře', state: 'merged',
      reviewed: true, mergedAt: '2026-09-02', author: 'kuba' },
  ];
  vscode.window.showQuickPick = async (items, opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  vscode.window.showInputBox = async (opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  vscode.window.createTerminal = () => ({
    show() {}, dispose() {},
    sendText(t) { sent.push(t); },
  });
  return { asked, sent };
}

checkAsync('tým s recenzentem se musí zeptat, který PR', async () => {
  // Tohle se nezeptalo a uživatel napsal číslo PR do zadání. Cíl se tím
  // nezměnil — zadání čte agent, cíl vybírá deterministická příprava — takže
  // recenzent dostal PR aktuální větve a zastavil se s otázkou, proč mu zadání
  // mluví o něčem jiném.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt',
    packs: [RG_PACK, PO_PACK],
    hires: [
      HIRE({ id: 'review-graph@claude', pack: 'review-graph', display: 'Reviewer · sonnet' }),
      HIRE({ id: 'po@claude', pack: 'po', display: 'Product owner · sonnet' }),
    ],
  });

  const { asked, sent } = chainAskedAbout([
    { label: 'Reviewer · sonnet', hire: state.snapshot.hires[0] },
    { label: 'Product owner · sonnet', hire: state.snapshot.hires[1] },
    { label: '#479', pr: { number: 479, reviewed: false } },
    'zjisti, jestli to dává produktový smysl',
  ]);

  await review.pickAndChain('C:/projekt', { appendLine() {} });

  assert.ok(asked.some((t) => /which pull request/i.test(t)),
    'bez téhle otázky se cíl vezme z aktuální větve a nikdo se to nedozví');
  assert.strictEqual(sent.length, 1);
  assert.ok(sent[0].includes('--pr 479'), `vybraný PR musí být v příkazu: ${sent[0]}`);
  assert.ok(sent[0].includes('chain review-graph@claude po@claude'));
});

checkAsync('tým jen nad projektem se na PR neptá', async () => {
  // QA i PO pracují nad projektem. Otázka, na kterou nikdo nepotřebuje znát
  // odpověď, je jen krok navíc.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt',
    packs: [QA_PACK, PO_PACK],
    hires: [
      HIRE({ id: 'po@claude', pack: 'po', display: 'Product owner · sonnet' }),
      HIRE({ id: 'qa@claude', pack: 'qa', display: 'QA engineer · sonnet' }),
    ],
  });

  const { asked, sent } = chainAskedAbout([
    { label: 'Product owner · sonnet', hire: state.snapshot.hires[0] },
    { label: 'QA engineer · sonnet', hire: state.snapshot.hires[1] },
    'co má tým řešit',
  ]);

  await review.pickAndChain('C:/projekt', { appendLine() {} });

  assert.ok(!asked.some((t) => /which pull request/i.test(t)));
  // `--prompt` v sobě `--pr` obsahuje, takže se hledá celý přepínač.
  assert.ok(!/\s--pr\s/.test(sent[0]), sent[0]);
});

checkAsync('už zrecenzovaný PR tým nezastaví hned na prvním kroku', async () => {
  // Uživatel ho právě vybral ze seznamu, kde je označený jako zrecenzovaný —
  // je to volba, ne omyl. Bez `--force` by se řetěz zastavil na `already-reviewed`.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/projekt',
    packs: [RG_PACK, PO_PACK],
    hires: [
      HIRE({ id: 'review-graph@claude', pack: 'review-graph', display: 'Reviewer · sonnet' }),
      HIRE({ id: 'po@claude', pack: 'po', display: 'Product owner · sonnet' }),
    ],
  });

  const { sent } = chainAskedAbout([
    { label: 'Reviewer · sonnet', hire: state.snapshot.hires[0] },
    { label: 'Product owner · sonnet', hire: state.snapshot.hires[1] },
    { label: '#474', pr: { number: 474, reviewed: true } },
    '',
  ]);

  await review.pickAndChain('C:/projekt', { appendLine() {} });

  assert.ok(sent[0].includes('--force'), sent[0]);
});

(async () => {
  for (const [name, fn] of pending) {
    try { await fn(); console.log(`  ok   ${name}`); }
    catch (e) { failed += 1; console.log(`  FAIL ${name}\n       ${e.message}`); }
  }
  console.log(failed ? `\n${failed} selhalo\n` : '\nvšechno prošlo\n');
  process.exit(failed ? 1 : 0);
})();
