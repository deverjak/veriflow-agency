"""Brána mezi tím, co napsal agent, a tím, co se stane nálezem.

Agent zapíše `findings.json` a skončí. Do té chvíle je to text, ne data.
Tenhle soubor z něj dělá kandidáty — a hlavně ODMÍTÁ.

Tři důvody, proč je brána deterministická a ne další LLM krok:

  1. Zvýšený objem nálezů se nesmí propsat do zvýšeného odpadu. Odpad se pozná
     bez modelu: nález, který ukazuje na soubor, co na tom commitu neexistuje,
     je halucinace, ne názor.
  2. Model, který hlídá model, je dvakrát dražší a jednou tak spolehlivý.
  3. Zahození musí být přezkoumatelné. Proto se nic nemaže — vyřazené nálezy
     jdou do `gated.json` i s důvodem a číslo skončí v run recordu.

Brána nekontroluje kvalitu textu. Na to je `score` od packu a triage od
člověka. Kontroluje, jestli nález vůbec MŮŽE být pravdivý.
"""

from __future__ import annotations

from pathlib import Path

from . import dedup, proc
from .config import Project
from .runs import Run, load_runs, now
from .util import bundled, read_json, write_json

# Důvody vyřazení. Stejně jako u zamítnutí je to enum, ne volný text — jinak
# se nedá spočítat, čím pack nejčastěji plýtvá.
GATE_REASONS = {
    "schema": "neodpovídá finding.v1",
    "phantom-file": "soubor na analyzovaném commitu neexistuje",
    "phantom-line": "řádek je za koncem souboru v den analýzy",
    "below-score": "score pod prahem projektu",
}


def _schema_errors(findings: list[dict]) -> dict[int, list[str]]:
    """Chyby kontraktu po indexech. Bez jsonschema jen povinná pole."""
    errs: dict[int, list[str]] = {}
    try:
        import jsonschema
    except ImportError:
        required = ("id", "runId", "pack", "severity", "title", "body", "anchor", "evidence")
        for i, f in enumerate(findings):
            missing = [k for k in required if k not in f]
            if missing:
                errs[i] = [f"chybí {k}" for k in missing]
        return errs

    schema = read_json(bundled("schemas", "finding.v1.json"))
    v = jsonschema.Draft202012Validator(schema)
    for i, f in enumerate(findings):
        msgs = ["/".join(str(p) for p in e.path) + ": " + e.message for e in v.iter_errors(f)]
        if msgs:
            errs[i] = msgs
    return errs


def _exists_at_commit(root: Path, commit: str, path: str) -> tuple[bool, int | None]:
    """Byl ten soubor na tom commitu, a kolik měl řádků?

    Vrací `(True, None)`, když commit v klonu není — nedostupnost commitu není
    důkaz, že nález lže. Squash-merge se smazanou větví je na GitHubu default,
    a zahodit kvůli tomu poctivý nález by byla horší chyba než ho pustit dál.
    """
    if not commit or not proc.commit_exists(root, commit):
        return True, None
    content = proc.show_file(root, commit, path)
    if content is None:
        return False, None
    return True, content.count("\n") + 1


def gate(project: Project, run: Run, findings: list[dict], min_score: int | None) -> tuple[list[dict], list[dict]]:
    """Rozdělí nálezy na ty, co projdou, a na vyřazené i s důvodem."""
    kept: list[dict] = []
    dropped: list[dict] = []
    errs = _schema_errors(findings)

    for i, f in enumerate(findings):
        def drop(reason: str, detail: str = "") -> None:
            dropped.append({
                "id": f.get("id"), "title": f.get("title"),
                "reason": reason, "detail": detail or GATE_REASONS.get(reason, ""),
                "finding": f,
            })

        if i in errs:
            drop("schema", "; ".join(errs[i])[:400])
            continue

        a = f.get("anchor") or {}
        ok, lines = _exists_at_commit(project.root, a.get("commit") or "", a["file"])
        if not ok:
            drop("phantom-file", f"{a['file']} na {(a.get('commit') or '')[:8]} není")
            continue
        if lines is not None and a.get("line", 1) > lines:
            drop("phantom-line", f"řádek {a['line']} > {lines} řádků souboru")
            continue

        score = f.get("score")
        if min_score is not None and isinstance(score, int) and score < min_score:
            drop("below-score", f"score {score} < {min_score}")
            continue

        kept.append(f)

    return kept, dropped


def earlier_findings(project: Project, run: Run) -> list[dict]:
    """Nálezy ze starších běhů — proti nim se deduplikuje.

    Jen kandidáti a přijaté; duplicitu duplicity nemá smysl hlásit.
    """
    pool: list[dict] = []
    for r in load_runs(project):
        if r.id >= run.id:
            continue
        for f in r.findings():
            if f.get("state") in (None, "candidate", "accepted", "published"):
                pool.append(f)
    return pool


def ingest(project: Project, run: Run, min_score: int | None = None) -> dict:
    """Celá brána: kontrakt → existence → práh → dedup → zápis.

    Idempotentní. Druhé spuštění nad týmž během dá tentýž výsledek, protože se
    vždycky vychází z `findings.raw.json`, když existuje.
    """
    raw_path = run.dir / "findings.raw.json"
    if raw_path.is_file():
        findings = read_json(raw_path, default=[])
    else:
        findings = run.findings()
        if findings:
            # Původní výstup agenta se schovává stranou, aby šlo bránu pustit
            # znovu s jinými pravidly a neztratit, co pack skutečně napsal.
            write_json(raw_path, findings)

    raw_count = len(findings)
    cfg = project.pack_config(run.record().get("pack", "review-graph").split("@")[0]) or {}
    if min_score is None:
        min_score = (cfg.get("review") or {}).get("minScore")

    kept, dropped = gate(project, run, findings, min_score)
    for f in kept:
        f["fingerprint"] = dedup.fingerprint(f)

    dups = dedup.mark_duplicates(kept, earlier_findings(project, run))

    write_json(run.findings_path, kept)
    if dropped:
        write_json(run.dir / "gated.json", dropped)
    elif (run.dir / "gated.json").is_file():
        (run.dir / "gated.json").unlink()

    by_reason: dict[str, int] = {}
    for d in dropped:
        by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1

    rec = run.record()
    rec["counts"] = {
        "raw": raw_count,
        "gated": len(dropped),
        "belowScore": by_reason.get("below-score", 0),
        "duplicates": len(dups),
        "kept": len([f for f in kept if f.get("state") != "duplicate"]),
    }
    rec["gatedBy"] = by_reason or None
    rec["status"] = "ok" if kept else ("no-findings" if raw_count == 0 else "gated-out")
    rec.setdefault("finishedAt", now())
    run.save_record(rec)

    return {
        "run": run.id,
        "raw": raw_count,
        "kept": rec["counts"]["kept"],
        "duplicates": dups,
        "dropped": [{k: v for k, v in d.items() if k != "finding"} for d in dropped],
        "counts": rec["counts"],
    }
