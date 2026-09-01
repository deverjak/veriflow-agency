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
- **`knownFindings`/`knownSpecs` se slévaly do `run.graph`**, který má v `run.v1` zavřený seznam klíčů — každý grafový běh tedy psal neplatný záznam. Nikdo si toho nevšiml, protože `agency validate` kontroluje `finding.v1` a `run.v1` nikdo. Paměť teď bydlí v `evidence`; validaci `run.v1` doplnila Fáze 1.
- **Promptová plocha se musela posunout hned:** `packs/review-graph/skill/SKILL.md` odkazovalo na `detect-changes.txt`, `dead-code.txt` a na seznam „Untested:" z panelu, který přestal existovat. Zbytek promptové plochy zůstává na Fázi 3.

### Souběžně, na ničem nezávisle

- [ ] Hindsight harness hooky — [`shared-memory.md`](shared-memory.md) → **Krok 5**, třetí odrážka. `npx @vectorize-io/hindsight-coding-agents install claude-code` / `codex` (ten chce `codex_hooks = true`). Vyhodnocuje se samo, neblokuje nic a nic z něj neblokuje.

---

## Fáze 1 — společný základ (~1 den) — **hotovo 1. 9. 2026**

> [`shared-memory.md`](shared-memory.md) → **Krok 1** (= [`teams.md`](teams.md) Krok 1, dělá se jednou). Plná specifikace tam.

- [x] **a)** strukturovaná identita `by`: `hire:<id>` / `human` (i `human:<jméno>`); legacy `cli` a `vscode` se při čtení mapují na `human`. Tvar se validuje při zápisu, čte se normalizovaně (`agency findings`, export)
- [x] **b)** `RUN_DIR/summary.md` jako výstup běhu (~30 řádků); kontrakt v SKILL.md všech čtyř packů, `ingest` zaznamená přítomnost do `run.outputs.summary`
- [x] **c)** `knowledge.py` — `assemble` / `for_run` / `upstream`; `known_memory()` je jeho konzument, výstupní soubory beze změny

**Hotovo, když:** rozhodnutí agenta nese `hire:<id>`, běh po sobě nechává `summary.md`, a `runs.py` už paměť neskládá — jen volá `knowledge.py`. — ✅ ověřeno i přes CLI (`agency triage`, `agency ingest`), `tests/test_knowledge.py` a `tests/test_run_record.py`.

### Co plán nepředpokládal

- **Identitu skládá jádro, ne agent.** `context.json` nese hotové `by` (`hire:<id>`), takže `--by` je pro packa opis, ne úsudek. Běh bez rosteru má pracovníka taky — `pack@provider` — jinak by se v projektu bez rosteru „rozhodl specialista" nedalo odlišit od „rozhodl člověk".
- **Extension píše `human`, ne `vscode`.** Identita odpovídá na „kdo rozhodl", ne „kterými dveřmi"; člověk klikající v editoru je týž člověk, co píše do terminálu.
- **Prázdná identita se nedoplňuje na `human`.** „Nevím, kdo rozhodl" a „rozhodl člověk" jsou různá tvrzení a jen jedno z nich někdo udělal.
- **`bundle()` se nepsal.** Patří do Fází 4–6 a stub, který nic nedělá, je horší než jeho absence.
- **`agency validate` kontroluje i `run.v1`** — to je ten samostatný úkol, který si Fáze 0 zapsala. Odhalil rovnou dva další drifty: `gated-out` nebyl v enumu stavů (píše ho `ingest`, ikonu pro něj má i extension) a `project.slug` nesměl být `null` (doctor přitom repozitář bez remote podporuje). Obojí byla chyba schématu, ne kódu — opraveno tam.
- **Fixture v testech vyráběla neplatný záznam** (`target` bez `headRefOid`). Opraveno; jinak by nová validace byla testovaná proti něčemu, co skutečný běh nikdy nezapíše.

---

## Fáze 2 — grafový šev (~1,5 dne) — **hotovo 1. 9. 2026**

> [`graph-abstraction.md`](graph-abstraction.md) → **Krok 1** a **Krok 2**.

- [x] `packages/core/src/agency/graph.py`: verby `state` / `refresh` / `changes` / `impact` / `locate` / `neighbors` + extended `unreferenced` / `tests-for`; typované dicty, parsing uvnitř, `capabilities()` se ptá předem
- [x] přepojit `prepare_graph` a `collect_evidence` (`runs.py`), `anchor.py`, doctor (`cli.py`)
- [x] `config.py` — `hasGraph` přes `graph.state()` místo natvrdo `.code-review-graph/graph.db` (jediná věc z Kroku 3 vzatá hned)
- [x] `agency graph <verb>` — JSON na výstupu vždycky
- [x] `packs.py` — `graph` politika z booleanu na `{required, optional}`; doctor umí říct „pack chce `tests-for`, driver ho neumí“

