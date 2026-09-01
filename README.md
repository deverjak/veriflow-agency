# VeriFlow Agency

Specialisté, které si najmeš do repozitáře. Attended, na tvém přihlášení,
s doloženými nálezy, které zůstanou.

**Recenzent** projde pull request — otevřený i mergnutý — zkříží změny se skutečnou
strukturou kódu z `code-review-graph` a napíše nálezy.

**QA** prozkoumá běžící aplikaci podle zadání, které napíšeš ty: *„vyzkoušej
rezervaci lekce jako nový uživatel, včetně platby“*. Metoda je pro všechny
projekty stejná, zadání ne — a právě zadání dělá ze specialisty tvého.
Ke každému nálezu napíše **Playwright spec, který na něm spadne**; ten se uloží
k běhu, takže „je to už opravené?" se za rok zodpoví spuštěním, ne dalším sezením.

**Právník** projde právní povrch produktu — VOP, podmínky pro partnery, změnová
doložka, souhlasy, cookies, DAC7 — proti tomu, co české a evropské předpisy
opravdu říkají. Každý nález nese citaci ustanovení přečtenou z primárního zdroje
(e-Sbírka přes ELI, EU právo přes CELEX). A protože obecné modely v tomhle oboru
chybují hlavně směrem nahoru, hlásí i **povinnosti, které si produkt vymyslel sám**:
re-consent okno u změny, kterou už kryje sjednaný mechanismus, souhlas u zpracování
běžícího na smlouvě, archiv VOP zřízený kvůli pravidlu, které neexistuje.

**Product owner** drží roadmapu proti tomu, co se opravdu staví. Nahraješ mu
závazky, on projde otevřené issues i drafty na nástěnce a rozhodne, co se staví
teď: na to zakládá tickety a draft issues, a co teď na řadě není, **škrtne
a napíše proč** — na ticket, veřejně, i se závazkem, proti kterému to měřil.
Výchozí odpověď je ne a každé ano se platí ze závazku, který v roadmapě opravdu
je. Všechno, co pošle ven, je **podepsané jako od agenta** a nese marker, takže
druhý běh najde, co napsal první, místo aby to napsal podruhé.

Každý nález má evidenci, kotvu, která přežije pozdější změny kódu, a rozhodnutí,
ze kterého se dá spočítat, kolik z toho byla pravda. Všichni specialisté píšou do
téhož kontraktu, takže se v panelu, ve frontě i v metrikách chovají stejně.

Každého z nich si můžeš najmout **jednou na každý AI runner** — recenzenta na
Claudovi i recenzenta na Codexu — a pustit je na tentýž pull request vedle sebe.
Sdílejí jednu konfiguraci, jednu frontu nálezů a jeden dedup, takže co druhý
zopakuje, se označí jako duplicita místo aby se tě to ptalo dvakrát.

## Instalace

```powershell
pwsh scripts/install.ps1
```

Nainstaluje jádro přes `uv` (editable) a extension přes VSIX. Jednotlivě:
`-Core`, `-Extension`.

Předpoklady: `git`, `uv`, VS Code 1.85+; recenzent navíc `gh` (přihlášené)
a `code-review-graph`, QA s prohlížečem `node`/`npx` a stažené prohlížeče
Playwrightu. Ověří je `agency doctor` — **před** během, ne v jeho půlce, a ptá se
jen na to, co najatí specialisté opravdu potřebují.

## První běh

```
cd <projekt>
agency hire review-graph     # nainstaluje metodu a postaví na ni prvního pracovníka
agency doctor                # předpoklady
agency run review-graph --pr 123
#   … CLI vypíše hotový příkaz; spusť ho ve worktree
agency ingest                # brána nad tím, co agent napsal
agency findings              # co čeká na rozhodnutí
agency triage accept <id>
agency metrics               # precision, dedup, fronta
```

