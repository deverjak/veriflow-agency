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
| Triage až v kroku 4 | **Sdílené úložiště rozhodnutí už v kroku 3** | triage musí umět i agent, takže rozhodnutí je operace nad úložištěm, ne příkaz UI — a to mění tvar kontraktu |
| Model jako globální nastavení | **`agent.model` v konfiguraci packu**, zapsaný do run recordu | §3.3b — recenze je čtení, ne psaní; a bez záznamu modelu se precision nedá porovnat mezi modely |
| `CommentController` jako riziko | **Ověřeno spikem, riziko zavřené** | §3.6 — a odhalilo to pět chyb v návrhu, které by jinak vyšly najevo až u kroku 4 |

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

**A ještě jedno místo, na které se snadno zapomene: worktree.** Recenze neběží v projektu, ale v jednorázovém worktree na hlavičce PR — a ten je *čistý checkout*, vidí jen commitnuté soubory. Skill packu commitnutý není a být nemá (metoda patří nástroji, ne recenzovanému repu), takže se v něm metoda vůbec nenajde: `Skill(agency-review-graph)` → *Unknown skill*, agent začne hádat a běh se rozpadne dřív, než přečte `context.json`.

Proto `agency run` po založení worktree **přenese nainstalované soubory packu dovnitř** — z pracovní kopie projektu, ne z packu, aby do worktree šlo přesně to, co je nainstalované včetně případné blokované ruční úpravy. Zkopírované soubory se zároveň zapíšou do worktree-lokálního `info/exclude`, aby se netvářily jako změna, kterou přinesl PR; nález *„PR přidal skill"* by byl artefakt nástroje.

Ze stejné rodiny je druhá past: `findings.json` se zapisuje do `RUN_DIR`, který leží **v projektu, tedy mimo worktree**. Agent se proto ptá na zápis ven z pracovního adresáře — attended to přežije, ale je to překážka v každém běhu. Řeší to `--add-dir RUN_DIR` v `launch` argv (§3.3b).

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

## 3.3b Model je vlastnost úkolu, ne uživatele

Výchozí model si člověk volí pro to, co dělá nejčastěji — u tebe kódování, tedy ten nejsilnější. Recenze je ale jiná práce: čtení, klasifikace a zápis JSONu, ne psaní kódu. Nutit ji do stejné volby znamená platit psací sazbu za čtecí úkol.

Proto volba agenta patří **do projektu**, ne do globálního nastavení editoru — a od 31. 8. večer ne do jednoho pole konfigurace, ale do **rosteru**:

```jsonc
// <projekt>/.agency/hires.json — kdo je tu najatý
{ "hires": [
  { "id": "review-graph@claude", "pack": "review-graph", "provider": "claude", "model": "sonnet" },
  { "id": "review-graph@codex",  "pack": "review-graph", "provider": "codex",  "model": null }
]}
```

Jednorázově to přebije `agency run review-graph@claude --pr 466 --model opus`.

Tvar spouštěcího příkazu **vlastní CLI**, ne klient. `agency run --json` vrací hotové `launch` argv a extension ho jen pošle do terminálu — kdyby si příkaz skládala i ona, vzniklo by druhé místo, kde se model dá nastavit jinak, a `run.json` by lhal.

A právě proto se `agent.provider` / `agent.model` **zapisuje do run recordu**. Bez toho je otázka *„dává silnější model lepší nálezy, nebo jen dražší?"* nezodpověditelná — a je to přesně ta otázka, kterou má tenhle nástroj umět zodpovědět čísly, ne dojmem. Spolu s cost záznamem ze §3.3 tvoří dvojici, na které stojí test životaschopnosti: precision per model per koruna.

Tabulka providerů je **data, ne větvení** (`providers.py`) — `bin`, `modelFlag`, `dirFlag`, `promptFlag`. Ověřený je zatím jen `claude`; přidat další nevyžaduje zásah do kódu ani vydání nástroje: `agency providers --add grok --bin grok` zapíše řádek do `~/.agency/providers.json` a od té chvíle je grok najmutelný ve všech projektech. Provider je vlastnost **stroje**, hire vlastnost **projektu** — proto bydlí každý jinde a `agency doctor` umí říct „tenhle specialista u tebe běžet nemůže" místo toho, aby to zjistil až běh.

