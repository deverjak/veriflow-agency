# Týmy — chainování specialistů nad jedním cílem

**Datum:** 2026-09-01
**Navazuje na:** [`../implementation-plan-v0.md`](../implementation-plan-v0.md) (roster; rozhodnutí jako operace nad úložištěm), [`shared-memory.md`](shared-memory.md) (Krok 1 je společný pro oba plány)
**Řeší:** víc specialistů nad jedním cílem v pořadí, kde druhý soudí výstup prvního — pipeline (product owner dostane nálezy právníka jako zadání) a v druhém kroku řízenou diskusi (product owner usměrní další kolo právníka).
**Pořadí prací napříč plány:** [`tasks.md`](tasks.md)

---

## 1. Proč

Konkrétní případ, ze kterého tohle vzniklo: ve webovém repu byly VOP, do kterých LLM dotlačilo povinnosti, které z žádného předpisu neplynou — složitý reconsent, publikaci nového znění, archivaci verzí. Pack `legal` na tohle dimenzi má (`over-compliance` — *„Duties the product invented for itself“*, [`packs/legal/pack.json:46`](../../packs/legal/pack.json)). Ale druhá půlka soudu je produktová, ne právní: *„reconsent flow je pro tenhle web irelevantní, protože nemá uživatelské účty“* neumí říct právník, umí to říct product owner. Dnes ty dvě hlavy spojuje člověk — čte právníkovu frontu a sám hraje PO.

Chain z toho dělá práci nástroje: právník běží první, product owner dostane jeho nálezy **jako zadání** — ne jako pozadí — každý rozhodne (`accept` / `reject` s důvodem / `defer`) a na člověka jde rozhodnutá fronta, ne surová.

To je celá pointa: **výstup chainu není víc nálezů, ale míň nerozhodnutých.** Triage člověkem je nejdražší krok celého lifecycle — a přesně ten chain zlevňuje.

---

## 2. Co už stojí a chainování to jen použije

Ověřeno v kódu 1. 9. 2026. Většina „chainování“ v projektu existuje jako primitiva — jen nejsou spojená.

| primitivum | kde | co dává chainu |
|---|---|---|
| sdílená paměť běhů | `known_memory()`, [`runs.py:480`](../../packages/core/src/agency/runs.py) | každý běh už dnes dostává nálezy všech předchozích běhů **včetně rozhodnutí**, napříč packy i hiry |
| rozhodnutí jako operace nad úložištěm | `agency triage … --by`, [`cli.py:1905`](../../packages/core/src/agency/cli.py); append-only `decisions.jsonl`, [`runs.py:804`](../../packages/core/src/agency/runs.py) | agent smí rozhodovat o cizím nálezu **už dnes** — extension i agent píší toutéž cestou |
| poznámky k nálezu | `agency note`, [`cli.py:1930`](../../packages/core/src/agency/cli.py) | vlákno diskuse nad nálezem, oddělené od rozhodnutí (a od metrik) |
| roster | [`hires.py`](../../packages/core/src/agency/hires.py) | tým je výběr z rosteru — hire je už dnes (pack × provider × model) s vlastní identitou |
| zadání ve dvou vrstvách | `resolve_brief()`, [`runs.py:207`](../../packages/core/src/agency/runs.py) | `standing` platí pořád, `focus` jen tento běh — usměrnění dalšího kola má kam vstoupit, aniž by přepsalo trvalé zadání |
| marker idempotence nese hire | `review_marker()`, [`runs.py:242`](../../packages/core/src/agency/runs.py) | dva specialisté nad jedním PR se nevylučují |
| launch kontrakt pro klienty | `agency run --json`, [`cli.py:801`](../../packages/core/src/agency/cli.py); [`review.js:313`](../../packages/extension/src/review.js) | tvar spuštění vlastní CLI, klient ho jen posílá do terminálu — chain tuhle hranici nemění |

**Co chybělo, byla jediná schopnost jádra: spustit agenta a vědět, kdy skončil.** `cmd_run` běh připravil a příkaz vytiskl (nebo se do něj `--launch` proměnil přes `execvp`); docstring `cmd_cleanup` to říkal výslovně — *„no pid to watch and no exit code to catch“*. Chain je běh → počkej → ingest → další běh. Zbytek je kontrakt handoffu, ne nová infrastruktura. **Krok 2 to doplnil 1. 9. 2026** — `agency run --wait` čeká, zapisuje `agent.exitCode` a bránu pouští sám.

