# Vzdálené ovládání — úkolovat specialisty z mobilu, bez veřejné IP

**Datum:** 2026-09-04
**Navazuje na:** [`agency-v1.md`](agency-v1.md) (jádro obecné, klient jen posílá JSON), [`unattended.md`](unattended.md) (běh, u kterého nikdo nesedí), [`teams.md`](teams.md) (chain jako sekvence)
**Řeší:** spustit specialistu nad projektem z telefonu, když je PC zapnuté a projekt aktivovaný — a vidět, co dělá, aniž by PC mělo veřejnou IP.
**Rozhodnuto s uživatelem 4. 9. 2026:** klient = HTML servírované démonem · transport = Tailscale · dohled = obě varianty (unattended i Remote Control) · rozsah v1 = start nad PR, start s promptem, živý průběh a výsledek brány.

---

## 1. Proč

Extension umí zadat úkol jedním kliknutím, ale to klikání musí být u toho počítače. Věci, které se rozhodnou jinde — „tenhle PR ať projde recenzent", „ať se právník podívá na ty VOP" — dnes čekají, než přijdu domů. Přitom PC běží, agent by běžel taky.

Cíl **není** druhé UI. Cílem je jedna obrazovka na telefonu, ze které jde spustit specialistu nad aktivovaným projektem a sledovat, co dělá. Rozhodování o nálezech zůstává tam, kde je dnes: u kódu, v editoru.

---

## 2. Co už stojí a co si remote jen půjčí

Ověřeno v kódu 4. 9. 2026.

| primitivum | kde | co dává remote vrstvě |
|---|---|---|
| `agency … --json` jako jediný kontrakt pro klienty | [`cli.py:1316`](../../packages/core/src/agency/cli.py), [`cli.js:33`](../../packages/extension/src/cli.js) | remote je **třetí klient**, ne nová architektura |
| `run --unattended --wait` — spustí agenta, čte jeho stream, sám pustí bránu | [`cli.py:700`](../../packages/core/src/agency/cli.py), [`review.js:195`](../../packages/extension/src/review.js) | běh bez terminálu je hotový, remote ho jen odpálí |
| **surový stream agenta se už ukládá do běhu** — `agent.jsonl` | [`runs.py:637`](../../packages/core/src/agency/runs.py) | živý průběh se dá číst tailováním souboru; **žádný nový formát se nezavádí** |
| překladač streamu obou runnerů na uzavřený slovník událostí | [`events.py`](../../packages/core/src/agency/events.py) | `events.parse(dialect, line)` je celý backend „co agent zrovna dělá" |
| `launch_argv()` — tvar spuštění vlastní jádro | [`runs.py:250`](../../packages/core/src/agency/runs.py) | Remote Control je klíč v tabulce providerů, ne skládání příkazu v klientovi |
| `agency prs`, `agency packs`, `agency status` | `cli.py` | seznamy pro mobil bez jediného nového dotazu |

Původní odhad počítal s tím, že se do běhu musí doplnit `events.jsonl`. Nemusí — `attend()` píše `agent.jsonl` pokaždé, když je znám dialekt. Démon nad ním dělá totéž, co dnes dělá `_progress` v terminálu.

---

## 3. Tvarová rozhodnutí

**1. Démon nemá vlastní úsudek.** `agency serve` umí tři věci: ověřit zařízení, vědět, které projekty jsou aktivované, a spouštět `agency` jako podproces. Nesestavuje prompty, nerozhoduje o nálezech, nezná packy. Když se něco ptá jádra, ptá se ho přes `--json` — stejně jako extension.

**2. Klient je HTML z démona, ne aplikace.** Žádný build, žádný deploy, žádná druhá autentizace. Celý systém je jeden proces a jedna stránka. Až bude chtít víc (push notifikace, offline fronta), vymění se klient — démon se nezmění, protože mezi nimi je zase jen JSON.

**3. Transport je Tailscale, ne tunel — a publikuje ho `tailscale serve`, ne bind.** Démon poslouchá na `127.0.0.1:7777` a sám se ven nedostane; provoz z tailnetu chodí na jiné rozhraní (`100.x.y.z`), takže loopback by z telefonu byl neviditelný. Tu díru zavírá `tailscale serve`: Tailscale sám stojí před portem, přidá HTTPS s platným certifikátem na `https://<jméno-pc>.<tailnet>.ts.net` a do požadavku doplní identitu přihlášeného zařízení. Démon tím zůstane na loopbacku i po chybě v jeho vlastní autorizaci. Alternativa — bind na tailnetovou adresu — je o krok jednodušší a o dvě vrstvy horší (žádné HTTPS, žádná identita). Cloudflare Tunnel + Access je zdokumentovaná náhrada (§7), když jednou bude vadit mít Tailscale v mobilu; démon se tím nemění.

