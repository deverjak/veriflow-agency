# Superagenti — harness nad packy

**Datum:** 2026-09-06
**Navazuje na:** [`agency-v1.md`](agency-v1.md) (pack je skill v projektu, žádná konfigurace), [`shared-memory.md`](shared-memory.md) (paměť patří projektu a commituje se), [`teams.md`](teams.md) (řetěz: druhý specialista soudí, co našel první), [`findings-ownership.md`](findings-ownership.md) (board je stav, lokál je brána a stopa), [`unattended.md`](unattended.md) (proud událostí, `agent.jsonl`)
**Řeší:** jak z dnešních specialistů udělat agenty, kteří se **měřitelně** zlepšují — aniž by se z Agency stala univerzální platforma.
**Podnět:** [`affaan-m/ECC`](https://github.com/affaan-m/ECC), prostudováno 6. 9. 2026 (klon 92 MB, 286 skillů, 68 agentů, hookový graf 41 kB, „instinkty" s konfidencí), [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [`BerriAI/self-improving-agent`](https://github.com/BerriAI/self-improving-agent).

---

## Stav k 6. 9. 2026

Všech patnáct kroků má hotový kód, commitnuto po krocích, testy zelené mezi tím (393). Fáze D má hotový kód, ale **ne přejímku** — ta chce reálnou historii rozhodnutých nálezů, kterou tenhle repozitář nemá.

| | stav |
|---|---|
| **0** sonda hooků | hotovo — výsledky níž u Kroku 0, klíče v `providers.py` |
| **A** 1, 13, 14, 2, 3 | hotovo |
| **B** 8, 9, 15 | hotovo |
| **C** 4, 5, 6, 7 | hotovo |
| **D** 10, 11, 12 | kód hotový; §7 body 8–10 čekají na reálná rozhodnutá data |

**Co zbývá — jediná věc, a nejde udělat tady:** přejímka Fáze D (§7 body 8–10). Chce reálnou historii rozhodnutých nálezů nad `main-panelem`, kterou tenhle repozitář nemá. Kód všech patnácti kroků je hotový a otestovaný.

**Dodělané po prvním průchodu:**

1. **Krok 9 — řádka na telefon.** `RUN_DIR/notes.jsonl` jako druhý soubor; SSE endpoint čte oba a prokládá je. Do `agent.jsonl` se nesahá — je to surový transkript providera. Id události má proto tvar `<stream>.<notes>`, jinak by se po výpadku signálu obnovovalo na špatném místě.
2. **Krok 12 — spuštění nad připnutým commitem.** `cmd_run` dostal `pinned`, oddělený od `chain`: replay není člen řetězu. Fixtura si přitom musela začít pamatovat i seznam souborů — bez něj se PR pack odmítl spustit, a ptát se `gh` znovu by znamenalo, že eval přestane fungovat, jakmile se větev smerguje a smaže.
3. **Krok 2 — limit délky argumentu na Windows.** Doprobováno: 40 řádků = 4,4 kB projde, 250 řádků (27 kB) taky, 300 řádků (32,7 kB) ne. Zeď je `CreateProcess` a hlásí se jako `WinError 206`, tedy „soubor nenalezen". Pojistka: co se nevejde, se nepošle a záznam to přizná.
4. **Extension** ukazuje `blocked.md` v seznamu výstupů a vlastní ikonou stavu; tlačítko jako u `summary.md` neexistuje, protože takové tlačítko nemá ani `summary.md`.

**Čtyři věci, které plán tvrdil a kód říkal něco jiného** (opraveno v příslušných krocích, ne potichu): `--append-system-prompt-file` neexistuje jako funkční flag; příklad řádku v `tool-calls.jsonl` měl vymyšlený `exitCode`; `proc.stream` uplatňoval `timeout` až po dočtení proudu, takže runaway pojistka by nikdy nevystřelila; a řetěz předával společný prompt i členovi s `prompt: "none"`, čímž by `verify` shodil celý řetěz na svém kroku.

**A jedna živá chyba nalezená cestou:** `knownSpecs` se vracelo z `for_run` a chybělo v `MEMORY_STATS`, takže grafový běh v projektu se specy psal záznam neplatný proti vlastnímu schématu. Past §0.3/#1 počtvrté — [`tasks.md`](tasks.md) Fáze 0 ji přitom už jednou hlásila jako opravenou. Teď ji hlídá test proti tomu, co `for_run` doopravdy vrací.

---

## 0. Než začneš — orientace pro agenta, který tenhle plán vykonává

### 0.1 Kde co je

```
packages/core/src/agency/     jádro (Python, uv, editable). Zná běh, bránu, paměť, providery.
                              O žádném cílovém projektu neví nic a nesmí se to změnit.
packages/core/tests/          pytest nad jednorázovým git repem (conftest.py ho staví a boří)
packages/extension/           VS Code viewer, plain JS, bez buildu. Čte jen `agency … --json`.
schemas/run.v1.json           kontrakt běhu
schemas/finding.v1.json       kontrakt nálezu
packs/                        referenční kopie packů, které živě bydlí v `main-panelu`.
                              Výjimka: `packs/author/` je generický, ships s jádrem.
docs/plans/                   tenhle adresář — česky. Všechno ostatní anglicky.
```

### 0.2 Jak se to spouští a testuje

```powershell
pwsh scripts/test.ps1        # obojí: pytest jádra + smoke extension
```

Jen jádro: `cd packages/core; uv run --with pytest --with jsonschema python -m pytest`

Fixtury v [`conftest.py`](../../packages/core/tests/conftest.py), které budeš potřebovat: `repo`, `project`, `install_pack(project, name, manifest)`, `make_finding(project, run_id, **over)`, `make_run`. A `never_launch_an_agent` — **autouse** fixtura, která hlídá `proc.attend` i `proc.stream`. Nikdy ji neobcházej: jednou už se stalo, že testy pustily reálného `claude` a jeden běžel deset minut, než ho někdo zabil ([`tasks.md`](tasks.md), Fáze 8).

### 0.3 Tři pasti, do kterých se tady už spadlo

**1. Bloky v `run.v1` mají `additionalProperties: false`.** Přidáš klíč do `run.json` bez toho, abys ho přidal do schématu → běh zapíše **neplatný záznam** a nikdo si toho nevšimne, protože `agency validate` kontroluje `finding.v1`, ne `run.v1`. V [`tasks.md`](tasks.md) je to zapsané jako past, do které se spadlo **třikrát** (`knownFindings`, `recalled*`, `knownFindingsQuery`). Pravidlo: **napřed schéma, potom zápis.** Statistiky z přípravy běhu, které nejsou grafové, patří do `evidence`, ne do `run.graph` — na to je konstanta `MEMORY_STATS` ([`runs.py:513`](../../packages/core/src/agency/runs.py)).

**2. Fakta o provideru se probují, nevymýšlejí.** Podívej se, jak jsou psané komentáře v [`providers.py`](../../packages/core/src/agency/providers.py) — každý klíč nese, co přesně se spustilo a co konzole odpověděla, s datem. Když v tomhle plánu stojí „sonda", znamená to *spusť to na reálném `claude` a přečti výstup*, ne *přečti `--help` a odhadni*.

**3. Data, která nikdo nečte, jsou mrtvá data.** `streamArgs` byly v tabulce providera a na příkazovou řádku se nikdy nedostaly — orchestrátor parsoval proud, o který nepožádal, a řetěz mlčel dvacet minut. Testy to nechytily, protože krmily parser přímo. **Ke každému novému souboru v `RUN_DIR` musí existovat test, že ho něco vyrobilo, a věta v `SKILL.md`, že ho má agent přečíst.**

### 0.4 Attended a unattended — co který běh vůbec zaznamená

**Tohle musíš vědět, než sáhneš na cokoli měřicího.** Rozhoduje jediný řádek, [`cli.py:619`](../../packages/core/src/agency/cli.py):

```python
dialect = providers.streaming(agent_info["provider"])[1] if unattended else None
```

`dialect` je jediné, co v [`runs.attend`](../../packages/core/src/agency/runs.py) přepíná `proc.stream` (čte proud, parsuje `events.py`) proti `proc.attend` (jen počká na exit code).

| jak se spustí | proces | co se zapíše do `run.json` |
|---|---|---|
| `agency run X` | vytiskne příkaz, člověk ho vloží sám | **nic** |
| `agency run X --launch` | `os.execvp` ([`cli.py:627`](../../packages/core/src/agency/cli.py)) — proces se *stane* agentem | **nic** |
| `agency run X --remote-control` | okno na stroji, session pro Claude appku | nic z průběhu; interaktivní `claude` žádný strojový proud nepublikuje |
| `agency run X --wait` | subprocess, čeká | `agent.exitCode`, `cost.wallClockSeconds` |
| `agency run X --unattended --wait` | `-p`, `stream-json`, čte proud | **všechno**: `agent.turns`, `agent.denied`, `agent.sessionId`, `cost.usd`, tokeny |
| člen řetězu | vždy unattended | totéž co výše |

**Důsledek, který mění tenhle plán:** `turns`, `denied`, `cost` a `sessionId` existují **jedině u unattended běhů**. Na nich stojí Kroky 7, 9 a půlka briefu v Kroku 10. Kdo běhá převážně attended, nesbírá skoro nic — a `agency follow` mu nefunguje, protože není `sessionId` k obnovení. Řeší to Krok 14; do té doby to měj na paměti u každého kroku, který se opírá o `agent.*`.

### 0.5 Hranice, které se nehýbou

- **Jádro nezná žádný cílový projekt.** Nic v `packages/core/` nesmí obsahovat jméno repa, URL boardu ani cestu ke stagingu.
- **Do brány (`ingest`) nevstupuje model.** Brána zůstává deterministická a opakovatelná. Ověřování modelem je člen řetězu.
- **Žádná konfigurace.** Nový klíč jde do `pack.json` (zdroj projektu, versionuje se s ním) nebo do `run.json` (fakt o proběhlém běhu). Žádné `.agency/*.json`, žádné ENV profily, žádný `agency config`.
- **Nic se nezabíjí na základě heuristiky.** Varuj, zapiš, nech doběhnout. Jediná výjimka je runaway pojistka v Kroku 15 a je odůvodněná tam.
- **Necommituj, pokud tě o to zakladatel nepožádá.** Jeden krok = jeden commit, testy mezi tím.
- **Jazyk:** `docs/plans/*.md` česky. Kód, komentáře, CLI výstup, `SKILL.md` packů, README — anglicky. Když narazíš na češtinu mimo `docs/plans/`, přelož ji.

---

## 1. Proč tenhle plán existuje

Packy fungují. Běh doběhne, brána zahodí, co nemá důkaz, stopa si pamatuje, kam nález šel, a `agency metrics` umí říct `dimenze reuse 0.2, correctness 0.9`.

A přesně tam to končí. **Nikdo tu větu nepřečte a nikdo podle ní nic nezmění.** Pack, který půl roku produkuje šum v jedné dimenzi, ho produkuje i sedmý měsíc, protože jediná cesta, jak se to dozvědět, je otevřít metriky, a jediná cesta, jak to opravit, je ručně přepsat `SKILL.md` — a mezi tím není nic.

Tenhle plán je o tom mezitím: o **smyčce mezi tím, co pack našel, a tím, co s tím projekt udělal.**

**Dvě omezení, která mění pořadí prací:**

1. **Smyčka potřebuje palivo.** Fáze D chce ~10 **rozhodnutých** nálezů na pack. Podle [`tasks.md`](tasks.md) W5 nikdy nedoběhlo a přejímka Fáze 11 Kroku 7 je otevřená — reálně jich máme jednotky. Riziko není design, je to **stavba učícího stroje pro data, která zatím nejsou.** Proto jde `verify` (Krok 8) hned za záznam a **před** posilování brány: palivo se hromadí běháním, ne psaním kódu.
2. **Smyčka potřebuje měřidlo, které nelže.** Attended a unattended běhy jsou dvě různé populace (§0.4) a dnes se v `metrics` slévají. Krok 14 je proto ve Fázi A, ne až u metrik.

**A jedna věc, kterou tenhle plán nedělá, aby se to nečekalo:** nedělá agenta autonomnějším. Autonomii řídí `needs`, `needsUnattended` a `--bypass` — nic z toho se tu nemění. Plán dělá agenta **kalibrovaným**, a kalibrace je to, co si autonomii teprve zaslouží: až bude `review-graph` mít precision 0,85 doloženou na třiceti rozhodnutých nálezech, pustí ho zakladatel `--unattended` bez váhání. Dnes ho pouští attended, protože neví.

---

## 2. Co se bere z ECC a co ne

ECC je opak našeho zadání a je poctivé to říct hned: **jeden univerzální agent, kterému se přidává výbava** — 286 skillů, 68 agentů, 122 souborů pravidel, sedm harnessů, instalátor s profily a ~40 ENV proměnnými na vypínání hooků. Vlastní skill `context-budget` existuje proto, že ta výbava sama sežere kontextové okno, které měla obsloužit. My jdeme opačně: N úzkých specialistů, každý vlastněný jedním repem. Z toho neplyne, že tam není co brát — plyne z toho jen **co**: mechanismy harnessu, ne katalog obsahu.

| # | myšlenka | jak to dělá ECC | jak to děláme my | proč jinak |
|---|---|---|---|---|
| 1 | **učení z běhů** | `continuous-learning-v2`: hooky sbírají pozorování → agent na pozadí z nich destiluje „instinkty" (chování + konfidence 0,3–0,9) → `/evolve` je shlukne. Sklad mimo repo | Kroky 2, 10, 11 — zamítnutí a přijetí **už jsou** ten signál | ECC hádá z transkriptu, co se uživateli líbilo. My máme podepsané `sent`/`rejected` s pěti důvody ve commitované stopě. **Nikdy nestavět odvozený signál, když existuje přímý** |
| 2 | **provenience důkazu** | nemají — `gateguard` vynucuje zjišťování, ale nekontroluje ho zpětně | Krok 4 | naše nálezy mají pole `evidence[].source`; ECC nemá kam takovou kontrolu zavěsit |
| 3 | **vynucená fakta / druhá šance** | `gateguard` (PreToolUse blokuje první Edit, vyžádá si fakta; změřeno +2,25 z 10) | Kroky 5 a 7 | u nás většina packů zdroj needituje; přenáší se to na „než zapíšeš `findings.json`" |
| 4 | **druhý pár očí** | `council` (čtyři hlasy jako čerstvé subagenty), `agent-self-evaluation` (5osá rubrika) | Krok 8 — generický pack `verify` jako člen řetězu | `agency chain` to umí od 1. 9.; a na rozdíl od sebehodnocení to vyrábí tier `machine-confirmed`, který [`knowledge.py:307`](../../packages/core/src/agency/knowledge.py) **už umí spočítat a dnes ho skoro nic nevyrábí** |
| 5 | **eval místo dojmu** | `eval-harness`: pass@k / pass^k, regresní evaly, práh `pass@3 ≥ 0,90` | Krok 12 — `agency replay` | máme všechny součástky a nikdy jsme je nesložili: `target.headRefOid` je připnutý, worktree reprodukovatelný, `fingerprint` deterministický |
| 6 | **dohled za běhu** | `ecc-context-monitor`: vpichuje varování při ceně, vyčerpání kontextu a smyčce (5× týž nástroj) | Kroky 9 a 15 | proud čteme, `agent.denied` píšeme — chybí z toho něco vyvodit dřív než po konci |
| 7 | **just-in-time kontext** | `iterative-retrieval`: dispatch → evaluate → refine, max 3 kola | Krok 3 — krátký seznam místo retrieval smyčky | naše paměť jsou desítky nálezů, ne tisíce |

Osmý mechanismus si nebereme, protože ho máme: pravidlo z `growth-log` („zapiš vzorec, ne deník; hledej duplicitu dřív, než píšeš") je slovo od slova pravidlo, které každý náš `SKILL.md` opakuje pro `pages/<pack>/`, včetně `Last reviewed:` a kontroly stárnutí ([`knowledge.py:121`](../../packages/core/src/agency/knowledge.py)).

A jedna věc, kterou ECC nemá a my ji potřebujeme sami: **slovník pro „jsem zablokovaný"** (Krok 13). Obecný agent v konverzaci se prostě zeptá. Náš neattended specialista nemá koho, takže dnes buď hádá, nebo mlčí — a mlčení se nedá odlišit od úspěchu.

### Co z ECC nebrat

| co | proč ne |
|---|---|
| 286 skillů, 68 agentů, 94 příkazů | opak zadání; univerzální katalog je přesně to, co v1 mazala |
| instinktový sklad mimo repo (`~/.local/share/ecc-homunculus/`) | porušuje pravidlo „pravda bydlí v projektu". Co se pack naučí, musí jít commitnout a přečíst bez nástroje |
| konfidence rostoucí z „uživatel to neopravil" | falešný učitel; tichý souhlas není souhlas |
| profily hooků a ~40 ENV proměnných (`ECC_HOOK_PROFILE`, `GATEGUARD_*`) | konfigurace, kterou v1 zrušila. **Pozor na rozdíl:** zamítá se *konfigurovatelnost hooků*, ne hooky — viz Krok 0 a R5 |
| manifesty pro sedm harnessů | dva providery jako tabulka v `providers.py` řeší totéž o dva řády levněji |
| `SOUL.md`, `identity.json`, `WORKING-CONTEXT.md` jako sprint-deník | identita specialisty patří do jeho `SKILL.md`; „deník" je přesně to, co `pages/<pack>/` zakazují |
| `unified-memory` vault, MCP memory server | zamítnuto už v [`shared-memory.md`](shared-memory.md) §2, důvody se nezměnily |

---

## 3. Diagnóza — jedenáct míst, kde je náš strop

Kroky v §5 se na tahle čísla odkazují.

**D1 — Smyčka je otevřená.** [`metrics.py:241`](../../packages/core/src/agency/metrics.py) počítá `byDimension` a docstring modulu říká, k čemu to je: *„`precision 0.55` je k ničemu; `dimenze reuse 0.2, correctness 0.9` je pokyn vypnout jednu dimenzi."* Ten pokyn nikdo nevykoná. → Kroky 10, 11

**D2 — Zamítnutí je minulý nález, ne pravidlo.** `REJECT_REASONS` ([`runs.py:43`](../../packages/core/src/agency/runs.py)) má pět hodnot a jedna, `by-design`, znamená *tohle už nikdy nehlas*. Docstring `for_run` ([`knowledge.py:191`](../../packages/core/src/agency/knowledge.py)) to říká sám: *„this was already rejected as by-design is the most valuable sentence a new run can be handed."* A pak s tou větou zachází jako s řádkem v třísetprvkovém poli. → Krok 2

**D3 — Paměť se řeže stářím, ne tvarem.** `picked = all_findings[:300]` ([`knowledge.py:219`](../../packages/core/src/agency/knowledge.py)). BM25 ranker existoval (Fáze 7, `rank.py`) a Fáze 10 Krok 3 ho smazala. **To rozhodnutí zůstává v platnosti** — „desítky, ne tisíce" pořád platí. Jenže *pořadí* není *tvar*: chybí ne lepší řazení tří set položek, chybí **druhý, krátký seznam, který se přečte celý**. → Krok 3

**D4 — `evidence[].source` je nekontrolované tvrzení.** V `finding.v1` je to volný string. Agent smí napsat `"source": "agency graph impact --depth 2"`, **aniž to kdy spustil**, a nezkontroluje to nic — ani schéma, ani `ingest.gate`. Nejtišší díra v celé bráně. → Krok 4

**D5 — Brána váží schéma, ne sílu důkazu.** `finding.v1` chce `evidence` s `minItems: 1` a šesti rovnocennými `kind`. Dimenze `reuse` u `review-graph` stojí a padá na grafu — a projde s citací z README (`kind: doc`). → Krok 5

**D6 — `score` je volitelné.** V `finding.v1` nepovinné, `minScore` ([`packs.py:91`](../../packages/core/src/agency/packs.py)) default 70. Práh, kolem kterého se dá projít tím, že se mlčí. → Krok 6

**D7 — Zahozený nález je stoprocentní ztráta.** `counts.gated` se počítá, ale agent v tu chvíli už neexistuje. Napsal `findings.json`, skončil, brána to zahodila, nikdo běh neopakuje. → Krok 7

**D8 — Není známo, co agent skutečně měl, a není přehrání.** [`instructions.py`](../../packages/core/src/agency/instructions.py) umí najít kolizi `CLAUDE.md` × `needs`, ale používá ji jen `doctor` ([`cli.py:172`](../../packages/core/src/agency/cli.py)). `run.json` nedrží otisk `CLAUDE.md`, `SKILL.md` ani seznam evidence. *„Proč ten pack od úterý hůř soudí"* je nezodpověditelné — a v úterý mohl někdo přepsat `CLAUDE.md` v PR, který pack sám recenzoval. → Kroky 1, 12

**D9 — `no-findings` je přetížené a agent nemá slovník pro „nemůžu dál".** [`ingest.py:303`](../../packages/core/src/agency/ingest.py): `status = "ok" if kept else ("no-findings" if raw_count == 0 else "gated-out")`. Takže `no-findings` znamená současně *„autor napsal pack, což je správný výsledek"*, *„nic tu není"* a *„narazil jsem na zeď a nevěděl jsem, co dál"*. Agent nemá jak to třetí říct — buď hádá, nebo mlčí, a **mlčení se nedá odlišit od úspěchu.** → Krok 13

**D10 — Attended a unattended se v metrikách slévají.** §0.4: `turns`, `denied` a `cost` existují jen u streamovaných běhů. `metrics.collect` je počítá dohromady s attended běhy, kde jsou `null`, takže každé číslo o ceně a chování agenta je průměr přes populaci, jejíž půlka data nemá. → Krok 14

**D11 — Žádný strop na útratu.** `cost.wallClockSeconds` se zapisuje, žádná mez neexistuje. `runs.attend` má parametr `timeout`, ale pack nemá jak říct, co je u něj normální. PO běh v [`po-writes.md`](po-writes.md) hořel 41 minut a nerozhodl nic použitelného; nic to nehlásilo. → Krok 15

---

## 4. Tvarová rozhodnutí

**R1 — Učitel je rozhodnutá fronta, ne transkript.** Všechno učení stojí na `sent`/`rejected` s důvodem a podpisem. Odvozené signály (co agent psal, jak dlouho, kolikrát ho uživatel opravil) se nesbírají.

**R2 — Co se pack naučí, je diff v `SKILL.md`.** Žádný instinktový sklad, žádná druhá pravda vedle metody. Pack je zdroj → učení packu je změna zdroje → review je git.

**R3 — Do brány model nevstoupí.** `ingest` zůstává deterministický. Ověřování modelem je člen řetězu.

**R4 — Paměť se nezvětšuje, mění se její tvar.** Každý nový soubor v `evidence/` musí být malý a čtený. Kdo tam přidá třetí třísetprvkové pole, udělal opak toho, co tenhle plán chce.

**R5 — Hook je launch argument, ne konfigurace.** `claude --settings` bere **i JSON string přímo na příkazové řádce** — už ne „ověřeno v `--help`", ale ověřeno reálným během (Krok 0, 6. 9. 2026): hook se spustil a nikdo se na nic neptal. Hook se staví z `pack.json` a předává na spouštěcí řádce stejně jako `--model`. **Do projektu se nezapisuje žádný `settings.json`** a nic se neinstaluje do `~/.claude/`. Konfigurace je soubor, který někdo udržuje; tohle je odvozený argument.

**Důsledek, který sonda přidala:** pravidlo platí jen pro `claude`. `codex` hooky **má** — a tvarem tytéž — ale předat se dají jedině perzistentním `.codex/config.toml` v projektu, tedy přesně tou konfigurací, kterou tohle pravidlo zakazuje. Není to tedy „codex neumí hooky", je to „codex je neumí předat jako argument", a rozdíl se zapisuje do dat (R6), ne zamlčuje: `supportsHooks: False` v `providers.py` a `context.toolCalls: false` v záznamu běhu.

**R6 — Asymetrie se přiznává v datech, ne zamlčuje.** Platí pro hooky (jen `claude`), pro proud (jen unattended) i pro provenienci (jen když hook běžel). Cokoli, co nefunguje všude, **musí zapsat do `run.json`, jestli bylo aktivní** — jinak metriky míchají dvě populace a lžou. Zobecnění: *číslo bez populace, ze které pochází, je horší než žádné číslo.*

**R7 — Ticho není výsledek.** Běh, který skončil bez nálezů, musí umět říct, jestli nic nenašel, nebo nemohl pokračovat. → D9

**R8 — Šablony vzniknou samy, registr se nestaví.** Až budou `verify` a `author --revise`, je šablona pack s prázdnou sekcí *Project facts*. `packs/` už tím je.

---

## 5. Kroky

Každý krok: **jeden commit, testy zelené, pak další.**

---

### Krok 0 — sonda hooků (~3 h, žádný produkční kód)

**Proč:** Kroky 4, 7 a 9 stojí na tom, že hooky v našich bězích fungují a nikoho se na nic neptají. To se musí probovat, ne předpokládat — přesně jako se probovala MCP a trust otázka pro `agency serve`.

**Co ověřit, každé na reálném `claude` (2.1.258+), s přečtenou konzolí:**

| # | otázka | jak |
|---|---|---|
| 1 | Vezme `--settings` JSON string s `hooks` inline? | `claude -p --settings '{"hooks":{"Stop":[…]}}' "…"` |
| 2 | **Ptá se na schválení hooku?** ← nejdůležitější | totéž v adresáři, kde `claude` nikdy neběžel. Když se ptá, neattended běh visí — stejné selhání jako MCP dialog |
| 3 | Fungují hooky pod `-p` (neinteraktivně)? | Stop hook s `exit 2`; vidí agent stderr a dostane šanci reagovat? |
| 4 | Landují lifecycle události v proudu? | `--include-hook-events --output-format stream-json --verbose`, jaký to má tvar |
| 5 | Existuje `--append-system-prompt-file`? | v `--help` je zmíněný **jen uvnitř popisu jiného flagu**, jako vlastní položka není. Krok 2 na tom stojí |
| 6 | Interaguje `--setting-sources` s naším `--strict-mcp-config`? | worktree vs. workspace běh; cíl je symetrie z S4272 |
| 7 | Má `codex` cokoli ekvivalentního? | ECC má `hooks/codex-hooks.json` — je to tentýž mechanismus? |

**Výstup:** klíče a **komentáře s datem a konzolovým výstupem** v [`providers.py`](../../packages/core/src/agency/providers.py) — `hookFlag`, `hookEventsArgs`, `supportsHooks: bool`, ve stylu existujícího `noQuestionsArgs` a `trustFile`. Plus dopsaná odpověď do tohohle dokumentu.

**Hotovo, když:** u každé ze sedmi otázek je v `providers.py` věta začínající „Probed on 2026-09-…". **Když sonda #2 dopadne špatně** (ptá se), Kroky 4, 7 a 9 se dělají bez hooků: Krok 4 degraduje na část (b)+(c), Krok 7 vypadává a Krok 9 zůstane na `events.py`. Napiš to sem a pokračuj — neblokuj se na tom.

*(Doplněno po provedení: podmínka „všech sedm v `providers.py`" se splnit nedala doslova a nemá se předstírat, že ano. Odpovědi #1–#4, #6 a #7 tam jsou — nesou je komentáře u `supportsHooks`, `hookFlag` a `hookEventsArgs` u obou providerů. **Odpověď #5 tam není**, protože `--append-system-prompt` není tvar hooku, ale tvar doručení promptu, a klíč pro ni patří do Kroku 2; udělat ho už teď by znamenalo napsat kus Kroku 2 pod hlavičkou Kroku 0. Do té doby žije #5 jen v tabulce níž.)*

**Co NEdělat:** nezapisovat `settings.json` do žádného projektu. Neinstalovat nic do `~/.claude/`.

**Výsledek sondy (probed 2026-09-06, `claude` 2.1.263, `codex` 0.144.3):**

| # | otázka | odpověď |
|---|---|---|
| 1 | Vezme `--settings` JSON string s `hooks` inline? | Ano. `-p --settings '{"hooks":{"Stop":[…]}}' "…"` v adresáři, kde `claude` nikdy neběžel: hook doopravdy proběhl (zapsal soubor), žádný soubor se přitom nemusel dostat do projektu. |
| 2 | **Ptá se na schválení hooku?** | **Ne.** Stejný běh, stejný nikdy-neotevřený adresář, pod `-p`: žádný dialog o důvěře k adresáři (očekáváno — `-p` ho podle vlastní nápovědy přeskakuje) a hlavně žádný samostatný dialog "schval tenhle hook". Hook prostě proběhl. → Kroky 4, 7 a 9 se dělají **celé**, degradace z „Hotovo, když" se nepoužije. |
| 3 | Fungují hooky pod `-p`? | Ano, a vidí je i agent, ne jen orchestrátor. Stop hook, který napoprvé vrátí `exit 2` s `"missing field 'score'"` na stderr, donutil agenta přepsat `findings.json` (doplnil pole) a při druhém Stopu prošel. Vedlejší nález mimo sedm otázek: druhé (a další) volání téhož Stop hooku v běhu nese `"stop_hook_active": true` ve svém stdin payloadu — hotové pole pro dvojitou pojistku Kroku 7 místo počítání volání v orchestrátoru. |
| 4 | Landují lifecycle události v proudu? | Ano. S `--include-hook-events` navíc ke `streamArgs` přibudou v `stream-json` proudu řádky `{"type":"system","subtype":"hook_started"|"hook_response","hook_name":…,"hook_event":…}` — přečteno z reálného proudu (8 takových řádků na jeden nakonfigurovaný Stop hook), ne z nápovědy. |
| 5 | Existuje `--append-system-prompt-file`? | **Ne jako funkční flag.** V `--help` je vidět jen uvnitř popisu `--bare`, přesně jak plán čekal. Skutečný běh s `--append-system-prompt-file soubor` chybu nevrátí (na rozdíl od vymyšleného flagu, který spolehlivě spadne na `error: unknown option`), ale obsah souboru se do system promptu nedostane — ověřeno magic-stringem, který se model zeptaný "obsahuje tvůj system prompt tenhle řetězec" nenašel. `--bare` (kde nápověda flag zmiňuje) vyžaduje API-key auth, tahle instalace běží na OAuth, takže se nedalo dotestovat i s `--bare`. Krok 2 jde fallbackem (b): `--append-system-prompt "<obsah>"` inline — to funguje, stejný magic-string test ho tentokrát našel. |
| 6 | Interaguje `--setting-sources` s `--strict-mcp-config`? | Ne, jsou nezávislé, a worktree se v tomhle nechová jinak než hlavní checkout. Projektový `.claude/settings.json` se Stop hookem naběhl stejně v hlavním checkoutu i v čerstvém `git worktree` z téhož repa, s `--strict-mcp-config` i bez něj. `--setting-sources local` (bez `project`) hook v obou správně potlačil; `--setting-sources project` ho v obou vrátil. |
| 7 | Má `codex` cokoli ekvivalentního? | Typy hooků ano — `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SubagentStart`, `UserPromptSubmit`, `PermissionRequest` se našly jako řetězce přímo v binárce 0.144.3, tvarem kompatibilní s claude. Doručení jako launch argument ne: `codex --help`/`codex exec --help` nemá nic jako `--settings`; hooky se čtou z perzistentního `.codex/config.toml` v projektu a hlídá je vlastní "hook trust" — binárka nese text `„…' hooks need review before they can run."` a `--dangerously-bypass-hook-trust` ho obchází ("DANGEROUS. Intended only for automation that already vets hook sources"). Zapsat `.codex/config.toml` do cílového projektu je přesně to, co R5 zakazuje, proto `supportsHooks: False` u `codex` — není to chybějící vlastnost, je to chybějící způsob doručení. |

**Doprobováno nad rámec sedmi otázek**, protože na tom Krok 4 stojí a nikdo se na to neptal: **PostToolUse hook** se pouští stejnou cestou (`--settings`, `-p`) a jeho payload nese `tool_input.command` — tedy doslovný příkaz, ne jen jméno nástroje. Bez toho by provenience neměla co porovnávat. Přesný tvar payloadu a dvě opravy, které z něj plynou, jsou v Kroku 4.

**Mimochodem znovu potvrzeno:** `--allowedTools` je variadický a spolkl pozicní prompt (`Error: Input must be provided…`), dokud se nepřidalo `--`. To už `providers.py` ví jako `promptSeparator`; sonda do té pasti spadla znovu, což je dobrá zpráva o tom komentáři, ne o mně.

**Rozhodnutí:** sonda #2 dopadla dobře → Kroky 4, 7 a 9 se dělají celé. Klíče `hookFlag`, `hookEventsArgs`, `supportsHooks` jsou zapsané v [`providers.py`](../../packages/core/src/agency/providers.py) u obou providerů, s probed komentáři včetně přesných příkazů a výstupu.

---

## Fáze A — záznam, vstup a poctivé měřidlo

> Nepotřebuje žádná nová data. Nejlepší poměr užitku k práci v celém plánu. Kdyby se mělo udělat jen něco, je to tahle fáze.

### Krok 1 — otisk kontextu do `run.json` (~3 h) → D8

**Proč:** bez něj nemá žádný pozdější krok nezávislou proměnnou. „Precision klesla" je bez toho nezodpověditelná otázka.

**Napřed schéma** ([`schemas/run.v1.json`](../../schemas/run.v1.json), past 0.3):

```json
"context": {
  "type": "object",
  "description": "What the agent actually had. Without it, 'why did this pack get worse' has no independent variable.",
  "additionalProperties": false,
  "properties": {
    "instructions": {
      "type": "array",
      "description": "CLAUDE.md / AGENTS.md as they were in the run's cwd. Loaded by the runner itself, never by Agency — recorded so a rewrite of the house rules is visible next to the precision it changed.",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["path", "sha256", "bytes"],
        "properties": { "path": {"type":"string"}, "sha256": {"type":"string"}, "bytes": {"type":"integer"} }
      }
    },
    "skill": {
      "type": ["object", "null"], "additionalProperties": false,
      "required": ["path", "sha256"],
      "properties": { "path": {"type":"string"}, "sha256": {"type":"string"}, "references": {"type":"integer"} }
    },
    "evidence": {
      "type": "array",
      "items": { "type": "object", "additionalProperties": false,
        "required": ["name", "bytes"],
        "properties": { "name": {"type":"string"}, "bytes": {"type":"integer"}, "items": {"type":["integer","null"]} } }
    },
    "promptBytes": { "type": ["integer", "null"] },
    "conflicts": {
      "type": ["integer", "null"],
      "description": "CLAUDE.md x pack needs collisions at the moment of the run. `doctor` reports these before a run; nothing recorded that the run then happened under one."
    },
    "toolCalls": {
      "type": "boolean",
      "description": "Whether the PostToolUse hook was active (R6). A gate stage that depends on it must not silently treat these runs and hook-less runs as one population."
    }
  }
}
```

**Pak kód:** `runs.write_context` sbírá otisky (sha256 souborů), `runs.attend` doplní, co je známé až po startu. `instructions.paths(root)` a `instructions.conflicts(root, by_tool)` už existují — použij je, nepiš je znovu.

**Testy:** `tests/test_run_record.py` — běh nad `project` fixturou má vyplněný `context`; `tests/test_instructions.py` — `conflicts` se do záznamu dostane číslem, ne textem.

**Hotovo, když:** `agency metrics --by skill` umí rozdělit precision podle `context.skill.sha256`. To je doslova A/B test packů, postavený z jednoho hashe.

---

### Krok 13 — `blocked` jako plnohodnotný výsledek běhu (~4 h) → D9, R7

*(Číslo je 13, aby se dřívější čísla neposouvala; pořadí určuje §6. Tenhle krok je ve Fázi A schválně — je to kontrakt, je levný, a od něj se odvíjí, jak se čte každý běh, který nic nenašel.)*

**Proč:** dnes agent, který narazil na zeď — staging neběží, `gh` není přihlášené, board nemá pole, které `SKILL.md` předpokládá — nemá jak to říct. Napíše `findings.json: []` a skončí jako `no-findings`, tedy stejně jako pack, který poctivě nic nenašel, a stejně jako autor, u kterého je to správný výsledek. **Ticho se nedá odlišit od úspěchu**, a dokud to platí, nemá smysl pouštět nic bez dozoru.

**Kontrakt — jeden nový soubor a jeden stav:**

```
RUN_DIR/blocked.md      napíše agent, když nemůže pokračovat
```

Tvar (do `SKILL.md` každého packu jako povinná sekce, a do `packs/author/` jako věta, kterou autor do nových packů píše):

```markdown
# Blocked

**What I could not do:** verify the cancellation flow on staging.
**Why:** https://staging.example.com returned 502 on every attempt (12 tries, 10 min).
**What would unblock me:** a staging URL that answers, or permission to run it locally.
**What I did instead:** nothing — the remaining dimensions all depend on this one.
```

**Kód:**

- `run.v1` → `status` enum přibude `"blocked"`; `outputs` přibude `"blocked": {"type":"boolean"}` vedle `summary` a `handoff`.
- [`ingest.py:303`](../../packages/core/src/agency/ingest.py) — větev napřed: existuje-li `blocked.md`, status je `blocked` bez ohledu na `raw_count`, a `exitReason` nese první řádek *What I could not do*. Nálezy, které agent přesto napsal, projdou branou normálně — zablokovaný běh může mít částečný výsledek a zahodit ho by bylo horší.
- `agency status` a `findings` to odlišují barvou i slovem; extension ukazuje `blocked.md` stejným tlačítkem jako `summary.md`.
- **Řetěz na `blocked` členu zastaví** a napíše proč. Dnes by pokračoval s prázdným handoffem, což je nejdražší způsob, jak se nic nedozvědět.

**Co to NENÍ:** není to způsob, jak se agent ptá a čeká na odpověď. Neattended běh se zeptat nemůže a nic tady na to nečeká. Je to **výsledek**, ne dialog — a navazuje se na něj `agency follow` (§0.4), nebo novým během, až je překážka pryč.

**Testy:** `tests/test_gate.py` — `blocked.md` + 0 nálezů → `status: "blocked"`, ne `no-findings`; `blocked.md` + 2 platné nálezy → `blocked` a `counts.kept == 2`. `tests/test_chain.py` — zablokovaný první člen zastaví řetěz s vysvětlením.

**Hotovo, když:** běh nad vypnutým stagingem skončí jako `blocked` s větou, kterou zakladatel přečte a hned ví, co má opravit — místo dnešního `no-findings`, které vypadá jako „všechno v pořádku".

---

### Krok 14 — attended a unattended jsou dvě populace (~4 h) → D10, R6

**Proč:** §0.4. Dnes `metrics.collect` počítá průměry přes populaci, jejíž polovina nemá data. Číslo, které vzniklo z pěti unattended a dvaceti attended běhů, není o ničem.

**Co se mění:**

1. **`metrics` řeže podle `trigger.attended`.** Precision se počítá přes všechny (nálezy a rozhodnutí attended běh má, ta část je poctivá). **Cena, tahy a odmítnutí se počítají jen z unattended** a výstup u nich píše, z kolika běhů — `usd — from 5 of 24 runs (streamed only)`. Nikdy nevykazovat `null` jako nulu; `_ratio` už tuhle disciplínu má a její docstring ji vysvětluje.
2. **`agency status` říká, kolik běhů je „slepých"**, jednou větou: *„19 of 24 runs were attended and recorded no cost or turns."* To je informace, podle které se člověk rozhodne běhat jinak.
3. **`--wait` bez `--unattended` dostane jednorázovou poznámku** při startu: co se nezaznamená a čím to zapnout. Ne varování, ne otázka — jedna řádka, protože to je volba, ne chyba.

**Co se NEmění:** attended běh zůstává výchozí a plnohodnotný. Tohle není tlak na unattended, je to přiznání, co která volba stojí. Kdo chce dohled, má ho mít bez toho, aby mu to nástroj vyčítal.

**Testy:** `tests/test_anchor_metrics.py` (nebo nový) — dva attended a jeden unattended běh: `usd` se počítá z jednoho a výstup to říká; precision ze všech tří.

**Hotovo, když:** `agency metrics` u každého čísla o ceně a chování agenta uvádí, z kolika běhů pochází — a `agency status` řekne, kolik jich je slepých.

---

### Krok 2 — `do-not-report.md` a jeho **doručení** (~5 h) → D2

**Proč:** nejcennější věta v paměti je pohřbená v poli. A ECC k tomu má měřenou poznámku, kterou stojí za to vzít vážně: *skilly vystřelí v 50–80 % případů, hooky ve 100 %.* Vyrobit soubor a doufat, že si ho agent přečte, je polovina práce.

**a) generování.** `knowledge.for_run` vedle `known-findings.json` vygeneruje **markdown**, ne JSON, protože se to má číst, ne parsovat. Zdroj je stopa (`trail.jsonl` — commitovaná, přežije zahození běhu), filtr `state: "rejected"`, seskupení podle důvodu:

```markdown
# What this project has already rejected

Do not report these again. Each carries the reason a person or a chain
member rejected it, and a link to the finding where the full context is.

## by-design (4)
- Session is not cleared when the tab closes — that is the design. (`findings/01K…`)
- …

## wrong-diagnosis (2)
- …
```

Strop 40 řádků. Když se to nevejde, řeže se podle stáří **uvnitř důvodu**, aby `by-design` nikdy nezmizel celý — to je kategorie, která znamená „už nikdy", zatímco `not-reproducible` může být zítra jinak.

**b) doručení.** Sonda 0/#5 jednu z větví škrtla: **`--append-system-prompt-file` neexistuje** jako funkční flag (nespadne, ale obsah souboru se do promptu nedostane — proto se na „nespadlo to" nedá spolehnout jako na důkaz). Zbývá:
- `--append-system-prompt "<obsah>"` inline — ověřeno, že se do system promptu opravdu dostane. **Zbývá doprobovat limit délky argumentu na Windows**; 40 řádků se vejít má, ale nikdo to nezměřil, a `CreateProcess` má strop ~32 kB na celou příkazovou řádku, do které se počítá i `--allowedTools`. Když se ukáže, že se to nevejde, není to důvod psát soubor do projektu — je to důvod strop 40 řádků snížit;
- pro `codex` fallback: klíč `doNotReport` v `context.json` a věta v `SKILL.md`. Slabší doručení — zapiš to do `context.evidence` (R6).

**Proč tu není hook**, když Krok 0 potvrdil, že fungují: `--append-system-prompt` je stejně stoprocentní kanál jako hook — text je v system promptu, ne ve skillu, který si agent má vzpomenout přečíst. ECC poznámka o 50–80 % platí na skilly; tady se jí vyhýbáme levněji.

**Testy:** `tests/test_knowledge.py` — stopa se třemi zamítnutími vyrobí markdown se třemi řádky ve správných sekcích; strop řeže uvnitř důvodu, ne napříč. `tests/test_unattended.py` — launch argv obsahuje doručovací flag.

**Hotovo, když:** nález jednou zamítnutý jako `by-design` se nevrátí ve dvou po sobě jdoucích bězích téhož packu nad tímtéž kódem. Dnes se vrací — dedup ho chytí až po ingestu, tedy až po tom, co agent utratil čas na jeho odvození.

---

### Krok 3 — `evidence/known-here.json` (~3 h) → D3

**Proč:** běh nad PR, který sahá na `src/payments/`, potřebuje spíš dvanáct nálezů, které se kdy plateb týkaly, než tři sta nejnovějších.

**Co se mění:** `for_run` vyrobí druhý, malý seznam — nálezy, jejichž `anchor.file` leží v `context.files` tohoto běhu, případně jejichž `anchor.symbol.name` je v grafovém impact setu, který [`runs.collect_evidence`](../../packages/core/src/agency/runs.py) už počítá (`evidence/impact.json`). Tvar položky je stejný `_view` jako u `known-findings.json` — ať konzument nemusí umět dva tvary. Bez stropu (budou to jednotky), s rozhodnutím u každého.

**To není návrat rankeru** (D3). Ranker měnil pořadí tří set položek a byl smazán vědomě; tohle přidává krátký seznam a `known-findings.json` nechává být.

**Testy:** `tests/test_knowledge.py` — nález ukotvený v souboru, kterého se běh dotýká, je v `known-here.json`; nález mimo něj ne. Prázdný seznam se nezapisuje (soubor, který je vždycky prázdný, se přestane číst).

**Hotovo, když:** běh nad PR do souboru s historií tu historii dostane v souboru pod 50 položek a `run.json` to vykáže jako `context.evidence[].items`.

---

## Fáze B — palivo

> Kód je za dva dny. Pak to **běží** a rozhodnuté nálezy se hromadí, zatímco se dělá Fáze C. Proto to jde před bránu.

### Krok 8 — pack `verify` (~1 den) → palivo pro D1

**Proč:** tier `machine-confirmed` ([`knowledge.py:307`](../../packages/core/src/agency/knowledge.py)) je spočítaný, popsaný — a vzniká jen náhodou, když dva různí workeři najdou totéž. Chybí člen, který ho vyrábí schválně. A hlavně: **tohle je jediný krok, který sám vyrábí rozhodnutá data**, na kterých stojí celá Fáze D.

**Co to je:** druhý generický pack — jeho předmět je tenhle systém, ne konkrétní projekt, takže se jako `author` dodává s jádrem (`pyproject.toml` → `force-include`) a `agency init` ho zkopíruje.

```
agency chain review-graph verify --pr 479
```

`verify` dostane nálezy prvního člena jako **brief** (`knowledge.upstream` už to umí) a pro každý:

1. otevře `anchor.file:line` na `target.headRefOid` a přečte, co tam je;
2. **odvodí tvrzení znovu z kódu**, ne z těla nálezu — tělo je to, co se ověřuje, ne zdroj;
3. rozhodne `agency triage accept` / `reject --reason <jeden z pěti>`.

**Hranice v `SKILL.md`, které se nehýbou:** nesmí psát vlastní nálezy (kdo ověřuje, nenachází — jinak si ověřuje sám sebe); nesmí sahat na zdroj; **nesmí dostat transkript prvního běhu**, jen nálezy a kód; běží vždy neattended, protože je to člen řetězu.

**Proč ne sebehodnocení:** ECC má obojí (`agent-self-evaluation`, `council`) a rozdíl je v tom, co drží. Sebehodnocení má agent v témže kontextu, ve kterém nález vymyslel — a `gateguard` doložil, že se sebehodnocení odpovídá „ano, jsem si jistý". Čerstvý kontext, který nález nevymyslel, je jediné, co má šanci ho vyvrátit.

**`pack.json`:** `target: "pull-request"`, `worktree: true`, `graph: true`, `prompt: "none"`, `needs` s `agency triage`, `agency note`, `agency graph`, `git`. Bez `sink` — `verify` nic neposílá, jen rozhoduje.

**Testy:** `tests/test_chain.py` — `verify` jako druhý člen dostane upstream nálezy a jeho `triage` se propíše do `decisions.jsonl` s `by: "hire:verify@claude"`; `tests/test_ledger.py` — po přijetí vzniká tier `machine-confirmed`.

**Hotovo, když:** `agency chain review-graph verify --pr <n>` nad reálným PR v `main-panelu` doběhne, `agency knowledge` ukáže aspoň jeden `machine-confirmed`, a `agency metrics` vykáže precision `verify` samotného — **ověřovatel, který přijme všechno, je stejně k ničemu jako ten, který zamítne všechno**, a bez toho čísla se to nepozná.

---

### Krok 9 — živý dohled nad během (~4 h) → D8

**Proč:** [`events.summarize`](../../packages/core/src/agency/events.py) proud už čte a `agent.denied` do záznamu píše. Dozvíme se to ale až po konci — u dvacetiminutového běhu dvacet minut pozdě. (Jen unattended, §0.4 — Krok 14 už zajistil, že se to nevydává za víc.)

**Co se mění:** `runs.attend` dostane tři odvozené signály nad proudem, který už parsuje:

| signál | práh | co se stane |
|---|---|---|
| **smyčka** | 5× po sobě týž nástroj s týmiž argumenty | řádek do terminálu i na telefon; `run.json` → `agent.loops` |
| **záplava odmítnutí** | 3 odmítnutí téhož příkazu | řádek s návrhem, co chybí v `needs` |
| **nulový postup** | žádný zápis do `RUN_DIR` po N tazích | řádek |

Práh 5 je z ECC (`LOOP_THRESHOLD`; jejich poznámka: při 3 to falešně střílelo na legitimní retry a polling). Vezmi ho i s tím zdůvodněním.

**Nic nezabíjí a na nic se neptá** (§0.5). Odmítnutí uzavírají druhou smyčku: `doctor` nebo `metrics` může říct *„pack `qa` žádá `npm run verify` a je odmítnut ve třech bězích ze čtyř"* — návod, co dopsat do `needs`, dnes dohledatelný jen ručně z `agent.md`.

**Co sonda mění na vstupu tohohle kroku:** jakmile Kroky 4 a 7 zapnou hooky, poteče stejným proudem i `--include-hook-events` (Krok 0/#4), tedy řádky `{"type":"system","subtype":"hook_started"}` a `{"…":"hook_response"}` **proložené mezi tahy agenta** — v sondě jich na jeden nakonfigurovaný Stop hook bylo osm. Dvě věci z toho plynou a obě patří do tohohle kroku, ne až do Kroku 4:

1. **`events.py` je nesmí považovat za tah.** Neznámý `subtype` musí propadnout, ne spadnout a ne se počítat do `turns` — jinak Krok 15 srovnává rozpočet s číslem, které roste podle toho, kolik má pack hooků. To je přesně past §0.3/#3 naruby: data, o která nikdo nepožádal, tentokrát přitečou sama.
2. **`hook_response` nese `stdout`/`stderr`**, takže je to jediné místo, odkud jde přečíst, že Stop hook zablokoval — vstup pro `agent.stopBlocks` z Kroku 7.

**Schéma:** `agent.loops` do `run.v1` (past 0.3).

**Testy:** `tests/test_unattended.py` — nakrmený JSONL s pěti stejnými voláními vyrobí `agent.loops == 1`; čtyři nikoli.

**Hotovo, když:** běh, který se zacyklí na `Read` téhož souboru, má `agent.loops ≥ 1` a člověk u terminálu to viděl, když se to dělo.

---

### Krok 15 — rozpočet v `pack.json` (~4 h) → D11

**Proč:** PO běh hořel 41 minut a nerozhodl nic použitelného. Nikdo to nevěděl, dokud neskončil, a pak už to bylo jen číslo v záznamu. Pack ví, co je u něj normální — nikdo se ho neptá.

**Co se mění:**

```json
"budget": { "turns": 60, "minutes": 25 }
```

Obojí volitelné. Chování ve třech pásmech, protože „zabij ho" a „nedělej nic" jsou obě špatné odpovědi:

| pásmo | co se stane |
|---|---|
| do rozpočtu | nic |
| přes rozpočet | řádek do terminálu i na telefon, `cost.overBudget: true` v záznamu. **Běh pokračuje** — může být zrovna uprostřed zápisu `findings.json` |
| **3× rozpočet** | tvrdý stop jako runaway pojistka, `status: "failed"`, `exitReason` to říká |

Trojnásobek je jediná výjimka z pravidla „nezabíjet na heuristiku" (§0.5) a je odůvodněná tím, že to není heuristika: je to číslo, které pack sám deklaroval, a trojnásobek deklarované normy už není odchylka, je to porucha. `runs.attend` na to má parametr `timeout` — použij ho, nepiš druhou cestu.

**Rozpočet se vynucuje jen tam, kde je co měřit:** `minutes` jde všude (`wallClockSeconds` se měří i u attended), `turns` jen u streamovaných běhů (R6).

**Vedlejší efekt, který je vlastně hlavní:** `metrics` může spočítat **cenu na přijatý nález** — `usd / counts.sent`, po packech a modelech. Jedno číslo, které mění rozhodnutí o modelu, a dnes ho nikdo nemá, přestože obě strany zlomku se zapisují.

**Schéma:** `cost.overBudget` do `run.v1` (past 0.3).

**Testy:** `tests/test_wait.py` — běh přes rozpočet dostane `overBudget` a doběhne; přes trojnásobek skončí `failed` s důvodem.

**Hotovo, když:** `agency metrics --pack po` vypíše cenu na přijatý nález, a běh, který přeteče, to řekne, když se to děje.

---

## Fáze C — brána

### Krok 4 — provenience důkazu (~6 h) → D4

**Proč:** nejtišší díra v bráně a zároveň to, co ECC nemá kam pověsit. Dnes je `evidence[].source` tvrzení; tímhle se z něj stává fakt.

**a) sběr.** PostToolUse hook (přes `--settings` z Kroku 0, R5) zapisuje každé volání do `RUN_DIR/tool-calls.jsonl`. **Sonda 6. 9. 2026 ho spustila naostro** a payload, který hook dostane na stdin, vypadá takhle (klíče doslova, ne z hlavy):

```json
{"hook_event_name":"PostToolUse","tool_name":"Bash","tool_use_id":"…","cwd":"…",
 "session_id":"…","duration_ms":128,
 "tool_input":{"command":"echo PROVENANCE-PROBE","description":"Echo probe marker"},
 "tool_response":{"stdout":"PROVENANCE-PROBE","stderr":"","interrupted":false}}
```

**Dvě opravy proti tomu, co v tomhle plánu stálo dřív:**

- **`exitCode` v payloadu není.** Byl v původním příkladu vymyšlený. Co tam je: `tool_response.stdout` / `.stderr` / `.interrupted`. Provenienci to nevadí — otázka zní „spustil ten příkaz", ne „uspěl" — ale zapisovaný řádek musí odpovídat tomu, co hook doopravdy dostane. Čas si dopiš sám (`at`), payload ho nenese.
- **PostToolUse se pouští jen po volání, které proběhlo.** Odepřené volání záznam nevyrobí, což je pro provenienci správně: „spustil jsem graf" má být false, když ho brána nepustila.

Kam se má zapisovat, hook vědět nemusí a **žádnou ENV proměnnou na to nepotřebuje**: cesta k `RUN_DIR` se zapeče přímo do příkazu hooku ve chvíli, kdy Agency staví `--settings`. Ověřeno stejnou sondou — hook s absolutní cestou v příkazu psal tam, kam měl.

**b) kontrola v bráně.** Nový důvod v `GATE_REASONS` ([`ingest.py:31`](../../packages/core/src/agency/ingest.py)): `unproven-source` — *„evidence cites a command that never ran in this run"*.

