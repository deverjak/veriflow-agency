"""Co projekt ví — jedno místo, kde se paměť skládá.

Do 1. 9. 2026 paměť nebyla věc, byla to projekce do běhu: `known-findings.json`
vzniklo znovu do každého RUN_DIRu, strop 300 tiše zapomínal a mimo běh k paměti
nikdo přístup neměl. Vlastníkem je od té doby tenhle modul — projekce do běhu
(`for_run`) je jen jedna z jeho odpovědí, vedle úplného obrazu (`assemble`)
a výběru pro navazujícího specialistu v řetězu (`upstream`).

Pravda zůstává v `.agency/runs/`. Tenhle modul nic nevlastní — čte a skládá,
takže všechno, co vrací, se dá kdykoli přestavět. To platí i o jediné věci,
kterou zapisuje: commitovaný bundle `.agency/knowledge/` (`bundle()`) je
odvozený index paměti, ne druhý zdroj pravdy. Smazat ho a postavit znovu je
bezpečná operace; kdyby nebyla, byl by špatně.

Bundle existuje kvůli čtenáři, který nemá Agency: holá session v repu, kolega
v editoru, provider, o kterém dnes nevíme. Proto je to markdown a ne databáze.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import okf
from . import runs as _runs
from .config import Project
from .util import posix, write_json

#: Strop projekce do běhu. Je to pozadí, ne zadání: běh dostane, co se vejde do
#: okna, a nemá si podle toho myslet, že víc toho projekt neví. Navazující běh
#: v řetězu si bere `upstream()`, který strop nemá — zadání se ořezávat nesmí.
FOR_RUN_FINDINGS = 300
FOR_RUN_SPECS = 200

#: Commitovaný bundle. Všechno pod `findings/` plus `index.md` a `log.md`
#: generuje `bundle()`; `rules/` píše člověk a je to jediná část, kterou nic
#: negeneruje. Stránky packů přibudou ve Fázi 6.
BUNDLE = "knowledge"
LEDGER = "findings"
PAGES = "pages"

#: Kolik běhů se vypíše do chronologie. Strop je vidět přímo v souboru — na
#: rozdíl od stropu projekce, který tiše zapomínal (`docs/plans/tasks.md`
#: Fáze 0). Nevypsaný běh se neztratil, je o adresář vedle.
LOG_RUNS = 50


def _view(run, rec: dict, finding: dict, decision: dict | None,
          notes: list[dict] | None) -> dict:
    """Jeden nález tak, jak ho vidí někdo jiný než běh, který ho našel."""
    a = finding.get("anchor") or {}
    who = (rec.get("agent") or {}).get("hire")
    view = {
        "id": finding.get("id"), "title": finding.get("title"),
        "dimension": finding.get("dimension"), "severity": finding.get("severity"),
        "file": a.get("file"), "line": a.get("line"),
        "decision": decision["state"] if decision else None,
        "reason": decision.get("reason") if decision else None,
        # Kdo rozhodl. Rozdíl mezi „jeden model si to myslí“ a „druhý model to
        # potvrdil a člověk to přijal“ je ta nejcennější věc na vstupu — a jako
        # jeden string `decision` se ztrácela.
        "decidedBy": _runs.normalize_by(decision.get("by")) if decision else None,
        "runId": run.id,
        # Who found it. Without this there is no telling "a colleague on another
        # model already found this" from "I wrote this myself last week".
        "hire": who, "pack": rec.get("pack"),
        "provider": (rec.get("agent") or {}).get("provider"),
    }
    if notes:
        view["notes"] = [{"text": n.get("text"),
                          "by": _runs.normalize_by(n.get("by")),
                          "at": n.get("at")} for n in notes]
    return view


def assemble(project: Project, exclude: str | None = None,
             only: list[str] | None = None, with_notes: bool = True) -> dict:
    """Úplný atribuovaný obraz projektu — napříč běhy, packy a pracovníky.

    Bez stropu. Kdo si celý obraz neunese, volá `for_run`; kdo ho potřebuje
    jako zadání, volá `upstream`.
    """
    findings: list[dict] = []
    specs: list[dict] = []
    for run in _runs.load_runs(project):
        if exclude and run.id == exclude:
            continue
        if only is not None and run.id not in only:
            continue
        rec = run.record()
        decided = _runs.decisions(run)
        threads = _runs.history(run) if with_notes else {}
        for f in run.findings():
            notes = [e for e in threads.get(f.get("id"), []) if e.get("kind") == "note"]
            findings.append(_view(run, rec, f, decided.get(f.get("id")), notes))
        if (run.dir / "specs").is_dir():
            for path in sorted((run.dir / "specs").rglob("*")):
                if path.is_file():
                    specs.append({"runId": run.id,
                                  "hire": (rec.get("agent") or {}).get("hire"),
                                  "path": posix(path.relative_to(project.root))})
    return {"findings": findings, "specs": specs}


def rules(project: Project) -> list[dict]:
    """Projektová pravidla jako koncepty — vstup dimenze `repo-rules`.

    Do 1. 9. 2026 byl `review.rules` ukazatel do sekce cizího markdownu: buď
    tam byla, nebo dimenze neběžela, a nic mezi tím se zjistit nedalo. Koncept
    nese navíc stav a expiraci, takže pravidlo, které přestalo platit, se dá
    označit místo mazání — a je vidět, že přestalo platit, dřív než na něm
    někdo postaví nález. Ukazatel zůstává platný; tohle je vedle něj.
    """
    return okf.load_dir(project.agency_dir / BUNDLE / "rules",
                        kind="Rule", root=project.root)


def rules_summary(project: Project) -> dict:
    """Čím se dá pochlubit doctor: kolik jich je a kolik z nich je problém."""
    found = rules(project)
    return {
        "total": len([r for r in found if "error" not in r]),
        "expired": len([r for r in found if r.get("expired")]),
        "deprecated": len([r for r in found if r.get("status") == "deprecated"]),
        "broken": [{"path": r["path"], "error": r["error"]}
                   for r in found if "error" in r],
    }


# ------------------------------------------------------------------ stránky

def installed_packs(project: Project) -> list[str]:
    return sorted((project.installed().get("packs") or {}).keys())


def pages_dir(project: Project, pack: str, cfg: dict | None = None) -> Path:
    """Kde bydlí kurátorovaná znalost packu.

    Výchozí místo je v bundlu, ale `memory.dir` v konfiguraci packu vyhrává:
    QA, PO i právník si paměť psali do `.agency/<pack>/` dřív, než bundle
    existoval, a konfiguraci vlastní projekt — upgrade ji nepřepisuje. Přesun
    je tedy nabídka, ne migrace za zády uživatele.
    """
    cfg = cfg if cfg is not None else (project.pack_config(pack) or {})
    custom = str((cfg.get("memory") or {}).get("dir") or "").strip()
    return (project.root / custom) if custom else (project.agency_dir / BUNDLE / PAGES / pack)


def pages(project: Project, pack: str, cfg: dict | None = None) -> list[dict]:
    """Stránky packu — závěry, které si nese mezi běhy.

    Na rozdíl od nálezů je nikdo negeneruje: píše je specialista na konci běhu
    a projekt je vlastní. Proto se čtou shovívavě — stránka bez frontmatteru je
    starší stránka, ne rozbitá.
    """
    return okf.load_dir(pages_dir(project, pack, cfg), root=project.root, plain_ok=True)


def pages_summary(project: Project) -> dict:
    """Stav stránek všech najatých packů — pro doctor a `agency knowledge`."""
    out = {"total": 0, "expired": 0, "deprecated": 0, "plain": 0,
           "broken": [], "byPack": {}}
    for pack in installed_packs(project):
        found = pages(project, pack)
        if not found:
            continue
        ok = [p for p in found if "error" not in p]
        out["byPack"][pack] = len(ok)
        out["total"] += len(ok)
        out["expired"] += len([p for p in ok if p.get("expired")])
        out["deprecated"] += len([p for p in ok if p.get("status") == "deprecated"])
        # Stránka bez hlavičky se čte dál, ale neví, jestli ještě platí. Je to
        # nedodělaná migrace, ne chyba — a jako taková má být vidět.
        out["plain"] += len([p for p in ok if not p.get("frontmatter")])
        out["broken"] += [{"path": p["path"], "error": p["error"]}
                          for p in found if "error" in p]
    return out


def for_run(project: Project, run) -> dict:
    """What this project already knows — across runs, packs and specialists.

    This is the shared memory. The roster allows several workers over one pack;
    if each of them remembered only its own runs, the second provider would
    dutifully repeat everything the first one settled an hour ago, and the
    queue would grow twice as fast as the value.

    Findings carry their decision with them: "this was already rejected as
    by-design" is the most valuable sentence a new run can be handed on input.
    Dedup after ingest is a safety net, not a substitute — a session that
    starts without knowing past findings is condemned to repeat them.
    """
    ev = run.dir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    # Poznámky jsou vlákno diskuse; do pozadí běhu nepatří, do zadání pro
    # navazujícího specialistu ano.
    known = assemble(project, exclude=run.id, with_notes=False)

    write_json(ev / "known-findings.json", known["findings"][:FOR_RUN_FINDINGS])
    stats = {"knownFindings": len(known["findings"])}

    known_rules = [r for r in rules(project) if "error" not in r]
    if known_rules:
        # Bez stropu: pravidel je řádově míň než nálezů a oříznuté pravidlo je
        # díra v zadání, ne zkrácené pozadí.
        write_json(ev / "known-rules.json", known_rules)
        stats["knownRules"] = len(known_rules)
    pack = (run.record().get("pack") or "").split("@")[0]
    own_pages = [p for p in pages(project, pack) if "error" not in p] if pack else []
    if own_pages:
        # Taky bez stropu, a ze stejného důvodu jako pravidla: tohle nejsou cizí
        # nálezy na pozadí, tohle jsou vlastní závěry specialisty. Oříznout je
        # znamená nechat ho dojít k některému z nich podruhé.
        write_json(ev / "known-pages.json", own_pages)
        stats["knownPages"] = len(own_pages)
    if known["specs"]:
        # Reproduction tests from earlier runs. This is the thing a repro is
        # written as an executable file for and not as a paragraph: "is it
        # fixed yet?" is then answered by running it, not by another session.
        write_json(ev / "known-specs.json", known["specs"][:FOR_RUN_SPECS])
        stats["knownSpecs"] = len(known["specs"])
    return stats


def upstream(project: Project, run_ids: list[str]) -> dict:
    """Výběr pro navazujícího specialistu — plný, bez stropu.

    Rozdíl proti `for_run` není v datech, je v roli: tohle není pozadí, tohle je
    zadání. Nález, který se do pozadí nevešel, je nepříjemnost; nález, který se
    nevešel do zadání, je nález, o kterém druhý specialista nerozhodl.
    """
    picked = [r for r in _runs.load_runs(project) if r.id in set(run_ids)]
    known = assemble(project, only=run_ids, with_notes=True)
    return {
        "runs": [{
            "id": r.id,
            "pack": r.record().get("pack"),
            "hire": (r.record().get("agent") or {}).get("hire"),
            "summary": summary(r),
        } for r in picked],
        **known,
    }


# ------------------------------------------------------------------ ledger

def _entries(project: Project) -> list[dict]:
    """Každý nález i s tím, kdo ho zapsal a co se s ním pak dělo.

    Vlastní průchod, ne `assemble()`: projekce do běhu je záměrně útlá (tělo
    nálezu by ji nafouklo o řád) a ledger je naopak celý o textu. Jsou to dvě
    odpovědi na dvě otázky, ne jedna funkce se dvěma režimy.
    """
    found: list[dict] = []
    for run in _runs.load_runs(project):
        rec = run.record()
        pack = (rec.get("pack") or "unknown").split("@")[0]
        agent = rec.get("agent") or {}
        who = agent.get("hire") or _runs.worker_id({}, pack, provider=agent.get("provider"))
        events = _runs.history(run)
        for f in run.findings():
            found.append({
                "finding": f, "run": run, "pack": pack,
                "by": f"hire:{who}",
                "at": rec.get("finishedAt") or rec.get("startedAt"),
                "events": [e for e in events.get(f.get("id")) or []
                           if e.get("kind", "decision") == "decision"],
            })
    return found


def _root_id(by_id: dict, fid: str | None) -> str | None:
    """Kořen rodiny duplicit. Cyklus i ukazatel do zahozeného běhu končí tady."""
    seen: set[str] = set()
    while fid in by_id and fid not in seen:
        seen.add(fid)
        nxt = by_id[fid]["finding"].get("duplicateOf")
        if not nxt or nxt not in by_id:
            break
        fid = nxt
    return fid


def _is_human(by: str | None) -> bool:
    v = _runs.normalize_by(by) or ""
    return v == _runs.HUMAN or v.startswith(_runs.HUMAN + ":")


#: Kolik pozornosti nález zatím dostal. Není to totéž co `verified` a schválně:
#: `verified` jsou potvrzení TVRZENÍ, tier je míra přezkoumání. Zamítnutý nález
#: má `human-reviewed` a `status: deprecated` zároveň — člověk se na něj díval
#: a tvrzení neobstálo. Kdyby to bylo jedno pole, jedna z těch dvou vět by se
#: nedala napsat.
TIERS = ("unverified", "machine-confirmed", "human-reviewed")

#: Stav tvrzení. `deferred` není `draft` — odložený nález pořád platí, jen se
#: s ním teď nic nedělá.
STATUS_BY_DECISION = {"accepted": "stable", "deferred": "stable", "rejected": "deprecated"}


def _concept(members: list[dict], origin: dict) -> dict:
    """Rodina duplicit jako jeden nález — s tím, kdo ho potvrdil."""
    f = origin["finding"]
    a = f.get("anchor") or {}
    sym = (a.get("symbol") or {}).get("name")

    # Duplicita od TÉHOŽ pracovníka není nezávislé potvrzení, je to týž
    # pracovník podruhé. Rozdíl mezi „jeden model si to myslí“ a „shodli se
    # dva“ je celý důvod, proč se atribuce ve Fázi 1 vůbec zaváděla.
    confirmations = [m for m in members if m is not origin and m["by"] != origin["by"]]
    events = sorted((e for m in members for e in m["events"]), key=lambda e: e.get("at") or "")
    decision = events[-1] if events else None
    peers = [e for e in events
             if not _is_human(e.get("by")) and _runs.normalize_by(e.get("by")) != origin["by"]]

    if any(_is_human(e.get("by")) for e in events):
        trust = "human-reviewed"
    elif confirmations or peers:
        trust = "machine-confirmed"
    else:
        trust = "unverified"

    verified = [{"by": m["by"], "at": m["at"], "how": "independent-duplicate"}
                for m in confirmations]
    verified += [{"by": _runs.normalize_by(e.get("by")), "at": e.get("at"), "how": "accepted"}
                 for e in peers if e.get("state") == "accepted"]

    return {
        "id": f.get("id"),
        "title": f.get("title") or f.get("id"),
        "body": f.get("body") or "",
        "pack": origin["pack"],
        "dimension": f.get("dimension"),
        "severity": f.get("severity"),
        "status": STATUS_BY_DECISION.get(decision["state"], "draft") if decision else "draft",
        "trust": trust,
        "generated": {"by": origin["by"], "at": origin["at"]},
        "verified": verified,
        "decision": ({"state": decision["state"], "reason": decision.get("reason"),
                      "by": _runs.normalize_by(decision.get("by")), "at": decision.get("at")}
                     if decision else None),
        "anchor": {"file": a.get("file"), "line": a.get("line"),
                   "commit": a.get("commit"), "symbol": sym},
        "sources": [{"resource": f"agency://run/{origin['run'].id}"}]
                   + [{"resource": e.get("source"), "note": e.get("detail")}
                      for e in (f.get("evidence") or []) if e.get("source")],
        "trail": [{"by": m["by"], "at": m["at"], "run": m["run"].id,
                   "how": "found" if m is origin else "found again", "note": None}
                  for m in members]
                 + [{"by": _runs.normalize_by(e.get("by")), "at": e.get("at"),
                     "run": None, "how": e["state"], "note": e.get("reason")}
                    for e in events],
        "occurrences": len(members),
    }


def ledger(project: Project) -> list[dict]:
    """Nálezy napříč běhy, duplicity složené do rodin.

    Duplicita není další nález, je to druhý pracovník u téhož nálezu — a
    přesně tím se z ní stává `verified`. Kdyby měla vlastní soubor, ledger by
    tvrdil, že projekt našel dvakrát víc věcí, než našel.
    """
    entries = _entries(project)
    by_id = {e["finding"].get("id"): e for e in entries if e["finding"].get("id")}
    families: dict[str, list[dict]] = {}
    for e in entries:
        families.setdefault(_root_id(by_id, e["finding"].get("id")), []).append(e)

    out = []
    for rid, members in families.items():
        members.sort(key=lambda m: m["run"].id)
        origin = next((m for m in members if m["finding"].get("id") == rid), members[0])
        out.append(_concept(members, origin))
    return sorted(out, key=lambda c: c["id"] or "", reverse=True)


# ------------------------------------------------------------------ bundle

#: Skupiny v přehledu. Zamítnuté se schválně nezahazují: „tohle už jednou
#: zamítli jako by-design“ je ta nejcennější věta, kterou může další běh dostat
#: na vstupu — a v přehledu, kde by nebyla, by ji nikdo nenašel.
GROUPS = (
    ("open", "Open — nobody has decided yet"),
    ("accepted", "Accepted"),
    ("deferred", "Deferred"),
    ("rejected", "Rejected — do not report these again"),
)


def _cell(text: str | None) -> str:
    """Buňka tabulky. Svislítko v titulku by rozbilo sloupce."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _rel_link(from_dir: Path, target: Path) -> str:
    """Odkaz z bundlu jinam do repa. Stránky packu nemusí být uvnitř."""
    return posix(os.path.relpath(target, from_dir))