### Roster: jedna metoda, víc pracovníků *(31. 8.)*

Pack je metoda. Hire je pracovník, který se jí drží. Táž metoda jde najmout jednou na každý runner, takže „recenzent · sonnet" a „recenzent · codex" jsou dva řádky nad **jednou** konfigurací, **jednou** frontou nálezů a **jedním** dedupem. Hire nemá vlastní úložiště — sdílená paměť z toho plyne, nemusela se dodělávat.

Důvod není kosmetický. Dva providery nad jedním pull requestem jsou nejlevnější způsob, jak zjistit, který z nich má pravdu; bez rosteru by to šlo udělat jen přepsáním `agent.provider` mezi běhy a run recordy by pak tvrdily, že je to táž práce, jen jinak nastavená.

Tři věci, které to vynutilo, a bez kterých by paralelní běh vypadal, že funguje:

1. **Worktree na pracovníka.** `worktree.path` má `{hire}` a `agency run` odmítne převzít adresář, který drží jiný běžící běh. Bez toho by druhý specialista prvnímu smazal rozdělanou recenzi `--force`em — a poznalo by se to tím, že chybí výsledek.
2. **Marker na pracovníka.** `<!-- agency:review-graph:<hire>:<sha> -->`. Sdílený marker znamená, že první specialista druhého z toho commitu vyzamkne. Skládá ho jádro a předává hotový v `context.json`, aby pravidlo nebylo na dvou místech.
3. **Duplicita se připíše svému autorovi.** Druhý provider, který najde totéž, se označí jako duplicita a do triage se nedostane — v rozpadu po specialistech by proto vypadal, že nenašel nic. V `byHire` a `byProvider` proto duplicita dědí rozhodnutí svého originálu; v celkové precision zůstává vyloučená, aby se jeden nález nepočítal dvakrát. Kolik z toho je shoda dvou různých pracovníků, říká `metrics.agreement` — a vysoké číslo je pokyn pustit je na různé PR, ne na tentýž.

Kill criterium „třetí provider adaptér dřív než třetí pack" (§6) tím **nepadá**: třetí provider už není adaptér, ale řádek dat.

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
    legal/
    po/
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

## 3.6 Co ověřil spike (31. 8.)

Otevřená otázka §8.2 — *unese Comments API nález zakotvený na jiný commit, než je working tree?* — je **zodpovězená kladně**. Postaveno v `packages/extension` na osmi nálezech, z nichž pět jsou skutečné z `pr-review-graph` komentáře na PR #460 (commit `93dc76a`) a tři jsou hraniční případy z reálné historie `main-panelu`: posun řádku 62 → 47 v souboru s +1012/−865, smazaný soubor, číslo řádku za koncem souboru.

| Co se ověřovalo | Výsledek |
|---|---|
| Vlákno na pracovní kopii (případ A) | ✅ 6 z 8 |
| Vlákno na read-only dokumentu z commitu (případ B) | ✅ smazaný soubor se přesto zobrazí |
| Akce v hlavičce vlákna včetně podnabídky s důvody | ✅ |
| Text z pole odpovědi dorazí do příkazu | ✅ |
| `vscode.diff` proti pracovní kopii | ✅ |
| Kotva nad driftem | ✅ 62 → 47 |
| Řádek za koncem souboru nepřistane tiše | ✅ odmítnuto |

**Webview-only varianta se nepoužije, plán se nemění.**

### Pět věcí, které z toho vypadly a v plánu nebyly

Všechny jsou chyby v mém návrhu, ne omezení VS Code — což je přesně to, co spike měl najít, dokud oprava stojí hodinu:

