# Outputs — Agency přestane předpokládat, že každý výstup je nález

**Datum:** 2026-09-06
**Navazuje na:** [`agency-v1.md`](agency-v1.md) (pack je skill v projektu, žádná konfigurace), [`harness.md`](harness.md) (provenience tool callů, brána, metriky, revize packu), [`findings-ownership.md`](findings-ownership.md) (board je stav, lokál je brána a stopa), [`teams.md`](teams.md) (řetěz), [`shared-memory.md`](shared-memory.md) (paměť patří projektu)
**Řeší:** jádro dnes umí evidovat jediný druh výstupu — nález s kotvou na soubor a řádek. PO a CEO produkují rozhodnutí, odpovědi, sázky a drafty, a **oba už jádro kvůli tomu obcházejí**. Plán zobecňuje mechanismy, které v jádru fungují (brána, dedup, sinky, paměť, metriky), tak aby přestaly předpokládat code-review nález — a nedělá z Agency univerzální platformu.
**Stav k 6. 9. 2026:** Kroky 1–3 hotové a commitnuté (testy 436 zelených). Další na řadě: Krok 4 — svislý řez `bet`, který ověří, jestli Kroky 1–3 sedí.

**Nedělá:** nový generický agent framework. Žádný plugin systém metrik, žádný registr typů, žádná doménová znalost v jádru. Přibývají přesně dvě abstrakce — `TypePolicy` a `Run.scope`.

---

## 0. Diagnóza — čím je to doložené

### 0.1 Dva packy jádro obcházejí, každý na jiné ose

[`packs/po/SKILL.md:21`](../../packs/po/SKILL.md) to říká doslova: *„Findings still go to the board through the core, decisions do not."* Hlavní produkt product ownera — rozhodnutí s pěti dispozicemi `BUILD-NOW` / `FIX-REMOVE-NOW` / `VALIDATE-CHEAPLY` / `DEFER-WITH-TRIGGER` / `REJECT` — si pack posílá sám přes `backlog.py comment|decide|promote`. Jádro o něm neví, nededuplikuje ho, nepočítá z něj metriku a nedostane k němu zpětnou vazbu.

CEO obchází jádro na dvou osách. Výstupní: [`packs/ceo/SKILL.md`](../../packs/ceo/SKILL.md) má čtyři produkty jednoho běhu — answer, drafts, registers, findings — a jádro eviduje jediný z nich. Paměťovou: registry (`strategy.md`, `competitors.md`, `stakeholders.md`, `opportunities.md`, `decisions.md`) si pack zapisuje přímo do `.agency/knowledge/pages/ceo/`, včetně `decisions.md`, což je fakticky feedback log v markdownové tabulce, kterou podepisuje zakladatel.

A tam, kde CEO jádro neobchází, platí za to deformací: [`packs/ceo/SKILL.md:229`](../../packs/ceo/SKILL.md) kotví strategický nález na `footer.tsx` řádky 1–12, protože `anchor` je v `finding.v1` povinný.

### 0.2 Brána stojí na kotvě, ne na evidenci

[`ingest.gate`](../../packages/core/src/agency/ingest.py) (řádek 208) má šest důvodů k zahození ([`GATE_REASONS`](../../packages/core/src/agency/ingest.py), řádek 32). Ze čtyř netriviálních stojí **dva přímo na kotvě** — `phantom-file` a `phantom-line` přes [`_exists_at_commit`](../../packages/core/src/agency/ingest.py) (169).

Evidence sama má dnes tvar `{kind, detail, source}`, kde `detail` i `source` jsou volný text a `kind` je jeden ze šesti řetězců. **Žádný locator.** Jediné, co se z ní strojově ověřuje, je [`unproven`](../../packages/core/src/agency/ingest.py) (99): když `source` začíná na jeden z `COMMAND_PREFIXES`, porovná se hlavička příkazu proti `tool-calls.jsonl`. Kontrola `weak-evidence` ověřuje jen *druh* důkazu, nikdy jeho obsah.

**Důsledek pro pořadí prací:** kdyby se kotva uvolnila dřív, než evidence dostane locatory, brána spadne ze dvou reálných kontrol na nulu — a to zrovna u výstupů CEO, které kotvu stejně nemají jak poctivě naplnit.

### 0.3 Živá chyba: web se do provenience nezapisuje

[`runs.record_tool_call`](../../packages/core/src/agency/runs.py) (420) zahodí každé volání, které nemá `tool_input.command`:

```python
command = ((payload.get("tool_input") or {}).get("command")
           if isinstance(payload.get("tool_input"), dict) else None)
if not command:
    return None          # runs.py:435
```