def _where(anchor: dict) -> str:
    f, line = anchor.get("file"), anchor.get("line")
    if not f:
        return ""
    return f"{f}:{line}" if line else f


def _finding_md(c: dict) -> str:
    """Jeden nález jako koncept — čitelný v editoru, parsovatelný `okf.read`."""
    front = {
        "type": "Finding",
        "title": c["title"],
        "status": c["status"],
        "trust": c["trust"],
        "tags": [t for t in (f"pack/{c['pack']}",
                             f"dimension/{c['dimension']}" if c["dimension"] else None,
                             f"severity/{c['severity']}" if c["severity"] else None) if t],
        "generated": c["generated"],
        "verified": c["verified"],
        "decision": c["decision"],
        "anchor": c["anchor"],
        "occurrences": c["occurrences"] if c["occurrences"] > 1 else None,
        "sources": c["sources"],
    }

    body = [c["body"].strip()]
    where = _where(c["anchor"])
    if where:
        # Odkaz vede z `.agency/knowledge/findings/` do kořene projektu, aby
        # se dal otevřít kliknutím v editoru — bez Agency a bez nástroje.
        commit = (c["anchor"].get("commit") or "")[:8]
        at = f" · commit `{commit}`" if commit else ""
        body.append(f"**Where:** [`{where}`](../../../{c['anchor']['file']}){at}")

    trail = ["**Trail**", ""]
    for t in c["trail"]:
        run = f" — [run {t['run'][:8]}](../../runs/{t['run']}/)" if t.get("run") else ""
        when = f" · {t['at'][:10]}" if t.get("at") else ""
        note = f" — {t['note']}" if t.get("note") else ""
        trail.append(f"- {t['how']} by `{t['by']}`{run}{note}{when}")
    body.append("\n".join(trail))

    return okf.dump(front, "\n\n".join(x for x in body if x))


