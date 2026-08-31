// Klient CLI.
//
// Extension nesahá na úložiště nálezů přímo — volá `agency`, stejně jako to
// dělá agent. Kdyby si četla soubory sama, vznikly by dva výklady téhož stavu
// a rozhodnutí by záviselo na tom, jestli je otevřený editor.
//
// Cena je spawn procesu na dotaz (~150–300 ms), což triage UI ustojí. Až to
// začne vadit, vymění se transport za dlouho žijící proces; kontrakt zůstane.

const cp = require('child_process');
const path = require('path');

/** Spustí `agency` a vrátí rozparsovaný JSON. */
function call(cwd, args) {
  return new Promise((resolve) => {
    cp.execFile('agency', [...args, '--json'],
      { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, windowsHide: true },
      (err, stdout, stderr) => {
        if (err && !stdout) {
          return resolve({ ok: false, error: (stderr || err.message || '').trim(), data: null });
        }
        try {
          resolve({ ok: true, error: null, data: JSON.parse(stdout) });
        } catch (e) {
          resolve({ ok: false, error: `nečitelný JSON z agency: ${e.message}`, data: null });
        }
      });
  });
}

async function available(cwd) {
  const r = await call(cwd, ['status', '--limit', '1']);
  return r.ok;
}

/** Nálezy napříč běhy, i s kotvou a driftem — ty jsou jen v --json. */
async function findings(cwd) {
  const r = await call(cwd, ['findings', '--all']);
  return r.ok ? (r.data || []) : [];
}

async function status(cwd) {
  const r = await call(cwd, ['status']);
  return r.ok ? (r.data || []) : [];
}

/**
 * Rozhodnutí. Jde touž cestou jako `agency triage` z terminálu nebo od agenta —
 * extension není vlastník, jen jeden ze tří rovnocenných klientů.
 */
async function triage(cwd, findingId, action, { reason, note } = {}) {
  const args = ['triage', action, findingId, '--by', 'vscode'];
  if (reason) args.push('--reason', reason);
  if (note) args.push('--note', note);
  return call(cwd, args);
}

/** PR k recenzi — otevřené i prošlé. Podklad pro klikací výběr. */
async function prs(cwd, { state = 'all', limit = 30 } = {}) {
  const r = await call(cwd, ['prs', '--state', state, '--limit', String(limit)]);
  return r.ok ? (r.data || []) : [];
}

/**
 * Deterministická příprava běhu. Vrací kde běh leží, kde je worktree a jakým
 * promptem ho dokončit — vlastní recenzi pouští uživatel v terminálu, protože
 * attended je vlastnost systému, ne úmysl.
 */
async function run(cwd, pack, { pr, latestMerged, force } = {}) {
  const args = ['run', pack];
  if (pr) args.push('--pr', String(pr));
  if (latestMerged) args.push('--latest-merged');
  if (force) args.push('--force');
  const r = await call(cwd, args);
  if (r.ok && r.data && r.data.ok === false) {
    return { ok: false, error: r.data.message, reason: r.data.reason, data: null };
  }
  return r;
}

/** Obsah souboru v den analýzy — `git show <commit>:<path>` v projektu. */
function showAtCommit(repo, commit, relPath) {
  return new Promise((resolve) => {
    cp.execFile('git', ['-C', repo, 'show', `${commit}:${relPath}`],
      { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, windowsHide: true },
      (err, stdout) => resolve(err ? null : stdout));
  });
}

module.exports = { call, available, findings, status, triage, prs, run, showAtCommit };
