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

První tři řádky umí `agency run … --wait` najednou: pustí agenta v tomhle
terminálu — pořád je vidět a dá se do něj vstoupit — počká na něj a bránu spustí
sám. Nejde o pohodlí. Běh, u kterého se na `agency ingest` zapomene, zůstane
navždycky `running` a jeho nálezy pro nástroj neexistují. Navíc je poprvé vidět,
**jak** agent skončil: `agent.exitCode` v záznamu, `failed` místo mlčení, a
změřený čas běhu, ze kterého metriky spočítají cenu za kandidáta.

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

## Tým — specialisté za sebou

Právník najde, že chybí reconsent flow. Je to nález, nebo ne? Odpověď nezná
právník — zná ji product owner, protože ví, že tenhle web nemá účty a letos
mít nebude. Dokud běhy stojí vedle sebe, přijde ta otázka na člověka. V řetězu
přijde na product ownera.

```powershell
agency chain legal po --prompt "VOP pro nový web"
agency chain legal@claude po@claude --pr 12
```

Každý člen dostane výstup předchozích v `evidence/upstream.json` — **plné
nálezy s rozhodnutími, bez stropu**. Strop tři sta patří pozadí; zadání se
ořezávat nesmí, jinak řetěz tiše vyrábí nálezy, o kterých nikdo nerozhodl.

Prompt kroku skládá jádro z deterministické šablony a celý skončí v `prompt.txt`,
takže je vidět, čím byl který člen vykopnutý:

```
… You are step 2/2 of a chain (po@claude).
Upstream: legal@claude — 7 findings (5 undecided), full data in evidence/upstream.json.
First judge those findings — `agency triage accept|reject|defer <id> --by …` —
and only then run your own dimensions.
Handoff from legal@claude: <prvních 40 řádků handoff.md předchůdce>
```

Věty v šabloně vlastní jádro, obsah v nich napsal upstream agent do
`handoff.md`. **Žádný LLM mezi běhy** — chain je deterministický seznam,
pořadí volí člověk a úsudek patří dovnitř běhů, kde je zaznamenaný a zaplacený
jednou.

`summary.md` je „co jsem udělal" pro člověka a pro paměť projektu. `handoff.md`
je „co potřebuješ ty" pro jednoho jmenovaného kolegu: co jsem nedořešil, co
stojí na domněnce o produktu, čemu bych sám nevěřil.

Čtyři vlastnosti, které z toho dělají tým a ne skript:

- **Řetěz je v datech.** Každý `run.json` nese `chain: {id, position, of, upstream}`.
  Bez toho nejde zpětně poznat, které rozhodnutí padlo nad cizím nálezem
  v rámci předání a které samostatně.
- **Jeden tým = jeden provider** (v1). Jeden binár, jeden credential, jedna sada
  quirků na terminálu. Handoff je souborový, takže mix providerů není
  architektonická překážka — je to změna jedné validace, až se pipeline osvědčí.
- **Odmítnutý nebo spadlý krok řetěz zastaví.** Pokračovat potichu by znamenalo,
  že product owner soudí nálezy, které nevznikly. Co doběhlo, je zapsané
  a vytiskne se, kde se dá navázat ručně.
- **Neúplný řetěz je poznat.** `of` je v záznamu právě proto: zastavený tým se
  v přehledu nesmí tvářit jako dokončený, jen kratší.

V VS Code je to **Run a team…** — výběr po jednom, protože pořadí je celý smysl
věci a QuickPick ho neumí zaručit. Běhy jednoho týmu drží v přehledu pohromadě
pod jedním uzlem. Orchestruje pořád CLI: extension pošle do terminálu
`agency chain …` a dál se dívá.

## Paměť projektu jako markdown

`.agency/knowledge/` je commitovaná paměť projektu. Čte ji každý provider,
kolega v editoru i holá session bez Agency — proto je to markdown, a ne
databáze.

```
.agency/knowledge/
  index.md            přehled — co projekt ví, co kdo rozhodl
  log.md              chronologie: čím se který běh zabýval, jeho vlastními slovy
  findings/<id>.md    nálezy napříč běhy, packy a specialisty — generované
  rules/<id>.md       pravidla projektu — píše člověk
  pages/<pack>/       závěry specialisty: co ví QA, PO nebo právník o tomhle projektu
```

### Pravidla — píše je člověk

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

Příprava běhu z něj udělá `evidence/known-rules.json`, `agency doctor` řekne
„5 concepts · 1 expired“, a pravidlo, které přestalo platit, se označí
(`status: deprecated`) místo mazání — historie rozhodnutí je to, kvůli čemu
tenhle nástroj existuje.

### Ledger nálezů — generuje se

`agency ingest` po bráně přepíše `findings/`. Každý nález je koncept s kotvou
do kódu, s tím, kdo ho našel, a s tím, co se s ním pak stalo:

```markdown
---
type: Finding
title: "Sink PR komentáře spolkne chybu a běh hlásí úspěch"
status: deprecated
trust: human-reviewed
generated:
  by: hire:review-graph@codex
  at: 2026-08-31T21:44:00Z
verified:
  - by: hire:review-graph@claude
    at: 2026-09-01T07:10:00Z
    how: independent-duplicate
decision:
  state: rejected
  reason: by-design
  by: human:kuba
  at: 2026-09-01T09:02:00Z
---
```