---

## 3. Tvarová rozhodnutí

**1. Chain je sekvence běhů, ne konverzace.** Handoff je soubor (`findings.json` + `decisions.jsonl` + `summary.md`), ne zpráva v session. Všechno, co si agenti „řeknou“, je append-only událost nad nálezem — stejná filozofie, na které už stojí triage. Díky tomu je diskuse auditovatelná po jednotlivých událostech a dá se přehrát.

**2. Jeden tým = jeden provider (v1).** Vědomé zúžení: jeden binár, jeden credential, jedna sada quirks na terminálu. Handoff je souborový, takže mix providerů **není** architektonická překážka — až se pipeline osvědčí, je to změna jedné validace v Kroku 3, ne přestavba. (Paralelní běh dvou providerů nad týmž PR je jiná věc a roster ho umí už dnes.)

**3. Pořadí volí člověk, ne model.** Žádný LLM orchestrátor, který rozhoduje, kdo poběží příště. Chain je deterministický seznam; úsudek patří dovnitř běhů, ne mezi ně.

**4. Diskuse je ohraničená.** v1 je pipeline — jeden průchod. v2 přidá druhé kolo se steeringem, a tam to končí: neohraničená debata dvou modelů je spálený rozpočet bez zastavovací podmínky.

**5. Odmítnutý krok chain zastaví.** `cmd_run` umí běh odmítnout (`draft`, `already-reviewed`, `no-files`, `no-brief`); pokračovat potichu by znamenalo, že product owner soudí nálezy, které nevznikly. Chain vytiskne, co doběhlo a proč stojí.

**6. Prompt kroku skládá orchestrátor — deterministicky, z kusů, které napsali agenti.** Týmové chování stojí a padá s tím, jak se člen „vykopne“: co je jeho role v řetězu, co je upstream a co s ním má udělat. Dnešní jednořádkový prompt ([`cli.py:784`](../../packages/core/src/agency/cli.py)) na to nestačí. Šablonu vlastní jádro — je testovatelná a celá skončí v `prompt.txt` běhu, takže kvalita vykopnutí se dá číst a ladit. Obsahové kusy ale nepíše jádro ani třetí model: píší je členové týmu **uvnitř svých běhů** (`handoff.md`, steering) — tam jsou zaznamenané a atribuované. „Orchestrátor napíše prompt“ tedy znamená: šablona jádra + slova upstream agenta, ne skrytý LLM krok mezi běhy.

---

## 4. Kroky

### Krok 1 — společný základ se sdílenou pamětí (~1 den)

Plná specifikace v [`shared-memory.md`](shared-memory.md), Krok 1 — je to týž krok, dělá se jednou. Chain z něj potřebuje tři věci:

- **strukturovanou identitu `by`** (`hire:<id>` / `human`) — bez ní se „po@claude zamítl právníkův nález“ nedá odlišit od ručního rozhodnutí v CLI,
- **`RUN_DIR/summary.md`** jako výstup běhu — kompaktní „co jsem zjistil a co jsem s tím udělal“ pro dalšího v řadě; 300 položek `known-findings.json` není handoff, je to pozadí,
- **`knowledge.py`** — jediné místo, kde se skládá „co projekt ví“; příprava kroku N v chainu z něj bere upstream výběr místo vlastního průchodu přes `load_runs()`.

### Krok 2 — `agency run --wait` (~půl dne) — **hotovo 1. 9. 2026**

- [x] Spustit `launch` argv jako subprocess ve worktree, počkat, exit code zapsat do run recordu (`agent.exitCode`), po doběhnutí automaticky `ingest`.
- [x] `--launch` (execvp) zůstává pro ruční použití; `--wait` je nová cesta a jediná, kterou chain volá. (`os.execvp` je na Windows beztak polospolehlivý — nahrazení procesu tam ve skutečnosti neexistuje.)
- [x] Attended charakter se nemění: subprocess běží v témže terminálu, uživatel ho vidí a může do něj vstoupit. Mění se jen to, že po skončení má jádro exit code a nemusí prosit o `agency ingest` ručně.

> **Kontrola hotovosti:** `agency run legal --wait` doběhne, ingest proběhl bez druhého příkazu, běh není `running` a record má `agent.exitCode`. — ✅ ověřeno end-to-end proti `legal@fake` (provider s `.CMD` binárkou) ve všech čtyřech koncích: 0, nenulový bez zápisu, nenulový se zápisem, chybějící binárka. `tests/test_wait.py` (10 testů).

