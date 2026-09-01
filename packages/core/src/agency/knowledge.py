"""Co projekt ví — jedno místo, kde se paměť skládá.

Do 1. 9. 2026 paměť nebyla věc, byla to projekce do běhu: `known-findings.json`
vzniklo znovu do každého RUN_DIRu, strop 300 tiše zapomínal a mimo běh k paměti
nikdo přístup neměl. Vlastníkem je od té doby tenhle modul — projekce do běhu
(`for_run`) je jen jedna z jeho odpovědí, vedle úplného obrazu (`assemble`)
a výběru pro navazujícího specialistu v řetězu (`upstream`).

Pravda zůstává v `.agency/runs/`. Tenhle modul nic nevlastní a nic nepřepisuje,
jen čte a skládá — proto se všechno, co vrací, dá kdykoli přestavět. Commitovaný
bundle `.agency/knowledge/` sem přibude v dalších krocích (`docs/plans/tasks.md`
Fáze 4–6) jako další odpověď, ne jako druhý zdroj pravdy.
"""

from __future__ import annotations

from . import runs as _runs
from .config import Project
from .util import posix, write_json

#: Strop projekce do běhu. Je to pozadí, ne zadání: běh dostane, co se vejde do
#: okna, a nemá si podle toho myslet, že víc toho projekt neví. Navazující běh
#: v řetězu si bere `upstream()`, který strop nemá — zadání se ořezávat nesmí.
FOR_RUN_FINDINGS = 300
FOR_RUN_SPECS = 200


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