**Hotovo, když:** chybějící schopnost je vidět v doctoru předem, ne až tichým selháním uprostřed běhu. — ✅ `tests/test_graph.py` (13 testů), ověřeno i proti reálnému CRG 2.3.7.

### Co plán nepředpokládal

- **`search` a `query` vracejí JSON taky.** `anchor.py` nad nimi tedy jel regexem stejně jako `detect-changes` ve Fázi 0 — jen se to v Kroku 0 nevidělo, protože ta plocha se počítala jako „graf". `locate()` teď vrací cesty relativní k repu, což je přesně tvar, na kterém kotva stojí.
- **`Answer` nese `data` i `raw`.** `data` je kontrakt (přežije výměnu driveru), `raw` je evidence (po výměně se změní a přesně proto se ukládá). Kdyby existovalo jen jedno, buď nejde vyměnit, nebo nejde doložit.
- **Doctor hlásí i nečerstvý index** — `built_at_commit` vs. `current_sha`. Z lidského panelu se to dalo jen přečíst očima; index z jiné hlavičky přitom umí nález opřít o kód, který na téhle větvi neexistuje.
- **Politika „bez grafu" je `None`, ne `False`.** Pack, který se grafu nedotkne, po driveru nechce nic — a to je jiné tvrzení než „chce, aby graf nebyl".
- **`proc.crg_status` zmizel.** Na stav grafu se ptá `graph.state()`; `proc.py` je obálka nad procesem, ne místo, kde se rozhoduje, co je čerstvý index.

---

## Fáze 3 — graf v promptu a v záznamu (~2 h) — **hotovo 1. 9. 2026**

> [`graph-abstraction.md`](graph-abstraction.md) → **Krok 4**. Dělá se před ledgerem (vazba 2 nahoře).

- [x] `packs/review-graph/skill/SKILL.md` a `packs/qa/skill/SKILL.md` → `agency graph locate|neighbors|tests-for`; `evidence.source` v příkladu nálezu taky
- [x] běh zapíše `RUN_DIR/evidence/graph-capabilities.json`; SKILL.md pravidlo *„co driver neumí, se nedokládá“* — dimenze se přeskočí a napíše se to do `exitReason`
- [x] `schemas/run.v1.json` — ke `graph.tool` přidán `driver` a `capabilities`
- [x] `schemas/finding.v1.json` — popisy `evidence.kind` / `evidence.source` už nejmenují konkrétní nástroj

**Hotovo, když:** po výměně driveru se pozná, jestli nálezů ubylo kvůli horšímu nástroji, nebo jen proto, že zmizel `dead-code`. — ✅ záznam s `driver` + `capabilities` validuje proti `run.v1`; ve `schemas/` už není jediná zmínka o `code-review-graph`.

### Co plán nepředpokládal

- **Windowsí poznámka v SKILL.md zmizela a nenahradila se.** `PYTHONIOENCODING` a normalizace absolutních cest byly obcházení toho, že se pack ptal nástroje přímo; přes `agency graph` je odpověď JSON s cestami relativními k repu, takže obojí odpadlo.
- **Pack s grafem a bez worktree kopíroval index sám na sebe.** Latentní od začátku (žádný z dnešních packů tu kombinaci nemá), na Windows tvrdá `PermissionError`. Vyšlo to najevo při ověřování záznamu; opraveno v `graph.prepare`.

---

## Fáze 4 — pravidla jako koncepty (~1 den) — **hotovo 1. 9. 2026**

> [`shared-memory.md`](shared-memory.md) → **Krok 2** (argumentace [`graph-abstraction.md`](graph-abstraction.md) §5.4).

- [x] `.agency/knowledge/rules/` — `type: Rule`, `status`, `stale_after`, `verified`, `generated`, `sources`, `tags`
- [x] dimenze `repo-rules` čte strukturovaný vstup (`evidence/known-rules.json`) **vedle** ukazatele do cizího markdownu
- [x] doctor: „2 concepts · 1 expired · 1 deprecated“ + rozbité pravidlo s číslem řádku

