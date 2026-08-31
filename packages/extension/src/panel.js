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
  ['not-reproducible', 'Nešlo zopakovat'],
  ['by-design', 'Chová se tak záměrně'],
  ['wrong-diagnosis', 'Špatná diagnóza — problém je jinde'],
  ['duplicate-missed', 'Duplicita, kterou dedup nechytil'],
  ['out-of-scope', 'Mimo rozsah projektu'],
];

const DRIFT_NOTE = {
  untouched: ['ok', 'Kód je od analýzy nezměněný', 'Nález platí doslova — čísla řádků sedí.'],
  touched: ['warn', 'Na tenhle kód se od analýzy sáhlo',
    'Může být už opravené. Podívej se nejdřív na diff, ať nezamítáš něco, co platilo.'],
  deleted: ['warn', 'Soubor byl od analýzy smazaný',
    'Kód v den analýzy je pořád k přečtení — z commitu, případně z těla uloženého v nálezu.'],
  unknown: ['dim', 'Commit v klonu není', 'Drift se nedá vyhodnotit. `git fetch origin <sha>` obvykle pomůže.'],
};

const EVIDENCE_KIND = {
  graph: 'fakt z grafu kódu',
  rule: 'pravidlo projektu',
  'test-gap': 'chybějící pokrytí',
  diff: 'obsah změny',
  runtime: 'pozorované chování',
  doc: 'rozpor s dokumentací',
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
`;

function shell(title, body, { script = '' } = {}) {
  const nonce = String(Math.random()).slice(2) + Date.now().toString(36);
  return `<!DOCTYPE html><html lang="cs"><head><meta charset="utf-8">
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
    f.state === 'duplicate' ? '<span class="badge">duplicita</span>' : '',
  ].filter(Boolean).join('');

  const evidence = (f.evidence || []).map((e) => `
    <div class="ev">
      <div class="kind">${esc(EVIDENCE_KIND[e.kind] || e.kind)}</div>
      <div>${md(e.detail)}</div>
      ${e.source ? `<div class="src">${esc(e.source)}</div>` : ''}
    </div>`).join('') || '<p class="empty">Bez evidence by nález bránou neprošel.</p>';

  const history = (f.history || []).map((h) => {
    if ((h.kind || 'decision') === 'note') {
      return `<div class="hist"><div>${md(h.text)}</div>
        <div class="who">poznámka · ${esc(h.by)} · ${esc((h.at || '').slice(0, 16).replace('T', ' '))}</div></div>`;
    }
    const mark = { accepted: 'Přijato', rejected: 'Zamítnuto', deferred: 'Odloženo' }[h.state] || h.state;
    return `<div class="hist"><div><strong>${esc(mark)}</strong>${h.reason ? ` — <code>${esc(h.reason)}</code>` : ''}</div>
      ${h.note ? `<div>${md(h.note)}</div>` : ''}
      <div class="who">${esc(h.by)} · ${esc((h.at || '').slice(0, 16).replace('T', ' '))}</div></div>`;
  }).join('');

  const reasonOptions = REASONS.map(([v, l]) =>
    `<option value="${v}">${esc(l)}</option>`).join('');

  return shell(f.title || 'Nález', `
    <div class="badges">${badges}</div>
    <h1>${esc(f.title)}</h1>

    <h2>Co to tvrdí</h2>
    ${md(f.body)}

    <h2>Čím to dokládá</h2>
    ${evidence}

    <h2>Kde to je</h2>
    <div class="note ${drift[0]}"><strong>${esc(drift[1])}</strong><span>${esc(drift[2])}</span></div>
    <dl class="grid">
      <dt>soubor</dt><dd>${esc(a.file || '—')}</dd>
      <dt>řádek</dt><dd>${esc(a.line)}${resolved.line && resolved.line !== a.line
        ? ` → dnes ${esc(resolved.line)}` : ''}${resolved.via ? ` <span class="empty">(${esc(resolved.via)})</span>` : ''}</dd>
      ${a.symbol ? `<dt>symbol</dt><dd>${esc(a.symbol.name)}</dd>` : ''}
      <dt>commit</dt><dd>${esc((a.commit || '').slice(0, 12))}</dd>
      ${target.pr ? `<dt>zdroj</dt><dd>PR #${esc(target.pr)}${target.mergedAt
        ? ' · retrospektivní audit' : ''}</dd>` : ''}
      <dt>běh</dt><dd>${esc(f.runId)}</dd>
    </dl>
    <div class="bar">
      <button class="sec" data-cmd="open">Otevřít v kódu</button>
      <button class="sec" data-cmd="atCommit">Kód v den analýzy</button>
      ${f.drift === 'touched' ? '<button class="sec" data-cmd="diff">Porovnat s dneškem</button>' : ''}
    </div>

    <h2>Rozhodnutí</h2>
    ${f.decision
      ? `<div class="note ok"><strong>${esc({ accepted: 'Přijato', rejected: 'Zamítnuto', deferred: 'Odloženo' }[f.decision])}${f.reason ? ` — ${esc(f.reason)}` : ''}</strong>
         <span>Rozhodnutí je append-only událost — dá se přepsat novým, historie zůstane.</span></div>`
      : `<p class="empty">Zatím nerozhodnuto. Dokud nerozhodneš, nezapočítá se do precision.</p>`}
    ${history ? `<div>${history}</div>` : ''}

    <div class="bar">
      <button data-cmd="accept">Přijmout</button>
      <button class="sec" data-cmd="defer">Odložit</button>
      <select id="reason">${reasonOptions}</select>
      <button class="sec" data-cmd="reject">Zamítnout</button>
    </div>
    <textarea id="note" placeholder="Poznámka — volný text pro čtenáře. Ukládá se zvlášť od rozhodnutí, protože z rozhodnutí se počítá precision."></textarea>
    <div class="bar"><button class="sec" data-cmd="note">Uložit poznámku</button></div>
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
    <th class="num">přijato</th><th class="num">zamítnuto</th></tr>` +
    entries.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${meter(v.precision)}</td>
      <td class="num">${v.accepted}</td><td class="num">${v.rejected}</td></tr>`).join('') +
    '</table>';
}

function metricsHtml(m) {
  if (!m) return shell('Metriky', '<p class="empty">Metriky se nepodařilo načíst.</p>');
  const t = m.triage, f = m.findings, q = m.queue;
  return shell('Metriky', `
    <h1>${esc(m.project.name)}</h1>
    <div class="badges"><span class="badge">${m.runs} běhů</span></div>

    <h2>Precision</h2>
    <p style="font-size:1.4rem">${meter(t.precision)}</p>
    <p>${t.accepted} přijato · ${t.rejected} zamítnuto · ${t.undecided} nerozhodnuto</p>
    <div class="note"><strong>Počítá se jen z rozhodnutých nálezů.</strong>
      <span>Nerozhodnutý nález není ani pravda, ani lež. Kdyby padal do jmenovatele,
      každý nový běh by precision zředil a číslo by měřilo rychlost triage, ne kvalitu nálezů.</span></div>

    <h2>Průchod bránou</h2>
    <dl class="grid">
      <dt>zapsal pack</dt><dd>${f.raw}</dd>
      <dt>prošlo</dt><dd>${f.kept}${f.gateYield !== null ? ` (${Math.round(f.gateYield * 100)} %)` : ''}</dd>
      <dt>duplicity</dt><dd>${f.duplicates}${f.dedupRatio ? ` (${Math.round(f.dedupRatio * 100)} %)` : ''}</dd>
      ${f.gatedBy ? `<dt>vyřazeno</dt><dd>${esc(Object.entries(f.gatedBy)
        .map(([k, v]) => `${v}× ${k}`).join(', '))}</dd>` : ''}
    </dl>

    <h2>Fronta</h2>
    <dl class="grid">
      <dt>čeká</dt><dd>${q.undecided}</dd>
      ${q.medianAgeDays !== null ? `<dt>medián stáří</dt><dd>${q.medianAgeDays} dní</dd>` : ''}
      ${q.oldestDays !== null ? `<dt>nejstarší</dt><dd>${q.oldestDays} dní</dd>` : ''}
      ${m.cost.secondsPerKeptFinding ? `<dt>cena</dt><dd>${m.cost.secondsPerKeptFinding} s na nález</dd>` : ''}
    </dl>

    ${tallyTable('Po dimenzích', m.byDimension)}
    ${tallyTable('Po severitě', m.bySeverity)}
    ${tallyTable('Po modelech', m.byModel)}
    ${m.rejectReasons ? `<h2>Důvody zamítnutí</h2><table>` +
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
  return shell('Předpoklady', `
    <h1>Předpoklady běhu</h1>
    <p>${bad ? `${bad} věcí není v pořádku.` : 'Všechno je připravené.'}</p>
    <div class="note"><strong>Ověřuje se PŘED během, ne v jeho půlce.</strong>
      <span>Běh, který spadne po deseti minutách na chybějícím přihlášení, stojí
      víc než kontrola, která trvá vteřinu.</span></div>
    ${rows}
  `);
}

module.exports = { shell, esc, md, findingHtml, metricsHtml, doctorHtml, REASONS };
