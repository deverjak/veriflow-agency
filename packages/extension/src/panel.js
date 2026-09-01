// Panely v editoru — detail nálezu, metriky, předpoklady.
//
// Do postranního panelu se vejde navigace, ne obsah. Nález má tvrzení, tělo,
// evidenci, kotvu a historii rozhodnutí; ve 300 px by to bylo nečitelné.
// Panel se otevře jako tab vedle kódu, v plné šířce, a rozhodnutí jde udělat
// odsud — takže nemusíš skákat zpátky do stromu.
//
// Theming jde přes `--vscode-*` proměnné, ne přes vlastní barvy. Stránka se tím
// sladí s aktivním tématem uživatele včetně vysokého kontrastu, a nemusí se to
// nikde udržovat. `@vscode/webview-ui-toolkit` je deprecated a nebere se.
//
// Žádné CDN, žádný bundler: obsah je jeden string, skript je inline s nonce.

const vscode = require('vscode');

const REASONS = [
  ['not-reproducible', 'Could not reproduce'],
  ['by-design', 'Behaves that way by design'],
  ['wrong-diagnosis', 'Wrong diagnosis — the problem is elsewhere'],
  ['duplicate-missed', 'Duplicate the dedup missed'],
  ['out-of-scope', 'Out of scope for this project'],
];

const DRIFT_NOTE = {
  untouched: ['ok', 'The code has not changed since the analysis',
    'The finding holds literally — the line numbers still match.'],
  touched: ['warn', 'This code was touched since the analysis',
    'It may already be fixed. Look at the diff first, so you do not reject something that was true.'],
  deleted: ['warn', 'The file was deleted after the analysis',
    'The code as of the analysis is still readable — from the commit, or from the body stored in the finding.'],
  unknown: ['dim', 'The commit is not in this clone',
    'Drift cannot be evaluated. `git fetch origin <sha>` usually helps.'],
};

const EVIDENCE_KIND = {
  graph: 'fact from the code graph',
  rule: 'project rule',
  'test-gap': 'missing coverage',
  diff: 'content of the change',
  runtime: 'observed behaviour',
  doc: 'contradicts the documentation',
};

function esc(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Minimální markdown. Záměrně neúplný: nálezy píše pack podle skillu, takže
 * repertoár je známý — tučné, kód, odrážky, odstavce. Plnohodnotný parser by
 * znamenal závislost, kterou by CSP stejně nepustila.
 */
function md(text) {
  const lines = esc(text).split('\n');
  const out = [];
  let list = false;
  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\s)_([^_]+)_/g, '$1<em>$2</em>');
  for (const raw of lines) {
    const l = raw.trim();
    if (/^[-*]\s+/.test(l)) {
      if (!list) { out.push('<ul>'); list = true; }
      out.push(`<li>${inline(l.replace(/^[-*]\s+/, ''))}</li>`);
      continue;
    }
    if (list) { out.push('</ul>'); list = false; }
    if (!l) continue;
    if (/^#{1,4}\s/.test(l)) {
      out.push(`<h4>${inline(l.replace(/^#{1,4}\s/, ''))}</h4>`);
      continue;
    }
    out.push(`<p>${inline(l)}</p>`);
  }
  if (list) out.push('</ul>');
  return out.join('\n');
}

