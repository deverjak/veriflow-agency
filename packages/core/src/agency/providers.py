"""What a run can be handed to — the AI runners present on this machine.

A provider is a property of the MACHINE, not of the project. Whether you have
`codex` depends on what you installed, not on which repository you happen to
have open — which is why this table lives in `~/.agency/providers.json`, next
to the project registry, and not in `.agency/`.

Two are built in because they are the two that have been exercised. A third is
added with a command, not with a commit:

    agency providers add grok --bin grok

Were this a branch in the code, every new runner would mean a release of the
tool — and that is exactly the thing the roster (`hires.py`) exists to avoid.

The launch shape is a description, not code: which flag carries the model,
which one grants a directory outside the working copy, whether the prompt goes
positionally or behind a flag. As long as a new runner fits that shape, one row
of data is enough.
"""

from __future__ import annotations

from pathlib import Path

from . import proc
from .util import read_json, write_json

# An empty `promptFlag` means a positional argument — both claude and codex.
FIELDS = ("title", "bin", "modelFlag", "dirFlag", "promptFlag", "promptSeparator",
          "extraArgs", "models", "defaultModel")

BUILTIN: dict[str, dict] = {
    "claude": {
        "title": "Claude Code",
        "bin": "claude",
        "modelFlag": "--model",
        # RUN_DIR sits outside the worktree, and findings.json is written there.
        # Without this the agent asks for permission to write outside its
        # working directory on every single run.
        "dirFlag": "--add-dir",
        "promptFlag": None,
        # `--add-dir <directories...>` je VARIADICKÝ: bez tohohle oddělovače
        # spolkne poziční prompt jako druhý adresář a agent naběhne s prázdným
        # zadáním. Ověřeno na claude 2.1.258:
        #   claude -p --add-dir DIR "text"     → Error: Input must be provided…
        #   claude -p --add-dir DIR -- "text"  → odpoví
        # Nebylo to vidět, protože běh doběhl „úspěšně" bez nálezů.
        "promptSeparator": "--",
        "extraArgs": [],
        "models": ["opus", "sonnet", "haiku"],
        "defaultModel": None,
    },
    "codex": {
        "title": "Codex CLI",
        "bin": "codex",
        "modelFlag": "--model",
        "dirFlag": None,
        "promptFlag": None,
        # Nic variadického před promptem není, takže oddělovač není potřeba —
        # a neověřený `--` u cizího parseru je riziko, ne opatrnost.
        "promptSeparator": None,
        "extraArgs": [],
        "models": [],
        "defaultModel": None,
    },
}


def path() -> Path:
    from .registry import home
    return home() / "providers.json"


def custom() -> dict[str, dict]:
    data = read_json(path(), default={"version": 1, "providers": {}})
    return data.get("providers") or {}


def load() -> dict[str, dict]:
    """The built-ins, overlaid with whatever the user added.

    An overlay, not a replacement: someone who wants claude with a different
    binary (another path, a wrapper) overrides `bin` alone and the rest of the
    launch shape stays.
    """
    merged = {k: dict(v) for k, v in BUILTIN.items()}
    for pid, over in custom().items():
        base = merged.get(pid) or {"title": pid, "bin": pid, "modelFlag": "--model",
                                   "dirFlag": None, "promptFlag": None,
                                   # Výchozí `None`, protože cizí runner nemusí
                                   # `--` znát. Kdo ho potřebuje, nastaví si ho.
                                   "promptSeparator": None,
                                   "extraArgs": [], "models": [], "defaultModel": None}
        base.update({k: v for k, v in over.items() if k in FIELDS})
        merged[pid] = base
    return merged


def known() -> list[str]:
    return sorted(load())


def spec(provider_id: str) -> dict:
    """The launch shape of a provider. Unknown name = a binary of that name.

    An unknown name is DELIBERATELY not refused: `agency run … --provider
    myscript` should work without registering anything. Registration exists so
    a runner shows up in the picker and in the doctor, not to be mandatory.
    """
    s = load().get(provider_id)
    if s is None:
        s = {"title": provider_id, "bin": provider_id, "modelFlag": "--model",
             "dirFlag": None, "promptFlag": None, "extraArgs": [],
             "models": [], "defaultModel": None, "unregistered": True}
    out = dict(s)
    out["id"] = provider_id
    return out


def installed(provider_id: str) -> str | None:
    """Path to the binary, or None.

    This is why the roster lives in the project but availability is computed
    here: a colleague with the same repository need not have the same tools.
    """
    return proc.which(spec(provider_id).get("bin") or provider_id)


def detected() -> list[dict]:
    rows = []
    for pid, s in sorted(load().items()):
        rows.append({
            "id": pid,
            "title": s.get("title") or pid,
            "bin": s.get("bin") or pid,
            "models": s.get("models") or [],
            "defaultModel": s.get("defaultModel"),
            "builtin": pid in BUILTIN,
            "path": proc.which(s.get("bin") or pid),
        })
    for r in rows:
        r["installed"] = bool(r["path"])
    return rows


def register(provider_id: str, **fields) -> dict:
    provider_id = (provider_id or "").strip().lower()
    if not provider_id or not provider_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit(
            f"“{provider_id}” is not a usable provider id — letters, digits, - and _ only.")
    data = read_json(path(), default={"version": 1, "providers": {}})
    entry = dict((data.get("providers") or {}).get(provider_id) or {})
    entry.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
    entry.setdefault("bin", provider_id)
    entry.setdefault("title", provider_id)
    data.setdefault("providers", {})[provider_id] = entry
    data["version"] = 1
    write_json(path(), data)
    return spec(provider_id)


def forget(provider_id: str) -> bool:
    data = read_json(path(), default={"version": 1, "providers": {}})
    if provider_id not in (data.get("providers") or {}):
        return False
    data["providers"].pop(provider_id)
    write_json(path(), data)
    return True
