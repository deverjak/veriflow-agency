# VeriFlow Agency — první implementační kroky (v0)

**Datum:** 2026-08-30, přepsáno 2026-08-31
**Navazuje na:** [`baseline.md`](baseline.md), [`ui-surface-decision.md`](ui-surface-decision.md)
**Přijaté zadání:** attended only · pouze subscription · self-hosted single-user (vlastní VPS) · 3+ projekty od začátku · agenti se sjednocují, ne izolují · agentní vývoj → dny, ne týdny

**Co se v přepisu 31. 8. změnilo:**

| Bylo | Je | Proč |
|---|---|---|
| „CLI first, UI až později" | CLI **a** VS Code extension od kroku 1 | [`ui-surface-decision.md`](ui-surface-decision.md) — backend bez klienta si zvolí tvar dat, který se dobře zapisuje, ne zobrazuje |
| Jádro v TypeScriptu | **Python** vedle `code-review-graph` | ověřeno: CRG je Python (uv, stdlib `sqlite3`), ne Node. Volba je vědomě dočasná — viz §3.2 |
| „lokální SQLite" | `.agency/runs/` v repu = pravda, `agency.db` = přestavitelný index | deletion-safe persistence; `agency.db` smí kdykoli zaniknout |
| Triage → GitHub Project | Lokální store je pravda, Project je **jednosměrný export** | ruší ruční přepis (35 z 36 nálezů) bez sync konfliktů |
| Kroky 1–6 sekvenčně | Krok 1 je **vertikální řez** na `main-panelu` | mismatch se odhalí za tři dny, ne u kroku 4 |