const CSS = `
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
  color: var(--vscode-foreground); background: var(--vscode-editor-background);
  margin: 0; padding: 0 0 4rem;
}
.wrap { max-width: 62rem; margin: 0 auto; padding: 1.6rem 2rem; }
h1 { font-size: 1.35rem; line-height: 1.35; margin: 0 0 .4rem; font-weight: 600; }
h2 { font-size: .78rem; text-transform: uppercase; letter-spacing: .08em;
     color: var(--vscode-descriptionForeground); margin: 2rem 0 .6rem; font-weight: 600; }
h4 { font-size: .95rem; margin: 1rem 0 .3rem; }
p { line-height: 1.6; margin: .5rem 0; }
code { font-family: var(--vscode-editor-font-family); font-size: .9em;
       background: var(--vscode-textCodeBlock-background); padding: .1em .35em; border-radius: 3px; }
a { color: var(--vscode-textLink-foreground); }
ul { margin: .4rem 0; padding-left: 1.2rem; line-height: 1.6; }
.badges { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .8rem; }
.badge { font-size: .72rem; padding: .18rem .5rem; border-radius: 999px;
         border: 1px solid var(--vscode-panel-border); color: var(--vscode-descriptionForeground); }
.badge.sev-blocker, .badge.sev-high { border-color: var(--vscode-charts-red); color: var(--vscode-charts-red); }
.badge.sev-medium { border-color: var(--vscode-charts-orange); color: var(--vscode-charts-orange); }
.note { border-left: 3px solid var(--vscode-panel-border); padding: .55rem .9rem;
        margin: .8rem 0; background: var(--vscode-textBlockQuote-background); border-radius: 0 4px 4px 0; }
.note.ok { border-left-color: var(--vscode-charts-green); }
.note.warn { border-left-color: var(--vscode-charts-orange); }
.note strong { display: block; margin-bottom: .15rem; }
.note span { color: var(--vscode-descriptionForeground); font-size: .9em; }
.ev { border: 1px solid var(--vscode-panel-border); border-radius: 5px;
      padding: .6rem .8rem; margin: .5rem 0; }
.ev .kind { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
            color: var(--vscode-descriptionForeground); }
.ev .src { font-size: .8rem; color: var(--vscode-descriptionForeground); margin-top: .35rem;
           font-family: var(--vscode-editor-font-family); }
.grid { display: grid; grid-template-columns: 9rem 1fr; gap: .35rem 1rem; font-size: .9rem; }
.grid dt { color: var(--vscode-descriptionForeground); }
.grid dd { margin: 0; font-family: var(--vscode-editor-font-family); word-break: break-all; }
.bar { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center;
       position: sticky; bottom: 0; padding: .9rem 0 .2rem;
       background: var(--vscode-editor-background); border-top: 1px solid var(--vscode-panel-border); }
button { font-family: inherit; font-size: .88rem; padding: .4rem .9rem; border: none;
         border-radius: 3px; cursor: pointer;
         background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
button:hover { background: var(--vscode-button-hoverBackground); }
button.sec { background: var(--vscode-button-secondaryBackground);
             color: var(--vscode-button-secondaryForeground); }
button.sec:hover { background: var(--vscode-button-secondaryHoverBackground); }
select, textarea, input { font-family: inherit; font-size: .88rem; padding: .35rem .5rem;
        background: var(--vscode-input-background); color: var(--vscode-input-foreground);
        border: 1px solid var(--vscode-input-border, var(--vscode-panel-border)); border-radius: 3px; }
textarea { width: 100%; min-height: 4.5rem; resize: vertical; margin-top: .4rem; }
.hist { font-size: .88rem; border-left: 2px solid var(--vscode-panel-border);
        padding-left: .8rem; margin: .4rem 0; }
.hist .who { color: var(--vscode-descriptionForeground); font-size: .8rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--vscode-panel-border); }
th { color: var(--vscode-descriptionForeground); font-weight: 500; font-size: .8rem; }
td.num { text-align: right; font-family: var(--vscode-editor-font-family); }
.meter { display: inline-block; width: 7rem; height: .5rem; border-radius: 3px;
         background: var(--vscode-panel-border); overflow: hidden; vertical-align: middle; }
.meter i { display: block; height: 100%; background: var(--vscode-charts-green); }
.meter.mid i { background: var(--vscode-charts-orange); }
.meter.low i { background: var(--vscode-charts-red); }
.empty { color: var(--vscode-descriptionForeground); font-style: italic; }
.frow { display: grid; grid-template-columns: 13rem 1fr; gap: .3rem 1rem;
        align-items: center; padding: .5rem 0; border-bottom: 1px solid var(--vscode-panel-border); }
.frow label { color: var(--vscode-descriptionForeground); }
.frow input[type=text], .frow select { width: 100%; }
.frow.check label { color: var(--vscode-foreground); grid-column: 1 / -1; }
.fhelp { grid-column: 2; font-size: .82rem; color: var(--vscode-descriptionForeground); line-height: 1.5; }
.frow.check .fhelp { grid-column: 1 / -1; }
`;

