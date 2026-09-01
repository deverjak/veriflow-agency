# Pořadí prací — grafová vrstva a sdílená paměť

**Datum:** 2026-09-01
**Zdrojové plány:** [`graph-abstraction.md`](graph-abstraction.md) · [`shared-memory.md`](shared-memory.md) · [`teams.md`](teams.md)

Tenhle dokument je **jen sekvence**. Žádná argumentace, žádné nové rozhodnutí — každá položka odkazuje do plánu, kde je popsaná celá. Když se něco rozchází, platí plán, ne tenhle seznam.

---

## Co drží pořadí

Tři vazby, zbytek je volný:

1. **Společný Krok 1 je první.** Identita `by`, `summary.md`, `knowledge.py`. Bez nich nemá ledger nálezů z čeho stavět `verified` tiery a rozhodnutí agenta se nedá odlišit od ručního v CLI.
2. **Graf jde před ledgerem nálezů.** `evidence.source` má jmenovat `agency graph …`, ne `code-review-graph` ([`graph-abstraction.md`](graph-abstraction.md) Krok 4/4). Ledger ta jména zhmotní do markdownu — přejmenovat se musí dřív, než vzniknou.
3. **Hindsight orchestrátor je poslední** — potřebuje `agency run --wait` z [`teams.md`](teams.md) Kroku 2. Harness hooky nezávisejí na ničem a jdou zkusit hned.

---

## Fáze 0 — JSON místo regexů (~2 h) — **hotovo 1. 9. 2026**

> [`graph-abstraction.md`](graph-abstraction.md) → **Krok 0**. Nezávislé na všem ostatním, čistý zisk.

- [x] `runs.py` — zahodit `--brief`, číst plný JSON; regexový blok i lokální `import re as _re` pryč
- [x] `runs.py` — `dead-code --json`, ukládat jako `.json`
- [x] `proc.py` — `crg_status` přes `status --json`, místo `raw` rozparsovaný dict (doctor teď hlásí i uzly a soubory)
- [x] ověřit, že `changedFiles` / `changedFunctions` / `affectedFlows` / `untestedFunctions` / `riskScore` pořád sedí na `run.v1`

**Hotovo, když:** jeden běh nad projektem s postaveným grafem má v `run.v1` vyplněné všechny grafové statistiky a v `runs.py` není žádný `re.search` nad výstupem CRG. — ✅ ověřeno proti CRG 2.3.7, `tests/test_graph_evidence.py` (5 testů) to zamyká.

### Co plán nepředpokládal

- **`changedFiles` se přestalo číst z grafu.** V JSON to číslo není (jen ve větě shrnutí) a graf navíc počítá svůj diff, ne ten po `skipPatterns`. Bere se ze seznamu, který jádro samo odfiltrovalo — stejně jako u workspace běhu.
- **CRG řeže změněné funkce na 500** (`CRG_MAX_CHANGED_FUNCS`) a ten strop hlásí ve shrnutí jako výsledek. Nový příznak `changedFunctionsTruncated` v `run.v1` z toho dělá dolní odhad místo tichého faktu.
- **`knownFindings`/`knownSpecs` se slévaly do `run.graph`**, který má v `run.v1` zavřený seznam klíčů — každý grafový běh tedy psal neplatný záznam. Nikdo si toho nevšiml, protože `agency validate` kontroluje `finding.v1` a `run.v1` nikdo. Paměť teď bydlí v `evidence`; **`run.v1` pořád nikdo nevaliduje** — kandidát na samostatný úkol.
- **Promptová plocha se musela posunout hned:** `packs/review-graph/skill/SKILL.md` odkazovalo na `detect-changes.txt`, `dead-code.txt` a na seznam „Untested:" z panelu, který přestal existovat. Zbytek promptové plochy zůstává na Fázi 3.

### Souběžně, na ničem nezávisle

- [ ] Hindsight harness hooky — [`shared-memory.md`](shared-memory.md) → **Krok 5**, třetí odrážka. `npx @vectorize-io/hindsight-coding-agents install claude-code` / `codex` (ten chce `codex_hooks = true`). Vyhodnocuje se samo, neblokuje nic a nic z něj neblokuje.