### Co plán nepředpokládal

- **Windows si k příkazu domyslí jen `.exe`.** `subprocess` i `os.execvp` hledají holé jméno v PATH bez rozvinutí PATHEXT, takže `codex` — fakticky `codex.CMD` — skončí jako `FileNotFoundError`. Ověřeno na skutečné instalaci, ne odvozeno z dokumentace. Binárka se proto před spuštěním rozvine přes `shutil.which`; tentýž řádek dostal i `--launch`, kde ta díra byla celou dobu a nikdo o ní nevěděl, protože `claude` je `.EXE`.
- **`--wait` a `--json` se vylučují.** Agent píše do téhož stdout jako CLI. Kontrakt „na výstupu je jeden JSON dokument“, na kterém stojí extension, se u toho nedá slíbit — a slib, který rozbije cizí výpis, je horší než chybějící kombinace přepínačů. Chain volá jádro zevnitř, takže o nic nepřichází.
- **Exit code musí bránu přebít, ne nahradit.** Brána bez `findings.json` napíše `no-findings`, což je tvrzení „díval se a nic nenašel“ — u agenta, který skončil jedničkou, je to nepravda. Pořadí je proto: co agent stihl zapsat, projde branou jako vždycky, a teprve pak se stav přepíše na `failed` s `exitReason`. Nálezy se nezahazují, ale běh se netváří jako úspěšný.
- **`needs-login` a `quota` zůstávají nevyplněné.** `run.v1` je v enumu stavů má a exit code by se na ně dal mapovat — jenže žádný z providerů své návratové kódy nedokumentuje. Odhad by vyrobil číslo, které nikdo neověří, a metriky stojí na tom, že se v nich nehádá.
- **`cost.wallClockSeconds` se zapnulo mimochodem.** V `run.v1` je od začátku, metriky ho čtou (`s per candidate`) a nikdy ho nic nevyplnilo — protože nebyl proces, který by měřil. Vlastnictví procesu to spravuje zadarmo; přibylo k němu `cost.provider/model/credential`, credential odvozený z `trigger.attended`, ne z domněnky.
- **Ctrl-C konečně něco znamená.** U `--launch` přerušení nikdo nezaznamená. Tady rodičovský proces žije dál, takže běh zavře jako `abandoned` a uklidí worktree, na který by uživatel jinak musel přijít sám.
- **Worktree se po doběhnutí nemaže.** Brána je automatická, úklid ne: běh sice skončil, ale worktree je jediné místo, kde se dá dohledat, nad čím agent pracoval. `agency cleanup` zůstává rozhodnutím člověka — u chainu (Krok 3) to bude vlastní rozhodnutí, protože tam se worktree hromadí po krocích.

### Krok 3 — `agency chain` (~1–1,5 dne) — **hotovo 1. 9. 2026**

```
agency chain legal po --prompt "VOP pro nový web"
agency chain legal@claude po@claude --pr 12
```

- Každý ref projde `hires.resolve()` — jméno hire vyhrává nad jménem packu, přesně jako u `run`.
- Validace v1: všichni členové na stejném provideru, jinak odmítnout s vysvětlením (viz §3.2).
- `chainId` = ulid. Každý `run.json` dostane blok `chain: {id, position, of, upstream: [runId…]}` — a `run.v1` schema se o něj rozšíří.
- **Handoff:** příprava kroku N zapíše `evidence/upstream.json` — plné nálezy + rozhodnutí + `summary.md` upstream běhů, **bez stropu** (strop 300 patří pozadí, ne zadání) — a `context.json` dostane blok `chain`.
- **Prompt kroku** (viz §3.6): orchestrátor rozšíří dnešní jednořádkový prompt o chain blok z deterministické šablony. Dva tvary — první člen a navazující člen:

  ```
  [method hint] RUN_DIR=… — start from its context.json. Required output: findings.json (finding.v1).
  You are step 2/2 of a chain (po@claude).
  Upstream: legal@claude — 7 findings (5 undecided), full data in evidence/upstream.json.
  First judge the upstream findings (agency triage … --by hire:po@claude), then run your own dimensions.
  Handoff from legal@claude: <obsah RUN_DIR/handoff.md upstream běhu, zkrácený na ~40 řádků>
  Brief for this run: <--prompt / scénář>
  ```

  Celý složený prompt jde do `prompt.txt` jako dnes — vykopnutí každého člena je zaznamenané a dá se ladit. Zadání per člen (`--focus po:"…"`) je snadné rozšíření, přidá se, až o něj první reálný chain řekne.