function shell(title, body, { script = '' } = {}) {
  const nonce = String(Math.random()).slice(2) + Date.now().toString(36);
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<title>${esc(title)}</title><style>${CSS}</style></head>
<body><div class="wrap">${body}</div>
${script ? `<script nonce="${nonce}">${script}</script>` : ''}
</body></html>`;
}

// ------------------------------------------------------------ detail nálezu

function findingHtml(f) {
  const sev = f.severity || 'low';
  const drift = DRIFT_NOTE[f.drift] || DRIFT_NOTE.unknown;
  const a = f.anchor || {};
  const resolved = f.resolved || {};
  const target = f.target || {};

  const badges = [
    `<span class="badge sev-${esc(sev)}">${esc(sev)}</span>`,
    f.dimension ? `<span class="badge">${esc(f.dimension)}</span>` : '',
    f.pack ? `<span class="badge">${esc(f.pack)}</span>` : '',
    typeof f.score === 'number' ? `<span class="badge">score ${f.score}</span>` : '',
    f.state === 'duplicate' ? '<span class="badge">duplicate</span>' : '',
  ].filter(Boolean).join('');

  const evidence = (f.evidence || []).map((e) => `
    <div class="ev">
      <div class="kind">${esc(EVIDENCE_KIND[e.kind] || e.kind)}</div>
      <div>${md(e.detail)}</div>
      ${e.source ? `<div class="src">${esc(e.source)}</div>` : ''}
    </div>`).join('') || '<p class="empty">Without evidence a finding would not pass the gate.</p>';

  const history = (f.history || []).map((h) => {
    if ((h.kind || 'decision') === 'note') {
      return `<div class="hist"><div>${md(h.text)}</div>
        <div class="who">note · ${esc(h.by)} · ${esc((h.at || '').slice(0, 16).replace('T', ' '))}</div></div>`;
    }
    const mark = { accepted: 'Accepted', rejected: 'Rejected', deferred: 'Deferred' }[h.state] || h.state;
    return `<div class="hist"><div><strong>${esc(mark)}</strong>${h.reason ? ` — <code>${esc(h.reason)}</code>` : ''}</div>
      ${h.note ? `<div>${md(h.note)}</div>` : ''}
      <div class="who">${esc(h.by)} · ${esc((h.at || '').slice(0, 16).replace('T', ' '))}</div></div>`;
  }).join('');

  const reasonOptions = REASONS.map(([v, l]) =>
    `<option value="${v}">${esc(l)}</option>`).join('');

  return shell(f.title || 'Finding', `
    <div class="badges">${badges}</div>
    <h1>${esc(f.title)}</h1>

    <h2>What it claims</h2>
    ${md(f.body)}

    <h2>What backs it up</h2>
    ${evidence}

    <h2>Where it is</h2>
    <div class="note ${drift[0]}"><strong>${esc(drift[1])}</strong><span>${esc(drift[2])}</span></div>
    <dl class="grid">
      <dt>file</dt><dd>${esc(a.file || '—')}</dd>
      <dt>line</dt><dd>${esc(a.line)}${resolved.line && resolved.line !== a.line
        ? ` → today ${esc(resolved.line)}` : ''}${resolved.via ? ` <span class="empty">(${esc(resolved.via)})</span>` : ''}</dd>
      ${a.symbol ? `<dt>symbol</dt><dd>${esc(a.symbol.name)}</dd>` : ''}
      <dt>commit</dt><dd>${esc((a.commit || '').slice(0, 12))}</dd>
      ${target.pr ? `<dt>source</dt><dd>PR #${esc(target.pr)}${target.mergedAt
        ? ' · retrospective audit' : ''}</dd>` : ''}
      <dt>run</dt><dd>${esc(f.runId)}</dd>
    </dl>
    <div class="bar">
      <button class="sec" data-cmd="open">Open in code</button>
      <button class="sec" data-cmd="atCommit">Code as of the analysis</button>
      ${f.drift === 'touched' ? '<button class="sec" data-cmd="diff">Compare with today</button>' : ''}
    </div>

    <h2>Decision</h2>
    ${f.decision
      ? `<div class="note ok"><strong>${esc({ accepted: 'Accepted', rejected: 'Rejected', deferred: 'Deferred' }[f.decision])}${f.reason ? ` — ${esc(f.reason)}` : ''}</strong>
         <span>A decision is an append-only event — it can be overwritten by a new one, the history stays.</span></div>`
      : `<p class="empty">Undecided so far. Until you decide it, it does not count towards precision.</p>`}
    ${history ? `<div>${history}</div>` : ''}

    <div class="bar">
      <button data-cmd="accept">Accept</button>
      <button class="sec" data-cmd="defer">Defer</button>
      <select id="reason">${reasonOptions}</select>
      <button class="sec" data-cmd="reject">Reject</button>
    </div>
    <textarea id="note" placeholder="Note — free text for the reader. It is stored separately from the decision, because precision is computed from decisions."></textarea>
    <div class="bar"><button class="sec" data-cmd="note">Save note</button></div>
  `, {
    script: `
      const vs = acquireVsCodeApi();
      document.querySelectorAll('button[data-cmd]').forEach((b) => {
        b.addEventListener('click', () => {
          const reasonEl = document.getElementById('reason');
          const noteEl = document.getElementById('note');
          vs.postMessage({
            cmd: b.dataset.cmd,
            reason: reasonEl ? reasonEl.value : null,
            note: noteEl ? noteEl.value.trim() : '',
          });
          if (noteEl && (b.dataset.cmd === 'note')) noteEl.value = '';
        });
      });
    `,
  });
}

// ------------------------------------------------------------------ metriky

function meter(p) {
  if (p === null || p === undefined) return '<span class="empty">—</span>';
  const cls = p >= 0.7 ? '' : p >= 0.4 ? 'mid' : 'low';
  return `<span class="meter ${cls}"><i style="width:${Math.round(p * 100)}%"></i></span> `
    + `${Math.round(p * 100)} %`;
}

function tallyTable(title, rows) {
  const entries = Object.entries(rows || {}).filter(([, v]) => v.accepted + v.rejected);
  if (!entries.length) return '';
  return `<h2>${esc(title)}</h2><table><tr><th></th><th>precision</th>
    <th class="num">accepted</th><th class="num">rejected</th></tr>` +
    entries.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${meter(v.precision)}</td>
      <td class="num">${v.accepted}</td><td class="num">${v.rejected}</td></tr>`).join('') +
    '</table>';
}