def _index_md(project: Project, concepts: list[dict]) -> str:
    by_state: dict[str, list[dict]] = {}
    for c in concepts:
        state = (c["decision"] or {}).get("state") or "open"
        by_state.setdefault(state, []).append(c)

    confirmed = len([c for c in concepts if c["trust"] != "unverified"])
    tally = " · ".join([f"**{len(concepts)} finding{'' if len(concepts) == 1 else 's'}**"]
                       + [f"{len(by_state[s])} {s}" for s, _ in GROUPS if by_state.get(s)]
                       + ([f"{confirmed} reviewed by a second reader"] if confirmed else []))

    lines = [
        "# What this project knows",
        "",
        "Generated from `.agency/runs/` — `agency ingest` refreshes it after every "
        "run and `agency knowledge --rebuild` rewrites it from scratch. Edits here "
        "are overwritten; the truth is in the run directories. The one part written "
        "by hand is [`rules/`](rules/).",
        "",
        tally + " · [run log](log.md)",
        "",
    ]

    for state, heading in GROUPS:
        group = by_state.get(state)
        if not group:
            continue
        lines += [f"## {heading}", "",
                  "| finding | severity | where | found by | reviewed |",
                  "|---|---|---|---|---|"]
        for c in group:
            reason = (c["decision"] or {}).get("reason")
            reviewed = c["trust"] + (f" · {reason}" if reason else "")
            lines.append(
                f"| [{_cell(c['title'])}]({LEDGER}/{c['id']}.md) "
                f"| {c['severity'] or ''} | `{_where(c['anchor'])}` "
                f"| `{c['generated']['by']}` | {reviewed} |")
        lines.append("")

    by_pack = [(pack, pages(project, pack)) for pack in installed_packs(project)]
    by_pack = [(pack, own) for pack, own in by_pack if own]
    if by_pack:
        lines += ["## Pages", "",
                  "Written by the specialist at the end of a run — conclusions, "
                  "not a log. The chronology of runs is in [`log.md`](log.md).", ""]
    for pack, own in by_pack:
        # Odkaz musí vést tam, kde stránka opravdu je. Pack, který si paměť
        # nechal mimo bundle, tady není chyba — jen se to musí poznat.
        rel = _rel_link(project.agency_dir / BUNDLE, pages_dir(project, pack))
        lines += [f"### {pack}", "", "| page | status | |", "|---|---|---|"]
        for p in own:
            if "error" in p:
                lines.append(f"| `{p['path']}` | broken | {_cell(p['error'])} |")
                continue
            flags = " · ".join(f for f in ("expired" if p.get("expired") else "",
                                           "" if p.get("frontmatter") else "no frontmatter") if f)
            lines.append(f"| [{_cell(p['title'])}]({rel}/{p['id']}.md) "
                         f"| {p.get('status') or ''} | {flags} |")
        lines.append("")

    known_rules = rules(project)
    if known_rules:
        lines += ["## Rules", "",
                  "Written by hand — nothing here regenerates them.", "",
                  "| rule | status | |", "|---|---|---|"]
        for r in known_rules:
            if "error" in r:
                lines.append(f"| `{r['path']}` | broken | {_cell(r['error'])} |")
                continue
            flag = "expired" if r.get("expired") else ""
            lines.append(f"| [{_cell(r['title'])}](rules/{r['id']}.md) "
                         f"| {r.get('status') or ''} | {flag} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _log_md(project: Project) -> str:
    all_runs = _runs.load_runs(project)
    lines = [
        "# Run log",
        "",
        "Newest first. Each entry is the summary the specialist left behind "
        "(`RUN_DIR/summary.md`) — its own words, not a rendering of the findings.",
        "",
    ]
    for run in all_runs[:LOG_RUNS]:
        rec = run.record()
        agent = rec.get("agent") or {}
        pack = (rec.get("pack") or "unknown").split("@")[0]
        who = agent.get("hire") or _runs.worker_id({}, pack, provider=agent.get("provider"))
        when = (rec.get("startedAt") or "")[:10]
        counts = rec.get("counts") or {}
        kept = counts.get("kept", 0)
        tally = (f"{counts.get('raw', 0)} written → {kept} candidate{'' if kept == 1 else 's'}"
                 if counts else rec.get("status") or "")
        lines += [f"## {when} · {pack} · `hire:{who}`", "",
                  f"[run {run.id}](../runs/{run.id}/) · {tally}", ""]
        text = summary(run)
        # Běh bez shrnutí se vypíše taky. Kontrakt je v SKILL.md packů a
        # prázdné místo v chronologii je jediné, kde je vidět, že ho pack nesplnil.
        lines += [text if text else "_No summary left behind._", ""]

    if len(all_runs) > LOG_RUNS:
        lines += [f"_{len(all_runs) - LOG_RUNS} older runs are not listed here — "
                  f"they are in `.agency/runs/`._", ""]
    return "\n".join(lines).rstrip() + "\n"


def _bundle_files(project: Project) -> dict[str, str]:
    """Co má v bundlu být. Čistá funkce nad běhy — proto se dá porovnat s tím,
    co na disku je, aniž se cokoli přepíše.

    Nic tu nenese čas generování. Kdyby ano, každé přegenerování by přepsalo
    celý bundle a `git diff` by přestal odpovídat na otázku, co se změnilo.
    """
    if not _runs.load_runs(project):
        return {}
    concepts = ledger(project)
    files = {f"{LEDGER}/{c['id']}.md": _finding_md(c) for c in concepts}
    files["index.md"] = _index_md(project, concepts)
    files["log.md"] = _log_md(project)
    return files


def bundle(project: Project, write: bool = True) -> dict:
    """Zapíše (nebo jen porovná) `.agency/knowledge/`.

    Bundle je odvozený — týž statut jako `agency.db`. Kdyby se stal zdrojem
    pravdy, jeden špatný přepis by smazal historii rozhodnutí; proto se dá
    kdykoli zahodit a postavit znovu z `.agency/runs/`.
    """
    root = project.agency_dir / BUNDLE
    want = _bundle_files(project)

    have: dict[str, str] = {}
    for name in ("index.md", "log.md"):
        if (root / name).is_file():
            have[name] = (root / name).read_text(encoding="utf-8")
    for path in sorted((root / LEDGER).glob("*.md")) if (root / LEDGER).is_dir() else []:
        have[f"{LEDGER}/{path.name}"] = path.read_text(encoding="utf-8")

    changed = sorted(name for name, text in want.items() if have.get(name) != text)
    # Zahozený běh musí zmizet i z ledgeru. Maže se jen to, co bundle generuje —
    # `rules/` je vedle a nesahá se na ně.
    removed = sorted(name for name in have if name not in want)

    if write:
        for name in changed:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(want[name])
        for name in removed:
            (root / name).unlink()

    return {"path": posix(root), "findings": len(want) - 2 if want else 0,
            "changed": changed, "removed": removed, "written": write}


def summary(run) -> str | None:
    """Shrnutí, které po sobě běh nechal (`RUN_DIR/summary.md`), nebo nic.

    Kontrakt je v SKILL.md packů. Jádro ho nevyrábí ani nedopisuje: shrnutí je
    to jediné místo, kde specialista mluví vlastními slovy, a psát ho za něj by
    znamenalo vyrobit si vlastní záznam o cizí práci.
    """
    path = run.dir / "summary.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None
