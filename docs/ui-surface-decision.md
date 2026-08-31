# VeriFlow Agency — kde žije UI (rozhodnutí)

**Datum:** 2026-08-31
**Navazuje na:** [`implementation-plan-v0.md`](implementation-plan-v0.md), [`product-brief.md`](product-brief.md)
**Otázka:** Máme vedle CLI stavět desktopovou aplikaci? Nebo stačí VS Code extension se sidebarem a webview?
**Rozhodnutí:** VS Code extension. Desktopová aplikace se neodkládá — **ruší se**.
**Ověřeno 31. 8. v `main-panelu`:** `code-review-graph` v2.3.7 je Python (instalované přes `uv`, přístup k DB přes stdlib `sqlite3`) a jeho `serve` je hotový MCP server — stdio, nebo Streamable HTTP na `127.0.0.1:5555`. §4, §6 a §9 jsou podle toho přepsané.

---

## 0. Rozhodnutí v pěti větách

Triage nálezu je ze čtyř kroků ze tří prací v editoru — přečíst tvrzení, podívat se na kód, posoudit evidence, rozhodnout. Desktopová aplikace by byla druhé okno, ze kterého se uživatel okamžitě proklikává zpátky do editoru, a přitom by si musela sama postavit file tree, diff viewer, syntax highlighting a odkazy na `file:line`. VS Code tohle všechno dává zadarmo a navíc umí jednu věc, kterou desktopová aplikace fyzicky neumí: **zobrazit nález jako inline review komentář přímo u řádku kódu**. Obava, že „hotový backend pak nepasuje na UI", je oprávněná, ale neřeší se stavbou dvou UI paralelně — řeší se tím, že CLI i extension jsou tencí klienti jednoho JSON kontraktu nad společným jádrem, a že se hned v prvním týdnu udělá jeden vertikální řez skrz obojí. Cena za rozhodnutí je ztráta JetBrains publika; to se bude řešit, až se ozve, a řeší se druhým klientem nad tímtéž kontraktem.

---

## 1. Odkud otázka vzešla

Původní plán v0 počítal s pořadím *CLI first → později nějaké GUI*. Námitka proti tomu je správná a stojí za to ji zapsat doslova:

> Mít hotový backend / CLI a pak kolem toho dělat velkou desktopovou appku — zjistíš, že to pak nepasuje.

To je reálné riziko, ne teoretické. Backend postavený bez klienta si vždycky zvolí tvar dat, který se dobře **zapisuje**, ne tvar, který se dobře **zobrazuje**. Typicky se to projeví takhle: nález má `evidence` jako volný text, protože do JSON logu se to psalo dobře; UI pak potřebuje `file`, `line`, `snippet` a `commit` zvlášť, aby mohlo udělat proklik — a jde se přepisovat schéma i migrace.

Otázka má proto dvě části a je potřeba je oddělit:

1. **Kde má UI žít?** → §2, §3
2. **Jak zabránit tomu mismatchi?** → §4, §5

Odpověď na (2) *není* „stavět dvě věci paralelně". To je organizační odpověď na architektonický problém a na sólo projektu vede ke dvěma půlhotovým věcem.

---

## 2. Proč VS Code extension, a ne desktop

### 2.1 Argument z workflow

Hlavní smyčka produktu je triage. Vypadá takhle:

```
přečtu tvrzení nálezu
  → otevřu file:line a podívám se na kód
  → posoudím evidence proti skutečnosti
  → Accept / Reject / Defer
  → (u Accept) pošlu to Claude Code opravit
```

Tři z pěti kroků se odehrávají v editoru. Čtvrtý (Claude Code) taky, protože Claude Code má vlastní VS Code extension a běží ve stejném okně. Samostatná desktopová aplikace by v téhle smyčce byla průchozí bod, ze kterého uživatel alt-tabuje pryč — a pro proklik na kód by stejně musela střílet `vscode://file/{path}:{line}` do editoru, čili přiznat, že těžiště je jinde.

### 2.2 Argument z primitiv

Co VS Code dává hotové a co z toho tenhle produkt opravdu potřebuje:

