// Smoke test for the extension without a running VS Code.
//
//   node packages/extension/test/harness.js
//
// Checks what can be checked without a real editor: that the modules load,
// that the trees build the right nodes from the real shape of the data, and
// that unescaped input cannot reach the HTML. Rendering comment threads and
// clicking buttons wants F5 — this file does not pretend to cover that.
//
// The fake `vscode` is deliberately dumb. If logic had to be written into
// it, that would mean logic is migrating from the core into the extension.

const Module = require('module');
const assert = require('assert');
const path = require('path');

// ------------------------------------------------------------ fake vscode
class EventEmitter {
  constructor() { this.handlers = []; }
  get event() { return (fn) => { this.handlers.push(fn); return { dispose() {} }; }; }
  fire(...a) { this.handlers.forEach((h) => h(...a)); }
}

const fake = {
  EventEmitter,
  ConfigurationTarget: { Global: 1, Workspace: 2 },
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
    parse: (s) => ({ scheme: String(s).split(':')[0], toString: () => String(s) }),
  },
  workspace: {
    workspaceFolders: [{ uri: { fsPath: 'C:/project' } }],
    // A mutable store per section, so `presets.js` can round-trip through
    // `.get`/`.update` the same way the real settings object does — a fake
    // that only ever answered `cliPath` could not test a preset surviving
    // a redraw.
    _settings: { agency: { cliPath: 'agency', presets: [] } },
    getConfiguration(section) {
      const store = fake.workspace._settings[section] || (fake.workspace._settings[section] = {});
      return {
        get: (key, def) => (key in store ? store[key] : def),
        update: (key, value) => { store[key] = value; return Promise.resolve(); },
      };
    },
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
  env: {
    clipboard: { writeText: async () => {} },
    openExternal() {},
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

// ----------------------------------------------------------------- fixtures
const SRC = path.join(__dirname, '..', 'src');
const panel = require(path.join(SRC, 'panel.js'));
const views = require(path.join(SRC, 'views.js'));
const state = require(path.join(SRC, 'state.js'));

const FINDING = {
  id: '01M1BTSC00000000000000000A',
  runId: '01M1BT1TX2G11HZ8SQC0FZCDAE',
  pack: 'review-graph',
  dimension: 'correctness',
  severity: 'high',
  title: 'The address suggestion survives a failed geocode',
  body: 'The diff introduces `addressSuggestion` state.\n\n- first point\n- second point',
  file: 'src/components/Fields.tsx',
  line: 185,
  anchor: {
    file: 'src/components/Fields.tsx', line: 185, endLine: 190,
    commit: 'f7dd184fd40a159524a55df3ab5e581980c01b33',
    symbol: { name: 'InstructorVenueLocationFields', range: [47, 416] },
    snippet: 'if (generation !== ref.current) return;',
  },
  evidence: [{ kind: 'diff', detail: 'Two early returns do not clear the suggestion.', source: 'git diff' }],
  drift: 'touched',
  resolved: { line: 170, via: 'snippet', note: 'shifted 185 → 170' },
  score: 90,
  state: 'candidate',
  ref: null,
  url: null,
  reason: null,
  by: null,
  history: [],
  target: { pr: 467, url: 'https://github.com/x/y/pull/467' },
};

// A pack the way `agency packs --json` describes it — the same shape whether
// the caller is the extension or an agent reading the terminal.
const RG_PACK = {
  name: 'review-graph', title: 'Reviewer', skill: 'agency-review-graph',
  description: 'Walks a pull request.',
  dimensions: [{ id: 'correctness', title: 'Correctness and blast radius' }],
  requires: [],
  run: { target: 'pull-request', worktree: true,
    graph: { required: ['changes', 'impact'], optional: [] }, prompt: 'optional', needs: [] },
  minScore: 80,
};

const QA_PACK = {
  name: 'qa', title: 'QA engineer', skill: 'agency-qa',
  description: 'Explores the running application.',
  dimensions: [{ id: 'happy-path', title: 'The main flows do what they promise' }],
  requires: [],
  run: { target: 'workspace', worktree: false, graph: null, prompt: 'required', needs: [] },
  minScore: 70,
};

const PO_PACK = {
  name: 'po', title: 'Product owner', skill: 'agency-po',
  description: 'Holds the roadmap against what is actually being built.',
  dimensions: [{ id: 'scope', title: 'Work in flight that no commitment covers' }],
  requires: ['python .claude/skills/agency-po/scripts/backlog.py'],
  run: { target: 'workspace', worktree: false, graph: null, prompt: 'optional',
    needs: ['python .claude/skills/agency-po/scripts/backlog.py'] },
  minScore: 75,
};

/** The PO pack as it really is since `needsUnattended`: two commands that
 *  leave a mark other people see, held back from the blanket grant. */
const PO_TRUSTED = {
  ...PO_PACK,
  run: { ...PO_PACK.run,
    needsUnattended: ['python .claude/skills/agency-po/scripts/backlog.py promote'] },
};

let failed = 0;
function check(name, fn) {
  try { fn(); console.log(`  ok   ${name}`); }
  catch (e) { failed += 1; console.log(`  FAIL ${name}\n       ${e.message}`); }
}

// Starting a run is a chain of promises. Async checks are collected and run
// at the end, so the summary does not print "passed" before it knows.
const pending = [];
function checkAsync(name, fn) { pending.push([name, fn]); }

console.log('\nAgency — extension smoke test\n');

// ---------------------------------------------------------------- panel.js

check('markdown escapes HTML from the input', () => {
  const html = panel.md('<img src=x onerror="alert(1)"> and `code`');
  assert.ok(!html.includes('<img'), 'an unescaped tag reached the HTML');
  assert.ok(html.includes('<code>code</code>'));
});

check('finding detail renders the claim, the evidence and the anchor', () => {
  const html = panel.findingHtml(FINDING);
  assert.ok(html.includes('The address suggestion survives'), 'missing title');
  assert.ok(html.includes('What backs it up'), 'missing evidence section');
  assert.ok(html.includes('early returns'), 'missing evidence text');
  assert.ok(html.includes('InstructorVenueLocationFields'), 'missing symbol from the anchor');
  assert.ok(html.includes('185') && html.includes('170'), 'missing anchor shift');
  assert.ok(html.includes('Compare with today'),
    'a drifted finding is missing the diff button — its presence IS the drift signal');
});

check('an untouched finding does not offer a diff', () => {
  const html = panel.findingHtml({ ...FINDING, drift: 'untouched' });
  assert.ok(!html.includes('Compare with today'),
    'a diff against the working copy would show the same content twice');
});

check('finding detail shows the outcome and a note field, never a decision button', () => {
  const html = panel.findingHtml({ ...FINDING, state: 'sent', ref: 'PVTI_X', url: 'https://x/PVTI_X' });
  assert.ok(html.includes('Outcome'), 'missing the outcome section');
  assert.ok(html.includes('PVTI_X'), 'missing the board reference');
  assert.ok(html.includes('data-cmd="note"'), 'missing the note action');
  assert.ok(html.includes('data-cmd="openOnBoard"'), 'missing the open-on-board action');
  for (const cmd of ['accept', 'defer', 'reject']) {
    assert.ok(!html.includes(`data-cmd="${cmd}"`), `a viewer must not offer to ${cmd} a finding`);
  }
  assert.ok(!html.includes('id="reason"'), 'the rejection reason picker should be gone');
});

check('a rejected finding shows the reason, a held one shows it is waiting', () => {
  const rejected = panel.findingHtml({ ...FINDING, state: 'rejected', reason: 'by-design', by: 'hire:po@claude' });
  assert.ok(rejected.includes('Rejected') && rejected.includes('by-design'));

  const held = panel.findingHtml({ ...FINDING, state: 'held' });
  assert.ok(held.includes('Held'));
});

check('metrics with no data show a dash, not a zero', () => {
  const html = panel.metricsHtml({
    project: { name: 'p' }, runs: 1,
    triage: { accepted: 0, rejected: 0, deferred: 0, undecided: 3, precision: null },
    findings: { raw: 3, kept: 3, duplicates: 0, dedupRatio: null, gateYield: 1, gatedBy: null },
    queue: { undecided: 3, medianAgeDays: 0.1, oldestDays: 0.1 },
    cost: { secondsPerKeptFinding: 276 },
    byDimension: {}, bySeverity: {}, byHire: {}, byModel: {}, rejectReasons: null,
  });
  assert.ok(html.includes('—'), 'a zero-over-zero rendered as a number');
});

check('agreement between two specialists shows only once there are two', () => {
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

  const two = panel.metricsHtml({ ...base, agreement: { crossHire: 1, sameHire: 0, hires: 2 } });
  assert.ok(two.includes('By specialist'), 'missing the per-specialist breakdown');
  assert.ok(two.includes('review-graph@codex'), 'the second specialist did not render');
  assert.ok(two.includes('Agreement'), 'missing the agreement between two specialists');

  // With one worker the agreement is always zero and would read as a failure.
  const one = panel.metricsHtml({ ...base, agreement: { crossHire: 0, sameHire: 0, hires: 1 } });
  assert.ok(!one.includes('Agreement'));

  // Older data has no such field at all — the panel must not crash on that.
  assert.ok(!panel.metricsHtml(base).includes('Agreement'));
});

// -------------------------------------------------------------- Overview

check('the findings tree splits by outcome — board, chain, no board, not reported, duplicates', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/project', runs: [], packs: [], project: null, metrics: null,
    findings: [
      { ...FINDING, id: 'A', state: 'sent', ref: 'PVTI_X' },
      { ...FINDING, id: 'B', state: 'held' },
      { ...FINDING, id: 'C', state: 'candidate' },
      { ...FINDING, id: 'D', state: 'rejected', reason: 'by-design' },
      { ...FINDING, id: 'E', state: 'duplicate' },
    ],
  });
  const roots = new views.FindingsTree().roots();
  const labels = roots.map((r) => r.item.label);
  assert.deepStrictEqual(labels,
    ['On the board', 'In a chain', 'Waiting — no board here', 'Not reported again', 'Duplicates']);
  assert.strictEqual(roots[0].children.length, 1);
});

