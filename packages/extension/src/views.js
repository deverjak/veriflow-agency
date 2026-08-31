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
  blocker: { icon: 'error', color: 'charts.red', label: 'blocker' },
  high: { icon: 'error', color: 'charts.red', label: 'high' },
  medium: { icon: 'warning', color: 'charts.orange', label: 'medium' },
  low: { icon: 'info', color: 'charts.blue', label: 'low' },
};

const DECISION = {
  accepted: { icon: 'pass-filled', color: 'charts.green', label: 'accepted' },
  rejected: { icon: 'error-small', color: 'charts.red', label: 'rejected' },
  deferred: { icon: 'clock', color: 'charts.yellow', label: 'deferred' },
};

const DRIFT = {
  untouched: 'the code has not changed since the analysis — the finding holds literally',
  touched: 'this code was touched since the analysis — it may already be fixed',
  deleted: 'the file was deleted after the analysis',
  unknown: 'the commit is not in this clone, drift cannot be evaluated',
};

function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
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
    if (s.loading && !s.loadedAt) return [node('loading…', { iconId: 'loading~spin' })];
    if (!s.probe.ok) return [];   // uvítací obrazovka z package.json

    const rows = [];
    const p = s.project || {};

    rows.push(node('Project', {
      description: p.slug || (s.cwd ? path.basename(s.cwd) : '—'),
      iconId: 'repo',
      tooltip: `**${p.slug || ''}**\n\n${s.cwd || ''}\n\nEverything Agency writes `
        + 'lives in `.agency/` of this project — not in the tool. That is why it survives '
        + 'a reinstall and a fresh clone of the repository.',
    }));

    const problems = (s.doctor || []).filter((c) => !c.ok);
    const fatal = problems.filter((c) => c.fatal);
    rows.push(node('Prerequisites', {
      description: problems.length
        ? `${problems.length} ${problems.length === 1 ? 'problem' : 'problems'}`
        : 'all good',
      iconId: fatal.length ? 'error' : problems.length ? 'warning' : 'pass',
      color: fatal.length ? 'charts.red' : problems.length ? 'charts.orange' : 'charts.green',
      command: 'agency.doctor',
      tooltip: problems.length
        ? problems.map((c) => `- **${c.name}** — ${c.detail}`).join('\n')
        : 'Tools, logins and the state of the graph are checked **before** a run, not '
        + 'halfway through it. Click for the full list.',
    }));

    const packs = (s.packs || []).filter((x) => x.installed);
    rows.push(node('Specialists', {
      description: packs.length ? packs.map((x) => x.name).join(', ') : 'none installed',
      iconId: packs.length ? 'person' : 'person-add',
      command: packs.length ? undefined : 'agency.pack.add',
      tooltip: packs.length
        ? 'A pack is a method of work, not content. An installed pack brought its skill '
        + 'and its configuration into the project — the content (rules, documentation) '
        + 'stays with the project.'
        : 'None yet. Click to install the first one.',
    }));

    const last = (s.runs || [])[0];
    rows.push(node('Last run', {
      description: last
        ? `${last.targetLabel || '—'} · ${last.findings} findings · ${ago(last.startedAt)}`
        : 'none yet',
      iconId: last ? (last.status === 'ok' ? 'history' : 'circle-slash') : 'circle-outline',
      command: last ? undefined : 'agency.review.pick',
      tooltip: last
        ? `Run \`${last.id}\`, status \`${last.status}\`.\n\nA run is a record in the repo, `
        + 'not an event in the tool — it can still be read a year from now and reviewed in a PR.'
        : 'Click and pick a pull request to review.',
    }));

    const q = state.queue();
    rows.push(node('Decision queue', {
      description: q.length ? `${q.length}` : 'empty',
      iconId: q.length ? 'inbox' : 'check-all',
      color: q.length ? 'charts.orange' : 'charts.green',
      command: 'agency.view.findings.focus',
      tooltip: 'An undecided finding is neither true nor false. Until you decide it, '
        + 'it does not count towards precision — which is why a growing queue is the '
        + 'most expensive thing in the whole system.',
    }));

    const m = s.metrics;
    const t = m && m.triage;
    rows.push(node('Precision', {
      description: t && t.precision !== null && t.precision !== undefined
        ? `${Math.round(t.precision * 100)} % (${t.accepted} of ${t.accepted + t.rejected})`
        : 'nothing to compute from yet',
      iconId: 'graph',
      color: t && t.precision >= 0.7 ? 'charts.green'
        : t && t.precision !== null && t.precision !== undefined ? 'charts.orange' : undefined,
      command: 'agency.metrics',
      tooltip: 'How much of what the pack found is true. It is computed **only from decided** '
        + 'findings — undecided ones would dilute the number and it would then measure the '
        + 'speed of triage, not the quality of the findings.\n\nClick for the full breakdown '
        + 'by dimension, severity and model.',
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

      children.push(node('What it does', {
        description: '', tooltip: p.description, iconId: 'info',
      }));
      const dims = (p.dimensions || []).length ? p.dimensions : null;
      if (dims) {
        children.push(node('What it looks at', {
          description: `${dims.length} dimensions`,
          iconId: 'checklist',
          collapsed: true,
          children: dims.map((d) => node(d.title || d.id, {
            description: d.projectSpecific ? 'follows project rules' : '',
            iconId: 'circle-small-filled',
            tooltip: d.projectSpecific
              ? 'This dimension needs the project rules (`review.rules` in the '
              + 'configuration). Without them the pack runs one dimension short — which is '
              + 'a legitimate outcome, not a failure.'
              : undefined,
          })),
        }));
      }
      const takesBrief = p.run && p.run.prompt && p.run.prompt.accepts;
      children.push(node('What it works on', {
        description: p.run && p.run.target === 'workspace'
          ? 'the project as it is' : 'a pull request',
        iconId: p.run && p.run.target === 'workspace' ? 'browser' : 'git-pull-request',
        tooltip: p.run && p.run.target === 'workspace'
          ? 'It runs over the working copy, including uncommitted work — that is where the '
          + 'application under test actually runs. No throwaway worktree, so the source is '
          + '**read only**: everything the run produces goes into the run directory.'
          : 'It runs over a pull request in a throwaway worktree on its head commit. Your '
          + 'branch and your work in progress stay untouched.',
      }));
      if (p.installed && takesBrief) {
        const standing = (p.brief && p.brief.standing) || null;
        const scenarios = (p.brief && p.brief.scenarios) || [];
        children.push(node('Brief', {
          description: standing ? String(standing).slice(0, 40) : 'not set',
          iconId: 'note',
          color: standing ? 'charts.green' : undefined,
          command: 'agency.pack.brief',
          args: [p.name],
          collapsed: true,
          children: scenarios.length
            ? scenarios.map((sc) => node(sc.name, {
              description: String(sc.text || '').slice(0, 60),
              iconId: 'bookmark',
              tooltip: `\`agency run ${p.name} --scenario ${sc.name}\`\n\n${sc.text || ''}`,
            }))
            : undefined,
          tooltip: 'What this specialist should work on. The **standing** brief applies to '
            + 'every run and lives in the project configuration; a one-off assignment is '
            + 'given when the run starts. The choice is written into the run record — '
            + '“which brief produces better findings” is a question worth answering with '
            + 'numbers.\n\nClick to change it.',
        }));
      }
      if (p.installed && p.playwright) {
        const pw = p.playwright;
        children.push(node('Browser', {
          description: pw.enabled
            ? `Playwright · specs ${pw.specTarget === 'suite' ? 'in the suite' : 'with the run'}`
            : 'off — HTTP only',
          iconId: pw.enabled ? 'browser' : 'circle-slash',
          color: pw.enabled ? 'charts.green' : undefined,
          command: 'agency.qa.playwright',
          args: [p.name],
          tooltip: pw.enabled
            ? 'The session drives a real browser and writes a **failing spec** for every finding. '
            + 'The spec travels with the run record, so “is it fixed?” is answered by running it, '
            + 'not by another session.'
            + (pw.configFile ? `\n\nUses the project config \`${pw.configFile}\`.`
              : `\n\nThe project has no Playwright; scaffolding is \`${pw.scaffold}\`.`)
            : 'Off. The session only reaches what it can over HTTP — enough for API-level checks, '
            + 'not for anything a user actually clicks.\n\nClick to set it up.',
        }));
      }
      if (p.installed && p.agent) {
        children.push(node('Who handles it', {
          description: [p.agent.provider, p.agent.model].filter(Boolean).join(' · ')
            || 'provider default model',
          iconId: 'rocket',
          tooltip: 'The model is a property of the task, not of the user. A review is '
            + 'reading and classification, not writing — it can run cheaper than coding. '
            + 'The choice is written into the run record so you can measure which model '
            + 'produces better findings.',
        }));
      }
      if (p.installed) {
        children.push(node('Configuration', {
          description: `.agency/${p.name}.json`,
          iconId: 'settings-gear',
          command: 'agency.pack.openConfig',
          args: [p.name],
          tooltip: 'The configuration is owned by the **project** — a pack upgrade never '
            + 'overwrites it. Model, score threshold, skipped files, export target.',
        }));
      }

      return node(p.title || p.name, {
        id: `pack:${p.name}`,
        description: p.installed
          ? [p.installed.split('@')[1] || p.version, p.agent && p.agent.model]
            .filter(Boolean).join(' · ')
          : 'not installed',
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

      return node(r.targetLabel || r.id.slice(0, 10), {
        id: `run:${r.id}`,
        description: `${r.findings} findings · ${ago(r.startedAt)}`,
        iconId: st[0], color: st[1],
        collapsed: true,
        contextValue: 'agencyRun',
        children: mine.length
          ? mine.map((f) => findingNode(f, { showFile: true }))
          : [node('no findings', { iconId: 'circle-outline' })],
        tooltip: `Run \`${r.id}\`\n\n- status: \`${r.status}\`\n- pack: \`${r.pack}\`\n`
          + `- ${{ 'merged-pull-request': 'retrospective audit', workspace: 'over the project as it was' }[r.kind]
            || 'open PR'}\n`
          + (r.brief ? `- brief: _${String(r.brief).slice(0, 120)}_\n` : '')
          + `- ${r.undecided} undecided`,
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
  tip.appendMarkdown(`- severity: **${sev.label}**${f.dimension ? ` · dimension \`${f.dimension}\`` : ''}\n`);
  if (f.file) tip.appendMarkdown(`- \`${f.file}:${f.line}\`\n`);
  tip.appendMarkdown(`- ${DRIFT[f.drift] || 'drift unknown'}\n`);
  if (f.resolved && f.resolved.note) tip.appendMarkdown(`- anchor: ${f.resolved.note}\n`);
  tip.appendMarkdown(`- evidence: ${(f.evidence || []).length}×\n`);
  if (dec) tip.appendMarkdown(`- decision: **${dec.label}**${f.reason ? ` — \`${f.reason}\`` : ''}\n`);

  return node(f.title || '(untitled)', {
    id: `finding:${f.id}`,
    description: [showFile ? loc : '', drifted ? '· touched' : ''].filter(Boolean).join(' '),
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
      groups.push(node(`To decide`, {
        description: String(open.length),
        iconId: 'inbox',
        children: open.map((f) => findingNode(f)),
        tooltip: 'Sorted so that findings on code nobody has touched since the analysis '
          + 'come first — those hold literally and are the fastest to decide.',
      }));
    }
    if (decided.length) {
      groups.push(node('Decided', {
        description: String(decided.length),
        iconId: 'check-all',
        collapsed: true,
        children: decided.map((f) => findingNode(f)),
      }));
    }
    if (dupes.length) {
      groups.push(node('Duplicates', {
        description: String(dupes.length),
        iconId: 'copy',
        collapsed: true,
        children: dupes.map((f) => findingNode(f)),
        tooltip: 'A finding the pack found a second time. It is not thrown away — the '
          + 'dedup ratio is the metric this is counted for — but it does not belong in '
          + 'the queue.',
      }));
    }
    return groups;
  }
}

module.exports = { OverviewTree, ToolsTree, RunsTree, FindingsTree, ago, SEVERITY, DRIFT };