**4. Aktivace projektu je stav démona, ne konfigurační soubor.** `agency serve --project <cesta>` obsluhuje jen vyjmenované repozitáře a aktivace má okno (výchozí 8 h), po kterém se sama zavře. Znovuotevření je příkaz na PC, ne tlačítko v mobilu — kdo má telefon, nesmí si sám prodloužit právo spouštět kód.

**5. Dvě tlačítka na řádku specialisty, protože dohled je volba, ne vlastnost packu.** Extension už tuhle větu má u dvou šipek ([`README.md`](../../README.md), *Supervised, or on its own*); remote ji jen zopakuje jinými slovy:

| tlačítko | co spustí | co uvidíš v mobilu |
|---|---|---|
| **Spustit** | `agency run <pack> --unattended --wait` | živý průběh z `agent.jsonl` a po doběhu počty z brány |
| **Převzít** | attended launch + `claude --remote-control agency-<runId>` | „session běží, pokračuj v Claude appce" + tlačítko na bránu, až skončíš |

**6. Remote Control neumí živý průběh, a je to tak správně.** `--output-format stream-json` existuje jen s `-p`; interaktivní session žádný strojový stream nevydává. Kdyby to démon předstíral, ukazoval by průběh běhu, o kterém nic neví. Místo toho řekne pravdu: tenhle režim je pro chvíle, kdy si s agentem chceš psát, a psát si s ním budeš v Claude appce.

**7. Brána po Remote Control běhu je ruční krok.** Interaktivní `claude` po dokončení úkolu neskončí — sedí na promptu (přesně to je důvod pro `unattendedPrefix` v [`providers.py:36`](../../packages/core/src/agency/providers.py)). Démon tedy nemá exit code, na který by čekal, a `agency ingest --run <id>` pouští člověk tlačítkem. Stejné, jako je dnes **Process run output** v extension.

**8. `--bypass` je právo zařízení, ne checkbox v UI.** Vzdálený běh s vypnutými kontrolami je spuštění libovolného kódu na mém PC z telefonu. Zařízení ho buď má (a pak je to u něj napsané při párování), nebo pack, který ho potřebuje, ze zařízení prostě nejde spustit.

**9. Jeden souběžný běh na projekt.** Příprava běhu si zabírá worktree a dvě přípravy najednou dostanou tutéž cestu ([`review.js:232`](../../packages/extension/src/review.js) to říká u paralelního startu). Démon serializuje.

---

## 4. Kroky

### Krok 0 — původ běhu v záznamu (~1 h) — **hotovo 4. 9. 2026**

- [x] `schemas/run.v1.json` — do `trigger` přibylo `origin` (`cli` | `extension` | `remote`) a `device` (string). `kind` se nemění: „manual" pořád platí, remote není jiný druh spouštěče, jen jiné místo.
- [x] `runs.start()` je předává dál ([`runs.py:544`](../../packages/core/src/agency/runs.py)).
- [x] `agency run --origin remote --device <id>` — skryté v `--help`, protože to není příkaz pro člověka.
- [x] **navíc:** extension posílá `--origin extension` ([`cli.js`](../../packages/extension/src/cli.js), [`review.js`](../../packages/extension/src/review.js)). Plán s tím nepočítal, ale hodnota enumu, kterou nikdo nikdy nezapíše, je lež ve schématu — a otázka „co jsem spustil z vlaku" má odpověď jen tehdy, když i ostatní dva klienti řeknou pravdu. **Projeví se až po přebalení extension.**

**Hotovo, když:** běh spuštěný z telefonu má v `run.json` napsané, že přišel z telefonu a z kterého. — ✅ `tests/test_serve.py` (záznam i validace proti `run.v1`), `test/harness.js` pro editor.

### Krok 1 — `agency serve` (~1 den) — **hotovo 4. 9. 2026**

Šestnáctý příkaz. Stdlib `http.server` na vlákně, žádná závislost navíc (jádro má dnes jedinou — `jsonschema`).

```
agency serve --project . [--project ../main-panel] [--port 7777] [--hours 8]
```

Endpointy — všechny vracejí to, co vytiskne `agency … --json`, bez přebalování:

