"""Drobnosti, které používá zbytek balíčku."""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- ULID

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """ULID: 48 bitů času + 80 bitů náhody, lexikograficky řaditelné.

    Ne autoincrement — konvence 1 z plánu. Bez toho vzniknou při slučování
    dvou historií (tvoje a agentova) kolize ID.
    """
    ms = int(time.time() * 1000)
    rnd = random.getrandbits(80)
    n = (ms << 80) | rnd
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[n & 0x1F])
        n >>= 5
    return "".join(reversed(out))


# ---------------------------------------------------------------- JSON

# Rozliší „default se nepředal" od „default je None". Bez toho se
# `read_json(p, default=None)` chová jako bez defaultu a vyhodí výjimku —
# a `agency init` spadne na projektu, který prostě nemá package.json.
_NO_DEFAULT = object()


def read_json(path: Path, default: Any = _NO_DEFAULT) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        if default is _NO_DEFAULT:
            raise
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def strip_comments(obj: Any) -> Any:
    """Vyhodí klíče `$comment*` — šablony konfigurace je používají na vysvětlivky."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("$comment")}
    if isinstance(obj, list):
        return [strip_comments(x) for x in obj]
    return obj


# ---------------------------------------------------------------- cesty

def posix(p: str | Path) -> str:
    """Cesty v záznamech jsou vždy POSIX a relativní. Absolutní cesta v run
    recordu znamená, že se nedá sdílet ani commitovat — konvence 3 z plánu."""
    return str(p).replace("\\", "/")


def bundled(*parts: str) -> Path:
    """Packs a schemas — buď z wheelu, nebo z repozitáře při vývoji."""
    here = Path(__file__).resolve().parent
    inside = here / "_bundled"
    if inside.is_dir():
        return inside.joinpath(*parts)
    return here.parents[3].joinpath(*parts)  # src/agency -> core -> packages -> repo


# ---------------------------------------------------------------- output

class Out:
    """Coloured output that turns itself off when this is not a terminal."""

    def __init__(self) -> None:
        self.tty = os.isatty(1) and os.environ.get("NO_COLOR") is None
        # Progress is suppressed in --json mode; otherwise it would mix into
        # the JSON and the consumer (extension, agent) could not parse it.
        self.quiet = False

    def _c(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.tty else s

    def dim(self, s: str) -> str:
        return self._c("2", s)

    def bold(self, s: str) -> str:
        return self._c("1", s)

    def ok(self, s: str) -> str:
        return self._c("32", s)

    def warn(self, s: str) -> str:
        return self._c("33", s)

    def err(self, s: str) -> str:
        return self._c("31", s)

    def step(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {self.dim('·')} {msg}", flush=True)

    def done(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {self.ok('✓')} {msg}", flush=True)

    def fail(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {self.err('✗')} {msg}", flush=True)

    def note(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {self.warn('!')} {msg}", flush=True)

    def say(self, msg: str = "") -> None:
        if not self.quiet:
            print(msg, flush=True)


out = Out()