- **`handoff.md`:** volitelný výstup běhu vedle `summary.md` (Krok 1) — přímá zpráva dalšímu v řadě: co jsem nedořešil, na co se dívat, čemu nevěřit. `summary.md` je „co jsem udělal“ (pro člověka, log a paměť), `handoff.md` je „co potřebuješ ty“ (adresné). Když chybí, použije se `summary.md`; když chybí obojí, jen počty z `evidence/upstream.json`. Kontrakt v SKILL.md — Krok 4.
- Odmítnutí nebo nenulový exit kroku chain zastaví; vytiskne se, které běhy doběhly a čím to stojí. Přerušený chain se neresuscituje (`--resume` až to bude potřeba doopravdy) — běhy jsou zapsané, dokončit je jde ručně.
- `agency status` ukáže chain id u běhů, které v nějakém jely — skupinové zobrazení stačí textově.

### Krok 4 — metoda: handoff a soud nad upstreamem (~3 h) — **hotovo 1. 9. 2026**

- [`packs/po/skill/SKILL.md`](../../packs/po/skill/SKILL.md): nová sekce — když má `context.json` blok `chain` s `upstream`, projdi upstream nálezy **před** vlastními dimenzemi. Každý rozhodni `agency triage accept|reject|defer … --by hire:<id>` (id je v `context.json.hire`), nebo aspoň okomentuj `agency note`. Nálezy, které z toho vzniknou („právník navrhuje reconsent; roadmapa říká, že účty letos nebudou“), jdou normálně do `findings.json`.
- Všechny packy, které můžou stát v chainu jinde než na konci (v1: `legal`), dostanou do SKILL.md odstavec o handoffu: běžíš-li v chainu, zapiš `RUN_DIR/handoff.md` — pár odstavců **pro dalšího člena**, ne rekapitulaci. Co jsem nedořešil, kde jsem si nejistý, co z nálezů stojí na domněnce o produktu, kterou má potvrdit on.

### Co plán nepředpokládal (Kroky 3, 4, 6)

- **`run.v1` má zavřený seznam klíčů i nahoře.** Potřetí táž past (po `run.graph` ve Fázi 0 a `evidence` u rankeru): `additionalProperties: false` znamená, že blok `chain` bez zápisu do schématu udělá z každého týmového běhu neplatný záznam. Kdo bude přidávat další blok, narazí taky.
- **Členy je nutné jmenovat hire id, ne packem, když se má poznat provider.** `hires.add` napřed **zhmotní stávajícího pracovníka**, takže po `agency hire po --provider codex` existuje `po@claude` i `po@codex` — a holé `po` sáhne po tom prvním. Validace „jeden provider" je tím pádem pravdivá, ale uživatel si ji snadno obejde, aniž by chtěl. Ukázalo se to až testem, který kvůli tomu spustil skutečnou binárku.
- **Test málem pustil skutečného agenta.** `cmd_chain` končí u `proc.attend`, tedy u `claude` na stroji, který testy pouští. `test_chain.py` má proto autouse pojistku: výchozí `proc.attend` padá s vysvětlením a podstrčit agenta se musí vědomě. Bez ní je každý zapomenutý monkeypatch spuštěná binárka.
- **Pořadí členů se v UI nedá vybrat najednou.** VS Code QuickPick s `canPickMany` **nezaručuje pořadí** výběru, a pořadí je u řetězu celý smysl. Výběr je proto po jednom, s „Run the team" od druhého člena dál — o dvě kliknutí otravnější, zato je vidět, kdo soudí koho.
- **Extension nemůže použít `--json` kontrakt.** `chain` si běhy pouští sám přes `--wait`, a ten se s `--json` vylučuje (agent píše do téhož stdout). Klient tedy neposílá do terminálu hotové `launch` argv od jádra, ale rovnou `agency chain …`. Hranice „jádro rozhoduje, klient zobrazuje" se nemění — jen se posouvá o úroveň výš, na celý řetěz.
- **`handoff.md` se zaznamenává i u samostatného běhu.** Pack neví, jestli za ním někdo stojí. Zapsat ho zbytečně je levnější než ho nemít, až bude potřeba, takže `outputs.handoff` vzniká vždycky.
- **Neúplný řetěz musí být poznat na první pohled.** Proto je v záznamu `of`, ne jen `position`: bez něj by zastavený tým vypadal v přehledu jako dokončený, jen kratší. UI ho kreslí oranžově a tooltip řekne, kolik kroků chybí.