/**
 * How often two specialists land on the same thing.
 *
 * Only shown once two of them have actually met over the same code — with one
 * worker the number is always zero and would read as a failure rather than as
 * "not applicable".
 */
function agreementHtml(a) {
  if (!a || a.hires <= 1 || !(a.crossHire || a.sameHire)) return '';
  return `
    <h2>Agreement</h2>
    <dl class="grid">
      <dt>found by another specialist too</dt><dd>${a.crossHire}</dd>
      <dt>found twice by the same one</dt><dd>${a.sameHire}</dd>
    </dl>
    <div class="note"><strong>A repeat is credited to whoever found it, never to the
      overall number.</strong>
      <span>The second specialist to arrive is marked as a duplicate and never reaches
      triage — under “By specialist” it would look like it found nothing, so there it
      inherits the decision of the finding it repeats. Counting it twice in the overall
      precision would inflate the one number the whole tool is judged by.
      A high first row means the second runner is buying confirmation rather than
      coverage — which is a reason to run them on different pull requests.</span></div>`;
}

function metricsHtml(m) {
  if (!m) return shell('Metrics', '<p class="empty">Metrics could not be loaded.</p>');
  const t = m.triage, f = m.findings, q = m.queue;
  return shell('Metrics', `
    <h1>${esc(m.project.name)}</h1>
    <div class="badges"><span class="badge">${m.runs} runs</span></div>

    <h2>Precision</h2>
    <p style="font-size:1.4rem">${meter(t.precision)}</p>
    <p>${t.accepted} accepted · ${t.rejected} rejected · ${t.undecided} undecided</p>
    <div class="note"><strong>Computed only from decided findings.</strong>
      <span>An undecided finding is neither true nor false. If it fell into the denominator,
      every new run would dilute precision and the number would measure the speed of triage,
      not the quality of the findings.</span></div>

    <h2>Through the gate</h2>
    <dl class="grid">
      <dt>written by pack</dt><dd>${f.raw}</dd>
      <dt>passed</dt><dd>${f.kept}${f.gateYield !== null ? ` (${Math.round(f.gateYield * 100)} %)` : ''}</dd>
      <dt>duplicates</dt><dd>${f.duplicates}${f.dedupRatio ? ` (${Math.round(f.dedupRatio * 100)} %)` : ''}</dd>
      ${f.gatedBy ? `<dt>dropped</dt><dd>${esc(Object.entries(f.gatedBy)
        .map(([k, v]) => `${v}× ${k}`).join(', '))}</dd>` : ''}
    </dl>

    <h2>Queue</h2>
    <dl class="grid">
      <dt>waiting</dt><dd>${q.undecided}</dd>
      ${q.medianAgeDays !== null ? `<dt>median age</dt><dd>${q.medianAgeDays} days</dd>` : ''}
      ${q.oldestDays !== null ? `<dt>oldest</dt><dd>${q.oldestDays} days</dd>` : ''}
      ${m.cost.secondsPerKeptFinding ? `<dt>cost</dt><dd>${m.cost.secondsPerKeptFinding} s per finding</dd>` : ''}
    </dl>

    ${tallyTable('By dimension', m.byDimension)}
    ${tallyTable('By severity', m.bySeverity)}
    ${tallyTable('By specialist', m.byHire)}
    ${tallyTable('By model', m.byModel)}
    ${agreementHtml(m.agreement)}
    ${m.rejectReasons ? `<h2>Reasons for rejection</h2><table>` +
      Object.entries(m.rejectReasons).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join('') + '</table>' : ''}
  `);
}