check('a finding on the board shows its board reference, not a decision mark', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    findings: [{ ...FINDING, id: 'A', state: 'sent', ref: 'PVTI_X' }],
  });
  const board = new views.FindingsTree().roots()[0];
  assert.ok(String(board.children[0].item.description).includes('PVTI_X'));
});

check('sent findings sort untouched-since-analysis first', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    findings: [
      { ...FINDING, id: 'A', state: 'sent', drift: 'touched', severity: 'high' },
      { ...FINDING, id: 'B', state: 'sent', drift: 'untouched', severity: 'medium' },
    ],
  });
  const board = new views.FindingsTree().roots()[0];
  assert.strictEqual(board.children[0].item.id, 'finding:B',
    'the finding on code nobody touched should be on top — it holds literally');
});

check('the overview shows precision, with no decision queue of its own', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/project', loadedAt: new Date(),
    project: { slug: 'org/repo' }, doctor: [{ name: 'gh', ok: true, detail: '' }],
    packs: [RG_PACK],
    runs: [{ id: 'R', target: 467, targetLabel: 'PR #467', findings: 3, status: 'ok', startedAt: new Date().toISOString() }],
    findings: [FINDING],
    metrics: { triage: { precision: 0.8, accepted: 4, rejected: 1 } },
  });
  const labels = new views.OverviewTree().roots().map((r) => r.item.label);
  for (const want of ['Project', 'Prerequisites', 'Specialists', 'Last run', 'Precision']) {
    assert.ok(labels.includes(want), `overview is missing "${want}"`);
  }
  assert.ok(!labels.includes('Decision queue'),
    'a viewer does not own a queue of decisions to make');
});

