# Co ověřit během běhu

**Datum:** 2026-09-08
**Navazuje na:** [`prejimka-outputs.md`](prejimka-outputs.md) — kód plánu [`plans/outputs.md`](plans/outputs.md) je hotový a otestovaný
**K čemu to je:** tohle je poslední otevřená položka přejímky. **Co se nikdy nespustilo, není hotové — jen otestované.** Seznam níž je to, co test říct nemůže, protože to stojí na hooku, na cizím boardu, na webu nebo na člověku.

**Kdy je tenhle dokument uzavřený:** až všech pět skupin níž jednou proběhne na ostrém běhu a §5 dostane první čísla. Do té doby ho měj otevřený vedle terminálu.

---

## 0. Než pustíš první běh

```powershell
agency doctor --json      # žádná failující kontrola; v main-panelu smí zůstat jen „rules vs code-review-graph“
agency packs --json       # pack má typy, které čekáš (ceo: answer/bet/draft, po: decision/ticket_draft)
```

A u CEO ještě to, co bez chyby vrátí prázdno:

```powershell
python .claude\skills\agency-ceo\scripts\scope.py    # živé sázky, ne `[]`
```

- [ ] **0.1** Doktor čistý v obou repozitářích.
- [ ] **0.2** `agency packs --json` u `po` ukazuje `decision` i `ticket_draft`, u `ceo` `answer`, `bet` i `draft`.
- [ ] **0.3** Scope skript vrací neprázdné pole. Prázdné pole není chyba skriptu — znamená, že ve `strategy.md` není živá sázka s řádkem `Ref:`.

---

## 1. Tři věci, které selžou tiše — u prvního běhu **každého** packu

Tohle je nejdůležitější sekce celého dokumentu. Všechno ostatní se pozná z výpisu; tohle ne.

### 1.1 Zapisoval vůbec někdo provenienci?

```powershell
Get-Content .agency\runs\<run-id>\tool-calls.jsonl -TotalCount 3
```

- [ ] **Soubor existuje a není prázdný.**

**Proč na tom záleží víc než na čemkoliv jiném:** `None` a `[]` znamenají v jádru opak. Když soubor chybí, jádro to čte jako *„nikdo nenahrával“* a **přeskočí celou kontrolu `unproven-source` i ověření `web_snapshot`** — schválně, protože zahodit poctivý nález kvůli nespuštěnému hooku by bylo horší. Ale to znamená, že běh bez hooku projde branou volněji než běh s ním, a **nikde to není vidět**. Když soubor chybí, výsledek toho běhu neber jako důkaz, že brána funguje.

### 1.2 Co brána zahodila a proč

```powershell
agency outputs --run <run-id> --json | ConvertFrom-Json | Select-Object -First 3
Get-Content .agency\runs\<run-id>\gated.json | ConvertFrom-Json | Select-Object reason, title, detail
```

- [ ] **`run.json → gatedBy` přečtený, ne přeskočený.** Devět možných důvodů; `below-score` mezi nimi **není** a už nikdy nebude.
- [ ] **`schema` u prvního běhu = pack píše tvar, který kontrakt odmítá.** To je chyba v `SKILL.md`, ne v bráně. Přečti `detail`, oprav příklad v packu.

**Zahození není bug.** `gated.json` je záznam k přečtení, ne fronta k opravě. Než na cokoliv sáhneš, přečti si `detail` u tří zahozených.

### 1.3 Sedí počty?

- [ ] **`run.json → counts`** má `raw`, `gated`, `duplicates`, `kept`, `sent`, `held`. Když `raw > 0` a `kept == 0`, je celý běh v `gated.json` a je pro to jeden důvod — najdi ho, nespouštěj znovu.

---

## 2. CEO — první ostrý běh nad Kvesterosem

```powershell
agency run ceo --prompt "..." --wait
agency outputs --run <run-id> --type bet --json
```

- [ ] **2.1 Sázky mají `subject`** ve tvaru `{ "kind": "bet", "ref": "<slug>" }`, a ten slug sedí s řádkem `Ref:` ve `strategy.md`. Bez toho sázka **nemá místo** — v dedupu se porovnává jen otisk, tedy identické tvrzení slovo od slova, a přeformulovaná sázka o téže věci projde jako nová.
- [ ] **2.2 Žádná sázka nenese `code` evidenci.** Ne proto, že by nesměla mít důkaz — má ho mít jiný. Kdyby ho měla, je to návrat k `footer.tsx`, kvůli kterému celý plán vznikl.
- [ ] **2.3 Poctivá sázka nepadla na `unverified-evidence`.** Když padla, jsou tři možné příčiny a je mezi nimi rozdíl:
  - artefakt není pod `RUN_DIR/evidence/` → pack stránku nestáhl, jen na ni odkázal;
  - URL v locatoru se liší od URL v `tool-calls.jsonl` (normalizuje se, ale ne přes redirect) → pack cituje jinou adresu, než otevřel;
  - `tool-calls.jsonl` chybí → viz 1.1, tohle není verdikt o sázce.
