"""Sémantický recall přes Hindsight — volitelný adaptér, výchozí vypnuto.

Bundle (`.agency/knowledge/`) dává strukturu, atribuci a přenositelnost. Nedává
„najdi mi, co je z těch tří set konceptů právě teď relevantní" — a to se
nestaví, to se adaptuje. Stejné pravidlo jako u grafu: engine nepíšeme.

Tři pravidla, na kterých tenhle soubor stojí:

  1. **Nikdy neshodí běh.** Paměť je pozadí, ne vstup, bez kterého se nedá
     pracovat. Každá cesta ven odsud vrací dict, případně s `error` — nikdy
     výjimku. Proto je `except Exception` tady záměr, ne lenost: za tou
     hranicí je cizí klient a síť.
  2. **Jen localhost.** Konfigurace harnessu (`~/.hindsight/coding-agent.json`)
     má výchozí režim `cloud`. Mlčky podle ní poslat nálezy projektu do cizí
     služby je přesně to, co má tenhle nástroj zakázané — adresa mimo tenhle
     stroj se odmítne a řekne se to.
  3. **Co se vrátilo, je vidět.** Recall zapisuje `evidence/recall.json` a
     počty jdou do run recordu. Zaznamenaný vstup, ne volná magie: bez toho by
     po deseti bězích nešlo říct, jestli adaptér přinesl něco, co bundle nedal.

Banka je `coding-agent::<jméno hlavního worktree>` — táž, kterou plní harness
pluginy (`@vectorize-io/hindsight-coding-agents`), takže interaktivní session
a běh Agency sdílejí paměť. Odvozeno z jejich `gitProjectName()`, ne
odhadnuto z README: rozhoduje jméno adresáře HLAVNÍHO worktree, takže běh
recenzenta v odloženém worktree míří do téže banky jako všechno ostatní.

Kill criteria mají v tomhle souboru mechaniku, ne dobré úmysly: co adaptér sám
uloží, nese značku `agency`. Když jsou po deseti bězích všechny zásahy recallu
vlastní, znamená to, že bundle je měl taky — a adaptér nepřinesl nic.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from . import proc
from .util import read_json, write_json

#: Prefix banky harness pluginů. Za `::` jde jméno projektu.
BANK_PREFIX = "coding-agent"
#: Port lokálního démona podle pluginu. `hindsight-client` má vlastní výchozí
#: 8888, ale to je konvence self-hosted serveru — démon poslouchá na 9077.
DEFAULT_PORT = 9077
#: Adresy, které jsou ještě „tenhle stroj".
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
#: Vteřiny. Klient má výchozí timeout 300 s, což je pro krok přípravy nesmysl:
#: běh nemá čekat pět minut na pozadí, které je volitelné.
TIMEOUT = 10.0
MAX_TOKENS = 2048
#: Značka, kterou nese všechno, co uloží tenhle adaptér.
TAG = "agency"


# ---------------------------------------------------------------- kde a jestli

def hindsight_config() -> dict:
    """`~/.hindsight/coding-agent.json` — konfigurace harness pluginů.

    Čte se schválně: kdyby si adaptér adresu vymýšlel sám, uživatel s démonem
    na jiném portu by dostal prázdnou banku a žádné vysvětlení.
    """
    return read_json(Path.home() / ".hindsight" / "coding-agent.json", default={})


def endpoint(cfg: dict) -> dict:
    """Kam se ptát — a odkud to víme. Zdroj se zapisuje, protože prázdná banka
    a špatná adresa vypadají zvenčí stejně."""
    configured = (cfg.get("recall") or {}).get("baseUrl")
    if configured:
        return {"url": configured.rstrip("/"), "source": "pack configuration"}
    if os.environ.get("HINDSIGHT_API_URL"):
        return {"url": os.environ["HINDSIGHT_API_URL"].rstrip("/"),
                "source": "HINDSIGHT_API_URL"}
    hs = hindsight_config()
    harness = "~/.hindsight/coding-agent.json"
    if hs.get("apiUrl"):
        return {"url": str(hs["apiUrl"]).rstrip("/"), "source": harness}
    if hs.get("apiPort"):
        return {"url": f"http://127.0.0.1:{hs['apiPort']}", "source": harness}
    if os.environ.get("HINDSIGHT_API_PORT"):
        return {"url": f"http://127.0.0.1:{os.environ['HINDSIGHT_API_PORT']}",
                "source": "HINDSIGHT_API_PORT"}
    return {"url": f"http://127.0.0.1:{DEFAULT_PORT}", "source": "local daemon default"}


def is_local(url: str) -> bool:
    return (urlsplit(url).hostname or "") in LOCAL_HOSTS


def bank_id(project) -> str | None:
    """`coding-agent::<jméno hlavního worktree>`, nebo None.

    None znamená „git se nezeptal" — a to je jediná správná odpověď. Banku
    s uhodnutým jménem by nikdo jiný nenašel a paměť by se tiše rozdvojila;
    plugin z téhož důvodu radši selže, než by hádal.
    """
    r = proc.git("rev-parse", "--path-format=absolute", "--git-common-dir",
                 cwd=project.root)
    if not r.ok or not r.stdout.strip():
        return None
    common = Path(r.stdout.strip())
    root = common.parent if common.name == ".git" else project.root
    return f"{BANK_PREFIX}::{root.name}"


def settings(project, cfg: dict) -> dict:
    """Stav adaptéru pro tenhle projekt a tenhle pack. Nic nevolá ven."""
    st: dict = {"enabled": bool((cfg.get("recall") or {}).get("enabled"))}
    if not st["enabled"]:
        return st

    bank = bank_id(project)
    if bank is None:
        st["error"] = "git could not name the project — refusing to guess a bank id"
        return st
    st["bank"] = bank
    st.update(endpoint(cfg))
    if not is_local(st["url"]):
        st["error"] = (f"{st['url']} is not on this machine — the adapter only talks to "
                       f"a local daemon (address came from {st['source']})")
    return st


# ---------------------------------------------------------------- klient

def _client(url: str):
    """Lazy import: bez `hindsight-client` musí zbytek nástroje fungovat dál.

    Adaptér je experiment za flagem — jeho závislost (18 balíčků s aiohttp
    a pydantic) nemá co dělat v instalaci někoho, kdo ho nezapnul.
    """
    from hindsight_client import Hindsight
    return Hindsight(url, timeout=TIMEOUT)


@contextmanager
def _session(url: str):
    """Klient, který po sobě zavře spojení.

    Bez toho aiohttp na konci procesu vypíše `Unclosed client session` — a
    varování cizí knihovny uprostřed výstupu běhu vypadá jako chyba nástroje,
    i když je to jen nezavřený socket.
    """
    client = _client(url)
    try:
        yield client
    finally:
        closer = getattr(client, "close", None)
        if callable(closer):
            closer()


MISSING = ("hindsight-client is not installed — "
           "`uv pip install hindsight-client`, or install agency with the `recall` extra")


def _fail(st: dict, exc: BaseException) -> dict:
    st["error"] = (MISSING if isinstance(exc, ImportError)
                   else f"{type(exc).__name__}: {exc}"[:300])
    return st


def _row(result) -> dict:
    """Z modelu klienta jen to, co má smysl číst v `evidence/recall.json`.

    Výřez, ne `model_dump()`: soubor čte specialista v běhu a celý objekt by mu
    do kontextu nasypal skóre, chunky a interní id, která nikam nevedou.
    """
    get = (lambda k: getattr(result, k, None))
    return {"id": get("id"), "type": get("type"), "text": get("text"),
            "context": get("context"), "documentId": get("document_id"),
            "tags": list(get("tags") or []), "at": str(get("mentioned_at") or "") or None}


def _ours(row: dict) -> bool:
    return TAG in (row.get("tags") or [])


# ---------------------------------------------------------------- recall

def query_for(pack_name: str, brief: dict | None, target: dict | None) -> str:
    """Na co se ptát. Zadání běhu, jinak cíl — víc než to by byl balast."""
    brief = brief or {}
    target = target or {}
    parts = [brief.get("focus") or brief.get("standing"), target.get("title"), pack_name]
    return " — ".join(str(p).strip() for p in parts if p)[:600]


def for_run(project, run, cfg: dict, brief: dict | None = None,
            target: dict | None = None) -> dict:
    """Recall před spuštěním agenta. Zapisuje `evidence/recall.json`.

    Soubor vzniká i když se nic nevrátilo. „Zeptal jsem se a nic tam nebylo" a
    „adaptér byl vypnutý" jsou dvě různá tvrzení a po deseti bězích se budou
    rozlišovat.
    """
    st = settings(project, cfg)
    if not st["enabled"] or st.get("error"):
        return st

    pack_name = (run.record().get("pack") or "").split("@")[0]
    st["query"] = query_for(pack_name, brief, target)
    try:
        with _session(st["url"]) as client:
            answer = client.recall(bank_id=st["bank"], query=st["query"],
                                   max_tokens=MAX_TOKENS)
        rows = [_row(r) for r in (getattr(answer, "results", None) or [])]
    except Exception as e:  # cizí klient a síť — viz pravidlo 1 v hlavičce
        return _fail(st, e)

    st["results"] = rows
    st["foreign"] = len([r for r in rows if not _ours(r)])
    write_json(run.dir / "evidence" / "recall.json", {
        "bank": st["bank"], "query": st["query"],
        # Kolik z toho nepřišlo od nás. Tohle číslo je celé kill criterion:
        # samé vlastní zásahy znamenají, že bundle měl totéž.
        "foreign": st["foreign"], "results": rows,
    })
    return st


# ---------------------------------------------------------------- retain

def _retain(project, cfg: dict, content: str, context: str,
            document_id: str, tags: list[str]) -> dict:
    st = settings(project, cfg)
    if not st["enabled"] or st.get("error"):
        return st
    try:
        with _session(st["url"]) as client:
            client.retain(bank_id=st["bank"], content=content, context=context,
                          document_id=document_id, tags=[TAG, *tags],
                          metadata={"source": TAG, "project": project.name})
    except Exception as e:
        return _fail(st, e)
    st["retained"] = document_id
    return st


def after_ingest(project, run, cfg: dict) -> dict:
    """Shrnutí běhu do banky — po bráně, ne po agentovi.

    Ukládá se `summary.md`, protože to je jediný text, kde specialista říká
    vlastními slovy, co dělal. Kandidáti se neukládají: nálezy, o kterých
    nikdo nerozhodl, jsou tvrzení, ne znalost, a banka plná neověřených
    tvrzení by recall utopila.
    """
    summary = run.dir / "summary.md"
    if not summary.is_file():
        st = settings(project, cfg)
        st["skipped"] = "the run left no summary.md"
        return st
    rec = run.record()
    pack = (rec.get("pack") or "").split("@")[0]
    return _retain(project, cfg, summary.read_text(encoding="utf-8"),
                   context=f"agency run {run.id} · {rec.get('pack')}",
                   document_id=f"agency:run:{run.id}", tags=[f"pack:{pack}"])


def after_decision(project, run, cfg: dict, finding: dict, event: dict) -> dict:
    """Rozhodnutí o nálezu do banky.

    Tohle je ta polovina, kterou plán čekal „po ingestu": v tu chvíli ale ještě
    nic přijaté není — brána vyrábí kandidáty, přijímá se až v triage. Zamítnutí
    je přitom cennější než přijetí: „reconsent flow je pro tenhle web
    irelevantní" je znalost o produktu, kterou příště nemá smysl objevovat
    znovu.
    """
    rec = run.record()
    pack = (rec.get("pack") or "").split("@")[0]
    reason = f" ({event['reason']})" if event.get("reason") else ""
    note = f"\n{event['note']}" if event.get("note") else ""
    content = (f"{event['state'].capitalize()}{reason}: {finding.get('title') or ''}\n"
               f"{finding.get('body') or ''}{note}")
    return _retain(project, cfg, content,
                   context=f"agency triage · {event.get('by')} · {rec.get('pack')}",
                   document_id=f"agency:finding:{finding.get('id')}",
                   tags=[f"pack:{pack}", f"decision:{event['state']}"])
