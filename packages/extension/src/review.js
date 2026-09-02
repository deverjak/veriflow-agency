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

/** Workers whose method works over the project rather than over a pull request. */
function workspaceHires() {
  return (state.snapshot.hires || []).filter((h) => {
    const p = packInfo(h.pack);
    return p && p.installed && p.run && p.run.target === 'workspace';
  });
}

/** Workers whose method walks a pull request. */
function reviewHires() {
  return (state.snapshot.hires || []).filter((h) => {
    const p = packInfo(h.pack);
    return p && p.installed && !(p.run && p.run.target === 'workspace');
  });
}

/** Kept for callers that still think in packs — the workspace ones. */
function workspacePacks() {
  return (state.snapshot.packs || []).filter(
    (p) => p.installed && p.run && p.run.target === 'workspace');
}

/**
 * Which specialists should take this. Several may.
 *
 * Multi-select rather than a single pick, because two providers over the same
 * code is the whole reason a method can be hired more than once — and asking
 * twice would make the cheap thing feel expensive. One hired worker skips the
 * dialog entirely.
 */
async function pickHires(candidates, { title, canMultiSelect = true } = {}) {
  const usable = candidates.filter((h) => h.available);
  if (!candidates.length) return [];
  if (usable.length === 1 && candidates.length === 1) return usable;

  const picked = await vscode.window.showQuickPick(
    candidates.map((h) => ({
      label: `${h.available ? '$(person)' : '$(warning)'} ${h.display}`,
      description: h.available ? h.id : `${h.id} — \`${h.bin}\` is not on PATH`,
      detail: [h.provider, h.model].filter(Boolean).join(' · '),
      hire: h,
    })),
    {
      title,
      placeHolder: canMultiSelect
        ? 'Pick more than one to run them side by side — they share the queue and dedup'
        : 'One specialist',
      canPickMany: canMultiSelect,
      matchOnDescription: true,
    });

  if (!picked) return null;                       // Esc = odchod
  const list = (Array.isArray(picked) ? picked : [picked]).map((x) => x.hire);
  const blocked = list.filter((h) => !h.available);
  if (blocked.length) {
    vscode.window.showWarningMessage(
      `Agency: ${blocked.map((h) => h.bin).join(', ')} is not on PATH — `
      + `${blocked.map((h) => h.id).join(', ')} was skipped.`);
  }
  return list.filter((h) => h.available);
}

/**
 * Zeptá se na zadání: uložený scénář, nebo nový text.
 *
 * Vrací `{prompt, scenario}`, nebo null, když uživatel odešel. Trvalé zadání
 * z konfigurace se tady needituje — to je `agency brief`, a platí i bez editoru.
 */
async function askBrief(pack, who) {
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
      title: who ? `${who} — what is its part?` : (policy.label || 'What should this run focus on?'),
      placeHolder: standing
        ? `The standing brief always applies: ${String(standing).slice(0, 90)}`
        : 'Saved scenarios live in the pack configuration',
      matchOnDetail: true,
    });
    if (!pick) return null;
    if (!pick.fresh) return { scenario: pick.scenario };
  }

  const typed = await vscode.window.showInputBox({
    // V řetězu se ptáme po členech, takže titulek musí říct, KOMU. Jedno pole
    // pro všechny je přesně ta chyba, kvůli které recenzent odpovídal na
    // otázky psané product ownerovi.
    title: who ? `${who} — what is its part?` : (policy.label || 'What should this run focus on?'),
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
 * Prepares one run per specialist and starts each in its own terminal.
 *
 * Preparation is SEQUENTIAL on purpose even though the runs themselves are
 * parallel: `agency run` claims a worktree path, and letting two preparations
 * race would mean the guard in the core sees an empty record and hands both of
 * them the same directory. The agents then run side by side, which is the part
 * that actually costs wall-clock time.
 */
async function runEach(cwd, hires, opts, log) {
  const started = [];
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: hires.length > 1
        ? `Agency: preparing ${hires.length} runs`
        : `Agency: preparing a ${hires[0].display} run`,
      cancellable: false,
    },
    async (progress) => {
      for (const h of hires) {
        progress.report({ message: h.display });
        const result = await cli.run(cwd, h.id, opts);
        if (!result.ok) {
          const msg = result.error || 'preparation failed';
          if (result.reason === 'already-reviewed' && !opts.force) {
            const again = await vscode.window.showWarningMessage(
              `${h.display}: ${msg}`, 'Run anyway');
            if (again) {
              const forced = await cli.run(cwd, h.id, { ...opts, force: true });
              if (forced.ok) started.push(launch(forced.data, log));
              continue;
            }
            continue;
          }
          vscode.window.showErrorMessage(`Agency · ${h.display}: ${msg}`);
          if (log) log.appendLine(`[run] ${h.id} failed: ${msg}`);
          continue;
        }
        started.push(launch(result.data, log));
      }
    });

  if (started.length > 1) {
    vscode.window.showInformationMessage(
      `Agency: ${started.length} specialists are running side by side. They share one `
      + 'queue of findings, so whatever the second one repeats is marked as a duplicate '
      + 'rather than asked about twice.');
  }
  return started.length ? started[0] : null;
}

