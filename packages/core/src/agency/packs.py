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


@dataclass
class Pack:
    name: str
    version: str
    manifest: dict
    root: Path

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


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
    known = ", ".join(p.name for p in available()) or "(žádné)"
    raise SystemExit(f"Pack „{name}“ neznám. Dostupné: {known}")


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
            action, why = "create", "soubor v projektu není"
        else:
            cur_hash = _sha(dst.read_bytes())
            if cur_hash == new_hash:
                action, why = "keep", "shodný obsah"
            elif prev_files.get(item["to"]) and prev_files[item["to"]] != cur_hash:
                action, why = "blocked", "soubor byl ručně změněn od instalace"
            else:
                action, why = "update", f"nová verze packu ({prev.get('version', '?')} → {pack.version})"

        steps.append({"kind": "file", "to": item["to"], "src": src,
                      "action": action, "why": why, "hash": new_hash})

    cfg_rel = pack.manifest.get("config", {}).get("file")
    if cfg_rel:
        dst = project.root / cfg_rel
        steps.append({
            "kind": "config", "to": cfg_rel, "src": pack.root / pack.manifest["config"]["template"],
            # Konfiguraci vlastní projekt. Po prvním zápisu se nikdy nepřepisuje.
            "action": "keep" if dst.exists() else "create",
            "why": "konfiguraci vlastní projekt, upgrade ji nepřepisuje" if dst.exists()
                   else "šablona konfigurace",
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
                if r.get("rules") and "repo-rules" not in r.get("dimensions", []):
                    r.setdefault("dimensions", []).append("repo-rules")
            write_json(dst, cfg)
        else:
            dst.write_bytes(s["src"].read_bytes())
            files[s["to"]] = s["hash"]

    entry["version"] = pack.version
    entry["ref"] = pack.ref
    project.save_installed(state)


def installed_ref(project: Project, name: str) -> str | None:
    return ((project.installed().get("packs") or {}).get(name) or {}).get("ref")