| cesta | co dělá |
|---|---|
| `GET /api/projects` | aktivované projekty a zbývající čas okna |
| `GET /api/packs?project=` | `agency packs` |
| `GET /api/prs?project=` | `agency prs` |
| `POST /api/run` | `{project, pack, pr? , prompt?, mode: "unattended"\|"remote-control"}` → id běhu |
| `GET /api/run/<id>/events` | SSE: tail `agent.jsonl` → `events.parse()` → JSON událost |
| `GET /api/runs?project=` | `agency status` — bez něj telefon po reloadu nenajde běh, který sám spustil |
| `GET /api/run/<id>` | záznam běhu vlastními slovy + `counts` z brány |
| `POST /api/run/<id>/ingest` | ruční brána (režim Remote Control) |

Párování: `agency serve` vypíše na konzoli šestimístný kód, telefon ho jednou zadá a dostane per-device token do `localStorage`; token se uloží na PC mimo repozitář (`%LOCALAPPDATA%/agency/devices.json`) a jde odvolat. Každá vzdálená akce jde na řádek do `remote.jsonl` vedle něj — audit je soubor, ne log.

**Co plán nepředpokládal**

- **`events.jsonl` se nezavádí.** `runs.attend()` už dnes píše surový stream runneru do `agent.jsonl` ([`runs.py:637`](../../packages/core/src/agency/runs.py)) a `events.parse()` z řádku dělá událost. SSE endpoint je tyhle dvě věci po HTTP, ne třetí formát.
- **Id běhu se čte z disku, ne z výstupu.** `--wait` a `--json` se vylučují, takže `agency run --wait` id nevrací. `POST /api/run` proto čeká, až se objeví záznam běhu s `trigger.device` toho zařízení. Alternativa — regex nad lidským výstupem na ULID — je přesně to, co Fáze 0 z [`tasks.md`](tasks.md) z jádra vyhazovala.
- **Když běh vůbec nezačne, odpovědí je to, co podproces vytiskl.** Odmítnutí (draft, už zrecenzovaný commit, chybějící prompt) se tiskne, nevrací; vymýšlet pro telefon vlastní důvod by znamenalo říct mu něco, co terminál neřekl. Logy podprocesů leží v `<state>/jobs/`.
- **`--pair` na běžícím démonu neexistuje.** Okno na párování se otevírá při startu (`--pair-window`, výchozí 5 minut, ne 60 s — za minutu se telefon nestihne ani odemknout) a zavírá se po prvním spárovaném zařízení nebo po pěti špatných kódech. Otevřít nové = restartovat `agency serve`, což je správně: je to rozhodnutí u toho počítače.
- **Stav démona bydlí v `%LOCALAPPDATA%/agency/`.** Pravidlo „žádné `~/.agency/`" mířilo na konfiguraci — token o ničem nerozhoduje a druhé místo, kam ho dát, je komitnutý adresář.

**Hotovo, když:** z telefonu v tailnetu spustím `po` s promptem nad `main-panel` a vidím, jak agent volá nástroje, a po doběhu počty z brány. — ✅ **postavené a otestované** (`tests/test_serve.py`: párování, okno aktivace, argv běhu, serializace, audit, stream včetně `offset`, `Last-Event-ID` a rozepsaného řádku; navrch smoke proti skutečnému projektu s packem, kde endpointy obsluhuje opravdový podproces). Poslední kus té věty — *z telefonu* — je na tobě: prohlížeč v ruce jsem neměl.

### Krok 2 — Remote Control jako druhý režim (~4 h) — **hotovo 5. 9. 2026**

