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

    const roster = s.hires || [];
    const offline = roster.filter((h) => !h.available);
    rows.push(node('Specialists', {
      description: roster.length
        ? roster.map((h) => h.label).join(', ')
          + (offline.length ? ` · ${offline.length} not on PATH` : '')
        : 'nobody hired',
      iconId: roster.length ? 'person' : 'person-add',
      color: offline.length ? 'charts.orange' : undefined,
      command: roster.length ? 'agency.view.tools.focus' : 'agency.hire.add',
      tooltip: roster.length
        ? 'A pack is a method of work; a specialist is one worker following it. The same '
        + 'method can be hired once per provider — “Reviewer · sonnet” and '
        + '“Reviewer · codex” share one configuration, one queue of findings and one '
        + 'dedup, and differ only in who does the work.'
        + (offline.length
          ? `\n\n**${offline.map((h) => h.id).join(', ')}** cannot run here — the runner `
          + 'is not on PATH. The roster travels with the repository, the binaries do not.'
          : '')
        : 'Nobody yet. Click to hire the first one.',
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

// The view lists WORKERS, not methods.
//
// A pack is a method of work; a hire is one worker following it. The same pack
// can be hired once per provider, so "Reviewer · sonnet" and "Reviewer · codex"
// are two rows over one configuration, one finding queue and one dedup — and
// the difference between them is the only thing worth showing at the top level.
//
// A pack that nobody is hired for still shows up, otherwise there would be no
// way to hire the first worker for it.

/** Everything a worker inherits from its method. Shared on purpose: brief,
 *  browser and configuration belong to the pack, not to whoever runs it. */
function packChildren(p, { shared = false } = {}) {
  const children = [];
  const note = shared
    ? '\n\nShared by every specialist hired for this method — one configuration, '
    + 'one queue of findings, one dedup.'
    : '';

  children.push(node('What it does', {
    description: '', tooltip: (p.description || '') + note, iconId: 'info',
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

  children.push(node('What it works on', {
    description: p.run && p.run.target === 'workspace'
      ? 'the project as it is' : 'a pull request',
    iconId: p.run && p.run.target === 'workspace' ? 'browser' : 'git-pull-request',
    tooltip: p.run && p.run.target === 'workspace'
      ? 'It runs over the working copy, including uncommitted work — that is where the '
      + 'application under test actually runs. No throwaway worktree, so the source is '
      + '**read only**: everything the run produces goes into the run directory.'
      : 'It runs over a pull request in a throwaway worktree on its head commit. Your '
      + 'branch and your work in progress stay untouched. Two specialists on the same '
      + 'pull request get a worktree each, so they can run at the same time.',
  }));

  const takesBrief = p.run && p.run.prompt && p.run.prompt.accepts;
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
        + 'numbers.' + note + '\n\nClick to change it.',
    }));
  }

  if (p.installed && p.backlog) {
    // A specialist that writes OUTSIDE the repository has to say so on its own
    // row. Which switches are open is the difference between a note on a board
    // and a ticket in somebody's inbox, and nobody goes looking for that in a
    // JSON file.
    const bl = p.backlog;
    const writes = bl.writes || [];
    const may = bl.dryRun ? 'rehearsal only'
      : (writes.length ? `may ${writes.join(', ')}` : 'reads only');
    const where = `${bl.repo || 'no repo'}`
      + (bl.projectNumber ? ` · board #${bl.projectNumber}` : '');
    children.push(node('Backlog', {
      description: `${where} · ${may}`,
      iconId: bl.dryRun ? 'beaker' : 'checklist',
      color: writes.length && !bl.dryRun ? 'charts.green' : undefined,
      command: 'agency.pack.openConfig',
      args: [p.name],
      tooltip: 'Where this specialist writes, and what it may write there. Everything it '
        + 'posts is signed as an agent and carries a marker, so a second run finds what '
        + 'the first one wrote instead of writing it again.\n\n'
        + (bl.dryRun
          ? '**Rehearsal** — every write is composed and shown, and nothing reaches GitHub. '
          + 'That is how a fresh installation should run for the first few days.'
          : `Open: ${writes.length ? writes.join(', ') : 'nothing'}. Everything else is `
          + 'off — an issue lands in someone’s inbox, so it is opened one switch at a time.')
        + '\n\nClick to open the configuration.',
    }));
    if (bl.roadmap) {
      children.push(node('Roadmap', {
        description: bl.roadmap + (bl.cycle ? ` · ${bl.cycle}` : ''),
        iconId: 'milestone',
        tooltip: 'What every request is measured against. It is copied into the run '
          + 'directory when a run starts, so a decision stays reviewable against the '
          + 'wording it was actually made from.'
          + (bl.cycle ? '' : '\n\nNo cycle is set — without one, “now” is an opinion.'),
      }));
    }
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

  if (p.installed) {
    children.push(node('Configuration', {
      description: `.agency/${p.name}.json`,
      iconId: 'settings-gear',
      command: 'agency.pack.openConfig',
      args: [p.name],
      tooltip: 'The configuration is owned by the **project** — a pack upgrade never '
        + 'overwrites it. Score threshold, skipped files, export target.' + note,
    }));
  }
  return children;
}

class ToolsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];

    const rows = [];
    const byName = Object.fromEntries((s.packs || []).map((p) => [p.name, p]));

    for (const h of s.hires || []) {
      const p = byName[h.pack] || { name: h.pack, title: h.packTitle };
      const children = [];

      // NO command on this row. A TreeItem's command fires on an ordinary
      // single click, so an informational line that launches an agent means a
      // terminal opens while you are only reading the panel. Starting a run is
      // the ▶ on the specialist's own row and nowhere else.
      children.push(node('Who handles it', {
        description: [h.provider, h.model].filter(Boolean).join(' · ')
          || 'provider default model',
        iconId: h.available ? 'rocket' : 'warning',
        color: h.available ? undefined : 'charts.orange',
        tooltip: h.available
          ? `\`${h.bin}\` · ${h.providerTitle}\n\nThe model is a property of the task, `
          + 'not of the user. The choice goes into the run record, so “which specialist '
          + 'produces better findings” is a question for the metrics rather than for '
          + 'your memory.\n\nStart a run with the ▶ on the row above.'
          : `\`${h.bin}\` is **not on PATH** — this specialist cannot run on this machine. `
          + 'The roster travels with the repository, the binaries do not; a colleague may '
          + 'well have it.',
      }));

      children.push(...packChildren(p, { shared: (s.hires || [])
        .filter((x) => x.pack === h.pack).length > 1 }));

      // The label already ends in whatever tells this worker apart, so the
      // description must not repeat it — "QA engineer · sonnet   sonnet" is
      // noise where the runner behind the model would be information.
      const extra = h.label === h.provider ? '' : h.provider;
      rows.push(node(h.display || `${p.title || p.name} · ${h.label}`, {
        id: `hire:${h.id}`,
        description: [extra, h.available ? '' : 'not on PATH']
          .filter(Boolean).join(' · '),
        iconId: h.available ? 'person' : 'person',
        color: h.available ? 'charts.green' : 'charts.orange',
        contextValue: 'agencyHire',
        collapsed: true,
        children,
        tooltip: `**${h.display}**  \`${h.id}\`\n\n${p.description || ''}\n\n---\n\n`
          + `- runner: \`${h.provider}\`${h.model ? ` · model \`${h.model}\`` : ''}\n`
          + `- method: \`${h.pack}\` — configuration, brief and findings are shared with `
          + 'every specialist hired for it\n'
          + `\n\`agency run ${h.id}\``,
      }));
    }

    // Methods nobody works by yet. Without this row there would be no way to
    // hire the first worker for a pack.
    for (const p of s.packs || []) {
      if ((s.hires || []).some((h) => h.pack === p.name)) continue;
      rows.push(node(p.title || p.name, {
        id: `pack:${p.name}`,
        description: p.installed ? 'installed, nobody hired' : 'not hired',
        iconId: 'person-add',
        contextValue: 'agencyPack.available',
        collapsed: true,
        children: packChildren(p),
        tooltip: `**${p.title || p.name}** \`${p.version}\`\n\n${p.description || ''}\n\n`
          + 'Nobody works by this method here yet. Hire the first one — and later a '
          + 'second on another provider, if you want two opinions on the same code.',
      }));
    }

    return rows;
  }
}

