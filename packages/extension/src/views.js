// Čtyři stromy v postranním panelu.
//
// Rozdělení odpovídá čtyřem otázkám, které si u tohohle nástroje kladeš
// v tomhle pořadí:
//
//   Přehled     — co se tu vůbec děje a je to v pořádku?
//   Specialisté — koho si můžu najmout a co ten člověk umí?
//   Běhy        — co už proběhlo a jak to dopadlo?
//   Nálezy      — co ode mě čeká rozhodnutí?
//
// Stromy jsou NATIVNÍ, ne webview: dědí theming, klávesnici, ikony i context
// menu zadarmo a v 300 px šířky panelu vypadají jako zbytek editoru. Na obsah,
// který se do 300 px nevejde, je detail nálezu v editoru (panel.js).
//
// Žádný z pohledů nevolá CLI. Čtou snímek ze `state.js` — jinak by překreslení
// stromu spouštělo procesy.

const vscode = require('vscode');
const path = require('path');
const state = require('./state.js');

const SEVERITY = {
  blocker: { icon: 'error', color: 'charts.red', label: 'blokující' },
  high: { icon: 'error', color: 'charts.red', label: 'vysoká' },
  medium: { icon: 'warning', color: 'charts.orange', label: 'střední' },
  low: { icon: 'info', color: 'charts.blue', label: 'nízká' },
};

const DECISION = {
  accepted: { icon: 'pass-filled', color: 'charts.green', label: 'přijato' },
  rejected: { icon: 'error-small', color: 'charts.red', label: 'zamítnuto' },
  deferred: { icon: 'clock', color: 'charts.yellow', label: 'odloženo' },
};

const DRIFT = {
  untouched: 'kód je od analýzy nezměněný — nález platí doslova',
  touched: 'na tenhle kód se od analýzy sáhlo — možná už opravené',
  deleted: 'soubor byl od analýzy smazaný',
  unknown: 'commit není v klonu, drift se nedá vyhodnotit',
};

function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'právě teď';
  if (s < 5400) return `před ${Math.round(s / 60)} min`;
  if (s < 172800) return `před ${Math.round(s / 3600)} h`;
  return `před ${Math.round(s / 86400)} dny`;
}

function icon(name, color) {
  return new vscode.ThemeIcon(name, color ? new vscode.ThemeColor(color) : undefined);
}

/** Základ pro všechny čtyři stromy — obsluha překreslení je pokaždé stejná. */
class Tree {
  constructor() {
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
    state.onDidChange(() => this._emitter.fire());
  }
  refresh() { this._emitter.fire(); }
  getTreeItem(node) { return node.item; }
  getChildren(node) { return node ? (node.children || []) : this.roots(); }
}

/** Uzel: popisek, popis vpravo, ikona, tooltip, příkaz při kliku. */
function node(label, { description, tooltip, iconId, color, command, args, children,
  collapsed, contextValue, id } = {}) {
  const collapsible = children
    ? (collapsed ? vscode.TreeItemCollapsibleState.Collapsed
      : vscode.TreeItemCollapsibleState.Expanded)
    : vscode.TreeItemCollapsibleState.None;
  const item = new vscode.TreeItem(label, collapsible);
  if (description !== undefined) item.description = description;
  if (tooltip) item.tooltip = typeof tooltip === 'string'
    ? new vscode.MarkdownString(tooltip) : tooltip;
  if (iconId) item.iconPath = icon(iconId, color);
  if (contextValue) item.contextValue = contextValue;
  if (id) item.id = id;
  if (command) item.command = { command, title: label, arguments: args || [] };
  return { item, children };
}

// ------------------------------------------------------------------ Přehled

class OverviewTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (s.loading && !s.loadedAt) return [node('načítám…', { iconId: 'loading~spin' })];
    if (!s.probe.ok) return [];   // uvítací obrazovka z package.json

    const rows = [];
    const p = s.project || {};

    rows.push(node('Projekt', {
      description: p.slug || (s.cwd ? path.basename(s.cwd) : '—'),
      iconId: 'repo',
      tooltip: `**${p.slug || ''}**\n\n${s.cwd || ''}\n\nVšechno, co Agency zapíše, `
        + 'leží v `.agency/` tohohle projektu — ne v nástroji. Proto to přežije '
        + 'přeinstalaci i nové naklonování repozitáře.',
    }));

    const problems = (s.doctor || []).filter((c) => !c.ok);
    const fatal = problems.filter((c) => c.fatal);
    rows.push(node('Předpoklady', {
      description: problems.length
        ? `${problems.length} ${problems.length === 1 ? 'problém' : 'problémy'}`
        : 'v pořádku',
      iconId: fatal.length ? 'error' : problems.length ? 'warning' : 'pass',
      color: fatal.length ? 'charts.red' : problems.length ? 'charts.orange' : 'charts.green',
      command: 'agency.doctor',
      tooltip: problems.length
        ? problems.map((c) => `- **${c.name}** — ${c.detail}`).join('\n')
        : 'Nástroje, přihlášení a stav grafu se ověřují **před** během, ne až '
        + 'v jeho půlce. Klikni pro celý výpis.',
    }));

    const packs = (s.packs || []).filter((x) => x.installed);
    rows.push(node('Specialisté', {
      description: packs.length ? packs.map((x) => x.name).join(', ') : 'žádný nainstalovaný',
      iconId: packs.length ? 'person' : 'person-add',
      command: packs.length ? undefined : 'agency.pack.add',
      tooltip: packs.length
        ? 'Pack je metoda práce, ne obsah. Nainstalovaný pack přinesl do projektu '
        + 'svůj skill a konfiguraci — obsah (pravidla, dokumentace) zůstává projektu.'
        : 'Zatím žádný. Klikni a nainstaluj prvního.',
    }));

    const last = (s.runs || [])[0];
    rows.push(node('Poslední běh', {
      description: last
        ? `${last.target ? '#' + last.target : '—'} · ${last.findings} nálezů · ${ago(last.startedAt)}`
        : 'zatím žádný',
      iconId: last ? (last.status === 'ok' ? 'history' : 'circle-slash') : 'circle-outline',
      command: last ? undefined : 'agency.review.pick',
      tooltip: last
        ? `Běh \`${last.id}\`, stav \`${last.status}\`.\n\nBěh je záznam v repu, ne `
        + 'událost v nástroji — dá se přečíst i za rok a v PR se dá reviewovat.'
        : 'Klikni a vyber pull request k recenzi.',
    }));

    const q = state.queue();
    rows.push(node('Fronta k rozhodnutí', {
      description: q.length ? `${q.length}` : 'prázdná',
      iconId: q.length ? 'inbox' : 'check-all',
      color: q.length ? 'charts.orange' : 'charts.green',
      command: 'agency.view.findings.focus',
      tooltip: 'Nález bez rozhodnutí není ani pravda, ani lež. Dokud ho nerozhodneš, '
        + 'nezapočítá se do precision — proto fronta, která roste, je ta nejdražší '
        + 'věc v celém systému.',
    }));

    const m = s.metrics;
    const t = m && m.triage;
    rows.push(node('Precision', {
      description: t && t.precision !== null && t.precision !== undefined
        ? `${Math.round(t.precision * 100)} % (${t.accepted} z ${t.accepted + t.rejected})`
        : 'zatím není z čeho počítat',
      iconId: 'graph',
      color: t && t.precision >= 0.7 ? 'charts.green'
        : t && t.precision !== null && t.precision !== undefined ? 'charts.orange' : undefined,
      command: 'agency.metrics',
      tooltip: 'Kolik z toho, co pack našel, je pravda. Počítá se **jen z rozhodnutých** '
        + 'nálezů — nerozhodnuté by číslo ředily a měřily by pak rychlost triage, '
        + 'ne kvalitu nálezů.\n\nKlikni pro celý rozpad podle dimenzí, severity a modelů.',
    }));

    return rows;
  }
}

// -------------------------------------------------------------- Specialisté

class ToolsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    return (s.packs || []).map((p) => {
      const children = [];

      children.push(node('Co dělá', {
        description: '', tooltip: p.description, iconId: 'info',
      }));
      const dims = (p.dimensions || []).length ? p.dimensions : null;
      if (dims) {
        children.push(node('Na co se dívá', {
          description: `${dims.length} dimenzí`,
          iconId: 'checklist',
          collapsed: true,
          children: dims.map((d) => node(d.title || d.id, {
            description: d.projectSpecific ? 'podle pravidel projektu' : '',
            iconId: 'circle-small-filled',
            tooltip: d.projectSpecific
              ? 'Tahle dimenze potřebuje pravidla projektu (`review.rules` '
              + 'v konfiguraci). Bez nich pack běží o jednu dimenzi méně — což je '
              + 'legitimní výstup, ne selhání.'
              : undefined,
          })),
        }));
      }
      if (p.installed) {
        children.push(node('Konfigurace', {
          description: `.agency/${p.name}.json`,
          iconId: 'settings-gear',
          command: 'agency.pack.openConfig',
          args: [p.name],
          tooltip: 'Konfiguraci vlastní **projekt** — upgrade packu ji nikdy nepřepíše. '
            + 'Model, práh score, přeskakované soubory, cíl exportu.',
        }));
      }

      return node(p.title || p.name, {
        id: `pack:${p.name}`,
        description: p.installed ? p.installed.split('@')[1] || p.version : 'neinstalován',
        iconId: p.installed ? 'person' : 'person-add',
        color: p.installed ? 'charts.green' : undefined,
        contextValue: p.installed ? 'agencyPack.installed' : 'agencyPack.available',
        collapsed: true,
        children,
        tooltip: `**${p.title || p.name}** \`${p.version}\`\n\n${p.description || ''}`,
      });
    });
  }
}

// --------------------------------------------------------------------- Běhy

class RunsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    return (s.runs || []).map((r) => {
      const mine = s.findings.filter((f) => f.runId === r.id);
      const st = {
        ok: ['pass', 'charts.green'],
        'no-findings': ['circle-outline', undefined],
        'gated-out': ['filter', 'charts.orange'],
        running: ['loading~spin', undefined],
        failed: ['error', 'charts.red'],
      }[r.status] || ['circle-outline', undefined];

      return node(r.target ? `PR #${r.target}` : r.id.slice(0, 10), {
        id: `run:${r.id}`,
        description: `${r.findings} nálezů · ${ago(r.startedAt)}`,
        iconId: st[0], color: st[1],
        collapsed: true,
        contextValue: 'agencyRun',
        children: mine.length
          ? mine.map((f) => findingNode(f, { showFile: true }))
          : [node('žádné nálezy', { iconId: 'circle-outline' })],
        tooltip: `Běh \`${r.id}\`\n\n- stav: \`${r.status}\`\n- pack: \`${r.pack}\`\n`
          + `- ${r.kind === 'merged-pull-request' ? 'retrospektivní audit' : 'otevřený PR'}\n`
          + `- ${r.undecided} bez rozhodnutí`,
      });
    });
  }
}

// ------------------------------------------------------------------- Nálezy

function findingNode(f, { showFile = true } = {}) {
  const sev = SEVERITY[f.severity] || SEVERITY.low;
  const dec = DECISION[f.decision];
  const loc = f.file ? `${path.basename(f.file)}:${(f.resolved && f.resolved.line) || f.line}` : '';
  const drifted = f.drift === 'touched' || f.drift === 'deleted';

  const tip = new vscode.MarkdownString();
  tip.appendMarkdown(`**${f.title}**\n\n`);
  if (f.body) tip.appendMarkdown(`${String(f.body).slice(0, 400)}\n\n`);
  tip.appendMarkdown(`---\n\n`);
  tip.appendMarkdown(`- závažnost: **${sev.label}**${f.dimension ? ` · dimenze \`${f.dimension}\`` : ''}\n`);
  if (f.file) tip.appendMarkdown(`- \`${f.file}:${f.line}\`\n`);
  tip.appendMarkdown(`- ${DRIFT[f.drift] || 'drift neznámý'}\n`);
  if (f.resolved && f.resolved.note) tip.appendMarkdown(`- kotva: ${f.resolved.note}\n`);
  tip.appendMarkdown(`- evidence: ${(f.evidence || []).length}×\n`);
  if (dec) tip.appendMarkdown(`- rozhodnutí: **${dec.label}**${f.reason ? ` — \`${f.reason}\`` : ''}\n`);

  return node(f.title || '(bez titulku)', {
    id: `finding:${f.id}`,
    description: [showFile ? loc : '', drifted ? '· dotčeno' : ''].filter(Boolean).join(' '),
    iconId: dec ? dec.icon : sev.icon,
    color: dec ? dec.color : sev.color,
    tooltip: tip,
    contextValue: dec ? 'agencyFinding.decided' : 'agencyFinding.open',
    command: 'agency.finding.open',
    args: [f.id],
  });
}

class FindingsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    const all = s.findings || [];
    if (!all.length) return [];

    const open = all.filter((f) => !f.decision && f.state !== 'duplicate');
    const decided = all.filter((f) => f.decision);
    const dupes = all.filter((f) => f.state === 'duplicate');

    // Uvnitř fronty napřed to, na co se od analýzy nesáhlo — tam nález platí
    // doslova. „Dotčené" bývají často už opravené a stojí víc času.
    const rank = (f) => (f.drift === 'untouched' ? 0 : 1) * 10
      + ['blocker', 'high', 'medium', 'low'].indexOf(f.severity || 'low');
    open.sort((a, b) => rank(a) - rank(b));

    const groups = [];
    if (open.length) {
      groups.push(node(`K rozhodnutí`, {
        description: String(open.length),
        iconId: 'inbox',
        children: open.map((f) => findingNode(f)),
        tooltip: 'Seřazeno tak, aby nahoře byly nálezy na kódu, na který od analýzy '
          + 'nikdo nesáhl — ty platí doslova a rozhodnou se nejrychleji.',
      }));
    }
    if (decided.length) {
      groups.push(node('Rozhodnuté', {
        description: String(decided.length),
        iconId: 'check-all',
        collapsed: true,
        children: decided.map((f) => findingNode(f)),
      }));
    }
    if (dupes.length) {
      groups.push(node('Duplicity', {
        description: String(dupes.length),
        iconId: 'copy',
        collapsed: true,
        children: dupes.map((f) => findingNode(f)),
        tooltip: 'Nález, který pack našel podruhé. Nezahazuje se — dedup ratio je '
          + 'metrika, kvůli které se to počítá —, ale do fronty nepatří.',
      }));
    }
    return groups;
  }
}

module.exports = { OverviewTree, ToolsTree, RunsTree, FindingsTree, ago, SEVERITY, DRIFT };