`WebFetch` a `WebSearch` `command` nemají — mají `url` a `query`. Do `tool-calls.jsonl` se tedy nezapíšou vůbec. CEO pack má přitom v popisu *„Reads the web this run; a claim it cannot cite is not written"* a `providers.py:261` o tom rozdílu ví (*„its work on the web needs a TOOL, not a command"*) — jen se to nepromítlo do záznamu. **Disciplína, na které CEO celý stojí, je dnes jediná, která nejde ověřit.**

### 0.4 A jedna věc, která pro PO a CEO už dnes nefunguje

[`knowledge.here`](../../packages/core/src/agency/knowledge.py) (305) filtruje známé nálezy podle `impacted_files` a `impacted_nodes` z `evidence/impact.json`. Ten vzniká z grafu — a `po` i `ceo` mají v manifestu `"graph": false`. `known-here.json` je pro oba packy mrtvý kód. Generalizací o nic nepřijdou; naopak je to jediná cesta, jak jim kontextovou paměť vůbec dát.

---

## 1. Cílový model

### 1.1 Tok

```
Pack            deklaruje politiku svých output typů
  ↓
Run             má scope (v témže slovníku jako subject)
  ↓
Output          id, type, title, body, subject, evidence, data, score?
  ↓
Actions         co se kvůli outputu skutečně změnilo ve světě
  ↓
Feedback        událost se zdrojem, polaritou a lifecyclem
  ↓
Memory          jen závěry, které mají změnit budoucí chování
```

Formulace, o kterou jde:

> **Agency eviduje outputy specialisty. Nález je jeden konkrétní druh outputu.**

### 1.2 Obálka

```json
{
  "id": "01K…",
  "runId": "01K…",
  "pack": "ceo",
  "type": "bet",
  "title": "Distribuce přes regionální instituce",
  "body": "…",
  "subject": { "kind": "bet", "ref": "regional-distribution" },
  "evidence": [ { "kind": "web_snapshot", "locator": {…}, "detail": "…" } ],
  "data":     { "…": "pack-specific" },
  "actions":  [],
  "score":    91
}
```

`title` a `body` zůstávají nahoře **kvůli dedupu a paměti**, ne kvůli čitelnosti: [`dedup.claim`](../../packages/core/src/agency/dedup.py) (64) počítá podpis tvrzení z `body` a nikdy z titulku, a [`knowledge.do_not_report`](../../packages/core/src/agency/knowledge.py) (70) staví briefing z titulků. Obálka `{id, type, data}` by obojí zabila.

`data` patří packu. Jádro do něj nesahá.

### 1.3 `TypePolicy` — první ze dvou nových abstrakcí

Typ není štítek. Je to záznam o tom, **jak se s outputem má mechanicky zacházet**. Pack ho deklaruje v `pack.json`:

```json
"outputs": {
  "bet": {
    "cardinality": "many",
    "dedup": true,
    "evidence": { "required": ["document", "web_snapshot"], "min": 1 },
    "actions": "none",
    "memory": "proposes",
    "feedback": {
      "selection": {
        "metric": "selection_rate",
        "kinds": { "selected": "positive", "rejected": "negative" }
      },
      "outcome": {
        "metric": "success_rate",
        "requires": "selection.selected",
        "kinds": { "successful": "positive", "failed": "negative",
                   "abandoned": "neutral" }
      }
    }
  },
  "answer": {
    "cardinality": "one", "dedup": false, "memory": "never",
    "evidence": { "required": ["document"], "min": 1 }, "feedback": {}
  }
}
```

Jádro z toho zná: *dedupovat?*, *jaká evidence je povinná*, *jaký feedback existuje, jakou má polaritu a co je terminální*, *smí vzniknout akce*, *smí z toho vzniknout paměť*, *kolik jich smí za běh být*. Nezná `BUILD-NOW`, `bet`, `distribution` ani `stakeholder`. To je doména packu.

**Feedback je seskupený po lifecyclech, ne plochý.** Sázka má dva: výběr a výsledek. Plochá mapa polarity by [`metrics`](../../packages/core/src/agency/metrics.py) (94) donutila spočítat `(selected + successful) / (selected + rejected + successful + failed)`, což není ani selection rate, ani success rate. `requires` drží nevybrané sázky mimo jmenovatel outcome — přesně to pravidlo, které `metrics.py:45` už jednou vyslovil pro nerozhodnuté nálezy.

### 1.4 `Run.scope` — druhá nová abstrakce

`subject` sám nestačí. Kontextová paměť je průnik dvou množin:

```
relevantní paměť = outputs.subject ∩ run.scope
```

```json
"scope": [
  { "kind": "bet", "ref": "regional-distribution" },
  { "kind": "board_item", "ref": "255" },
  { "kind": "file", "ref": "src/foo.ts" }
]
```

To je zobecnění [`knowledge.here`](../../packages/core/src/agency/knowledge.py) (305) — dnes napevno soubory a symboly z grafu — na jeden mechanismus, který obslouží review i PO i CEO.

