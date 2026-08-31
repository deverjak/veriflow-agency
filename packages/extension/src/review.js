// Spuštění běhu — od výběru cíle po běžícího agenta.
//
// Cíl není vždycky pull request. Čím se pack pouští, říká jeho běhová politika
// z `agency packs --json` (`run.target`, `run.prompt`): recenzent se ptá na PR,
// QA na zadání. Kdyby to extension rozhodovala podle jména packu, byl by každý
// další specialista zásahem do klienta.
//
// Recenze se pouští v integrovaném terminálu, ne na pozadí. Není to lenost:
// attended má být vlastnost systému, ne úmysl. Když běh vidíš běžet a můžeš do
// něj mluvit, je to attended provoz. Kdyby ho extension pustila na pozadí,
// hranice attended/unattended by byla jen na tvojí paměti.
//
// Tvar spouštěcího příkazu vlastní CLI. `agency run --json` vrací hotové
// `launch` argv a extension ho jen pošle do terminálu — kdyby si ho skládala
// i ona, vzniklo by druhé místo, kde se dá nastavit model, a run record by lhal.

const vscode = require('vscode');
const cli = require('./cli.js');
const state = require('./state.js');

const STATE_ICON = { open: '$(git-pull-request)', merged: '$(git-merge)' };

function items(prs) {
  const open = prs.filter((p) => p.state === 'open');
  const merged = prs.filter((p) => p.state === 'merged');
  const list = [];

  const push = (p) => list.push({
    label: `${STATE_ICON[p.state]} #${p.number}  ${p.title || ''}`,
    description: p.reviewed ? '$(check) already reviewed' : undefined,
    detail: p.state === 'merged'
      // Retrospektivní audit je plnohodnotný režim, ne výjimka — na projektu
      // s jediným mergnutým PR by pack jinak neměl co dělat.
      ? `retrospective audit · ${(p.mergedAt || '').slice(0, 10)} · ${p.author || ''}`
      : `open · ${(p.updatedAt || '').slice(0, 10)} · ${p.author || ''}`,
    pr: p,
  });

  if (open.length) {
    list.push({ label: 'Open', kind: vscode.QuickPickItemKind.Separator });
    open.forEach(push);
  }
  if (merged.length) {
    list.push({ label: 'Merged — retrospective audit', kind: vscode.QuickPickItemKind.Separator });
    merged.forEach(push);
  }
  return list;
}

/** Metadata packu ze snímku — běhová politika, zadání, scénáře. */
function packInfo(name) {
  return (state.snapshot.packs || []).find((p) => p.name === name) || null;
}

/** Packy, které pracují nad projektem, ne nad pull requestem. */
function workspacePacks() {
  return (state.snapshot.packs || []).filter(
    (p) => p.installed && p.run && p.run.target === 'workspace');
}

/**
 * Zeptá se na zadání: uložený scénář, nebo nový text.
 *
 * Vrací `{prompt, scenario}`, nebo null, když uživatel odešel. Trvalé zadání
 * z konfigurace se tady needituje — to je `agency brief`, a platí i bez editoru.
 */
async function askBrief(pack) {
  const info = packInfo(pack) || {};
  const policy = (info.run && info.run.prompt) || {};
  const saved = (info.brief && info.brief.scenarios) || [];
  const standing = info.brief && info.brief.standing;

  if (saved.length) {
    const items = [
      ...saved.map((sc) => ({
        label: `$(bookmark) ${sc.name}`,
        detail: String(sc.text || '').slice(0, 160),
        scenario: sc.name,
      })),
      { label: '', kind: vscode.QuickPickItemKind.Separator },
      { label: '$(edit) Write a new brief…', fresh: true },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      title: policy.label || 'What should this run focus on?',
      placeHolder: standing
        ? `The standing brief always applies: ${String(standing).slice(0, 90)}`
        : 'Saved scenarios live in the pack configuration',
      matchOnDetail: true,
    });
    if (!pick) return null;
    if (!pick.fresh) return { scenario: pick.scenario };
  }

  const typed = await vscode.window.showInputBox({
    title: policy.label || 'What should this run focus on?',
    placeHolder: policy.placeholder || 'e.g. the checkout flow as a logged-out user',
    prompt: standing
      ? `The standing brief from the configuration applies on top of this: ${String(standing).slice(0, 120)}`
      : 'Free text. It is written into the run record — “which brief produces better findings” is a question worth answering with numbers.',
    ignoreFocusOut: true,
  });
  if (typed === undefined) return null;
  if (!typed.trim() && policy.required && !standing) {
    vscode.window.showWarningMessage(
      'Agency: this specialist needs to know what to work on — the run was not started.');
    return null;
  }
  return { prompt: typed.trim() || undefined };
}