check('the overview lists the packs actually in this project', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/project', loadedAt: new Date(),
    project: { slug: 'org/repo' }, doctor: [], runs: [], findings: [], metrics: null,
    packs: [RG_PACK, QA_PACK],
  });
  const row = new views.OverviewTree().roots().find((r) => r.item.label === 'Specialists');
  assert.strictEqual(row.item.description, 'review-graph, qa');
  assert.ok(row.item.tooltip.value.includes('.claude/skills/agency-<name>/'),
    'a pack is a skill in the project, not something the tool installed');
});

check('without the CLI the trees render no items, not empty ones', () => {
  Object.assign(state.snapshot, { probe: { ok: false, reason: 'no-cli' }, findings: [] });
  assert.deepStrictEqual(new views.FindingsTree().roots(), []);
  assert.deepStrictEqual(new views.OverviewTree().roots(), []);
});

check('doctor from the CLI arrives as {checks:[…]}, the tree expects an array', () => {
  // A mismatch here would take down the whole Overview with `.filter is not
  // a function`. It unwraps in cli.js, in one place — one test covers it.
  const cli = require(path.join(SRC, 'cli.js'));
  assert.strictEqual(typeof cli.doctor, 'function');
  Object.assign(state.snapshot, {
    probe: { ok: true }, cwd: 'C:/project', loadedAt: new Date(),
    project: { slug: 'org/repo' },
    doctor: [{ name: 'gh auth', ok: false, detail: 'not logged in', fatal: true }],
    packs: [], runs: [], findings: [], metrics: null,
  });
  const rows = new views.OverviewTree().roots();
  const req = rows.find((r) => r.item.label === 'Prerequisites');
  assert.strictEqual(req.item.description, '1 problem');
});

// ------------------------------------------------------------ Specialists

check('the Specialists tree shows one row per pack, not per run policy variant', () => {
  Object.assign(state.snapshot, { probe: { ok: true }, packs: [RG_PACK, QA_PACK, PO_PACK] });
  const rows = new views.ToolsTree().roots();
  assert.deepStrictEqual(rows.map((r) => r.item.label), ['Reviewer', 'QA engineer', 'Product owner']);
  assert.deepStrictEqual(rows.map((r) => r.item.id), ['pack:review-graph', 'pack:qa', 'pack:po']);
  for (const r of rows) assert.strictEqual(r.item.contextValue, 'agencyPack');
});

check('a pack row shows what it does, what it looks at and what it works on', () => {
  const row = new views.ToolsTree().roots()[0];   // Reviewer
  const labels = row.children.map((c) => c.item.label);
  assert.ok(labels.includes('What it does'));
  assert.ok(labels.includes('What it looks at'));
  assert.ok(labels.includes('What it works on'));

  const dims = row.children.find((c) => c.item.label === 'What it looks at');
  assert.strictEqual(dims.item.description, '1 dimensions');
  assert.strictEqual(dims.children[0].item.label, 'Correctness and blast radius');

  const target = row.children.find((c) => c.item.label === 'What it works on');
  assert.strictEqual(target.item.description, 'a pull request');
});

check('a workspace pack reads "the project as it is", not "a pull request"', () => {
  const qa = new views.ToolsTree().roots()[1];
  const target = qa.children.find((c) => c.item.label === 'What it works on');
  assert.strictEqual(target.item.description, 'the project as it is');
  assert.ok(target.item.tooltip.value.includes('working copy'),
    'a workspace run is read-only over the working copy — that has to be visible');
});

check('a required prompt says so on the row, an optional one does too', () => {
  const rows = new views.ToolsTree().roots();
  const qaPrompt = rows[1].children.find((c) => c.item.label === 'Prompt');
  assert.strictEqual(qaPrompt.item.description, 'required every run');
  const rgPrompt = rows[0].children.find((c) => c.item.label === 'Prompt');
  assert.strictEqual(rgPrompt.item.description, 'optional');
});

check('a pack with no prompt at all has no Prompt row', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true },
    packs: [{ ...RG_PACK, run: { ...RG_PACK.run, prompt: 'none' } }],
  });
  const row = new views.ToolsTree().roots()[0];
  assert.ok(!row.children.some((c) => c.item.label === 'Prompt'));
});