### Krok 5 — druhé kolo se steeringem (v2, ~1 den, **odložit**)

Dělá se, až pipeline doběhne aspoň na dvou reálných případech. Tvar:

- Poslední člen chainu smí zapsat `RUN_DIR/steering.json`: `[{hire|pack, focus: "…"}]` — usměrnění, ne příkaz.
- `agency chain … --rounds 2`: po posledním kroku se orchestrátor vrátí k prvnímu členu s `focus` = steering (vrstva `focus` z `resolve_brief`; `standing` zůstává netknutý).
- Marker idempotence dostane číslo kola, jinak by druhé kolo skončilo na `already-reviewed` vlastního prvního kola.
- Strop `--rounds` je 2. Víc kol znamená, že zadání bylo špatně, ne že je potřeba víc konverzace.

### Krok 6 — extension (~půl dne, po CLI) — **hotovo 1. 9. 2026**

- Přehled: běhy jednoho chainu jako skupina; tlačítko „Run team“ až když si tvar CLI sedne.
- Orchestruje pořád CLI — extension pošle do terminálu `agency chain …` stejně, jako dnes posílá launch jednoho běhu ([`review.js:321`](../../packages/extension/src/review.js)). Žádná orchestrace v JS; hranice „jádro rozhoduje, klient zobrazuje“ se nemění.

---

## 5. Co se vědomě nedělá

- **Message bus / živý chat mezi agenty.** Neohraničené, neauditovatelné, drahé. Události nad nálezy (`decisions.jsonl`) dávají tutéž diskusi čitelně a s možností přehrání.
- **LLM, který mezi kroky píše nebo přepisuje prompty.** Kvalitu vykopnutí řeší šablona jádra + kusy psané agenty uvnitř běhů (`handoff.md`, steering) — obojí zaznamenané a atribuované. Třetí model mezi běhy by byl úsudek, který nikde nebydlí: nevznikne z něj record, nález ani rozhodnutí, a přesně tomu se celý nástroj brání.
- **LLM orchestrátor.** Kdo poběží a v jakém pořadí, je rozhodnutí člověka. Nástroj, jehož smyslem je měřitelnost, si nemůže dovolit nedeterministický plán běhu.
- **Paralelní fan-out uvnitř chainu.** Chain existuje kvůli závislosti výstupů — tam paralelismus nemá co dělat. Nezávislý paralelismus (dva provideři nad jedním PR) už umí roster.
- **Mixed-provider tým v1.** Viz §3.2 — vědomé zúžení, ne omezení architektury.
- **Nové reject reasons.** „Teď to není relevantní“ je `defer`; „z žádné povinnosti to neplyne“ je `reject` + `by-design` nebo `out-of-scope`. Enum zůstává — metriky přes packy zůstanou souměřitelné.

---

## 6. Souhrn rozsahu

| krok | rozsah | kdy |
|---|---|---|
| 1 — společný základ (identita, summary, `knowledge.py`) | ~1 den | první; společný se [`shared-memory.md`](shared-memory.md) |
| 2 — `agency run --wait` + auto-ingest | ~půl dne | **hotovo 1. 9. 2026** |
| 3 — `agency chain` + handoff + skládání promptu + `run.v1` | ~1–1,5 dne | **hotovo 1. 9. 2026** |
| 4 — SKILL.md: soud nad upstreamem + `handoff.md` | ~3 h | **hotovo 1. 9. 2026** |
| 5 — steering a druhé kolo | ~1 den | **v2 — až pipeline doběhne na reálných případech** |
| 6 — extension skupina + „Run team“ | ~půl dne | **hotovo 1. 9. 2026** |

Kroky 1–4 a 6 jsou hotové a dávají použitelnou pipeline `legal → po`: právníkova fronta přichází k člověku už rozhodnutá product ownerem. Otevřený zůstává jen Krok 5 (steering), a ten čeká na spouštěč, ne na kapacitu — dělá se, až pipeline doběhne aspoň na dvou reálných případech.