Totéž klikáním: ikona **Agency** v activity baru VS Code.
(`agency add` je totéž pod starším jménem.)

## Víc providerů nad jednou metodou

**Pack je metoda, hire je pracovník**, který se jí drží. Táž metoda jde najmout
jednou na každý runner:

```
agency providers                              # co je na tomhle stroji
agency hire review-graph --provider codex     # druhý recenzent, jiný runner
agency hire review-graph --model opus         # nebo tentýž runner, silnější model
agency roster                                 # kdo je tu najatý

agency run review-graph@claude --pr 123
agency run review-graph@codex  --pr 123       # klidně současně, v druhém terminálu
```

Ve VS Code je to jeden dialog: **Review a pull request…** se po výběru PR zeptá,
kdo ho má vzít, a **vybrat jich smíš víc** — každý dostane vlastní terminál.

Co je sdílené a co ne:

| Sdílené (patří metodě) | Vlastní (patří pracovníkovi) |
|---|---|
| `.agency/<pack>.json` — zadání, prahy, dimenze, prohlížeč | runner a model |
| fronta nálezů, rozhodnutí, dedup, kotvy | vlastní worktree u paralelního běhu |
| paměť projektu — co už se našlo a jak se o tom rozhodlo | vlastní marker na PR |

Poslední dva řádky jsou to, co dělá paralelní běh bezpečným: bez vlastního
worktree by druhý recenzent prvnímu smazal rozdělanou práci, a bez vlastního
markeru by ho z toho commitu vyzamkl.

`agency metrics` pak umí to, kvůli čemu se dva providery pouštějí: rozpad
**by specialist** a `agreement` — kolikrát našli totéž. Vysoká shoda znamená, že
druhý runner platíš za potvrzení, ne za pokrytí, a je čas pustit ho na jiné PR.

### Nový runner na stroji

Když si nainstaluješ další CLI agent, není potřeba vydávat nástroj:

```
agency providers --add grok --bin grok --models "fast,heavy"
agency hire review-graph --provider grok --model heavy
```

Provider je vlastnost **stroje** (`~/.agency/providers.json`), roster vlastnost
**projektu** (`.agency/hires.json`, commituje se). Proto `agency doctor` řekne
„tenhle specialista u tebe běžet nemůže, `grok` není na PATH" místo aby to
zjistil až běh — kolega, který si repo naklonuje, nemusí mít tvoje nástroje.

## QA sezení

```
agency hire qa
#   … do .agency/qa.json doplň app.baseUrl (kde aplikace běží)

agency brief qa --set "Rezervační aplikace pro lekce. Nejdůležitější je rezervace a platba."
agency run qa --prompt "vyzkoušej rušení rezervace na mobilu"

#   uložené zadání pro opakovaná sezení
agency brief qa --scenario smoke --set "přihlášení, dashboard, jedna rezervace"
agency run qa --scenario smoke
```

Zadání má dvě vrstvy, protože každá platí jinak dlouho: **trvalé** (`brief.default`
v konfiguraci projektu) platí pro každý běh, **jednorázové** (`--prompt`, `--scenario`)
jen pro tenhle. Obě jdou do run recordu, takže „které zadání dává lepší nálezy“ je
otázka, na kterou umí nástroj odpovědět čísly.

QA se pouští po jednom, i když je jich najatých víc: sezení řídí běžící aplikaci,
a dvě najednou by se praly o tentýž prohlížeč, databázi a fixtures. Paralelně jde
pouštět recenze, ne sezení.

QA běží **nad pracovní kopií**, ne v jednorázovém worktree — aplikace, kterou zkouší,
běží nad ní. Zdrojový kód je proto ke čtení; zapisuje se do běhového adresáře.
Nález musí být **zopakovaný v čisté session** a zakotvený na řádek kódu, který ho
způsobuje; nereprodukované pozorování se do `findings.json` nedostane.

### Prohlížeč