**Hotovo, když:** padlo první reálné rozhodnutí o tvaru frontmatteru — na nejmenším možném soustu. — ✅ `okf.py` + `tests/test_okf.py` (14 testů), ověřeno na reálném projektu (doctor i projekce do běhu).

### Co plán nepředpokládal

- **Vlastní čtečka místo PyYAML.** Frontmatter konceptu je úzká podmnožina YAML a závislost navíc by se tahala kvůli deseti řádkům. Cena je striktnost: co parser nepozná, ohlásí **s číslem řádku** a pravidlo se označí jako rozbité. Tichý špatný výklad pravidla je horší než pravidlo, které se nenačte — a rozbité pravidlo se nesmí ztratit mezi ostatními, jinak dimenze běží s tichou dírou v zadání.
- **Ukazatel `review.rules` zůstává.** Koncepty jsou vedle něj, ne místo něj: projekt, který má pravidla v `CLAUDE.md`, se nemá čím rozbít. Dimenze se pouští, když je čím ji krmit — z kteréhokoli z těch dvou zdrojů.
- **Pravidla jdou do běhu bez stropu** (na rozdíl od nálezů). Oříznuté pravidlo je díra v zadání, ne zkrácené pozadí.
- **`knownRules` musel do `MEMORY_STATS`** — jinak by skončil v `run.graph`, což je přesně ta past, kterou u `knownFindings` odhalila Fáze 0.
- **README dostal sekci s příkladem konceptu.** Formát, který zná jen kód, není formát čitelný bez nástroje.

---

## Fáze 5 — ledger nálezů (~1–2 dny) — **hotovo 1. 9. 2026**

> [`shared-memory.md`](shared-memory.md) → **Krok 3** (argumentace [`graph-abstraction.md`](graph-abstraction.md) §5.1–5.3).

- [x] `bundle()` generuje `.agency/knowledge/findings/<id>.md` + `index.md` + `log.md` (chronologie ze `summary.md`)
- [x] `verified` tiery z atribuce Fáze 1: `hire:…@codex` našel → `hire:…@claude` potvrdil → `human` přijal
- [x] zapisuje `ingest` po bráně; jde přegenerovat příkazem (`agency knowledge --rebuild`) — pravda zůstává v `.agency/runs/`

**Hotovo, když:** paměť přečte holá session v repu bez Agency i kolega v editoru — bez nástroje a bez účtu. — ✅ `tests/test_ledger.py` (15 testů), ověřeno na reálném projektu: bundle postavený z cizích běhů se celý přečte zpátky parserem, druhé přestavení nemění ani bajt.

### Co plán nepředpokládal

- **Duplicita nedostane vlastní soubor.** Plán mluvil o „dedup match napříč hiry“, ale nedořekl důsledek: rodina duplicit je **jeden** koncept a druhý pracovník je v něm jako `verified`. Dva soubory by tvrdily, že projekt našel dvakrát víc věcí, než našel — a `codex našel → claude potvrdil` by se přitom ztratilo úplně.
- **`trust` a `status` musely zůstat dvě pole.** `trust` je míra přezkoumání, `status` je stav tvrzení. Zamítnutý nález je `human-reviewed` **a** `deprecated` zároveň; jako jedno pole by jedna z těch dvou vět nešla napsat. (`trust` je z OKF v0.2 hotové, nemuselo se vymýšlet.)
- **Potvrzení musí přijít od někoho jiného.** Duplicita od téhož pracovníka není shoda dvou, je to týž pracovník podruhé — a `agency triage --by <vlastní hire>` taky ne. Bez téhle podmínky by stačilo pustit jeden pack dvakrát a tier by vyskočil.
- **K parseru musel přibýt zapisovač** (`okf.dump`) a hned si vyžádal escapování: reálný nález má v titulku `„Ponechat moji adresu"` a bez uvozování by se z generovaného konceptu stal nečitelný soubor. Bydlí schválně v témž modulu — čtení a psaní rozdělené do dvou souborů se rozejde a pozná se to až na rozbitém repu.
- **V bundlu není čas generování.** Kdyby byl, každé přegenerování by přepsalo všechno a `git diff` by přestal odpovídat na otázku, co se změnilo. Všechny časy v konceptech pocházejí z dat, ne z hodin.
- **`stale_after` se u nálezu negeneruje.** Krok 3 ho vyjmenoval, ale u odvozeného nálezu není z čeho ho poctivě spočítat. Drift kotvy umí `anchor.resolve`, jenže je to git volání **na nález** — ingest by se tím stal O(n) procesů. Koncept nese `anchor.commit` a drift zůstává otázkou na vyžádání.
- **`agency knowledge` bez `--rebuild` nic nepíše.** Otázka „je bundle v souladu s běhy?“ musí jít položit, aniž si ji nástroj po cestě sám opraví — jinak se nedá poznat, že ho někdo ručně editoval.
- **`context.json` ukazuje na bundle absolutní cestou.** Ve worktree na hlavičce PR bundle existuje taky — ve verzi z toho commitu. Relativní cesta by specialistu poslala číst starší paměť, než jakou projekt má.
- **`specs/` z layoutu §5.3 nevzniklo.** Reprodukce jsou spustitelné soubory v běhu; koncept kolem nich by přidal jen další cestu k témuž. Zůstává `known-specs.json`.

