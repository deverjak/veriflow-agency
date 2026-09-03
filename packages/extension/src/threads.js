// Nálezy jako inline review komentáře u řádku.
//
// Tohle je jediná věc, kterou desktopová aplikace fyzicky neumí a kvůli které
// UI Agency žije ve VS Code (ui-surface-decision.md §2.2). Vlákno sedí přímo
// u kódu, hlavička nese rozhodnutí, pole odpovědi poznámku.
//
// Rozhodnutí a poznámka NESMÍ sdílet tlačítko. Rozhodnutí je strukturovaný
// vstup metriky, poznámka volný text; smíchat je znamená rozbít buď měření,
// nebo použitelnost — ve spiku to bylo zkoušené a rozbilo to obojí.
//
// Kam vlákno umístit, říká CLI: `agency findings --json` posílá `resolved`
// (kotva po driftu) a `drift`. Extension to nepočítá znovu.

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const gitx = require('./git.js');

const CONTROLLER_ID = 'agency.findings';

const SEV_ICON = { blocker: '🔴', high: '🔴', medium: '🟠', low: '🟡' };

const DRIFT_LABEL = {
  untouched: '✅ **The code has not changed since the analysis** — the finding holds literally.',
  touched: '⚠️ **This code was touched since the analysis** — it may be fixed, look at the diff.',
  deleted: '🗑️ **The file was deleted after the analysis.**',
  unknown: '❔ The commit is not in this clone, drift cannot be evaluated.',
};

class Threads {
  constructor(log) {
    this.log = log;
    this.controller = vscode.comments.createCommentController(CONTROLLER_ID, 'Agency — findings');
    // Uživatel nezakládá vlastní vlákna — komentář bez nálezu by neměl kam patřit.
    this.controller.commentingRangeProvider = { provideCommentingRanges: () => [] };
    this.threads = [];
    /** Generace: build je asynchronní a dá se spustit dvakrát naráz. Bez čítače
     *  druhý běh uklidí vlákna prvního, ale ta rozdělaná vzniknou AŽ PO úklidu
     *  a přežijí jako duplikáty. */
    this.generation = 0;
  }

  dispose() {
    this.clear();
    this.controller.dispose();
  }

  clear() {
    for (const t of this.threads) {
      try { t.dispose(); } catch (_) { /* už zaniklo */ }
    }
    this.threads = [];
  }

  /** Vlákno pro jeden nález. Vrací, kam se posadilo — nebo že nikam. */
  async place(repo, f) {
    const a = f.anchor || {};
    if (!a.file) return null;
    const resolved = f.resolved || {};

    // A — do pracovní kopie, když kotva něco našla
    if (resolved.line) {
      const abs = path.join(repo, a.file);
      if (fs.existsSync(abs)) {
        return { uri: vscode.Uri.file(abs), line: resolved.line, placed: 'working-tree' };
      }
    }
    // B — na read-only dokument z commitu analýzy. Tohle drží retrospektivní
    //     audit: soubor už nemusí existovat a nález se pořád dá přečíst.
    if (await gitx.commitExists(repo, a.commit)) {
      const content = await gitx.showAtCommit(repo, a.commit, a.file);
      if (content !== null && a.line <= content.split('\n').length) {
        return { uri: gitx.commitUri(repo, a.commit, a.file), line: a.line, placed: 'at-commit' };
      }
    }
    return null;
  }

  head(f) {
    const a = f.anchor || {};
    const md = new vscode.MarkdownString();
    md.isTrusted = true;
    md.appendMarkdown(`**${f.title}**\n\n`);
    if (f.body) md.appendMarkdown(`${f.body}\n\n`);
    md.appendMarkdown('---\n\n');
    md.appendMarkdown(`${DRIFT_LABEL[f.drift] || DRIFT_LABEL.unknown}\n\n`);
    md.appendMarkdown(`Found at \`${String(a.commit || '').slice(0, 8)}\` · `
      + `\`${a.file}:${a.line}\``);
    if (f.resolved && f.resolved.note) md.appendMarkdown(` · ${f.resolved.note}`);
    const ev = (f.evidence || []).length;
    if (ev) md.appendMarkdown(`\n\nEvidence: ${ev}× — [full detail](command:agency.finding.open?${
      encodeURIComponent(JSON.stringify([f.id]))})`);
    return {
      body: md,
      mode: vscode.CommentMode.Preview,
      author: { name: `${SEV_ICON[f.severity] || '🟡'} ${(f.pack || 'agency').split('@')[0]}` },
      contextValue: 'agencyFinding',
    };
  }