check('a pack that needs a tool says so, one that needs none has no Requires row', () => {
  Object.assign(state.snapshot, { probe: { ok: true }, packs: [PO_PACK, QA_PACK] });
  const rows = new views.ToolsTree().roots();
  const po = rows.find((r) => r.item.id === 'pack:po');
  const requires = po.children.find((c) => c.item.label === 'Requires');
  assert.ok(requires, 'a pack with a `requires` list must show it — nobody reads pack.json to find out');
  assert.strictEqual(requires.item.description, 'python .claude/skills/agency-po/scripts/backlog.py');

  const qa = rows.find((r) => r.item.id === 'pack:qa');
  assert.ok(!qa.children.some((c) => c.item.label === 'Requires'));
});

check('preset rows sit under their pack, ahead of the pack\'s own info rows', () => {
  const vscode = require.cache.vscode.exports;
  vscode.workspace._settings.agency.presets = [
    { pack: 'review-graph', provider: 'codex', model: 'gpt-5', label: 'Reviewer · codex' },
  ];
  Object.assign(state.snapshot, { probe: { ok: true }, packs: [RG_PACK, QA_PACK] });

  const row = new views.ToolsTree().roots()[0];
  assert.strictEqual(row.children[0].item.label, 'Reviewer · codex');
  assert.strictEqual(row.children[0].item.contextValue, 'agencyPreset');
  assert.strictEqual(row.children[0]._pack.name, 'review-graph');
  assert.ok(row.children.some((c) => c.item.label === 'What it does'),
    'the pack\'s own info rows must still be there, after the presets');

  vscode.workspace._settings.agency.presets = [];
});

checkAsync('presets.add refuses a duplicate', async () => {
  const presets = require(path.join(SRC, 'presets.js'));
  const vscode = require.cache.vscode.exports;
  vscode.workspace._settings.agency.presets = [];

  const p = { pack: 'qa', provider: 'claude', model: 'sonnet' };
  const first = await presets.add(p);
  const second = await presets.add(p);

  assert.strictEqual(first, true);
  assert.strictEqual(second, false, 'the same preset added twice must not duplicate');
  assert.strictEqual(presets.all().length, 1);

  vscode.workspace._settings.agency.presets = [];
});

checkAsync('a preset\'s provider/model reach cli.run, alongside the prompt', async () => {
  const review = require(path.join(SRC, 'review.js'));
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK] });

  let captured = null;
  cli.run = async (cwd, pack, opts) => {
    captured = opts;
    return {
      ok: true,
      data: {
        runId: '01M1CGN9HAMBKK63SASPP2EYWJ', worktree: 'C:/project',
        agent: { provider: opts.provider, model: opts.model },
        target: { ref: 'main' }, launch: ['claude', 'go'],
      },
    };
  };
  vscode.window.showInputBox = async () => 'try cancelling a booking';

  await review.runOverWorkspace('C:/project', QA_PACK, { appendLine() {} },
    { provider: 'codex', model: 'gpt-5' });

  assert.strictEqual(captured.provider, 'codex');
  assert.strictEqual(captured.model, 'gpt-5');
  assert.strictEqual(captured.prompt, 'try cancelling a booking');
});

check('a tree row carries a name, not an object', () => {
  // A command fired from a tree row gets a NODE, not a string. Without
  // unwrapping it, the object reaches execFile, stringifies, and the run
  // dies on `Unknown pack "[object Object]"` — an error that does not say
  // where it came from. The id shape is the contract between the tree and
  // the commands in extension.js, which has nothing else to read.
  Object.assign(state.snapshot, { probe: { ok: true }, packs: [RG_PACK, QA_PACK] });
  const rows = new views.ToolsTree().roots();
  for (const r of rows) {
    assert.strictEqual(typeof r.item.id, 'string');
    assert.ok(r.item.id.startsWith('pack:'));
  }
});

// -------------------------------------------------------------------- Runs

check('a run without a pull request is not named by a bare id', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [{
      id: '01M1CGN9HAMBKK63SASPP2EYWJ', pack: 'qa', provider: 'claude', model: 'sonnet',
      status: 'ok', target: null, targetLabel: 'main', kind: 'workspace',
      prompt: 'try cancelling a booking', findings: 1, undecided: 1,
      startedAt: new Date().toISOString(),
    }],
  });
  const run = new views.RunsTree().roots()[0];
  assert.strictEqual(run.item.label, 'main');
  assert.ok(run.item.tooltip.value.includes('over the project as it was'),
    'the tooltip is missing that the run went over the project');
  assert.ok(run.item.tooltip.value.includes('cancelling a booking'),
    'the tooltip is missing the prompt the run was started with');
});

check('two runs over the same PR can be told apart', () => {
  // Without a name in the list these are two identical "PR #467" rows — and
  // comparing two providers is exactly why there are two runs.
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'review-graph', provider: 'claude', model: 'sonnet',
        status: 'ok', target: 467, targetLabel: 'PR #467', kind: 'pull-request',
        findings: 3, undecided: 3, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'review-graph', provider: 'codex', model: null,
        status: 'ok', target: 467, targetLabel: 'PR #467', kind: 'pull-request',
        findings: 2, undecided: 2, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.ok(String(rows[0].item.description).startsWith('review-graph · claude'));
  assert.ok(String(rows[1].item.description).startsWith('review-graph · codex'));
});