---

## Fáze 6 — knowledge pages packů (~1 den) — **hotovo 1. 9. 2026**

> [`shared-memory.md`](shared-memory.md) → **Krok 4**.

- [x] `.agency/knowledge/pages/<pack>/` — stránky jako koncepty (`type: Page`, `status`, `stale_after`, `verified`); jména stránek zůstala ta, která packy psaly už dřív
- [x] SKILL.md: na konci běhu aktualizuj svoje stránky — **závěry, ne log**; co přestalo platit, přepiš nebo `deprecated`
- [x] příprava běhu stránky packu přibalí do kontextu (`evidence/known-pages.json` + `context.json` → `pages`)
- [x] v1 jen packy s `worktree: false` (po, qa, legal); reviewer až v druhé vlně přes RUN_DIR

**Hotovo, když:** znalost packu má domov, který přežije běh, a je vidět, kdy přestala platit. — ✅ `tests/test_pages.py` (13 testů), ověřeno na reálné konfiguraci: doctor hlásí `legal 1 · qa 2 · 1 expired · 1 without frontmatter`.

### Co plán nepředpokládal

- **Znalost packu domov měla.** §1 bod 2 plánu („nemá domov") platil jen zpola: QA, PO i právník píšou `config.memory.dir` (`.agency/qa/coverage.md`, `.agency/po/decisions.md`, `.agency/legal/applicability.md`) od svého vzniku. Co scházelo, byly tři jiné věci: **tvar** (volný markdown neumí říct, že závěr přestal platit), **viditelnost** (jádro o tom adresáři nevědělo — nepřipravovalo ho do běhu, doctor ho nehlásil, bundle na něj neodkazoval) a **jedno místo** (tři packy, tři layouty téhož nápadu).
- **Jména stránek z plánu už existovala pod jinými.** `weak-areas` + `test-lore` je `coverage` + `known-regressions`, `product-decisions` + `roadmap-context` je `decisions` + `roadmap-state`, `obligations-map` je `applicability`. Zavést obojí by znamenalo dvě paměti na tutéž věc — vyhrála jména, která packy píšou a která reálné projekty mají.
- **`coverage.md` musel přestat být deník.** Kontrakt zněl „jeden řádek na sezení" — jenže chronologii běhů vede od Fáze 5 `log.md` ze `summary.md`. Dvě verze téhož znamenají, že jedna z nich bude časem lhát; `coverage.md` je teď stav pokrytí, ne historie sezení.
- **Stránka bez hlavičky není rozbitá stránka.** Fáze 4 zavedla „co parser nepozná, ohlásí" — jenže tady by to označilo za rozbitou fungující paměť, kterou packy psaly měsíce. `okf.read` dostal `plain_ok`: soubor **bez** frontmatteru je starší stránka (čte se, v přehledu je „no frontmatter"), soubor **s rozbitým** frontmatterem je chyba s číslem řádku. U pravidel shovívavost neplatí a hlídá to test — pravidlo bez hlavičky neví, jestli platí, a nález na něm stavět nelze.
- **`memory.dir` z konfigurace vyhrává nad bundlem.** Konfiguraci vlastní projekt a upgrade ji nepřepisuje, takže projekt s `.agency/qa/` ho má dál — jádro čte, kam ukazuje, a odkaz v `index.md` vede tam. Přesouvat uživateli paměť za zády kvůli hezčí cestě se nesmí; nové projekty dostanou bundle ze šablony.
- **Vyloučení recenzenta je mechanické, ne konvence.** `context.json` → `pages` je `null`, když běh vlastní worktree. Důvod není opatrnost: worktree stojí na hlavičce PR a `agency run` ho po sobě smaže, takže zapsaný závěr by zmizel. Cesta přes RUN_DIR přijde, až bude co aplikovat při `ingest`.

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
