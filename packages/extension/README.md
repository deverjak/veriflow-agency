# CommentController spike

Zjišťuje jedinou věc, na které stojí rozhodnutí v [`docs/ui-surface-decision.md`](../../docs/ui-surface-decision.md) §9 otázka 2:

> Unese VS Code Comments API nález zakotvený na **jiný commit**, než je working tree?

Je to spike, ne základ extension — plain JS, nula závislostí, žádný build step. Až odpoví, zahodí se nebo přepíše do TypeScriptu podle [`implementation-plan-v0.md`](../../docs/implementation-plan-v0.md) §3.5.

## Data

Nejsou vymyšlená. `src/fixtures.json` se generuje z reálného gitu `main-panelu`:

| # | případ | zdroj |
|---|---|---|
| f1–f5 | `no-drift` | skutečné nálezy z `pr-review-graph` komentáře na PR #460, commit `93dc76a` |
| f6 | `drifted` | `BookingsTabPanel.tsx`, řádek 62 → 47 v souboru s +1012/−865 od 18. 8. |
| f7 | `deleted` | `src/app/[locale]/account/page.tsx`, od té doby smazaný |
| f8 | `out-of-bounds` | číslo řádku 99999 |

## Spuštění

**Strojová část** — kotva a test driftu, bez VS Code:

```
node packages/extension/test/harness.js
```

**Vizuální část** — F5 v tomhle repu (`.vscode/launch.json` otevře Extension Development Host nad `main-panelem`), pak z palety:

```
Agency Spike: Spustit všechny kontroly
```

Otevře se markdown report a vytvoří se vlákna.

## Co harness NEOVĚŘÍ — tohle musíš odkliknout

1. **Vlákno je vidět u řádku.** Otevři `src/application/marketplace/getMyBookings.ts` → u řádku 517 má být vlákno.
2. **Čtyři ikony v hlavičce vlákna:** Přijmout · Odložit · Historie · Porovnat. Tohle je vlastní test menu příspěvků — když se neobjeví, `when` klauzule `commentController == agency.findings` nesedí.
3. **Zamítnutí s důvodem.** Napiš text do pole odpovědi a klikni „Zamítnout s důvodem" — příkaz musí ten text dostat (jde do Output → *Agency Spike*). Tohle je jediná cesta, jak sebrat důvod zamítnutí bez vlastního dialogu.
4. **Read-only pohled z commitu** (ikona Historie u f7 — smazaný soubor). Musí se otevřít obsah z `git show`, ne prázdno.
5. **Diff proti pracovní kopii** (ikona Porovnat u f6).
6. **Reload okna** (`Developer: Reload Window`) — vlákna musí zmizet, ne se zdvojit. VS Code komentáře nepersistuje, takže se po aktivaci vytvářejí znovu z dat.

## Co spike už našel

Chybu v návrhu kotvy, ne v API: **vrstva 1 nesmí testovat `commit == HEAD`, ale neměnnost konkrétního souboru.** Nález na netknutém souboru jinak propadne přes všechny vrstvy až na `none`. A vrstva 2 nesmí hledat jediný řádek — docblok začíná na `/**`, což je k nalezení k ničemu; hledá se nejcharakterističtější řádek bloku a odečte se offset.

Obojí je opravené a patří do `finding.v1`.
