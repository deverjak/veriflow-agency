// The four trees in the side panel.
//
// The split answers four questions, in the order you ask them of this tool:
//
//   Overview     — what is going on here, and is it in order?
//   Specialists  — which packs does this project have, and what do they do?
//   Runs         — what already happened, and how did it go?
//   Findings     — what is waiting for me to decide?
//
// The trees are NATIVE, not a webview: they inherit theming, keyboard,
// icons and the context menu for free, and at a 300 px panel width they
// look like the rest of the editor. For content that does not fit 300 px,
// there is the finding detail in the editor (panel.js).
//
// No view calls the CLI. They read the snapshot from `state.js` — otherwise
// redrawing a tree would spawn processes.

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

/** Base for all four trees — redraw handling is the same for every one. */
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

/** A node: label, right-hand description, icon, tooltip, command on click. */
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

// ------------------------------------------------------------------ Overview

class OverviewTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (s.loading && !s.loadedAt) return [node('loading…', { iconId: 'loading~spin' })];
    if (!s.probe.ok) return [];   // the welcome screen from package.json handles this

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

    const packs = s.packs || [];
    rows.push(node('Specialists', {
      description: packs.length
        ? packs.map((x) => x.name).join(', ')
        : 'none in this project',
      iconId: packs.length ? 'person' : 'person-add',
      command: 'agency.view.tools.focus',
      tooltip: packs.length
        ? 'A pack is a skill in `.claude/skills/agency-<name>/` — written for this project, '
        + 'not installed into it. Click to see what each one does and run one.'
        : 'No pack found. A pack is a skill directory with a `pack.json` next to its `SKILL.md`.',
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
        + 'by dimension, severity and provider.',
    }));

    return rows;
  }
}

// -------------------------------------------------------------- Specialists

/** Everything worth showing about one pack — the same for every row, since
 *  there is no per-worker variation left to show beside it (no roster). */
function packChildren(p) {
  const children = [];

  children.push(node('What it does', {
    description: '', tooltip: p.description || '', iconId: 'info',
  }));

  const dims = (p.dimensions || []).length ? p.dimensions : null;
  if (dims) {
    children.push(node('What it looks at', {
      description: `${dims.length} dimensions`,
      iconId: 'checklist',
      collapsed: true,
      children: dims.map((d) => node(d.title || d.id, { iconId: 'circle-small-filled' })),
    }));
  }

  const target = p.run && p.run.target;
  children.push(node('What it works on', {
    description: target === 'workspace' ? 'the project as it is' : 'a pull request',
    iconId: target === 'workspace' ? 'browser' : 'git-pull-request',
    tooltip: target === 'workspace'
      ? 'It runs over the working copy, including uncommitted work. No throwaway worktree, '
      + 'so the source is **read only**: everything the run produces goes into the run directory.'
      : 'It runs over a pull request in a throwaway worktree on its head commit. Your '
      + 'branch and your work in progress stay untouched.',
  }));

  const prompt = p.run && p.run.prompt;
  if (prompt && prompt !== 'none') {
    children.push(node('Prompt', {
      description: prompt === 'required' ? 'required every run' : 'optional',
      iconId: 'edit',
      tooltip: prompt === 'required'
        ? 'This specialist needs to know what to work on — you are asked for it when you run it.'
        : 'You may focus this run with a prompt; without one it works from its own method alone.',
    }));
  }

  if ((p.requires || []).length) {
    children.push(node('Requires', {
      description: p.requires.join(', '),
      iconId: 'tools',
    }));
  }

  return children;
}

class ToolsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    return (s.packs || []).map((p) => node(p.title || p.name, {
      id: `pack:${p.name}`,
      description: p.skill || '',
      iconId: 'person',
      color: 'charts.green',
      contextValue: 'agencyPack',
      collapsed: true,
      children: packChildren(p),
      tooltip: `**${p.title || p.name}**\n\n${p.description || ''}\n\n---\n\n`
        + `\`agency run ${p.name}\` — or the ▶ on this row.`,
    }));
  }
}

// --------------------------------------------------------------------- Runs

class RunsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    return groupChains((s.runs || []).map((r) => runNode(r, s)), s.runs || []);
  }
}

/** Runs belonging to one chain under one node — otherwise a team looks like
 *  several unrelated runs and there is no way to see that the second one
 *  judged the first. Order inside follows position, not time: a chain is a
 *  sequence. */