// --------------------------------------------------------------------- Běhy

class RunsTree extends Tree {
  roots() {
    const s = state.snapshot;
    if (!s.probe.ok) return [];
    return groupChains((s.runs || []).map((r) => runNode(r, s)), s.runs || []);
  }
}

/** Běhy jednoho řetězu pod jeden uzel — jinak vypadá tým jako několik
 *  nesouvisejících běhů a to, že druhý soudil prvního, není odkud vyčíst.
 *  Pořadí uvnitř je podle pozice, ne podle času: řetěz je sekvence. */
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
    const who = members.map(({ other }) => String(other.hire || other.pack || '?').split('@')[0]);
    // An incomplete chain must not look finished — that is what `of` is in the
    // record for.
    const short = members.length < c.of;
    // A chain whose every step "succeeded" and produced nothing used to look
    // exactly like one that worked. A failed member, and the count of calls its
    // agents were refused, are the two things that tell them apart.
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
        // Pozice patří na řádek, ne jen do tooltipu: uvnitř týmu je „kolikátý"
        // to jediné, co dva jinak stejné řádky odlišuje.
        const n = nodes[j];
        n.item.description = `step ${other.chain.position}/${other.chain.of} · ${n.item.description}`;
        return n;
      }),
      tooltip: [
        `Team run \`${c.id}\``,
        '',
        ...members.map(({ other }) =>
          `- ${other.chain.position}/${other.chain.of} \`${other.hire || other.pack}\``
          + ` — ${other.findings} findings, ${other.status}`
          + (other.denied ? `, **${other.denied} denied**` : '')),
        '',
        denied
          ? `${denied} tool call(s) were refused across this team. A member that may not `
            + 'write finishes cleanly and records nothing, which is not the same as finding '
            + 'nothing — widen `agent.allow` in the pack configuration.'
          : short
            ? `The chain stopped after ${members.length} of ${c.of} steps. `
              + 'What did run is recorded; the rest can be finished by hand.'
            : 'Each member judged what the previous one found before running its own dimensions.',
      ].join('\n'),
    }));
  });
  return out;
}

