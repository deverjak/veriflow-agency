#!/usr/bin/env node
// Programatická triage — tohle volá agent.
//
// Ve spiku je to jeden soubor; v ostrém nástroji je to `agency triage`
// v Pythonu. Podstatné je, že to NENÍ příkaz VS Code: extension i agent
// zapisují do téhož úložiště přes tutéž vrstvu (src/store.js), takže žádný
// z nich není privilegovaný a rozhodnutí nezávisí na tom, jestli je otevřený
// editor.
//
//   node tools/triage.js list
//   node tools/triage.js accept f1
//   node tools/triage.js reject f5 --reason wrong-diagnosis --note "docblok je ok"
//   node tools/triage.js defer  f3
//   node tools/triage.js reject f5 --reason by-design --json

const fs = require('fs');
const path = require('path');
const store = require('../src/store.js');

const FIXTURES = path.join(__dirname, '..', 'src', 'fixtures.json');

function findings() {
  return JSON.parse(fs.readFileSync(FIXTURES, 'utf8')).findings;
}

function usage(code) {
  console.log(`
Použití:
  node tools/triage.js list [--json]
  node tools/triage.js accept <findingId> [--note "..."]
  node tools/triage.js reject <findingId> --reason <důvod> [--note "..."]
  node tools/triage.js defer  <findingId> [--note "..."]

Důvody zamítnutí: ${store.REASONS.join(' | ')}

Úložiště: ${store.storePath()}
`.trim());
  process.exit(code);
}

function parseFlags(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) { flags[key] = true; }
      else { flags[key] = next; i++; }
    }
  }
  return flags;
}

const [cmd, id, ...rest] = process.argv.slice(2);
const flags = parseFlags(rest);

if (!cmd || cmd === 'help' || cmd === '--help') usage(0);

if (cmd === 'list') {
  const cur = store.current();
  const rows = findings().map(f => ({
    id: f.id,
    severity: f.severity,
    file: f.anchor.file,
    line: f.anchor.line,
    title: f.title,
    decision: cur.get(f.id) || null,
  }));
  if (flags.json) { console.log(JSON.stringify(rows, null, 2)); process.exit(0); }
  const undecided = rows.filter(r => !r.decision).length;
  console.log(`\n${rows.length} nálezů, ${undecided} bez rozhodnutí\n`);
  for (const r of rows) {
    const d = r.decision;
    const mark = !d ? '·' : d.state === 'accepted' ? '✔' : d.state === 'rejected' ? '✘' : '⏱';
    const tail = d ? `${d.state}${d.reason ? ' / ' + d.reason : ''} (${d.by})` : '';
    console.log(`  ${mark} ${r.id.padEnd(3)} ${r.title.slice(0, 58).padEnd(60)} ${tail}`);
  }
  console.log('');
  process.exit(0);
}

if (!store.STATES.includes(cmd === 'accept' ? 'accepted' : cmd === 'reject' ? 'rejected' : cmd === 'defer' ? 'deferred' : cmd)) {
  console.error(`Neznámý příkaz "${cmd}".`);
  usage(1);
}
if (!id) { console.error('Chybí findingId.'); usage(1); }

const known = new Set(findings().map(f => f.id));
if (!known.has(id)) {
  console.error(`Nález "${id}" neexistuje. Známé: ${[...known].join(', ')}`);
  process.exit(1);
}

const state = cmd === 'accept' ? 'accepted' : cmd === 'reject' ? 'rejected' : 'deferred';

try {
  const ev = store.append(id, state, {
    reason: typeof flags.reason === 'string' ? flags.reason : undefined,
    note: typeof flags.note === 'string' ? flags.note : undefined,
    by: typeof flags.by === 'string' ? flags.by : 'cli',
  });
  if (flags.json) console.log(JSON.stringify(ev, null, 2));
  else console.log(`${id} → ${ev.state}${ev.reason ? ' · ' + ev.reason : ''}${ev.note ? ' · ' + ev.note : ''}`);
} catch (e) {
  console.error(`Chyba: ${e.message}`);
  process.exit(1);
}
