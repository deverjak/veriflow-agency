---
name: agency-qa
description: "Use when asked to test a running application against a written brief and record what is broken durably. Triggered by `agency run qa --prompt \"…\"`, which resolves the project, collects what it already knows and writes a context bundle; this skill then explores the app as the configured personas — through Playwright when the project has it — reproduces every problem in a failing spec, anchors it to the responsible code and writes findings.json. Also usable directly: 'QA session on the booking flow', 'test the checkout as a logged-out user'. Not for reviewing a diff or a pull request — use the agency-review-graph pack for that."
---

# QA session against a brief

Průzkum **běžící aplikace** podle zadání, které napsal člověk. Metoda je pořád stejná; co se má zkoušet, říká `brief` — a to je jediný rozdíl mezi dvěma projekty i mezi dvěma sezeními na tomtéž projektu.

**Výstupem není report. Výstupem je `findings.json`.** Každý nález je reprodukovaný a zakotvený na řádek kódu, který ho způsobuje. Nereprodukované pozorování není nález; nález bez kotvy za měsíc nikdo nedohledá.

## Co dostáváš hotové

`agency run qa` udělalo deterministickou část. **Nedělej ji znovu.** Přečti si:

```
<RUN_DIR>/context.json                 zadání, konfigurace projektu, stav pracovní kopie
<RUN_DIR>/evidence/known-findings.json co už tenhle projekt našel a jak to dopadlo
<RUN_DIR>/evidence/known-specs.json    reprodukční testy ze starších běhů — dají se pustit znovu
<RUN_DIR>/evidence/recent-commits.txt  co se v projektu poslední dobou dělo
<RUN_DIR>/evidence/changes.txt         diff proti základní větvi, když nějaký je
<RUN_DIR>/run.json                     záznam běhu, který na konci doplníš
```

`context.json` nese mimo jiné:

| Klíč | Význam |
|---|---|
| `brief.standing` | co o projektu platí **pořád** — z `.agency/qa.json` |
| `brief.focus` | zadání **tohohle** běhu, z `--prompt` nebo ze scénáře |
| `by` | čím se podepsat pod rozhodnutí o nálezu (`agency triage … --by <by>`). Hotové z jádra — neskládej ho sám. |
| `config.app` | kde aplikace běží, v jakém prostředí, čím se pozná, že jede |
| `config.playwright` | jestli a čím se řídí prohlížeč — a co smíš v projektu založit |
| `config.personas` | za koho se vydávat |
| `config.safety` | co se nesmí — hranice, ne doporučení |
| `config.memory` | kde v projektu bydlí paměť QA |
| `config.session` | rozpočet času, strop nálezů, screenshoty |
| `review.dimensions` | které dimenze pustit |
| `review.minScore` / `review.language` | práh a jazyk výstupu |
| `target.headRefOid` | commit, na který se kotví nálezy — **plných 40 znaků** |
| `files[]` | co se změnilo proti základní větvi. **Vodítko, kde hledat nejdřív, ne hranice.** |
| `worktreeOwned` | `false` — běžíš v pracovní kopii uživatele, viz níže |

Když `context.json` chybí, běžíš mimo `agency run`. Řekni to uživateli a nabídni `agency run qa --prompt "…"`. Přípravu ručně nesimuluj.

## Hranice, které se neposouvají

- **Pracovní kopie není tvoje.** `worktreeOwned: false` znamená, že jsi v repozitáři, ve kterém uživatel právě pracuje. Zdrojový kód je ke **čtení**. Zapisuje se do `<RUN_DIR>/` a do adresáře paměti z `config.memory.dir` — nikam jinam. Necommituj, nepřepínej větev, nesahej na rozdělanou práci.
- **`config.app.startPolicy: "manual"`** znamená, že aplikaci nespouštíš. Když neběží, běh **skonči** a napiš, čím ji uživatel nastartuje (`config.app.start`). Vymyšlené nálezy z nedostupné aplikace jsou horší než žádné.
- **`config.app.env: "production"`** bez `safety.allowProduction` je důvod běh odmítnout. QA sezení zapisuje data.
- **`safety.allowDestructive: false`** platí doslova: nemazat, nerušit, neplatit. Když se flow bez destruktivního kroku dokončit nedá, zapiš to jako nepokrytou část, ne jako nález.

## 1. Přečti zadání a paměť projektu