**Tři pojistky, bez kterých to bude zahazovat poctivé nálezy:**

1. **Kontroluje se jen `source`, který vypadá jako příkaz.** `"agency graph impact --depth 2"` ano; `"CLAUDE.md#rules-that-will-bite-you"` je odkaz na dokument a musí projít. Rozhodovací pravidlo napiš explicitně (prefix `agency `, `git `, `gh `, `npx `, `npm `), ne heuristiku „obsahuje mezeru".
2. **Kontroluje se jen tehdy, když `tool-calls.jsonl` existuje.** Codex běh (`supportsHooks: False`, R5), attended běh → soubor není → **kontrola se přeskočí celá**. Nikdy nezahazovat nález proto, že hook neběžel. Sonda #2 tuhle pojistku *nezrušila* — jen z ní ubrala jeden důvod; zbylé dva zůstávají a jsou trvalé.
3. **`context.toolCalls` v `run.json`** říká, jestli byla aktivní (R6).

**Porovnání je volné, ne přesné na znak:** normalizuj bílé znaky a porovnávej prefix příkazu plus podmnožinu argumentů. Agent, který napsal `--depth 2` a spustil `--depth 3`, lže o detailu, ne o tom, že graf viděl.

**Testy:** nový `tests/test_provenance.py` — (a) `source` s příkazem, který v `tool-calls.jsonl` je → projde; (b) není → `unproven-source`; (c) `source` s dokumentem → projde vždy; (d) `tool-calls.jsonl` chybí → projde všechno a `context.toolCalls == false`.