check('runs from one team stay together', () => {
  // Without grouping a team looks like two unrelated runs, and there is no
  // way to read that the second one judged the first.
  const chain = { id: '01M1TEAM0000000000000000AA', of: 2 };
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'po', provider: 'claude', status: 'ok',
        targetLabel: 'main', kind: 'workspace',
        chain: { ...chain, position: 2, upstream: ['01M1CGN9HAMBKK63SASPP2EYWA'] },
        findings: 2, undecided: 1, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'legal', provider: 'claude', status: 'ok',
        targetLabel: 'main', kind: 'workspace',
        chain: { ...chain, position: 1, upstream: [] },
        findings: 3, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();

  assert.strictEqual(rows.length, 1, 'two runs of one chain are one node');
  assert.strictEqual(rows[0].item.label, 'legal → po', 'order follows position, not time');
  assert.ok(String(rows[0].item.description).includes('2/2 steps'));
  assert.ok(String(rows[0].item.description).includes('5 findings'), 'counts must add up');
  assert.strictEqual(rows[0].children.length, 2);
  assert.ok(String(rows[0].children[0].item.description).startsWith('step 1/2'));
});

check('an unfinished team does not read as done', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'legal', provider: 'claude', status: 'failed',
        targetLabel: 'main', kind: 'workspace',
        chain: { id: '01M1TEAM0000000000000000BB', position: 1, of: 3, upstream: [] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.ok(String(rows[0].item.description).includes('1/3 steps'));
  assert.ok(rows[0].item.tooltip.value.includes('stopped after 1 of 3'));
});

check('a team that could not write is not a team with no findings', () => {
  // This is the whole reason Phase 8 exists. A chain over PR #479 finished
  // "successfully" twice and produced nothing — every write the agent
  // attempted was denied. In the panel that looked identical to a team that
  // looked and found nothing; until the denial is on the row, the panel
  // sends the user to go dig through the terminal.
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'review-graph', provider: 'claude', status: 'failed',
        targetLabel: 'PR #479', kind: 'merged-pull-request',
        exitReason: 'the agent wrote no findings.json', denied: 5,
        outputs: ['agent.md'],
        chain: { id: '01M1TEAM0000000000000000DD', position: 1, of: 2, upstream: [] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'po', provider: 'claude', status: 'no-findings',
        targetLabel: 'PR #479', kind: 'merged-pull-request',
        denied: 0, outputs: [],
        chain: { id: '01M1TEAM0000000000000000DD', position: 2, of: 2, upstream: [] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();

  assert.ok(String(rows[0].item.description).includes('5 denied'),
    'a denial belongs on the row, not buried in the log');
  assert.strictEqual(rows[0].item.iconPath.id, 'error', 'a failed member turns the whole team red');
  assert.ok(rows[0].item.tooltip.value.includes('widen'),
    'the tooltip should say what to do about it');

  const step = rows[0].children[0];
  assert.ok(String(step.item.description).includes('5 denied'));
  assert.ok(step.item.tooltip.value.includes('agent.md'),
    'the agent\'s last words are the only place that analysis survived');
});

check('the team node can be right-clicked', () => {
  const chain = { id: '01M1TEAM0000000000000000CC', of: 2 };
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'review-graph', provider: 'claude', status: 'ok',
        targetLabel: 'PR #474', kind: 'pull-request',
        chain: { ...chain, position: 1, upstream: [] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
      { id: '01M1CGN9HAMBKK63SASPP2EYWB', pack: 'po', provider: 'claude', status: 'running',
        targetLabel: 'main', kind: 'workspace',
        chain: { ...chain, position: 2, upstream: ['01M1CGN9HAMBKK63SASPP2EYWA'] },
        findings: 0, undecided: 0, startedAt: new Date().toISOString() },
    ],
  });
  const row = new views.RunsTree().roots()[0];
  assert.strictEqual(row.item.contextValue, 'agencyChain');

  const menus = require(path.join(SRC, '..', 'package.json'))
    .contributes.menus['view/item/context'];
  const hit = menus.filter((m) => m.when === 'viewItem == agencyChain');
  assert.ok(hit.length, 'a contextValue with no matching menu means right-click offers nothing');
  assert.ok(hit.some((m) => m.command === 'agency.chain.discard'));
});

check('a standalone run is not wrapped in a team', () => {
  Object.assign(state.snapshot, {
    probe: { ok: true }, findings: [],
    runs: [
      { id: '01M1CGN9HAMBKK63SASPP2EYWA', pack: 'qa', provider: 'claude', status: 'ok',
        targetLabel: 'main', kind: 'workspace', chain: null,
        findings: 1, undecided: 1, startedAt: new Date().toISOString() },
    ],
  });
  const rows = new views.RunsTree().roots();
  assert.strictEqual(rows[0].item.label, 'main');
  assert.ok(!String(rows[0].item.id).startsWith('chain:'));
});

// --------------------------------------------------------------- starting a run

check('workspace and pull-request packs are told apart by run policy, not by name', () => {
  // If the extension branched on a pack's name, every new specialist would
  // be a change to the client. `run.target` from the manifest decides.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, packs: [QA_PACK, RG_PACK, PO_PACK] });
  assert.deepStrictEqual(review.workspacePacks().map((p) => p.name), ['qa', 'po']);
  assert.deepStrictEqual(review.reviewPacks().map((p) => p.name), ['review-graph']);
});

/**
 * Stubs the answers to quick picks and input boxes, and records what was
 * asked. `cli.run` is stubbed too, so the test does not launch a real
 * `agency` process — what is under test is what the UI asks, not what the
 * core does with it.
 */