/**
 * Běh nad projektem, jak je právě teď. Bez pull requestu, bez worktree —
 * QA zkouší běžící aplikaci, a ta běží nad pracovní kopií.
 */
async function runOverWorkspace(cwd, who, log) {
  // `who` is the worker already chosen — the run button on their own row.
  // Asking again there would be asking a question the click already answered.
  let chosen = who ? [who] : null;

  if (!chosen) {
    const candidates = workspaceHires();
    if (!candidates.length) return null;
    // A session drives the running application, so two of them at once would
    // fight over the same browser, the same database and the same fixtures.
    // One at a time is the honest default here.
    chosen = await pickHires(candidates, {
      title: 'Which specialist should run the session?',
      canMultiSelect: false,
    });
    if (!chosen || !chosen.length) return null;
  }

  const brief = await askBrief(chosen[0].pack);
  if (!brief) return null;

  return runEach(cwd, chosen.slice(0, 1),
    { prompt: brief.prompt, scenario: brief.scenario }, log);
}

/**
 * Vybere PR, nechá CLI udělat deterministickou přípravu a pustí agenty.
 * Vrací data prvního běhu, nebo null, když uživatel odešel.
 */
/**
 * Který pull request. Jedno místo pro běh i pro řetěz.
 *
 * Vynechat tenhle krok znamená, že se cíl vezme z aktuální větve — a uživatel,
 * který spustil recenzi z panelu, o žádné aktuální větvi nepřemýšlel. Napsat
 * číslo PR do zadání ten cíl nezmění: zadání čte agent, cíl vybírá příprava.
 */
async function pickPr(cwd, title) {
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
        title,
        placeHolder: 'Open and merged — merged ones get a retrospective audit',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    });
  return (picked && picked.pr) || null;
}


async function pickAndRun(cwd, log) {
  const candidates = reviewHires();
  if (!candidates.length) {
    // No worker over a pull request — fall back to whatever works over the
    // project, so the button never dead-ends on a project that hired only QA.
    if (workspaceHires().length) return runOverWorkspace(cwd, null, log);
    const hire = await vscode.window.showInformationMessage(
      'Agency: nobody is hired here yet.', 'Hire a specialist');
    if (hire) await vscode.commands.executeCommand('agency.hire.add');
    return null;
  }

  const pr = await pickPr(cwd, 'Which pull request should be reviewed?');
  if (!pr) return null;

  const chosen = await pickHires(candidates, {
    title: `PR #${pr.number} — which specialists should review it?`,
  });
  if (!chosen || !chosen.length) return null;

  // Volitelné zaostření recenze. Prázdné pole je běžný stav — recenzent umí
  // celý PR sám a zadání jen mění pořadí a hloubku, ne pravidla.
  let focus;
  const info = packInfo(chosen[0].pack);
  if (info && info.run && info.run.prompt && info.run.prompt.accepts) {
    focus = await vscode.window.showInputBox({
      title: `Review of PR #${pr.number} — anything to focus on?`,
      placeHolder: (info.run.prompt.placeholder) || 'Leave empty for a full review',
      prompt: chosen.length > 1
        ? `The same brief goes to all ${chosen.length} specialists — same task, different runners.`
        : undefined,
      ignoreFocusOut: true,
    });
    if (focus === undefined) return null;   // Esc = odchod, ne prázdné zadání
  }

  return runEach(cwd, chosen, {
    pr: pr.number,
    force: pr.reviewed || undefined,
    prompt: focus || undefined,
  }, log);
}

