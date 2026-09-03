// Shared UI state — one loaded snapshot every view reads from.
//
// Without this, four trees plus threads plus the status bar would each spawn
// their own `agency …` process on every redraw. The snapshot is taken once,
// views redraw from it, and `refresh()` is the only place that touches the CLI.
//
// State does NOT live here. It lives in `.agency/runs/` and this file is only
// a copy of it for rendering — which is why it can be thrown away and reloaded
// at any time.

const vscode = require('vscode');
const cli = require('./cli.js');

const emitter = new vscode.EventEmitter();

/** Views listen to this; they never touch the CLI themselves. */
const onDidChange = emitter.event;

const snapshot = {
  cwd: null,
  /** {ok, reason, error} — why the UI shows a welcome screen instead of data */
  probe: { ok: false, reason: 'loading', error: null },
  project: null,     // {name, slug, root, packs} — from `agency status`
  packs: [],
  runs: [],
  findings: [],
  metrics: null,
  doctor: [],
  loading: false,
  loadedAt: null,
};

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri.fsPath : null;
}

/** Findings resting with no board to go to — the one thing left that might
 *  actually need a person's attention, since everything else either went
 *  out through a sink already or is waiting on the next chain member. */
function candidates() {
  return snapshot.findings.filter((f) => f.state === 'candidate');
}

function findingById(id) {
  return snapshot.findings.find((f) => f.id === id) || null;
}

/**
 * Reloads everything. The only place in the extension that calls the CLI
 * for reads.
 *
 * `metrics` and `doctor` are loaded too — two extra processes, but they
 * answer "is this paying off?" and "why isn't this working?", which
 * otherwise have to be looked up in the terminal.
 */
async function refresh({ light = false } = {}) {
  const cwd = workspaceRoot();
  snapshot.cwd = cwd;
  if (!cwd) {
    snapshot.probe = { ok: false, reason: 'no-folder', error: null };
    emitter.fire();
    return snapshot;
  }

  snapshot.loading = true;
  emitter.fire();

  snapshot.probe = await cli.probe(cwd);
  if (!snapshot.probe.ok) {
    snapshot.findings = [];
    snapshot.runs = [];
    snapshot.loading = false;
    emitter.fire();
    return snapshot;
  }

  const [findings, statusData] = await Promise.all([cli.findings(cwd), cli.status(cwd)]);
  snapshot.findings = findings || [];
  snapshot.runs = (statusData && statusData.runs) || [];
  snapshot.project = (statusData && statusData.project) || snapshot.project;

  if (!light) {
    const [packs, metrics, doctor] = await Promise.all([
      cli.packs(cwd), cli.metrics(cwd), cli.doctor(cwd),
    ]);
    snapshot.packs = packs || [];
    snapshot.metrics = metrics || null;
    snapshot.doctor = doctor || [];
  }

  snapshot.loading = false;
  snapshot.loadedAt = new Date();
  emitter.fire();
  return snapshot;
}

module.exports = {
  snapshot, onDidChange, refresh, candidates, findingById, workspaceRoot, emitter,
};