function askedAbout(answers) {
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  const asked = [];
  const queue = [...answers];
  cli.run = async (cwd, pack) => ({
    ok: true,
    data: {
      runId: '01M1CGN9HAMBKK63SASPP2EYWJ', worktree: 'C:/project',
      agent: { provider: 'claude', model: 'sonnet' },
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

checkAsync('running from a pack\'s own row does not ask which specialist', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK] });

  const asked = askedAbout(['try cancelling a booking']);
  await review.runOverWorkspace('C:/project', QA_PACK, { appendLine() {} });

  assert.deepStrictEqual(asked, ['What should this run focus on?'],
    'asking again which pack to run is a question the click already answered');
});

checkAsync('a generic run must ask which specialist', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK, PO_PACK] });

  const asked = askedAbout([{ pack: QA_PACK }, 'try cancelling a booking']);
  await review.runOverWorkspace('C:/project', null, { appendLine() {} });

  assert.strictEqual(asked[0], 'Which specialist should run the session?',
    'with two candidates and none chosen, asking is mandatory');
});

/**
 * Same idea as `askedAbout`, but it also records what reached a terminal and
 * what reached `cli.run` — an unsupervised run takes the first path and a
 * supervised one the second, and the whole point is which.
 */
function supervisionHarness(answers) {
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  const asked = [];
  const sent = [];
  const prepared = [];
  const queue = [...answers];
  cli.run = async (cwd, pack, opts) => {
    prepared.push({ pack, opts });
    return {
      ok: true,
      data: {
        runId: '01M1CGN9HAMBKK63SASPP2EYWJ', worktree: 'C:/project',
        agent: { provider: 'claude', model: 'sonnet' },
        target: { ref: 'main' }, launch: ['claude', 'go'],
      },
    };
  };
  vscode.window.showQuickPick = async (items, opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  vscode.window.showInputBox = async (opts) => {
    asked.push((opts && opts.title) || '');
    return queue.shift();
  };
  vscode.window.createTerminal = () => ({
    show() {}, dispose() {}, sendText(t) { sent.push(t); },
  });
  return { asked, sent, prepared };
}

checkAsync('a pack that cannot act outward is never asked about supervision', async () => {
  // QA writes findings and nothing else. Asking "supervised?" there would be
  // a question whose two answers do the same thing.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK] });

  const { asked, prepared } = supervisionHarness(['try cancelling a booking']);
  await review.runOverWorkspace('C:/project', QA_PACK, { appendLine() {} });

  assert.deepStrictEqual(asked, ['What should this run focus on?']);
  assert.strictEqual(prepared.length, 1, 'it still runs, just without the question');
});

checkAsync('a pack that can promote is asked, and unsupervised goes to the CLI', async () => {
  // The unsupervised path must NOT be the prepare-and-launch one: that would
  // send a bare `claude -p --output-format stream-json` to the terminal and
  // put raw JSONL in front of the user. `agency run … --unattended --wait`
  // prints readable progress and gates the output itself.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [PO_TRUSTED] });

  const { asked, sent, prepared } = supervisionHarness([
    'what should PO look at', { unattended: true },
  ]);
  await review.runOverWorkspace('C:/project', PO_TRUSTED, { appendLine() {} });

  assert.ok(asked.some((t) => /supervised, or on its own/i.test(t)),
    `the supervision question was never asked: ${JSON.stringify(asked)}`);
  assert.strictEqual(prepared.length, 0, 'unsupervised does not go through --json prepare');
  assert.strictEqual(sent.length, 1);
  assert.ok(sent[0].includes('run po --unattended --wait'), sent[0]);
  assert.ok(sent[0].includes('--prompt "what should PO look at"'), sent[0]);
});

checkAsync('supervised keeps the ordinary prepare-and-launch path', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [PO_TRUSTED] });

  const { sent, prepared } = supervisionHarness([
    'what should PO look at', { unattended: false },
  ]);
  await review.runOverWorkspace('C:/project', PO_TRUSTED, { appendLine() {} });

  assert.strictEqual(prepared.length, 1, 'supervised prepares through the CLI as always');
  assert.ok(!(prepared[0].opts || {}).unattended, 'and never asks for the grant');
  assert.deepStrictEqual(sent, ['claude go'], 'the launch argv from the CLI reaches the terminal');
});

checkAsync('walking away from the supervision question starts nothing', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [PO_TRUSTED] });

  const { sent, prepared } = supervisionHarness(['what should PO look at', undefined]);
  const result = await review.runOverWorkspace('C:/project', PO_TRUSTED, { appendLine() {} });

  assert.strictEqual(result, null);
  assert.deepStrictEqual(sent, []);
  assert.deepStrictEqual(prepared, []);
});

/** A team assembles a terminal command instead of starting a run directly —
 *  `agency chain` runs the steps itself — so this checks what reaches the
 *  terminal. */