/** Pošle hotový příkaz od CLI do terminálu. Sestavovat ho tady by byla chyba. */
function launch(data, log) {
  const agent = data.agent || {};
  const target = data.target || {};
  const what = target.pr ? `PR #${target.pr}` : (target.ref || 'session');
  // The terminal is named after the worker, not the model. With two of them on
  // one pull request, two tabs called "Agency · PR #12" would be unusable.
  const who = (data.hire && data.hire.label) || agent.model || agent.provider;
  const name = `Agency · ${what}` + (who ? ` · ${who}` : '');
  const term = vscode.window.createTerminal({ name, cwd: data.worktree });
  term.show(true);
  term.sendText(data.launch.map(quote).join(' '));

  if (log) {
    log.appendLine(`[run] ${data.runId} · ${(data.hire && data.hire.id) || agent.provider}`
      + ` · worktree ${data.worktree}`);
    log.appendLine(`[run] ${data.launch.join(' ')}`);
  }
  vscode.window.showInformationMessage(
    `Agency: run ${String(data.runId).slice(0, 10)} is ready — it is running in the terminal. `
    + 'When it finishes, run “Agency: Process run output”.');
  return data;
}

// ---------------------------------------------------------------- tým

/**
 * Řetěz specialistů. Na rozdíl od jednoho běhu tady extension nedostane hotové
 * `launch` argv: `agency chain` si běhy pouští sám (`--wait`), a proto se
 * s `--json` vylučuje — agent píše do téhož stdout. Do terminálu tedy jde
 * `agency chain …` a orchestruje pořád CLI. Hranice „jádro rozhoduje, klient
 * zobrazuje" se tím nemění, jen se posouvá o úroveň výš.
 */
/** Text uloženého scénáře. `--focus` bere volný text, takže se scénář
 *  rozbalí tady — v řetězu je zadání per člen a chain-wide `--scenario` by ho
 *  poslal všem, což je právě ta chyba, kterou `--focus` řeší. */
function scenarioText(pack, name) {
  if (!name) return null;
  const saved = ((packInfo(pack) || {}).brief || {}).scenarios || [];
  const hit = saved.find((s) => s.name === name);
  return (hit && hit.text) || null;
}