1. `brief.standing` + `brief.focus`. Focus je konkrétní úkol, standing je kontext, ve kterém platí. Když si odporují, vyhrává focus a zmíníš to v `run.json` → `exitReason`.
2. `config.memory.dir` — `coverage.md` (co už se zkoušelo) a `known-regressions.md` (co se opakovaně vrací). Když adresář neexistuje, projekt zatím paměť nemá; založíš ji v kroku 8.
3. `evidence/known-findings.json` — **dřív, než začneš.** Nález, který projekt už jednou zamítl s důvodem `by-design`, nehlas podruhé. Dedup po ingestu je pojistka, ne náhrada za tohle.
4. `files[]` a `evidence/recent-commits.txt` — co se v kódu poslední dobou hnulo. Tam se rozbíjí nejvíc věcí.

Z toho sestav **plán sezení** do `<RUN_DIR>/plan.md`: seznam konkrétních průchodů (persona → cíl → očekávaný výsledek), ne prózu. Plán je krátký a je vidět, co z něj zbylo nezkoušené.

## 2. Ověř, že aplikace jede

```bash
curl -sS -o /dev/null -w "%{http_code}" <baseUrl><readyCheck>
```

Nedostupná aplikace = konec běhu se `status: "failed"` a `exitReason` s tím, co vrátila. Neodhaduj chování z kódu — na to je recenzent, ne QA.

## 3. Prohlížeč: co projekt má, to se použije

`config.playwright` rozhoduje, čím se sezení dívá.

Když je `enabled: false`, prohlížeč nepoužíváš — průzkum je omezený na to, co jde přes HTTP, a napiš to do `run.json` → `exitReason`. Zbytek metody platí beze změny.

Když je `enabled: true`, je jediná otázka: **má projekt Playwright?**

| Stav v konfiguraci | Co udělat |
|---|---|
| `configFile` není `null` | **Použij ho.** Spouštěj s `--config <configFile>`, ber z něj `baseURL`, `projects`, `webServer` i přihlášení. Přečti dva tři existující specy z `projectTestDir` a piš ve stejném dialektu. |
| `configFile` je `null`, `scaffold: "run-dir"` | Postav si vlastní konfiguraci **uvnitř běhového adresáře** (níže). Do projektu se nesahá. |
| `configFile` je `null`, `scaffold: "project"` | Smíš přidat `playwright.config.ts` a devDependency **do projektu**. Je to změna, kterou uvidí příští PR — udělej ji jednou, minimální, a zmiň ji v `run.json`. |
| `configFile` je `null`, `scaffold: "never"` | Skonči a napiš, co má uživatel spustit. Průzkum bez prohlížeče nepředstírej. |

**Dialekt projektu se nepřepisuje.** Když má projekt auth setup projekt nebo `storageState`, použij ho. Spec, který si vymyslí vlastní způsob přihlášení, je druhá pravda o tomtéž a rozpadne se při první změně. Když projekt přihlášení nemá, udělej ho jednou v `specs/auth.setup.ts` a ulož stav do souboru z `playwright.storageStateFile` — **ten se necommituje**, je to relace.

**Celou existující sadu nespouštěj.** Od toho je CI (`review.verifyCommand`). Ty píšeš cílené specy k tomu, co zkoumáš.

### Vlastní konfigurace v běhovém adresáři

