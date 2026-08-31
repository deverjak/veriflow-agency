# VeriFlow Agency

Specialisté, které si najmeš do repozitáře. Attended, na tvém přihlášení,
s doloženými nálezy, které zůstanou.

Recenzent projde pull request — otevřený i mergnutý — zkříží změny se skutečnou
strukturou kódu z `code-review-graph` a napíše nálezy. Každý nález má evidenci,
kotvu, která přežije pozdější změny kódu, a rozhodnutí, ze kterého se dá spočítat,
kolik z toho byla pravda.

## Instalace

```powershell
pwsh scripts/install.ps1
```

Nainstaluje jádro přes `uv` (editable) a extension přes VSIX. Jednotlivě:
`-Core`, `-Extension`.

Předpoklady: `git`, `gh` (přihlášené), `uv`, `code-review-graph`, VS Code 1.85+.
Ověří je `agency doctor` — a ověřuje je **před** během, ne v jeho půlce.

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
| `packs/` | specialisté — metoda práce, ne obsah |
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
