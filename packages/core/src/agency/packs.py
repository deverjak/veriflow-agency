"""Instalace a upgrade packů.

Model je „managed s hash pojistkou“: soubory metody vlastní nástroj a přepisují
se, ale při instalaci se uloží hash. Když ho někdo ručně změnil, upgrade odmítne
přepsat a řekne to.

Ruční úprava packu je diagnóza, ne problém — znamená, že v konfiguraci chybí
pole. Hash pojistka to řekne nahlas místo toho, aby změnu tiše přepsala.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .config import Project
from .util import bundled, posix, read_json, strip_comments, write_json


# Výchozí běhová politika packu.
#
# Existuje proto, aby CLI nemuselo znát jména packů. Recenzent potřebuje pull
# request, worktree a graf; QA potřebuje běžící aplikaci a zadání, co zkoušet.
# Kdyby o tom rozhodovalo větvení v cli.py, byl by každý další specialista
# zásahem do jádra — takhle je to políčko v manifestu.
RUN_DEFAULTS: dict = {
    # pull-request = běh se váže na PR (otevřený nebo mergnutý)
    # workspace    = běh se váže na projekt tak, jak je právě teď
    "target": "pull-request",
    # Jednorázový worktree na hlavičce PR. QA ho mít nesmí: zkouší běžící
    # aplikaci, a ta běží nad pracovní kopií s nainstalovanými závislostmi.
    "worktree": True,
    # Co pack chce od grafu. `false` = běh se grafu nedotkne; objekt vyjmenuje
    # otázky (verby `graph.py`), na kterých pack stojí. Boolean `true` ze
    # starších manifestů znamená „graf ano, verby neurčené".
    "graph": {"required": ["changes", "impact"], "optional": []},
    # Does the run need the product queue on input? A pack that decides what to
    # build starts from the open tickets, and fetching them is deterministic —
    # so it belongs to the preparation, not to the first minutes of a session.
    "backlog": False,
    "prompt": {
        # Bere pack zadání textem? Když ne, `--prompt` se u něj odmítne.
        "accepts": False,
        # Bez zadání nemá běh smysl — odmítni dřív, než vznikne prázdný běh.
        "required": False,
        "label": "What should this run focus on?",
        "placeholder": "",
    },
}


def graph_policy(value) -> dict | None:
    """Co pack chce od grafu — `None`, když nic.

    Boolean stačil, dokud byl jeden nástroj. Ve chvíli, kdy je driver
    vyměnitelný, je rozdíl mezi „potřebuju blast radius" a „hodil by se mi
    mrtvý kód" ten, který rozhoduje, jestli zhasne jedna dimenze, nebo jestli
    nemá smysl běh vůbec pouštět. Chybějící schopnost je legitimní degradace —
    ale musí být vidět dopředu, ne až tichým selháním uprostřed běhu.
    """
    if not value:
        return None
    if value is True:
        return {"required": [], "optional": []}
    return {"required": list(value.get("required") or []),
            "optional": list(value.get("optional") or [])}


@dataclass
class Pack:
    name: str
    version: str
    manifest: dict
    root: Path

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def run_policy(self) -> dict:
        """Co pack potřebuje k běhu. Chybějící pole = výchozí, ne chyba."""
        policy = dict(RUN_DEFAULTS)
        policy.update(self.manifest.get("run") or {})
        prompt = dict(RUN_DEFAULTS["prompt"])
        prompt.update(policy.get("prompt") or {})
        policy["prompt"] = prompt
        policy["graph"] = graph_policy(policy.get("graph"))
        return policy

    @property
    def skill_name(self) -> str | None:
        """Jméno skillu, který pack instaluje — pod ním si ho agent vyvolá."""
        for item in self.manifest.get("installs", []):
            to = str(item.get("to") or "")
            if to.endswith("SKILL.md"):
                return Path(to).parent.name
        return None


def packs_dir() -> Path:
    return bundled("packs")


def available() -> list[Pack]:
    d = packs_dir()
    if not d.is_dir():
        return []
    found = []
    for sub in sorted(d.iterdir()):
        m = sub / "pack.json"
        if m.is_file():
            data = read_json(m)
            found.append(Pack(data["name"], data["version"], data, sub))
    return found


def load(name: str, from_path: str | Path | None = None) -> Pack:
    if from_path:
        root = Path(from_path).resolve()
        data = read_json(root / "pack.json")
        return Pack(data["name"], data["version"], data, root)
    for p in available():
        if p.name == name:
            return p
    known = ", ".join(p.name for p in available()) or "(none)"
    raise SystemExit(f"Unknown pack “{name}”. Available: {known}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def plan(pack: Pack, project: Project) -> list[dict]:
    """Co by instalace udělala. Idempotentní — a hlavně to ŘEKNE, co udělá."""
    state = project.installed()
    prev = (state.get("packs") or {}).get(pack.name) or {}
    prev_files = prev.get("files") or {}

    steps = []
    for item in pack.manifest.get("installs", []):
        src = pack.root / item["from"]
        dst = project.root / item["to"]
        new = src.read_bytes()
        new_hash = _sha(new)

        if not dst.exists():
            action, why = "create", "the file is not in the project"
        else:
            cur_hash = _sha(dst.read_bytes())
            if cur_hash == new_hash:
                action, why = "keep", "identical content"
            elif prev_files.get(item["to"]) and prev_files[item["to"]] != cur_hash:
                action, why = "blocked", "the file was modified by hand since the installation"
            else:
                action, why = "update", f"new pack version ({prev.get('version', '?')} → {pack.version})"

        steps.append({"kind": "file", "to": item["to"], "src": src,
                      "action": action, "why": why, "hash": new_hash})

    cfg_rel = pack.manifest.get("config", {}).get("file")
    if cfg_rel:
        dst = project.root / cfg_rel
        steps.append({
            "kind": "config", "to": cfg_rel, "src": pack.root / pack.manifest["config"]["template"],
            # Konfiguraci vlastní projekt. Po prvním zápisu se nikdy nepřepisuje.
            "action": "keep" if dst.exists() else "create",
            "why": "the configuration is owned by the project, an upgrade leaves it alone"
                   if dst.exists() else "configuration template",
            "hash": None,
        })
    return steps


def apply(pack: Pack, project: Project, steps: list[dict], detected: dict | None = None) -> None:
    state = project.installed()
    packs = state.setdefault("packs", {})
    entry = packs.setdefault(pack.name, {})
    files = entry.setdefault("files", {})

    for s in steps:
        if s["action"] in ("keep", "blocked"):
            continue
        dst = project.root / s["to"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if s["kind"] == "config":
            cfg = strip_comments(read_json(s["src"]))
            cfg["pack"] = pack.ref
            if detected:
                cfg.setdefault("repo", {})["slug"] = detected.get("slug")
                r = cfg.setdefault("review", {})
                for key in ("rules", "docMap", "verifyCommand"):
                    if detected.get(key) is not None:
                        r[key] = detected[key]
                # Dimenzi přidávej jen packu, který ji má. Druhý pack tuhle
                # větev odhalil: QA žádné `repo-rules` nezná a dostávalo by
                # do konfigurace dimenzi, kterou by nikdy nepustilo.
                known = {d.get("id") for d in (pack.manifest.get("dimensions") or [])}
                if (r.get("rules") and "repo-rules" in known
                        and "repo-rules" not in r.get("dimensions", [])):
                    r.setdefault("dimensions", []).append("repo-rules")

                # Playwright, který v projektu už je, se má POUŽÍT, ne postavit
                # vedle. Proto se cesty k němu vyplní hned při instalaci —
                # jinak by je uživatel dopisoval ručně do konfigurace, kterou
                # ještě neviděl.
                pw = cfg.get("playwright")
                found = detected.get("playwright") or {}
                if isinstance(pw, dict) and found.get("present"):
                    pw["enabled"] = True
                    pw["configFile"] = found.get("configFile")
                    pw["projectTestDir"] = found.get("testDir")
            write_json(dst, cfg)
        else:
            dst.write_bytes(s["src"].read_bytes())
            files[s["to"]] = s["hash"]

    entry["version"] = pack.version
    entry["ref"] = pack.ref
    project.save_installed(state)


def installed_ref(project: Project, name: str) -> str | None:
    return ((project.installed().get("packs") or {}).get(name) or {}).get("ref")