**Hotovo, když:** ručně zfalšovaný `source` skončí jako `unproven-source` a `metrics` ten důvod vykáže. ~~Když sonda 0/#2 dopadla špatně, dělá se jen část (b) a (c).~~ **Sonda dopadla dobře, krok se dělá celý včetně (a).** Připravená kolej z (b)+(c) tím ale nezaniká: je to pořád ten stav, ve kterém běží codex a attended běhy.

---

### Krok 5 — důkaz podle dimenze (~3 h) → D5

**Co se mění:** dimenze v `pack.json` smí říct, čím se dokazuje:

```json
{ "id": "reuse", "title": "Code nothing points at", "evidence": ["graph"] }
```

`ingest.gate` dostane důvod `weak-evidence`: dimenze má seznam a v `finding.evidence[]` není ani jeden prvek s odpovídajícím `kind`. Dimenze bez klíče `evidence` se chová jako dnes — zpětná kompatibilita zadarmo.

`packs.Pack.dimensions` ([`packs.py:87`](../../packages/core/src/agency/packs.py)) klíč jen propustí; validace patří do brány, ne do načítání packu.

**Testy:** `tests/test_gate.py` — dimenze s `["graph"]` zahodí nález s `kind: "doc"` a pustí ten s `kind: "graph"`; dimenze bez klíče pustí obojí.

