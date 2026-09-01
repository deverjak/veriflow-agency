# Grafová vrstva — výměnitelnost a kroky 0–4

**Datum:** 2026-09-01
**Navazuje na:** [`../implementation-plan-v0.md`](../implementation-plan-v0.md) §3.1
**Řeší:** vrstvu abstrakce nad `code-review-graph`, aby šel v budoucnu vyměnit za GitNexus, Graphify nebo cokoli dalšího — a aby se cestou opravilo to, co je křehké už dnes.
**Součástí je** návrh na OKF pro sdílenou paměť agentů (§5) — samostatná věc, sekvencovaná za grafem.

---

## 1. Proč

Dva nezávislé důvody. **Ten první platí, i kdyby k výměně nikdy nedošlo.**

### 1.1 Křehkost dnes

Na třech místech se parsuje lidský text, i když tentýž příkaz umí strojový výstup:

| místo | co dělá | co je k dispozici |
|---|---|---|
| `runs.py:545` | `detect-changes --brief` → Rich panel, z něj regexy na `runs.py:549-557` | **bez `--brief` vrací plný JSON** (nápověda doslova: *„Show the risk summary + Token Savings panel instead of the full JSON"*) |
| `runs.py:566` | `dead-code` → text | `dead-code --json` |
| `proc.py:220` | `status` → uloží se `raw` text | `status --json` |

Až CRG přeformuluje větu v panelu, `riskScore` a `untestedFunctions` tiše zmizí z run recordu. Nic nespadne, nic nekřikne — jen se do `run.v1` začnou zapisovat prázdná pole. Komentář na `runs.py:549` už jednu takovou past dokumentuje (`(\d+)\s+changed` chytne „10 changed file(s)" dřív než „23 changed function(s)").

### 1.2 Výměna zítra

Volání grafu je dnes rozeseté v pěti modulech a ve dvou SKILL.md. Není to *hodně* míst, ale nejsou nikde vyjmenovaná, takže výměna začíná grepem, ne kontraktem.

**Python plocha:**

- `proc.py:199-222` — `CRG` konstanta, `crg()`, `crg_version()`, `crg_status()`
- `runs.py:451-478` — `prepare_graph()`: kopie `graph.db` do worktree + `update`
- `runs.py:545,560,566` — `detect-changes`, `impact`, `dead-code`
- `anchor.py:95-99` — `crg search` + regex nad stdout; vrstva 3 kotvy
- `cli.py:385-386,396-400` — doctor
- `cli.py:672-679` — `policy["graph"]` větev v běhu
- `config.py:83` — natvrdo `.code-review-graph/graph.db`
- `packs.py:35` — `"graph": True` jako boolean v běhové politice

**Prompt plocha** (větší a horší, protože ji žádná Python fasáda nezakryje):

- `packs/review-graph/skill/SKILL.md:51,63-64,128`
- `packs/qa/skill/SKILL.md:174-175`

---

## 2. Co bylo ověřeno (1. 9. 2026)

Nápovědy CRG spuštěny lokálně; GitNexus a Graphify z veřejné dokumentace.

| otázka, kterou jádro klade | code-review-graph | GitNexus | Graphify |
|---|---|---|---|
| stav / čerstvost indexu | `status --json` | `status` | `graph_stats` / `graph_status` |
| přírůstková aktualizace | `update` | `analyze --watch` | ✗ (rebuild) |
| co se změnilo proti base | `detect-changes --base` | `detect-changes` | `get_pr_impact` |
| blast radius | `impact --files --depth` | `impact` | `graph_impact` |
| symbol → `file:line` | `search` | `context` / `query` | `get_node` / `explain` |
| volající / volaní | `query callers_of\|callees_of` | `context` (sloučeně) | `get_neighbors` |
| **mrtvý kód** | `dead-code --json` | **✗** | **✗** |
| **testy pro symbol** | `query tests_for` | **✗** | **✗** |

### Tři zjištění, která mění návrh

**A. Dvě z osmi otázek jsou CRG-only — a každá nese celou dimenzi packu.**
`reuse` stojí na `dead-code` (`runs.py:566`), `tests` na `query tests_for` (`SKILL.md:51`). Po výměně za GitNexus nebo Graphify zhasnou 2 z 5 dimenzí v `packs/review-graph/pack.json`. Není to důvod šev nedělat — je to důvod postavit ho jako **explicitní degradaci se schopnostmi**, ne jako „všechno všude stejně".

**B. Trik „zkopíruj `graph.db` do worktree a doindexuj" (`runs.py:451-478`) je čistě CRG.**
GitNexus drží index v `.gitnexus/` v embedded graph DB (jiný layout, ale kopírovatelné). Graphify vyrábí `graphify-out/graph.json` jako artefakt bez doložené inkrementální aktualizace. `prepare_graph` proto nemůže zůstat sdílenou implementací — je to strategie driveru.

**C. Driver musí být modul, ne řádek konfigurace.**
První úvaha byla udělat to po vzoru [`providers.py`](../../packages/core/src/agency/providers.py) — tabulka dat, ne kód. **Neobstojí.** Providery mají všichni stejný tvar (binárka + flag na model + prompt). Grafové nástroje ne: GitNexus i Graphify mají doložený jen MCP jako strojové rozhraní, JSON na CLI nikde nedokládají. Jeden driver bude subprocess wrapper, druhý MCP klient. To se do řádku dat nevejde.

---

## 3. Kroky

### Krok 0 — JSON místo regexů (~2 h, žádná abstrakce)

Čistý zisk. Dělá se **první**, protože z něj vzniknou skutečné normalizované tvary — kontrakt v Kroku 1 se pak píše nad daty, ne nad odhadem.

1. `runs.py:545` — zahodit `--brief`, číst plný JSON. Smazat regexový blok `runs.py:549-557` i lokální `import re as _re`.
2. `runs.py:566` — přidat `--json` k `dead-code`, výstup ukládat jako `.json` místo `.txt`.
3. `proc.py:215-222` — `crg_status` volat `status --json`, místo `raw` ukládat rozparsovaný dict.
4. Zkontrolovat, že klíče, které z toho lezou (`changedFiles`, `changedFunctions`, `affectedFlows`, `untestedFunctions`, `riskScore`), pořád sedí na `run.v1` a na `cli.py:692`.

> **Kontrola hotovosti:** jeden běh na projektu s postaveným grafem, `run.v1` má vyplněné všechny grafové statistiky, a v `runs.py` už není žádný `re.search` nad výstupem CRG.

### Krok 1 — `graph.py`: kontrakt ve dvou úrovních (~1 den)

Nový modul `packages/core/src/agency/graph.py`. Verby jsou definované **otázkami, které recenze klade**, ne příkazy CRG — obtisk současného CLI vypadá jako abstrakce a při druhé implementaci praskne.

```
core      state()          stav a čerstvost indexu
          refresh(scope)   doindexuj pro tenhle běh
          changes(base)    {files, functions, flows, testGaps, riskScore}
          impact(files, depth)
          locate(symbol)   → file:line
          neighbors(symbol, direction)

extended  unreferenced(path_glob)
          tests_for(symbol)
```

Pravidla:

- Každý verb vrací **typovaný dict**. Parsing vlastní modul, volající nikdy nevidí stdout.
- `capabilities()` vrací seznam podporovaných verbů. **Volající se ptá předem**, ne až podle výjimky.
- Chybějící schopnost není chyba. Ten reflex v projektu už je (`config.template.json`: *„Without project rules 4 of 5 dimensions run — that is a legitimate outcome, not a failure"*).
- `graph.py` v tuhle chvíli **je** CRG driver. Žádné `drivers/`, žádný registr — viz Krok 3.

Přepojit na něj: `runs.py:451,545,560,566`, `anchor.py:95`, `cli.py:396-400`, `config.py:83`.

> **`config.py:83` je jediná věc z Kroku 3, kterou si vezmi hned:** `hasGraph` se přestane ptát natvrdo na `.code-review-graph/graph.db` a zeptá se `graph.state()`. Jedna funkce, ne systém driverů.

### Krok 2 — `agency graph <verb>` (~půl dne)

Jedny dveře pro jádro i pro agenta. `--json` jako výchozí výstup.

```
agency graph state
agency graph refresh
agency graph changes --base <sha>
agency graph impact --files a.py b.py --depth 2
agency graph locate <symbol>
agency graph neighbors <symbol> [--direction in|out]
agency graph unreferenced --path <glob>
agency graph tests-for <symbol>
agency graph capabilities
```

**Tenhle krok není o výměně.** Je o tom, že půlka použití grafu žije v promptu (`SKILL.md`) a Python fasáda ji nepokryje. Vedlejší efekt je ale ten důležitý: **šev se pak testuje každým během**, ne až teoreticky v den výměny.

Zároveň `packs.py:35` — běhová politika přestává být boolean:

```json
"graph": {
  "required": ["changes", "impact"],
  "optional": ["unreferenced", "tests-for"]
}
```

Doctor (`cli.py:396-400`) pak umí říct *„review-graph chce `tests-for`, tvůj driver ho neumí — dimenze `tests` poběží bez grafového signálu"* místo aby to tiše selhalo uprostřed běhu.

### Krok 3 — driver a workspace strategie (~půl dne, **odložit**)

Dělá se **až ve chvíli, kdy druhý nástroj fyzicky přibývá.** Do té doby je to mrtvý kód.

- `graph/drivers/crg.py`, volba přes `graph.driver` v `.agency/review-graph.json`
- `prepare_graph` (`runs.py:451`) se stěhuje do driveru a deklaruje strategii:
  `copy-db` (CRG) · `reindex` (GitNexus) · `rebuild` (Graphify)
- registr driverů obdobou `providers.py`, ale s modulem místo řádku dat — viz zjištění **C**

> Rozdělovat `graph.py` do `drivers/` má smysl v den, kdy vzniká druhý soubor. Ne dřív.

### Krok 4 — prompt plocha a záznam (~2 h)

1. `packs/review-graph/skill/SKILL.md:63-64,128` a `packs/qa/skill/SKILL.md:174-175` → `agency graph locate|neighbors|tests-for` místo přímého `code-review-graph`.
2. Běh zapíše `RUN_DIR/evidence/graph-capabilities.json`. SKILL.md dostane pravidlo:

   > **Co driver neumí, se nedokládá.** Dimenze bez schopnosti se přeskočí a zapíše se to — nedohaduje se.

3. `schemas/run.v1.json:152` — ke `graph.tool` přidat `driver` (id) a `capabilities` (seznam).

   Bez toho po výměně **nepoznáš, jestli nálezů ubylo kvůli horšímu nástroji, nebo jen proto, že zmizel `dead-code`.** To je jediná věc, kvůli které se dá výměna vůbec vyhodnotit.

4. `schemas/finding.v1.json:90,95` — popisy `evidence.kind` a `evidence.source` přestanou jmenovat `code-review-graph` a budou mluvit o „grafovém driveru".

---

## 4. Co se u grafu vědomě nedělá

**MCP jako hlavní šev.** Všechny tři nástroje MCP server mají (CRG `serve`, GitNexus `mcp`, Graphify `python -m graphify.serve`) a je to lákavé. Ale evidence, která končí ve `finding.v1` jako `evidence.source` (`schemas/finding.v1.json:95`), musí být **deterministická a zaznamenatelná** — volná explorace přes MCP tohle nesplní. Po Kroku 4 se MCP může připojit **navíc** pro agentovo volné hledání; doložené nálezy ale jdou přes `agency graph`.

**Kanonický formát grafu.** Vyexportovat všechny nástroje do jednoho interchange formátu a dotazovat se sám. Ne: normalizuje se tvar grafu (uzly, hrany), ale to, co se při výměně rozbije, jsou **odvozené analýzy** — „které funkce nemají test reference" není hrana, je to dotaz nad grafem. Navíc by to znamenalo postavit vlastní dotazovací engine, což [`implementation-plan-v0.md`](../implementation-plan-v0.md) §3.1 zakazuje.

**Přebírat Graphify `list_prs` / `get_pr_impact` / `triage_prs`.** Triage frontu má Agency vlastní a lepší (`agency triage`, `dedup.py`).

**Emitovat OKF z grafu.** CRG i GitNexus mají `wiki` (markdown z community struktury). Kdyby to někdy vydávaly jako OKF bundle, je to jejich práce — nestav to za ně. OKF v Agency patří jinam, viz §5.

---

## 5. OKF pro sdílenou paměť agentů

**Co OKF je:** otevřená specifikace Google Cloudu (v0.1 12. 6. 2026, v0.2 25. 7. 2026) — adresář markdown souborů s YAML frontmatterem, křížově prolinkovaných. Povinné je jediné pole `type`. Konzument nesmí bundle odmítnout kvůli neznámému `type`, neznámým klíčům ani rozbitým odkazům. Spec výslovně říká, že předepisovat storage, serving nebo **dotazovací infrastrukturu je non-goal**.

**Proto se nehodí na §3.** Grafový šev řeší živý dotaz nad čerstvým indexem („blast radius těchhle 40 souborů na téhle hlavičce PR"). OKF je bundle, který někdo napsal, ne engine, kterého se ptáš. Nemá verby.

**Ale na sdílenou paměť sedí přesně.** Ta v projektu už existuje jako pojem — `known_memory()` (`runs.py:479-530`) to má v docstringu:

> *„This is the shared memory. The roster allows several workers over one pack; if each of them remembered only its own runs, the second provider would dutifully repeat everything the first one settled an hour ago."*

### 5.1 Co je na dnešní paměti špatně

`known_memory()` vyrábí `known-findings.json` (strop 300 položek, `runs.py:527`) a `known-specs.json` (strop 200), regenerované z `load_runs()` do **každého** RUN_DIR znovu.

Jádro problému: **paměť dneska není věc, je to projekce do běhu.** Nikdo ji nevlastní, existuje jen jako vedlejší produkt startu běhu, a mimo běh k ní nikdo nemá přístup.

| dnes | s OKF | proč je to lepší |
|---|---|---|
| ploché pole, strop `known[:300]` | adresář konceptů s `index.md` | **Strop tiše zapomíná.** Po nějakém počtu běhů se paměť ořízne a nikde se to nezaznamená. Bundle se prochází po odkazech — agent si vezme, co potřebuje, místo aby dostal 300 položek naráz. |
| kopie paměti v každém RUN_DIR | **jeden bundle** v `.agency/knowledge/` | N běhů = N kopií téhož. Bundle je jedno místo, RUN_DIR na něj odkazuje. |
| `decision: "rejected"` + `reason` jako volný text | `verified: [{by, at}]` a tiery *unverified → machine-confirmed → human-reviewed* | Dnes se ztrácí **kdo a kdy** to rozhodl — a hlavně že to potvrdili **dva nezávisle**. To je přesně signál, který by `dedup.py` mohl vážit, a nemá ho. |
| `hire`, `pack`, `provider` jako holé stringy (`runs.py:511-514`) | `generated: {by, at}` + `sources[]` s `last_modified` | Autora máš, ale ne čas vzniku ani stáří podkladu. |
| stáří nálezu se dopočítává za běhu přes `anchor.drift()` | `stale_after`, `status: deprecated` | Nález, jehož kód už neexistuje, si to **nese v sobě**; dnes se to musí pokaždé přepočítat. |
| vazby mezi nálezy počítá heuristika v `dedup.py` | markdown odkazy `/findings/<id>.md` | Duplicita, follow-up a „tohle je regrese tamtoho" jsou **hrany**, ne dohad. |
| čitelné jen pro běh, který si to vygeneroval | adresář markdownu v repu | Agent otevřený v projektu **bez** Agency běhu (prostý Claude Code, kolega bez extension) dnes nemá k paměti přístup vůbec. |

### 5.2 Proč zrovna OKF a ne vlastní formát

Protože **roster už dneska míchá runtimy, které Agency neovládá.** `providers.py` má claude a codex zabudované a `agency providers add <cokoli>` přidá další. Každý z nich je jiný agent s jiným kontextovým oknem a jiným způsobem čtení souborů.

Formát, který takovou skupinu obslouží, musí být čitelný **bez nástroje** — a to je přesně teze OKF: adresář markdownu, žádný SDK, žádný registr schémat, žádný účet. Vlastní formát by musel dojít ke stejnému závěru a navíc si ho obhájit.

Druhý důvod je tvrdší: **v0.2 přidalo `provenance`, `trust`, `freshness`, `lifecycle` a `attestation`.** To je čtyřpětinový překryv s tím, co ledger nálezů potřebuje, a nemuselo se to vymýšlet.

### 5.3 Jak by koncept vypadal

```markdown
---
type: Finding
title: "Sink prCommentu spolkne chybu a běh hlásí úspěch"
description: "Export do PR komentáře selže tiše, run record zůstane ok."
resource: agency://veriflow-agency/findings/f_2f9c1a
tags: [dimension/errors, severity/high, pack/review-graph]
generated:
  by: review-graph@codex
  at: 2026-08-31T21:44:00Z
verified:
  - by: review-graph@claude      # jiný model to potvrdil nezávisle
    at: 2026-08-31T22:10:00Z
  - by: kuba                     # člověk to potvrdil
    at: 2026-09-01T09:02:00Z
status: stable
stale_after: 2026-12-01T00:00:00Z
sources:
  - id: g1
    resource: "agency graph impact --files packages/core/src/agency/export.py --depth 2"
    last_modified: 2026-08-31T21:40:00Z
---

Kotva: [`export.py:118`](/code/export.md) · duplicitní s [`f_0a71b2`](/findings/f_0a71b2.md)
```

Ten `verified` blok je celá pointa. **Dnes se tři různé věci — „codex to našel", „claude to nezávisle potvrdil", „člověk to schválil" — slijí do jednoho stringu `decision`.** Přitom rozdíl mezi „jeden model si to myslí" a „dva modely a člověk se shodli" je ta nejcennější informace, kterou může nový běh dostat na vstupu.

Navrhovaný layout:

```
.agency/knowledge/
  index.md              přehled, generovaný
  log.md                chronologie rozhodnutí
  findings/<id>.md      nálezy napříč běhy, packy a specialisty
  specs/<id>.md         reprodukce (dnes known-specs.json)
  rules/<id>.md         projektová pravidla — viz 5.4
```

### 5.4 Vedlejší kandidát: projektová pravidla

Dnes jsou `review.rules` a `review.docMap` v `config.template.json` **ukazatele na sekci** cizího markdownu (`CLAUDE.md#rules-that-will-bite-you`). Bez nich dimenze `repo-rules` (`packs/review-graph/pack.json`) prostě neběží.

Jako OKF koncept (`type: Rule`, `status`, `stale_after`, `verified`) dostane dimenze **strukturovaný vstup místo textového ukazatele** a doctor umí říct „5 pravidel, 1 po expiraci". Je to výrazně menší kus než §5.1 — dobrý první ochutnávkový krok.

### 5.5 Sekvencování a rizika

**Spouštěč už fakticky nastal.** Roster s heterogenními providery je přesně ta situace, kvůli které přenositelný formát paměti dává smysl. Není to „až někdy pro externí čtenáře".

**Přesto to jde až za Krok 2**, a to z jednoho důvodu: je to ortogonální práce a míchat ji do jedné dávky s grafem znamená, že se nedodělá ani jedno.

Rizika, se kterými do toho jít vědomě:

- **OKF je v0.2, tři měsíce staré a samo se označuje za nehotové** („a starting point, not a finished standard"). Verze 0.3 může pole přejmenovat.
- **Migrace není zadarmo:** `dedup.py` dnes počítá nad plochým polem; nad bundlem se počítá jinak.
- **Pravda zůstává v `.agency/runs/`.** Bundle je odvozený, přestavitelný index paměti — stejné pravidlo, jaké už platí pro `agency.db` (viz `implementation-plan-v0.md` §2). Kdyby se bundle stal zdrojem pravdy, jeden špatný přepis maže historii rozhodnutí.

---

## 6. Souhrn rozsahu

| krok | rozsah | kdy |
|---|---|---|
| 0 — JSON místo regexů | ~2 h | hned, nezávisle na všem ostatním |
| 1 — `graph.py` + `capabilities()` | ~1 den | po 0 |
| 2 — `agency graph <verb>` + politika packu | ~půl dne | po 1 |
| 4 — SKILL.md, `graph-capabilities.json`, `run.v1` | ~2 h | po 2 |
| 3 — `drivers/`, workspace strategie | ~půl dne | **až přibývá druhý grafový nástroj** |
| 5 — OKF bundle pro sdílenou paměť | neodhadnuto | po Kroku 2; začít §5.4 (pravidla), pak §5.1 (nálezy) |

Kroky 0 + 1 + 2 + 4 jsou **den a půl** a pokrývají obě plochy — Python i prompt.