```
agency config qa --set playwright.enabled=true
agency doctor                # node, playwright, stažené prohlížeče, dostupnost aplikace
```

Ve VS Code totéž klikáním: **Specialisté → QA → Browser**. Nastavení bydlí
v `.agency/qa.json`, ne v editoru, takže platí i pro běh z terminálu a pro agenta.

Instalace zjistí, jestli projekt Playwright **už má** — a když ano, sezení ho
použije: jeho `baseURL`, jeho fixtures, jeho přihlášení. Spec, který si vymyslí
vlastní způsob přihlášení, je druhá pravda o tomtéž a rozpadne se při první změně.

Když projekt Playwright nemá, rozhoduje `playwright.scaffold`:

| Hodnota | Co se stane |
|---|---|
| `run-dir` *(výchozí)* | konfigurace vznikne **uvnitř běhového adresáře**, v repozitáři se nezmění nic |
| `project` | pack smí přidat `playwright.config.ts` a devDependency do projektu |
| `never` | sezení skončí a řekne, co spustit |

Reprodukční specy jdou do `.agency/runs/<id>/specs/` a commitují se s během.
`playwright.specTarget: "suite"` je pošle rovnou do testovací sady projektu — to je
ale rozhodnutí o repozitáři, takže se o něj musíš říct.

## Právní revize

```
agency hire legal
agency config legal --set business.model="marketplace" --set business.size="micro"
agency doctor

agency run legal
agency run legal --prompt "musí být změna VOP oznámena předem?"
```

Než se cokoli kontroluje, rozhodne se **co vůbec platí**. `business.model`
a `business.size` jsou proto povinná konfigurace a `agency doctor` je vymáhá:
mikropodnik je mimo oddíly 3 a 4 DSA i mimo zákon o přístupnosti, § 1752 platí jen
na dlouhodobé opakované závazky a DAC7 se zapíná až `counterparties.businessUsers`.
Pack, který tohle neví, umí vyrobit povinnost, kterou nikdo nemá — a to je u
právníka ta nejdražší chyba. Dimenze `partners` a `tax-reporting` se proto samy
nezapínají; přidáš je do `review.dimensions`, až projekt podnikatelské uživatele
opravdu má. Závěry si pack zapisuje do `.agency/legal/applicability.md`, takže
druhý běh gate neodvozuje znovu.

Předpis se **nečte z paměti**. České zákony bere z e-Sbírky přes ELI (open data,
bez klíče), evropské z Publications Office podle CELEX; znění, o které se nález
opírá, se ukládá k běhu. `posture.requireCitation: true` znamená, že tvrzení bez
konkrétního ustanovení se zahodí dřív, než se boduje — to je celá pointa packu.

| `posture.level` | Co se hlásí |
|---|---|
| `proportionate` *(výchozí)* | jen to, co vyžaduje jmenované ustanovení nebo vlastní slib produktu |
| `conservative` | navíc obhajitelná dobrá praxe, vždy označená a nikdy bodovaná jako povinnost |

Právník **nic nemění** — ani VOP, ani kód. Když si vyžádáš návrh, jde do
`.agency/runs/<id>/drafts/`. A nenahrazuje advokáta: připravuje mu otázky
a evidenci, aby jeho hodina padla na to těžké.

## Product owner

```
agency hire po
agency config po --set roadmap.file=docs/roadmap.md --set roadmap.cycle=2026-Q3
agency config po --set board.projectNumber=7 --set policy.escalate=@kuba
agency doctor

agency run po
agency run po --prompt "má se referral program stavět tenhle cyklus?"
```

`roadmap.file` je povinná konfigurace a `agency doctor` ji vymáhá — a to včetně
toho, že na tu cestu opravdu nějaký soubor ukazuje. Je to táž brána jako
`business.model` u právníka: **bez závazků nemá pack čím říct ne**, a product
owner, který neumí říct ne, je generátor ticketů. `roadmap.cycle` a `capacity`
jsou ze stejného důvodu: „teď“ bez horizontu je názor a škrt bez kapacity se
nedá obhájit.