| Primitivum | K čemu v Agency |
|---|---|
| `CommentController` | **Nálezy jako inline review komentáře u řádku**, s akcemi Accept / Reject / Defer. Desktopová aplikace to neumí. **Ověřeno spikem 31. 8.** |
| Panel *Comments* | Seznam všech nálezů napříč soubory, se skupinami a čísly řádků — **zadarmo, jako vedlejší efekt vláken**. Nečekal jsem to a ubírá to práci v kroku 4. |
| `DiagnosticCollection` | Nálezy jako squiggles + Problems panel. Nutně za přepínačem, jinak šum. |
| `TreeDataProvider` | Projekty, běhy, triage fronta. Zdarma klávesnice, ikony, badge s počtem, context menu. |
| `vscode.diff` | Diff viewer pro evidence. Žádný vlastní syntax highlighting ani virtualizovaný scroll. |
| Multi-root workspace | Multi-project model nativně, včetně per-folder konfigurace. |
| Integrovaný terminál | Attended běh je vidět, jak běží. Odpadá vlastní log viewer. |
| `QuickPick` | Rozhodnutí triage na klávesnici, bez myši. |
| Status bar, notifikace | Stav běhu bez vlastního chrome. |

Zároveň odpadá: code signing na Windows i macOS, auto-update kanál, packaging, správa oken, vlastní theming.

### 2.3 Co se tím ztrácí

Poctivě: **JetBrains publikum**. To je jediná reálná ztráta a je odložitelná — Cursor i Windsurf jsou forky VS Code, tam extension pojede (sideload VSIX, případně OpenVSX). Pokud se JetBrains ozve, je to argument pro architekturu z §4, ne proti tomuhle rozhodnutí: druhý klient nad stejným JSON-RPC.

---

## 3. Co konkrétně kde — sidebar vs. webview panel

Chyba, do které se tady dá spadnout, je nacpat celé UI do sidebar webview. Sidebar má kolem 300 px a bude to křeč.

**Rozdělení:**

- **Activity bar** — vlastní ikona „Agency", čili `contributes.viewsContainers.activitybar`.
- **Sidebar = nativní TreeView(y)**, ne webview. Levné, klávesnicově ovladatelné, vypadá to jako zbytek editoru, dědí theming zdarma:
  - *Projekty a specialisté* — co je nainstalované kde
  - *Běhy* — historie, stav, proklik do detailu
  - *Triage fronta* — seskupeno podle severity nebo projektu, badge s počtem
- **Editor column = `WebviewPanel`** pro obsah, který se do stromu nevejde. Otevře se jako tab vedle kódu, plná šířka:
  - detail nálezu s evidence
  - dedup porovnání (dva nálezy vedle sebe)
  - timeline běhu
  - portfolio dashboard přes projekty

Takže ano na „větší webview" — ale jako **panel v editoru**, ne jako sidebar.

**Detail, který ušetří den:** `@vscode/webview-ui-toolkit` je deprecated, nebrat. Plain React (nebo cokoli jiného) + `--vscode-*` CSS proměnné na theming; tím se webview automaticky sladí s aktivním tématem uživatele včetně high-contrast.

---

## 4. Architektura, která ten mismatch nedovolí

Tohle je vlastní odpověď na obavu z §1. Po ověření v `main-panelu` vypadá jinak, než jsem původně navrhoval — a jednodušeji, protože polovina té vrstvy už existuje.

```
code-review-graph 2.3.7   Python · uv · stdlib sqlite3 · HOTOVÉ
  ├─ serve                MCP: stdio | HTTP 127.0.0.1:5555, --tools filtr
  ├─ register/repos       multi-repo registry
  └─ crg-daemon           multi-repo watch

agency (Python)           packs, běhy, nálezy, dedup, triage
  ├─ CLI                  --json na všem
  ├─ importuje code_review_graph přímo (stejný runtime)
  └─ klienti
       ├─ VS Code ext     TreeView + WebviewPanel · TypeScript · VSIX
       └─ (později)       web UI / JetBrains  →  stejný JSON kontrakt
```

Čtyři důvody, proč zrovna tenhle tvar:

