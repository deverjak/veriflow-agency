// Spustí logiku spiku BEZ VS Code — podstrčí falešný `vscode` modul.
// Ověří to jedinou věc, kterou lze ověřit strojově: rozlišení kotvy a test driftu
// na skutečných datech main-panelu. Zbytek (renderování vláken, tlačítka) chce F5.
//
//   node packages/extension/test/harness.js

const Module = require('module');
const fs = require('fs');
const path = require('path');

// ------------------------------------------------------------- fake `vscode`
const fake = {
  Uri: {
    file: (p) => ({ scheme: 'file', fsPath: p, path: p.replace(/\\/g, '/') }),
    from: (o) => ({ ...o, fsPath: o.path }),
  },
  workspace: {
    async openTextDocument(uri) {
      const p = uri.fsPath || uri.path;
      const lines = fs.readFileSync(p, 'utf8').split(/\r?\n/);
      return { lineCount: lines.length, lineAt: (i) => ({ text: lines[i] ?? '' }) };
    },
    registerTextDocumentContentProvider: () => ({ dispose() {} }),
  },
  window: {
    createOutputChannel: () => ({ appendLine() {}, dispose() {} }),
    showErrorMessage() {}, showWarningMessage() {}, showInformationMessage() {},
    setStatusBarMessage() {}, showTextDocument() {},
  },
  comments: { createCommentController: () => ({ dispose() {} }) },
  commands: { registerCommand: () => ({ dispose() {} }), executeCommand() {} },
  Range: class { constructor(a, b, c, d) { Object.assign(this, { a, b, c, d }); } },
  Selection: class {},
  MarkdownString: class { constructor() { this.value = ''; } appendMarkdown(s) { this.value += s; } },
  CommentMode: { Preview: 1, Editing: 0 },
  CommentThreadCollapsibleState: { Collapsed: 0, Expanded: 1 },
  CommentThreadState: { Unresolved: 1, Resolved: 0 },
  TextEditorRevealType: { InCenter: 2 },
};

const origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === 'vscode') return fake;
  return origLoad.call(this, request, ...rest);
};

const { _internal } = require('../src/extension.js');

// ---------------------------------------------------------------------- běh
const PASS = '[32mOK  [0m';
const FAIL = '[31mCHYBA[0m';
let failures = 0;

function check(cond, label, detail) {
  if (!cond) failures++;
  console.log(`  ${cond ? PASS : FAIL} ${label}${detail ? '  — ' + detail : ''}`);
}

(async () => {
  const fx = _internal.loadFixtures();
  console.log(`\nRepo:  ${fx.repo}`);
  console.log(`HEAD:  ${fx.head.slice(0, 8)}`);
  console.log(`Nálezů: ${fx.findings.length}\n`);

  const rows = [];
  for (const f of fx.findings) {
    const a = f.anchor;
    const drift = await _internal.driftCheck(fx.repo, a);
    const res = await _internal.resolveAnchor(fx.repo, a);
    const atCommit = await _internal.commitExists(fx.repo, a.commit)
      && (await _internal.gitShow(fx.repo, a.commit, a.file)) !== null;
    rows.push({ f, drift, res, atCommit });
  }

  console.log('  id  případ          drift       kotva                   řádek   commit-view');
  console.log('  ' + '-'.repeat(84));
  for (const r of rows) {
    console.log(`  ${r.f.id.padEnd(3)} ${r.f.case.padEnd(15)} ${r.drift.padEnd(11)} ` +
      `${r.res.via.padEnd(23)} ${String(r.res.line ?? '—').padEnd(7)} ${r.atCommit ? 'ano' : 'ne'}`);
    if (r.res.note) console.log(`      ${' '.repeat(58)}↳ ${r.res.note}`);
  }

  console.log('\nKontroly:\n');

  const noDrift = rows.filter(r => r.f.case === 'no-drift');
  check(noDrift.every(r => r.drift === 'untouched'),
    'pět skutečných nálezů z PR #460 hlásí nezměněný kód',
    noDrift.map(r => r.drift).join(','));
  check(noDrift.every(r => r.res.line === r.f.anchor.line),
    'a kotva u nich vrací původní řádek');

  const d = rows.find(r => r.f.case === 'drifted');
  check(d && d.res.line === d.f.expect.resolvedLine,
    `drift: řádek ${d && d.f.anchor.line} → očekáváno ${d && d.f.expect.resolvedLine}`,
    d ? `dostal ${d.res.line} přes „${d.res.via}"` : 'fixture chybí');
  // Pozor: `untouched` je tady SPRÁVNĚ. Soubor má +1012/-865, ale na ten konkrétní
  // řádek nikdo nesáhl — jen se posunul. Přesně to rozlišení triage potřebuje:
  // „přepsáno" (může být opravené) vs. „přesunuto" (platí doslova).
  check(d && d.drift === 'untouched',
    'drift: řádek se posunul, ale nezměnil → hlásí se untouched, ne touched',
    d ? d.drift : '');

  const del = rows.find(r => r.f.case === 'deleted');
  check(del && del.drift === 'deleted' && del.res.line === null,
    'smazaný soubor: nekotví se do pracovní kopie',
    del ? `drift=${del.drift} řádek=${del.res.line}` : '');
  check(del && del.atCommit, 'smazaný soubor: jde přesto zobrazit z commitu (případ B)');

  const oob = rows.find(r => r.f.case === 'out-of-bounds');
  check(oob && oob.res.line === null,
    'řádek za koncem souboru: kotva odmítne, nepřistane tiše',
    oob ? oob.res.note : '');

  console.log(`\n${failures === 0 ? '[32mVšechny kontroly prošly.[0m'
    : `[31m${failures} kontrol(a) selhala.[0m`}\n`);
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