async function pickAndChain(cwd, log) {
  const candidates = (state.snapshot.hires || []).filter((h) => {
    const p = packInfo(h.pack);
    return p && p.installed;
  });
  if (candidates.length < 2) {
    vscode.window.showWarningMessage(
      'Agency: a team needs at least two specialists. Hire another one first.');
    return null;
  }

  // Pořadí je celý smysl řetězu, a QuickPick ho nezaručuje — vybírá se proto
  // po jednom. Otravnější o dvě kliknutí, zato je vidět, kdo soudí koho.
  const order = [];
  while (true) {
    const left = candidates.filter((h) => !order.includes(h));
    if (!left.length) break;
    const step = order.length + 1;
    const picked = await vscode.window.showQuickPick(
      [
        ...left.map((h) => ({
          label: `${h.available ? '$(person)' : '$(warning)'} ${h.display}`,
          description: h.available ? h.id : `${h.id} — \`${h.bin}\` is not on PATH`,
          detail: [h.provider, h.model].filter(Boolean).join(' · '),
          hire: h,
        })),
        ...(order.length >= 2
          ? [{ label: '', kind: vscode.QuickPickItemKind.Separator },
             { label: '$(check) Run the team', done: true }]
          : []),
      ],
      {
        title: `Team — step ${step}`,
        placeHolder: order.length
          ? `After ${order.map((h) => h.display).join(' → ')}. Each member judges what the previous one found.`
          : 'Who goes first? Whatever they find is handed to the next one.',
        matchOnDescription: true,
      });
    if (!picked) return null;                     // Esc = odchod
    if (picked.done) break;
    order.push(picked.hire);
  }

  if (order.length < 2) return null;

  const providers = new Set(order.map((h) => h.provider));
  if (providers.size > 1) {
    // Táž validace jako v jádře. Zopakovaná tady jen proto, aby se uživatel
    // dozvěděl teď a ne až z terminálu — jádro zůstává tím, kdo rozhoduje.
    vscode.window.showErrorMessage(
      `Agency: a chain runs on one provider at a time, and this team mixes `
      + `${[...providers].join(' and ')}.`);
    return null;
  }

  const blocked = order.filter((h) => !h.available);
  if (blocked.length) {
    vscode.window.showErrorMessage(
      `Agency: ${blocked.map((h) => h.bin).join(', ')} is not on PATH — `
      + `${blocked.map((h) => h.id).join(', ')} cannot run.`);
    return null;
  }

  // Cíl se musí vybrat, ne odvodit. Když je v týmu někdo, kdo recenzuje pull
  // request, a nikdo se nezeptá, vezme se PR aktuální větve — a číslo napsané
  // do zadání na tom nic nezmění, protože zadání čte agent, kdežto cíl vybírá
  // deterministická příprava. Členové nad projektem `--pr` prostě ignorují.
  const reviewsPr = order.some((h) => {
    const p = packInfo(h.pack);
    return p && p.run && p.run.target === 'pull-request';
  });
  let pr = null;
  if (reviewsPr) {
    pr = await pickPr(cwd, `Team ${order.map((h) => h.label || h.id).join(' → ')} — which pull request?`);
    if (!pr) return null;
  }

  // Zadání po členech, ne jedno pro všechny. Společný text mluví ke dvěma
  // lidem („udělej review a pomocí PO agenta zjisti…") a ten, komu druhá půlka
  // není určená, na ni stejně odpoví — viděno na prvním reálném řetězu.
  // Prázdné pole je legitimní: člen pak nedostane zadání žádné.
  const focus = [];
  for (const h of order) {
    const brief = await askBrief(h.pack, h.display || h.id);
    if (brief === null) return null;               // Esc nebo chybějící povinné zadání
    const text = brief.prompt || scenarioText(h.pack, brief.scenario);
    if (text) focus.push(`${h.id}:${text}`);
  }

  const args = ['chain', ...order.map((h) => h.id)];
  if (pr) args.push('--pr', String(pr.number));
  // Už zrecenzovaný commit by řetěz zastavil hned na prvním kroku. Uživatel ho
  // právě vybral ze seznamu, kde je označený — je to volba, ne omyl.
  if (pr && pr.reviewed) args.push('--force');
  for (const f of focus) args.push('--focus', f);

  const name = `Agency · team · ${order.map((h) => h.label || h.id).join(' → ')}`;
  const term = vscode.window.createTerminal({ name, cwd });
  term.show(true);
  term.sendText([cli.bin(), ...args].map(quote).join(' '));

  if (log) log.appendLine(`[chain] ${args.join(' ')}`);
  vscode.window.showInformationMessage(
    `Agency: the team is running in the terminal — ${order.length} specialists, one after another. `
    + 'Each one waits for the previous to finish.');
  return order;
}

function quote(arg) {
  const s = String(arg);
  return /[\s"']/.test(s) ? JSON.stringify(s) : s;
}

module.exports = {
  pickAndRun, pickAndChain, runOverWorkspace, askBrief, runEach, pickHires,
  workspacePacks, workspaceHires, reviewHires, items,
};