1. **Mismatch se řeší sám.** Každá potřeba UI se musí stát příkazem nebo RPC metodou — a ta samá je tím pádem dostupná i z CLI. Nemůže vzniknout backend, který „nepasuje", protože UI je jediný důvod, proč ta metoda vůbec vznikla. Tohle je ta pojistka, ne paralelní vývoj.
2. **ABI problém neexistuje.** Původní obava z `better-sqlite3` v extension hostu je bezpředmětná: jádro je Python a v extension hostu nikdy nepoběží. Extension je čistě TypeScript bez jediné native závislosti.
3. **Transportní vrstva je hotová.** `code-review-graph serve` je plnohodnotný MCP server přes stdio i HTTP. Vlastní JSON-RPC se nestaví.
4. **Registry a watch daemon už existují.** `register` / `repos` a `crg-daemon` pokrývají multi-project model; Agency z nich čte, nezakládá druhý paralelní seznam projektů.

**Volba Pythonu je vědomě dočasná** — je to nejrychlejší cesta k experimentu, ne konečná architektura. Aby pozdější přepis stál dny a ne měsíc, platí jedna hranice: **přes hranici jádro ↔ extension smí téct jen JSON podle `run.v1` / `finding.v1`.** Žádné Python typy, žádné implicitní schéma odvozené z toho, co zrovna `json.dumps` vyrobil. Extension nikdy neví, v čem je jádro napsané — a pak je přepis výměna procesu za proces.

**Transport pro v0:** extension spouští `agency <cmd> --json` per dotaz. Spawn Pythonu stojí zhruba 150–300 ms, což triage UI ustojí. Přechod na dlouho žijící proces (`serve --http`) se udělá, až to začne vadit — kontrakt zůstává stejný, mění se jen transport.

### Hranice, která se nepřekračuje

**Extension není source of truth.** Zdrojem pravdy jsou run recordy `<projekt>/.agency/runs/<id>/` — commitované, review-ovatelné v PR, přežijí re-clone. `agency.db` je jen index nad nimi a **musí jít kdykoli smazat a přestavět** (`agency reindex`); ve stejné třídě úložiště jako `graph.db`, který má ve svém `.gitignore` doslova `*` a příkaz `build` ho přestaví od nuly. Extension je *viewer + command issuer*, nikdy vlastník stavu.

Drží to dvě pravidla produktu — deletion-safe persistence a oddělení metody od stavu — a hlavně tím zůstává otevřená cesta na další klienty. React bundle ve webview je stejný React bundle kdekoli jinde, jen s jiným IPC adaptérem.

Totéž platí směrem ven: **rozhodnutí z triage je pravda lokálně, GitHub Project je jednosměrný export.** Žádný zpětný sync, žádné mapování stavů oběma směry. Kdyby někdo změnil stav přímo v Projectu, další export ho přepíše — a to je zamýšlené chování.

---

## 5. Ne dvě větve — jeden vertikální řez

Správná odpověď na „backend a UI se rozejdou" není stavět je paralelně. Je to postavit **jeden tenký řez skrz celý stack hned v prvním týdnu**:

> spustit `review-graph` pack na jednom projektu → nálezy se uloží do grafu → sidebar je ukáže ve stromu → klik otevře `file:line` → Accept/Reject se zapíše zpátky do grafu

Tenké, ošklivé, bez dedup, jeden pack, jeden projekt, žádný webview panel. Ale end-to-end.

Ten řez během pár dní odhalí přesně ty mismatche, kterých se bát: jaký tvar musí mít nález, aby šel zobrazit; co potřebuje evidence pro proklik; jak vypadá idempotentní zápis rozhodnutí; co se stane při druhém běhu nad stejným commitem. A odhalí je v momentě, kdy oprava stojí hodinu, ne přepis schématu a migraci.

Teprve pak ztlušťovat: víc packů → dedup → webview detail → cross-project portfolio.

---

## 6. Technické zádrhely, které stojí za předběžné zapsání