Při `scaffold: "run-dir"` zapiš `<RUN_DIR>/playwright.config.ts` a nic jiného nikam nepřidávej:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  outputDir: './evidence/playwright',
  reporter: [['list'], ['json', { outputFile: './evidence/playwright-report.json' }]],
  use: {
    baseURL: '…config.app.baseUrl…',
    trace: '…config.playwright.artifacts.trace…',
    screenshot: '…artifacts.screenshot…',
    video: '…artifacts.video…',
    // až potom, co přihlašovací setup ten soubor vyrobí
    storageState: '…config.playwright.storageStateFile…',
  },
  // JEN když config.app.startPolicy === "agent" a config.app.start není null
  webServer: { command: '…config.app.start…', url: '…baseUrl…', reuseExistingServer: true },
});
```

Spouštění:

```bash
npx playwright test --config <RUN_DIR>/playwright.config.ts --project=<browsers[0]>
```

Když `@playwright/test` v projektu není, `npx --yes playwright@latest test …` si ho stáhne do npx cache — do repozitáře nepřidá nic. Prohlížeče doinstaluje `npx playwright install <browser>`; jdou do uživatelského cache, taky mimo projekt. Instalaci **do projektu** dělej jen při `scaffold: "project"`.

## 4. Průzkum: persona, ne klikání

Za každou personu z `config.personas` projdi cíle z plánu. Když personas nastavené nejsou, jedeš za anonymního návštěvníka a za jeden přihlášený účet z `config.app.accountsFile`.

| Dimenze | Na co se dívá |
|---|---|
| `happy-path` | dělá hlavní flow to, co slibuje, celý, do konce |
| `edge-cases` | prázdný stav, mez, dlouhý text, diakritika, dvojklik, zpět v prohlížeči |
| `errors` | selže to čitelně? dá se z toho dostat? nebo to jen tiše nic neudělá |
| `data` | přežije výsledek reload, druhou záložku a odhlášení |
| `access` | co role **nesmí** — cizí záznam přes URL, akce skrytá jen v UI |
| `regression` | to, co je v `known-regressions.md`; a specy z `known-specs.json` se dají rovnou pustit znovu |

Průběžně sbírej **evidenci, ne dojmy**: přesné kroky, URL, konzolové chyby, stavy odpovědí, screenshot do `<RUN_DIR>/evidence/`. Co nemá kroky, nemá reprodukci.

Regrese má proti ostatním dimenzím výhodu: nález ze staršího běhu s uloženým specem se ověří spuštěním, ne novým průzkumem. Když takový spec **projde**, je to zpráva („vypadá to opravené"), ne nález — napiš ji do poznámky přes `agency note <id> "…"`, ne do `findings.json`.

## 5. Deterministická brána: reprodukce je spec, ne odstavec

Než z pozorování uděláš nález, **napiš k němu spec a nech ho spadnout na tom, co je rozbité.**

```
<RUN_DIR>/specs/<slug-nálezu>.spec.ts     při specTarget: "run" (výchozí)
<projectTestDir>/<slug>.spec.ts           při specTarget: "suite"
```

Pravidla, na kterých to stojí:

- **Jeden spec = jeden nález.** Jméno souboru je slug titulku, ať se pár najde i za rok.
- **Čistý kontext.** Playwright dává každému testu nový browser context sám — nespoléhej se na stav z předchozího testu a nepiš specy závislé na pořadí. Tohle je právě ta izolace, kterou ruční klikání nemá.
- **Selhat musí ze správného důvodu.** Assertion na chování (`await expect(page.getByText('Rezervace potvrzena')).toBeVisible()`), ne timeout na selektor. Spec, který spadne na chybějícím tlačítku, tvrdí něco jiného, než chceš tvrdit.
- **Pusť ho dvakrát.** Test, který jednou projde a jednou spadne, není nález, ale flaky test — nebo jsi našel race condition, a pak to tak napiš a doloz to.
- **Bez destrukce.** `safety.allowDestructive: false` platí i pro specy. Data, která spec vyrobí, uklízej v `afterEach`, kde to jde.

Když je Playwright vypnutý, platí totéž ručně: zopakuj postup v novém okně prohlížeče s prázdným úložištěm a zapiš kroky. Reprodukce z kontaminovaného sezení je ta nejdražší chyba, jaké se tady dá dopustit — v baseline projektu takhle vznikl nález `401 no_authorization`, který byl artefaktem předchozího klikání a jehož skutečná diagnóza byla úplně jiná.

Zahoď všechno, co:

- **se nepodařilo zopakovat** — patří do `plan.md` jako nejisté pozorování, ne do findings
- **je vlastnost prostředí**, ne aplikace: mrtvý seed, vypnutá integrace ve stagingu, expirovaný testovací účet
- **chytá CI** — `review.verifyCommand` dělá typecheck/lint/testy, nederivuj to znovu
- **projekt už zná** z `known-findings.json` nebo z `known-regressions.md`
- **je vkusová věc** bez opory v zadání, v dokumentaci nebo v chování, které aplikace sama slibuje

Co přežije, oskóruj 0–100 a ponech `>= review.minScore`. **Nula nálezů je platný výsledek**, ne selhání běhu.

## 6. Kotva do kódu

Nález z UI musí ukázat na kód, jinak z něj nikdo neudělá opravu. Postup od symptomu ke zdroji:

```bash
# co obsluhuje tu cestu / ten text z chybové hlášky
rg -n "<řetězec z UI>" --glob '!node_modules'
# když je v projektu graf, je to rychlejší a přesnější
agency graph locate "<name>" --repo <project.root>
agency graph neighbors <name> --direction in --repo <project.root>
```

Pomůže i trace ze spadlého specu: nese poslední request, jeho stav a stack — a odtud je k handleru krok.

Do `anchor` patří:

- **`file` + `line`** — POSIX cesta relativní ke kořeni projektu, řádek, který chování způsobuje. Ne test, ne konfigurace, ne místo, kde se to jen projeví.
- **`commit`** — `target.headRefOid`, **plných 40 znaků**. Zkrácený SHA může později tiše ukázat jinam.
- **`snippet`** — celý blok `line..endLine`, ne jeden řádek.
- **`symbol`** — jediná vrstva kotvy, která přežije refaktor. Vyplň z grafu, ne odhadem.

Když kotvu opravdu neumíš najít — chyba je v datech nebo v cizí službě — zakotvi na místo, kde aplikace ten výsledek přebírá, a napiš to do `body`. Nález bez kotvy neprojde bránou v `agency ingest` a byla by to zbytečně vyhozená práce.

## 7. Zapiš `findings.json`

Jediný povinný výstup. Do `<RUN_DIR>/findings.json` pole objektů podle `finding.v1`:

```jsonc
{
  "id": "<ULID>",
  "runId": "<z run.json>",
  "pack": "qa@0.1.0",
  "dimension": "happy-path",
  "severity": "high",
  "title": "Jednovětné tvrzení, co je rozbité",
  "body": "Markdown: co se stalo, co se mělo stát, a KROKY: 1. … 2. … 3. → místo potvrzení prázdná stránka.",
  "anchor": {
    "file": "app/booking/actions.ts",
    "line": 142,
    "endLine": 158,
    "commit": "<plných 40 znaků target.headRefOid>",
    "snippet": "<text bloku 142..158>",
    "symbol": { "name": "createBooking", "range": [128, 171] },
    "body": "<tělo symbolu, strop 8 kB>"
  },
  "evidence": [
    { "kind": "runtime", "detail": "spec selže 2/2 běhů: očekáváno potvrzení, přišlo 500", "source": "specs/rezervace-prazdna-stranka.spec.ts" },
    { "kind": "runtime", "detail": "trace: POST /api/booking → 500, v konzoli TypeError", "source": "evidence/playwright/…/trace.zip" },
    { "kind": "doc", "detail": "podle README má nedostupný slot vrátit 409", "source": "README.md#booking" }
  ],
  "score": 88,
  "state": "candidate"
}
```

- `kind: "runtime"` je pro QA hlavní evidence — pozorované chování. Alespoň jedna položka je povinná, jinak nález neprojde bránou.
- **`source` u reprodukce je cesta ke specu**, relativní k `RUN_DIR`. Tím se z reprodukce stává něco spustitelného: `npx playwright test <ten soubor>` za rok odpoví na otázku „je to opravené?" líp než jakýkoli odstavec.
- Cesty k trace, screenshotu a videu ber z `evidence/playwright-report.json`.
- Piš v jazyce z `review.language`.

Doplň `run.json`: `status`, `finishedAt`, `counts` a `cost` (provider, model, počet dimenzí, doba běhu).

A napiš `<RUN_DIR>/summary.md` — **nejvýš 30 řádků** vlastními slovy: s jakým zadáním jsi běžel, co jsi prošel, co jsi našel (počty a to podstatné, ne výpis nálezů), co jsi rozhodl a co doporučuješ dál. Čte to člověk, chronologie paměti projektu a další specialista, který na tenhle běh naváže. `findings.json` to nenahrazuje ani nekopíruje — strukturovaná data jsou tam, tohle jsou tvoje slova.

## 8. Paměť projektu

Do `config.memory.dir`:

- **`coverage.md`** — jeden řádek na sezení: datum, zadání, co se prošlo, co zůstalo nezkoušené. Bez toho se za měsíc nepozná, jestli je flow v pořádku, nebo se na něj jen nikdo nepodíval.
- **`known-regressions.md`** — přidej jen to, co se vrátilo **podruhé**. Seznam, do kterého se píše všechno, nikdo nečte.

Specy zůstávají v běhovém adresáři a commitují se s ním — jsou to reprodukce nálezů, ne testovací sada projektu. Přesunout spec do sady projektu je rozhodnutí člověka a dělá se až u přijatého nálezu; nabídni to, neudělej to sám (výjimka: `specTarget: "suite"`, kde si to projekt vyžádal předem).

Paměť patří **projektu**, ne packu. Zapiš ji a nech ji tam; git ceremonii kolem ní nedělej.

## 9. Úklid

Aplikaci nech ve stavu, ve kterém jsi ji našel: odhlas se, zavři prohlížeč, testovací data, která šla bezpečně vrátit, vrať. Když jsi něco nechal za sebou (nedokončená rezervace, testovací účet), napiš to na konec `plan.md` — jinak to příští sezení najde jako nález.

Do projektu nepatří nic, co jsi nezaložil se svolením: žádný `playwright.config.ts` navíc při `scaffold: "run-dir"`, žádný `node_modules` v repozitáři, žádný uložený `storageState` v gitu.

Worktree tenhle pack nemá, takže není co mazat. `agency cleanup` na takový běh záměrně nic neudělá.
