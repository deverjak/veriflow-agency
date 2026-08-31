"""Jednosměrný export nálezů do GitHub Projectu.

**Jednosměrnost je rozhodnutí, ne zjednodušení.** Pravda o rozhodnutí je run
record v repu. Project je publikační cíl pro lidi, kteří VS Code neotevřou, a
místo, kde se precision dá ukázat bez nástroje. Kdyby se stavy synchronizovaly
oběma směry, vznikly by konflikty a hlavně druhý vlastník pravdy. Když někdo
změní stav přímo v Projectu, další export ho přepíše — a to je zamýšlené.

Pole se hledají JMÉNEM, ne zašitým id. Baseline zná id pro jeden konkrétní
Project (`Stav`, `Reason`), jenže druhý projekt má jiná a třetí Project nemá
vůbec. Jméno je jediné, co přežije čtyři projekty.

Idempotence stojí na dvou nezávislých nohách:
  1. `sinks.githubProjectItem` v nálezu — lokální, funguje i offline,
  2. marker `<!-- agency:finding:<id> -->` v těle položky — přežije i to, když
     se run record ztratí.
Kdyby stála jen na jedné, opakovaný export vyrobí duplicitní položky — a to je
přesně ta ruční práce, kvůli které tenhle nástroj vznikl.
"""

from __future__ import annotations

import json
import re

from . import proc
from .config import Project
from .runs import Run, decisions
from .util import write_json

MARKER = "<!-- agency:finding:{id} -->"
MARKER_RE = re.compile(r"<!-- agency:finding:([0-9A-HJKMNP-TV-Z]{26}) -->")

# Jak se rozhodnutí promítne do pole `Stav`. Kandidáti podle jména, bere se
# první, který v Projectu existuje — jména stavů se mezi projekty liší.
STATUS_CANDIDATES = {
    "accepted": ["Observed", "Accepted", "Todo", "New", "Backlog"],
    "rejected": ["Rejected"],
    "deferred": ["Deferred", "Backlog", "Icebox"],
}


class ExportError(RuntimeError):
    pass


def _gh_json(*args: str):
    r = proc.gh(*args, "--format", "json")
    if not r.ok:
        raise ExportError((r.stderr or r.stdout).strip()[:400])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise ExportError(f"gh returned unreadable JSON: {e}") from e


def project_meta(number: int, owner: str) -> dict:
    """Id Projectu a jeho pole. Jeden dotaz navíc, zato nulové zašité id."""
    view = _gh_json("project", "view", str(number), "--owner", owner)
    fields = _gh_json("project", "field-list", str(number), "--owner", owner)
    rows = fields.get("fields") if isinstance(fields, dict) else fields
    by_name = {f["name"]: f for f in (rows or [])}
    return {"id": view.get("id"), "title": view.get("title"),
            "number": number, "owner": owner, "fields": by_name}


def _option(field: dict | None, name: str) -> str | None:
    for o in (field or {}).get("options") or []:
        if o.get("name", "").lower() == str(name).lower():
            return o.get("id")
    return None


def _pick_status(field: dict | None, state: str) -> str | None:
    if not field:
        return None
    for name in STATUS_CANDIDATES.get(state, []):
        if _option(field, name):
            return name
    return None


def _existing_items(number: int, owner: str) -> dict[str, str]:
    """Marker nálezu → id položky. Druhá noha idempotence."""
    data = _gh_json("project", "item-list", str(number), "--owner", owner, "--limit", "500")
    items = data.get("items") if isinstance(data, dict) else data
    found: dict[str, str] = {}
    for it in items or []:
        content = it.get("content") or {}
        m = MARKER_RE.search(content.get("body") or "")
        if m:
            found[m.group(1)] = it.get("id")
    return found


def item_body(finding: dict, decision: dict | None, run: Run) -> str:
    a = finding.get("anchor") or {}
    t = run.record().get("target") or {}
    lines = [
        MARKER.format(id=finding["id"]),
        finding.get("body") or "",
        "",
        "---",
        "",
        f"**Where:** `{a.get('file')}:{a.get('line')}` at `{(a.get('commit') or '')[:8]}`",
    ]
    if t.get("url"):
        lines.append(f"**Source:** {t['url']}"
                     + (" · retrospective audit" if t.get("mergedAt") else ""))
    lines.append(f"**Pack:** `{finding.get('pack')}`"
                 + (f" · dimension `{finding['dimension']}`" if finding.get("dimension") else "")
                 + f" · run `{run.id}`")

    ev = finding.get("evidence") or []
    if ev:
        lines += ["", "**Evidence:**"]
        for e in ev:
            lines.append(f"- `{e.get('kind')}` — {e.get('detail')}"
                         + (f"  \n  _{e['source']}_" if e.get("source") else ""))
    if decision:
        mark = {"accepted": "accepted", "rejected": "rejected", "deferred": "deferred"}
        lines += ["", f"**Triage:** {mark.get(decision['state'], decision['state'])}"
                  + (f" — `{decision['reason']}`" if decision.get("reason") else "")
                  + (f" ({decision.get('by')})" if decision.get("by") else "")]
        if decision.get("note"):
            lines.append(f"> {decision['note']}")
    return "\n".join(lines)


