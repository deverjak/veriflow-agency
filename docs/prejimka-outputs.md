# Přejímka — `outputs.md`

**Datum:** 2026-09-08
**Předmět:** plán [`plans/outputs.md`](plans/outputs.md) — jádro Agency přestane předpokládat, že každý výstup je nález
**Rozsah:** 11 kroků, 15 commitů (`31cbea3..2ef0b4d`), 501 testů
**Verdikt:** **hotovo.** Všech pět bodů přejímky §7 platí. Co zbývá, je ostrý provoz, ne kód.

---

## 1. Ověř si to sám — pět minut

```powershell
cd veriflow-agency
git log --oneline 31cbea3^..HEAD          # 16 řádků, jeden krok = jeden commit
pwsh -NoProfile -File scripts/test.ps1    # musí říct „both passed“, 501 testů
```

Že sedí i to, co bydlí jinde:

```powershell
cd ..\kvesteros-platform
agency doctor --json          # žádná failující kontrola
python .claude\skills\agency-ceo\scripts\scope.py    # živé sázky, ne prázdné pole

cd ..\main-panel
agency doctor --json          # jediná failující je „rules vs code-review-graph“ — starší, nesouvisí
```

A ta jedna věta, na které přejímka stála:

```powershell
Select-String "decisions do not" packs\po\SKILL.md   # nic; přestala být pravdivá
```

---

## 2. Pět bodů přejímky (§7)

| | Bod | Stav | Kde je to dokázané |
|---|---|---|---|
| 1 | `agency outputs --type bet` funguje a sázka nemá ani nepředstírá code evidenci | **platí** | `test_a_bet_needs_no_anchor_and_is_not_thereby_unchecked`, `test_outputs_can_be_asked_for_one_kind` |
| 2 | Brána zahodí sázku doloženou URL, které v tom běhu nikdo neotevřel — offline | **platí** | `test_a_bet_citing_a_page_nobody_opened_is_refused` |
| 3 | `agency metrics` ukáže `selection_rate` a `success_rate` jako dvě nezávislá čísla | **platí** | `test_the_two_questions_stay_two_numbers`, `test_one_bet_answers_both_questions`, `test_a_bet_nobody_chose_is_not_pending_an_outcome` |
| 4 | Review pack se chová identicky jako před refactorem — týž dedup, týž drift | **platí** | `test_the_four_layers_read_a_code_locator_the_same_way`, `test_a_pack_that_migrates_does_not_report_its_backlog_again`, `test_an_anchored_output_keeps_the_place_it_always_had` |
| 5 | `packs/po/SKILL.md` už neobsahuje větu o obcházení jádra | **platí** | věta je pryč, a starou cestu zavírá `needs`, ne prosba v textu: `test_the_po_agent_can_no_longer_post_a_decision_by_hand` |

Bod 4 je z nich nejdůležitější a nejsnáz se přehlédne: **zobecnění, které cestou zhoršilo review, není zobecnění, ale výměna.** Proto k němu vede test, který porovnává starý a nový tvar téhož nálezu, a ne jen „testy pořád procházejí".

---

## 3. Co se za jedenáct kroků změnilo

| Krok | Commit | Co přesunul | Odhad vs. skutečnost |
|---|---|---|---|
| 1 — provenience i pro tooly bez příkazu | `f78b765` | `WebFetch` se zapisuje do `tool-calls.jsonl`, ne jen shell | ~2 h, sedělo |
| 2 — evidence dostane locatory | `927db61` | `{kind, detail, source}` → + `locator`, ověřovaný **offline** proti tomu, co běh uložil | ~1,5 dne, sedělo |
| 3 — `TypePolicy` | `5cb39b1`, `a530125` | `pack.json → outputs`, `type` na outputu, jeden poměr na lifecycle | ~1 den, dva commity |
| 4 — svislý řez: CEO `bet` | `a2797b5` | první typ, který není nález, od začátku do konce — **a přeskládal zbytek plánu** | ~1 den |
| 5 — `subject` a `run.scope` | `2265a6d` | output má místo i bez kotvy, běh má scope, paměť se zúžila i bez grafu | ~1,5 dne |
| 6 — `actions` ze `sinks` | `df8f029` | dvě zadrátované cesty ven → co output udělal ve světě, s pokusy, které selhaly | ~0,5 dne, cestou opravena idempotence ingestu |
| 7 — feedback jako události | `e515e02` | jedna odpověď **na otázku**, ne jedna na output; `requires` ožilo | ~1,5 dne → **hotovo za půl** |
| 8 — `score` přestane být branou | `179e7b9` | `below-score` pryč, strop rozhoduje *kolik*, score *které* | ~0,5 dne |
| 9 — kotva jako `evidence.kind = code` | `3c755f0` | čtyři vrstvy do `locator`, `anchor.of()` čte oba tvary | ~2 dny → **nebyl nejdražší** |
| 10 — migrace PO a CEO na jádro | `72a1292` | rozhodnutí je output; stará cesta zavřená přes `needs` | ~1,5 dne |
| 11 — rename `finding` → `output` | `2ef0b4d` | `agency outputs` hlavní, `findings` alias napořád | ~0,5 dne |

