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

### Krok 2 — Remote Control jako druhý režim (~4 h)

- `providers.py` — u `claude` přibude `remoteControlArgs: ["--remote-control"]` (ověřeno proti `claude --help`: *„Start an interactive session with Remote Control enabled (optionally named)"*). `launch_argv()` je přidá, když si o ně volající řekne; jméno session je `agency-<pack>-<runId první 8>`, aby šlo v Claude appce poznat, co to je.
- **Spike, který se musí udělat první:** attended `claude` chce terminál, a démon žádný nemá. Pořadí pokusů: `CREATE_NEW_CONSOLE` (na PC se otevře okno, což doma nevadí a večer je to i vodítko), pak `claude --bg` + `attach`. Když ani jedno nedrží, krok se odloží a v mobilu zůstane jen **Spustit** — režim, který uživatel stejně vybral jako první.

**Hotovo, když:** tlačítko **Převzít** otevře session, kterou v Claude appce najdu pod jménem specialisty, odpovím jí na dotaz na oprávnění a pak z mobilu pustím bránu.

### Krok 3 — stránka (~4 h, souběžně s Krokem 1) — **hotovo 4. 9. 2026**

Jeden `index.html` v `packages/core/src/agency/_web/`, servírovaný démonem. Tři obrazovky: projekty → specialisté (řádek = titul, dvě tlačítka) → běh (průběh, pak výsledek brány). Prompt je `<textarea>`, PR je seznam z `agency prs`. Žádný framework; když stránka poroste přes jeden soubor, je to signál, že měla být PWA.

**Co plán nepředpokládal**

- **Obrazovky jsou čtyři.** První je párování — kód z konzole a jméno zařízení; token pak leží v `localStorage`. Bez ní by první otevření stránky bylo 401 bez vysvětlení.
- **Tlačítko je jedno, ne dvě.** Druhé patří Kroku 2 a tlačítko, které vrací 501, není tlačítko. Přibude s ním.
- **`EventSource` se po `done` zavírá z klienta.** Prohlížeč se po ukončeném streamu sám připojí znovu, takže bez toho by konec běhu přehrával dokola.
- **Resume jede přes `Last-Event-ID`.** Tu hlavičku posílá prohlížeč při reconnectu sám; `?offset=` zůstává pro ruční otevření. Resume, který závisí na tom, že si klient vzpomene přidat parametr, je resume, který jednou přehraje hodinu volání nástrojů.
- **Stránka se nikdy necachuje** (`Cache-Control: no-store`) a čte se z disku při každém požadavku — úprava na počítači je živá po přetažení prstem, ne po vyčištění cache telefonu.
- **Konzole démona nesmí shodit request.** Nalezeno při smoke testu: `✓` po úspěšném párování narazilo na cp1250 konzoli, vyhodilo `UnicodeEncodeError` a telefon dostal 500 za něco, co už proběhlo. Řádek na konzoli je zdvořilost, odpověď telefonu je práce.

**Hotovo, když:** stránka na telefonu spustí specialistu a ukáže jeho průběh. — ✅ postavené; ověřená je syntaxe skriptu, tvary všech odpovědí, které stránka čte, proti skutečnému projektu, a že se servíruje bez cache. Klik z telefonu je na tobě.

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
- **Druhý projekt na jedno kliknutí.** `--project` se dá dát vícekrát, ale přepínání projektů v UI je seznam, ne funkce.

---

## 7. Náhradní transport, až bude vadit VPN v mobilu

`cloudflared` jako služba na Windows, `agency.<doména>` → `127.0.0.1:7777`, před tím Cloudflare Access s přihlášením e-mailem a MFA. Démon se nemění ani o řádek — mění se jen to, kdo stojí před portem. Podmínkou je doména v Cloudflare a druhý běžící proces. Vlastní relay (Worker + Durable Object) má smysl teprve, až bude potřeba fronta pro vypnuté PC nebo víc strojů; do té doby je to infrastruktura bez užitku.