`trust` a `status` odpovídají na dvě různé otázky a schválně se neslily do
jedné. `trust` je míra přezkoumání (kdo se na to díval), `status` je stav
tvrzení (obstálo?). Zamítnutý nález má obojí zároveň — člověk se díval **a**
tvrzení neobstálo; jako jedno pole by jedna z těch dvou vět nešla napsat.

`verified` vzniká z duplicit napříč pracovníky: když nález našel `codex`
a `claude` ho nezávisle našel znovu, není to druhý nález, ale potvrzení
prvního. Duplicita od **téhož** pracovníka potvrzení není — to je jen týž
pracovník podruhé, a kdyby se to počítalo, stačilo by pustit jeden pack dvakrát.

Ledger je **odvozený**, stejný statut jako `agency.db`: pravda zůstává
v `.agency/runs/` a bundle se dá kdykoli zahodit a postavit znovu.

```powershell
agency knowledge            # je bundle v souladu s běhy?
agency knowledge --rebuild  # přestav ho z .agency/runs/
```

### Stránky packů — píše je specialista

Nález je jednotlivost. „Payment state machine je dlouhodobě nejrizikovější část"
nebo „u monetizace preferujeme Free jako growth engine" jednotlivost není a do
`findings/` se to nevejde. Od toho jsou `pages/<pack>/`: kurátorovaná znalost
packu, kterou na konci běhu aktualizuje sám specialista.

```markdown
---
type: Page
title: "Co je prozkoumané a co ne"
status: stable
stale_after: 2026-12-01
verified:
  - by: hire:qa@claude
    at: 2026-09-01T12:00:00Z
---
```

Pravidlo, které dostaly QA, PO i právník do SKILL.md, zní **závěry, ne log**.
Chronologii běhů vede `log.md`; kdyby ji stránka vedla podruhé, jedna z těch
dvou verzí bude časem lhát. Co přestalo platit, se přepíše, nebo dostane
`status: deprecated` a **zůstane** — smazat závěr znamená zahodit i důvod, proč
se k němu nemá příště docházet znovu.

Stránka **bez hlavičky** se čte dál a v přehledu je označená jako
„no frontmatter". Paměť se psala dřív, než koncepty existovaly, a prohlásit
fungující soubor za rozbitý by byla nepravda. U pravidla to neplatí: pravidlo
bez hlavičky neví, jestli ještě platí, a nález na něm stavět nelze.

Výchozí místo je v bundlu, ale `memory.dir` v konfiguraci packu vyhrává —
projekt, který má paměť v `.agency/qa/`, ji tam má dál a odkaz v přehledu vede
tam. Pack běžící ve worktree stránky nedostane vůbec: worktree stojí na hlavičce
PR a `agency run` ho po sobě smaže.

Formát je [Open Knowledge Format](https://github.com/google/open-knowledge-format)
v0.2, ale je to **konvence, ne závislost**: povinné je jediné pole `type`
a čtečka je v `packages/core/src/agency/okf.py` na padesát řádků. Co nepřečte,
ohlásí s číslem řádku — tiše špatně vyložené pravidlo by bylo horší než žádné.

### Co z paměti běh dostane — a proč zrovna to

Do běhu se paměť nevejde celá; `known-findings.json` má strop tři sta nálezů.
Dlouho to znamenalo „posledních tři sta", protože běhy se čtou od nejnovějšího.
Nález z jara tím vypadl, aby se vešlo tři sta čerstvých malicherností — a to je
zapomínání, které si nikdo neobjednal.

Dneska strop vybírá podle toho, co má běh dělat. Zadání (`--prompt`), titulek
cíle a jméno packu složí dotaz a nálezy se seřadí podle BM25 —
`packages/core/src/agency/rank.py`, sto řádků nad `math` a `re`. Žádný model,
žádné API, žádná síť, žádný proces navíc.

```
agency run qa --prompt "reconsent banner po expiraci"
#   evidence/ filled  {'knownFindings': 812, 'knownFindingsQuery': 'reconsent banner …'}
```

Dvě vlastnosti stojí za vyslovení, protože jsou to rozhodnutí, ne detaily:

- **Bez zadání se nic nepřeskládá.** Běh bez `--prompt` a bez cíle nemá dotaz
  a dostane pořadí podle stáří, jako dřív. Vymýšlet dotaz z ničeho by znamenalo
  řadit podle šumu, což je horší než řadit podle času.
- **Synonyma to neumí.** „payment flow" nenajde nález, který mluví jen
  o „checkout process". Za tohle se platí embeddings, embeddings znamenají model
  a model znamená klíč nebo GPU — tedy přesně tu závislost, kterou tenhle
  nástroj nemá. Dotaz i nálezy naštěstí mluví slovníkem téhož repa.

Sémantický recall přes [Hindsight](https://github.com/vectorize-io/hindsight)
tu byl postavený a zamítnutý: ten démon si extrahuje fakta vlastním LLM, takže
lokální adresa nezaručuje, že obsah nikam nejde — a to byla jediná věc, kterou
si za démona, 18 balíčků a port navíc člověk kupoval. Rozbor je
v [`docs/plans/shared-memory.md`](docs/plans/shared-memory.md) Kroku 5.

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