Plus tři nefunkční commity, které k plánu patří: `be4cebf` a `34a37f0` (předávka a inventura mezi sessions) a `959b0f7` (kód mluví anglicky, plány česky).

---

## 4. Pět míst, kde plán neměl pravdu

Tohle je ta část přejímky, která má cenu za rok. Ne co se povedlo — kde byl odhad špatně a proč.

1. **Krok 4 měl být ověřením, byl to přeskládání plánu.** Svislý řez jednoho typu (`bet`) našel, že `dedup.symbol_key` padá na `file:?`, takže **každý output bez kotvy sdílel jedno místo** — a pojistka „dvě tvrzení na různých místech jsou dvě tvrzení" se obrátila v svůj opak. Čtyři různě formulované sázky se složily do jedné. Našel to běh, ne úvaha, a tím se `subject` (Krok 5) z vylepšení stal nutností.

2. **Past, kterou Krok 7 čekal, nenastala.** Plán se bál, že fold historie je rozsypaný na deset míst; byl jeden a jen moc hrubý. Krok stál polovinu odhadu. Nastala jiná: **podmínka, která zahodí odpověď.** `requires` říká, které otázky jsou otevřené — kdyby rozhodovalo i o tom, které odpovědi se počítají, sázka označená `successful` bez zapsaného `selected` by z metrik zmizela úplně.

3. **U Kroku 8 nechyběla náhrada — existovala a nikoho nechránila.** `outputs.<type>.limit` je v jádru od Kroku 3, jenže `outputs` blok měl **jeden ze sedmi packů**. Nebezpečí nebylo v tom, že náhrada chybí, ale že je a nekryje. Odtud backstop `RUNAWAY = 25`, změřený z `baseline.md`, ne odhadnutý.

4. **Číslo „58 výskytů" u Kroku 9 měřilo špatnou věc.** Většina z nich je slovo „anchor" jako **jméno mechanismu** a nikam nejde. Míst, která čtou pole nálezu, bylo jedenáct a schovala se za dvě funkce. Drahá byla dokumentace packů, ne jádro. — Chyba, o vlásek nespáchaná: nechat vymyšlený soubor v locatoru padat dál na `unverified-evidence`. Pack po migraci by měl `phantom-file` **nula** a vypadal by, že přestal halucinovat.

5. **Krok 10 nebyl „jen přejímka", jak jsem ho v plánu popsal.** Otevřel dvě mezery v jádru, které mohl najít jen ostrý typ se sinkem: typ, který smí jednat, neměl kam zapsat, že jednal (spadl by až v běhu, potom, co už na board napsal), a `agency feedback` odmítal každý typ se sinkem — takže rozhodnutí přehlasované vlastníkem nemělo kam. A jedna věta v „prvním pohybu" byla přímo chybná: *pět dispozic jsou `kinds` v lifecyclu*. Nejsou. Dispozice je **obsah** rozhodnutí; `kinds` jsou verdikty **o** něm.

---

## 5. Co zůstalo vědomě otevřené

Každá z těchhle věcí byla rozhodnutá, ne zapomenutá.