1. **Kotva, vrstva 1** — testovala `commit == HEAD`, musí testovat neměnnost souboru. Zapsáno u kroku 3, bodu 4.
2. **Kotva, vrstva 2** — hledala jeden řádek, musí hledat blok. Tamtéž.
3. **Rozhodnutí patří do sdíleného úložiště, ne do paměti extension.** Bez toho agent triage neumí. Přesunuto z kroku 4 do kroku 3, bod 6.
4. **Rozhodnutí a poznámka jsou dvě různé věci** a nesmí sdílet jedno tlačítko ani jedno pole. Tamtéž.
5. **Přestavba vláken potřebuje generační čítač.** `buildThreads()` je asynchronní a poběží ze tří míst — po doběhnutí runu, při změně větve, po reindexu. Když se dva běhy prolnou, druhý uklidí vlákna prvního, ale ta rozdělaná vzniknou až po úklidu a přežijí jako duplikáty. Ověřeno tím, že se to stalo. Patří do kroku 4.

### Co se z prototypu přenese a co ne

**Přenese se** tvar řešení, ne kód: čtyřvrstvá kotva, `agency:` scheme s `TextDocumentContentProvider` nad `git show`, `contextValue` na vlákně řídící nabídku akcí, rozdělení hlavička/pole odpovědi, enum důvodů.

**Nepřenese se** implementace — spike je plain JS bez závislostí a bez build stepu, ostrá extension je TypeScript podle §3.5. A fixtures se zahodí, jakmile krok 1 vyrobí skutečný `findings.json`.

### Jedna věc, která ubírá práci v kroku 4

**Panel *Comments* agreguje vlákna napříč soubory sám**, se skupinami po souborech, čísly řádků a počtem odpovědí. Seznamový pohled přes všechny nálezy tedy nemusí stavět TreeView — ten zůstane na navigaci mezi projekty, běhy a triage frontou, což je míň, než §3 [`ui-surface-decision.md`](ui-surface-decision.md) předpokládal.

---

## 4. Kroky

Řazené podle poměru *co se dozvím / co to stojí*. Každý má pozorovatelné „hotovo".

> ### Stav k 31. 8. večer
>
> | Krok | Stav | Co konkrétně chybí |
> |---|---|---|
> | 0 | ✅ hotovo | — |
> | 1 | 🟡 kód hotový | **jedno rozhodnutí na skutečných datech.** Cesta je otestovaná (28 testů nad dočasným repem), ale v `main-panelu` je pořád `decisions.jsonl` prázdný a tři nálezy z PR #467 čekají. |
> | 2 | 🟡 rozdělaný | CLI má 16 příkazů, ale běží jeden projekt ze čtyř. `kvesteros-platform` (jiný owner, nula testů, jediný mergnutý PR) je ten, který manifest prověří. |
> | 3 | ✅ kód hotový | brána, dedup, metriky i export existují a mají testy. Export ale ještě nikdy neodešel do skutečného Projectu a metriky nemají z čeho počítat, dokud nezačne triage. |
> | 4 | 🟡 UI přestavěné | čtyři pohledy, detail nálezu v editoru, nastavení, VSIX. Zbývá to, kvůli čemu krok existuje: 47 `Observed` pod 15. **To není práce pro nástroj, to je práce pro tebe.** |
> | 5, 6 | ⬜ nezačato | — |
>
> **Jedno pozorování, které stojí za zapsání.** Kroky 1 a 3 se nedají dokončit
> kódem. Chybí jim rozhodnutí o skutečných nálezech — a to je přesně ta věc,
> kterou nástroj dělat nemá. Když se plán psal, vypadalo „hotovo, když rozhodnutí
> přežije restart" jako technická podmínka; ve skutečnosti je to podmínka
> *použití*. Zbytek plánu má stejnou vlastnost: krok 4 se měří frontou, krok 3
> precision, a ani jedno číslo nevyrobí commit.


### Krok 0 — Stav `Rejected` v Projectu · **½ dne** · ✅ **hotovo 31. 8.**

Z `baseline.md` §7.1–7.2. Přidat `Rejected` + `Reason`, zpětně doplnit 2–3 známé vadné nálezy z `known-regressions.md`.

**Hotovo, když:** precision je měřitelná. → **Splněno pro měření dopředu, ne zpětně.**
**Proč první:** je to 45 minut a bez toho zůstaneš měřicky slepý napořád — každý další krok ten slepý bod zvětší.