  history(f) {
    return (f.history || []).map((e) => {
      const md = new vscode.MarkdownString();
      if ((e.kind || 'decision') === 'note') {
        md.appendMarkdown(e.text || '');
        return { body: md, mode: vscode.CommentMode.Preview, author: { name: `📝 ${e.by}` } };
      }
      const mark = { sent: '→ Sent', rejected: '✘ Rejected' }[e.state] || e.state;
      md.appendMarkdown(`**${mark}**${e.reason ? ` — \`${e.reason}\`` : ''}`);
      if (e.note) md.appendMarkdown(`\n\n${e.note}`);
      return { body: md, mode: vscode.CommentMode.Preview, author: { name: `⚖ ${e.by}` } };
    });
  }

  /** Postaví vlákna ze snímku nálezů. Vrací, kolik se jich kam posadilo. */
  async build(repo, findings) {
    const gen = ++this.generation;
    this.clear();
    const stats = { 'working-tree': 0, 'at-commit': 0, none: 0 };

    for (const f of findings) {
      if (f.state === 'duplicate') continue;   // duplicita nepatří ke kódu podruhé
      const spot = await this.place(repo, f);
      if (gen !== this.generation) return { stats, cancelled: true };
      if (!spot) { stats.none += 1; continue; }

      const doc = await vscode.workspace.openTextDocument(spot.uri);
      if (gen !== this.generation) return { stats, cancelled: true };
      const line = Math.min(Math.max(spot.line, 1), doc.lineCount) - 1;

      const head = this.head(f);
      const thread = this.controller.createCommentThread(
        spot.uri, new vscode.Range(line, 0, line, 0), [head, ...this.history(f)]);
      thread.collapsibleState = vscode.CommentThreadCollapsibleState.Collapsed;
      thread.canReply = true;
      // Kontext řídí, které akce se nabídnou. U nezměněného souboru je diff
      // proti pracovní kopii bezcenný — ukázal by tentýž obsah dvakrát.
      // Přítomnost toho tlačítka je tím pádem tentýž signál jako test driftu.
      thread.contextValue = f.drift === 'touched' ? 'agencyFinding.drifted'
        : f.drift === 'deleted' ? 'agencyFinding.deleted' : 'agencyFinding';
      const mark = f.state === 'sent' ? `→ ${f.ref || 'board'} ` : f.state === 'rejected' ? '✘ ' : '';
      thread.label = mark + String(f.title || '').slice(0, 70);
      thread.state = (f.state === 'sent' || f.state === 'rejected')
        ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
      thread._agency = { finding: f, repo, placed: spot.placed };
      this.threads.push(thread);
      stats[spot.placed] += 1;
    }

    if (this.log) {
      this.log.appendLine(`[threads] ${this.threads.length} of ${findings.length} findings `
        + `(working tree ${stats['working-tree']}, from commit ${stats['at-commit']}, `
        + `unplaced ${stats.none})`);
    }
    return { stats, cancelled: false };
  }
}

/** Vlákno z argumentu příkazu — přichází ze dvou různých menu s jiným tvarem. */
function threadOf(arg) {
  if (!arg) return null;
  if (arg.thread) return arg.thread;      // CommentReply (comments/commentThread/context)
  if (arg.uri && arg.range) return arg;   // CommentThread (comments/commentThread/title)
  return null;
}

/** Text z pole odpovědi. VS Code ho předá jen s rozbaleným editorem — bonus, ne vstup. */
function replyTextOf(arg) {
  if (!arg || typeof arg.text !== 'string') return null;
  const t = arg.text.trim();
  return t.length ? t : null;
}

module.exports = { Threads, threadOf, replyTextOf, CONTROLLER_ID };
