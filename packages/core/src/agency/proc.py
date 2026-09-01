"""Obálky nad git, gh a code-review-graph.

Všechno, co sahá ven, jde přes tenhle soubor — aby šlo v testech podstrčit
jedno místo a aby se windowsí zvláštnosti (kódování) řešily jednou.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass
class Result:
    ok: bool
    code: int
    stdout: str
    stderr: str

    def json(self, default: Any = None) -> Any:
        try:
            return json.loads(self.stdout)
        except (json.JSONDecodeError, ValueError):
            return default


def run(
    args: Sequence[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> Result:
    full_env = {**os.environ, **(env or {})}
    # code-review-graph kreslí Rich panely rámečkovými znaky, které v cp1250
    # konzoli padají na UnicodeEncodeError. Nastavit to globálně je levnější
    # než si pamatovat, u kterého volání to hrozí.
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        p = subprocess.run(
            list(args), cwd=str(cwd) if cwd else None, env=full_env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return Result(False, 127, "", f"{args[0]}: command not found")
    except subprocess.TimeoutExpired:
        return Result(False, 124, "", f"{args[0]}: timed out after {timeout}s")
    return Result(p.returncode == 0, p.returncode, p.stdout or "", p.stderr or "")


def which(tool: str) -> str | None:
    return shutil.which(tool)


def attend(args: Sequence[str], cwd: str | Path | None = None) -> int:
    """Spustit a počkat — s terminálem, ne s rourou. Vrací exit code.

    `run()` sbírá výstup, protože ho volající čte. Agent je opak: mluví
    s uživatelem a čeká na odpověď. Roura by z attended běhu udělala
    neattended, který zamrzne na první otázce, kterou nemá kdo přečíst — proto
    si tenhle proces stdio nechává zdědit.

    Binárku hledá `which`, i když by ji CreateProcess našlo samo: umí si totiž
    domyslet jen `.exe`. `codex` je na Windows `codex.CMD` a bez rozvinutí
    PATHEXT skončí jako FileNotFoundError. Ověřeno, ne odhad.
    """
    exe = which(args[0]) or args[0]
    try:
        return subprocess.call([exe, *args[1:]], cwd=str(cwd) if cwd else None)
    except OSError:
        # Týž kód jako u `run()`: shell hlásí nespustitelný příkaz 127.
        return 127


# ---------------------------------------------------------------- git

def git(*args: str, cwd: str | Path | None = None) -> Result:
    return run(["git", *args], cwd=cwd)


def repo_root(start: str | Path | None = None) -> Path | None:
    r = git("rev-parse", "--show-toplevel", cwd=start or Path.cwd())
    return Path(r.stdout.strip()) if r.ok else None


def head(cwd: str | Path) -> str:
    return git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


def default_branch(cwd: str | Path) -> str | None:
    r = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd)
    if r.ok:
        return r.stdout.strip().split("/", 1)[-1]
    for cand in ("main", "master"):
        if git("show-ref", "--verify", f"refs/remotes/origin/{cand}", cwd=cwd).ok:
            return cand
    return None


def remote_slug(cwd: str | Path) -> str | None:
    """owner/repo z origin, ať už je to ssh nebo https."""
    r = git("remote", "get-url", "origin", cwd=cwd)
    if not r.ok:
        return None
    url = r.stdout.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@"):
        url = url.split(":", 1)[-1]
    elif "://" in url:
        url = url.split("://", 1)[-1].split("/", 1)[-1]
    parts = [p for p in url.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def file_unchanged(cwd: str | Path, commit: str, path: str) -> bool:
    """Nezměnil se ten SOUBOR mezi commitem a HEAD?

    Pozor: rozhoduje neměnnost souboru, ne to, jestli commit == HEAD. Kdyby se
    testoval celý repozitář, propadne kotva i u nálezu na netknutém souboru.
    """
    return git("diff", "--quiet", f"{commit}..HEAD", "--", path, cwd=cwd).ok


def show_file(cwd: str | Path, commit: str, path: str) -> str | None:
    r = git("show", f"{commit}:{path}", cwd=cwd)
    return r.stdout if r.ok else None


def commit_exists(cwd: str | Path, commit: str) -> bool:
    return git("cat-file", "-e", f"{commit}^{{commit}}", cwd=cwd).ok


def browser_cache() -> str | None:
    """Kam Playwright stahuje prohlížeče, pokud tam už něco je.

    Prohlížeče nejsou v projektu, ale v uživatelském cache — proto se na ně
    `agency doctor` ptá zvlášť. Chybí typicky na čerstvém stroji a chyba, kterou
    to vyrobí, přijde až uprostřed sezení.
    """
    from pathlib import Path as _P

    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates = [override] if override and override != "0" else []
    home = _P.home()
    candidates += [
        os.environ.get("LOCALAPPDATA", "") and str(_P(os.environ["LOCALAPPDATA"]) / "ms-playwright"),
        str(home / "AppData" / "Local" / "ms-playwright"),
        str(home / "Library" / "Caches" / "ms-playwright"),
        str(home / ".cache" / "ms-playwright"),
    ]
    for c in candidates:
        if not c:
            continue
        d = _P(c)
        if d.is_dir() and any(d.iterdir()):
            return str(d)
    return None


def reachable(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Odpovídá ta adresa?

    QA sezení proti nedostupné aplikaci je vyhozený běh — a pozná se to
    dopředu, jedním dotazem. 401 a 403 jsou v pořádku: aplikace běží a jen
    chce přihlášení, což je přesně to, co se v sezení řeší.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "agency-doctor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 400, f"{url} → HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"{url} → HTTP {e.code}"
    except Exception as e:  # síť, DNS, TLS, timeout — pro doktora jeden případ
        return False, f"{url} unreachable — {type(e).__name__}"


# ---------------------------------------------------------------- gh

def gh(*args: str, cwd: str | Path | None = None) -> Result:
    return run(["gh", *args], cwd=cwd)


PR_FIELDS = (
    "number,url,title,body,state,isDraft,author,headRefName,headRefOid,"
    "baseRefName,baseRefOid,isCrossRepository,files,additions,deletions,"
    "comments,mergedAt,mergeCommit"
)


def pr_view(cwd: str | Path, number: int | None = None) -> dict | None:
    args = ["pr", "view"]
    if number is not None:
        args.append(str(number))
    args += ["--json", PR_FIELDS]
    r = gh(*args, cwd=cwd)
    return r.json() if r.ok else None


def pr_list(cwd: str | Path, state: str = "open", limit: int = 20) -> list[dict]:
    r = gh("pr", "list", "--state", state, "--limit", str(limit),
           "--json", "number,title,state,headRefOid,mergedAt,author,updatedAt", cwd=cwd)
    return r.json(default=[]) or []


def gh_login() -> str | None:
    r = gh("api", "user", "-q", ".login")
    return r.stdout.strip() if r.ok else None


def gh_scopes() -> list[str]:
    """What the signed-in token is allowed to do.

    Asked before a run, not during one: a token without `project` reads issues
    fine and then fails on the first board write, half an hour in and after the
    agent has already decided what to post.
    """
    r = gh("auth", "status")
    m = re.search(r"[Tt]oken scopes:\s*(.+)", (r.stdout or "") + (r.stderr or ""))
    if not m:
        return []
    return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]


# ---------------------------------------------- code-review-graph

CRG = "code-review-graph"


def crg(*args: str, cwd: str | Path | None = None, timeout: int = 1800) -> Result:
    return run([CRG, *args], cwd=cwd, timeout=timeout)


def crg_version() -> str | None:
    r = crg("--version")
    return r.stdout.strip() if r.ok else None


# Na stav grafu se ptá `graph.state()` — tenhle soubor je obálka nad procesem,
# ne místo, kde se rozhoduje, co je čerstvý index.