---

## Fáze 1 — společný základ (~1 den)

> [`shared-memory.md`](shared-memory.md) → **Krok 1** (= [`teams.md`](teams.md) Krok 1, dělá se jednou). Plná specifikace tam.

- [ ] **a)** strukturovaná identita `by`: `hire:<id>` / `human`; legacy `cli` a `extension` se při čtení mapují na `human`. Dotčené: `runs.py:804`, `cli.py:1905,1930`, zápis z extension, SKILL.md packů, které triagují
- [ ] **b)** `RUN_DIR/summary.md` jako výstup běhu (~30 řádků); kontrakt v SKILL.md, `ingest` zaznamená přítomnost
- [ ] **c)** `knowledge.py` — `assemble` / `for_run` / `upstream` / `bundle`; `known_memory()` se stává jeho konzumentem, výstupní soubory beze změny

**Hotovo, když:** rozhodnutí agenta nese `hire:<id>`, běh po sobě nechává `summary.md`, a `runs.py` už paměť neskládá — jen volá `knowledge.py`.

---

## Fáze 2 — grafový šev (~1,5 dne)

> [`graph-abstraction.md`](graph-abstraction.md) → **Krok 1** a **Krok 2**.

- [ ] `packages/core/src/agency/graph.py`: verby `state` / `refresh` / `changes` / `impact` / `locate` / `neighbors` + extended `unreferenced` / `tests_for`; typované dicty, parsing uvnitř, `capabilities()` se ptá předem
- [ ] přepojit `runs.py:451,545,560,566`, `anchor.py:95`, `cli.py:396-400`
- [ ] `config.py:83` — `hasGraph` přes `graph.state()` místo natvrdo `.code-review-graph/graph.db` (jediná věc z Kroku 3 vzatá hned)
- [ ] `agency graph <verb>` s `--json` jako výchozím výstupem
- [ ] `packs.py:35` — `graph` politika z booleanu na `{required, optional}`; doctor umí říct „pack chce `tests-for`, driver ho neumí“

**Hotovo, když:** chybějící schopnost je vidět v doctoru předem, ne až tichým selháním uprostřed běhu.

---

## Fáze 3 — graf v promptu a v záznamu (~2 h)

> [`graph-abstraction.md`](graph-abstraction.md) → **Krok 4**. Dělá se před ledgerem (vazba 2 nahoře).

- [ ] `packs/review-graph/skill/SKILL.md:63-64,128` a `packs/qa/skill/SKILL.md:174-175` → `agency graph locate|neighbors|tests-for`
- [ ] běh zapíše `RUN_DIR/evidence/graph-capabilities.json`; SKILL.md pravidlo *„co driver neumí, se nedokládá“*
- [ ] `schemas/run.v1.json:152` — ke `graph.tool` přidat `driver` a `capabilities`
- [ ] `schemas/finding.v1.json:90,95` — popisy `evidence.kind` / `evidence.source` přestanou jmenovat `code-review-graph`

**Hotovo, když:** po výměně driveru se pozná, jestli nálezů ubylo kvůli horšímu nástroji, nebo jen proto, že zmizel `dead-code`.

---

## Fáze 4 — pravidla jako koncepty (~1 den)

> [`shared-memory.md`](shared-memory.md) → **Krok 2** (argumentace [`graph-abstraction.md`](graph-abstraction.md) §5.4).

- [ ] `.agency/knowledge/rules/` — `type: Rule`, `status`, `stale_after`, `verified`
- [ ] dimenze `repo-rules` čte strukturovaný vstup místo ukazatele do cizího markdownu
- [ ] doctor: „5 pravidel, 1 po expiraci“

**Hotovo, když:** padlo první reálné rozhodnutí o tvaru frontmatteru — na nejmenším možném soustu.

---

## Fáze 5 — ledger nálezů (~1–2 dny)