function chainAskedAbout(answers) {
  const vscode = require.cache.vscode.exports;
  const cli = require(path.join(SRC, 'cli.js'));
  const asked = [];
  const sent = [];
  const queue = [...answers];
  cli.prs = async () => [
    { number: 479, title: 'The generator refuses a placeholder identity', state: 'merged',
      reviewed: false, mergedAt: '2026-09-02', author: 'kuba' },
    { number: 474, title: 'The inquiry CTA targets the form anchor', state: 'merged',
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

checkAsync('a team with a reviewer must ask which pull request', async () => {
  // This did not use to ask, and a user typed a PR number into the prompt
  // instead. The target did not change: the prompt is read by the agent,
  // the deterministic preparation picks the target — so the reviewer got
  // the PR of the current branch and stalled on a prompt that talked about
  // something else.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [RG_PACK, PO_PACK] });

  const { asked, sent } = chainAskedAbout([
    { pack: RG_PACK }, { pack: PO_PACK },
    { label: '#479', pr: { number: 479, reviewed: false } },
    'walk the PR technically',
    'does this make product sense?',
  ]);

  await review.pickAndChain('C:/project', { appendLine() {} });

  assert.ok(asked.some((t) => /which pull request/i.test(t)),
    'without this question the target is taken from the current branch and nobody finds out');
  assert.strictEqual(sent.length, 1);
  assert.ok(sent[0].includes('--pr 479'), `the chosen PR must be in the command: ${sent[0]}`);
  assert.ok(sent[0].includes('chain review-graph po'));
});

checkAsync('a team asks for a brief per member, not one for all', async () => {
  // One field for the whole chain produced exactly what it had to: a user
  // wrote "review this, and use the PO agent to check whether it makes
  // sense" and the reviewer read the second half as its own and answered
  // it. A sentence addressed to someone else is not context, it is a
  // confusing instruction.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [RG_PACK, PO_PACK] });

  const { asked, sent } = chainAskedAbout([
    { pack: RG_PACK }, { pack: PO_PACK },
    { label: '#479', pr: { number: 479, reviewed: false } },
    'walk the PR technically',
    'does this make product sense?',
  ]);

  await review.pickAndChain('C:/project', { appendLine() {} });

  assert.ok(asked.some((t) => /Reviewer — what is its part\?/.test(t)));
  assert.ok(asked.some((t) => /Product owner — what is its part\?/.test(t)));

  assert.ok(sent[0].includes('--focus "review-graph:walk the PR technically"'), sent[0]);
  assert.ok(sent[0].includes('--focus "po:does this make product sense?"'), sent[0]);
  assert.ok(!/\s--prompt\s/.test(sent[0]),
    'a shared prompt should be replaced by the split, not kept alongside it');
});

checkAsync('a member with no brief simply does not get one', async () => {
  // An empty answer is legitimate: the reviewer can handle a whole PR alone,
  // and a prompt only changes order and depth, not the rules.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [RG_PACK, PO_PACK] });

  const { sent } = chainAskedAbout([
    { pack: RG_PACK }, { pack: PO_PACK },
    { label: '#479', pr: { number: 479, reviewed: false } },
    '',
    'only PO has anything to look at',
  ]);

  await review.pickAndChain('C:/project', { appendLine() {} });

  assert.ok(!sent[0].includes('review-graph:'), sent[0]);
  assert.ok(sent[0].includes('--focus "po:only PO has anything to look at"'), sent[0]);
});

checkAsync('a team over the project only does not ask about a PR', async () => {
  // QA and PO both work over the project. A question nobody needs answered
  // is just one more step.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK, PO_PACK] });

  const { asked, sent } = chainAskedAbout([
    { pack: PO_PACK }, { pack: QA_PACK },
    'what should PO look at',
    'what should QA try',
  ]);

  await review.pickAndChain('C:/project', { appendLine() {} });

  assert.ok(!asked.some((t) => /which pull request/i.test(t)));
  // `--prompt` contains `--pr` as a substring, so the whole flag is searched for.
  assert.ok(!/\s--pr\s/.test(sent[0]), sent[0]);
});

checkAsync('an already-reviewed PR does not stop the team at its first step', async () => {
  // The user just picked it from a list where it was marked as such — that
  // is a choice, not a mistake. Without `--force` the chain would stop on
  // `already-reviewed`.
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [RG_PACK, PO_PACK] });

  const { sent } = chainAskedAbout([
    { pack: RG_PACK }, { pack: PO_PACK },
    { label: '#474', pr: { number: 474, reviewed: true } },
    '',
    '',
  ]);

  await review.pickAndChain('C:/project', { appendLine() {} });

  assert.ok(sent[0].includes('--force'), sent[0]);
});

checkAsync('a team needs at least two specialists', async () => {
  const review = require(path.join(SRC, 'review.js'));
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [QA_PACK] });
  const result = await review.pickAndChain('C:/project', { appendLine() {} });
  assert.strictEqual(result, null);
});

// -------------------------------------------------------------- package.json

check('the pack row offers "run" inline, not only in the context menu', () => {
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const menus = pkg.contributes.menus['view/item/context'];
  const run = menus.find((m) => m.command === 'agency.pack.run');
  assert.ok(run, 'missing agency.pack.run in the context menu');
  assert.strictEqual(run.when, 'viewItem == agencyPack');
  assert.ok(run.group.startsWith('inline'), 'an action only in the right-click menu is one nobody finds');
});

check('accept/defer/rejectPick/decision.apply are no longer contributed', () => {
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const ids = pkg.contributes.commands.map((c) => c.command);
  for (const gone of ['agency.finding.accept', 'agency.finding.defer',
    'agency.finding.rejectPick', 'agency.decision.apply',
    'agency.finding.reject.not-reproducible', 'agency.finding.reject.by-design',
    'agency.finding.reject.wrong-diagnosis', 'agency.finding.reject.duplicate-missed',
    'agency.finding.reject.out-of-scope']) {
    assert.ok(!ids.includes(gone), `${gone} should no longer be contributed`);
  }
  assert.ok(!('agency.rejectMenu' in (pkg.contributes.submenus || {})),
    'the reject submenu should be gone');
});