**Hotovo, když:** `review-graph` s `"evidence": ["graph"]` u dimenze `reuse` zahodí nález, který o grafu jen mluví, a `metrics` ten důvod vykáže.

---

### Krok 6 — `score` povinné a odůvodněné (~2 h) → D6

**Co se mění:** `score` v `finding.v1` do `required`; přibude `scoreReason` (max ~200 znaků, jedna věta: *co by muselo být jinak, aby to skóre bylo nižší*). Chybějící skóre zahazuje brána jako `schema` — schéma je správné místo, nedělej nový důvod.

**Vedlejší efekt, který je vlastně hlavní:** `metrics` může porovnat rozdělení skóre proti precision. Pack, který dává všemu 90 a má precision 0,4, je kalibračně rozbitý a je to vidět na jednom čísle.

**Migrace:** starší `findings.json` bez `score` v uzavřených bězích se neopravují — `agency validate --fix` je nechává být a `metrics` je počítají do starší populace (R6). Napiš to do docstringu, ať se to nezkouší.

**Testy:** `tests/test_gate.py` — nález bez `score` padá jako `schema`. `tests/test_anchor_metrics.py` — průměrné skóre přijatých vs. zamítnutých.

**Hotovo, když:** `agency metrics --pack qa` vypíše obě čísla. Když se neliší, skóre nic neměří a je to konečně vidět.

