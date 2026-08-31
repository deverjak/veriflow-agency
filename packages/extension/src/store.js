// Sdílené úložiště rozhodnutí.
//
// Zapisují do něj DVA rovnocenní klienti: extension (člověk klikne) a CLI
// (agent zavolá `node tools/triage.js`). Ani jeden z nich není vlastník —
// vlastníkem je soubor. To je ve spiku zmenšenina toho, co v ostrém nástroji
// dělá .agency/runs/ podle implementation-plan-v0.md §2.2.
//
// Zápis je append-only událost, ne mutace stavu (plán §5, konvence 1) —
// aktuální stav se počítá přehráním. Díky tomu jde historii dvou zapisovatelů
// sloučit bez konfliktu.

const fs = require('fs');
const path = require('path');

const STATE_DIR = path.join(__dirname, '..', '.spike-state');
const FILE = path.join(STATE_DIR, 'decisions.json');

const REASONS = [
  'not-reproducible',
  'by-design',
  'wrong-diagnosis',
  'duplicate-missed',
  'out-of-scope',
];

const STATES = ['accepted', 'rejected', 'deferred'];

function storePath() { return FILE; }

/** @returns {{events: Array}} */
function readRaw() {
  try {
    return JSON.parse(fs.readFileSync(FILE, 'utf8'));
  } catch (_) {
    return { version: 1, events: [] };
  }
}

/** Aktuální stav = přehrání událostí. Poslední zápis k danému id vyhrává. */
function current() {
  const out = new Map();
  for (const e of readRaw().events) out.set(e.findingId, e);
  return out;
}

/**
 * @param {string} findingId
 * @param {'accepted'|'rejected'|'deferred'} state
 * @param {{reason?: string, note?: string, by?: string}} [opts]
 */
function append(findingId, state, opts = {}) {
  if (!STATES.includes(state)) {
    throw new Error(`neznámý stav "${state}", povolené: ${STATES.join(', ')}`);
  }
  if (state === 'rejected' && !opts.reason) {
    throw new Error(`zamítnutí vyžaduje důvod (--reason), povolené: ${REASONS.join(', ')}`);
  }
  if (opts.reason && !REASONS.includes(opts.reason)) {
    throw new Error(`neznámý důvod "${opts.reason}", povolené: ${REASONS.join(', ')}`);
  }
  const event = {
    findingId,
    state,
    reason: opts.reason || null,
    note: opts.note || null,
    by: opts.by || 'unknown',
    at: new Date().toISOString(),
  };
  const data = readRaw();
  data.events.push(event);
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(data, null, 2) + '\n', 'utf8');
  return event;
}

module.exports = { REASONS, STATES, storePath, readRaw, current, append };
