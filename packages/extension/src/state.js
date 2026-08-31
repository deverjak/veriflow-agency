// Sdílený stav UI — jeden načtený snímek, ze kterého čtou všechny pohledy.
//
// Bez tohohle by čtyři stromy plus vlákna plus stavový řádek spustily při každém
// překreslení vlastní `agency …` proces. Snímek se pořídí jednou, pohledy se
// překreslí z něj, a `refresh()` je jediné místo, které sahá na CLI.
//
// Stav TADY NEŽIJE. Žije v `.agency/runs/` a tenhle soubor je jen jeho kopie
// pro vykreslení — proto se smí kdykoli celý zahodit a načíst znovu.

const vscode = require('vscode');
const cli = require('./cli.js');

const emitter = new vscode.EventEmitter();

/** Pohledy poslouchají tohle; nikdy nesahají na CLI samy. */
const onDidChange = emitter.event;

const snapshot = {
  cwd: null,
  /** {ok, reason, error} — proč UI ukazuje uvítání místo dat */
  probe: { ok: false, reason: 'loading', error: null },
  project: null,     // `agency init` — co nástroj o projektu ví
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

/** Nálezy k rozhodnutí. Duplicity a rozhodnuté se do fronty nepočítají. */
function queue() {
  return snapshot.findings.filter((f) => !f.decision && f.state !== 'duplicate');
}

function findingById(id) {
  return snapshot.findings.find((f) => f.id === id) || null;
}

/**
 * Načte všechno znovu. Jediné místo v extension, které volá CLI kvůli čtení.
 *
 * `metrics` a `doctor` se načítají taky — jsou to dva procesy navíc, ale
 * odpovídají na otázky „vyplácí se to?" a „proč to nejede?", které se jinak
 * musí hledat v terminálu.
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

  const [findings, runs] = await Promise.all([cli.findings(cwd), cli.status(cwd)]);
  snapshot.findings = findings || [];
  snapshot.runs = runs || [];

  if (!light) {
    const [packs, project, metrics, doctor] = await Promise.all([
      cli.packs(cwd), cli.init(cwd), cli.metrics(cwd), cli.doctor(cwd),
    ]);
    snapshot.packs = packs || [];
    snapshot.project = project || null;
    snapshot.metrics = metrics || null;
    snapshot.doctor = doctor || [];
  }

  snapshot.loading = false;
  snapshot.loadedAt = new Date();
  emitter.fire();
  return snapshot;
}

module.exports = { snapshot, onDidChange, refresh, queue, findingById, workspaceRoot, emitter };