function groupChains(nodes, runs) {
  const out = [];
  const placed = new Set();
  runs.forEach((r, i) => {
    if (placed.has(i)) return;
    const c = r.chain;
    if (!c) { out.push(nodes[i]); return; }

    const members = runs
      .map((other, j) => ({ other, j }))
      .filter(({ other }) => other.chain && other.chain.id === c.id)
      .sort((a, b) => a.other.chain.position - b.other.chain.position);
    members.forEach(({ j }) => placed.add(j));

    const findings = members.reduce((n, { other }) => n + (other.findings || 0), 0);
    const undecided = members.reduce((n, { other }) => n + (other.undecided || 0), 0);
    const who = members.map(({ other }) => String(other.pack || '?'));
    // An incomplete chain must not look finished — that is what `of` is in the
    // record for.
    const short = members.length < c.of;
    const broke = members.some(({ other }) => other.status === 'failed');
    const denied = members.reduce((n, { other }) => n + (other.denied || 0), 0);

    out.push(node(who.join(' → '), {
      id: `chain:${c.id}`,
      description: `${members.length}/${c.of} steps · ${findings} findings`
        + `${denied ? ` · ${denied} denied` : ''} · ${undecided} undecided`,
      iconId: broke ? 'error' : short ? 'debug-disconnect' : 'organization',
      color: broke ? 'charts.red' : short ? 'charts.orange' : undefined,
      collapsed: true,
      contextValue: 'agencyChain',
      children: members.map(({ j, other }) => {
        const n = nodes[j];
        n.item.description = `step ${other.chain.position}/${other.chain.of} · ${n.item.description}`;
        return n;
      }),
      tooltip: [
        `Team run \`${c.id}\``,
        '',
        ...members.map(({ other }) =>
          `- ${other.chain.position}/${other.chain.of} \`${other.pack}\``
          + ` — ${other.findings} findings, ${other.status}`
          + (other.denied ? `, **${other.denied} denied**` : '')),
        '',
        denied
          ? `${denied} tool call(s) were refused across this team. A member that may not `
            + 'write finishes cleanly and records nothing, which is not the same as finding '
            + 'nothing — widen `needs` in the pack, or pass `--bypass`.'
          : short
            ? `The chain stopped after ${members.length} of ${c.of} steps. `
              + 'What did run is recorded; the rest can be finished by hand.'
            : 'Each member judged what the previous one found before running its own dimensions.',
      ].join('\n'),
    }));
  });
  return out;
}

function runNode(r) {
  const mine = state.snapshot.findings.filter((f) => f.runId === r.id);
  const st = {
    ok: ['pass', 'charts.green'],
    'no-findings': ['circle-outline', undefined],
    'gated-out': ['filter', 'charts.orange'],
    running: ['loading~spin', undefined],
    // Not an error: the agent was launched and the terminal was closed
    // before it finished. Dim, because there is nothing to act on.
    abandoned: ['circle-slash', undefined],
    failed: ['error', 'charts.red'],
  }[r.status] || ['circle-outline', undefined];

  const who = [r.pack, r.provider].filter(Boolean).join(' · ');
  const denied = r.denied ? ` · ${r.denied} denied` : '';
  return node(r.targetLabel || r.id.slice(0, 10), {
    id: `run:${r.id}`,
    description: `${who ? `${who} · ` : ''}${r.findings} findings${denied} · ${ago(r.startedAt)}`,
    iconId: st[0], color: st[1],
    collapsed: true,
    // A run still marked running is the only one worth offering to close —
    // and it stays that way until somebody says so, because nothing here
    // can see the terminal it was launched in.
    contextValue: r.status === 'running' ? 'agencyRun.open' : 'agencyRun',
    children: mine.length
      ? mine.map((f) => findingNode(f, { showFile: true }))
      : [node('no findings', { iconId: 'circle-outline' })],
    tooltip: `Run \`${r.id}\`\n\n- status: \`${r.status}\`\n- pack: \`${r.pack}\`\n`
      + (r.exitReason ? `- why: _${r.exitReason}_\n` : '')
      + (r.denied
        ? `- **${r.denied} tool call(s) denied** — the run measured its permissions, `
          + 'not the method. Widen `needs` in the pack, or pass `--bypass`.\n'
        : '')
      + ((r.outputs || []).length ? `- left behind: ${r.outputs.map((n) => `\`${n}\``).join(', ')}\n` : '')
      + `- provider: \`${r.provider || '?'}\`${r.model ? ` · \`${r.model}\`` : ''}\n`
      + `- ${{ 'merged-pull-request': 'retrospective audit', workspace: 'over the project as it was' }[r.kind]
        || 'open PR'}\n`
      + (r.prompt ? `- prompt: _${String(r.prompt).slice(0, 120)}_\n` : '')
      + `- ${r.undecided} undecided\n`
      + (r.status === 'running'
        ? '\nStill open. Nothing here can see the terminal it runs in, so it stays '
        + 'open until you close it — **Close run** on this row.'
        : ''),
  });
}

// ------------------------------------------------------------------- Findings

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

    // Untouched-since-analysis first inside the queue — those hold literally.
    // "Touched" findings are often already fixed and cost more time to review.
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