---

### Krok 7 — Stop hook: druhá šance uvnitř běhu (~5 h) → D7

**Závisel na sondě 0/#2 a #3. Obě dopadly dobře — krok se dělá, a to celý.** Navíc už není teoretický: sonda ho 6. 9. 2026 předvedla od začátku do konce v malém. Agent zapsal soubor, Stop hook vrátil `exit 2` s větou *„missing required field 'score'"* na stderr, **agent tu větu přečetl, soubor přepsal a doplnil chybějící pole**, a druhý Stop prošel. To je přesně mechanika tohohle kroku; zbývá ji napojit na `finding.v1` místo na vymyšlené pole.

**Proč:** `counts.gated` je dnes stoprocentní ztráta. Agent napsal, skončil, brána zahodila, nikdo neopakuje. Stop hook, který validuje `findings.json` proti `finding.v1` a vrátí chyby na stderr s `exit 2`, dá agentovi šanci to opravit, dokud je kontext živý.

**Co hook dělá:** jen validaci schématu a existenci anchoru (`_schema_errors`, `_exists_at_commit` — obojí v [`ingest.py`](../../packages/core/src/agency/ingest.py) už je; **volej to, nepiš znovu**). Ne dedup, ne skóre, ne provenienci — ty vyžadují stav mimo běh a patří do brány.

