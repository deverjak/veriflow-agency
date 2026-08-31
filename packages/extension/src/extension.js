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

const SCHEME = 'agency';
const CONTROLLER_ID = 'agency.findings';

/** @type {vscode.CommentController} */
let controller;
/** @type {vscode.CommentThread[]} */
let threads = [];
/** @type {vscode.OutputChannel} */
let log;
/** rozhodnutí drží spike v paměti; v ostrém nástroji jde do .agency/runs/ */
const decisions = new Map();

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

async function buildThreads() {
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

    if (uri && line !== null) {
      const doc = await vscode.workspace.openTextDocument(uri);
      const safeLine = Math.min(Math.max(line, 1), doc.lineCount) - 1;
      const range = new vscode.Range(safeLine, 0, safeLine, 0);
      const thread = controller.createCommentThread(uri, range, [{
        body: makeBody(f, resolution, drift),
        mode: vscode.CommentMode.Preview,
        author: { name: `${severityIcon(f.severity)} review-graph` },
        contextValue: 'agencyFinding',
      }]);
      thread.label = f.title.slice(0, 70);
      thread.collapsibleState = vscode.CommentThreadCollapsibleState.Collapsed;
      thread.canReply = true;
      thread.contextValue = 'agencyFinding';
      // vlastní data pro handlery příkazů
      thread._agency = { finding: f, resolution, drift, repo, placed };
      threads.push(thread);
    }

    results.push({ f, drift, resolution, placed });
  }
  return { fx, results };
}

function clearThreads() {
  for (const t of threads) { try { t.dispose(); } catch (_) { /* už zaniklo */ } }
  threads = [];
}

// -------------------------------------------------------------------- report

function verdictLine(ok, text) { return `${ok ? '✅' : '❌'} ${text}`; }

async function runAllChecks() {
  const { fx, results } = await buildThreads();

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

function record(thread, state, reason) {
  const meta = thread && thread._agency;
  const id = meta ? meta.finding.id : '?';
  decisions.set(id, { state, reason: reason || null, at: new Date().toISOString() });
  log.appendLine(`[rozhodnutí] ${id} → ${state}${reason ? ' · ' + reason : ''}`);
  if (thread) {
    thread.state = state === 'accepted'
      ? vscode.CommentThreadState.Resolved
      : vscode.CommentThreadState.Unresolved;
    thread.label = `${state === 'accepted' ? '✔' : state === 'rejected' ? '✘' : '⏱'} ${thread.label}`;
  }
  vscode.window.setStatusBarMessage(`Agency: ${id} → ${state}`, 4000);
}

function activate(context) {
  log = vscode.window.createOutputChannel('Agency Spike');
  context.subscriptions.push(log);

  controller = vscode.comments.createCommentController(CONTROLLER_ID, 'Agency — nálezy');
  controller.commentingRangeProvider = { provideCommentingRanges: () => [] }; // uživatel nezakládá vlastní
  context.subscriptions.push(controller);

  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(
    SCHEME, new CommitContentProvider()));

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

  reg('agency.finding.accept', (arg) => record(threadOf(arg), 'accepted'));
  reg('agency.finding.defer', (arg) => record(threadOf(arg), 'deferred'));
  reg('agency.finding.reject', (arg) => {
    const t = threadOf(arg);
    const reason = (arg && arg.text) ? String(arg.text).trim() : '';
    if (!reason) {
      vscode.window.showWarningMessage('Zamítnutí chce důvod — napiš ho do pole odpovědi a klikni znovu.');
      return;
    }
    record(t, 'rejected', reason);
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

  log.appendLine('Agency spike aktivní. Spusť „Agency Spike: Spustit všechny kontroly".');
}

function deactivate() { clearThreads(); }

module.exports = { activate, deactivate };

// Vystaveno pro harness v test/ — spike musí jít vyhodnotit i bez spuštěného VS Code.
module.exports._internal = { driftCheck, resolveAnchor, loadFixtures, gitShow, commitExists, git };