Provedeno: volba `Rejected` v poli `Stav`, nové single-select pole `Reason` s pěti hodnotami shodnými s enumem z kroku 3. **Zpětné doplnění neproběhlo vůbec** — dva ze tří kandidátů v Projectu nejsou a třetí je ve skutečnosti opravená verze nálezu, ne vadná. V Projectu není žádný potvrzený falešný pozitiv, takže jmenovatel zůstává nula až do triage v kroku 4. Rozbor a tři pravidla, která z toho plynou pro triage, jsou v [`baseline.md`](baseline.md) §7.2.

---

### Krok 1 — Vertikální řez na `main-panelu` · **3 dny** · 🟡 **hotovo až na poslední důkaz (31. 8.)**

Jeden tenký průchod celým stackem. Ne kompletní CLI, ne kompletní extension — **jedna cesta od začátku do konce**:

> `agency run review-graph` na `main-panelu` → nálezy se zapíšou do `.agency/runs/<id>/findings.json` → zaindexují do `agency.db` → sidebar v VS Code je ukáže ve stromu → klik otevře `file:line` → Accept/Reject se zapíše zpátky do run recordu

Co v tom kroku **je**:

1. `git init` v `veriflow-agency`, layout podle §3.5, Python balíček, `agency` konzolový skript přes `uv`
2. rozpad `pr-review-graph` skillu podle §2.1 na jádro / konfiguraci / obsah projektu
3. `run.json` + `findings.json` podle §2.2 — primární výstup, dnes neexistuje. **Včetně kotvy nálezu (krok 3, bod 4)** — ta musí být v datech od prvního zápisu, protože doplnit ji zpětně jde jen zahozením starých nálezů.
4. `agency.db` jako index + `agency reindex`, který ho postaví z `.agency/runs/**`
5. VS Code extension, minimální: activity bar ikona, **jeden** TreeView (nálezy posledního běhu), proklik na `file:line`, rozhodnutí Přijmout / Odložit / Zamítnout ▸ důvod

Co v tom kroku **není**: dedup, druhý projekt, druhý pack, `doctor`, webview panel, GitHub Project export, retrospektivní audit. Všechno tohle přijde, ale ne teď.

> **Část práce je hotová.** Spike z 31. 8. (§3.6) už má ověřený tvar kotvy, `agency:` scheme, rozdělení rozhodnutí/poznámka i sdílené úložiště, včetně CLI klienta. Nepřenáší se kód — spike je plain JS, ostrá extension je TypeScript — ale nepřenáší se ani žádná otevřená otázka. Bod 5 je tedy přepis, ne návrh, a bod 3 má hotovou specifikaci kotvy včetně dvou oprav, které by jinak vyšly najevo až na reálných datech.

**Hotovo, když:** proběhne celý řetězec bez ručního zásahu, rozhodnutí přežije restart VS Code **a totéž rozhodnutí jde udělat z `agency triage` bez otevřeného editoru.**

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

### Krok 3 — Kontrakt, kotva, rozhodnutí, dedup, metriky, export · **3 dny** · ✅ **kód hotový 31. 8., čeká na data**

`run.v1` a `finding.v1` jako formální schéma (JSON Schema, validované na obou stranách hranice ze §3.2), dedup přes existující fingerprint, a odvozené sinky.

```
agency findings          # napříč všemi projekty
agency metrics           # precision, dedup ratio, stáří, shoda severity
agency export github     # jednosměrný push do GitHub Projectu
```