- ~~**SQLite v extension hostu**~~ — **vyřešeno**, viz §4 bod 2. Jádro je Python, v extension hostu nikdy nepoběží, extension nemá žádnou native závislost.
- **Webview CSP** — obsah se načítá přes `webview.asWebviewUri()`, žádné přímé `file://`. Bundlovat lokálně, ne z CDN. Týká se to i výstupu `code-review-graph visualize`, pokud se použije ve webview.
- **`retainContextWhenHidden`** — drží stav webview při přepnutí tabu, ale žere paměť. Lepší je stav serializovat a obnovit ho.
- **Lifecycle extension hostu** — přežívá jen dokud je okno otevřené. Pro attended-only model je to v pořádku a je to vlastně vynucení pravidla produktu. Pro plánované běhy to nikdy nebude to správné místo — ty patří CLI + cron.
- **Distribuce: VSIX** (rozhodnuto 31. 8.) — instaluje se ručně, žádný marketplace. Publikování je zbytečná režie, dokud jsi uživatel ty a případně teammates, kterým se dá poslat soubor.
- **Testovatelnost** — jádro i CLI se testují normálně v Pythonu, mimo VS Code. Extension vrstva se drží tak tenká, aby na ni `@vscode/test-electron` skoro nebyl potřeba; hranice ze §4 to vynucuje sama.

---

## 7. Kdy by extension nestačil

Tři scénáře — a ani jeden nechce desktopovou aplikaci:

| Scénář | Správná odpověď |
|---|---|
| Non-dev stakeholder chce vidět nálezy | Webová stránka nebo GitHub Project |
| Portfolio view bez otevřeného projektu | Webview panel; jen nepotřebuje workspace |
| Plánované / neatendované běhy | CLI + cron na VPS |

Desktopová aplikace je správná odpověď na „uživatel nemá editor". To není tenhle produkt.

---

## 8. Co to mění v implementačním plánu

**Provedeno 31. 8.** — [`implementation-plan-v0.md`](implementation-plan-v0.md) je přepsaný, změny má vypsané v hlavičce. Konkrétně:

- Krok 1 je nově **vertikální řez z §5** na `main-panelu`, ne kostra CLI. Zbytek CLI se přesunul do kroku 2.
- Přibyl krok 4 „Extension v2" — `CommentController`, webview panel, triage fronta. Nahradil samostatný krok „triage konzument".
- Ze seznamu odložených věcí zmizelo „jakékoli UI" a místo toho tam je **desktopová aplikace jako zrušená**, ne odložená.
- Přibyla §3.1 (co `code-review-graph` už umí) a §3.2 (jazyk jádra jako dočasné rozhodnutí).
- Odhad se posunul z ~8–11 na ~11–12 dní; rozdíl je extension a dřívější dodání triage.

---

## 9. Otevřené otázky

1. ~~Jede `code-review-graph` na SQLite a přes jaký driver?~~ **Zodpovězeno 31. 8.** — SQLite ano, ale tool je **Python** v2.3.7 (uv, stdlib `sqlite3`, žádné native rozšíření) a `serve` je hotový MCP server. Viz §4.
2. ~~Je `CommentController` použitelný nad nálezy z běhu proti *jinému* commitu, než je working tree?~~ **Zodpovězeno 31. 8. spikem — ano.** Postaveno na osmi nálezech, z toho pěti skutečných z PR #460, a ověřeno i na smazaném souboru a na posunu řádku 62 → 47. Webview-only varianta se nepoužije, **tohle rozhodnutí je tím potvrzené**. Výsledky a pět chyb v návrhu, které to odhalilo, jsou v [`implementation-plan-v0.md`](implementation-plan-v0.md) §3.6.
3. ~~Kolik nálezů poteče do Problems panelu?~~ **Rozhodnuto:** `DiagnosticCollection` je **default vypnutá**, jen přepínač. Při 35+ nálezech na běh by Problems panel přestal být použitelný pro cokoli jiného.
4. Nové: unese `agency.db` jako index nad `.agency/runs/**` i retrospektivní audit, kde jeden běh vyprodukuje desítky nálezů nad starými commity? Zjistí se v kroku 2 na `kvesteros-platform`.

---

## 10. Jedna věta

UI Agency žije jako VS Code extension — sidebar se stromy pro navigaci, webview panel v editoru pro detail — nad jádrem v Pythonu, ke kterému CLI i extension přistupují týmž JSON kontraktem; desktopová aplikace se neruší z úspory, ale proto, že by uživatele odváděla z místa, kde ta práce stejně probíhá.
