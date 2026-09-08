// The code as it was on the day of the analysis.
//
// A finding was made on a commit that has long since left your working tree.
// Without a way to look at THAT code a retrospective audit cannot be worked
// through: you look at today and guess what used to be there. Hence the custom
// `agency:` scheme — VS Code turns it into a full read-only document a thread
// can sit on and `vscode.diff` can open.
//
// Anchor resolution and the drift test are NOT here. The CLI does them and
// sends them finished in `agency outputs --json`. If both sides could do
// them, there would be two answers to the same question — and the deciding one
// would be whichever happened to run.

const vscode = require('vscode');
const cp = require('child_process');

const SCHEME = 'agency';

function git(repo, args) {
  return new Promise((resolve) => {
    cp.execFile('git', ['-C', repo, ...args],
      { maxBuffer: 32 * 1024 * 1024, encoding: 'utf8', windowsHide: true },
      (err, stdout, stderr) => resolve({ ok: !err, stdout: stdout || '', stderr: stderr || '' }));
  });
}

async function showAtCommit(repo, commit, relPath) {
  const r = await git(repo, ['show', `${commit}:${relPath}`]);
  return r.ok ? r.stdout : null;
}

async function commitExists(repo, commit) {
  if (!commit) return false;
  const r = await git(repo, ['cat-file', '-e', `${commit}^{commit}`]);
  return r.ok;
}

/** `agency:/<path>?repo=<abs>&commit=<sha>` */
function commitUri(repo, commit, relPath) {
  return vscode.Uri.from({
    scheme: SCHEME,
    path: '/' + relPath,
    query: `repo=${encodeURIComponent(repo)}&commit=${encodeURIComponent(commit)}`,
  });
}

class CommitContentProvider {
  /** @param {vscode.Uri} uri */
  async provideTextDocumentContent(uri) {
    const q = new URLSearchParams(uri.query);
    const repo = q.get('repo');
    const commit = q.get('commit');
    const rel = decodeURIComponent(uri.path.replace(/^\//, ''));
    const content = await showAtCommit(repo, commit, rel);
    if (content !== null) return content;

    // A squash-merge with a deleted branch is the GitHub default, so the
    // commit CAN be missing from the clone. The safety net is `anchor.body` on
    // the finding; this text is the last resort when even that is gone.
    return [
      `// Commit ${String(commit).slice(0, 8)} is not in this clone.`,
      `//`,
      `// Try:  git fetch origin ${commit}`,
      `// GitHub keeps refs/pull/<n>/head, so this usually works even after the branch is gone.`,
      `//`,
      `// The body of the function as of the analysis is stored in the finding (anchor.body) —`,
      `// open the finding detail in the Agency panel.`,
    ].join('\n');
  }
}

module.exports = { SCHEME, git, showAtCommit, commitExists, commitUri, CommitContentProvider };
