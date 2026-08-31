// Spuštění recenze — od výběru PR po běžícího agenta.
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

const STATE_ICON = { open: '$(git-pull-request)', merged: '$(git-merge)' };

function items(prs) {
  const open = prs.filter((p) => p.state === 'open');
  const merged = prs.filter((p) => p.state === 'merged');
  const list = [];

  const push = (p) => list.push({
    label: `${STATE_ICON[p.state]} #${p.number}  ${p.title || ''}`,
    description: p.reviewed ? '$(check) už recenzovaný' : undefined,
    detail: p.state === 'merged'
      // Retrospektivní audit je plnohodnotný režim, ne výjimka — na projektu
      // s jediným mergnutým PR by pack jinak neměl co dělat.
      ? `retrospektivní audit · ${(p.mergedAt || '').slice(0, 10)} · ${p.author || ''}`
      : `otevřený · ${(p.updatedAt || '').slice(0, 10)} · ${p.author || ''}`,
    pr: p,
  });

  if (open.length) {
    list.push({ label: 'Otevřené', kind: vscode.QuickPickItemKind.Separator });
    open.forEach(push);
  }
  if (merged.length) {
    list.push({ label: 'Prošlé — retrospektivní audit', kind: vscode.QuickPickItemKind.Separator });
    merged.forEach(push);
  }
  return list;
}

/**
 * Vybere PR, nechá CLI udělat deterministickou přípravu a pustí agenta.
 * Vrací data běhu, nebo null, když uživatel odešel.
 */
async function pickAndRun(cwd, log) {
  const cfg = vscode.workspace.getConfiguration('agency');
  const pack = cfg.get('pack') || 'review-graph';

  const picked = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: 'Agency: načítám PR…' },
    async () => {
      const prs = await cli.prs(cwd, { state: 'all', limit: 30 });
      if (!prs.length) {
        vscode.window.showWarningMessage(
          'Agency: žádné PR. Ověř `gh auth status` a že jsi v repu s remote.');
        return null;
      }
      return vscode.window.showQuickPick(items(prs), {
        title: 'Který pull request zrecenzovat?',
        placeHolder: 'Otevřené i prošlé — u prošlých se udělá retrospektivní audit',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    });

  if (!picked || !picked.pr) return null;
  const pr = picked.pr;

  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Agency: připravuji recenzi PR #${pr.number}`,
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: 'worktree, graf, evidence…' });
      return cli.run(cwd, pack, {
        pr: pr.number,
        force: pr.reviewed || undefined,
        model: cfg.get('model') || undefined,
        provider: cfg.get('provider') || undefined,
      });
    });

  if (!result.ok) {
    const msg = result.error || 'příprava selhala';
    if (result.reason === 'already-reviewed') {
      const again = await vscode.window.showWarningMessage(msg, 'Přesto spustit');
      if (again) {
        const forced = await cli.run(cwd, pack, { pr: pr.number, force: true });
        if (forced.ok) return launch(forced.data, log);
      }
      return null;
    }
    vscode.window.showErrorMessage(`Agency: ${msg}`);
    if (log) log.appendLine(`[běh] selhalo: ${msg}`);
    return null;
  }

  return launch(result.data, log);
}

/** Pošle hotový příkaz od CLI do terminálu. Sestavovat ho tady by byla chyba. */
function launch(data, log) {
  const agent = data.agent || {};
  const name = `Agency · PR #${data.target && data.target.pr}`
    + (agent.model ? ` · ${agent.model}` : '');
  const term = vscode.window.createTerminal({ name, cwd: data.worktree });
  term.show(true);
  term.sendText(data.launch.map(quote).join(' '));

  if (log) {
    log.appendLine(`[běh] ${data.runId} · worktree ${data.worktree}`);
    log.appendLine(`[běh] ${data.launch.join(' ')}`);
  }
  vscode.window.showInformationMessage(
    `Agency: běh ${String(data.runId).slice(0, 10)} připraven — recenze běží v terminálu. `
    + 'Až doběhne, spusť „Agency: Zpracovat výsledek běhu".');
  return data;
}

function quote(arg) {
  const s = String(arg);
  return /[\s"']/.test(s) ? JSON.stringify(s) : s;
}

module.exports = { pickAndRun, items };
