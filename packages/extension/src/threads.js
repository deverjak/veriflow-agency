// Findings as inline review comments at the line.
//
// This is the one thing a desktop app physically cannot do, and the reason
// Agency's UI lives in VS Code (ui-surface-decision.md §2.2). The thread sits
// right by the code, its header carries the decision, its reply box the note.
//
// A decision and a note MUST NOT share a button. A decision is structured
// input to a metric, a note is free text; mixing them breaks either the
// measurement or the usability — the spike tried it and broke both.
//
// Where a thread goes is the CLI's answer: `agency outputs --json` sends
// `resolved` (the anchor after drift) and `drift`. The extension does not
// compute it again.

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
    // The user does not start threads of their own — a comment with no finding
    // would have nowhere to belong.
    this.controller.commentingRangeProvider = { provideCommentingRanges: () => [] };
    this.threads = [];
    /** Generation: a build is async and can be started twice at once. Without
     *  the counter the second run clears the first one's threads, but the ones
     *  already in flight appear AFTER that cleanup and survive as duplicates. */
    this.generation = 0;
  }

  dispose() {
    this.clear();
    this.controller.dispose();
  }

  clear() {
    for (const t of this.threads) {
      try { t.dispose(); } catch (_) { /* already gone */ }
    }
    this.threads = [];
  }

  /** The thread for one finding. Returns where it landed — or that it did not. */
  async place(repo, f) {
    const a = f.anchor || {};
    if (!a.file) return null;
    const resolved = f.resolved || {};

    // A — into the working tree, when the anchor found something
    if (resolved.line) {
      const abs = path.join(repo, a.file);
      if (fs.existsSync(abs)) {
        return { uri: vscode.Uri.file(abs), line: resolved.line, placed: 'working-tree' };
      }
    }
    // B — onto the read-only document from the analysis commit. This is what
    //     holds a retrospective audit up: the file need not exist any more and
    //     the finding can still be read.
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

  /** Builds the threads from a snapshot of findings. Returns how many landed where. */
  async build(repo, findings) {
    const gen = ++this.generation;
    this.clear();
    const stats = { 'working-tree': 0, 'at-commit': 0, none: 0 };

    for (const f of findings) {
      if (f.state === 'duplicate') continue;   // a duplicate does not belong at the code twice
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
      // The context decides which actions are offered. On an unchanged file a
      // diff against the working tree is worthless — it would show the same
      // content twice. The presence of that button is therefore the same
      // signal as the drift test.
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

/** The thread from a command argument — it arrives from two different menus
 *  in two different shapes. */
function threadOf(arg) {
  if (!arg) return null;
  if (arg.thread) return arg.thread;      // CommentReply (comments/commentThread/context)
  if (arg.uri && arg.range) return arg;   // CommentThread (comments/commentThread/title)
  return null;
}

/** The text from the reply box. VS Code hands it over only with the editor
 *  expanded — a bonus, not an input. */
function replyTextOf(arg) {
  if (!arg || typeof arg.text !== 'string') return null;
  const t = arg.text.trim();
  return t.length ? t : null;
}

module.exports = { Threads, threadOf, replyTextOf, CONTROLLER_ID };