Roadmapa se při každém běhu **zamrazí** do `evidence/roadmap/`. Rozhodnutí je
přezkoumatelné jen proti znění, ze kterého vzniklo — škrt hájený větou
„roadmapa to neměla“ nemá po dvou editacích roadmapy žádnou cenu.

### Co smí napsat ven

Tohle je první specialista, který **nepíše jen do repozitáře**. Zakládá tickety
v cizí schránce a komentuje cizí vlákna, takže se zapisovací práva zapínají po
jednom:

| `writes.*` | Výchozí | Proč |
|---|---|---|
| `comments` | zapnuto | komentář je vratný a je to způsob, jak se rozhodnutí dá přečíst |
| `draftIssues` | zapnuto | draft leží na nástěnce, nikoho neupozorní a nic nestojí smazat |
| `issues` | **vypnuto** | issue spadne lidem do schránky |
| `promote` | **vypnuto** | povýšení draftu je okamžik, kdy se z poznámky stává závazek |
| `labels` | **vypnuto** | štítky a sloupce jsou cizí struktura |
| `close` | **vypnuto** | škrt patří do komentáře a sloupce, ne do zavřeného ticketu |

```
agency config po --set writes.dryRun=true    # všechno nanečisto, ven nejde nic
agency config po --set writes.issues=true    # až budeš chtít
```

`writes.dryRun` je způsob, jak tenhle pack pustit poprvé: každý zápis se složí
i s podpisem, vypíše se a nikam neodejde. Co by odešlo, leží v `backlog.jsonl`
u běhu.

### Zápis jde přes jádro, ne přes `gh`

Pack nevolá `gh` sám. Volá `agency backlog`, stejně jako agent volá
`agency triage` — a ze stejného důvodu:

```
agency backlog list                                  # issues i drafty
agency backlog draft   --title "…" --body-file …     # poznámka na nástěnku
agency backlog issue   --title "…" --body-file …     # ticket
agency backlog promote PVTI_xxx                      # draft → issue, v místě
agency backlog comment 41 --text-file …              # podepsaný komentář
agency backlog decide  41 not-now --because "…" --commitment "docs/roadmap.md#L18"
```

Kdyby si pack sáhl po `gh` sám, čtyři věci by skončily v promptu, kde je nikdo
nevymáhá: **podpis** (jeden tvar, z jednoho místa), **marker** (druhý běh pozná,
co napsal první), **brána `writes.*`** a **ledger** v `.agency/runs/<id>/backlog.jsonl`.
Pravda o tom, co se rozhodlo, tak zůstává v repu — GitHub je sink, ne vlastník.

Idempotence stojí na klíči odvozeném z titulku. Zápis pod klíčem, který už
existuje, vrátí `{"action": "exists"}` a nepošle nic; to je úspěch, ne chyba.
`promote` převádí draft **v místě** (GitHub to umí sám), takže si položka nechá
své id, sloupec i hodnoty polí.

### Podpis

```
---
**Product owner** — written by an agent, not a person. `agency po@0.1.0` · run `01M1…` · `sonnet`
If this call is wrong, say so here — @kuba has the last word.
```

`policy.escalate` je součást podpisu schválně: agent, který řekne ne a nenapíše,
kdo ho může přebít, není specialista, ale překážka.

## Pravidla projektu jako koncepty

Dimenze `repo-rules` uměla jediný vstup: ukazatel do sekce cizího markdownu
(`review.rules`, třeba `CLAUDE.md#rules-that-will-bite-you`). Ten funguje dál,
ale vedle něj je teď `.agency/knowledge/rules/` — pravidlo jako soubor, který
si nese, jestli ještě platí:

