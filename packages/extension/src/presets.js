// Launch presets — "which runner, which model" said ahead of time.
//
// A preset is nothing more than `agency run <pack> --provider X --model Y`
// spoken in advance. It lives entirely in a VS Code setting
// (`agency.presets`, workspace-scoped) — the core knows nothing about it
// and there is no `.agency/*.json` file for it. That is deliberate: a
// roster of hired workers was the design this replaced, and a preset must
// never grow back into one — it is a shortcut for a flag, not an identity.

const vscode = require('vscode');

function all() {
  const list = vscode.workspace.getConfiguration('agency').get('presets');
  return Array.isArray(list) ? list : [];
}

function forPack(name) {
  return all().filter((p) => p.pack === name);
}

/** What a pack's own row starts on: its first preset, or nothing at all.
 *
 *  "Nothing" is not "any model will do" — it is the row's cue to ask. A run
 *  with no `--model` takes whatever the runner's session defaults to that
 *  month, which is a model nobody chose for this specialist and one the run
 *  record could not name afterwards. */
function pinned(name) {
  const [first] = forPack(name);
  return first ? { provider: first.provider, model: first.model } : null;
}

function label(p) {
  return p.label || p.model || p.provider;
}

function same(a, b) {
  return a.pack === b.pack && a.provider === b.provider && (a.model || null) === (b.model || null);
}

/** Adds a preset unless an identical one already exists. Returns whether it
 *  was actually added. */
async function add(p) {
  const list = all();
  if (list.some((x) => same(x, p))) return false;
  await vscode.workspace.getConfiguration('agency')
    .update('presets', [...list, p], vscode.ConfigurationTarget.Workspace);
  return true;
}

async function remove(p) {
  const list = all().filter((x) => !same(x, p));
  await vscode.workspace.getConfiguration('agency')
    .update('presets', list, vscode.ConfigurationTarget.Workspace);
}

module.exports = { all, forPack, pinned, label, same, add, remove };