* **`sinks` a `anchor` ve `finding.v1`** zůstávají jako superseded. Nemažou se — committed historie tří repozitářů je má a jádro z nich pořád čte. Rozdíl mezi nimi: `sinks` je nahrazený tvar, `anchor` je **pořád správný**, jen se nemá psát nový.
* **`minScore` v manifestech** nedělá nic a `agency doctor` to řekne. Klíč není chyba — manifest nemá schéma.
* **`stop_errors()` nekontroluje artefaktové locatory.** Code locatory dostal zadarmo v Kroku 9; o neuloženém `web_snapshot` se agent dozví až od brány. Odloženo, dokud to neukáže první ostrý běh CEO.
* **`decisions()` žije vedle `verdicts()`.** „Rozhodl o tom vůbec někdo?" je jiná otázka než „jak dopadla otázka X".
* **`core` jako zdroj feedbacku nevznikl a nemá.** `duplicate` je stav v potrubí, ne verdikt; kdyby jádro svoje účetnictví zapisovalo jako feedback, precision by počítala rozhodnutí, která nikdo neudělal. Zamčeno testem.
* **`dispatchErrors` v `run.json` zůstává.** `actions[]` je append-only a říká, co se s outputem kdy stalo; `dispatchErrors` se přepočítá při každém ingestu a říká, co tenhle **běh** neodeslal. Dvě otázky.
* **Registry CEO packu zůstávají paměťové stránky**, output typem se nestaly. Zdvojily by mechanismus, který v `knowledge/pages/` funguje.

---

## 6. Co může říct jen ostrý provoz

Tohle je jediná otevřená položka celé přejímky. **Kód je hotový; co se nikdy nespustilo, není hotové — jen otestované.**

1. **První běh CEO nad Kvesterosem.** Vzniknou sázky jako outputy se `subject`? Sedí scope ze `strategy.md`? A hlavně: nezahodí brána poctivou sázku na `unverified-evidence`? Kontrola „URL bylo otevřené v tomhle běhu" je nejmladší a jediná, která stojí na hooku.
2. **První běh PO nad main-panelem je ten důležitější**, protože poprvé posílá rozhodnutí na board **přes jádro**. Sleduj `actions[]` na outputu: úspěch nese packovo vlastní sloveso (`decide`, `draft`), neúspěch nese `error` a output zůstane `candidate` na další pokus.
3. **Zakladatelův a vlastníkův verdikt.** Dokud nikdo neřekne `agency feedback <id> selected|rejected` resp. `upheld|overridden|reverted`, nemá `selection_rate` ani `upheld_rate` jmenovatele. §5 „explicit" a „derived" jsou zatím tvrzení podepřená testem, ne provozem.
4. **`known-here.json` bude na prvním běhu prázdný, a je to správně.** Průnik nemá co potkat, dokud neexistuje ani jeden output se `subject`. Naplní se od druhého běhu.

Pravidlo pro to, co přijde potom: **neopravuj čísla, oprav metodu.** Pack s precision 0.4 se nemá přeskórovat — má se přepsat, a `agency metrics --for-author <pack>` je přesně na to.

---

## 7. Kde teď co bydlí

| Co | Kde |
|---|---|
| politika typů | [`packages/core/src/agency/outputs.py`](../packages/core/src/agency/outputs.py) — `TypePolicy`, `Lifecycle`, `RUNAWAY`, `errors()` |
| brána | [`ingest.py`](../packages/core/src/agency/ingest.py) — devět důvodů v `GATE_REASONS`, strop až jako poslední |
| kotvení a drift | [`anchor.py`](../packages/core/src/agency/anchor.py) — čtyři vrstvy beze změny, `of()` a `places()` čtou oba tvary |
| fold událostí | [`runs.py`](../packages/core/src/agency/runs.py) — `read_events()`, `verdicts()`, `decisions()` |
| místo outputu | [`dedup.py`](../packages/core/src/agency/dedup.py) — `subject_key()`: subject → symbol → soubor → nic |
| referenční packy | `packs/*/` — sedm packů, z toho dva (`ceo`, `po`) deklarují vlastní typy |
| živé packy | `kvesteros-platform/.claude/skills/agency-ceo`, `main-panel/.claude/skills/agency-{po,legal,qa,review-graph,author}` — dorovnané 8. 9. 2026 |
| kontrakt | [`schemas/finding.v1.json`](../schemas/finding.v1.json), [`schemas/run.v1.json`](../schemas/run.v1.json) |

Plán sám — se všemi retrospektivami po krocích — zůstává v [`plans/outputs.md`](plans/outputs.md). Tenhle dokument je jeho přejímka, ne náhrada: kdo bude řešit *proč* je něco tak, jak to je, najde odpověď tam.