> **Poznámka k původnímu oponentnímu review.** Dokument `second-opinion-veriflow-agency.md` (30. 8., role „devil's advocate" nad původním návrhem headless control plane + Agent Packs + desktop) byl 31. 8. rozpuštěn do tohoto plánu a do [`baseline.md`](baseline.md) a smazán. Přežilo z něj to, co je pořád platné a nikde jinde nebylo: pravidlo *trigger určuje credential* (§3.3), test ekonomické životaschopnosti (§3.3), princip *páteří je kontrakt* (§3.4), čtyřstavový lifecycle nálezu a deterministická brána (krok 3), kill criteria (§6) a čtyři otevřené otázky (§8). Zahozeno bylo to, co je buď splněné, nebo přebité pozdějšími rozhodnutími: doporučení stavět na bezobslužném běhu (attended-only to ruší), pořadí fází F0–F5 (nahrazeno kroky 0–6), a závěr „nejlepší verze je nudný CLI nástroj bez UI" (přebito rozhodnutím v [`ui-surface-decision.md`](ui-surface-decision.md)).

---

## 1. Kde beru zpět svoje doporučení

Původní oponentní review z 30. 8. doporučovalo „agenty zatím neslučovat, Agency je jen linkuje". **To bylo správně pro jeden projekt a je to špatně pro tři.** Tvoje námitka platí a data ji potvrzují tvrději, než jsi ji formuloval:

**Důkaz 1 — `repoRoot` ukazuje na agenta, ne na projekt.**

```js
// nalekci-qa-agent/scripts/lib/config.mjs
export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
//                                    ^ repo AGENTA, ne cílového projektu
config.paths.product = path.resolve(repoRoot, config.repositories.product); // "../main-panel"
```

Konfigurace, paměť i artefakty se rozpouštějí relativně k **agentovi**. Sourozenecká konvence `../main-panel` předpokládá jeden plochý workspace a jeden projekt. Se třemi projekty to nejde ohnout — musel bys mít tři kopie agenta. To je přesně ten „nový nápad → nové repo" vzorec, který chceš zastavit.

**Důkaz 2 — stav a metoda jsou v jednom repu slepené.**
`memory/STATE.md`, `COVERAGE.md`, `LEARNINGS.md`, `references/known-regressions.md` **nejsou QA metoda. To je paměť projektu NaLekci**, která jen bydlí v repu agenta.

**Takže ano — slučovat. Ale přesně tohle:**

| Vrstva | Kam patří | Sdílí se mezi projekty? |
|---|---|---|
| **Metoda** — skills, workflow, lifecycle, dedup pravidla | do Agency jako **pack** | **ano**, jedna verze pro všechny |
| **Stav** — paměť, coverage, personas, URL, GH project, findings | do **cílového projektu** | **ne**, per projekt |

Není to „sloučit vs. nesloučit". Je to **rozdělit metodu od stavu — a pak sloučit jen metodu.** Dnes jsou spletené, a proto agent neumí druhý projekt.

---

## 2. Referenční architekturu už máš — je to `pr-review-graph`

Tohle je nejdůležitější věc z celého průzkumu.

```
main-panel/.claude/skills/pr-review-graph/SKILL.md    178 řádků, 1 soubor  ← METODA
main-panel/.code-review-graph/graph.db                                     ← STAV projektu
veriflow-architecture/.claude/skills/…                (zkopírováno ručně)
veriflow-architecture/.code-review-graph/graph.db                          ← STAV projektu
```

**Review-graph skill už běží na dvou projektech.** Metoda je v projektu, stav je v projektu, žádné sourozenecké cesty, žádná staging URL, žádné persony. Jediné, co je ruční, je to kopírování.

Porovnej s QA agentem:

| | `pr-review-graph` | `nalekci-qa-agent` |
|---|---|---|
| Metoda | 1 soubor, 178 ř. | 6 skills, 310 ř. + node balík |
| Kde bydlí | v cílovém projektu | ve vlastním repu |
| Stav | `.code-review-graph/graph.db` v projektu | `memory/` v repu agenta |
| Externí nástroj | `code-review-graph` v2.3.7 | Playwright + `gh` |
| Projektů s **grafem** | **3** (main-panel, veriflow-architecture, kvesteros-platform) | — |
| Projektů se **skillem** | **1** (main-panel) | 1 |
| Nálezů (baseline) | **36 z 51** | 15 z 51 |
| Kolik skills je project-specific | viz §2.1 | **1 ze 6** (`qa-session`) |

> **Drahá část už je všude, levná ne.** Graf (main-panel 9 819 uzlů / 105 713 hran / 1 841 souborů; kvesteros 5 784 / 139 152 / 1 105, 7 jazyků) je postavený na třech projektech. Nezkopírovaný zůstal jen ten 178řádkový skill — protože je přivařený k main-panelu.

---

## 2.1 Rozpad packu — manifest vypadl z reality, nevymýšlel se

Skutečné vazby `pr-review-graph` (moje dřívější „závislosti: git" bylo nepřesné):

| Vrstva | Obsah | Sdílí se? |
|---|---|---|
| **Přenositelné jádro** | resolve PR → worktree → `update` grafu → `detect-changes` + `impact` → N dimenzí paralelně → FP filtr + skóre ≥80 → findings | **ano** — to je pack |
| **Konfigurace projektu** | repo slug, šablona cesty worktree, CI příkaz, mapa dokumentace, práh skóre, jazyk výstupu, sinks | ne |
| **Obsah projektu** | dimenze „repo-rule compliance" — u main-panelu Supabase dataAccess fence, RLS/`service_role`, granty, migrace, `createCustomSport`, `NOT VALID` sémantika, diakritiky | ne, vlastní projekt |

Bez projektových pravidel běží **4 z 5 dimenzí** (korektnost/blast radius, pokrytí testy, reuse/dead-code, ošetření chyb). To je legitimní výstup, ne selhání.

**Konfigurační soubor = přesně ten seznam vazeb** — `<projekt>/.agency/review-graph.json`:

```json
{
  "pack": "review-graph@0.1.0",
  "repo": { "slug": "deverjak/kvesteros-platform" },
  "graph": { "db": ".code-review-graph/graph.db", "onStale": "update" },
  "worktree": { "path": "../{repo}-review-pr-{n}" },
  "review": {
    "dimensions": ["correctness", "tests", "reuse", "errors"],
    "rules": null,            // main-panel: "CLAUDE.md#rules-that-will-bite-you"
    "docMap": null,           // main-panel: "CLAUDE.md#where-the-truth-lives"
    "verifyCommand": null,    // nalekci-pulse: "npm run verify"
    "minScore": 80,
    "language": "cs"
  },
  "sinks": { "runRecord": true, "prComment": false, "githubProject": null }
}
```

Pro main-panel je to tentýž soubor s vyplněnými `rules`, `docMap`, `verifyCommand` a `githubProject`.

> Oponentní review tvrdilo, že se formát packu má **objevit z bolesti**, ne navrhnout — proti původnímu návrhu 12sekčního manifestu. Objevil se — rozdělením jednoho reálného skillu, za hodinu, ne až u třetího packu. Pravidlo přitom platí dál: **další pole se do manifestu přidá, až ho vyžádá konkrétní pack, ne až ho vymyslíš.**

---

## 2.2 Kam se zapisují nálezy — klíčová inverze

**Dnes se nezapisují nikam.** Výstupem skillu je komentář na PR. Napříč deseti PR, ze kterých pocházejí nálezy v Projectu:

```
PR #460  komentářů=1  s markerem pr-review-graph=1   ← jediný
PR #461  komentářů=0  s markerem=0                    ← přitom 9 nálezů v Projectu
PR #450 #447 #446 #442 #438 #419   komentářů=0
PR #434 #432 #423                  komentáře jsou, marker žádný
```

**36 nálezů je v Projectu, ale skill je tam nezapsal — přepsal je člověk.** To je chybějící článek řetězce a zároveň to nejcennější, co Agency udělá jako první.

Návrh to obrací:

```
<projekt>/.agency/runs/<run-id>/         ← COMMITUJE SE, toto je pravda
  run.json        # pack+verze, PR, headRefOid, provider, začátek/konec, výsledek
  findings.json   # finding.v1[], validované schématem
  evidence/       # detect-changes, impact, diff, výstupy dimenzí

~/.agency/agency.db                       ← NEcommituje se, kdykoli přestavitelné
  index nálezů napříč projekty, dedup fingerprinty, triage fronta, metriky
```

`findings.json` je pravda. **PR komentář, GitHub Project i `agency.db` jsou z něj odvozené** — volitelné a opakovatelné. Když sink selže nebo je vypnutý, nález se neztratí; dnes se ztrácí.

**Proč zrovna takhle rozdělené** (rozhodnuto 31. 8.): `agency.db` potřebuješ na rychlý dedup přes stovky nálezů, na cross-project dotazy a na triage frontu — to v JSON souborech nechceš psát ručně. Ale nesmí být zdrojem pravdy: `.code-review-graph/graph.db` má ve svém `.gitignore` doslova `*` s poznámkou *„do not commit database files"* a příkaz `build` ho kdykoli přestaví od nuly. Kdyby nálezy žily ve stejné třídě úložiště, jeden rebuild je smaže. Proto platí pravidlo:

> **`agency.db` musí jít smazat a přestavět z `.agency/runs/**` jedním příkazem** (`agency reindex`). Když to neplatí, je to bug, ne feature.

Vedlejší efekt, který stojí za to: nálezy jsou v repu, takže se dají reviewovat v PR a přežijí re-clone.

Idempotence je už vyřešená: skill používá marker `<!-- pr-review-graph:<headRefOid> -->`. Run record se klíčuje stejně — `(repo, PR, headRefOid)`. Stejný commit dvakrát nevyrobí duplikát.

> **Nemusíš pack model vymýšlet. Musíš QA agenta přetvarovat do tvaru, který `pr-review-graph` už má.**
> To je imitace, ne design. A `agency add <pack>` je v podstatě „to kopírování, ale správně, s verzí, doctorem a stavem".

---

## 2.3 Jak se pack instaluje a aktualizuje

Bez tohohle je krok 2 improvizace — celý stojí na instalaci do cizích projektů.

**Co se instaluje** (a co ne):

| | Kam | Vlastní |
|---|---|---|
| Metoda — soubor skillu | `<projekt>/.claude/skills/<pack>/` | **nástroj** |
| Šablona konfigurace | `<projekt>/.agency/<pack>.json` | **projekt**, po prvním zápisu se nepřepisuje |
| Evidence instalace | `<projekt>/.agency/installed.json` | nástroj |
| Stav projektu — paměť, nálezy, coverage | vzniká v projektu za běhu | projekt, nikdy se neinstaluje |

**Odkud se pack bere:** je **zabalený uvnitř `agency`** jako package data. `agency add review-graph` ho zkopíruje do projektu, žádná síť, jedna verze pro všechny projekty. Upgrade nástroje = `uv tool upgrade agency`. Pro vývoj packu existuje `agency add review-graph --from ./packs/review-graph`, aby se editace projevila bez reinstalace balíčku.

**Co se stane při upgradu — managed s hash pojistkou:**

Při instalaci se do `installed.json` uloží verze packu a hash každého nainstalovaného souboru. Při `agency update`:

- **hash sedí** → soubor se přepíše novou verzí, bez ptaní
- **hash nesedí** → **nepřepisuje se**, upgrade to nahlásí a ukáže diff

Konfigurace (`<pack>.json`) se nepřepisuje nikdy; při novém povinném poli to `doctor` ohlásí jako chybějící, ne že by ho domyslel.

> **Ruční úprava packu je diagnóza, ne problém.** Když sáhneš do souboru skillu, znamená to, že ti v konfiguraci chybí pole. Hash pojistka ti to řekne nahlas místo toho, aby změnu tiše přepsala — a je to přesně ten signál pro pravidlo ze §2.1: *další pole se do manifestu přidá, až ho vyžádá konkrétní pack.*

**Jedna věc, kterou to odhaluje pro krok 2:** `main-panel` má dnes v skillu **zašitá projektová pravidla** (dimenze „repo-rule compliance" — Supabase fence, RLS, migrace). Ta se musí vystěhovat do `review-graph.json` **dřív**, než na main-panel poprvé pustíš `agency add`, jinak je první upgrade buď přepíše, nebo se o ně navždy zasekne na hash pojistce.

---

## 3. Co tvoje omezení odstraňují (a jedno, které přidávají)

**Attended + subscription only ruší:**
- celou tabulku auth stavů → stačí `ok` / `needs_login`
- ukládání credentials → provider CLI si je drží sám, Agency se jich nedotkne
- scheduler, fronty, retry politiku
- riziko porušení podmínek dodavatele z velké části — attended wrapper je legitimní model, viz §3.3
- multi-user server, RBAC, OIDC, Postgres

**Self-hosted na vlastní VPS ruší:** tenanci, izolaci runnerů, billing, sdílené credentials.

**Jedno omezení to ale přidává, a musí být v kódu, ne ve slibu:**

> **„Attended" musí být vlastnost systému, ne úmysl.**
>
> Trigger je od cronu vzdálený jeden zapomenutý `--watch` přes noc. Konkrétní mechanismus: CLI drží **heartbeat živé session**. Každý běh si ho na startu ověří. Když je starší než X minut, běh se **nespustí — zařadí se a upozorní**. ~30 řádků, a hranice attended/unattended přestane být na tvojí paměti.
>
> Bonus: chrání i před nechtěným spálením kvóty.

**K týmovému sdílení stavu:** sdílet *artefakty a rozhodnutí* na tvojí VPS není multi-user SaaS, je to sdílená kartotéka. Hranice, která to drží čisté: **sdílí se stav, nikdy ne credentials ani běhy.** Každý si spouští svoje, na svém přihlášení.

---

## 3.1 Co už `code-review-graph` umí — a co proto Agency nesmí stavět znovu

Ověřeno 31. 8. v `main-panelu`. Tohle mění rozsah kroků 1–3 víc než cokoli jiného:

| Co existuje | Co to znamená pro Agency |
|---|---|
| **Python**, v2.3.7, instalované přes `uv` do `~/.local/bin` | jádro Agency v Pythonu může `code_review_graph` **importovat přímo** — žádný subprocess, žádný parsing stdout |
| Přístup k DB přes **stdlib `sqlite3`**, žádné native rozšíření | žádné ABI riziko, žádná kompilace, `agency.db` může jet na tomtéž |
| `serve` = **MCP server**, stdio nebo Streamable HTTP na `127.0.0.1:5555`, s `--tools` filtrem | transportní vrstva pro extension **už je hotová**. Nestaví se žádné vlastní RPC. |
| `register` / `unregister` / `repos` — multi-repo registry | `agency status` čte tenhle registr, nezakládá druhý paralelní seznam projektů |
| `crg-daemon` — multi-repo watch daemon (`start/stop/status/add/remove`) | krok 6 (watch trigger) je z velké části konfigurace existujícího daemona, ne nový kód |
| `visualize` — interaktivní HTML vizualizace grafu | kandidát na obsah webview panelu; nekreslí se vlastní graf |
| `detect-changes`, `impact`, `search`, `flows`, `architecture`, `dead-code` | dimenze packu volají tohle, nepočítají si vlastní blast radius |

**Praktický důsledek:** velká část toho, co jsem v původním plánu psal jako „krok 3 — kontrakt a store", je ve skutečnosti tenká vrstva nad hotovým nástrojem. Agency přidává **nálezy, rozhodnutí a packy** — ne grafovou infrastrukturu.

---

## 3.2 Jazyk jádra — vědomě dočasné rozhodnutí

Jádro (packs, běhy, nálezy, dedup, triage) i `agency` CLI jsou **v Pythonu**, instalovatelné přes `uv` stejně jako `code-review-graph`. Důvod je rychlost experimentu, ne architektonická čistota: sdílí runtime s CRG, může ho importovat, `sqlite3` je ve stdlib a nulová konfigurace balíčkování.

Extension a webview jsou nutně TypeScript. Repo tedy bude dvojjazyčné a to je v pořádku.

**Rozhodnutí se počítá s tím, že se přepíše.** Aby ten přepis stál dny a ne měsíc, platí jedna hranice:

> **Přes hranici Python ↔ extension smí téct jen JSON podle `run.v1` / `finding.v1`.** Žádné Python typy, žádný pickle, žádné implicitní schéma odvozené z toho, co zrovna `json.dumps` vyrobil. Extension nikdy neví, v čem je jádro napsané.

Když tohle platí, přepis jádra do TS (nebo do čehokoli) je výměna procesu za proces, ne přepis produktu. Když to poruší jediné místo, přepis je migrace.

---

## 3.3 Trigger určuje credential — a test, který rozhoduje o životaschopnosti

Attended-only je přijaté zadání, takže tohle pravidlo dnes nemá druhou větev. Ale musí být v systému zapsané **od začátku**, protože ta druhá větev jednou přijde a bez pravidla se tam propašuje potichu:

> **Typ triggeru určuje typ credentialu.**
>
> - **Attended** (sedíš u toho, ruční spuštění nebo watch) → **subscription**. Nízké riziko, plná rychlost.
> - **Unattended** (cron, webhook, CI, noční běh) → **API klíč / SDK kredit**, s rozpočtem a tvrdým stropem.

Důvod není jen technický. Anthropic omezuje použití subscription OAuth v aplikacích třetích stran a od 15. 6. 2026 se programatické `claude -p` / Agent SDK běhy odečítají z odděleného měsíčního Agent SDK kreditu. Argument *„je to jen obal terminálu"* je pravdivý pro interaktivní obsluhovaný provoz a podstatně slabší pro cron běžící, když spíš. To nejsou stejné produkty a nemají stejný rizikový profil — heartbeat ze §3 je mechanismus, tohle je pravidlo, které ten mechanismus vynucuje.

**A z toho plyne test, který rozhoduje o smyslu celého projektu:**

> **Je systém stále výhodný, když každé LLM volání stojí plnou API cenu?**
>
> Když **ano** → stavěj. Hodnotu nese deterministická vrstva (graf, fingerprint dedup, evidence gate, coverage mapa) a model je vyměnitelná komponenta.
> Když **ne** → stavíš obal kolem slevy, a ta sleva ti nepatří.

Test dnes **nejde zodpovědět**, protože žádný běh nezaznamenává cost ([`baseline.md`](baseline.md) §7.3). Proto je záznam ceny součástí kroku 3, ne „až bude čas".

---

## 3.4 Princip, který drží celý plán pohromadě

> **Páteří produktu není runtime. Páteří je kontrakt: `run.v1` + `finding.v1`.**
> Všechno ostatní — CLI, jádro, extension, packy, sinky — jsou vyměnitelní klienti toho kontraktu.

Kdo vlastní kontrakt, vlastní produkt. Kdo vlastní jen UI, staví další obal kolem cizího nástroje.

Tenhle princip je zároveň důvod, proč je volba Pythonu v §3.2 bezpečná: jazyk jádra je implementační detail *pod* kontraktem. A je to důvod, proč se kontrakt v kroku 3 píše formálně, ne „nějak se to ustálí".

**Jedna nedořešená věc, kterou tenhle princip odhaluje.** `veriflow-architecture` obsahuje `packages/agent-session` (spawn providera, streamované sessions, contracts), `packages/workspace` (worktree resolver) a `packages/store` — tedy věci, které krok 1 bude potřebovat. Oponentní review na to mělo tvrdé pravidlo: *„pokud se přistihneš, že píšeš provider adapter, run store nebo event stream — zastav se, ten soubor existuje"*. To pravidlo bylo psané pro TypeScriptové jádro. **S Pythonem ho nejde dodržet doslova** — TS balíček se z Pythonu nedá importovat. Zbývají tři možnosti a rozhodnout se musí v kroku 1, ne mlčky:

1. spustit provider přes `subprocess` a `agent-session` vůbec nepoužít (nejjednodušší, duplikuje ~200 řádků),
2. volat `veriflow-architecture` jako samostatný proces s JSON rozhraním (drží reuse, přidává hop),
3. přijmout duplikaci vědomě a označit ji jako dluh k zaplacení při případném přepisu jádra do TS.

Viz otevřená otázka §8.5.

---

## 3.5 Layout repozitáře

První rozhodnutí kroku 1 — buď vědomé, nebo se udělá samo tím, že něco vytvoříš.

```
veriflow-agency/
  packages/
    core/             pyproject.toml
                      src/agency/          ← jádro + CLI, konzolový skript `agency`
    extension/        package.json
                      src/                 ← TreeView, webview, CommentController
   (core-ts/)                              ← sem se jednou přesune jádro, viz §3.2
  packs/
    review-graph/
    qa/
  schemas/            run.v1.json
                      finding.v1.json
  docs/

uv tool install ./packages/core
cd packages/extension && npm run package     # → VSIX
```

**`schemas/` je jediný zdroj pravdy pro kontrakt.** Ani jedna strana si schéma nedrží vlastní:

- **Python** je načítá za běhu a validuje přes `jsonschema` — každý zápis `findings.json` jím projde
- **TypeScript** si z nich při buildu generuje typy (`json-schema-to-typescript`)

Tím se hranice ze §3.2 hlídá sama. Když někdo přidá pole jen na jedné straně, druhá se rozbije při buildu nebo při validaci — ne až v provozu na tvaru dat, který nikdo nečekal.

**Proč `packages/`, a ne ploché repo s `pyproject.toml` v kořeni.** §3.2 počítá s tím, že se jádro jednou přepíše do TypeScriptu. V tomhle layoutu je ten přepis mechanický — přibude `packages/core-ts` vedle stávajícího, přepne se, starý se smaže. V plochém layoutu je to přestavba kořene repozitáře. Cena za tu volnost je jedna úroveň zanoření navíc.

---

## 4. Kroky

Řazené podle poměru *co se dozvím / co to stojí*. Každý má pozorovatelné „hotovo".

### Krok 0 — Stav `Rejected` v Projectu · **½ dne**

Z `baseline.md` §7.1–7.2. Přidat `Rejected` + `Reason`, zpětně doplnit 2–3 známé vadné nálezy z `known-regressions.md`.

**Hotovo, když:** precision má poprvé nenulový jmenovatel.
**Proč první:** je to 45 minut a bez toho zůstaneš měřicky slepý napořád — každý další krok ten slepý bod zvětší.

---

### Krok 1 — Vertikální řez na `main-panelu` · **3 dny** · *nejdůležitější krok plánu*

Jeden tenký průchod celým stackem. Ne kompletní CLI, ne kompletní extension — **jedna cesta od začátku do konce**:

> `agency run review-graph` na `main-panelu` → nálezy se zapíšou do `.agency/runs/<id>/findings.json` → zaindexují do `agency.db` → sidebar v VS Code je ukáže ve stromu → klik otevře `file:line` → Accept/Reject se zapíše zpátky do run recordu

Co v tom kroku **je**:

1. `git init` v `veriflow-agency`, layout podle §3.5, Python balíček, `agency` konzolový skript přes `uv`
2. rozpad `pr-review-graph` skillu podle §2.1 na jádro / konfiguraci / obsah projektu
3. `run.json` + `findings.json` podle §2.2 — primární výstup, dnes neexistuje. **Včetně kotvy nálezu (krok 3, bod 4)** — ta musí být v datech od prvního zápisu, protože doplnit ji zpětně jde jen zahozením starých nálezů.
4. `agency.db` jako index + `agency reindex`, který ho postaví z `.agency/runs/**`
5. VS Code extension, minimální: activity bar ikona, **jeden** TreeView (nálezy posledního běhu), proklik na `file:line`, tři příkazy Accept / Reject / Defer

Co v tom kroku **není**: dedup, druhý projekt, druhý pack, `doctor`, webview panel, `CommentController`, GitHub Project export, retrospektivní audit. Všechno tohle přijde, ale ne teď.

**Hotovo, když:** proběhne celý řetězec bez ručního zásahu a rozhodnutí přežije restart VS Code.

**Proč právě takhle a proč `main-panel`:** `main-panel` už má postavený graf (9 819 uzlů, 169 MB), má skill i historii běhů — nulová příprava. A ten řez odhalí přesně ty mismatche, kvůli kterým se plán 31. 8. přepisoval: jaký tvar musí mít nález, aby šel zobrazit; co potřebuje evidence pro proklik; jak vypadá idempotentní zápis rozhodnutí; co se stane při druhém běhu nad stejným commitem. Odhalí je v momentě, kdy oprava stojí hodinu, ne přepis schématu a migraci.

---

### Krok 2 — Pack #1 dotažený, čtyři projekty · **1½–2 dny**

Teď teprve zbytek CLI:

```
agency init          # rozpozná projekt: git remote, framework, testy, existující skills
agency add review-graph
agency doctor        # ověří gh auth, code-review-graph --version, stav grafu — PŘED během
agency run review-graph
agency status        # čte registr z `code-review-graph repos`, viz §3.1
```

Instalace a upgrade packu podle §2.3 — zabalený v nástroji, managed s hash pojistkou.

> **Předpoklad, který se musí splnit dřív, než na `main-panel` poprvé pustíš `agency add`:** vystěhovat zašitá projektová pravidla ze skillu do `review-graph.json` (§2.1, dimenze „repo-rule compliance"). Jinak je první upgrade buď přepíše, nebo se o ně natrvalo zasekne na hash pojistce. Je to půlhodina a patří na začátek kroku 2, ne na jeho konec.

Plus dvě věci, které bez druhého projektu nejde ověřit:

- **správa grafu**: chybí → `build`, zastaralý → `update` (main-panel je zastaralý *právě teď*, kvesteros o 25 dní)
- **režim retrospektivního auditu** — `kvesteros-platform` má za celou dobu **jediný PR** (mergnutý). Bez „prověř poslední mergnuté PR" tam pack nemá co dělat. Není to funkce navíc: přesně tak vzniklo 14 nálezů v baseline (`zdroj: PR #… · retrospektivní audit`).

Čtyři projekty, **záměrně heterogenní**:

| Projekt | Owner | Graf | CI příkaz | Co to prověří |
|---|---|---|---|---|
| `main-panel` | Chci-na-lekci | ✅ 9 819 uzlů, **zastaralý** | `npm run verify` | plná konfigurace, GH Project 1, obsluha zastaralého grafu |
| `nalekci-pulse` | Chci-na-lekci | ❌ chybí | `npm run verify` | `build` grafu od nuly |
| `kvesteros-platform` | **deverjak** | ✅ 5 784 uzlů, **25 dní starý** | **žádný** (bez root `package.json`) | jiný owner, žádný GH Project, chybějící CI filtr, **jediný PR** → retrospektivní režim |
| `veriflow-agency` | (nový git) | ❌ | žádný | prázdný repo, dogfooding |

Každý záměrně láme jinou část konfigurace ze §2.1. Když projdou všechny čtyři, manifest je ověřený.

**Hotovo, když:** `agency status` ukáže 4 projekty, `doctor` je zelený všude a **nikde jsi needitoval soubor ručně**.

**Tady se láme UX.** Laťka: *nový projekt od nuly k prvnímu běhu pod 10 minut bez čtení dokumentace.* Když `kvesteros-platform` (jiný owner, nula testů) projde initem bez ruční editace, UX je hotové.

---

### Krok 3 — Kontrakt, kotva, dedup, metriky, export · **2½ dne**

`run.v1` a `finding.v1` jako formální schéma (JSON Schema, validované na obou stranách hranice ze §3.2), dedup přes existující fingerprint, a odvozené sinky.

```
agency findings          # napříč všemi projekty
agency metrics           # precision, dedup ratio, stáří, shoda severity
agency export github     # jednosměrný push do GitHub Projectu
```

Pět věcí, které do kontraktu patří hned a jinde by se doplňovaly draho:

**1. Lifecycle nálezu má čtyři stavy, ne sedm.**

```
candidate → duplicate | accepted → published
```

Čtyři, protože dedup opravdu potřebuješ. Původní návrh měl sedm; zbylé tři byly odstíny téhož a v datech pro ně není opora. Stejná úspornost platí pro auth: `ok | needs_login`, zbytek jsou jen odstíny „nespouštěj".

**2. Deterministická brána před ingestem.**

Nález, který nemá **citovanou evidenci** a **`file:line` uvnitř indexovaného modulu**, se nestane kandidátem — zahodí se s důvodem do run recordu. Není to filtr kvality textu, je to schéma: `finding.v1` prostě takový nález nevaliduje. Tohle je nejlevnější existující obrana proti tomu, aby se zvýšený objem propsal do zvýšeného odpadu, a opírá se o graf, který už na všech projektech stojí (§3.1).

**3. Cost per run.**

Provider, model, tokeny, doba běhu, počet dimenzí — do `run.json`. Bez toho nejde zodpovědět test ze §3.3 („je to výhodné i při plné API ceně?") ani druhé kill criterium ze §6. Je to pár polí, ale musí vzniknout dřív, než se nasbírá historie běhů, do které je zpětně nedoplníš.

**4. Kotva nálezu — čtyři vrstvy, ne číslo řádku.**

Nález najdeš na commitu `abc123` a čteš ho o tři týdny později z pracovní kopie, která je o 30 commitů dál. Číslo řádku už neplatí a **nijak to nepozná** — komentář se posadí na nevinný kód, ty ho zamítneš a tím si rozbiješ tu jedinou metriku, kvůli které vznikl [`baseline.md`](baseline.md). Proto kotva:

```jsonc
"anchor": {
  "file":   "src/auth.ts",
  "line":   142,
  "commit": "abc123…",                    // 1. přesná shoda, když commit == HEAD
  "snippet": "  const x = await getUser(id)",   // 2. text řádku — najde posunutý kód
  "symbol": { "name": "UserService.getUser", "range": [128, 171] },  // 3. dotaz do grafu
  "body":   "…celé tělo funkce v den analýzy, strop 8 kB…"           // 4. záchranná síť
}
```

Rozlišuje se shora dolů, zastaví se na první vrstvě, která uspěje. Selže-li všechno, vlákno se posadí na řádek 1 s poznámkou „původní umístění zaniklo" — **degraduje se, neztratí se.**

Vrstvu 3 dostaneš z `code-review-graph` zadarmo (symbol i rozsah řádků pro `file:line`) a je to ta zajímavá: kotva na symbol přežije refaktor a přesun bloku, číslo řádku ne. Vrstva 4 řeší případ, kdy commit v lokálním klonu už není — squash-merge se smazanou větví je na GitHubu default. `git fetch origin <sha>` obvykle ještě pomůže (GitHub drží `refs/pull/<n>/head`), ale spoléhat se na to nedá. Nálezů budou stovky, ne miliony; 8 kB na nález je levná pojistka.

**5. Test driftu při ingestu — automatický předtřídič.**

Když znáš commit i rozsah symbolu, jde se levně zeptat, jestli na ten kód od té doby někdo sáhl:

```
git diff abc123..HEAD -- src/auth.ts     # dotkly se hunky řádků 128–171?
```

- **nedotkly** → nález platí doslova, kód je nezměněný
- **dotkly** → možná už opravené; při triage ukázat ten diff jako první

Deterministické, bez jediného LLM volání, a řeže přesně to úzké hrdlo, které `baseline.md` označil za největší ztrátu hodnoty v systému: ze 47 čekajících položek to oddělí živé od pravděpodobně vyřešených ještě předtím, než jedinou otevřeš.

**Jednosměrnost exportu je rozhodnutí, ne zjednodušení** (31. 8.): pravda o rozhodnutí je lokální run record, GitHub Project je publikační cíl pro stakeholdery a měření precision. Žádný zpětný sync, žádné mapování stavů oběma směry, žádné konflikty. Kdyby někdo změnil stav přímo v Projectu, další export ho přepíše — a to je zamýšlené chování, ne bug.

**Hotovo, když:** metriky, které jsem v `baseline.md` počítal ručně, vypadnou z jednoho příkazu, a nález se do Projectu dostane bez toho, aby ho člověk přepsal.

**Poznámka ke schématu:** kontrakt piš až teď, odvozený z toho, co kroky 1–2 skutečně potřebovaly. Ne dopředu.

---

### Krok 4 — Extension v2 a rozhýbaná triage fronta · **2 dny**

Teprve teď se z minimálního TreeView stává použitelné UI. Detaily rozvržení v [`ui-surface-decision.md`](ui-surface-decision.md) §3.

- **`CommentController`** — nálezy jako inline review komentáře u řádku, s akcemi Accept / Reject / Defer. Tohle je nosná feature celého UI rozhodnutí; pokud se ukáže, že nejde použít nad jiným commitem než working tree (viz §8 otázka 2), je to jediné místo, kde se plán mění.
- **`WebviewPanel`** v editoru — detail nálezu s evidencí, dedup porovnání dvou nálezů vedle sebe, timeline běhu, portfolio přehled přes projekty
- **Pohled „kód v den analýzy"** — `TextDocumentContentProvider` pro scheme `agency:`, plněný z `git show <commit>:<path>` a oříznutý na rozsah symbolu z kotvy (krok 3, bod 4). Dvě použití z jedné implementace: read-only vlákna pro retrospektivní audit a `vscode.diff` proti pracovní kopii, když test driftu hlásí změnu. Fallback na `anchor.body`, když commit v klonu není.
- **další TreeViews** — projekty a specialisté, běhy, triage fronta s badge počtu
- **`DiagnosticCollection`** — **default vypnuto**. Při 35+ nálezech na běh by Problems panel přestal být použitelný pro cokoli jiného.
- **distribuce: VSIX**, žádný marketplace. Instaluje se ručně, publikování je zbytečná režie, dokud jsi uživatel ty a případně teammates.

Prokázaná zácpa, kterou to má rozhýbat: **47 položek `Observed`, 0 promoce z lidských zdrojů** (baseline §2).

**Hotovo, když:** 47 `Observed` klesne pod 15 a `agency metrics` poprvé ukáže skutečnou precision.

---

### Krok 5 — QA jako pack #2 · **2 dny · nejtěžší krok**

Rozdělit metodu od stavu:

- `repoRoot` → **cílový projekt**, ne repo agenta
- `qa.config.json` → do cílového projektu (`.agency/qa.json`)
- `memory/`, `references/` → do cílového projektu jako jeho paměť
- `skills/qa-session/SKILL.md` → odstranit nalekci specifika (zbylých 5 skills je už generických)
- sourozenecké cesty `../main-panel`, `../nalekci-po-agent` → zrušit, řeší je projektový kontext
- **Git PR ceremonii u paměti zahodit** — branch → PR → merge → memory-sync branch → PR → merge je pro zápis paměti absurdní režie. Zápis do projektového stavu + commit, bez PR.

**Hotovo, když:** QA běží přes Agency na `main-panel` **a** existuje druhá konfigurace pro `nalekci-pulse` (i kdyby úzce zaměřená), a jeho nálezy se v extension chovají stejně jako nálezy z review-graph.

**Proč až teď:** pack formát se tímhle krokem **validuje nebo vyvrátí**. Kdyby byl QA pack #1, navrhl bys formát podle jednoho příkladu. Takhle ho ověřuješ druhým, výrazně odlišným tvarem — a to je jediný způsob, jak zjistit, že je špatně. Zároveň se tím ověří, že `finding.v1` není přišitý na jeden pack.

---

### Krok 6 — Triggery, attended-only · **½–1 den**

Tři spouštěče, všechny za heartbeatem živé session (§3):

- ruční — `agency run <pack>` nebo příkaz z extension
- **watch** — změna větve / nový commit / otevřený PR, když sedíš u stroje. Z velké části konfigurace existujícího `crg-daemon` (§3.1), ne nový kód.
- **post-merge** — lokální git hook

Žádný cron. Žádný webhook zvenčí. Když je heartbeat starý, běh se **zařadí, neproběhne**.

> Extension host přežívá jen dokud je okno otevřené — což je pro attended model přesně správně a je to vlastně druhá, nezávislá pojistka téhož pravidla.

---

## 5. Co v této fázi vědomě NEDĚLÁM

| Odloženo | Spouštěč pro zařazení |
|---|---|
| **Týmový sync stavu** | až budeš mít druhého člověka **a** kroky 1–5 poběží |
| **Desktopová aplikace** | **zrušeno**, ne odloženo — viz [`ui-surface-decision.md`](ui-surface-decision.md) |
| Publikování extension na marketplace | až ho bude instalovat někdo, komu nemůžeš poslat VSIX |
| Podpora JetBrains | až se ozve; řeší se druhým klientem nad stejným JSON kontraktem (§3.2) |
| Server / daemon / SSE | až bude druhý stroj |
| PO agent jako plný pack | až triage z kroku 4 ukáže, kde přesně chybí úsudek |
| CEO agent | nahrazeno deterministickým digestem z `agency metrics` |
| Pack registry, podpisy, ACP | až u třetího packu, ne dřív |
| Unattended větev, API pricing | mimo zadání |

### Čtyři rozhodnutí o úložišti, která udělej teď, aby byl sync později levný

Sync neřešíš, ale nesmíš si ho zavřít:

1. **Append-only události**, ne mutovaný stav. Sloučení dvou historií je pak triviální.
2. **ULID/UUID**, nikdy autoincrement. Bez toho vzniknou při slučování kolize ID.
3. **Žádné absolutní lokální cesty v záznamech.** Vše relativně ke kořeni projektu. (`code-review-graph` má ve svém `.gitignore` výslovnou poznámku, že `graph.db` obsahuje absolutní cesty — proto se necommituje. Run recordy se commitovat mají, takže si to dovolit nemůžou.)
4. **`agency.db` je vždy zahoditelný.** Viz §2.2. Jakmile v něm vznikne jediný údaj, který není v `.agency/runs/**`, sync i deletion-safe persistence padají zároveň.

Tohle jsou čtyři konvence, ne práce navíc. Když je porušíš, sync později znamená migraci.

---

## 6. Kdy to zabít

Sepsáno předem, dokud k projektu nejsi upsaný. Vyhodnocení proti stavu k 30. 8. je v [`baseline.md`](baseline.md) §6 — **žádné kritérium tehdy nebylo splněno**, ale dvě z nich se nedala vyhodnotit vůbec, a přesně to opravují krok 0 a krok 3.

| Kritérium | Co udělat, když nastane | Stav k 30. 8. |
|---|---|---|
| Po 4 týdnech běhů je **precision < 25 %** | Přestat stavět runtime a opravit agenta — evidence requirements, prompt, scope. Platforma nad špatným generátorem je zesilovač šumu. | nelze vyhodnotit → řeší krok 0; proxy (shoda severity 6/6, 80 % dedup, sebekorekce) všechny příznivé |
| **Cena za užitečný nález při plné API ceně > cena stejného nálezu od člověka** | Ekonomika stojí jen na subscription arbitráži. To není základ produktu. | neměřeno → řeší krok 3 |
| Po 3 měsících jsi **jediný uživatel a nespouštíš to týdně** | Je to koníček. Legitimní — ale okamžitě přestat platit platformní daň (registry, RBAC, sync, packaging) a nechat to jako CLI + extension. | neaplikovatelné, projekt je starý dny |
| Přistihneš se, že **píšeš třetí provider adaptér dřív, než máš třetí pack** | Stavíš pro imaginární ekosystém. | prošlo — 2 providery, 2 packy |

**Poznámka k platformní dani.** Tohle je zatím osobní nástroj, ne produkt. Rozdíl není v ambici, ale v účtu: produkt platí za pack registry, podpisy, RBAC, audit log a víceuživatelský sync — a nic z toho nepotřebuje uživatel č. 1. Není nutné teď rozhodnout, který z těch dvou to je. Je nutné **nepředstírat, že je to rozhodnuté**, a neplatit tu daň, dokud rozhodnuté není.

---

## 7. Souhrn

| Krok | Doba | Výstup | Co se dozvíš |
|---|---|---|---|
| 0 | ½ d | stav `Rejected` | precision je poprvé měřitelná |
| 1 | **3 d** | **vertikální řez** CLI → store → sidebar → rozhodnutí | sedí tvar dat na to, co UI potřebuje? |
| 2 | 1½–2 d | pack #1 dotažený, 4 projekty, `doctor` | funguje instalace packu do cizího projektu? obstojí UX? |
| 3 | 2½ d | kontrakt, 4stavový lifecycle, kotva, evidence gate, test driftu, cost per run, metriky, export do GH | jsou nálezy dohledatelné a dohledané i po měsíci? kolik běh stojí? |
| 4 | 2 d | extension v2, triage fronta | klesne 47 `Observed` pod 15? jaká je **skutečná** precision? |
| 5 | 2 d | QA jako pack #2 | je pack formát správný, nebo ho druhý tvar rozbil? |
| 6 | ½–1 d | attended triggery | drží hranice attended v kódu? |

**Součet: ~12–14 dní agentního vývoje** k bodu, kde máš čtyři projekty pod jedním nástrojem, dva packy, měřitelnou kvalitu nálezů, známou cenu za běh, rozhýbanou triage frontu a UI, ve kterém se ta práce dá skutečně dělat.

**Nejrychlejší návratnost je v kroku 1**, ne až na konci: run record ukončí ruční přepisování nálezů do Projectu, které dnes stojí za 35 ze 36 položek (§2.2).

**První Definition of Done** (konec kroku 2):

> Do `kvesteros-platform` — projektu s jiným ownerem, bez testů a bez jakékoli agentní historie — nainstaluješ jedním příkazem review-graph pack, proběhne attended běh na tvém subscription, nálezy skončí v jednom dohledatelném úložišti vedle nálezů z ostatních tří projektů, otevřou se ti v sidebaru VS Code s proklikem na kód, a `agency doctor` je zelený, aniž bys editoval jediný soubor ručně.

Když tohle funguje, „nový nápad → nové repo" přestane být problém — protože marginální cena nového projektu klesne na jeden příkaz.

---

## 8. Otevřené otázky

**Technické — zodpoví se během kroků 1–2:**

1. ~~Jede `code-review-graph` na SQLite a přes jaký driver?~~ **Zodpovězeno 31. 8.** — Python, stdlib `sqlite3`, v2.3.7, bez native rozšíření. Viz §3.1.
2. Je `CommentController` použitelný nad nálezy z běhu proti **jinému commitu**, než je aktuální working tree? Pravděpodobně ano přes vlastní `CommentThread` na konkrétní `Uri`, ale chce to ověřit prototypem **v kroku 1**, ne až v kroku 4 — je to nosná feature UI rozhodnutí a její selhání je jediná věc, která by plán vrátila k webview-only variantě.
3. Unese `agency.db` jako index nad `.agency/runs/**` i retrospektivní audit, kde jeden běh vyprodukuje desítky nálezů nad starými commity? Zjistí se v kroku 2 na `kvesteros-platform`.
4. Kolik nálezů týdně unese tvoje triage kapacita? **To je skutečný strop propustnosti systému, ne rychlost agenta.** Změří se v kroku 4 při rozpouštění fronty 47 → pod 15.
5. Jak naložit s `veriflow-architecture/packages/{agent-session,workspace,store}`, které Python jádro nemůže importovat? Tři varianty jsou v §3.4, rozhodnout v kroku 1.

**Produktové — nezodpoví se kódem:**

6. Kolik stojí jeden běh při plné API ceně? Bez toho neznáš ekonomiku svého produktu ani nemůžeš vyhodnotit druhé kill criterium (§6). Instrumentace je v kroku 3, číslo až po pár bězích.
7. Existuje reálný druhý uživatel, nebo je to zatím hypotéza? Odpověď mění polovinu §5 — bez druhého uživatele je celý sloupec „odloženo" trvalý, ne dočasný.
8. Je `nalekci-po-agent` ochoten stát se kódem? Když ne, pack #3 neexistuje a projekt končí u dvou packů s dobrou triage — což je pořád dobrý výsledek, jen jiný produkt, než se dnes plánuje.