Dvě omezení, která z toho plynou a která rozhodují o použitelnosti (§3.2):

* **scope musí existovat před spuštěním agenta**, protože paměť se injektuje do promptu;
* **scope je hrubý stálý rozsah, ne jemný seznam subjektů**. U CEO to jsou živé sázky ze `strategy.md`, ne stakeholder, kterého se rozhodne prozkoumat ve dvacáté minutě.

### 1.5 Kde je hranice

> **Jádro rozumí tomu, co se tvrdí (`title`/`body`), čeho se to týká (`subject`), čím je to doloženo (`evidence`) a jak se s tím má zacházet (`TypePolicy`). Doménovému významu nerozumí a nesmí začít.**

Architektonický test každé další featury: *potřebuje to opravdu každý pack?* Když ne, patří to do packu nebo do jeho output schématu.

---

## 2. Co v jádru je a co se s tím stane

| mechanismus | dnes | po plánu |
|---|---|---|
| `unproven` + `tool-calls.jsonl` | ověří citovaný **příkaz** | beze změny v logice, rozšíří se o non-shell tooly (Krok 1) |
| `_exists_at_commit` | `anchor.file` @ commit | `evidence.kind = code` (Krok 9) |
| `weak-evidence` (`required_evidence`) | dimenze deklaruje druhy důkazů | **předloha celého plánu** — přesune se z dimenze na typ (Krok 3) |
| `below-score` | `score < minScore` → zahodit | zaniká jako brána, `score` zůstává jako kalibrace (Krok 8) |
| `dedup` | otisk z `pack`+`dimension`+`symbol_key`+podpis `body` | `symbol_key` → `subject_key`, do otisku přibude `type` (Krok 5) |
| `knowledge.here` | soubory a symboly z grafu | `subject ∩ run.scope` (Krok 5) |
| `sinks: {prComment, githubProjectItem}` | dvě zadrátované cesty ven | `actions[]` s výsledkem (Krok 6) |
| `state` (skalár na nálezu) | jeden verdikt | projekce `fold(feedback_events, policy)` (Krok 7) |
| `knowledge/pages/<pack>/` | píše je pack sám | beze změny — jádro paměť nepíše (§3.3) |
| `do-not-report.md` | automaticky z trailu rejections | beze změny, jen zobecněná na negativní polaritu |
| `metrics.precision` | `accepted / decided` | jeden poměr **na lifecycle**, jméno dodá pack (Krok 3) |

---

## 3. Invarianty

### 3.1 Brána je offline

**Evidence se ověřuje proti tomu, co běh zaznamenal, nikdy proti živému světu.**

```
agent → WebFetch / gh / příkaz → RUN_DIR/evidence/* → output odkazuje → brána ověří odkaz
```

Ne `brána → internet`. Jinak přestane platit determinismus, [`replay`](../../packages/core/src/agency/replay.py) přestane dávat smysl a výsledek ingestu začne záviset na tom, jestli je cizí web zrovna nahoře.

### 3.2 `scope` nepíše agent

Kdyby si ho deklaroval sám, je nekontrolovatelný a paměť je tím gameable: široký scope = víc kontextu, úzký scope = vyhnutí se nepohodlným rejections. A hlavně by přišel pozdě — paměť se injektuje před během.

Scope produkuje **příprava**, doménovou znalost k tomu má **pack**: PO má `backlog.py snapshot`, CEO čte `strategy.md`, review má graf. Jádro zavolá, co pack deklaruje, a spotřebuje tvar `{kind, ref}[]`. Žádná pack-specific logika v jádru nepřibývá.

### 3.3 Jádro nepíše paměť

`memory: "proposes"` znamená **„feedback k tomuhle typu se od minulého běhu dostane do briefu"**. Stránku si přepíše pack sám — CEO to se `strategy.md` už dělá a dělá to dobře. Destilace není mechanická operace; `do-not-report.md` funguje automaticky jen proto, že rejection má triviální tvar „tohle znovu nehlásit". Žádný destilátor se nestaví.

### 3.4 Feedback má zdroj

