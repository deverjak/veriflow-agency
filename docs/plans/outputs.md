# Outputs — Agency přestane předpokládat, že každý výstup je nález

**Datum:** 2026-09-06
**Navazuje na:** [`agency-v1.md`](agency-v1.md) (pack je skill v projektu, žádná konfigurace), [`harness.md`](harness.md) (provenience tool callů, brána, metriky, revize packu), [`findings-ownership.md`](findings-ownership.md) (board je stav, lokál je brána a stopa), [`teams.md`](teams.md) (řetěz), [`shared-memory.md`](shared-memory.md) (paměť patří projektu)
**Řeší:** jádro dnes umí evidovat jediný druh výstupu — nález s kotvou na soubor a řádek. PO a CEO produkují rozhodnutí, odpovědi, sázky a drafty, a **oba už jádro kvůli tomu obcházejí**. Plán zobecňuje mechanismy, které v jádru fungují (brána, dedup, sinky, paměť, metriky), tak aby přestaly předpokládat code-review nález — a nedělá z Agency univerzální platformu.
**Stav k 8. 9. 2026:** **Plán je hotový** — Kroky 1–11 commitnuté, 501 testů zelených, přejímka §7 splněná. Svislý řez `bet` prošel u Kroku 4 a **přeskládal zbytek plánu**; Krok 5 dal outputu `subject` a běhu `scope`, Krok 6 nahradil `sinks` akcemi a cestou opravil dvě místa, kde `agency ingest` nebyl idempotentní, Krok 7 zúžil fold událostí na jeden na lifecycle a oživil `requires`, Krok 8 vyndal `score` z brány a nahradil ho stropem, Krok 9 přestěhoval kotvu do `evidence.kind = code` a Krok 10 provedl přejímku: PO a CEO přestaly jádro obcházet. Živé packy v obou cizích repozitářích jsou dorovnané a `agency doctor` je v nich čistý — čeká se na první ostrý běh. Krok 11 přejmenoval příkaz na `agency outputs` (`findings` zůstává aliasem napořád). Co zbývá, je ostrý provoz — viz „Co může říct jen ostrý provoz“ níž.

**Přejímka:** [`../prejimka-outputs.md`](../prejimka-outputs.md) · **provoz:** [`../overeni-v-provozu.md`](../overeni-v-provozu.md) — pět bodů §7 s tím, kde je každý dokázaný, pět míst, kde plán neměl pravdu, a co může říct jen ostrý provoz.
**Výklad pro čtenáře:** [`../concepts.md`](../concepts.md) — šest konceptů a šest diagramů; co z tohohle plánu zbylo jako tvar, který se dá vysvětlit.

**Nedělá:** nový generický agent framework. Žádný plugin systém metrik, žádný registr typů, žádná doménová znalost v jádru. Přibývají přesně dvě abstrakce — `TypePolicy` a `Run.scope`.

---

## Pro další session — než začneš

Tahle sekce je pro agenta (nebo pro mě za měsíc), který v plánu pokračuje. Číslované sekce níž jsou plán; tohle je způsob práce, který se u Kroků 1–6 osvědčil, pasti, na které se cestou došláplo, a inventura toho, co ještě chybí.

### Kde to stojí, ověřitelně

```powershell
git log --oneline 31cbea3^..HEAD     # commity tohohle plánu, jeden na krok
pwsh -NoProfile -File scripts/test.ps1   # jádro + smoke extension; musí říct „both passed“
```

Jen jádro, když jde o rychlost: `cd packages/core; uv run --with pytest --with jsonschema python -m pytest -q`

A že sedí i to, co bydlí jinde:

```powershell
cd ..\kvesteros-platform
python .claude\skills\agency-ceo\scripts\scope.py   # tři živé sázky, ne prázdné pole
agency doctor --json                                # žádné „pack ceo scope" ani „pack ceo outputs"
```

Stav k 8. 9. 2026: **hotovo, všech jedenáct kroků**, 501 testů, živé packy dorovnané. Zbývá ostrý provoz, ne kód.

### Co dělat teď, když je plán hotový

Kód je hotový a přejímka §7 platí. **Co zbývá, není další krok — je to provoz**, a jsou to přesně ty čtyři věci ze seznamu „co může říct jen ostrý provoz" níž. Kdo tenhle plán otevře příště, ať začne tam a ne v kódu.

1. **Pusť CEO nad Kvesterosem a PO nad main-panelem.** Obojí je dorovnané a doktor je čistý; co se nikdy nespustilo, není hotové, jen otestované.
2. **První ostrý běh PO je ten důležitější**, protože poprvé posílá rozhodnutí na board přes jádro. Sleduj `actions[]` na outputu: úspěch nese packovo `kind` (`decide`, `draft`), neúspěch nese `error` a output zůstane `candidate` na další pokus.
3. **Až board odpoví, zapiš to.** `agency feedback <id> upheld|overridden|reverted` — bez toho je `upheld_rate` prázdná a §5 „derived" je pořád jen tvrzení. Totéž platí pro `selection_rate` u sázek: dokud zakladatel nevybere, není jmenovatel.
4. **Neopravuj čísla, oprav metodu.** `agency metrics --for-author <pack>` je na to postavené a od Kroku 3 zná i `byLifecycle`. Pack, který má precision 0.4, se nemá přeskórovat — má se přepsat.

### Co chybí — inventura k 8. 9. 2026

**Zbývající kroky:** žádné. Tabulka zůstává jako záznam toho, kde odhad seděl a kde ne.

| krok | odhad | co je na tom podstatné |
|---|---|---|
| ~~**7** — feedback jako události, projekce `state`~~ | ~~1,5 dne~~ · **hotovo za půl** | past 5 nenastala — fold byl jeden, jen moc hrubý. Události v plném tvaru dodal už Krok 4 |
| ~~**8** — `score` přestane být branou~~ | ~~0,5 dne~~ · **hotovo** | náhrada existovala, ale platila jen packu, který si ji vyžádal — a to byl jeden ze sedmi. Strop dostal backstop (25, změřený z `baseline.md`) a score se z brány přesunulo do řazení nad stropem |
| ~~**9** — kotva jako `evidence.kind = code`~~ | ~~2 dny~~ · **hotovo** | 58 výskytů byla špatná míra: většina je slovo „anchor" jako jméno mechanismu. Čtenářů pole bylo jedenáct a schovali se za `anchor.of()`. Drahá byla dokumentace packů, ne jádro |
| ~~**10** — migrace PO a CEO na jádro~~ | ~~1,5 dne~~ · **hotovo** | přejímka prošla, a otevřela dvě mezery, které mohl najít jen ostrý typ se sinkem: typ, který smí jednat, neměl kam zapsat, že jednal, a `agency feedback` odmítal každý typ se sinkem. Stará cesta je zavřená přes `needs`, ne přes prosbu v SKILL.md |
| ~~**11** — rename `finding` → `output`~~ | ~~0,5 dne~~ · **hotovo** | `agency outputs` hlavní, `findings` alias napořád. Data (`findings.json`, `finding.v1`, `findingId`) se nepřejmenovala — je v nich committed historie tří repozitářů. `dispatchErrors` zůstává: inventura si tu odporovala s Krokem 6 a pravdu měl Krok 6 |

**Vědomě otevřené věci, které nepatří k žádnému kroku** — každá byla rozhodnutá, ne zapomenutá:

* **`stop_errors()` nekontroluje locatory** (Krok 2) — **už jen ty artefaktové.** Krok 9 tam dostal code locatory zadarmo (kotva se kontrolovala vždycky a teď je kotvou právě code evidence), takže agent se o vymyšleném souboru dozví ještě před koncem běhu. O neuloženém `web_snapshot` pořád až od brány; odloženo dál, protože to ukáže teprve první ostrý běh CEO.
* ~~**`decisions()` drží jedno rozhodnutí na output**~~ — vyřešeno Krokem 7. `verdicts()` drží jednu odpověď **na lifecycle**; `decisions()` zůstal vedle ní schválně, protože „rozhodl o tom vůbec někdo?" je jiná otázka než „jak dopadla otázka X".
* **`by` nese to, co plán chtěl po `source`** (Krok 7). Druhé pole s touž informací by znamenalo dvě místa, která si můžou odporovat. Kdyby se `source` někdy přidával, ať je to proto, že `by` na něco nestačí — ne proto, že to plán kdysi napsal.
* **`sinks` v `finding.v1` zůstává** jako superseded (Krok 6). Nemaže se — committed historie ho má a čtenáři z něj padají zpátky. To platí i po Kroku 11.
* **`anchor` ve `finding.v1` zůstává** jako superseded (Krok 9), ze stejného důvodu a čte ho `anchor.of()` jako záložní tvar. Rozdíl proti `sinks`: tenhle tvar je pořád **správný** — jen se nemá psát nový.
* **`minScore` v manifestech živých packů** (Krok 8). Klíč nedělá nic, doctor to řekne, a smazat ho z cizích repozitářů odsud nejde. Patří ke Kroku 10 spolu se zbytkem migrace.