def plan(runs_: list[Run], only_decided: bool = True) -> list[dict]:
    """Co by se exportovalo. Sestavuje se bez jediného síťového volání."""
    rows = []
    for run in runs_:
        dec = decisions(run)
        # Celý seznam se drží stranou, protože `push` do nálezů dopisuje
        # `sinks` — a zapsat se musí týž objekt, který se měnil, ne čerstvě
        # přečtený ze souboru. Jinak se odkaz na položku tiše ztratí a druhý
        # export založí duplicitní položku.
        allf = run.findings()
        for f in allf:
            if f.get("state") == "duplicate":
                continue
            d = dec.get(f.get("id"))
            if only_decided and not d:
                continue
            rows.append({
                "runId": run.id, "run": run, "finding": f, "decision": d, "_all": allf,
                "id": f.get("id"), "title": f.get("title"),
                "state": d["state"] if d else "candidate",
                "reason": d.get("reason") if d else None,
                "already": (f.get("sinks") or {}).get("githubProjectItem"),
            })
    return rows


def push(rows: list[dict], number: int, owner: str, dry_run: bool = False) -> dict:
    """Vytvoří nebo aktualizuje položky. Nikdy nemaže — mazání by byl sync."""
    if dry_run:
        return {"project": {"number": number, "owner": owner, "title": None},
                "created": [r for r in _slim(rows) if not r["item"]],
                "updated": [r for r in _slim(rows) if r["item"]],
                "fieldSkips": [], "failed": [], "dryRun": True}

    meta = project_meta(number, owner)
    remote = _existing_items(number, owner)
    status_field = meta["fields"].get("Stav") or meta["fields"].get("Status")
    reason_field = meta["fields"].get("Reason") or meta["fields"].get("Důvod")

    created, updated, skipped, failed = [], [], [], []
    touched: dict[str, tuple[Run, list]] = {}

    for row in rows:
        fid = row["id"]
        item_id = row["already"] or remote.get(fid)
        body = item_body(row["finding"], row["decision"], row["run"])
        title = (row["title"] or "")[:250]
        try:
            if not item_id:
                res = _gh_json("project", "item-create", str(number), "--owner", owner,
                               "--title", title, "--body", body)
                item_id = res.get("id")
                created.append({"id": fid, "title": title, "item": item_id})
            else:
                r = proc.gh("project", "item-edit", "--id", item_id,
                            "--project-id", meta["id"], "--title", title, "--body", body)
                if not r.ok:
                    raise ExportError((r.stderr or r.stdout).strip()[:300])
                updated.append({"id": fid, "title": title, "item": item_id})

            for field, value in ((status_field, _pick_status(status_field, row["state"])),
                                 (reason_field, row["reason"])):
                if not (field and value and item_id):
                    continue
                opt = _option(field, value)
                if not opt:
                    skipped.append({"id": fid, "field": field["name"],
                                    "why": f"the field has no option {value}"})
                    continue
                r = proc.gh("project", "item-edit", "--id", item_id,
                            "--project-id", meta["id"], "--field-id", field["id"],
                            "--single-select-option-id", opt)
                if not r.ok:
                    skipped.append({"id": fid, "field": field["name"],
                                    "why": (r.stderr or "").strip()[:200]})

            row["finding"].setdefault("sinks", {})["githubProjectItem"] = item_id
            touched[row["runId"]] = (row["run"], row["_all"])
        except ExportError as e:
            failed.append({"id": fid, "title": title, "error": str(e)})

    # Zpětný zápis do nálezů: kam se propsaly. Odvozený cíl, ne pravda — ale
    # bez něj se druhý export ptá GitHubu na to, co ví z vlastního repa.
    for run, allf in touched.values():
        write_json(run.findings_path, allf)

    return {"project": {"number": number, "owner": owner, "title": meta.get("title")},
            "created": created, "updated": updated,
            "fieldSkips": skipped, "failed": failed, "dryRun": False}


def _slim(rows: list[dict]) -> list[dict]:
    return [{"id": r["id"], "title": r["title"], "state": r["state"],
             "reason": r["reason"], "item": r["already"]} for r in rows]
