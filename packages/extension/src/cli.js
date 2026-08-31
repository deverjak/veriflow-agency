// Klient CLI — jediná cesta, kterou extension sahá na data.
//
// Extension nečte `.agency/` ze souborů, i když by mohla. Kdyby to dělala,
// vznikly by dva výklady téhož stavu a agent by přestal být rovnocenný klient:
// jeho `agency triage` by šel jinudy než klik v editoru. Tohle je ta hranice
// z ui-surface-decision.md §4 — extension je viewer a zadavatel příkazů,
// nikdy vlastník stavu.
//
// Cena je spawn procesu na dotaz (~150–300 ms), což triage UI ustojí. Až to
// začne vadit, vymění se transport za dlouho žijící proces; kontrakt zůstane.

const cp = require('child_process');
const vscode = require('vscode');

/** Cesta k binárce. Nastavení, protože `uv tool install` ji umí položit mimo PATH. */
function bin() {
  return vscode.workspace.getConfiguration('agency').get('cliPath') || 'agency';
}

/**
 * Spustí `agency … --json`.
 *
 * Vrací vždy `{ok, error, data}` a NIKDY nevyhazuje — chyba CLI je normální
 * stav (není projekt, chybí `gh`, neproběhl běh) a UI ji má umět ukázat, ne
 * na ni spadnout.
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

/** Pomocník pro čtení: při chybě vrátí `fallback`, ne výjimku. */
async function read(cwd, args, fallback) {
  const r = await call(cwd, args);
  return r.ok ? (r.data ?? fallback) : fallback;
}

// ---------------------------------------------------------------- diagnostika

/** Je CLI dostupné a jsme v projektu? Odpověď krmí uvítací obrazovky. */
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

const init = (cwd) => read(cwd, ['init'], null);

/**
 * Kontroly předpokladů. `agency doctor --json` je balí do `{checks: […]}`,
 * protože k nim časem přibude souhrn; klient to rozbalí tady, na jednom místě,
 * a zbytek extension vidí prosté pole.
 */
async function doctor(cwd) {
  const d = await read(cwd, ['doctor'], []);
  return Array.isArray(d) ? d : (d && d.checks) || [];
}
const packs = (cwd) => read(cwd, ['packs'], []);
const status = (cwd) => read(cwd, ['status', '--limit', '25'], []);
const metrics = (cwd) => read(cwd, ['metrics'], null);
const projects = (cwd) => read(cwd, ['projects'], []);

/** Nálezy napříč běhy — s kotvou, driftem a historií. Ty jsou jen v `--json`. */
const findings = (cwd) => read(cwd, ['findings', '--all'], []);

/** PR k recenzi, otevřené i prošlé. Podklad pro klikací výběr. */
const prs = (cwd, { state = 'all', limit = 30 } = {}) =>
  read(cwd, ['prs', '--state', state, '--limit', String(limit)], []);

// ---------------------------------------------------------------- zápis

/**
 * Rozhodnutí. Jde touž cestou jako `agency triage` z terminálu nebo od agenta —
 * extension není vlastník, jen jeden ze tří rovnocenných klientů.
 */
function triage(cwd, findingId, action, { reason, note } = {}) {
  const args = ['triage', action, findingId, '--by', 'vscode'];
  if (reason) args.push('--reason', reason);
  if (note) args.push('--note', note);
  return call(cwd, args);
}

/** Poznámka. Vlastní příkaz, protože poznámka NENÍ rozhodnutí. */
const note = (cwd, findingId, text) =>
  call(cwd, ['note', findingId, text, '--by', 'vscode']);

/** Brána: kontrakt, existence, práh, dedup. Pouští se po doběhnutí agenta. */
const ingest = (cwd, runId) =>
  call(cwd, runId ? ['ingest', '--run', runId] : ['ingest'], { timeout: 180000 });

/**
 * Deterministická příprava běhu. Vrací, kde běh leží, kde je worktree a jakým
 * příkazem ho dokončit — tvar spouštění vlastní CLI, ne klient. Kdyby si ho
 * skládala i extension, vznikne druhé místo, kde se dá nastavit model, a
 * run record by lhal.
 */
async function run(cwd, pack, { pr, latestMerged, force, model, provider,
  prompt, scenario, since } = {}) {
  const args = ['run', pack];
  if (pr) args.push('--pr', String(pr));
  if (latestMerged) args.push('--latest-merged');
  if (force) args.push('--force');
  if (model) args.push('--model', model);
  if (provider) args.push('--provider', provider);
  // Zadání jde do CLI jako argument, ne do promptu poskládaného tady. Kdyby si
  // ho skládala extension, vzniklo by druhé místo, kde běh vzniká, a run record
  // by o tom, s čím agent běžel, lhal.
  if (prompt) args.push('--prompt', prompt);
  if (scenario) args.push('--scenario', scenario);
  if (since) args.push('--since', since);
  const r = await call(cwd, args, { timeout: 15 * 60 * 1000 });
  if (r.ok && r.data && r.data.ok === false) {
    return { ok: false, error: r.data.message, reason: r.data.reason, data: null };
  }
  return r;
}

const addPack = (cwd, pack) => call(cwd, ['add', pack]);

/**
 * Konfigurace packu i s tím, co si nástroj o projektu domyslel.
 *
 * Zápis jde touž cestou jako `agency config` z terminálu — nastavení bydlí
 * v projektu, ne v editoru, takže co nastavíš klikem, platí i pro běh
 * z terminálu a pro agenta.
 */
const packConfig = (cwd, pack) => call(cwd, ['config', pack]);

const setConfig = (cwd, pack, values) => {
  const args = ['config', pack];
  for (const [key, value] of Object.entries(values || {})) {
    args.push('--set', `${key}=${JSON.stringify(value)}`);
  }
  return call(cwd, args);
};

/** Trvalé zadání packu a jeho pojmenované scénáře — čtení i zápis. */
const brief = (cwd, pack, { set, scenario, remove } = {}) => {
  const args = ['brief', pack];
  if (scenario) args.push('--scenario', scenario);
  if (remove) args.push('--remove');
  else if (set !== undefined && set !== null) args.push('--set', set);
  return call(cwd, args);
};

module.exports = {
  bin, call, probe,
  init, doctor, packs, status, metrics, projects, findings, prs,
  triage, note, ingest, run, addPack, brief, packConfig, setConfig,
};