// -------------------------------------------------------------- předpoklady

function doctorHtml(checks) {
  const rows = (checks || []).map((c) => `
    <div class="note ${c.ok ? 'ok' : c.fatal ? 'warn' : 'dim'}">
      <strong>${c.ok ? '✓' : c.fatal ? '✗' : '!'} ${esc(c.name)}</strong>
      <span>${esc(c.detail)}</span>
    </div>`).join('');
  const bad = (checks || []).filter((c) => !c.ok).length;
  return shell('Prerequisites', `
    <h1>Prerequisites for a run</h1>
    <p>${bad ? `${bad} ${bad === 1 ? 'thing is' : 'things are'} not in order.` : 'Everything is ready.'}</p>
    <div class="note"><strong>Checked BEFORE a run, not halfway through it.</strong>
      <span>A run that dies after ten minutes on a missing login costs more than a
      check that takes a second.</span></div>
    ${rows}
  `);
}

// ------------------------------------------------------------- prohlížeč

/** Pole formuláře. Klíč je dotted path do konfigurace packu — víc o nich neví ani panel, ani extension. */
const PW_FIELDS = [
  {
    key: 'playwright.enabled', type: 'bool', label: 'Drive a real browser',
    help: 'Off, the session only reaches what it can over HTTP. On, it explores through '
      + 'Playwright and writes a failing spec for every finding.',
  },
  {
    key: 'playwright.specTarget', type: 'choice', label: 'Where reproduction specs go',
    options: [
      ['run', 'Into the run directory — nothing changes in the repository'],
      ['suite', "Into the project's own test suite"],
    ],
    help: 'A spec in the run directory travels with the finding and can be re-run a year '
      + 'later. Moving it into the suite is a decision about the repository, so it is opt-in.',
  },
  {
    key: 'playwright.scaffold', type: 'choice', label: 'When the project has no Playwright',
    options: [
      ['run-dir', 'Set one up inside the run directory'],
      ['project', 'May add playwright.config and the dependency to the project'],
      ['never', 'Stop and tell me what to run'],
    ],
  },
  { key: 'playwright.configFile', type: 'text', label: 'Project config', placeholder: 'playwright.config.ts' },
  { key: 'playwright.projectTestDir', type: 'text', label: "Project's specs", placeholder: 'e2e' },
  { key: 'playwright.command', type: 'text', label: 'Test command', placeholder: 'npx playwright test' },
  { key: 'playwright.browsers', type: 'list', label: 'Browsers', placeholder: 'chromium, firefox, webkit' },
  { key: 'playwright.headed', type: 'bool', label: 'Headed browser', help: 'Watch the session run. Slower.' },
  {
    key: 'playwright.artifacts.trace', type: 'choice', label: 'Trace',
    options: [['retain-on-failure', 'Keep on failure'], ['on', 'Always'], ['off', 'Never']],
    help: 'The strongest runtime evidence there is: DOM, network and console at the moment of failure.',
  },
  {
    key: 'playwright.artifacts.screenshot', type: 'choice', label: 'Screenshot',
    options: [['only-on-failure', 'On failure'], ['on', 'Always'], ['off', 'Never']],
  },
  {
    key: 'playwright.artifacts.video', type: 'choice', label: 'Video',
    options: [['off', 'Never'], ['retain-on-failure', 'Keep on failure'], ['on', 'Always']],
  },
  {
    key: 'playwright.storageStateFile', type: 'text', label: 'Signed-in state',
    placeholder: '.agency/qa-storage-state.local.json',
    help: 'Must not be committed — it is a session token.',
  },
  { key: 'app.baseUrl', type: 'text', label: 'Application URL', placeholder: 'http://localhost:3000' },
  {
    key: 'app.startPolicy', type: 'choice', label: 'Starting the application',
    options: [['manual', 'I start it myself'], ['agent', 'The session may start it']],
  },
  { key: 'app.start', type: 'text', label: 'Start command', placeholder: 'npm run dev' },
];