**Dvě pojistky proti smyčce:**

1. **Nejvýš dvě zablokování na běh.** Potřetí projde a nechá to na bráně. ECC má na tentýž problém `GATEGUARD_FACT_FORCE_FULL_DENIALS` a je to poučení, ne detail: hook, který umí blokovat donekonečna, vyrobí běh, který donekonečna nedoběhne.
2. **Počet zablokování do `run.json`** (`agent.stopBlocks`). Pack, který potřebuje dvě kola pokaždé, má špatně napsaný `SKILL.md` — vstup pro Krok 11.

**Co k tomu sonda přidala — počítadlo je z poloviny hotové.** Stop hook dostává na stdin `"stop_hook_active": bool`: při prvním Stopu v běhu `false`, při opakovaném `true` (viděno na reálném payloadu). Na jedno zablokování tedy stačí samo pole a hook nemusí nic držet mezi voláními. Na *dvě* to nestačí — `true` znamená „už jsem jednou blokoval", ne „blokoval jsem dvakrát" — takže druhé kolo pořád potřebuje počítadlo. To počítadlo ale stejně musí vzniknout, protože se z něj plní `agent.stopBlocks`; **nedělej dvě cesty, piš rovnou počítadlo a `stop_hook_active` použij jen jako kontrolu, že se čte tentýž běh.**