- [x] `providers.py` — u `claude` přibyl `remoteControlFlag: "--remote-control"` (ověřeno proti `claude --help`: *„Start an interactive session with Remote Control enabled (optionally named)"*). `launch_argv()` ho přidá, když si o něj volající řekne; jméno session je `agency-<pack>-<runId prvních 8>`, aby šlo v Claude appce poznat, co to je.
- [x] **Spike dopadl na prvním pokusu.** `CREATE_NEW_CONSOLE` drží: démon spustí `agency run <pack> --remote-control --wait` v novém okně, dítě má vlastní stdio a `claude` v něm běží jako v terminálu. `claude --bg` + `attach` se tím pádem nezkoušelo. Na systému, kde konzoli dát nejde, režim **odmítne** (`no-console`) místo aby otevřel session, kterou nikdo neuvidí.
- [x] `--remote-control` je vlastní přepínač `agency run`, ne odvozenina z `--launch`: `--launch` znamená „převezmi tenhle terminál", `--remote-control` znamená „ať se do toho dá mluvit odjinud". Dohromady se `--unattended` se vylučuje a odmítá se to **před** stavbou worktree.

**Co plán nepředpokládal**

- **Session se ptá dřív, než začne — a na to spike nemyslel.** Ověřeno 5. 9. 2026 čtením konzole skutečného `claude` (attach na konzoli dítěte, `ReadConsoleOutputCharacterW`): v projektu s nerozhodnutým `.mcp.json` stojí *„New MCP server found in this project"* a v adresáři, ve kterém Claude Code nikdy nebyl, *„Is this a project you trust?"*. Druhou nepřeskočí ani `--dangerously-skip-permissions` (help to říká: přeskakuje se jen v neinteraktivním režimu). Obě otázky čekají na člověka, který u toho stroje není — přesně tak vypadalo první skutečné použití: okno se otevřelo a zaseklo.
  - MCP: session spuštěná z telefonu jde s `--strict-mcp-config`, takže otázka nemá jak vzniknout. Cena je, že projektové MCP servery nejsou k dispozici; to je poctivá výměna — session, které nemá kdo odpovědět, začne s méně, místo aby nezačala.
  - Důvěra: flag na to není, ale odpověď se zapisuje do `~/.claude.json` (`projects[<cesta>].hasTrustDialogAccepted`), takže se dá **přečíst dopředu**. Když adresář důvěru nemá — a pack s worktree je nový adresář pokaždé — běh se zavře s tímhle jako `exitReason` místo aby se otevřelo okno, které visí. Když se soubor přečíst nedá, spouští se dál: odhad, který odmítne session, jež by fungovala, je horší než to viset.
- **Brána nemusí být ruční.** Bod §3.7 počítal s tím, že démon nemá exit code, na který by čekal. `--wait` ho má i u attended běhu: `runs.attend()` pustí `claude` s poděděným stdio a čeká, až ho člověk zavře — pak sama proběhne brána. Tlačítko v mobilu zůstává pro session, kterou nikdo nezavře.
- **Tlačítko je jedno, ne dvě.** Na řádku specialisty ne — obě tlačítka jsou až na obrazovce spuštění, protože vedle titulu se druhá akce na mobilu nevejde a řádek se stane hádankou.

**Hotovo, když:** tlačítko **Otevřít session, se kterou si můžu psát** otevře session, kterou v Claude appce najdu pod jménem specialisty. — ✅ postavené a otestované (`tests/test_serve.py`: argv, vyžádaná konzole, odmítnutí tam, kde konzole není; `tests/test_follow.py`: tvar spuštění a že se u ní nestreamuje). Klik z telefonu je na tobě.

---

### Krok 5 — navázat otázkou a nepřijít o místo v aplikaci (~4 h) — **hotovo 5. 9. 2026**

Dvě věci, které vyšly najevo až prvním skutečným použitím z telefonu:

**1. Zpět v mobilu vyhazovalo z aplikace.** Stránka byla jedna URL a pět skrytých sekcí, takže gesto zpět neznamenalo „o obrazovku zpátky", ale „pryč ze stránky". Běh, na který se člověk dívá, se navíc nedal ani obnovit, ani otevřít z plochy.

- [x] Každá obrazovka má vlastní cestu: `/`, `/pair`, `/p/<projekt>/runs`, `/p/<projekt>/start/<pack>`, `/p/<projekt>/run/<id>`, `/p/<projekt>/run/<id>/doc/<soubor>`. Klient je `history.pushState` + `popstate`, žádný router z npm.
- [x] Démon servíruje stránku na **každé cestě, která není `/api/`** — jinak by první reload takové URL byl 404. `/api/…` zůstává chybou, aby se z chyby klienta nestala stránka HTML tam, kde se čeká JSON.
- [x] Dokument běhu je obrazovka, ne panel: zavře se gestem zpět.
- [x] Hlubokým odkazem se dá začít. Obrazovka spuštění si dotáhne pack z `agency packs`, když přehled v téhle relaci nikdo nenačetl, a co smí zařízení a jestli stroj umí otevřít okno se ptá `/api/projects` — endpoint, který nespouští žádný podproces.

**2. Na unsupervised běh se nedalo navázat.** Odpověď přišla, agent skončil a další otázka znamenala celý druhý běh, který si musel všechno přečíst znovu.

- [x] Sedmnáctý příkaz: `agency follow --run <id> --prompt "…"` — `claude --resume <sessionId>`, tedy **táž session**. `sessionId` se do záznamu psalo odjakživa (`run.v1`, „lets a run be replayed in the provider's tooling"), jen ho nikdo nečetl.
- [x] Odpověď je součástí běhu, ne nový běh: stream se **přidává** do `agent.jsonl` (telefon ji vidí ve stejném feedu, stačí otevřít stream tam, kde přestal číst) a turny, tokeny i cena se **přičítají**. Nahradit je by znamenalo, že běh stál tolik, co jeho poslední otázka.
- [x] Brána svůj verdikt nemění. `follow` si `running` jen půjčí, aby telefon věděl, že je co sledovat, a na konci vrátí stav, který dal gate. Když se `findings.json` změnil, řekne to a nechá `agency ingest` na člověku.
- [x] `POST /api/run/<id>/follow` čeká, až záznam řekne `running` — telefon otevírá stream hned po odpovědi a stream otevřený o chvíli dřív by skončil okamžitým `done`.
- [x] `agency follow --remote-control` je tatáž otázka položená session, se kterou si chceš psát. Tím se kruh uzavírá: pustím běh z telefonu, přečtu si výsledek, a když je o čem mluvit, převezmu ho v Claude appce.

**Co se u toho ukázalo**

- **Běh spuštěný v terminálu navázat nejde** a je to tak správně: attended běh nic nestreamuje, takže žádné `sessionId` nemá. Stránka se proto ptá záznamu (`canFollow`), místo aby nabídla tlačítko, které skončí chybou.
- **`--bypass` u navázání dědí běh, ne zařízení.** Otázka pokračuje v session, která už jednou běžela bez kontrol; posílá se `bypass` jen tehdy, když ho má i zařízení — jinak by šlo přes telefon bez toho práva pokračovat v čemkoli.
- **Codex má `resume`, Remote Control ne.** Obojí je řádek v tabulce providerů (`resumeShape`, `remoteControlFlag`), takže odmítnutí je fakt z tabulky, ne větev v příkazu.

**Hotovo, když:** z telefonu pustím `po`, přečtu odpověď, zeptám se na druhou věc a odpověď přijde do téhož feedu — a gesto zpět mě přitom nevyhodí z aplikace. — ✅ testy (`test_follow.py`, doplněné `test_serve.py`); ověření prstem je na tobě.

---

### Krok 6 — běh jde z telefonu i ukončit — **hotovo 5. 9. 2026**

Vyšlo najevo hned prvním skutečným použitím Kroku 2: **session předaná Claude appce sama neskončí.** Okno na počítači čeká, až ho někdo zavře, a do té doby je projekt obsazený, worktree zabraný a běh `running`. Z vlaku s tím nešlo dělat nic — telefon uměl session otevřít, ale ne zavřít.

- [x] `POST /api/run/<id>/stop` a na obrazovce běhu tlačítko **Close the session and its window**. Potvrzuje se druhým klepnutím, ne dialogem: druhý popisek je zároveň to varování (*agent se zabíjí tam, kde stojí*), takže není co číst dvakrát — a palec vedle se netrefí do běhu, který pracuje dvacet minut.
- [x] **Zabíjí se celý strom, ne proces.** `proc.kill_tree()` — na Windows `taskkill /T /F`. Dítě démona je `agency run`, agent je dítě jeho; konzole navíc nepatří žádnému z nich, ale skupině, a zavře se, až z ní odejde poslední proces. Zabít jen rodiče znamená `claude`, který dál pracuje v okně, které už nikomu nepatří.
- [x] **Nejdřív zabít, teprve pak `abandon`.** `runs.abandon()` maže worktree; agent, který v něm ještě žije, by se mazal uprostřed zápisu. To pořadí je celá bezpečnost té věci a je proto v testu (`test_the_agent_is_killed_before_its_worktree_is_taken`).
- [x] **Ukončit jde jen to, co démon drží.** Ne to, co říká záznam: `running` může být session, kterou někdo právě teď píše u počítače, a uvolnit jí worktree pod rukama je horší než tlačítko nemít. Popen v ruce je odpověď na jinou otázku než status v `run.json` — a mimochodem i pojistka proti recyklovanému PID, protože nezavřený handle ve Windows to číslo drží. Zbytek se odmítá s `agency cleanup --run <id>` jako návodem, u toho stroje, kde je i to okno.
- [x] `canStop` chodí v odpovědi `/api/run/<id>`, ne v `_run_state()` — to je čtení záznamu a ničeho jiného. Tlačítko, které by vždycky vrátilo 409, není tlačítko; je to táž hranice jako u `canFollow` a `canOpenSession`.
- [x] Na POSIXu jde běh do vlastní process group (`start_new_session`), aby bylo co zabít. **Bez kontroly, že je dítě vedoucím té skupiny, by `getpgid` vrátilo skupinu démona a `stop` by zastřelil sám démon** — pojištěno testem, protože na Windows tahle větev nikdy neběží a rozbila by se potichu.

**Co se u toho ukázalo**

- **Je to zabití, ne rozloučení.** Ctrl-C do cizí konzole poslat nejde (`GenerateConsoleCtrlEvent` míří jen na skupiny na vlastní konzoli), takže co měl agent rozdělané, končí tam. Popisek tlačítka to říká dřív, než se klepne podruhé.
- **Stav je `abandoned`, ne `failed`,** a přesně v tom významu, který mu `run.v1` dal odjakživa: příprava proběhla, agent běžel a terminál zmizel dřív, než skončil. Nový stav pro tohle nebyl potřeba.
- **Brána zůstává tlačítkem.** Ukončená session mohla `findings.json` napsat; `Run the gate` na té obrazovce je pořád, takže se z přerušeného běhu dá vytěžit, co stihl.

**Bypass byl práva bez dveří.** Tlačítko *Open one with no permission checks* se ukazuje jen zařízení, které má `device.bypass` — a to nešlo nastavit nijak. Párovací formulář posílal jen `{code, name}` a `agency serve` na to neměl přepínač; jediný zapisovatel byl `bool(body.get("bypass"))` v `/api/pair`, tedy **telefon si to právo uděloval sám**, přesně proti tomu, co pod formulářem stálo napsané. Kdo měl kód, měl i bypass.

- [x] `agency serve --allow-bypass` (a `scripts/serve.ps1 -AllowBypass`). Uděluje ho stroj, v tom párovacím okně, které sám otevřel — `pair()` už jen hlásí odpověď. `bypass` v těle požadavku se ignoruje.
- [x] Konzole to říká při každém startu, i když se neuděluje. Okno, které rozdává právo běžet bez jakýchkoli kontrol, se nemá poznávat zpětně z logu.
- [x] Chybějící volba na obrazovce spuštění říká, proč chybí, a co s tím u stroje. Nepřítomná věc je hádanka, dokud neřekne, na co čeká.
- [x] **A není to tlačítko, je to zaškrtávátko nad tlačítky.** Třetí tlačítko vedle dvou dělalo z téže session jinou věc, kterou spouštíš, a platilo jen pro interaktivní tvar — unsupervised běh se stejnou volnost pustit nedal vůbec. Vypnuté kontroly jsou vlastnost běhu, který spouštíš, ne třetí běh.
- [x] `scripts/serve.ps1` posílá `--allow-bypass` vždycky, bez přepínače, na který se zapomíná. Flag v jádru zůstává: jádro neví, čí je to stroj. Skript to ví — je to jeden notebook a jeden telefon na vlastním tailnetu, a stejně se to musí u každého běhu zaškrtnout.

**Hotovo, když:** okno, které si z telefonu otevřu, z telefonu i zavřu a projekt je hned volný pro další běh. — ✅ testy (`test_serve.py`: zabití, pořadí vůči worktree, odmítnutí cizího běhu, `canStop`, audit, obě větve `kill_tree`). Klik z telefonu je na tobě.

---

### Krok 3 — stránka (~4 h, souběžně s Krokem 1) — **hotovo 4. 9. 2026**

Jeden `index.html` v `packages/core/src/agency/_web/`, servírovaný démonem. Tři obrazovky: projekty → specialisté (řádek = titul, dvě tlačítka) → běh (průběh, pak výsledek brány). Prompt je `<textarea>`, PR je seznam z `agency prs`. Žádný framework; když stránka poroste přes jeden soubor, je to signál, že měla být PWA.

**Co plán nepředpokládal**

- **Obrazovky jsou čtyři.** První je párování — kód z konzole a jméno zařízení; token pak leží v `localStorage`. Bez ní by první otevření stránky bylo 401 bez vysvětlení.
- **Tlačítko je jedno, ne dvě.** Druhé patří Kroku 2 a tlačítko, které vrací 501, není tlačítko. Přibude s ním.
- **`EventSource` se po `done` zavírá z klienta.** Prohlížeč se po ukončeném streamu sám připojí znovu, takže bez toho by konec běhu přehrával dokola.
- **Resume jede přes `Last-Event-ID`.** Tu hlavičku posílá prohlížeč při reconnectu sám; `?offset=` zůstává pro ruční otevření. Resume, který závisí na tom, že si klient vzpomene přidat parametr, je resume, který jednou přehraje hodinu volání nástrojů.
- **Model se vybírá na obrazovce spuštění** (5. 9. 2026). Rozbalovátko pod promptem; seznam i výchozí hodnota chodí z `/api/projects`, z téže tabulky v `providers.py`, ze které se staví `--model`, takže stránka žádný seznam modelů nedrží a nezastará den, kdy provider dostane další. Výchozí je `sonnet`. Bez toho jel běh z telefonu vždycky na výchozím modelu providera a „který model nachází lepší nálezy" se z mobilu nedalo ani zkusit.
- **Stránka se nikdy necachuje** (`Cache-Control: no-store`) a čte se z disku při každém požadavku — úprava na počítači je živá po přetažení prstem, ne po vyčištění cache telefonu.
- **Konzole démona nesmí shodit request.** Nalezeno při smoke testu: `✓` po úspěšném párování narazilo na cp1250 konzoli, vyhodilo `UnicodeEncodeError` a telefon dostal 500 za něco, co už proběhlo. Řádek na konzoli je zdvořilost, odpověď telefonu je práce.

**Hotovo, když:** stránka na telefonu spustí specialistu a ukáže jeho průběh. — ✅ postavené; ověřená je syntaxe skriptu, tvary všech odpovědí, které stránka čte, proti skutečnému projektu, a že se servíruje bez cache. Klik z telefonu je na tobě.

---

### Krok 4 — všechny projekty na jednom místě (~4 h) — **hotovo 4. 9. 2026**

Krok 1 počítal s tím, že se démon spustí uvnitř projektu a další se dopíšou přes `--project`. Po prvním použití je jasné, proč to nestačí: **na telefonu nejsi „v projektu"**. Není tam `cd`, není tam terminál a to, co chceš vidět, není jeden repozitář — je to všechno, co dnes běží, a co v tom kterém projektu umí kdo spustit.

**Tohle je vědomý rozpor s [`agency-v1.md`](agency-v1.md) §1**, kde v seznamu „co to není" stojí *multi-projektový přehled* a *konfigurační systém*. Rozpor se řeší hranicí, ne výjimkou:

- **CLI zůstává jednoprojektové.** `run`, `findings`, `ingest`, `status` — všechno se pořád odvozuje od `cwd` a o žádném seznamu projektů neví. Vícero projektů zná jediný příkaz: `serve`, protože jeho celý smysl je, že u žádného z nich nesedíš.
- **Seznam není konfigurace projektu.** Je to stav toho stroje, jako tokeny zařízení — bydlí vedle nich v `%LOCALAPPDATA%/agency/projects.json` a žádný projekt o něm neví.

**Kam projekty zapsat: nikam.** Primární cesta je sken:

```
agency serve --scan C:/Users/kubad/Documents/coding --save
```

Projde strom do hloubky 2 (`<root>/<org>/<repo>`) a otevře každý repozitář, který má aspoň jednoho specialistu. `--save` tu otázku zapíše — od té chvíle bare `agency serve` otevře totéž. Uloží se **otázka, ne odpověď**: sken uložený jako seznam cest by zestárnul dnem, kdy něco naklonuješ, a znovu ho spustit stojí 0,1 s (měřeno na skutečném disku).

Dvě vyloučení nesou celou věc:

- **Worktree běhu není projekt.** `agency run` staví vedle repozitáře jednorázové worktree a kopíruje do nich pack, takže `main-panel-review-pr-467` vypadá na disku přesně jako projekt se specialistou — tři takové na disku ležely, když tohle vznikalo. Jejich `.git` je **soubor** (`gitdir: …`), ne adresář; tak je odlišuje git a tak je odlišuje sken.
- **Do repozitáře se nikdy nesestupuje.** Co je zanořené uvnitř, patří jemu; sken, který leze dovnitř, nabídne cizí fixtures jako projekty.

`--project <cesta>` zůstává pro to, co leží mimo skenované stromy, a otevře projekt, i když specialistu ještě nemá — cestu někdo napsal, to není odhad. Argumenty **přebíjejí** uložený seznam celý, aby šlo říct „dnes obsluhuj jenom tohle"; bez `--save` se uložené nesáhne.

**Jedna odpověď místo N.** `GET /api/overview` vrátí všechny projekty i s jejich specialisty a s tím, co v nich zrovna běží — projekty se ptají paralelně a `agency packs` se drží minutu v cache. Telefon, který musí udělat osm round-tripů, než něco ukáže, ukazuje kolečko. (Naměřeno na dvou skutečných projektech: 0,38 s poprvé, 5 ms z cache.)

Kolize jmen už démona neshodí: klíč je jméno adresáře, a když ho mají dva, tak `<org>/<repo>`. Padnout na startu kvůli klonu na špatném místě byl špatný tvar — `main-panel` se na malém displeji čte, `chytre-digital/main-panel` jen když musí.

**Hotovo, když:** na jedné obrazovce vidím každý projekt, jeho specialisty a co v něm zrovna běží. — ✅ ověřeno proti skutečnému disku (2 projekty, 3 worktree správně vynechané) i testy (`tests/test_serve.py`).

---

## 5. Ochrana — co musí platit, než to poprvé pustím ven

1. Démon poslouchá **na loopbacku**; do tailnetu ho pouští `tailscale serve`, ne bind na `0.0.0.0`. Rozdíl je v tom, co se stane při chybě: špatně napsaná autorizace v démonu je pak pořád dosažitelná jen z tailnetu, ne z celé domácí sítě.
   `tailscale funnel` je tentýž příkaz o slovo vedle a vystavuje službu do veřejného internetu — v tomhle projektu se nepoužije nikdy.
2. Bez tokenu zařízení nefunguje žádný endpoint kromě párování; párovat lze jen v okně po startu démona (`--pair-window`, výchozí 5 min), a to okno se zavře prvním spárovaným zařízením nebo pátým špatným kódem.
3. Spustit lze **jen pack, který v aktivovaném projektu existuje** — jméno packu se nikdy nepředává do shellu, jde jako argv prvek do `agency`.
4. Prompt jde agentovi tak, jak ho vlastní jádro ([`launch_argv`](../../packages/core/src/agency/runs.py)), ne skládáním příkazové řádky v démonu.
5. `--bypass` jen ze zařízení, které ho má povolené při párování.
6. Okno aktivace vyprší samo; po vypršení démon běží dál a odpovídá „projekt není aktivovaný".

---

## 6. Co v1 vědomě neumí

- **Seznam nálezů a triage.** Rozhodnutí o nálezu patří k řádku kódu; mobil ukáže počty z brány a tím to končí. První položka v2.
- **Týmy.** `agency chain` sekvenci umí, chybí jí jen jméno. Až na to dojde, tým bydlí jako `.claude/skills/agency-team-<name>/team.json` — komitnutý vedle packů, které řadí, tedy táž věc jako pack. `.agency/teams.json` ne: to je přesně ten konfigurační soubor, který [`agency-v1.md`](agency-v1.md) vyhodil.
- **Fronta pro vypnuté PC.** Vypnuté PC znamená „nejde to", ne „spustí se to potom". Fronta chce relay a relay chce provoz.
- **Notifikace.** Stránka drží SSE, dokud je otevřená. Push potřebuje PWA a HTTPS, tedy Krok „Cloudflare" níž.
- ~~**Druhý projekt na jedno kliknutí.**~~ — Přehodnoceno 4. 9. 2026, viz Krok 4.
- ~~**Převzetí session z telefonu.**~~ — Hotovo 5. 9. 2026, viz Krok 2.
- ~~**Navázat na doběhnutý běh další otázkou.**~~ — Hotovo 5. 9. 2026, viz Krok 5.
- **Živý průběh Remote Control session.** Nezmění se: interaktivní `claude` strojový stream nevydává (§3.6). Telefon ukáže jméno session a to, že skončila; co se v ní dělo, je v Claude appce.

---

## 7. Náhradní transport, až bude vadit VPN v mobilu

`cloudflared` jako služba na Windows, `agency.<doména>` → `127.0.0.1:7777`, před tím Cloudflare Access s přihlášením e-mailem a MFA. Démon se nemění ani o řádek — mění se jen to, kdo stojí před portem. Podmínkou je doména v Cloudflare a druhý běžící proces. Vlastní relay (Worker + Durable Object) má smysl teprve, až bude potřeba fronta pro vypnuté PC nebo víc strojů; do té doby je to infrastruktura bez užitku.
