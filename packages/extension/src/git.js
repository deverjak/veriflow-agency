// Kód v den analýzy.
//
// Nález vznikl na commitu, který ve tvojí pracovní kopii dávno není. Bez
// možnosti podívat se na TEN kód se retrospektivní audit nedá odbavit: díváš
// se na dnešek a hádáš, co tam bylo. Proto vlastní scheme `agency:` — VS Code
// z něj udělá plnohodnotný read-only dokument, na který jde posadit vlákno
// i pustit `vscode.diff`.
//
// Rozlišení kotvy a test driftu tady NEJSOU. Dělá je CLI a posílá je hotové
// v `agency findings --json`. Kdyby je uměly obě strany, byly by dvě odpovědi
// na tutéž otázku — a ta rozhodující by byla ta, která se zrovna spustila.

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

/** `agency:/<cesta>?repo=<abs>&commit=<sha>` */
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

    // Squash-merge se smazanou větví je na GitHubu default, takže commit
    // v klonu chybět MŮŽE. Záchranná síť je `anchor.body` v nálezu; tenhle
    // text je poslední instance, kdy ani ta není.
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