**Druhá věc zadarmo:** s `--include-hook-events` (Krok 0/#4) jsou v proudu řádky `{"type":"system","subtype":"hook_response","stdout":…,"stderr":…}`. `agent.stopBlocks` se z nich dá odvodit v `events.py` **bez toho, aby hook psal vedlejší soubor** — a bez souboru navíc odpadá past §0.3/#3 (soubor, který nikdo nečte).

**Testy:** hook nad neplatným `findings.json` vrátí 2 a chybové hlášky; nad platným 0; potřetí 0 bez ohledu na obsah.

**Hotovo, když:** `counts.gated` klesne mezi dvěma běhy téhož packu nad srovnatelným PR — a když neklesne, je v `agent.stopBlocks` vidět, jestli hook vůbec střílel.

---

## Fáze D — smyčka

> **Nezačínej, dokud nemá revidovaný pack aspoň ~10 rozhodnutých nálezů.** Není to varování, je to podmínka: pack s pěti nálezy, o kterých nikdo nerozhodl, nemá z čeho se učit a revize z něj udělá jen jinak náhodný pack.

### Krok 10 — `agency metrics --for-author <pack>` (~5 h) → D1

**Proč:** most mezi číslem a revizí. Krok 11 potřebuje brief, ne dashboard.

**Co se mění:** nový výstup `metrics`, který **není pro člověka u terminálu, ale pro agenta jako vstup**. JSON + markdown do `RUN_DIRu` revizního běhu:

- precision po dimenzích **s počty** (dimenze s jedním rozhodnutým nálezem není signál a musí to být vidět);
- **z které populace každé číslo je** (Krok 14) — brief, který míchá attended a unattended, vede k revizi opřené o průměr přes prázdno;
- dimenze, které za posledních N běhů nevystřelily ani jednou — kandidát na smazání;
- top důvody zahození branou po dimenzích (`GATE_REASONS`) — `weak-evidence` a `unproven-source` budou nejužitečnější;
- zamítnutí s důvody a **po třech vzorcích textu přijatých i zamítnutých nálezů** (kanonické příklady, ne katalog — Anthropic o few-shotu: *„diverse, canonical examples"*, ne edge cases nacpané do promptu);
- odmítnuté příkazy z Kroku 9, `agent.stopBlocks` z Kroku 7, `cost.overBudget` a cena na přijatý nález z Kroku 15;
- **běhy, které skončily `blocked`, a proč** (Krok 13) — opakovaná překážka je vada `SKILL.md` nebo `needs`, ne vada projektu;
- `pages/<pack>/`, které jsou `stale` ([`knowledge.py:121`](../../packages/core/src/agency/knowledge.py));
- **otisky `SKILL.md` z Kroku 1 a precision u každého** — „co se stalo po poslední změně metody".

**Hotovo, když:** brief jde přečíst a **člověk podle něj dokáže sám říct, co v `SKILL.md` opravit.** Jestli to nedokáže člověk, nedokáže to ani agent a Krok 11 nemá smysl začínat. Nejtvrdší podmínka v celém plánu a je tu schválně.

---

### Krok 11 — `agency run author --revise <pack>` (~1 den) → D1, R2

**Proč:** tady se smyčka zavírá. Kvůli tomuhle kroku má dokument smysl.

**Co se mění:** autor umí druhý režim — nepíše nový pack, **reviduje existující**. Dostane brief z Kroku 10, `SKILL.md` a `pack.json` revidovaného packu, a napíše do nich **diff**.

| smí měnit | nesmí |
|---|---|
| dimenze (přeformulovat, rozdělit, smazat) | `sink`, `needs`, `name` |
| `evidence` u dimenze (Krok 5) | cokoli mimo `.claude/skills/agency-<pack>/` |
| `minScore`, `budget` (Krok 15) | fakta, která tenhle běh nepřečetl v repu nebo mu je neřekl zakladatel |
| *Project facts* — jen ověřená fakta | jiný pack |

Tvar výstupu je ten, co autor už má a co je odzkoušené: **necommitnutý zdroj v pracovním stromu**, `summary.md` s odůvodněním každé změny, `findings.json` prázdné. Git je review.

To je zároveň odpověď na to, proč nestavíme instinktový sklad: **instinkt s konfidencí 0,7 nikdo nereviduje; diff v `SKILL.md` reviduje zakladatel v Source Control jako každou jinou změnu.**

**Práh jako podmínka spuštění, ne varování:** `--revise` s méně než 10 rozhodnutými nálezy odmítne startovat, stejnou logikou jako `prompt: required`.

**Testy:** `--revise` pod prahem končí `SystemExit` s vysvětlením; nad prahem připraví `RUN_DIR` s briefem.

**Hotovo, když:** nad packem s reálnou historií vznikne diff, který zakladatel přečte a přijme beze změny. A když ne, je v `summary.md` napsáno proč tak, aby se dalo namítnout.

---

### Krok 12 — `agency replay` (~1,5 dne) → D8

**Proč:** bez tohohle je Krok 11 stroj na neověřitelné změny, což je horší než žádný stroj.

**Co se mění:** fixtura je připnutý běh — `(pack, target.headRefOid, prompt)` plus rozhodnuté nálezy jako gold. Commituje se do `.agency/evals/<jméno>.json`, protože je to pravda projektu jako všechno ostatní.

```
agency replay --pack review-graph          # všechny fixtury packu
agency replay --fixture pr-479
```

Přehrání spustí pack nad **týmž commitem** s **dnešním** `SKILL.md` a porovná `fingerprint`y ([`dedup.py:97`](../../packages/core/src/agency/dedup.py)) proti goldu:

| číslo | co znamená |
|---|---|
| **recall** | kolik dřív **přijatých** nálezů se našlo znovu |
| **regrese** | kolik dřív **zamítnutých** se vrátilo ← **hlavní číslo** |
| **nové** | kolik gold nemá — k ručnímu posouzení, ne automaticky špatně |
| cena, čas, tahy | z `cost` a `agent.turns`, aby „lepší" neznamenalo „třikrát dražší" |

**Tvrdé pravidlo:** změna `SKILL.md`, která vrátí dřív zamítnutý nález, je regrese a neprojde. Bez výjimky — je to jediné číslo v plánu s jednoznačnou interpretací a ta cena za jednoznačnost stojí.

**Přehrání běží vždy `--unattended`**, i když se původní běh dělal attended — jinak by se cena a tahy neměly s čím porovnat (§0.4).

Z ECC bereme jazyk (`pass@k` pro schopnost, `pass^k` pro stabilitu) a jednu poznámku z jejich anti-patternů, která platí i pro nás: **fixtura, na kterou se pack začne přeučovat, přestala měřit.** Fixtury se proto přidávají průběžně a stará se nikdy neopravuje proto, aby prošla.

**Testy:** nový `tests/test_replay.py` — fixtura + podvržený `findings.json` dá recall/regrese/nové na známých číslech. Reálný agent se nespouští (`never_launch_an_agent`).

**Hotovo, když:** `agency replay --pack review-graph` nad třemi fixturami z `main-panelu` doběhne a vyrobí tu tabulku. Pak je vidět, jestli Krok 11 pomohl.

---

## 6. Pořadí

| fáze | kroky | rozsah | čeká na |
|---|---|---|---|
| **0 — sonda** | 0 | ~3 h | nic |
| **A — záznam, vstup, měřidlo** | 1, 13, 14, 2, 3 | ~3 dny | ~~Krok 0~~ hotovo |
| **B — palivo** | 8, 9, 15 | ~2 dny | A |
| **C — brána** | 4, 5, 6, 7 | ~2 dny | ~~Krok 0 (4 a 7)~~ hotovo; jinak A |
| **D — smyčka** | 10, 11, 12 | ~3 dny | B **a ~10 rozhodnutých nálezů na pack** |

Čtyři vazby, zbytek je volný:

1. ~~**Krok 0 je první**, protože rozhoduje, jestli se Kroky 4 a 7 dělají celé, částečně, nebo vůbec.~~ **Hotovo 6. 9. 2026, rozhodnuto: celé.** Vazba tím zaniká, Fáze C na nic nečeká. Jediné, co z Kroku 0 zbývá jako otevřená otázka, je limit délky argumentu na Windows v Kroku 2 — a ten se dá doprobovat až u něj.
2. **Krok 1 je první v kódu.** Otisk kontextu je nezávislá proměnná; bez něj jsou Kroky 10 a 12 měření bez měřidla.
3. **Krok 14 je před vším, co počítá.** Metriky, které míchají attended a unattended, vedou k revizi opřené o průměr přes prázdno — a to je horší než revize žádná.
4. **Fáze B jde před Fází C**, i když je brána zajímavější. Palivo se hromadí běháním, ne psaním kódu — čím dřív `verify` běží, tím dřív je Fáze D možná. Fáze C se dělá, zatímco běhy přibývají.

**Krok 13 (`blocked`) je uvnitř Fáze A na druhém místě schválně.** Je levný, je to kontrakt, a mění, jak se čte každý běh, který nic nenašel — včetně těch, které proběhnou během zbytku plánu.

---

## 7. Přejímka

Nad `main-panelem`, jedním PR, v tomhle pořadí:

1. `agency run review-graph --pr <n> --unattended --wait` — `run.json` má vyplněný `context` s otisky `CLAUDE.md` i `SKILL.md`;
2. v `RUN_DIRu` leží `do-not-report.md` pod 40 řádků a `known-here.json` pod 50 položek; v argv je vidět, čím se `do-not-report` doručil;
3. `agency metrics` u každého čísla o ceně uvádí populaci; `agency status` řekne, kolik běhů je slepých;
4. běh nad vypnutým stagingem (nebo s odebraným `gh` loginem) skončí jako `blocked` s čitelnou větou — **ne** jako `no-findings`;
5. `agency chain review-graph verify --pr <n>` doběhne; `agency knowledge` ukáže aspoň jeden `machine-confirmed`; `metrics` má precision i pro `verify`;
6. aspoň jeden nález zahozený jako `weak-evidence` nebo `unproven-source` — nebo doložené, že žádný takový nebyl. Ne mlčení;
7. `agency metrics --pack review-graph` vypíše cenu na přijatý nález;
8. `agency metrics --for-author review-graph` vypíše brief a **zakladatel podle něj řekne, co by sám změnil**, dřív než uvidí bod 9;
9. `agency run author --revise review-graph` napíše diff, který se s odhadem z bodu 8 potkává — a když ne, `summary.md` říká proč;
10. `agency replay --pack review-graph` nad fixturou z bodu 1 vykáže **regrese = 0**.

Bod 8 je nejtvrdší podmínka: jediné místo, kde se pozná, jestli je brief informace, nebo jen dobře naformátovaná čísla.

---

## 8. Co se vědomě nedělá

| co | proč ne | spouštěč |
|---|---|---|
| návrat `rank.py` (BM25 nad pamětí) | „desítky, ne tisíce" pořád platí; Krok 3 řeší tvar, ne pořadí | až `knownFindings` přeteče strop 300 na reálném projektu |
| sdílená stránka `pages/_project/` napříč packy | riziko druhé `CLAUDE.md`; hranice „pozorovaná fakta vs. instrukce" se špatně drží a ještě hůř vynucuje | až tři packy nezávisle napíšou totéž fakt do vlastních stránek |
| streamování attended běhu | interaktivní `claude` žádný strojově čitelný proud nepublikuje; vymyslet si ho by znamenalo vykazovat čísla, která nikdo neměřil | až to runner umí sám |
| „agent se zeptá a počká" | neattended běh nemá koho. `blocked` (Krok 13) je výsledek, ne dialog; navazuje se `follow` nebo novým během | až bude existovat běh, u kterého někdo trvale sedí a chce odpovídat |
| PreToolUse gate à la GateGuard | jejich +2,25 je změřené na „než něco přepíšeš, dokaž, že víš, kdo to importuje". Většina našich packů zdroj needituje; co se mapuje, je „než zapíšeš findings.json, dokaž, žes pustil graf" — a to už je Krok 4 | až vznikne pack, který zdroj mění |
| fan-out dimenzí do subagentů uvnitř běhu | pack si subagenta umí spustit sám, když mu to `needs` dovolí; jádro na to nepotřebuje mechaniku | až jeden běh nad velkým PR nedoběhne kvůli kontextu, ne kvůli času |
| hooky instalované do harnessu uživatele (styl ECC) | mimo hranici nástroje. **Není to totéž co hooky v našich bězích** — ty jsou R5 a dělají se v Krocích 4 a 7 | nikdy z tohohle plánu |
| hooky pro `codex` | umí je (tytéž typy, ověřeno v binárce), ale předat se dají jedině `.codex/config.toml` v projektu — konfigurace, kterou R5 zakazuje. Radši ať `context.toolCalls` řekne `false`, než aby se do cizího repa psal soubor | až `codex` vezme hooky na příkazové řádce |
| registr šablon packů | `packs/` už je šablona; registr je konfigurace pod jiným jménem | nikdy |

---

## 9. Jednou větou

ECC dělá jednoho obecného agenta lepším tím, že mu přidává výbavu. My máme něco, co ECC strukturálně mít nemůže: **frontu nálezů, o kterých někdo skutečně rozhodl.** To je učitel, ne heuristika — a celý tenhle plán je o tom ho konečně použít, po tom, co se změří poctivě (Krok 14) a co běh přestane mlčet, když nemůže dál (Krok 13).
