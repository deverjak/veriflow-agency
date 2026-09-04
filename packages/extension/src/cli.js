// CLI client — the only path through which the extension touches data.
//
// The extension does not read `.agency/` from files, even though it could. If
// it did, there would be two interpretations of the same state — the run
// directories on disk, and whatever this process cached. This is the
// boundary from ui-surface-decision.md §4 — the extension is a viewer and a
// command issuer over runs and notes, never an owner of a finding's outcome.
// That now lives entirely with the pack's own gate and sink, and with a
// chain member's own `agency triage` — not with a click in the editor.
//
// The cost is a process spawn per query (~150-300 ms), which the panel
// tolerates. If that ever becomes a problem, the transport changes to a
// long-lived process; the contract stays.

const cp = require('child_process');
const vscode = require('vscode');

/** Path to the binary. A setting, because `uv tool install` can place it
 *  outside PATH. */
function bin() {
  return vscode.workspace.getConfiguration('agency').get('cliPath') || 'agency';
}

/**
 * Runs `agency … --json`.
 *
 * Always returns `{ok, error, data}` and NEVER throws — a CLI error is a
 * normal state (no project, missing `gh`, no run yet) and the UI has to be
 * able to show it, not crash on it.
 */
function call(cwd, args, { timeout = 60000 } = {}) {
  return new Promise((resolve) => {
    cp.execFile(bin(), [...args, '--json'], {
      cwd, encoding: 'utf8', timeout,
      maxBuffer: 64 * 1024 * 1024, windowsHide: true,
    }, (err, stdout, stderr) => {
      if (err && !stdout) {
        const msg = (stderr || err.message || '').trim();
        return resolve({
          ok: false, data: null,
          error: /ENOENT/.test(msg) ? `\`${bin()}\` is not on PATH` : msg,
        });
      }
      try {
        resolve({ ok: true, error: null, data: JSON.parse(stdout) });
      } catch (e) {
        resolve({ ok: false, data: null, error: `unreadable JSON from agency: ${e.message}` });
      }
    });
  });
}

/** Read helper: returns `fallback` on error instead of throwing. */
async function read(cwd, args, fallback) {
  const r = await call(cwd, args);
  return r.ok ? (r.data ?? fallback) : fallback;
}

// ---------------------------------------------------------------- diagnostics

/** Is the CLI available and are we in a project? Feeds the welcome screens. */
async function probe(cwd) {
  const r = await call(cwd, ['status', '--limit', '1'], { timeout: 15000 });
  if (r.ok) return { ok: true, reason: null, error: null };
  const noCli = /is not on PATH|ENOENT/.test(r.error || '');
  return {
    ok: false,
    reason: noCli ? 'no-cli' : /no git repository/.test(r.error || '') ? 'no-repo' : 'error',
    error: r.error,
  };
}

/**
 * Prerequisite checks. `agency doctor --json` wraps them in `{checks: […]}`
 * because a summary may join them later; the client unwraps that here, once,
 * so the rest of the extension sees a plain array.
 */
async function doctor(cwd) {
  const d = await read(cwd, ['doctor'], []);
  return Array.isArray(d) ? d : (d && d.checks) || [];
}

/** The specialists in this project — skills in `.claude/skills/agency-<name>/`. */
const packs = (cwd) => read(cwd, ['packs'], []);

/** Runs, with the project's own name/slug/installed packs alongside them —
 *  `agency status --json` carries both so the extension does not need a
 *  second call just to know whose repository this is. */
const status = (cwd) => read(cwd, ['status', '--limit', '25'], { project: null, runs: [] });

const metrics = (cwd) => read(cwd, ['metrics'], null);

/** Findings across runs — with anchor, drift and history. Those are `--json` only. */
const findings = (cwd) => read(cwd, ['findings', '--all'], []);

/** PRs to review, open and past. Backs the clickable picker. */
const prs = (cwd, { state = 'all', limit = 30 } = {}) =>
  read(cwd, ['prs', '--state', state, '--limit', String(limit)], []);

// ---------------------------------------------------------------- writes

/** A note. Its own command, because a note is NOT a decision. Deciding a
 *  finding is not this client's job any more — that happens through a
 *  chain member's own `agency triage`, or on the board itself. */
const note = (cwd, findingId, text) =>
  call(cwd, ['note', findingId, text, '--by', 'human']);

/** The gate: contract, existence, threshold, dedup. Run after the agent finishes. */
const ingest = (cwd, runId) =>
  call(cwd, runId ? ['ingest', '--run', runId] : ['ingest'], { timeout: 180000 });

/**
 * The deterministic preparation of a run. Returns where it lives, where its
 * worktree is, and the exact command to finish it with — the shape of that
 * command belongs to the CLI, not to this client. If the client assembled it
 * too, there would be a second place to set the model, and the run record
 * would then be lying about one of them.
 */
async function run(cwd, pack, { pr, latestMerged, force, model, provider,
  bypass, prompt, since } = {}) {
  // Where the person was standing when they asked. An enum value nothing ever
  // writes is a lie in the schema, so the client that is not the terminal says so.
  const args = ['run', pack, '--origin', 'extension'];
  if (pr) args.push('--pr', String(pr));
  if (latestMerged) args.push('--latest-merged');
  if (force) args.push('--force');
  if (model) args.push('--model', model);
  if (provider) args.push('--provider', provider);
  if (bypass) args.push('--bypass');
  // The prompt goes to the CLI as an argument, not assembled here. If the
  // extension composed it, there would be a second place a run comes into
  // being, and the run record would lie about what the agent actually ran with.
  if (prompt) args.push('--prompt', prompt);
  if (since) args.push('--since', since);
  const r = await call(cwd, args, { timeout: 15 * 60 * 1000 });
  if (r.ok && r.data && r.data.ok === false) {
    return { ok: false, error: r.data.message, reason: r.data.reason, data: null };
  }
  return r;
}

/**
 * Close a run whose terminal is gone, or delete it outright.
 *
 * Nothing in the extension can tell whether an agent is still alive: the run
 * happens in a terminal, and closing that terminal leaves no signal behind.
 * So this is never automatic — it is the user saying the run is over.
 */
const cleanup = (cwd, { run, unfinished, discard, all, force } = {}) => {
  const args = ['cleanup'];
  if (run) args.push('--run', run);
  if (unfinished) args.push('--unfinished');
  if (discard) args.push('--discard');
  if (all) args.push('--all');
  if (force) args.push('--force');
  return call(cwd, args, { timeout: 120000 });
};

module.exports = {
  bin, call, probe,
  doctor, packs, status, metrics, findings, prs,
  note, ingest, run, cleanup,
};