function dig(obj, dotted) {
  return dotted.split('.').reduce((cur, part) =>
    (cur && typeof cur === 'object' ? cur[part] : undefined), obj);
}

function field(f, value) {
  const id = `f_${f.key.replace(/\./g, '_')}`;
  const help = f.help ? `<div class="fhelp">${esc(f.help)}</div>` : '';
  let control;
  if (f.type === 'bool') {
    control = `<input type="checkbox" id="${id}" data-key="${esc(f.key)}" data-type="bool"${value ? ' checked' : ''}>`;
    return `<div class="frow check"><label for="${id}">${control} ${esc(f.label)}</label>${help}</div>`;
  }
  if (f.type === 'choice') {
    control = `<select id="${id}" data-key="${esc(f.key)}" data-type="text">`
      + f.options.map(([v, l]) =>
        `<option value="${esc(v)}"${String(value) === v ? ' selected' : ''}>${esc(l)}</option>`).join('')
      + '</select>';
  } else {
    const shown = f.type === 'list' ? (Array.isArray(value) ? value.join(', ') : '') : (value ?? '');
    control = `<input type="text" id="${id}" data-key="${esc(f.key)}" data-type="${f.type}"
      value="${esc(shown)}" placeholder="${esc(f.placeholder || '')}">`;
  }
  return `<div class="frow"><label for="${id}">${esc(f.label)}</label>${control}${help}</div>`;
}

/**
 * Nastavení prohlížeče pro QA sezení.
 *
 * Formulář, ne prosba o ruční editaci JSONu: tohle je jediné místo v celé
 * Agency, kde má uživatel měnit nastavení běhu, aniž by věděl, jak se
 * konfigurace jmenuje. Uložení jde přes `agency config`, takže výsledek
 * platí i pro terminál a pro agenta.
 */
function playwrightHtml({ pack, config = {}, detected = {} }) {
  const pw = detected.playwright || {};
  const found = pw.present
    ? ['ok', `The project already has Playwright — ${esc(pw.configFile || 'no config file')}`,
      `${pw.specs || 0} specs in ${esc(pw.testDir || '(unknown directory)')}. `
      + 'The session reuses it: its baseURL, its fixtures, its login. A spec that invents its '
      + 'own way of logging in is a second truth about the same thing.']
    : ['warn', 'The project has no Playwright',
      'With “Set one up inside the run directory” the session builds a throwaway config in the '
      + 'run directory and adds nothing to the repository.'];

  const rows = PW_FIELDS.map((f) => field(f, dig(config, f.key))).join('');

  return shell(`${pack} — browser`, `
    <h1>Browser testing</h1>
    <p>How the QA session drives the application, and what it may create in the project.</p>
    <div class="note ${found[0]}"><strong>${found[1]}</strong><span>${found[2]}</span></div>
    <form id="form">${rows}</form>
    <div class="note"><strong>The reproduction is a file, not a paragraph.</strong>
      <span>Every finding ships with the spec that fails on it. “Is it fixed?” is then answered
      by running it, not by another session.</span></div>
    <div class="bar">
      <button data-cmd="save">Save</button>
      <button class="sec" data-cmd="open">Open the configuration file</button>
      <span class="empty" id="state"></span>
    </div>
  `, {
    script: `
      const vscode = acquireVsCodeApi();
      const state = document.getElementById('state');
      document.querySelector('[data-cmd="open"]').addEventListener('click',
        () => vscode.postMessage({ cmd: 'open' }));
      document.querySelector('[data-cmd="save"]').addEventListener('click', () => {
        const values = {};
        document.querySelectorAll('#form [data-key]').forEach((el) => {
          const key = el.dataset.key;
          if (el.dataset.type === 'bool') values[key] = el.checked;
          else if (el.dataset.type === 'list') {
            values[key] = el.value.split(',').map((s) => s.trim()).filter(Boolean);
          } else values[key] = el.value.trim() === '' ? null : el.value.trim();
        });
        state.textContent = 'saving…';
        vscode.postMessage({ cmd: 'save', values });
      });
      window.addEventListener('message', (e) => {
        if (e.data && e.data.saved) state.textContent = e.data.saved;
      });
    `,
  });
}

module.exports = {
  shell, esc, md, findingHtml, metricsHtml, doctorHtml, playwrightHtml, REASONS, PW_FIELDS,
};
