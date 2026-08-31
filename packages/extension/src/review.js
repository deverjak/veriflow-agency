// Klikací spuštění recenze.
//
// Tok: vyber PR → CLI udělá deterministickou přípravu → recenze se pustí
// v integrovaném terminálu.
//
// Ten terminál není lenost. Attended má být vlastnost systému, ne úmysl —
// když běh vidíš běžet a můžeš do něj mluvit, je to attended provoz. Kdyby
// extension pustila recenzi na pozadí, byla by hranice attended/unattended
// jen na tvojí paměti.

const vscode = require('vscode');
const agency = require('./agency.js');

const SEV = { open: '$(git-pull-request)', merged: '$(git-merge)' };

/** Sestaví položky QuickPicku ze seznamu PR. */
function items(prs) {
  const open = prs.filter((p) => p.state === 'open');
  const merged = prs.filter((p) => p.state === 'merged');
  const list = [];

  const push = (p) => list.push({
    label: `${SEV[p.state]} #${p.number}  ${p.title || ''}`,
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

async function pickAndRun(cwd, log) {
  const picked = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: 'Agency: načítám PR…' },
    async () => {
      const prs = await agency.prs(cwd, { state: 'all', limit: 30 });
      if (!prs.length) {
        vscode.window.showWarningMessage(
          'Agency: žádné PR. Ověř `gh auth status` a že jsi v repu s remote.');
        return null;
      }
      return vscode.window.showQuickPick(items(prs), {
        title: 'Který PR zrecenzovat?',
        placeHolder: 'Otevřené i prošlé — u prošlých se udělá retrospektivní audit',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    });

  if (!picked || !picked.pr) return null;
  const pr = picked.pr;

  let result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Agency: připravuji recenzi PR #${pr.number}`,
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: 'worktree, graf, grafový signál…' });
      return agency.run(cwd, 'review-graph', { pr: pr.number });
    });

  // Odmítnutí kvůli už recenzovanému commitu není chyba — je to idempotence.
  // Nabídni opakování místo hlášky, kterou uživatel neumí obejít.
  if (!result.ok && result.reason === 'already-reviewed') {
    const again = await vscode.window.showWarningMessage(
      `${result.error}`, 'Přesto spustit', 'Zrušit');
    if (again !== 'Přesto spustit') return null;
    result = await agency.run(cwd, 'review-graph', { pr: pr.number, force: true });
  }

  if (!result.ok) {
    vscode.window.showErrorMessage(`Agency: ${result.error || 'příprava selhala'}`);
    log.appendLine(`[run] selhalo: ${result.error}`);
    return null;
  }

  const d = result.data;
  log.appendLine(`[run] ${d.runId} · PR #${pr.number} · ${d.files} souborů · worktree ${d.worktree}`);

  // Tvar spuštění vlastní CLI, ne extension — model i provider si projekt
  // konfiguruje v .agency/, a kdyby si příkaz skládala i extension, byly by
  // dvě místa, kde se to dá nastavit různě.
  const argv = d.launch && d.launch.length ? d.launch : ['claude', d.prompt];
  const cmd = argv
    .map((a, i) => (i === 0 || /^[-\w./:@=]+$/.test(a) ? a : JSON.stringify(a)))
    .join(' ');

  const model = (d.agent && d.agent.model) || 'výchozí model';
  const term = vscode.window.createTerminal({
    name: `Agency · PR #${pr.number} · ${model}`,
    cwd: d.worktree,
    iconPath: new vscode.ThemeIcon('search'),
  });
  term.show(true);
  term.sendText(cmd);

  vscode.window.showInformationMessage(
    `Agency: běh ${d.runId.slice(0, 8)} připraven, recenze běží v terminálu (${model}).`,
    'Otevřít běh',
  ).then((choice) => {
    if (choice === 'Otevřít běh') {
      vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(d.runDir));
    }
  });

  return d;
}

module.exports = { pickAndRun, items };