**Co může říct jen ostrý provoz, ne test:**

1. **První běh CEO packu nad Kvesterosem.** Jestli sázky vzniknou jako outputy se `subject`, jestli scope ze `strategy.md` sedí, a hlavně jestli brána nezahodí poctivou sázku na `unverified-evidence` — kontrola „URL bylo otevřené v tomhle běhu" je nejmladší a jediná, která stojí na hooku.
2. **`known-here.json` bude na prvním běhu prázdný, a je to správně.** V Kvesterosu není ani jedna sázka jako output (pack tam byl starý), takže průnik nemá co potkat. Naplní se od druhého běhu. Kdyby byl prázdný i potom, hledej `evidence/scope.json` a `scopeItems` — to je ta dvojice, kvůli které se ten stat počítá i v nule.
3. **Zakladatelův verdikt.** Dokud nikdo neřekne `agency feedback <id> selected|rejected`, nemá `selection_rate` jmenovatele a §5 „explicit" je zatím jen tvrzení. Celý lifecycle sázky zatím prošel testem, ne člověkem.
4. **`success_rate` nemá zdroj feedbacku vůbec** (§5, „unknown"). To není chybějící práce — je to hranice, za kterou se lifecycle **nevymýšlí** (§3.5).

**Stav přejímky (§7)** — všech pět platí; co zbývá, je ostrý běh, ne kód:

| | |
|---|---|
| 1. `--type bet` funguje, sázka code evidenci nemá ani nepředstírá | platí (test, ne ostrý běh) |
| 2. brána zahodí sázku s neotevřeným URL, offline | platí |
| 3. `selection_rate` a `success_rate` jako dvě nezávislá čísla | platí od Kroku 7 — jedna sázka může být `selected` i `successful` a počítá se do obou, a nevybraná sázka už `success_rate` neředí |
| 4. review se chová identicky jako před refactorem | platí — 488 testů, klíč dedupu u ukotvených nálezů beze změny, drift netknutý, a od Kroku 9 i přes migraci tvaru: nález řečený code evidencí má týž otisk jako týž nález s polem |
| 5. `packs/po/SKILL.md` už neobsahuje větu o obcházení jádra | platí od Kroku 10 — a starou cestu zavírá `needs`, ne prosba v textu |

### Konvence, které drží plán a kód pohromadě

**Jeden krok = jeden commit**, a v témže commitu se aktualizuje tenhle plán. Krok se v nadpisu označí `— **hotovo**`, „Co se mění" se přepíše na „Co se změnilo", a věta v „Hotovo, když" se ~~přeškrtne~~ a doplní, ne smaže — zůstane vidět, co se slibovalo.

**Když kód řekne něco jiného než plán, opraví se plán, ne se to zamlčí.** Krok 1 zúžil whitelist oproti závorce v plánu, Krok 4 předsunul tři věci z jiných kroků; obojí je v plánu napsané i s důvodem. `harness.md` má na to vlastní odstavec („Čtyři věci, které plán tvrdil a kód říkal něco jiného") a stojí to za napodobení.

**Jazyk:** plány v `docs/plans/` česky, všechno ostatní — kód, komentáře, testy, `SKILL.md`, CLI výstup — anglicky. Commit messages česky, ve stylu ostatních: co se změnilo, proč, a co se cestou ukázalo jinak.

**Testy nesou důvod, ne jen tvrzení.** Docstring testu má říct, čemu ten test brání — `test_outputs.py` je tak psaný celý a je to to, co po refaktoru zůstane čitelné.

### Pasti, na které se v Krocích 1–6 došláplo

1. **Bash tool utne příkaz kolem 8 kB.** Heredoc s delším souborem skončí `unexpected EOF`. Delší obsah psát přes Write do scratchpadu a pak `cat >> soubor`.
2. **Soubory mají CRLF.** `Read`/`Write` to řeší, `python -c` s `read_text`/`write_text` taky (universal newlines). Ruční porovnávání bajtů ne — `cat -A` to ukáže.
3. **Kotvení `Edit` uvnitř třídy.** Anchor na `@property def decided` vložil novou třídu doprostřed `Tally` a osiřelý `as_dict` se stal metodou té nové. Testy to chytly hned, ale kotvit se má na text, který je v souboru jen jednou, a u tříd radši na jejich poslední řádek.
4. **`install_pack(..., {"minScore": 0})` dá 70**, protože `int(m.get("minScore") or 70)` — nula je falsy. Test, který chce prahem neprocházet, musí dát `minScore` skutečné číslo.
5. **Dva testovací outputy se stejným tělem jsou duplicita**, správně a nečekaně. Když test potřebuje dva různé outputy, musí mít dvě různá *tvrzení*, ne dva různé titulky — otisk se počítá z `body` a nikdy z titulku.
6. **`agency doctor` a schéma jsou dvě různé vrstvy.** Pattern u `artifact` zastaví `/etc/passwd`, ale `evidence/../../x` mu vyhoví a chytá to až `resolve()`. Když se přidává kontrola cesty, patří obě.
7. **`shlex.split` sežere zpětná lomítka.** Příkaz v manifestu (`sink`, `scope`) se parsuje POSIXově, takže `C:\Python\python.exe` se rozpadne na nesmysl. Cesty v manifestu proto vždy s lomítky dopředu — a test, který potřebuje spustit interpret téhle sady, si ho musí přepsat přes `Path(sys.executable).as_posix()` a `shlex.quote`.
8. **Python přes heredoc si nezaslouží důvěru u escapů.** Zpětné lomítko cestou zmizí (řetězec, který má do souboru zapsat lomítko a konec řádku, zapíše literál `n`) a trojité uvozovky v nahrazovaném textu ukončí řetězec toho skriptu. Cokoliv s escapy nebo s docstringy psát přes Write do scratchpadu a spustit jako soubor — je to jednou navíc a nikdy to nekousne.

### Rozhodnutí, která se nesmějí tiše zvrátit

Pokud se některé z nich příště ukáže jako špatné, ať se zvrátí **nahlas** — s odstavcem v plánu, ne úpravou kódu:

| | proč |
|---|---|
| Brána nikdy nevolá ven (§3.1) | jinak dá témuž běhu dvě odpovědi ve dvou dnech a `replay` přestane být regresní test |
| `scope` nepíše agent (§3.2) | jinak je paměť gameable a stejně přijde pozdě |
| Jádro nepíše paměť (§3.3) | destilace není mechanická operace; `do-not-report` funguje jen proto, že rejection má triviální tvar |
| `anchor: none` vyžaduje `evidence.required` | „sázka potřebuje jiný druh důkazu", ne „sázka nepotřebuje důkaz" |
| `finding` nedostane druhou metriku | precision už jméno má; druhý poměr nad týmiž daty je spor, ne měření |
| Lifecycle se nevymýšlí bez zdroje feedbacku (§5) | jinak vznikne framework, který půl roku vypadá, že se učí |

### Co se odsud udělat nedá

`packs/` jsou **referenční kopie** packů, které živě bydlí v cizích repozitářích. Proto poslední testy v `test_outputs.py` čtou skutečný `packs/ceo/pack.json` a `packs/ceo/scripts/scope.py` — aby si někdo všiml, kdyby se manifest, `SKILL.md` a skript rozešly. Totéž bude platit pro PO v Kroku 10.

**Přenos sám hotový je** (7. 9. 2026): `pack.json`, `SKILL.md`, obě `references/` a nově `scripts/scope.py` jsou v `kvesteros-platform/.claude/skills/agency-ceo/`, a `strategy.md` tam má tři `Ref:` řádky — `event-supply-baseline`, `showable-product`, `legitimacy-outreach`. Nekomitovalo se: ta složka je v tom repu netrackovaná a `strategy.md` měl rozpracované změny zakladatele.

**Co odsud pořád nejde:** ostrý běh (`agency run ceo`) a zakladatelovy verdikty nad tím, co z něj vypadne. Viz „Co může říct jen ostrý provoz" výš.

---

## 0. Diagnóza — čím je to doložené

### 0.1 Dva packy jádro obcházejí, každý na jiné ose

[`packs/po/SKILL.md:21`](../../packs/po/SKILL.md) to říká doslova: *„Findings still go to the board through the core, decisions do not."* Hlavní produkt product ownera — rozhodnutí s pěti dispozicemi `BUILD-NOW` / `FIX-REMOVE-NOW` / `VALIDATE-CHEAPLY` / `DEFER-WITH-TRIGGER` / `REJECT` — si pack posílá sám přes `backlog.py comment|decide|promote`. Jádro o něm neví, nededuplikuje ho, nepočítá z něj metriku a nedostane k němu zpětnou vazbu.

CEO obchází jádro na dvou osách. Výstupní: [`packs/ceo/SKILL.md`](../../packs/ceo/SKILL.md) má čtyři produkty jednoho běhu — answer, drafts, registers, findings — a jádro eviduje jediný z nich. Paměťovou: registry (`strategy.md`, `competitors.md`, `stakeholders.md`, `opportunities.md`, `decisions.md`) si pack zapisuje přímo do `.agency/knowledge/pages/ceo/`, včetně `decisions.md`, což je fakticky feedback log v markdownové tabulce, kterou podepisuje zakladatel.

A tam, kde CEO jádro neobchází, platí za to deformací: [`packs/ceo/SKILL.md:229`](../../packs/ceo/SKILL.md) kotví strategický nález na `footer.tsx` řádky 1–12, protože `anchor` je v `finding.v1` povinný.

> **Vyřešeno Krokem 10.** Obě osy obchvatu jsou zavřené: PO píše `decision` a `ticket_draft` jako outputy a na starou cestu nemá oprávnění, CEO přidal `answer` a `draft`. Paměťová osa zůstala schválně — registry jsou stránky, ne outputy (§3.3, past 7). Deformace s `footer.tsx` zanikla už Krokem 4 politikou kotvy.

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

To je zobecnění [`knowledge.here`](../../packages/core/src/agency/knowledge.py) — dřív napevno soubory a symboly z grafu — na jeden mechanismus, který obslouží review i PO i CEO. Bydlí v `RUN_DIR/evidence/scope.json`, ne v `run.json`; proč, je u Kroku 5.

Dvě omezení, která z toho plynou a která rozhodují o použitelnosti (§3.2):

* **scope musí existovat před spuštěním agenta**, protože paměť se injektuje do promptu;
* **scope je hrubý stálý rozsah, ne jemný seznam subjektů**. U CEO to jsou živé sázky ze `strategy.md`, ne stakeholder, kterého se rozhodne prozkoumat ve dvacáté minutě.

**Slovník `subject.kind`** — dohodnutý 7. 9. 2026, než se k tomu psal kód, protože hrubý subject vypne pojistku v dedupu (§6, past 3):

| kind | ref | kdo ho vyrábí |
|---|---|---|
| `file` | POSIX cesta od kořene projektu | jádro z kotvy a z diffu |
| `symbol` | jméno symbolu tak, jak ho zná graf | jádro z kotvy a z `impact.json` |
| `bet` | slug sázky ze `strategy.md` (řádek `Ref:`) | CEO pack |
| `board_item` | číslo issue nebo položky boardu | PO pack (Krok 10) |

`kind` je slug, který jádro nikdy nevykládá — porovnává dvojice, nic víc. Nový kind si pack přidá tím, že ho začne psát; registr se nezavádí, protože by byl jediným místem, kde jádro musí vědět, co je `stakeholder`.

Co ale platí pro každý:

* **`ref` pojmenovává jednu věc.** Test zní: *můžou dva různé outputy sdílet tenhle ref a být přitom o něčem jiném?* Když ano, je hrubý. `bet:regional-distribution` ano, `strategy` ne — a `bet:1` taky ne, protože pořadí sázek se mezi běhy přečísluje.
* **Dvojice musí přežít běh.** Subject, který se příště jmenuje jinak, nespáruje nic — ani v paměti, ani v dedupu.
* **`subject` je jeden, ale míst může mít víc.** Nález o kódu má svoje místo pojmenované dvakrát — souborem a symbolem — a obojí je v kotvě. Jádro si je odvodí samo; pack je nepíše a průnik se scope počítá přes všechna jména, jinak by běh se scope `file:src/auth.ts` přestal vidět nález ukotvený na `getUser` v tomtéž souboru.

### 1.5 Kde je hranice

> **Jádro rozumí tomu, co se tvrdí (`title`/`body`), čeho se to týká (`subject`), čím je to doloženo (`evidence`) a jak se s tím má zacházet (`TypePolicy`). Doménovému významu nerozumí a nesmí začít.**

Architektonický test každé další featury: *potřebuje to opravdu každý pack?* Když ne, patří to do packu nebo do jeho output schématu.

---

## 2. Co v jádru je a co se s tím stane

| mechanismus | dnes | po plánu |
|---|---|---|
| `unproven` + `tool-calls.jsonl` | ověří citovaný **příkaz** | beze změny v logice, rozšíří se o non-shell tooly (Krok 1) |
| `_exists_at_commit` | `anchor.file` @ commit | hotovo (Krok 9) — čte `anchor.places()`, tedy code locatory i staré pole, a každý z nich |
| `weak-evidence` (`required_evidence`) | dimenze deklaruje druhy důkazů | **předloha celého plánu** — přesune se z dimenze na typ (Krok 3) |
| `below-score` | `score < minScore` → zahodit | hotovo (Krok 8) — zanikl jako brána, `score` zůstalo jako kalibrace a nově jako pořadí u stropu |
| `dedup` | otisk z `pack`+`type`+`dimension`+`subject_key`+podpis `body` | hotovo (Kroky 3 a 5) |
| `knowledge.here` | `subject ∩ run.scope` | hotovo (Krok 5) |
| `sinks: {prComment, githubProjectItem}` | `actions[]` s výsledkem, časem a jménem od packu | hotovo (Krok 6) |
| `state` (skalár na nálezu) | jeden verdikt | hotovo (Krok 7) — `state` zůstal místem v potrubí, verdikty jsou `verdicts()` |
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

### Krok 4 — svislý řez: CEO `bet` od začátku do konce (~1 den) — **hotovo**, a přeskládal plán

**Proč:** Kroky 5–11 byly postavené na tom, že Kroky 1–3 sedí. Ověřit to až migrací na konci by znamenalo osm kroků na odhad. `bet` je jediný typ, který naráz protne všechno nové.

**Co se udělalo:** `packs/ceo/pack.json` deklaruje `outputs.bet` (`anchor: none`, `evidence.required: [web_snapshot, document]`, `limit: 3`, dva lifecycly) a `SKILL.md` §2 říká, jak se sázka píše: bez kotvy, se staženou a **uloženou** stránkou jako důkazem, a se stavem, který určí zakladatel, ne pack. Review běží celou dobu po staré cestě.

**Tři věci se předsunuly, protože bez nich nebyl řez poctivý:**

1. **Jádro Kroku 9 — povinnost kotvy se přesunula ze schématu do politiky.** Dokud musela mít kotvu i sázka, ukazovala pořád na `footer.tsx` a celý řez nic nedokazoval. `anchor` proto vypadl z `required` ve `finding.v1` a rozhoduje `outputs.<type>.anchor` (`required` je default a platí pro každý nález; nález bez kotvy padá na nový důvod `missing-anchor`). Modul [`anchor.py`](../../packages/core/src/agency/anchor.py) i drift zůstávají nedotčené — jen se nespouštějí nad outputem, který kotvu nemá.
   **A pojistka, bez které by to byla díra:** `outputs.errors` odmítne politiku, která zruší kotvu a nedeklaruje `evidence.required`. Formulace platí přesně tak, jak ji plán napsal — ne „sázka nepotřebuje kotvu", ale **„sázka potřebuje jiný druh důkazu"**.
2. **Generický zápis feedbacku (z Kroku 7).** `agency triage` má dvě slovesa a obě něco *dělají* — `accept` posílá sinkem, `reject` si pamatuje. Sázka nemá kam být poslána, takže celé „co se stalo" je záznam: `runs.record_feedback` + `agency feedback <id> <kind>`. Vokabulář je packův, takže ten příkaz žádný vlastní nemá a nikdy mít nebude. `state` outputu se **záměrně nemění** — `state` je místo v pipeline, verdikt je událost, a slepení těch dvou je právě to, proč musel být každý verdikt jedním z pěti slov.
3. **Filtr `agency findings --type` (z Kroku 11).** Jeden pack teď píše víc druhů výstupu a zakladatel hledající tři sázky je nechce mezi čtyřiceti nálezy.

**A jedna chyba, kterou našel až běh, ne úvaha.** `dedup.symbol_key` padal na `file:?` — takže **každý output bez kotvy sdílel jedno místo**, a pojistka „dvě tvrzení na různých místech jsou dvě tvrzení" se obrátila v svůj opak: všechno bylo na témže místě, tedy všechno porovnatelné, a čtyři různě formulované sázky se složily do jedné. Teď je bez kotvy místo prázdné a platí jen otisk — identické tvrzení slovo od slova. Rozhoduje o tom táž nesymetrie jako u prahu podobnosti: falešná duplicita zahodí práci, zmeškaná jen prodlouží frontu.

**Co to znamená pro Krok 5:** `subject` už není jen vylepšení kontextové paměti. Je to **náhrada za místo v dedupu**, které anchorless outputy nemají — a čím víc typů bez kotvy vznikne, tím dřív ho bude potřeba. Proto je hned další na řadě.

**Hotovo, když:** ~~`agency outputs --type bet` ukáže tři návrhy…~~ Splněno v `test_outputs.py` (řez má vlastní sekci, 10 testů): sázka bez kotvy projde, sázka s nestaženou stránkou ne, nález téhož packu kotvu pořád mít musí, `selection_rate 0.5` ze dvou zodpovězených, `precision` u toho nevznikne, zamítnutá sázka dojde do `do-not-report` dalšího běhu, a čtvrtá sázka v běhu padne na packův vlastní strop. Poslední test čte **skutečný `packs/ceo/pack.json`**, protože je to referenční kopie packu z jiného repa a nic jiného v sadě by si nevšimlo, že se obě poloviny rozešly.

**Co zbývá pro ostrý provoz:** ~~přenos `pack.json` + `SKILL.md` do repa Kvesteros~~ hotovo 7. 9. Zbývá reálný běh, a ten se odsud udělat nedá.

---

### Krok 5 — `subject` a `run.scope` (~1,5 dne) — **hotovo**

**Co Krok 4 změnil na zadání:** `subject` už není jen vylepšení paměti. Output bez kotvy nemá v dedupu **žádné místo**, takže se u něj uplatnil jen otisk; `subject` je to, co mu místo vrátí. Čím víc typů bez kotvy vznikne, tím víc práce by se bez něj ztratilo ve frontě.

**Co se změnilo:**

1. Output dostal `subject: {kind, ref}` (nepovinný, slovník je v §1.4). `ref` musí být konkrétní — `bet:regional-distribution`, nikdy `strategy` a nikdy `bet:1`. Důvod je v dedupu: [`is_duplicate`](../../packages/core/src/agency/dedup.py) odmítne porovnávat cokoliv, co nemá shodné „místo", a to je jediná pojistka proti tomu, aby se dvě různá tvrzení o téže oblasti spárovala. Hrubý subject tu pojistku vypne — práh je 0.5 překryv při ≥4 sdílených slovech, což u dvou sázek na distribuci padne snadno.
2. `symbol_key` → `subject_key`. `type` v otisku už byl z Kroku 3, takže z bodu 2 zbyl jen ten přejmenovaný klíč.
3. Běh dostal `scope` (§1.4, §3.2), vyrobený přípravou. Doménovou znalost dodává pack příkazem `scope` v `pack.json` — jádro ho spustí a přečte z něj `{kind, ref}` páry, nic víc. `packs/ceo/scripts/scope.py` je první takový: přečte živé sázky ze `strategy.md`.
4. [`here`](../../packages/core/src/agency/knowledge.py) přestal číst `impact.json` napřímo a počítá průnik `subject ∩ scope`. Pro review se výsledek nezměnil — graf plní scope soubory a symboly a `subjects()` porovnává obojí.

**Tři věci, které plán tvrdil a kód říká jinak:**

1. **Pořadí v `subject_key` je *subject → symbol → soubor → nic*, ne *symbol → soubor → subject*.** Pro committed historii se ty dvě pořadí neliší ani o bit — žádný zapsaný nález `subject` nemá, takže všechny otisky sedí dál (a proto taky odvozené tvary zůstaly `sym:` a `file:`, místo aby se při té příležitosti „zobecnily" na `symbol:`; přejmenování tvaru by tiše rozbilo dedup proti historii). Liší se až u outputu, který má kotvu **i** subject — a tam má vyhrát pack: pole, které jádro ignoruje pokaždé, když existuje kotva, by se skoro nedalo napsat, a „čeho se to týká" je právě to, co kotva říct neumí.
2. **`scope` se nedostal do `run.json`.** Past §6.9 varovala, že nové pole v záznamu musí zároveň do `run.v1` — místo toho se ukázalo, že tam nepatří vůbec: záznam drží **čísla** a seznamy leží vedle něj (`files[]` je v `context.json`, ne v `target`). Scope je proto `evidence/scope.json` a v záznamu je `evidence.scopeItems`. Ořezaný scope v `run.json` by byl lež o tom, čím se paměť zúžila, a neořezaný by do záznamu, který má u PR se čtyřmi sty soubory zůstat čitelný, nepatřil.
3. **Přibyla kontrola v `agency doctor`** (a `scope` v `agency packs --json`). Není v plánu, ale je to přesně ten check, který už existuje pro `sink`, a selhání má stejný tvar a stejné ticho: manifest jmenuje skript, který tam není, každý běh přijde o zúženou paměť a nikdo se to nedozví. Doktor to říká jako varování, ne jako fatální chybu — běh bez zúžené paměti je pořád běh.

**Co k tomu musel dostat CEO pack:** sázka v `strategy.md` má nově řádek `Ref: <slug>` ([`references/method.md`](../../packs/ceo/references/method.md)) a to je její identita — totéž, co nese `subject.ref` v `findings.json`, totéž, co čte příprava. Jmenuje **obsah** sázky, ne její pořadí: `bet-1` se přečísluje v den, kdy jedna sázka umře, a všechna paměť o ní jde s tím číslem pryč. Sázka se `Status: killed` do scope nepatří — běh má dostat, co bylo rozhodnuto o sázkách, které pořád běží.

**Testy:** 13 nových, 459 celkem. `test_knowledge.py` — pack bez grafu poprvé dostane neprázdný `known-here.json`; běh se scope `bet:x` nedostane výstupy o `bet:y`; scope, který spadne, stojí paměť a ne běh; scope, který vytiskne prózu, dopadne stejně; pack, který nic nedeklaruje, nespouští nic; `context.json` na scope ukazuje; doktor pozná chybějící skript. `test_outputs.py` — přeformulovaná sázka o téže sázce je duplicita (dřív nebyla), dvě sázky o dvou sázkách ne, ukotvený nález má pořád klíč `sym:`/`file:`, a skutečný `packs/ceo/scripts/scope.py` čte formát, který `method.md` předepisuje. „`bet` a `finding` se stejným tělem nejsou duplicita" už testoval Krok 3.

**Hotovo, když:** ~~`known-here.json` je poprvé neprázdný u packu bez grafu.~~ Splněno — `test_a_pack_with_no_graph_finally_gets_a_here_list`.

**Co zbývá pro ostrý provoz:** ~~přenos `packs/ceo/` do repa Kvesteros a doplnění `Ref:` řádků do `strategy.md`.~~ Hotovo 7. 9.: skript tam vrací `event-supply-baseline`, `showable-product`, `legitimacy-outreach` a `agency doctor` na packu mlčí. Živá kopie byla ještě pre-Krok-4 a nic v ní nebylo rozdivergované, takže se nic zakladatelova nepřepsalo.

**Na co si dát pozor při prvním běhu:** `known-here.json` bude prázdný, protože v tom repu není ani jedna sázka jako output — šest tamních běhů je z doby, kdy `bet` jako typ neexistoval. Průnik nemá co potkat a naplní se až od druhého běhu. Prázdný `known-here` proto zatím **není příznak chyby**; tím je až `scopeItems: 0`.

---

### Krok 6 — `actions` ze `sinks` (~0,5 dne) — **hotovo**

**Proč:** `sinks: {prComment, githubProjectItem}` už byly primitivní výsledky akcí, jen zadrátované na dvě cesty. Není to nový subsystém, je to zobecnění tvaru.

**Co se změnilo:**

```json
"actions": [ { "kind": "draft", "target": "255", "result": "success",
               "remoteId": "PVTI_X", "url": "…", "error": null, "at": "…" } ]
```

**Rozdělení, které to drží:** *output = co specialista rozhodl nebo vytvořil; action = co se kvůli tomu skutečně změnilo ve světě.* Prázdné pole je legitimní stav a ten nejčastější — projekt bez boardu drží nálezy v gitu, sázka je návrh pro zakladatele a nedojde nikam.

**Čtyři věci, které vyšly jinak, než plán čekal:**

1. **Slovník `kind` nedodává jádro, dodává ho sink.** Plán vypsal `pr_comment`, `github_project_item`, `board_decision`, `board_draft`, `issue_promotion` — jenže jádro o žádném z nich neví. Ví jedinou věc: *doběhl packův sink*. A packy to samy tisknou už dnes — `backlog.py` vrací `kind: draft | comment | issue | draft-note` a jádro to zahazovalo. `kind` se proto bere z odpovědi sinku, výchozí je `sink` (to, co jádro skutečně ví), a hodnota, která není jméno, se nahradí — je to text, který tenhle nástroj nepsal, a uložit ho neověřený znamená `findings.json`, který spadne až v `agency validate` nad polem, které nikdo nečte.
2. **Neúspěšný pokus se zapisuje taky** (`result: "error"`). Bez toho žije „board to třikrát odmítl" jen ve třech různých záznamech běhů a z outputu to není vidět vůbec. `dispatchErrors` v `run.json` zůstává — je to jiná otázka (co tenhle *běh* neodeslal) a čte ho výpis ingestu.
3. **`outputs.<type>.actions` se konečně čte.** Šlo deklarovat od Kroku 3 a nikdo se na to neptal — pack s boardem by tedy své sázky poslal na board a z návrhu pro zakladatele udělal ticket. Teď se typ s `actions: "none"` nedispatchuje vůbec, zůstane `candidate`, a ostatní typy téhož packu jdou dál.
4. **A jedna chyba, kterou našel test, ne úvaha — dvakrát.** `agency ingest` se sám dokumentuje jako idempotentní a nebyl:
   - **Akce se ztrácely.** Brána staví `findings.json` znovu z `findings.raw.json`, což je to, co napsal *pack* — takže druhý ingest tiše odzapsal položku na boardu, která doopravdy vznikla. Akce se proto přenášejí přes přestavbu. Idempotence je slib o **soudu** (týž běh dá tytéž verdikty); akce, která se stala, není verdikt a nedá se vzít zpět tím, že se znovu přečte soubor.
   - **Běh byl duplicitou sám sebe.** `earlier_findings` přeskakuje běhy `r.id >= run.id`, ale polovina, která čte stopu, žádnou takovou pojistku neměla — druhý `ingest` tedy porovnal nálezy proti řádkům stopy, které zapsal ten *první*, a každý odeslaný nález označil za duplicitu sebe sama. Oprava je jeden řádek (`row.get("runId") == run.id`) a docstring té funkce ji vždycky předpokládal: *„findings from older runs, plus the trail"* — a řádek, který zapsal tenhle běh, není ani jedno.

**Migrace:** `actions` **vedle** `sinks`, ne místo něj. Čtenáři umí obojí (`runs.acted_ref`), zapisuje se už jen nový tvar, committed historie se nepřepisuje — táž pravidla jako u evidence bez locatoru v Kroku 2. `sinks` má v schématu napsáno, že je superseded, a mimo jádro ho nikdy nikdo nečetl (rozšíření ani `backlog.py`).

**Testy:** 10 nových, 469 celkem. `test_decisions.py` — sink řekne, co udělal, a jádro to zapíše; mlčící sink je `sink`; `Board Draft!` se jménem nestane; typ s `actions: "none"` se neodešle, zatímco druhý typ téhož packu ano; ledger čte referenci z nového tvaru; nález odeslaný před 7. 9. 2026 pořád ví, kam šel; akce přežije druhý ingest; output, který nedošel nikam, akce nemá; a běh není duplicitou sebe sama. `test_gate.py` — dosavadní tři sink testy přepsané na nový tvar, včetně `["error", "success"]` po opakovaném pokusu.

**Hotovo, když:** ~~PO smí posílat rozhodnutí přes jádro a `agency outputs` u něj ukáže, co se na boardu doopravdy stalo.~~ Druhá polovina splněna — `agency findings --json` nese `actions[]` s výsledkem každého pokusu (příkaz se pořád jmenuje `findings`, přejmenování je Krok 11). První polovina je **Krok 10**: mechanismus stojí, migrace PO na něj do tohohle kroku nepatřila.

---

### Krok 7 — feedback jako události a projekce `state` (~1,5 dne) — **hotovo**, a byl menší, než plán čekal

**Proč:** dnešní `state` je skalár, který [`metrics`](../../packages/core/src/agency/metrics.py) čte na deseti místech, [`dedup`](../../packages/core/src/agency/dedup.py) ho zapisuje a `serve.py` i `cli.py` na něm staví výpis. Seznam událostí je datová změna **plus** jedna funkce, která v seznamu kroků snadno chybí.

**Co se změnilo:** [`runs.verdicts()`](../../packages/core/src/agency/runs.py) — `state = fold(events, policy)`, jedna odpověď **na lifecycle** místo jedné na output:

```python
verdicts(run)[fid] == {"selection": {…"state": "selected"…},
                       "outcome":   {…"state": "successful"…}}
```

Vedle ní `read_events()` (jediné místo, které log čte) a `decisions()` přepsané na ni — pořád vrací poslední verdikt bez ohledu na otázku, protože to je to, co chce devět z deseti volajících („rozhodl o tom vůbec někdo?"). `metrics.count_cycle` je ten desátý a bere teď všechny odpovědi.

**Pět věcí, které vyšly jinak, než plán čekal:**

1. **Past 5 nenastala.** Plán se bál, že si deset míst začne skládat historii samo. Nezačalo: `decisions()` byl jediný fold a čte ho 11 volání v šesti souborech. Krok tedy nebyl „přidat události a k tomu funkci" — události v plném tvaru (`lifecycle`, `polarity`, `by`, `at`) existují od Kroků 3–4 a `agency feedback <id> <kind>` je v CLI taky. Zbývalo jediné: **fold byl moc hrubý.** Odhad 1,5 dne byl na práci, kterou předsunul Krok 4.
2. **`source` se nepřidal, protože už existuje pod jménem `by`.** Plán chtěl `source: core | human | chain:<pack>`; kód má `by: human | chain | hire:<pack>@<provider>` a `metrics` na něm **už dnes** rozlišuje rozhodnutí řetězu od lidského (`Tally.add` počítá do precision jen `hire:`). Druhé pole s touž informací by znamenalo dvě místa, která si můžou odporovat. Zůstává `by`.
3. **`core` jako zdroj feedbacku nevznikl — a nemá.** `duplicate` píše [`dedup.mark_duplicates`](../../packages/core/src/agency/dedup.py) přímo na output a **žádnou událost nezakládá**. To není mezera: `state` je místo v potrubí (candidate, held, sent, duplicate), verdikt je událost, a [`runs.py`](../../packages/core/src/agency/runs.py) to říká výslovně už od Kroku 4 (*„The output's `state` is deliberately NOT touched"*). Kdyby jádro svoje účetnictví zapisovalo jako feedback, precision by začala počítat rozhodnutí, která nikdo neudělal. Zamčeno testem.
4. **`requires` bylo mrtvé pole a teprve tady ožilo.** `outputs.errors()` ho validovalo, `agency doctor` ho hlídal a **nečetlo ho nic** — takže zamítnutá sázka seděla ve jmenovateli `success_rate` jako nerozhodnutá a ten poměr klesal s každou sázkou, kterou zakladatel odmítl. Teď `Lifecycle.requirement` říká, které otázky jsou **otevřené**.
5. **A jedna chyba, kterou našel test, ne úvaha.** První verze `requires` zahazovala i odpověď, která existovala: sázka označená `successful` bez zapsaného `selected` by se nezapočítala vůbec. `test_the_two_questions_stay_two_numbers` spadl hned. Správné pravidlo: **`requires` rozhoduje o tom, které otázky jsou otevřené, nikdy o tom, které odpovědi se počítají.** Odpověď, kterou někdo dal, je důkaz, že otázka padla — zahodit ji kvůli nezapsané předchozí je ztráta jediné věci, kterou nikdo nedopočítá.

**Co zůstalo jako druhý fold, vědomě:** [`knowledge.py`](../../packages/core/src/agency/knowledge.py) (578) skládá `events[-1]` **napříč rodinou duplicit**, ne uvnitř běhu — je to jiná otázka („kdo o tomhle tvrzení řekl něco naposled, ať už v kterémkoliv běhu") a projekce na ni odpovědět neumí. Není to past 5; ta mluví o deseti místech, která skládají **týž** stav.

**CLI se nezměnilo**: `agency findings` ukazuje totéž co dřív, `agency accept` / `agency reject` jsou pořád zkratky a obecný `agency feedback <id> <kind>` byl v CLI už od Kroku 4.

**Testy:** 10 nových, 479 celkem. `test_decisions.py` — dvě odpovědi na dvě otázky dají dva stavy, zatímco dvě odpovědi na **jednu** otázku jsou oprava a poslední vyhrává; událost bez `lifecycle` (committed historie) se čte přes politiku; `deferred`, který nezná žádná politika, se složí pod `None` a neprojde za odpověď; poznámka není verdikt; duplicita nemá událost; nedopsaný poslední řádek nestojí běh o verdikty před ním. `test_outputs.py` — jedna sázka odpoví na obě otázky a obě se počítají; nevybraná sázka nečeká na výsledek; vybraná ano.

**Hotovo, když:** ~~`agency findings` ukazuje totéž co dnes, ale čte to z projekce.~~ Platí — a přejímka §7 bodu 3 s tím taky: `selection_rate` a `success_rate` jsou dvě nezávislá čísla i pro jednu sázku, která prošla oběma fázemi.

---

### Krok 8 — `score` přestane být branou, objem se řídí jinak (~0,5 dne) — **hotovo**

**Co se změnilo:** `below-score` z brány zmizel a s ním `counts.belowScore` z `run.v1`, `--min-score` z CLI, `minScore` z `context.json` i z `agency packs --json`. `score` se **dál zaznamenává** — [`metrics`](../../packages/core/src/agency/metrics.py) z něj počítá `scoreAccepted` / `scoreRejected` a je to jediné místo, kde se pozná pack, který dává všemu 90 a má precision 0.4.

> **Score není signál pravdivosti, je to signál kalibrace. Vyšší riziko musí zvyšovat nároky na evidenci, ne číslo, které si model přidělí sám.**

**Otázka, kterou plán nechal otevřenou — strop, nebo řazení? — má odpověď: obojí, a každé na jiné vrstvě.** Strop rozhoduje *kolik*, score rozhoduje *které*:

* **`outputs.<type>.limit` je strop** na typ a běh. Existoval od Kroku 3, ale platil jen tomu, kdo si ho vyžádal — a `outputs` blok má **jediný ze sedmi packů** (`ceo`). Šest ostatních by po zrušení `minScore` nemělo pojistku na objem žádnou. Proto `TypePolicy.max_per_run` vrací `outputs.RUNAWAY` (25) tam, kde pack nic neřekl.
* **Score se uplatní teprve u stropu**, a jen jako pořadí: přes strop přežije N nejlepších, shodu rozhodne pořadí, v jakém je pack napsal. Score nikdy neřekne „tohle je nepravda" — to o sobě žádné číslo od modelu říct nemůže. Řekne „tohle dřív než tamto", a to má smysl jen tam, kde běh napsal víc, než kdo přečte.

**Číslo 25 není odhad, je změřené.** [`baseline.md`](../baseline.md) §1: obava z „bambiliónu nálezů" **daty nesedí** — poslední strukturovaný běh se čtyřmi personami dal **tři** nové nálezy a dvanáct shod (dedup potlačuje 80 % objemu), za celé měřené období vzniklo 51 nálezů a nejsilnější producent jich měl 36. *Úzké hrdlo je lidský triage, ne generování.* Strop je tedy zhruba osminásobek normálního běhu: chytí pack, který má špatný den, ne pack, který dělá svou práci.

**Tři věci, které vyšly jinak, než plán čekal:**

1. **Strop se přesunul za bránu, ne do ní.** Dřív se kontroloval v cyklu a padal *jedenáctý v pořadí příchodu*. Aby mohl rozhodovat score, musí se trimovat až nad tím, co branou prošlo — `_under_ceiling()` je druhý průchod. Vlastnost, kterou původní komentář hájil (*„nepoctivý jedenáctý se má zahodit jako nepoctivý, ne jako jedenáctý"*), tím platí dál a nově i pro řazení.
2. **`minScore` se nedá jen tak smazat.** Živé packy bydlí v cizích repozitářích a `minScore: 85` v nich zůstane — a bude vypadat jako přísnější pack, kterým nebude. Klíč proto není chyba (manifest nemá schéma), ale `agency doctor` u něj řekne, že nedělá nic. Táž migrace jako u `sinks` v Kroku 6.
3. **Agent se o stropu dozví předem.** Na místě, kde v `context.json` bylo `review.minScore`, je teď `review.limits` — mapa typ → strop. Rozdíl je mezi packem, který napíše jedenáct sázek a osm mu někdo ořízne, a packem, který napíše ty tři, o které byl požádán.

**Co si tenhle krok vyžádal mimo jádro:** `minScore` zmizel z pěti referenčních `pack.json` a z dvanácti vět v sedmi `SKILL.md`, které o prahu mluvily jako o pravidle. **Živé packy to nemají** — CEO v repu Kvesteros pořád nese `minScore: 80` a větu o něm ve `SKILL.md`. Doctor to tam ohlásí; opravit se to má při Kroku 10.

**Testy:** 3 nové, 482 celkem. `test_gate.py` — nález se score 40 a dobrou evidencí projde a score se pořád zapisuje; pack bez deklarovaného stropu ho přesto má (26 nálezů → 25 a jeden `over-cardinality` v `gatedBy`). `test_outputs.py` — přes strop přežijí nejlíp ohodnocené a v pořadí, v jakém byly napsané; manifest, který pořád jmenuje `minScore`, dostane od doktora větu, že to nic nedělá.

**Hotovo, když:** ~~`agency ingest` nezahodí nic kvůli score a fronta přesto neroste přes strop.~~ Platí obojí.

---

### Krok 9 — uvolnit povinnou kotvu (~2 dny) — **hotovo**, a nebyl to nejdražší krok

**Co se změnilo:** `anchor` přestal být zvláštní pole a je z něj `evidence.kind = code`; čtyři vrstvy se přestěhovaly do `locator` beze změny. [`anchor.py`](../../packages/core/src/agency/anchor.py) — čtyřvrstvé kotvení, drift — zůstal nedotčený a přibyly mu dvě čtecí funkce. Pole ve `finding.v1` zůstává jako superseded, přesně jako `sinks` z Kroku 6: committed historie ho má a jádro ho pořád čte.

**Správná formulace hranice** platí tak, jak ji plán napsal:

> Ne „CEO nemusí mít kotvu", ale **„CEO nemusí mít code evidence — musí mít jinou ověřitelnou evidenci."**

**Číslo 58 bylo špatná míra.** Většina těch výskytů je slovo „anchor" jako **jméno mechanismu** — modul, drift, docstringy, `anchor: required` v politice — a to nikam nejde. Míst, která čtou samotné **pole nálezu**, bylo jedenáct, a všechna se schovala za jednu funkci. Po kroku zbyly dvě, obě uvnitř `anchor.py`; ostatní `get("anchor")` v jádru čtou řádek stopy nebo klíč manifestu, což je něco jiného. Skutečná cena kroku nebyla v jádru, ale v sedmi `SKILL.md`, které kotvu učily psát jako pole.

**Čtyři věci, které stojí za zapsání:**

1. **Dvě čtecí funkce, ne jedna.** `anchor.of()` odpovídá „kde ten output sedí" — jedno místo, a čtou ho dedup, drift a fronta. `anchor.places()` odpovídá „co má brána zkontrolovat", a to je seznam: nález může citovat tři kusy kódu a vymyslet ten třetí. Jedna funkce pro obojí by tiše nechala dva ze tří důkazů nepřečtené.
2. **`phantom-file` si musel code locatory vzít zpátky.** Ta chyba, která byla o vlásek: kdyby vymyšlený soubor v locatoru padal dál na `unverified-evidence` (kam ho dal Krok 2), pack, který se zmigruje, by měl `phantom-file` **nula** — a vypadal by jako pack, co se zlepšil. Počítadlo halucinací si drží jméno bez ohledu na to, které pole tu chybu neslo, takže `unverified()` code evidenci pustil a brána ji kontroluje pod starým jménem. Táž zásada, jakou už měl `test_a_cited_command_reads_the_same_in_both_shapes`.
3. **`symbol` v locatoru je podmínka, ne ozdoba.** `dedup.subject_key` bere místo outputu ze symbolu. Kdyby ho locator neuměl nést, první běh po migraci by nahlásil **celý backlog znovu** a nic by na to neupozornilo. Proto `locator` dostal `snippet`, `symbol` i `body` a proto je na to vlastní test (`test_a_pack_that_migrates_does_not_report_its_backlog_again`).
4. **Politika se s `evidence.required` nesloučila**, i když teď obě mluví o druzích evidence. Ptají se jinak: `evidence.required` je seznam, ze kterého stačí **jeden**, `anchor: required` je druh, který tam **musí** být. Review nález potřebuje `code` **a** jeden z graph/rule, a to seznam s „nebo" neumí říct.

**Tři věci spravené cestou** (všechny nalezené tím, že se do těch souborů sahalo): popis `score` ve `finding.v1` pořád tvrdil, že se nález pod prahem nepublikuje — to Krok 8 minul; fallback v `agency validate` bez `jsonschema` vyžadoval `anchor` jako povinný klíč, ačkoliv ze `required` vypadl už v Kroku 4; `verify/SKILL.md` popisoval tvar `upstream.json`, který nikdy neměl (`_view` kotvu plochá na `file`/`line`/`symbol`). A `stop_errors()` teď kontroluje i locatory — částečně tím zaniká jedna z vědomě otevřených věcí z Kroku 2.

**Testy:** 6 nových, 488 celkem. Nález řečený novým tvarem projde branou stejně jako starý; typ, který má ukazovat do kódu, se nespokojí s grafovým faktem; kontroluje se **každé** citované místo, ne první; migrovaný pack nehlásí backlog znovu; čtyři vrstvy a drift čtou locator stejně jako pole; stopa si po odmítnutí pamatuje místo i u nálezu, který ho řekl nově.

**Hotovo, když:** ~~review nález se chová identicky jako dnes, včetně driftu, a CEO sázka nemá `code` evidenci ani ji nepředstírá.~~ Platí obojí.

---

### Krok 10 — migrace PO a CEO na jádro (~1,5 dne) — **hotovo**

**Co se změnilo:** PO píše rozhodnutí a návrhy ticketů do `findings.json` jako outputy typu `decision` a `ticket_draft`; CEO přidal `answer` (`cardinality: one`) a `draft`. Registry zůstaly paměťovými stránkami a output typem se nestaly (§0.1, §3.3). Věta, na které stála přejímka, ze `packs/po/SKILL.md` zmizela — přestala být pravdivá.

**Dvě mezery v jádru, které otevřela až migrace.** Obě byly neviditelné, dokud byl `finding` jediný typ, který jedná:

1. **Typ, který smí jednat, musí mít kam zapsat, že jednal.** `runs.dispatch()` zapisuje `sent` sám a `append_decision` odmítne slovo, které žádný lifecycle nezná. Typ s `actions: sink` a bez `sent` v `kinds` proto nespadne u doktora — spadne až v běhu, potom, co už na board napsal. `finding` to nikdy neukázal, protože `triage` lifecycle dědí, ať si ho pack vyžádá nebo ne. Teď to `outputs.errors()` odmítne dopředu.
2. **`agency feedback` odmítal každý typ se sinkem.** Argument („`agency triage accept` navíc odesílá, pouhý zápis by to neudělal") platí pro verdikt, který odesílá — a o rozhodnutí, které vlastník po třech týdnech přehlasoval, není co odesílat. Ten verdikt jiné sloveso nemá, a bez něj nemá `upheld_rate` čitatel. Odmítnutí se zúžilo z celého typu na kindy toho jednoho lifecyclu.

**Kde bydlí dispozice — a proč ne ve schématu.** `finding.v1` má `additionalProperties: false` a jádro nesmí vědět, co znamená `BUILD-NOW` (§3.5). Dispozice proto jede v **hlavičce těla** rozhodnutí — `Disposition:`, volitelně `Commitment:` a `Cycle:`, blok končí prázdným řádkem — a čte ji packův vlastní skript. Je to týž vzorec, jaký plán zavedl v Kroku 5 řádkem `Ref:` ve `strategy.md`: pack-specific struktura patří do textu, který pack sám píše i sám čte. *(Poznámka pro pořádek: „pět dispozic jsou `kinds` v lifecyclu" v dřívější verzi téhle sekce byla chyba. Dispozice je **obsah** rozhodnutí; `kinds` jsou verdikty **o** rozhodnutí — upheld / overridden / reverted, přesně jak to §5 vždycky měla.)*

**Jeden sink, ne jeden na typ.** `pack.sink` zůstal jediným příkazem a `backlog.py` dostal sloveso `dispatch`, které si typ přečte z outputu a zaroutuje ho samo. Jádro se tak nemuselo naučit rozdíl mezi `draft` a `decide`, a mechanismus z Kroku 6 — pack hlásí zpátky `kind` akce — do toho zapadl beze změny. Na `dispatch` přešly i legal, qa a review-graph, takže na board vede **jedna** cesta místo dvou.

**A hlavně: stará cesta je zavřená.** `backlog.py decide` a `draft` zmizely z `needs` i `needsUnattended` PO packu — agent na ně nemá oprávnění a nemůže rozhodnutí poslat sám. Migrace, která nechá starou cestu otevřenou, se vrátí prvním nepohodlným během; je na to test.

**Odvozený feedback (§5) nedostal nový mechanismus a nepotřeboval ho.** Board čte `backlog.py snapshot`, verdikt zapisuje `agency feedback`, a dělá to **příští běh PO packu** — `SKILL.md` má na to krok ještě před vlastními dimenzemi. Zdroj je tím reálný, ne aspirační, a `by` už dnes odliší, že to zapsal pack a ne člověk. Co se **nezapisuje**, je stejně důležité: rozhodnutí, na které board zatím neodpověděl, nedostane nic. Ticho není souhlas a odhad by změřil jen vlastní optimismus.

**Živé packy dorovnané.** Šest packů ve dvou repozitářích (`kvesteros-platform/agency-ceo`, `main-panel/agency-{po,legal,qa,review-graph,author}`) běželo na verzi před Krokem 8 — `minScore` v manifestu, kotva jako pole, u autora chyběly celé sekce. `agency doctor --json` je v obou repech čistý.

**Testy:** 11 nových, 499 celkem. Rozhodnutí dojde přes jádro na board a nese packovo vlastní sloveso v `actions`; rozhodnutí bez `subject` neprojde; dva běhy nerozhodnou týž ticket dvakrát a dvě rozhodnutí o dvou ticketech nejsou duplicita; přehlasování se zapíše a `sent` pořád patří triage; typ, co smí jednat a nemá kam zapsat `sent`, doktor odmítne; skutečný `packs/po/pack.json` říká všechno výše a **negrantuje agentovi starou cestu**; sink jmenuje sloveso, které skript má; a hlavička s dispozicí se čte z obou stran.

**Hotovo, když:** ~~v `packs/po/SKILL.md` zmizí věta *„Findings still go to the board through the core, decisions do not."*~~ Zmizela.

---

### Krok 11 — rename `finding` → `output` (~0,5 dne) — **hotovo**

Úplně nakonec, v okamžiku, kdy to skutečně nejsou jen nálezy. Rename na začátku by vyrobil generický název nad review sémantikou — nejhorší z obou světů, a přitom by vypadal jako pokrok.

**Co se přejmenovalo:** `agency outputs` je hlavní příkaz, `agency findings` jeho alias — **napořád, ne do příště**. Nálezy revizora *jsou* findings, od toho to slovo je; co rename kupuje, je zakladatel, který čte `agency outputs --type bet` a neptá se, která z jeho tří sázek je nález. Packy mají v `needs` obě jména, protože obě jsou pravdivá.

**Co se schválně nepřejmenovalo, a proč:**

* **`findings.json`, `finding.v1`, `findingId` v událostech.** V těch souborech je committed historie tří repozitářů. Přejmenovat je znamená buď migrovat cizí repa, nebo mít dvě jména na totéž — a to druhé je přesně ta past, kterou plán řešil u `sinks` a `anchor`.
* **`FINDING_POLICY`, `FINDING_REASONS`, `DEFAULT_TYPE = "finding"`.** Ta jména nejsou pozůstatek, jsou správná: typ se doopravdy jmenuje `finding` a ta politika je jeho. Zobecnit je by znamenalo tvrdit, že `finding` je něco obecného, což je opak toho, co plán udělal.
* **`dispatchErrors` v `run.json`.** Tohle je jediné místo, kde si plán odporoval sám se sebou: inventura psala „při tom uklidit, je to od Kroku 6 odvoditelné z `actions`", ale retrospektiva Kroku 6 už dřív rozhodla, že **zůstává**, a měla pro to důvod. Platí ten důvod: `actions[]` je append-only a odpovídá „co se s tímhle outputem kdy stalo", `dispatchErrors` se přepočítá při každém ingestu a odpovídá „co tenhle **běh** neodeslal". Druhý ingest ho vyprázdní, akce z prvního zůstane — jsou to dvě otázky, ne jeden zdvojený zápis.

**Testy:** 2 nové, 501 celkem. Obě hláskování míří na tentýž příkaz; `--type decision` vrátí rozhodnutí a ne nálezy téhož běhu, a to rozhodnutí nemá místo ve zdrojáku.

---

## 5. Odkud přijde feedback

**Největší produktová otázka celého refactoru.** Bez zpětné vazby není paměť, a bez paměti nepřinese zobecnění datového modelu nic než hezčí schéma.

| output | feedback | zdroj | kategorie |
|---|---|---|---|
| review `finding` | accepted / rejected / duplicate / intentional | `agency triage`, člen řetězu `verify` | **explicit** |
| PO `decision` | upheld / overridden / reverted | stav boardu, zapisuje příští běh PO (Krok 10) | **derived** — živé |
| PO `ticket_draft` | promoted / dropped | stav boardu, zapisuje příští běh PO (Krok 10) | **derived** — živé |
| CEO `bet` (selection) | selected / rejected | zakladatel vybírá ze tří | **explicit** |
| CEO `bet` (outcome) | successful / failed / abandoned | — | **unknown** |
| CEO `draft` | sent / not-sent | — | **unknown** |
| CEO `draft` | got response | — | **unknown** |
| CEO `answer` | — | — | write-only — a v `pack.json` opravdu bez `feedback` (Krok 10) |
| QA `bug` | confirmed / not-reproducible / fixed | triage, opakovaný běh | explicit / derived |

**explicit** — člověk ten feedback stejně přirozeně vysloví. Ideál.
**derived** — Agency ho umí vyčíst ze světa (board se pohnul, issue je v Done). Funguje, pokud existuje odpovídající sink nebo connector.
**unknown** — neexistuje přirozený zdroj. **Lifecycle se nevymýšlí.** Takový output je `write-only`, nebo má feedback jen do fáze, kam ho někdo doopravdy dodá (`proposed → selected` a dál nic).

To je jediná ochrana před frameworkem, který půl roku vypadá, že se učí. Chyba, která by se neprojevila jako pád testu, ale jako prázdná tabulka po šesti měsících.

---

## 6. Pasti

1. ~~**Uvolnit kotvu dřív než dodat locatory**~~ (§0.2, Krok 9) — nenastalo, pořadí kroků ji obešlo. Past, která nastala místo toho: **přejmenovat důvod zahození při stěhování pole.** Vymyšlený soubor v locatoru padal od Kroku 2 na `unverified-evidence`; kdyby to tak zůstalo, pack po migraci by měl `phantom-file` nula a vypadal by, že přestal halucinovat. Jméno chyby patří chybě, ne poli, které ji nese.
2. **Plochá feedback mapa** (§1.3). Vyrobí číslo, které vypadá jako metrika a není žádná.
3. **Hrubý `subject`** (Krok 5). Vypne pojistku v dedupu a začne slučovat různá tvrzení.
4. **Nechat `scope` psát agenta** (§3.2). Nekontrolovatelné, gameable, a stejně pozdě.
5. ~~**Zapomenout na projekci `state`**~~ (Krok 7) — nenastalo, fold byl od začátku jeden. Past, která nastala místo toho: **podmínka, která zahodí odpověď.** `requires` říká, které otázky jsou otevřené; kdyby rozhodovalo i o tom, které odpovědi se počítají, sázka označená `successful` bez zapsaného `selected` by zmizela z metrik úplně. Chytil to test, ne úvaha.
6. ~~**Zrušit `minScore` bez náhrady objemu**~~ (Krok 8) — nestalo se, ale málem jinudy: náhrada v jádru **byla** a platila jen packu, který si ji vyžádal. Šest ze sedmi packů `outputs` blok nemají. Past se tedy neschovává v tom, že náhrada chybí, ale v tom, že existuje a nikoho nechrání.
7. **Postavit `register` jako output type** (§0.1). Zdvojí mechanismus, který v `knowledge/pages/` funguje.
8. **Ověřovat evidenci proti živému světu** (§3.1). Zabije replay a determinismus.
9. **Past §0.3 z [`harness.md`](harness.md) znovu:** cokoliv nového v `run.json` musí zároveň do `run.v1` a do statistik, které z něj čtou. `scope` z ní nakonec vyklouzl tím, že do záznamu nešel vůbec (Krok 5, důvod 2) — ale statistika `scopeItems` ano, a ta musela do `MEMORY_STATS`, jinak by ji `collect_evidence` u grafového běhu vložila do bloku `graph`, který má v `run.v1` zavřený seznam klíčů. Přesně ta chyba, kterou tahle past popisuje, jen o patro níž.

---

## 7. Přejímka

Plán je hotový, když platí všech pět:

1. **`agency outputs --type bet` funguje** a sázka nemá ani nepředstírá code evidenci.
2. **Brána zahodí sázku doloženou URL, které v tom běhu nikdo neotevřel** — a udělá to offline.
3. **`agency metrics` u CEO ukáže `selection_rate` a `success_rate` jako dvě nezávislá čísla**, ne jejich směs.
4. **Review pack se chová identicky jako před refactorem** — tytéž nálezy, týž dedup, týž drift, tytéž metriky. Když ne, není to zobecnění, ale výměna.
5. **`packs/po/SKILL.md` už neobsahuje větu o tom, že rozhodnutí jádro obchází** — protože ho neobchází.

Bod 4 je ten, na kterém to stojí. Celý smysl je, že review-graph nepřestane fungovat — jen přestane určovat datový model všech ostatních.