- [ ] **2.4 Čtvrtá sázka padla na `over-cardinality`**, ne na nic jiného. Strop je packův vlastní (`limit: 3`), protože zakladatel udrží tři.
- [ ] **2.5 `answer` je právě jedna** a její tělo je totéž, co je v `answer.md`. Dvě odpovědi na jednu otázku znamenají, že pack neodpověděl.
- [ ] **2.6 Drafty jsou outputy** se `subject.ref` shodným se jménem souboru v `drafts/`, a jejich `actions` je **prázdné pole** — draft posílá zakladatel, nebo nikdo.
- [ ] **2.7 `evidence/scope.json` není prázdný, `known-here.json` prázdný být smí a je to správně.** Průnik nemá co potkat, dokud neexistuje ani jeden output se `subject`. Od druhého běhu už prázdný být nesmí — a kdyby byl, hledej právě tuhle dvojici souborů.

---

## 3. PO — první ostrý běh nad main-panelem

**Tohle je ten důležitější běh.** Poprvé jde rozhodnutí na board **přes jádro**, ne z ruky agenta.

```powershell
agency run po --prompt "..." --wait
agency outputs --run <run-id> --type decision --json
```

- [ ] **3.1 Rozhodnutí existují jako outputy** a mají `state: "sent"`.
- [ ] **3.2 `actions[0].kind == "decide"`** — packovo vlastní sloveso, ne `sink`. Když je tam `sink`, skript nevytiskl `kind` a jádro si domýšlet nezačne.
- [ ] **3.3 Na boardu je komentář, `Stav` se posunul**, a u `BUILD-NOW` / `FIX-REMOVE-NOW` přibyl `priority:` label. Ověř to očima na GitHubu, ne z JSONu — tohle je to jediné, co JSON potvrdit nemůže.
- [ ] **3.4 Agent nepsal na board sám:**

  ```powershell
  Select-String "backlog.py (decide|draft)" .agency\runs\<run-id>\tool-calls.jsonl
  ```

  **Musí to nevrátit nic.** Když něco vrátí, `needs` nedrželo a migrace je jen na papíře — pack má obě cesty a tu pohodlnější si najde.
- [ ] **3.5 Hlavička dispozice se přečetla.** Když tělo rozhodnutí nezačíná `Disposition: <jedna z pěti>`, dispatch selže s čitelnou hláškou, output zůstane `candidate` a v `actions` je `result: "error"`. To je správné chování, ne pád — ale znamená to opravit příklad v `SKILL.md`.
- [ ] **3.6 Rozhodnutí bez `subject.ref` neprošlo branou.** Nemá kam se poslat a nemá místo pro dedup.
- [ ] **3.7 Idempotence:** pusť `agency ingest --run <run-id>` **podruhé**. Na boardu nesmí přibýt nic, `dispatchErrors` musí být prázdné a `counts.sent` nesmí narůst. Drží to marker `<!-- agency:po:<key> -->`, ne jádro.
- [ ] **3.8 Neúspěšný dispatch se opakuje, ne ztrácí.** Když board odmítne (např. `gh` vyprší), output zůstane `candidate`, pokus je v `actions` s `result: "error"` a v `run.json → dispatchErrors`. Další `agency ingest` to zkusí znovu. Ověř to aspoň jednou schválně — třeba odhlášením `gh` na jeden běh.
- [ ] **3.9 Druhý běh PO nad týmž ticketem** rozhodnutí **nepošle znovu** — `counts.duplicates` naroste, `sent` ne.
- [ ] **3.10 `ticket_draft` skončil jako draft na boardu**, ne jako issue. Povýšení je ruční sloveso a zůstalo ruční.

---

## 4. Review pack — regrese, kterou je nejsnáz přehlédnout

Kroky 8 a 9 sáhly na bránu a na kotvu. Testy říkají, že se review chová stejně; **první ostrý běh na tom PR to má potvrdit na živých datech.**

- [ ] **4.1 `agency outputs --json` u nálezu pořád nese `drift` a `resolved`.** Když `resolved.via` je `none` u čerstvého nálezu, kotva se nenavázala a čtyřvrstvé řešení nepracuje nad novým tvarem.
- [ ] **4.2 Dedup se nevynuloval.** Pusť review dvakrát nad týmž PR. Na druhém běhu musí `counts.duplicates` odpovídat tomu, co byl zvyklý — historicky **kolem 80 % objemu**.

  **Když je najednou nula, je to ta nejdražší tichá chyba celého plánu:** pack píše `code` locator **bez `symbol`**, klíč místa spadne ze `sym:getUser` na `file:src/auth.ts`, a projekt začne hlásit znovu celý backlog. Nic na to neupozorní. Kontrola je jednořádková:

  ```powershell
  agency outputs --run <run-id> --json | Select-String '"symbol"'
  ```