check('openOnBoard is inline on a finding row', () => {
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const ctx = pkg.contributes.menus['view/item/context'];
  const openOnBoard = ctx.find((m) => m.command === 'agency.finding.openOnBoard');
  assert.ok(openOnBoard, 'missing agency.finding.openOnBoard in the finding context menu');
  assert.strictEqual(openOnBoard.when, 'viewItem == agencyFinding');
  assert.ok(openOnBoard.group.startsWith('inline'));
});

check('Clear all sits on the Runs view title, a preset runs inline', () => {
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const title = pkg.contributes.menus['view/title'];
  const clearAll = title.find((m) => m.command === 'agency.runs.clearAll');
  assert.ok(clearAll, 'missing agency.runs.clearAll on a view title');
  assert.strictEqual(clearAll.when, 'view == agency.runs');

  const ctx = pkg.contributes.menus['view/item/context'];
  const run = ctx.find((m) => m.command === 'agency.preset.run');
  assert.ok(run, 'missing agency.preset.run in the preset context menu');
  assert.strictEqual(run.when, 'viewItem == agencyPreset');
  assert.ok(run.group.startsWith('inline'));
});

check('no leftover roster, provider-registry or Playwright-config commands remain', () => {
  // The whole point of this rewrite: a pack is a skill in the project, hired
  // by nobody, configured nowhere. These command ids belonged to the
  // roster/provider-registry/backlog-config design this replaced.
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const ids = pkg.contributes.commands.map((c) => c.command);
  for (const gone of ['agency.pack.add', 'agency.hire.add', 'agency.hire.remove',
    'agency.hire.run', 'agency.provider.add', 'agency.pack.brief', 'agency.qa.playwright',
    'agency.pack.openConfig']) {
    assert.ok(!ids.includes(gone), `${gone} should no longer be contributed`);
  }
});

check('Write a new specialist sits on the Specialists view title', () => {
  const pkg = require(path.join(SRC, '..', 'package.json'));
  const create = pkg.contributes.menus['view/title']
    .find((m) => m.command === 'agency.pack.create');
  assert.ok(create, 'missing agency.pack.create on a view title');
  assert.strictEqual(create.when, 'view == agency.tools');

  // Writing a specialist is a real thing to want from the palette too — it
  // is not a row action that needs a selection first.
  const hidden = (pkg.contributes.menus.commandPalette || [])
    .find((m) => m.command === 'agency.pack.create' && m.when === 'false');
  assert.ok(!hidden, 'agency.pack.create should stay in the command palette');
});

check('the author pack the client names is the one the repository ships', () => {
  // `AUTHOR_PACK` is the single hard-coded pack name in the extension —
  // unavoidable, because a run that writes a specialist cannot be started
  // from a row that does not exist yet. Renaming the reference pack without
  // this line would leave the button pointing at nothing, and the only
  // symptom would be a warning nobody expects.
  const review = require(path.join(SRC, 'review.js'));
  const manifest = require(path.join(SRC, '..', '..', '..', 'packs', 'author', 'pack.json'));
  assert.strictEqual(manifest.name, review.AUTHOR_PACK);
  assert.strictEqual(manifest.prompt, 'required',
    'the author cannot write a specialist nobody described');
  assert.strictEqual(manifest.target, 'workspace');
  assert.ok(!manifest.sink,
    'the author writes source, not findings — a sink would have nothing to send');
});

checkAsync('writing a specialist asks the description and the runner, then runs the author', async () => {
  const review = require(path.join(SRC, 'review.js'));
  const AUTHOR_PACK = {
    name: 'author', title: 'Pack author', skill: 'agency-author',
    description: 'Writes a new specialist for this project.',
    dimensions: [{ id: 'subject', title: 'What the specialist judges' }],
    requires: ['git'],
    run: { target: 'workspace', worktree: false, graph: null, prompt: 'required', needs: [] },
    minScore: 70,
  };
  Object.assign(state.snapshot, { probe: { ok: true }, cwd: 'C:/project', packs: [AUTHOR_PACK] });

  const cli = require(path.join(SRC, 'cli.js'));
  const prepared = [];
  cli.run = async (cwd, pack, opts) => {
    prepared.push({ pack, opts });
    return {
      ok: true,
      data: {
        runId: '01M1CGN9HAMBKK63SASPP2EYWJ', worktree: 'C:/project',
        agent: { provider: 'claude', model: 'opus' },
        target: { ref: 'main' }, launch: ['claude', 'go'],
      },
    };
  };

  // The pack declares no `needsUnattended`, so nothing may ask about
  // supervision — an authoring run touches nobody outside the repository.
  await review.runEach('C:/project', [AUTHOR_PACK],
    { prompt: 'watch our migrations', provider: 'claude', model: 'opus' }, { appendLine() {} });

  assert.strictEqual(prepared.length, 1);
  assert.strictEqual(prepared[0].pack, 'author');
  assert.strictEqual(prepared[0].opts.prompt, 'watch our migrations');
  assert.strictEqual(prepared[0].opts.provider, 'claude');
  assert.strictEqual(prepared[0].opts.model, 'opus',
    'the model picked for writing a SKILL.md has to reach the run, not be dropped here');
});

(async () => {
  for (const [name, fn] of pending) {
    try { await fn(); console.log(`  ok   ${name}`); }
    catch (e) { failed += 1; console.log(`  FAIL ${name}\n       ${e.message}`); }
  }
  console.log(failed ? `\n${failed} failed\n` : '\nall passed\n');
  process.exit(failed ? 1 : 0);
})();