/**
 * Běh nad projektem, jak je právě teď. Bez pull requestu, bez worktree —
 * QA zkouší běžící aplikaci, a ta běží nad pracovní kopií.
 */
async function runOverWorkspace(cwd, pack, log) {
  const cfg = vscode.workspace.getConfiguration('agency');
  const brief = await askBrief(pack);
  if (!brief) return null;

  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Agency: preparing a ${pack} session`,
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: 'workspace, evidence, what the project already knows…' });
      return cli.run(cwd, pack, {
        prompt: brief.prompt,
        scenario: brief.scenario,
        model: cfg.get('model') || undefined,
        provider: cfg.get('provider') || undefined,
      });
    });

  if (!result.ok) {
    const msg = result.error || 'preparation failed';
    vscode.window.showErrorMessage(`Agency: ${msg}`);
    if (log) log.appendLine(`[run] failed: ${msg}`);
    return null;
  }
  return launch(result.data, log);
}

/**
 * Vybere PR, nechá CLI udělat deterministickou přípravu a pustí agenta.
 * Vrací data běhu, nebo null, když uživatel odešel.
 */
async function pickAndRun(cwd, log) {
  const cfg = vscode.workspace.getConfiguration('agency');
  const pack = cfg.get('pack') || 'review-graph';
  const info = packInfo(pack);
  if (info && info.run && info.run.target === 'workspace') {
    return runOverWorkspace(cwd, pack, log);
  }

  const picked = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: 'Agency: loading pull requests…' },
    async () => {
      const prs = await cli.prs(cwd, { state: 'all', limit: 30 });
      if (!prs.length) {
        vscode.window.showWarningMessage(
          'Agency: no pull requests. Check `gh auth status` and that this repo has a remote.');
        return null;
      }
      return vscode.window.showQuickPick(items(prs), {
        title: 'Which pull request should be reviewed?',
        placeHolder: 'Open and merged — merged ones get a retrospective audit',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    });

  if (!picked || !picked.pr) return null;
  const pr = picked.pr;

  // Volitelné zaostření recenze. Prázdné pole je běžný stav — recenzent umí
  // celý PR sám a zadání jen mění pořadí a hloubku, ne pravidla.
  let focus;
  if (info && info.run && info.run.prompt && info.run.prompt.accepts) {
    focus = await vscode.window.showInputBox({
      title: `Review of PR #${pr.number} — anything to focus on?`,
      placeHolder: (info.run.prompt.placeholder) || 'Leave empty for a full review',
      ignoreFocusOut: true,
    });
    if (focus === undefined) return null;   // Esc = odchod, ne prázdné zadání
  }

  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Agency: preparing the review of PR #${pr.number}`,
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: 'worktree, graph, evidence…' });
      return cli.run(cwd, pack, {
        pr: pr.number,
        force: pr.reviewed || undefined,
        prompt: focus || undefined,
        model: cfg.get('model') || undefined,
        provider: cfg.get('provider') || undefined,
      });
    });

  if (!result.ok) {
    const msg = result.error || 'preparation failed';
    if (result.reason === 'already-reviewed') {
      const again = await vscode.window.showWarningMessage(msg, 'Run anyway');
      if (again) {
        const forced = await cli.run(cwd, pack, { pr: pr.number, force: true, prompt: focus || undefined });
        if (forced.ok) return launch(forced.data, log);
      }
      return null;
    }
    vscode.window.showErrorMessage(`Agency: ${msg}`);
    if (log) log.appendLine(`[run] failed: ${msg}`);
    return null;
  }

  return launch(result.data, log);
}

/** Pošle hotový příkaz od CLI do terminálu. Sestavovat ho tady by byla chyba. */
function launch(data, log) {
  const agent = data.agent || {};
  const target = data.target || {};
  const what = target.pr ? `PR #${target.pr}` : (target.ref || 'session');
  const name = `Agency · ${what}` + (agent.model ? ` · ${agent.model}` : '');
  const term = vscode.window.createTerminal({ name, cwd: data.worktree });
  term.show(true);
  term.sendText(data.launch.map(quote).join(' '));

  if (log) {
    log.appendLine(`[run] ${data.runId} · worktree ${data.worktree}`);
    log.appendLine(`[run] ${data.launch.join(' ')}`);
  }
  vscode.window.showInformationMessage(
    `Agency: run ${String(data.runId).slice(0, 10)} is ready — it is running in the terminal. `
    + 'When it finishes, run “Agency: Process run output”.');
  return data;
}

function quote(arg) {
  const s = String(arg);
  return /[\s"']/.test(s) ? JSON.stringify(s) : s;
}

module.exports = { pickAndRun, runOverWorkspace, askBrief, workspacePacks, items };
