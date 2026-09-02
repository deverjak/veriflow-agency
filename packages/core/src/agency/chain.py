"""Řetěz specialistů — běh, počkej, předej, další.

`docs/plans/teams.md` Krok 3. Chain **není konverzace**: je to sekvence běhů,
kde si členové předávají soubory, ne zprávy v session. Všechno, co si agenti
„řeknou", je append-only událost nad nálezem (`decisions.jsonl`) nebo soubor,
který po sobě nechal běh (`handoff.md`, `summary.md`, `findings.json`) — takže
se to dá po jednotlivých událostech přehrát a zpětně obhájit. Tuhle filozofii
nevymýšlí chain, jen ji používá: stojí na ní triage od začátku.

Co tenhle modul **nedělá** a dělat nemá:

  * **Nerozhoduje o pořadí.** Seznam členů píše člověk. Žádný LLM orchestrátor
    mezi běhy — úsudek patří dovnitř běhů, protože tam je zaznamenaný,
    atribuovaný a zaplacený jednou.
  * **Nepíše obsah promptu.** Šablonu vlastní jádro (`step_prompt`), ale věty
    v ní jsou slova upstream agenta z jeho `handoff.md`. „Orchestrátor skládá
    prompt" tedy znamená šablona + cizí slova, ne skrytý třetí model.
  * **Neresuscituje přerušený řetěz.** Běhy jsou zapsané; dokončit je jde ručně.
    `--resume` přijde, až bude doopravdy potřeba.

Řetěz drží pohromadě blok `chain` v `run.json` (`run.v1`), ne pořadí adresářů.
Bez něj by se zpětně nedalo poznat, které rozhodnutí padlo nad cizím nálezem
v rámci předání a které samostatně — a to je celý rozdíl mezi týmem a několika
běhy za sebou.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hires, knowledge
from .config import Project
from .util import write_json

#: Kolik řádků handoffu se vejde do promptu dalšího člena. Zbytek je v souboru,
#: na který prompt odkazuje — strop je tady proto, že vykopávací věta má být
#: k přečtení, ne k prolistování.
HANDOFF_LINES = 40


@dataclass
class Member:
    """Jeden člen řetězu tak, jak ho `agency chain` dostal na příkazové řádce."""
    ref: str
    pack: str
    hire: hires.Hire | None

    @property
    def label(self) -> str:
        return self.hire.id if self.hire else self.pack


def resolve(project: Project, refs: list[str]) -> list[Member]:
    """Jména z příkazové řádky na členy. `hires.resolve` rozhoduje stejně jako u `run`.

    Jméno hire vyhrává nad jménem packu — kdyby to bylo naopak, hire pojmenovaný
    po svém packu by byl nedosažitelný.
    """
    return [Member(ref, *hires.resolve(project, ref)) for ref in refs]


def one_provider(members: list[Member]) -> str | None:
    """Chyba, když řetěz míchá providery — jinak None.

    Vědomé zúžení v1 (`teams.md` §3.2), ne architektonická překážka: handoff je
    souborový, takže mix providerů je změna téhle jedné funkce. Zúžení existuje
    kvůli terminálu — jeden binár, jeden credential, jedna sada quirků — a padne,
    až se pipeline osvědčí. Do té doby je lepší odmítnout hned než uprostřed.
    """
    seen = {m.hire.provider for m in members if m.hire}
    if len(seen) <= 1:
        return None
    named = ", ".join(f"{m.label} ({m.hire.provider})" for m in members if m.hire)
    return (f"a chain runs on one provider at a time, and this one mixes "
            f"{' and '.join(sorted(seen))}: {named}. Run them separately, or pick "
            f"workers from the same provider.")


#: Co z orchestračního bloku smí do `run.json`. `chain` má v `run.v1` zavřený
#: seznam klíčů, takže vzkaz předchůdce ani zadání per člen — věci, které
#: orchestrátor v tomtéž dictu vozí — do záznamu nepatří. Bez tohohle filtru
#: byl každý týmový běh neplatný záznam a `agency validate` to hlásilo.
RECORD_KEYS = ("id", "position", "of", "upstream")


def block(chain_id: str, position: int, of: int, upstream: list[str]) -> dict:
    """Blok `chain` do run recordu. Tvar hlídá `run.v1`."""
    return {"id": chain_id, "position": position, "of": of, "upstream": list(upstream)}


def record_block(chain: dict) -> dict:
    """Jen to, co `run.v1` u bloku `chain` zná. Zbytek je věc orchestrátoru."""
    return {k: chain[k] for k in RECORD_KEYS if k in chain}


def find_member(project, chain_id: str, position: int):
    """Běh, který v řetězu obsadil tuhle pozici — nebo None.

    Chain se po každém kroku ptá takhle, a ne „který běh je nejnovější": nejnovější
    běh může být cizí (paralelní recenzent nad týmž PR je podporovaný případ),
    kdežto blok `chain` je identita, kterou si běh nese sám.
    """
    from .runs import load_runs
    for run in load_runs(project):
        c = run.record().get("chain") or {}
        if c.get("id") == chain_id and c.get("position") == position:
            return run
    return None


def handoff_text(run) -> tuple[str | None, str | None]:
    """Co upstream běh vzkazuje dál — a odkud to je.

    `handoff.md` je adresné („co potřebuješ ty"), `summary.md` je popisné („co
    jsem udělal"). Když je obojí, vyhrává adresné; když nic, vrací se `None` a
    prompt se opře jen o počty. Mlčení je legitimní výsledek — vymyslet za agenta
    vzkaz, který nenapsal, by bylo tvrzení, za které se nikdo nepodepsal.
    """
    for name in ("handoff.md", "summary.md"):
        path = run.dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return _clip(text, HANDOFF_LINES), name
    return None, None


def _clip(text: str, limit: int) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n… ({len(lines) - limit} more lines in the file)"


def write_upstream(project: Project, run, upstream_ids: list[str]) -> dict:
    """`evidence/upstream.json` — co dostal tenhle člen na vstupu.

    **Bez stropu, a to je celý rozdíl proti `known-findings.json`.** Tři sta je
    strop pozadí: nález, který se do pozadí nevejde, je nepříjemnost. Tohle je
    zadání — nález, který se nevejde do zadání, je nález, o kterém druhý
    specialista nerozhodl, a řetěz by tiše vyráběl díry ve vlastním výstupu.
    """
    data = knowledge.upstream(project, upstream_ids)
    undecided = len([f for f in data["findings"] if not f.get("decision")])
    payload = {
        "runs": data["runs"],
        "findings": data["findings"],
        "specs": data["specs"],
        "counts": {"findings": len(data["findings"]), "undecided": undecided},
    }
    write_json(run.dir / "evidence" / "upstream.json", payload)
    return payload


def step_prompt(base: str, member: Member, position: int, of: int,
                upstream: list[dict], counts: dict, handoff: str | None) -> str:
    """Vykopnutí člena řetězu — deterministicky, ze šablony jádra.

    Celý složený prompt jde do `prompt.txt` běhu, takže kvalita vykopnutí je
    čitelná a laditelná. To je důvod, proč šablonu vlastní jádro a ne pack:
    kdyby si ji každý pack psal sám, nedalo by se porovnat, proč jeden člen
    pochopil svou roli a druhý ne.
    """
    lines = [base, f"You are step {position}/{of} of a chain ({member.label})."]

    if not upstream:
        lines.append("You run first — nobody has handed you anything. "
                     "Whatever you write is the input of the next member.")
        return " ".join(lines[:2]) + "\n" + lines[2]

    who = ", ".join(u.get("hire") or (u.get("pack") or "?") for u in upstream)
    lines.append(
        f"Upstream: {who} — {counts['findings']} findings "
        f"({counts['undecided']} undecided), full data in evidence/upstream.json.")
    # Soud nad cizím nálezem je práce, kterou má člen odvést PŘED vlastními
    # dimenzemi: jinak dorazí k rozhodnutí s hlavou plnou vlastních nálezů a
    # cizí odbude. Pořadí je proto v promptu, ne jen v SKILL.md.
    lines.append(
        "First judge those findings — `agency triage accept|reject|defer <id> "
        "--by hire:<your id from context.json>`, or `agency note` when you are "
        "unsure — and only then run your own dimensions.")
    if handoff:
        lines.append(f"Handoff from {who}:\n{handoff}")
    return "\n".join(lines)


def per_member(members: list[Member], focus: list[str]) -> dict[str, str]:
    """`--focus po:"…"` — zadání pro jednoho člena, ne pro celý řetěz.

    Bez tohohle dostávali všichni týž `--prompt`. Na prvním reálném řetězu to
    dopadlo přesně tak, jak muselo: uživatel napsal „udělej review a pomocí PO
    agenta zjisti, jestli to dává produktový smysl", recenzent tu druhou půlku
    přečetl jako svoji a začal odpovídat na produktové otázky. Věta adresovaná
    někomu jinému není kontext, je to matoucí instrukce.

    Klíčem je jméno, kterým člen v řetězu vystupuje — id pracovníka, nebo jméno
    packu, když se řetěz skládal z packů. Neznámé jméno se odmítne: tiše
    zahozené zadání je horší než chybová hláška.
    """
    known = {m.label for m in members} | {m.pack for m in members} | {m.ref for m in members}
    out_: dict[str, str] = {}
    for item in focus:
        who, sep, text = str(item).partition(":")
        who, text = who.strip(), text.strip()
        if not sep or not who or not text:
            raise SystemExit(f"Expected <who>:<text>, got “{item}”.")
        if who not in known:
            raise SystemExit(
                f"“{who}” is not in this chain. Members: {', '.join(m.label for m in members)}")
        for m in members:
            if who in (m.label, m.pack, m.ref):
                out_[m.label] = text
    return out_