- [ ] **4.3 `phantom-file` pořád počítá.** Když u packu spadl na nulu a místo něj narostlo `unverified-evidence`, halucinovaný soubor se počítá pod špatným jménem a počítadlo halucinací lže o zlepšení.
- [ ] **4.4 Nález má `score` a nikdo ho kvůli němu nezahodil.** Nízké score už není důvod. Když ti mizí nálezy, důvod je v `gatedBy` a jmenuje se jinak.

---

## 5. Za dva týdny — smyčka, která tomu dává smysl

Bez tohohle je celé zobecnění datového modelu jen hezčí schéma. **Chyba, která se neprojeví jako pád testu, ale jako prázdná tabulka po šesti měsících.**

- [ ] **5.1 Zakladatel vybral ze sázek:** `agency feedback <id> selected|rejected --by human`.
- [ ] **5.2 Vlastník odpověděl na rozhodnutí** — a zapsal to **příští běh PO**, ne člověk ručně: `agency feedback <id> upheld|overridden|reverted`. Krok je v `packs/po/SKILL.md` ještě před vlastními dimenzemi.
- [ ] **5.3 Zapisuje se jen to, co board doopravdy ukazuje.** Rozhodnutí, na které nikdo neodpověděl, nedostane nic. **Ticho není souhlas** a odhad by změřil jen vlastní optimismus.
- [ ] **5.4 Čísla vznikla:**

  ```powershell
  agency metrics --json | ConvertFrom-Json | Select-Object -ExpandProperty byLifecycle
  ```

  Čekej klíče `ceo/bet/selection`, `ceo/bet/outcome`, `po/decision/outcome`, `po/ticket_draft/outcome`. Prázdné `byLifecycle` po dvou týdnech znamená, že nikdo nezapsal verdikt — ne že mechanismus nefunguje.
- [ ] **5.5 `success_rate` neředí nevybrané sázky.** Sázka, kterou zakladatel odmítl, nesmí sedět ve jmenovateli outcome. Drží to `requires: "selection.selected"`.
- [ ] **5.6 Až bude deset rozhodnutých nálezů, pusť revizi metody:** `agency metrics --for-author <pack>`.

---

## 6. Kam se dívat

| Otázka | Kde |
|---|---|
| Co běh napsal | `agency outputs --run <id> --json` · `--type <typ>` na jeden druh |
| Proč se něco nezveřejnilo | `.agency/runs/<id>/gated.json` → `reason` + `detail` |
| Souhrn brány | `run.json` → `counts`, `gatedBy` |
| Co se nepodařilo odeslat | `run.json` → `dispatchErrors` (co **tenhle běh** neposlal) |
| Co output kdy udělal ve světě | `actions[]` na outputu (append-only, přes všechny běhy) |
| Nahrával někdo? | `.agency/runs/<id>/tool-calls.jsonl` — **chybí = kontroly se přeskočily** |
| Čím byla zúžená paměť | `evidence/scope.json` + `evidence/known-here.json` |
| Co projekt už zamítl | `evidence/do-not-report.md` |
| Verdikty v čase | `.agency/runs/<id>/decisions.jsonl` (append-only) |
| Paměť, která přežije smazaný běh | `.agency/knowledge/trail.jsonl` |

---

## 7. Když něco nesedí

1. **Neopravuj čísla, oprav metodu.** Pack s precision 0,4 se nemá přeskórovat — má se přepsat. `agency metrics --for-author <pack>` je přesně na to a odmítne se spustit pod deseti rozhodnutými nálezy, protože pod tím se opravuje šum.
2. **Zahození je data.** Než změníš bránu, přečti tři zahozené v `gated.json`. Brána se ptá, jestli tvrzení **může** být pravdivé — ne jestli je dobré.
3. **Selhaný dispatch není selhaná brána.** Output zůstane `candidate` a další `agency ingest` to zkusí znovu. Nespravuj to ručně na boardu — rozbiješ tím marker idempotence.
4. **Ticho není výsledek.** Prázdný `findings.json` znamená „díval jsem se a nic tam není“. Když běh narazil na zeď, patří to do `blocked.md` — jinak se ty dva stavy nedají rozeznat a pack nejde pouštět bez dozoru.
5. **Když sáhneš na pack, sáhni na obě poloviny.** Manifest a `SKILL.md` se musí shodovat, jinak si model přečte tu starší. A referenční kopie v `packs/` a živý pack v cizím repu se rozejdou tiše — po každé změně je srovnej.

---

Až projdou všechny odškrtávátka výš, je plán `outputs.md` uzavřený nejen v kódu, ale i v provozu — a tenhle dokument se může archivovat vedle [`baseline.md`](baseline.md) jako záznam toho, co se první ostré běhy naučily.