function runNode(r, s) {
  return (() => {
      const mine = s.findings.filter((f) => f.runId === r.id);
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

      // With two specialists over one pull request, "PR #12" appears twice in
      // this list. Which of them produced it is the only thing telling the two
      // rows apart, so it goes into the row itself, not just the tooltip.
      const who = r.hire || r.model || r.provider;
      // A refused tool call is not a detail. It means the run measured its own
      // authorization rather than the pack's method, and a row that hides it
      // reads as "found nothing" — the exact confusion this whole change is
      // about.
      const denied = r.denied ? ` · ${r.denied} denied` : '';
      return node(r.targetLabel || r.id.slice(0, 10), {
        id: `run:${r.id}`,
        description: `${who ? `${String(who).split('@').pop()} · ` : ''}`
          + `${r.findings} findings${denied} · ${ago(r.startedAt)}`,
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
              + 'not the method. Widen `agent.allow` in the pack configuration.\n'
            : '')
          + ((r.outputs || []).length ? `- left behind: ${r.outputs.map((n) => `\`${n}\``).join(', ')}\n` : '')
          + (r.hire ? `- specialist: \`${r.hire}\`${r.model ? ` · \`${r.model}\`` : ''}\n` : '')
          + `- ${{ 'merged-pull-request': 'retrospective audit', workspace: 'over the project as it was' }[r.kind]
            || 'open PR'}\n`
          + (r.brief ? `- brief: _${String(r.brief).slice(0, 120)}_\n` : '')
          + `- ${r.undecided} undecided\n`
          + (r.status === 'running'
            ? '\nStill open. Nothing here can see the terminal it runs in, so it stays '
            + 'open until you close it — **Close run** on this row.'
            : ''),
      });
  })();
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