> [`shared-memory.md`](shared-memory.md) → **Krok 3** (argumentace [`graph-abstraction.md`](graph-abstraction.md) §5.1–5.3).

- [ ] `bundle()` generuje `.agency/knowledge/findings/<id>.md` + `index.md` + `log.md` (chronologie ze `summary.md`)
- [ ] `verified` tiery z atribuce Fáze 1: `hire:…@codex` našel → `hire:…@claude` potvrdil → `human` přijal
- [ ] zapisuje `ingest` po bráně; jde přegenerovat příkazem — pravda zůstává v `.agency/runs/`

**Hotovo, když:** paměť přečte holá session v repu bez Agency i kolega v editoru — bez nástroje a bez účtu.

---

## Fáze 6 — knowledge pages packů (~1 den)

> [`shared-memory.md`](shared-memory.md) → **Krok 4**.

- [ ] `.agency/knowledge/pages/<pack>/` — PO `product-decisions.md`, `roadmap-context.md` · QA `weak-areas.md`, `test-lore.md` · legal `obligations-map.md`
- [ ] SKILL.md: na konci běhu aktualizuj svoje stránky — **závěry, ne log**; co přestalo platit, smaž nebo `deprecated`
- [ ] příprava běhu stránky packu přibalí do kontextu
- [ ] v1 jen packy s `worktree: false` (po, qa, legal); reviewer až v druhé vlně přes RUN_DIR

---

## Fáze 7 — Hindsight recall adaptér (experiment, za flagem)

> [`shared-memory.md`](shared-memory.md) → **Krok 5**, orchestrátorová část. Blokuje ji [`teams.md`](teams.md) **Krok 2** (`agency run --wait`, ~půl dne) — jinak není kam recall/retain zavěsit.

- [ ] `agency run --wait` z [`teams.md`](teams.md) Kroku 2 (subprocess, exit code, auto-ingest)
- [ ] `hindsight-client`, výhradně lokální daemon (`--server daemon`), banka `coding-agent::{gitProject}`
- [ ] **recall** před spuštěním → `evidence/recall.json` · **retain** po `ingest` → `summary.md` + přijaté nálezy
- [ ] po ~10 bězích vyhodnotit kill criteria; když recall nepřinesl nic nad bundle, adaptér zhasnout

---

## Odloženo — čeká na spouštěč

| co | odkud | spouštěč |
|---|---|---|
| `graph/drivers/`, workspace strategie | [`graph-abstraction.md`](graph-abstraction.md) Krok 3 | až fyzicky přibývá druhý grafový nástroj |
| `agency chain`, handoff, steering, extension | [`teams.md`](teams.md) Kroky 3–6 | vlastní plán; z tohoto pořadí se z něj bere jen Krok 2 do Fáze 7 |

---

## Souhrn

| fáze | odkud | rozsah | čeká na |
|---|---|---|---|
| 0 — JSON místo regexů | graph Krok 0 | ~2 h | nic |
| 0b — Hindsight harness hooky | shared-memory Krok 5 | ~1 h | nic (souběžně) |
| 1 — společný základ | shared-memory Krok 1 = teams Krok 1 | ~1 den | nic |
| 2 — `graph.py` + `agency graph` | graph Kroky 1–2 | ~1,5 dne | 0 |
| 3 — prompt plocha + schémata | graph Krok 4 | ~2 h | 2 |
| 4 — `rules/` | shared-memory Krok 2 | ~1 den | 1 |
| 5 — `findings/` ledger | shared-memory Krok 3 | ~1–2 dny | 1, 3, 4 |
| 6 — knowledge pages | shared-memory Krok 4 | ~1 den | 5 |
| 7 — Hindsight adaptér | shared-memory Krok 5 + teams Krok 2 | ~1,5 dne + vyhodnocení | 5 |

Fáze 0–3 jsou **~2 dny** a uzavírají graf. Fáze 0–6 jsou **~6 dní** a dají paměť, která patří projektu a čte ji každý provider. Fáze 7 je ohraničený experiment, ne závislost.
