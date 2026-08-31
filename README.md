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

Každý nález má evidenci, kotvu, která přežije pozdější změny kódu, a rozhodnutí,
ze kterého se dá spočítat, kolik z toho byla pravda. Oba specialisté píšou do
téhož kontraktu, takže se v panelu, ve frontě i v metrikách chovají stejně.

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
agency add review-graph      # nainstaluje specialistu do projektu
agency doctor                # předpoklady
agency run review-graph --pr 123
#   … CLI vypíše hotový příkaz; spusť ho ve worktree
agency ingest                # brána nad tím, co agent napsal
agency findings              # co čeká na rozhodnutí
agency triage accept <id>
agency metrics               # precision, dedup, fronta
```

Totéž klikáním: ikona **Agency** v activity baru VS Code.

## QA sezení

```
agency add qa
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
| `packs/` | specialisté — metoda práce, ne obsah (`review-graph`, `qa`) |
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