Šest věcí, které do kontraktu patří hned a jinde by se doplňovaly draho:

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
  "commit": "abc123…",                    // 1. přesná shoda, když se ten SOUBOR nezměnil
  "snippet": "  const x = await getUser(id)",   // 2. text bloku — najde posunutý kód
  "symbol": { "name": "UserService.getUser", "range": [128, 171] },  // 3. dotaz do grafu
  "body":   "…celé tělo funkce v den analýzy, strop 8 kB…"           // 4. záchranná síť
}
```

Rozlišuje se shora dolů, zastaví se na první vrstvě, která uspěje. Selže-li všechno, vlákno se posadí na řádek 1 s poznámkou „původní umístění zaniklo" — **degraduje se, neztratí se.**

Vrstvu 3 dostaneš z `code-review-graph` zadarmo (symbol i rozsah řádků pro `file:line`) a je to ta zajímavá: kotva na symbol přežije refaktor a přesun bloku, číslo řádku ne. Vrstva 4 řeší případ, kdy commit v lokálním klonu už není — squash-merge se smazanou větví je na GitHubu default. `git fetch origin <sha>` obvykle ještě pomůže (GitHub drží `refs/pull/<n>/head`), ale spoléhat se na to nedá. Nálezů budou stovky, ne miliony; 8 kB na nález je levná pojistka.

> **Dvě opravy, které vypadly ze spiku** (§3.6) a bez nich kotva nefunguje:
>
> 1. **Vrstva 1 se ptá na neměnnost SOUBORU, ne repozitáře.** Původně jsem ji psal jako `commit == HEAD`. Jenže nález na souboru, na který od analýzy nikdo nesáhl, tím propadne přes všechny vrstvy až na `none` — protože HEAD je skoro vždy jiný commit. Správně je `git diff --quiet <commit>..HEAD -- <file>`. Ze spiku: takhle se chytnou 4 z 5 skutečných nálezů, předtím ani jeden.
> 2. **Vrstva 2 hledá blok, ne řádek.** Jednořádkový snippet selže na `/**`, `}` a podobné boilerplatě — a docblok začíná přesně na tom. Hledá se nejcharakterističtější řádek bloku `line..endLine` (nejdelší s aspoň čtyřmi alfanumerickými znaky) a od nalezené pozice se odečte offset. Ověřeno na reálném posunu 62 → 47 v souboru s +1012/−865.

**5. Test driftu při ingestu — automatický předtřídič.**

Když znáš commit i rozsah symbolu, jde se levně zeptat, jestli na ten kód od té doby někdo sáhl:

```
git diff abc123..HEAD -- src/auth.ts     # dotkly se hunky řádků 128–171?
```

- **nedotkly** → nález platí doslova, kód je nezměněný
- **dotkly** → možná už opravené; při triage ukázat ten diff jako první

Deterministické, bez jediného LLM volání, a řeže přesně to úzké hrdlo, které `baseline.md` označil za největší ztrátu hodnoty v systému: ze 47 čekajících položek to oddělí živé od pravděpodobně vyřešených ještě předtím, než jedinou otevřeš.

**6. Rozhodnutí je operace nad úložištěm, ne příkaz UI — a poznámka není rozhodnutí.**

Přesunuto sem z kroku 4 na základě spiku. Důvod je jednořádkový: **triage musí umět i agent.** Když rozhodnutí vzniká jako příkaz VS Code, který mimochodem zapíše soubor, je agent druhořadý a celý §3.4 padá. Takže:

```
.agency/runs/<run-id>/decisions.jsonl     ← vlastník rozhodnutí
     ▲                          ▲
     │                          │
  extension                agency triage
  (člověk klikne)          (agent zavolá)
```

Ani jeden klient není privilegovaný, oba zapisují přes tutéž vrstvu jádra. Extension soubor sleduje, takže zápis z CLI se v UI projeví bez reloadu — a to je zároveň jediný poctivý důkaz, že vlastníkem není.

Tři vlastnosti, které z toho plynou a patří do schématu:

- **Append-only události, ne mutovaný stav.** Aktuální stav = přehrání. Konvence 1 ze §5, poprvé použitá na něco reálného; bez ní se dvě historie (tvoje a agentova) nedají sloučit.
- **Rozhodnutí ≠ poznámka.** Rozhodnutí má strukturovaný důvod z pevného seznamu, protože z něj počítáš precision. Poznámka je volný text pro čtenáře („ověřeno na produkci, dva řádky"). Smíchat je znamená rozbít buď měření, nebo použitelnost — ve spiku jsem to zkusil a rozbil obojí.
- **Důvod zamítnutí je enum, ne text:** `not-reproducible` · `by-design` · `wrong-diagnosis` · `duplicate-missed` · `out-of-scope`. Je to týchž pět hodnot jako pole `Reason` v Projectu z [`baseline.md`](baseline.md) §7.1, takže export ze §krok 3 nepotřebuje mapování. Validuje se na obou stranách hranice.

**Jednosměrnost exportu je rozhodnutí, ne zjednodušení** (31. 8.): pravda o rozhodnutí je lokální run record, GitHub Project je publikační cíl pro stakeholdery a měření precision. Žádný zpětný sync, žádné mapování stavů oběma směry, žádné konflikty. Kdyby někdo změnil stav přímo v Projectu, další export ho přepíše — a to je zamýšlené chování, ne bug.

**Hotovo, když:** metriky, které jsem v `baseline.md` počítal ručně, vypadnou z jednoho příkazu, a nález se do Projectu dostane bez toho, aby ho člověk přepsal.

**Poznámka ke schématu:** kontrakt piš až teď, odvozený z toho, co kroky 1–2 skutečně potřebovaly. Ne dopředu.

---

### Krok 4 — Extension v2 a rozhýbaná triage fronta · **1½ dne** · 🟡 **UI přestavěné 31. 8., fronta se ještě nerozhýbala**

Teprve teď se z minimálního TreeView stává použitelné UI. Detaily rozvržení v [`ui-surface-decision.md`](ui-surface-decision.md) §3. Tvar většiny z toho už je ověřený spikem (§3.6), takže tenhle krok je z velké části přepis prototypu do TypeScriptu, ne návrh.

- **`CommentController`** — nálezy jako inline review komentáře u řádku. **Hlavička vlákna = rozhodnutí** (Přijmout · Odložit · Zamítnout ▸ pět důvodů), **pole odpovědi = poznámka** s vlastním tlačítkem. Ta dvě se nesmí míchat ani sdílet tlačítko: rozhodnutí je strukturované kvůli měření, poznámka je volný text. Zápis jde přes jádro do run recordu (krok 3, bod 6), ne do paměti extension.
- **`contextValue` na vlákně řídí nabídku akcí.** Diff proti pracovní kopii se nabízí jen u nálezů, kde test driftu hlásí změnu — u nezměněného souboru by ukázal tentýž obsah dvakrát. Přítomnost toho tlačítka je tím pádem tentýž signál jako předtřídění fronty.
- **Generační čítač při přestavbě vláken.** Poběží po doběhnutí runu, při změně větve i po reindexu; bez něj vznikají duplicitní vlákna (§3.6, bod 5).
- **`WebviewPanel`** v editoru — detail nálezu s evidencí, dedup porovnání dvou nálezů vedle sebe, timeline běhu, portfolio přehled přes projekty
- **Pohled „kód v den analýzy"** — `TextDocumentContentProvider` pro scheme `agency:`, plněný z `git show <commit>:<path>` a oříznutý na rozsah symbolu z kotvy (krok 3, bod 4). Dvě použití z jedné implementace: read-only vlákna pro retrospektivní audit a `vscode.diff` proti pracovní kopii, když test driftu hlásí změnu. Fallback na `anchor.body`, když commit v klonu není.
- **TreeViews jen na navigaci** — projekty a specialisté, běhy, triage fronta s badge počtu. **Seznam nálezů se nestaví** — panel *Comments* ho dělá sám (§3.6).
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

### Právník jako pack #3 *(1. 9.)*

Třetí tvar, protože recenzent i QA mají jeden zdroj pravdy — repozitář. Právník má dva: repozitář **a předpis, který v repozitáři není**. To je první pack, který musí sáhnout ven, a odpověď na otázku „kam" je součást metody, ne improvizace agenta: české zákony z e-Sbírky přes ELI (open data, bez klíče), evropské z Publications Office podle CELEX. Adresy bydlí v `lawSources` v konfiguraci projektu, takže změna endpointu není upgrade packu a `offline: true` je zapnutelný stav, ne výpadek.

Dvě věci, které z tohohle packu vypadly a jinde nejsou:

- **Aplikační brána.** `business.model` a `business.size` jsou povinná konfigurace a `agency doctor` je vymáhá. Právní specialista, který neví, kdo je zákazník a jak je firma velká, nevyrobí prázdný výstup — vyrobí povinnost, kterou nikdo nemá. Mikropodnik je mimo oddíly 3 a 4 DSA i mimo zákon o přístupnosti; § 1752 platí jen na dlouhodobé opakované závazky; DAC7 se zapíná podnikatelskými uživateli, ne slovem „marketplace“ v pitch decku. Závěry jdou do `.agency/legal/applicability.md`, aby je druhý běh neodvozoval znovu.
- **Kalibrační brána.** `posture.requireCitation` zahazuje tvrzení bez konkrétního ustanovení dřív, než se boduje, a dimenze `over-compliance` hlásí opačný směr chyby — re-consent okno u změny, kterou kryje sjednaný mechanismus, souhlas u zpracování běžícího na smlouvě, archiv VOP kvůli pravidlu, které neexistuje. Obecné modely v tomhle oboru nechybují náhodně, chybují **systematicky nahoru**; pack bez téhle brány by tu chybu jen zopakoval s razítkem nástroje.

**Co to vynutilo v jádře:** jednu řádku. `agency doctor` měl nápovědu „Ready. agency run review-graph --pr <n> · agency run qa --prompt …“ napevno; třetí specialista by po ní zůstal neviditelný přesně ve chvíli, kdy ho uživatel hledá. Teď se skládá z běhové politiky nainstalovaných packů (`_run_hint`). Nic jiného se sáhnout nemuselo — `finding.v1` unesl nález, jehož evidencí je citace paragrafu a jehož kotva vede do markdownu, a to je po QA druhé nezávislé potvrzení, že kontrakt není přišitý na kód.

---

### Product owner jako pack #4 *(1. 9.)*

Čtvrtý tvar, a první, který **píše ven**. Recenzent, QA i právník čtou; nejhorší, co z nich vypadne, je nález, který nesedí. Product owner zakládá tickety, komentuje cizí vlákna a hýbe kartami na cizí nástěnce — tím se posouvá, co znamená chyba. Duplicitní ticket už není šum v run recordu, je to práce navíc pro člověka, který o něj nežádal.

Tři věci, které z toho vypadly:

- **Roadmapa je brána, ne příloha.** `roadmap.file` je povinná konfigurace a `agency doctor` vymáhá i to, že na tu cestu ukazuje existující soubor. Je to tentýž tvar jako aplikační brána u právníka a ze stejného důvodu: bez závazků nemá pack čím říct ne, a product owner, který neumí říct ne, je generátor ticketů. Roadmapa se navíc při každém běhu zamrazí do `evidence/roadmap/` — rozhodnutí je přezkoumatelné jen proti znění, ze kterého vzniklo.
- **`agency backlog` místo `gh` v promptu.** Pack nesahá na GitHub sám, volá CLI — stejně jako agent volá `agency triage`, a ze stejného důvodu. Kdyby si volal `gh`, skončily by v promptu čtyři věci, které tam nejdou vymáhat: podpis (jeden tvar, z jednoho místa), marker `<!-- agency:po:<key> -->` (druhý běh pozná, co napsal první), brána `writes.*` a ledger v `.agency/runs/<id>/backlog.jsonl`. Pravda o rozhodnutí tak zůstává v repu; GitHub je sink, ne vlastník — táž věta jako u exportu.
- **Zapisovací práva jsou vypnutá, dokud se nezapnou.** `comments` a `draftIssues` ano (vratné, nikoho neupozorní), `issues`, `promote`, `labels` a `close` ne. `writes.dryRun` složí každý zápis včetně podpisu, vypíše ho a nepošle nic — což je způsob, jak tenhle pack pustit poprvé.

**Co to vynutilo v jádře:** jedno pole běhové politiky (`run.backlog`) a jednu kontrolu v doktoru. `backlog: true` znamená, že příprava načte frontu a zamrazí roadmapu — deterministický krok, takže patří jádru, ne prvním minutám session. Doktor umí navíc obecně ověřit cesty z `config.files` v manifestu (vyplněné pole může ukazovat na soubor, který tam není) a `project` scope u `gh` tokenu, protože chybějící scope se jinak projeví až prvním zápisem. `finding.v1` znovu nesáhnutý — nález kotvený na řádek roadmapy prošel toutéž bránou jako nález z grafu, což je po QA a právníkovi třetí nezávislé potvrzení, že kontrakt není přišitý na kód.

**Co je vědomě coupled:** `board.*` je GitHub. Draft issue je pojem GitHub Projectu a `convertProjectV2DraftIssueItemToIssue` je mutace GitHub API. Jeden backend, který funguje, je lepší než driver navržený proti jedné implementaci — a hranice je vedená tak, že všechno nad ní (roadmapa, rozhodnutí, důvod) backend nezná. Druhý backend vymění `backlog.py` a nic jiného.

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
| Přistihneš se, že **píšeš třetí provider adaptér dřív, než máš třetí pack** | Stavíš pro imaginární ekosystém. | prošlo — 2 providery, 2 packy; od 31. 8. je třetí provider řádek dat (`agency providers --add`), ne adaptér, takže tenhle příznak už neumí zaznít |

**Poznámka k platformní dani.** Tohle je zatím osobní nástroj, ne produkt. Rozdíl není v ambici, ale v účtu: produkt platí za pack registry, podpisy, RBAC, audit log a víceuživatelský sync — a nic z toho nepotřebuje uživatel č. 1. Není nutné teď rozhodnout, který z těch dvou to je. Je nutné **nepředstírat, že je to rozhodnuté**, a neplatit tu daň, dokud rozhodnuté není.

---

## 7. Souhrn

| Krok | Doba | Výstup | Co se dozvíš |
|---|---|---|---|
| 0 | ½ d ✅ | stav `Rejected` + pole `Reason` | precision je měřitelná dopředu; zpětně není co měřit |
| 1 | 3 d 🟡 | **vertikální řez** CLI → store → sidebar → rozhodnutí | sedí tvar dat na to, co UI potřebuje? — **ano, ověřeno na PR #467** |
| 2 | 1½–2 d 🟡 | pack #1 dotažený, 4 projekty, `doctor` | funguje instalace packu do cizího projektu? obstojí UX? — **zatím jen na jednom** |
| 3 | 3 d ✅ | kontrakt, lifecycle, kotva, evidence gate, test driftu, cost per run, **sdílené úložiště rozhodnutí**, metriky, export do GH | jsou nálezy dohledatelné i po měsíci? umí triage i agent? kolik běh stojí? — **829 s na 3 nálezy** |
| 4 | 1½ d 🟡 | extension v2, triage fronta | klesne 47 `Observed` pod 15? jaká je **skutečná** precision? |
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
2. ~~Je `CommentController` použitelný nad nálezy z běhu proti jinému commitu?~~ **Zodpovězeno 31. 8. spikem** — ano, včetně smazaných souborů a read-only pohledu z historie. Výsledky a pět věcí, které z toho vypadly, jsou v §3.6.
3. Unese `agency.db` jako index nad `.agency/runs/**` i retrospektivní audit, kde jeden běh vyprodukuje desítky nálezů nad starými commity? Zjistí se v kroku 2 na `kvesteros-platform`.
4. Kolik nálezů týdně unese tvoje triage kapacita? **To je skutečný strop propustnosti systému, ne rychlost agenta.** Změří se v kroku 4 při rozpouštění fronty 47 → pod 15.
5. Jak naložit s `veriflow-architecture/packages/{agent-session,workspace,store}`, které Python jádro nemůže importovat? Tři varianty jsou v §3.4, rozhodnout v kroku 1.

**Produktové — nezodpoví se kódem:**

6. Kolik stojí jeden běh při plné API ceně? Bez toho neznáš ekonomiku svého produktu ani nemůžeš vyhodnotit druhé kill criterium (§6). Instrumentace je v kroku 3, číslo až po pár bězích.
7. Existuje reálný druhý uživatel, nebo je to zatím hypotéza? Odpověď mění polovinu §5 — bez druhého uživatele je celý sloupec „odloženo" trvalý, ne dočasný.
8. Je `nalekci-po-agent` ochoten stát se kódem? Když ne, pack #3 neexistuje a projekt končí u dvou packů s dobrou triage — což je pořád dobrý výsledek, jen jiný produkt, než se dnes plánuje.