Dvě hodnoty dnešního `state` člověk nikdy nezadá: `duplicate` píše [`dedup.mark_duplicates`](../../packages/core/src/agency/dedup.py) (152), `deferred` je pozůstatek (`runs.py:40` — *„nothing writes them any more"*). Feedback událost proto nese `source`: `core` / `human` / `chain:<pack>`. Rozlišení už existuje — [`metrics`](../../packages/core/src/agency/metrics.py) počítá rozhodnutí člena řetězu jinak než rozhodnutí člověka — jen se musí přenést, ne vymyslet.

### 3.5 Lifecycle se nevymýšlí tam, kde feedback nikdo nedodá

Viz §5. Output bez přirozeného zdroje zpětné vazby je `write-only`, ne lifecycle na papíře.

---

## 4. Kroky

Pořadí je záměrné: **žádný krok neuvolní kontrolu dřív, než existuje její náhrada**, a ověřovací svislý řez je čtvrtý, ne poslední.

### Krok 1 — provenience i pro tooly bez příkazu (~2 h) — **hotovo**

**Proč:** samostatná chyba s okamžitou hodnotou, nezávislá na zbytku plánu (§0.3).

**Co se změnilo:** [`record_tool_call`](../../packages/core/src/agency/runs.py) přestal vyžadovat `tool_input.command` a zapisuje obecnější řádek:

```json
{ "at": "…", "tool": "WebFetch", "input": { "url": "https://kickk.cz/…" } }
```

`command` je jeden druh vstupu, ne podmínka záznamu. `unproven` čte dál jen řádky s příkazem — jeho chování se v tomhle kroku **nezměnilo**, jen mu přibylo, z čeho bude číst v Kroku 2.

**Whitelist je per TOOL, ne per klíč** (`RECORDED_TOOLS` v `runs.py`): `Bash → command`, `WebFetch → url`, `WebSearch → query`. Tool, který v mapě není, řádek nevyrobí vůbec. Důvod je dvojí — `tool_input` u `Write` nese celý soubor, a záznam všeho, čeho se agent dotkl, je jiný soubor s jiným účelem. Oproti první verzi tohohle kroku **v mapě není `Grep`**: `pattern` by dnes neměl konzumenta, protože `_is_command` `grep ` mezi `COMMAND_PREFIXES` nemá a žádný evidence kind se na něj neodkazuje. Až bude, přidá se řádek do mapy.

**Zpětná kompatibilita:** řádky psané před změnou jsou ploché (`{"command": …}`). `commands_run` čte přes nové `_command_of()` **oba tvary** — committed historie běhů se nepřepisuje a její provenience musí dál platit.

**Vedlejší důsledek, který je zlepšení:** běh, který jen stahoval web a nespustil žádný příkaz, nechá soubor existovat s nulou příkazů. `commands_run` proto vrátí `[]`, ne `None` — a nález, který v takovém běhu cituje příkaz, se poprvé správně zahodí jako `unproven-source`. Dřív takový běh soubor nezanechal vůbec a kontrola se přeskočila celá; „nikdo nezapisoval" se tím přestalo plést s „zapisovalo se a žádný příkaz neběžel".

**Testy:** `test_provenance.py` — `WebFetch`/`WebSearch` vyrobí řádek s locatorem a bez `prompt`u; `Read` i `Write` nevyrobí nic; prázdný `query` nevyrobí řádek s prázdným locatorem; plochý historický řádek se dál čte; web-only běh je `toolCalls: true` a zahodí citovaný příkaz, který neběžel.

**Hotovo, když:** ~~CEO běh, který si otevřel tři stránky, má v `tool-calls.jsonl` tři řádky s URL.~~ Splněno na úrovni jednotek; přejímka nad reálným CEO během patří k Kroku 4.

---

### Krok 2 — evidence dostane locatory a ověření (~1,5 dne) — **hotovo**

**Proč:** dokud evidence nemá locator, dělá veškerou deterministickou práci kotva (§0.2). Tohle je **náhrada, kterou musí mít CEO dřív, než se kotva uvolní.**

**Co se změnilo:** položka evidence dostala `locator`, jehož tvar určuje `kind`:

```json
{ "kind": "code",         "locator": { "file": "src/foo.ts", "line": 42, "commit": "…" } }
{ "kind": "web_snapshot", "locator": { "artifact": "evidence/web/01.json", "url": "https://…" } }
{ "kind": "board_item",   "locator": { "artifact": "evidence/backlog.json", "ref": "255" } }
{ "kind": "document",     "locator": { "file": "docs/ROADMAP-2026.md", "commit": "…" } }
{ "kind": "command",      "locator": { "command": "gh issue view 255" } }
```

Ověření v bráně, všechno offline (§3.1):

| kind | ověří se | kde |
|---|---|---|
| `code`, `document` | soubor existuje na daném commitu, řádek je v rozsahu | `_exists_at_commit` |
| `command` | hlavička příkazu je v `tool-calls.jsonl` | `unproven`, rozšířený o `locator.command` |
| `web_snapshot` | artefakt v `RUN_DIR` existuje **a** URL je v `tool-calls.jsonl` tohoto běhu | `unverified` + Krok 1 |
| `board_item` | artefakt existuje a `ref` je v něm | `unverified` |

Nový důvod v `GATE_REASONS`: `unverified-evidence`. Citovaný příkaz zůstává `unproven-source` **v obou tvarech** — `locator.command` i rozpoznaný `source` řeší jedna funkce, aby pack nedostal jiný verdikt za to, že použil novější zápis, a aby se dvě populace v `gatedBy` nemíchaly.

**Tři pojistky, které to nesmí zahodit poctivé nálezy:**

1. **URL se porovnává normalizovaná** (`_norm_url`) — hook píše, co se stahovalo, agent píše, co cituje. Lomítko na konci, velikost písmen v hostiteli a fragment nesmí být verdikt; query string ano, ten stránku změnit může.
2. **`urls_fetched` vrací `None`, když nikdo nezapisoval** — stejná pojistka jako u `commands_run`. U `web_snapshot` se pak přeskočí jen polovina „bylo to otevřeno v tomhle běhu"; polovina „artefakt je v běhu" platí vždy, protože ta na hooku nestojí.
3. **Cesta k artefaktu se ověřuje dvakrát.** Pattern v schématu zastaví `/etc/passwd`, ale `evidence/../../x` mu vyhoví — chytá to až `_in_run()` přes `resolve()`. Cesta ven z `RUN_DIR` není překlep, je to běh, který se zaručuje za něco, co nevlastní.

**Migrace:** `finding.v1` se nezahodil. Evidence přijímá **obě podoby** — starou `{kind, detail, source}` i novou `{kind, locator, detail}`. Staré kindy (`graph`, `rule`, `test-gap`, `diff`, `runtime`, `doc`) locator nemají a procházejí přesně jako dřív; nové (`code`, `document`, `command`, `web_snapshot`, `board_item`) ho mají povinný přes `if/then` v schématu. Bez toho nesedí ani jeden z šesti packů hned první den: PO má vlastní přepis požadovaného tvaru na [`SKILL.md:239`](../../packs/po/SKILL.md), CEO na [`215`](../../packs/ceo/SKILL.md). Committed historie v `.agency/knowledge/` se nepřepisuje nikdy.

**Testy:** `test_gate.py`, 15 nových — pro každý kind případ, který projde, i který ne; obojí `web_snapshot` selhání (nestažené URL, neuložený artefakt); normalizace URL; běh bez hooku si podrží polovinu, kterou zkontrolovat umí; obě vrstvy ochrany cesty; a starý tvar, který dál prochází.

**Hotovo, když:** ~~nález doložený jen webem projde branou, a tentýž nález s vymyšleným URL ne.~~ Splněno.

**Co zůstalo vědomě otevřené:** `stop_errors()` — druhá šance před koncem běhu — kontroluje schéma a kotvu, ale ne locatory. Chybějící `locator` tedy agent dostane zpět (je to schéma), zatímco neuložený artefakt se dozví až brána po jeho konci. Dá se doplnit, ale patří to k tomu až po Kroku 4, kdy bude vidět, jak často to reálně nastává.

---

### Krok 3 — `TypePolicy` (~1 den) — **hotovo**

**Proč:** aby mohly vzniknout jiné typy než nález, aniž by jádro znalo jejich význam.

**Co se změnilo:** nový modul `outputs.py`, `pack.json` dostal blok `outputs` (§1.3) a nález dostal nepovinné pole `type` (`finding`, když chybí — což je každý committed nález). Jádro z politiky čte:

* `dedup` → jestli output vůbec vstupuje do [`mark_duplicates`](../../packages/core/src/agency/dedup.py)
* `evidence.required` / `min` → přebíjí `weak-evidence` navázaný na dimenzi ([`required_evidence`](../../packages/core/src/agency/ingest.py) je předloha; dimenze zůstává, když typ mlčí)
* `feedback` → slovník, polarita, lifecycly, jejich jména metrik a nepovinné `reasons`
* `actions`, `memory`, `cardinality` / `limit`

Dva nové důvody v bráně: `unknown-type` (pack píše typ, který nemá v manifestu — mlčky zdefaultovat by schovalo přesně ten rozpor) a `over-cardinality`. **Strop se kontroluje jako poslední**, po všem, co soudí výstup samotný: nepoctivý jedenáctý výstup se má zahodit jako nepoctivý, ne jako jedenáctý, jinak se rozbitý pack schová za plnou kvótu.

Metriky počítají **jeden poměr na lifecycle**, pojmenovaný packem — `byLifecycle` v `agency metrics --json`, řádek na lifecycle v lidském výpisu. Nová třída `Cycle` počítá podle **polarity**, ne podle slov: `Tally` zná `accepted`/`sent`/`rejected`, což je přesně ten předpoklad, který se odstraňuje.

**Dvě rozhodnutí, která stojí za zapsání:**

1. **`finding` žádnou druhou metriku nedostane.** `byLifecycle` pokrývá jen typy, které pack skutečně napsal (`outputs.own_types`). Precision už jméno má a druhý poměr nad týmiž rozhodnutími pod druhým jménem není měření, ale spor o to, které z nich platí.
2. **Populace se u `Cycle` liší od precision záměrně.** Precision počítá jen verdikt člena řetězu, protože člověk rozhoduje nález na boardu a lokálně to nikdo nevidí. Sázka board nemá — zakladatel ji vybírá tady, takže `human` je signál, ne šum z doby před stopou.

**Předsunuto z Kroku 5, protože na tom stojí Krok 4:** `type` je ve fingerprintu a `is_duplicate` odmítne porovnávat různé typy. Sázka a nález o téže stránce sdílejí podstatná jména a similarity vrstva by jedno složila do druhého.

**Nedělá se plugin systém.** Šest packů, ne stovky. Politika je data, ne kód. Chyby v ní hlásí `agency doctor` (`outputs.errors`) — data, na která jádro reaguje, nespadnou, ale tiše se zdefaultují.

**Testy:** nový `test_outputs.py`, 24 testů — výchozí politika beze změny, dva lifecycly, obě chyby v deklaraci, `unknown-type`, evidence per typ, strop a jeho pořadí, opt-out z dedupu, vokabulář feedbacku per typ.

**Hotovo, když:** ~~`agency metrics` ukáže u packu s dvěma lifecycly dvě pojmenované metriky a ani jedna z nich není součet toho druhého.~~ Splněno.

**Co zůstalo vědomě otevřené:** `decisions()` skládá události na **jedno** rozhodnutí na output (poslední zápis vyhrává), takže sázka označená `selected` a později `successful` se v metrikách objeví jen pod `outcome`. Číslo je tím poctivé, ale ne úplné — plný fold po lifecyclech je Krok 7 a teprve po něm dávají obě otázky současně smysl.

---

### Krok 4 — svislý řez: CEO `bet` od začátku do konce (~1 den) ← ověření Kroků 1–3

**Proč:** Kroky 5–11 jsou postavené na tom, že Kroky 1–3 sedí. Ověřit to až migrací na konci znamená osm kroků na odhad. `bet` je jediný typ, který naráz protne **všechno nové**: evidence bez kódu, `TypePolicy`, dva lifecycly, subject bez souboru a paměť jako návrh do `strategy.md`.

**Co se udělá:** CEO pack dostane `outputs.bet` a píše sázky jako outputy vedle svých nálezů. Review běží celou dobu po staré cestě — dvojí přijímání schématu z Kroku 2 to umožňuje.

**Hotovo, když:** `agency outputs --type bet` ukáže tři návrhy, `agency feedback <id> selected` jeden vybere, `agency metrics` vykáže `selection_rate 0.33`, a další CEO běh dostane ten výběr v briefu. Kdykoli tohle nejde, **vrací se to do Kroků 2–3**, ne se to obchází dál.

---

### Krok 5 — `subject` a `run.scope` (~1,5 dne)

**Co se mění:**

1. Output dostane `subject: {kind, ref}`. `ref` musí být konkrétní — `bet:regional-distribution`, nikdy `strategy`. Důvod je v dedupu: [`is_duplicate`](../../packages/core/src/agency/dedup.py) (131) odmítne porovnávat cokoliv, co nemá shodné „místo", a to je jediná pojistka proti tomu, aby se dvě různá tvrzení o téže oblasti spárovala. Hrubý subject tu pojistku vypne — a práh je 0.5 překryv při ≥4 sdílených slovech, což u dvou sázek na distribuci padne snadno.
2. `symbol_key` → `subject_key`, do [`fingerprint`](../../packages/core/src/agency/dedup.py) (97) přibude `type` (jinak se `bet` a `finding` o téže věci označí za duplicitu).
3. Běh dostane `scope` (§1.4, §3.2), vyrobený přípravou z toho, co deklaruje pack.
4. [`here`](../../packages/core/src/agency/knowledge.py) (305) přestane číst `impact.json` napřímo a začne počítat průnik `subject ∩ scope`. Pro review se výsledek **nesmí změnit** — graf naplní scope soubory a symboly.

**Testy:** `test_knowledge.py` — review scope dá tentýž výsledek jako dnes; CEO běh se scope `bet:x` dostane výstupy o `bet:x` a ne o `bet:y`. `test_gate.py` — `bet` a `finding` se stejným tělem nejsou duplicita.

**Hotovo, když:** `known-here.json` je poprvé neprázdný u packu bez grafu.

---

### Krok 6 — `actions` ze `sinks` (~0,5 dne)

**Proč:** `sinks: {prComment, githubProjectItem}` už jsou primitivní výsledky akcí, jen zadrátované na dvě cesty. Není to nový subsystém, je to zobecnění tvaru.

**Co se mění:**

```json
"actions": [ { "kind": "board_decision", "target": "41",
               "result": "success", "remoteId": "…", "at": "…" } ]
```

Pokrývá `pr_comment`, `github_project_item`, `board_decision`, `board_draft`, `issue_promotion`. Prázdné pole je legitimní stav — CEO draft vyrobí artefakt a nic neodešle.

**Rozdělení, které se drží:** *output = co specialista rozhodl nebo vytvořil; action = co se kvůli tomu skutečně změnilo.*

**Testy:** `test_decisions.py` — dnešní sink zapíše `actions[0].remoteId` a `cli.py:1628` i `knowledge.py:491` čtou z nového tvaru.

**Hotovo, když:** PO smí posílat rozhodnutí přes jádro a `agency outputs` u něj ukáže, co se na boardu doopravdy stalo.

---

### Krok 7 — feedback jako události a projekce `state` (~1,5 dne)

**Proč:** dnešní `state` je skalár, který [`metrics`](../../packages/core/src/agency/metrics.py) čte na deseti místech, [`dedup`](../../packages/core/src/agency/dedup.py) ho zapisuje a `serve.py` i `cli.py` na něm staví výpis. Seznam událostí je datová změna **plus** jedna funkce, která v seznamu kroků snadno chybí.

**Co se mění:**

```json
{ "outputId": "…", "kind": "selected", "lifecycle": "selection",
  "source": "human", "at": "…", "note": "…" }
```

a k tomu **projekce** `state = fold(events, policy)` — jedno místo, které z historie a politiky spočítá aktuální stav. Nikdo jiný historii neskládá.

CLI zůstává pro uživatele beze změny tam, kde to dává smysl: `agency accept` / `agency reject` zůstávají jako zkratky pro packy, které takový feedback mají. Obecný tvar je `agency feedback <id> <kind>`. **CLI nemusí odhalovat vnitřní generalizaci všude.**

**Testy:** `test_decisions.py` — dvě události ve dvou lifecyclech dají dva nezávislé stavy; `duplicate` od jádra se do precision nepočítá jako lidské rozhodnutí.

**Hotovo, když:** `agency findings` ukazuje totéž co dnes, ale čte to z projekce.

---

### Krok 8 — `score` přestane být branou, objem se řídí jinak (~0,5 dne)

**Co se mění:** `below-score` z brány mizí. `score` se **dál zaznamenává** — [`metrics`](../../packages/core/src/agency/metrics.py) (59) z něj počítá kalibraci a je to jediné místo, kde se pozná pack, který dává všemu 90 a má precision 0.4.

> **Score není signál pravdivosti, je to signál kalibrace. Vyšší riziko musí zvyšovat nároky na evidenci, ne číslo, které si model přidělí sám.**

**Ale:** `minScore` je dnes **jediná pojistka na objem** — cap na počet outputů v jádru nikde není. Bez náhrady může fronta narůst tak, že se míň rozhoduje, a tím klesne kvalita samotného učení. Náhrada nesmí tvrdit pravdivost: `cardinality` v `TypePolicy` jako strop na typ a běh, případně „pošli N nejlepších podle score" jako řazení, ne jako brána.

**Testy:** `test_gate.py` — nález se score 40 a dobrou evidencí projde; jedenáctý output typu se stropem 10 neprojde a je to vidět v `dropped`.

**Hotovo, když:** `agency ingest` nezahodí nic kvůli score a fronta přesto neroste přes strop.

---

### Krok 9 — uvolnit povinnou kotvu (~2 dny)

**Proč až teď:** teprve tady existuje plná náhrada (Krok 2) a je ověřená (Krok 4).

**Co se mění:** `anchor` přestává být zvláštní pole a stává se `evidence.kind = code`. Není to odstranění fieldu — `anchor` má 58 výskytů v sedmi souborech jádra a [`anchor.py`](../../packages/core/src/agency/anchor.py) je celý modul (čtyřvrstvé kotvení, drift). Ten modul **zůstává**, jen se volá nad code evidencí místo nad `anchor`. Počítej s tím jako s nejdražším krokem seznamu.

**Správná formulace hranice:**

> Ne „CEO nemusí mít kotvu", ale **„CEO nemusí mít code evidence — musí mít jinou ověřitelnou evidenci."**

**Testy:** `test_anchor_metrics.py` a `test_replay.py` beze změny chování na review nálezech.

**Hotovo, když:** review nález se chová identicky jako dnes, včetně driftu, a CEO sázka nemá `code` evidenci ani ji nepředstírá.

---

### Krok 10 — migrace PO a CEO na jádro (~1,5 dne)

**Proč:** tohle je přejímka celého plánu. Ne „umí to jádro", ale **„přestaly ho packy obcházet?"**

PO: `decision` a `ticket_draft` přes jádro, `backlog.py` zůstává jako vykonavatel akcí, ne jako obchvat. CEO: `answer` (`cardinality: one`), `bet`, `draft` — registry **zůstávají paměťové stránky** a output typem se nestávají (§0.1, §3.3).

**Hotovo, když:** v `packs/po/SKILL.md` zmizí věta *„Findings still go to the board through the core, decisions do not."* — protože přestane být pravdivá.

---

### Krok 11 — rename `finding` → `output` (~0,5 dne)

Úplně nakonec, v okamžiku, kdy to skutečně nejsou jen nálezy. Rename na začátku by vyrobil generický název nad review sémantikou — nejhorší z obou světů, a přitom by vypadal jako pokrok.

`agency findings` a `agency triage accept` zůstávají jako aliasy. Uživatel review packu klidně může dál vidět „nálezy".

---

## 5. Odkud přijde feedback

**Největší produktová otázka celého refactoru.** Bez zpětné vazby není paměť, a bez paměti nepřinese zobecnění datového modelu nic než hezčí schéma.

| output | feedback | zdroj | kategorie |
|---|---|---|---|
| review `finding` | accepted / rejected / duplicate / intentional | `agency triage`, člen řetězu `verify` | **explicit** |
| PO `decision` | upheld / overridden / reverted | stav boardu | **derived** |
| PO `ticket_draft` | promoted / dropped | stav boardu | **derived** |
| CEO `bet` (selection) | selected / rejected | zakladatel vybírá ze tří | **explicit** |
| CEO `bet` (outcome) | successful / failed / abandoned | — | **unknown** |
| CEO `draft` | sent / not-sent | — | **unknown** |
| CEO `draft` | got response | — | **unknown** |
| CEO `answer` | — | — | write-only |
| QA `bug` | confirmed / not-reproducible / fixed | triage, opakovaný běh | explicit / derived |

**explicit** — člověk ten feedback stejně přirozeně vysloví. Ideál.
**derived** — Agency ho umí vyčíst ze světa (board se pohnul, issue je v Done). Funguje, pokud existuje odpovídající sink nebo connector.
**unknown** — neexistuje přirozený zdroj. **Lifecycle se nevymýšlí.** Takový output je `write-only`, nebo má feedback jen do fáze, kam ho někdo doopravdy dodá (`proposed → selected` a dál nic).

To je jediná ochrana před frameworkem, který půl roku vypadá, že se učí. Chyba, která by se neprojevila jako pád testu, ale jako prázdná tabulka po šesti měsících.

---

## 6. Pasti

1. **Uvolnit kotvu dřív než dodat locatory** (§0.2). Brána spadne na nulu kontrol a nikdo si toho nevšimne, protože testy na review nálezy dál projdou — ty kotvu mají.
2. **Plochá feedback mapa** (§1.3). Vyrobí číslo, které vypadá jako metrika a není žádná.
3. **Hrubý `subject`** (Krok 5). Vypne pojistku v dedupu a začne slučovat různá tvrzení.
4. **Nechat `scope` psát agenta** (§3.2). Nekontrolovatelné, gameable, a stejně pozdě.
5. **Zapomenout na projekci `state`** (Krok 7). Deset míst si začne skládat historii samo.
6. **Zrušit `minScore` bez náhrady objemu** (Krok 8). Fronta naroste, rozhodne se míň, precision přestane být signál.
7. **Postavit `register` jako output type** (§0.1). Zdvojí mechanismus, který v `knowledge/pages/` funguje.
8. **Ověřovat evidenci proti živému světu** (§3.1). Zabije replay a determinismus.
9. **Past §0.3 z [`harness.md`](harness.md) znovu:** cokoliv nového v `run.json` musí zároveň do `run.v1` a do statistik, které z něj čtou. Tenhle plán tam přidává `scope` a `outputs` — obojí je nová příležitost napsat záznam neplatný proti vlastnímu schématu.

---

## 7. Přejímka

Plán je hotový, když platí všech pět:

1. **`agency outputs --type bet` funguje** a sázka nemá ani nepředstírá code evidenci.
2. **Brána zahodí sázku doloženou URL, které v tom běhu nikdo neotevřel** — a udělá to offline.
3. **`agency metrics` u CEO ukáže `selection_rate` a `success_rate` jako dvě nezávislá čísla**, ne jejich směs.
4. **Review pack se chová identicky jako před refactorem** — tytéž nálezy, týž dedup, týž drift, tytéž metriky. Když ne, není to zobecnění, ale výměna.
5. **`packs/po/SKILL.md` už neobsahuje větu o tom, že rozhodnutí jádro obchází** — protože ho neobchází.

Bod 4 je ten, na kterém to stojí. Celý smysl je, že review-graph nepřestane fungovat — jen přestane určovat datový model všech ostatních.