```markdown
---
type: Rule
title: "Sink PR komentáře nesmí spolknout chybu"
status: stable
tags: [area/export, severity/high]
stale_after: 2026-12-01
generated:
  by: human
  at: 2026-09-01T10:00:00Z
verified:
  - by: hire:review-graph@claude
    at: 2026-09-01T12:00:00Z
sources:
  - resource: CLAUDE.md#rules-that-will-bite-you
---

Když selže zápis do PR komentáře, běh nesmí skončit jako `ok`. Nález se
neztrácí tím, že se nepovedlo ho vyvěsit.
```

Je to markdown v repu: čte ho každý provider, kolega v editoru i holá session
bez Agency. Příprava běhu z něj udělá `evidence/known-rules.json`, `agency
doctor` řekne „5 concepts · 1 expired“, a pravidlo, které přestalo platit, se
označí (`status: deprecated`) místo mazání — historie rozhodnutí je to, kvůli
čemu tenhle nástroj existuje.

Formát je [Open Knowledge Format](https://github.com/google/open-knowledge-format)
v0.2, ale je to **konvence, ne závislost**: povinné je jediné pole `type`
a čtečka je v `packages/core/src/agency/okf.py` na padesát řádků. Co nepřečte,
ohlásí s číslem řádku — tiše špatně vyložené pravidlo by bylo horší než žádné.

## Jak je to poskládané

```
agency (Python)              packy, běhy, nálezy, brána, dedup, triage, metriky
  ├── CLI                    --json na všem
  └── klienti
       ├── VS Code extension  stromy + detail v editoru + komentáře u řádků
       └── agent              `agency triage` — rovnocenný klient, ne přívěsek
```

Tři pravidla, na kterých to stojí:

**Pravda je v projektu, ne v nástroji.** Běhy, nálezy i rozhodnutí leží
v `<projekt>/.agency/runs/<id>/` a commitují se. Přežijí přeinstalaci nástroje
i nové naklonování repozitáře a dají se reviewovat v PR. Cokoli mimo — index,
registr projektů — smí kdykoli zaniknout a postavit se znovu.

**Přes hranici jádro ↔ klient teče jen JSON podle `run.v1` / `finding.v1`.**
Extension neví, v čem je jádro napsané. Volba Pythonu je vědomě dočasná; díky
téhle hranici je pozdější přepis výměna procesu za proces, ne přepis UI.

**Rozhodnutí je operace nad úložištěm, ne příkaz UI.** Klik ve VS Code,
`agency triage` v terminálu a volání agenta jdou toutéž cestou a zapisují do
téhož append-only souboru. Kdyby rozhodnutí vznikalo jako příkaz editoru, agent
by triage neuměl.

## Struktura

| Cesta | Co je uvnitř |
|---|---|
| `packages/core/` | jádro a CLI (Python, `uv`) |
| `packages/extension/` | VS Code extension (plain JS, bez build stepu) |
| `packs/` | metody práce, ne obsah (`review-graph`, `qa`, `legal`, `po`) — kdo je jimi najatý, je v projektu |
| `schemas/` | `run.v1`, `finding.v1` — kontrakt obou stran hranice |
| `docs/` | rozhodnutí a plán, včetně toho, co se v nich změnilo a proč |

## Testy

```powershell
pwsh scripts/test.ps1
```

Jádro se testuje nad dočasným git repem, který vznikne a zanikne v jednom testu —
takže testy jdou pustit stokrát za sebou a nesahají na skutečné projekty.
Extension má smoke test s podstrčeným `vscode`; vlákna a tlačítka chtějí `F5`.

## Kam dál

[`docs/implementation-plan-v0.md`](docs/implementation-plan-v0.md) — kroky, stav
a hlavně důvody. [`docs/baseline.md`](docs/baseline.md) — měření, ze kterého to
celé vzešlo. [`docs/ui-surface-decision.md`](docs/ui-surface-decision.md) — proč
VS Code a ne desktopová aplikace.
