# Baseline: kvalita agentních nálezů

**Datum měření:** 2026-08-30
**Zdroj dat:** GitHub Project `Chci-na-lekci/Product / NaLekci` #1 (71 položek), `main-panel` issues + git log, `nalekci-qa-agent/memory/inbox/`, `artifacts/sessions/`, `references/known-regressions.md`
**Účel:** změřit číslo, o kterém oponentní review z 30. 8. tvrdilo, že má rozhodnout o celém projektu.

> **Poznámka k odkazům.** Dokument `second-opinion-veriflow-agency.md`, na který se tento text původně odkazoval, byl 31. 8. rozpuštěn do [`implementation-plan-v0.md`](implementation-plan-v0.md) a smazán. Odkazy níže míří na jeho nástupce; kde se mluví o „původním review", jde o ten smazaný dokument a §8 zůstává jeho platným shrnutím.

---

## 0. Hlavní závěr — a proč je jiný, než jsem čekal

**Precision se spočítat NEDÁ. Ale ne proto, že by chyběla data — chybí stav.**

*(Stav k 30. 8. Instrumentace popsaná v §7.1 byla mezitím 31. 8. provedena — viz tam.)*

Workflow Projectu má stavy `New`, `Observed`, `Worth exploring`, `Converted to issue`, `Archived`. **Nemá stav pro zamítnutý nález.** `Archived` (definovaný jako „nepokračovat nebo historická evidence") má **0 položek**. Za celou dobu tedy nebyl explicitně odmítnut ani jeden z 51 agentních nálezů.

Jmenovatel pro „kolik jich bylo špatně" v systému neexistuje.

Falešné pozitivy přitom **existují a jsou zachycené** — jen v markdownu mimo Project (§4). Signál máš, není měřitelný.

**Druhý závěr, který mění tón mého původního review:** obava z „bambiliónu nálezů" **daty nesedí**. Poslední strukturovaný běh se 4 personami vyprodukoval **3 nové nálezy a 12 shod s existujícími**. Dedup potlačuje 80 % objemu. Problém není nadprodukce, ale opačný: agent je konzervativní a **úzké hrdlo je lidský triage, ne generování**.

**Rozhodnutí:** kill criteria (dnes [`implementation-plan-v0.md`](implementation-plan-v0.md) §6) **nejsou splněna** a data ukazují nadprůměrně kvalitní výstup. Ale před jakoukoli automatizací potřebuješ jednu drobnou instrumentaci (§7), jinak zůstaneš měřicky slepý napořád.

---

## 1. Složení korpusu

71 položek v Projectu, z toho **72 % vyrobili agenti**:

| Zdroj | n | % | Poznámka |
|---|---:|---:|---|
| **PR-review-agent** (`pr-review-graph`, retrospektivní audity PR) | 36 | 51 % | tvůj review-graph skill — největší producent |
| **QA-agent** (staging bughunt) | 15 | 21 % | |
| Člověk (roadmap #105, WhatsApp, screenshoty) | 20 | 28 % | |
| **Celkem agenti** | **51** | **72 %** | |

> **To je nález sám o sobě.** Původní review i tvůj návrh mluví hlavně o QA agentovi. Ve skutečnosti je **hlavním zdrojem nálezů review-graph skill nad PR** — 2,4× víc než QA. Roadmapa, která začíná QA vertical slice, optimalizuje menší proud.

### Stáří korpusu — kritický kontext

| Datum vytvoření | n |
|---|---:|
| 2026-08-26 | 4 |
| 2026-08-27 | 1 |
| 2026-08-28 | 30 |
| 2026-08-29 | 36 |

**66 z 71 položek (93 %) vzniklo za poslední dva dny.** A `main-panel` má commit `21d88dec — docs(252): Go/No-Go checklist a launch runbook pro 1. 9. 2026`.

**Jsi dva dny před ostrým launchem.** To vysvětluje burst 28.–29. 8. a zároveň to znamená, že metrika „kolik nálezů vedlo k opravě" má dnes nesmyslný jmenovatel — tým je v předlaunchovém režimu, kde se opravuje jen P0.

---

## 2. Co se s nálezy stalo

| Stav | Celkem | Člověk | PR-review | QA |
|---|---:|---:|---:|---:|
| `New` | 16 | 16 | 0 | 0 |
| `Observed` | 47 | 4 | 31 | 12 |
| `Worth exploring` | 2 | 0 | 1 | 1 |
| `Converted to issue` | 6 | 0 | 4 | 2 |
| `Archived` (= zamítnuto) | **0** | 0 | 0 | 0 |

**Míra promoce na repo issue:**
- PR-review-agent: 4/36 = **11 %**
- QA-agent: 2/15 = **13 %**
- Agenti celkem: 6/51 = **12 %**
- Člověk: 0/20 = **0 %**

> **Pozor na interpretaci.** README Projectu explicitně říká, že `Observed` znamená „jednotlivé nebo ověřené pozorování" a že Draft se převádí na issue až *„když je jasný požadovaný výsledek, jeho evidence, proč teď, přibližný scope a odpovědnost"*.
>
> **`Observed` tedy neznamená „zamítnuto". Znamená „platné, ale zatím nezescopované."** Těch 12 % NENÍ precision. Je to rychlost triage, měřená dva dny před launchem.

---

## 3. Šest promovaných nálezů — jediná tvrdá data o kvalitě

| Issue | Zdroj | Severity od agenta | Priorita od člověka | Stav | Vytvořeno |
|---|---|---|---|---|---|
| [#430](https://github.com/Chci-na-lekci/main-panel/issues/430) Online platby: karta v nastavení + úhrada při rezervaci | PR-review | High | **P1** | **CLOSED** (29. 8., PR #461) | 27. 8. |
| [#454](https://github.com/Chci-na-lekci/main-panel/issues/454) Storno: po zrušení A se tiše vybere a zruší B | **QA** | Blocker | **P0** | OPEN | 29. 8. |
| [#455](https://github.com/Chci-na-lekci/main-panel/issues/455) Přesun rezervace: kontrola shody aktivity je no-op | PR-review | High | **P1** | OPEN | 29. 8. |
| [#456](https://github.com/Chci-na-lekci/main-panel/issues/456) Soft-delete instruktora nekaskáduje — checkout dál funguje | PR-review | High | **P1** | OPEN | 29. 8. |
| [#457](https://github.com/Chci-na-lekci/main-panel/issues/457) Místo: formulář ignoruje adresu, uloží výchozí pin | **QA** | High | **P1** | OPEN | 29. 8. |
| [#458](https://github.com/Chci-na-lekci/main-panel/issues/458) Přesun může nabídnout termín archivované aktivity | PR-review | High | **P1** | OPEN | 29. 8. |

Tři čísla, která z toho plynou:

1. **Shoda severity: 6/6.** Každý `Blocker` se stal `P0`, každý `High` se stal `P1`. Člověk **ani jednou** nesnížil hodnocení agenta. *(Výběrové zkreslení uznávám — promovaly se právě ty vážné. Ale znamená to, že když se agentní High prozkoumá, obstojí.)*
2. **Latence opravy: ~2 dny.** Jediný nález starý dost na to, aby šel měřit (#430, 27. 8.), byl 29. 8. opraven a uzavřen přes PR #461 + commit `b084406f`.
3. **5 ze 6 issues je mladších než 24 hodin** a v repu na ně zatím není žádný commit. To není nízká fix-rate. To je **chybějící čas**.

---

## 4. Falešné pozitivy: existují, jsou zachycené, ale ne v Projectu

Tady je odpověď na otázku „kolik toho bylo špatně". Není v Projectu, je v markdownu.

**`references/known-regressions.md` → sekce „Must be reverified in clean isolation"** (2 položky):

> „Google Calendar connection returning `401 no_authorization`: the original trainer-b run **shared cookies via a page in the same browser context, so the evidence is contaminated**."

**A tady se stalo to nejzajímavější z celého měření.** Následující běh (`20260829T145539Z`, trainer-b) to znovu ověřil v čisté izolaci a našel **jinou, správnou příčinu**:

> „Google Calendar connect always fails: Supabase manual identity linking is disabled — `404 manual_linking_disabled`, na obou nezávislých implementacích #428, 100% reprodukovatelné."

**Systém sám zachytil vlastní kontaminovaný nález, označil ho ke znovuověření, znovu ho ověřil a nahradil správnou diagnózou.** To je uzavřená korekční smyčka bez lidského zásahu. Ta je cennější než jakákoli precision hodnota.

**Další zachycené korekce ze stejného běhu:**
- **Částečná falzifikace:** u #348 se dřív zaznamenaná HTTP 500 „did not reproduce this session on either viewport — worth re-checking before treating that half as still-open." Agent aktivně zpochybnil vlastní starší nález.
- **Zúžení diagnózy:** u #454 (P0) trainer-a vyčerpávajícím adversariálním replayem **vyloučil instruktorskou konzoli** jako zasaženou plochu. Diagnóza je nově zúžená na customer self-cancel path. To je ušetřený debugging čas, který se do žádné metriky nálezů nepromítne.
- **3 „uncertain observations"**, které agent vědomě **nezaložil** jako nálezy, protože je z prohlížeče nemohl ověřit.

---

## 5. Trychtýř jednoho běhu — jediný běh s plnou telemetrií

Run `20260829T145539Z-broad-exploratory-pass`, 4 persony (trainer-a/b, customer-a/b):

```
  4 persony
  │
  ├─ 3   NOVÉ nálezy založeny                          ← 20 % výstupu
  │      · Instructor customer-detail API vrací jméno+e-mail
  │        libovolného registrovaného uživatele        SECURITY / High
  │      · Google Calendar connect vždy selže          BUG / High
  │      · Bulk occurrence self-overlap                PRODUCT_GAP / Medium
  │
  ├─ 12  SHOD s existujícími nálezy                    ← 80 % výstupu
  │      každý rozšířen o novou datovanou evidenci
  │      (žádný duplikát nezaložen)
  │
  ├─ 3   nejistá pozorování — vědomě NEzaložena
  ├─ 1   starší nález částečně falzifikován (#348)
  ├─ 1   diagnóza P0 zúžena (#454)
  ├─ 1   kontaminovaný nález opraven (Google Calendar)
  │
  └─ rozsáhlá NEGATIVNÍ evidence
         cross-tenant IDOR sondy (booking ID 46/611/729/737) → čisté 404
         instructor events id 1–20, move-targets id 1–750    → čisté 404
         boundary validace (kapacita, cena, data)            → server-side OK
         double-submit rezervace                             → 409, žádný duplikát
         guest-cancellation disclosure vs. spec BOOKING-CANCEL-GUEST-001 → shoda CS i EN
```

**Poměr nové/dotčené = 3/15 = 20 %.** Dedup vrstva potlačuje 80 % objemu.

---

## 6. Vyhodnocení proti kill criteria

Kritéria dnes žijí v [`implementation-plan-v0.md`](implementation-plan-v0.md) §6, kam je tahle tabulka zpětně odkazuje.

| Kritérium | Verdikt | Data |
|---|---|---|
| Precision < 25 % → zastavit | **NELZE VYHODNOTIT** | od 31. 8. měřitelné **dopředu** (§7.1), zpětně ale není co — v Projectu není potvrzený falešný pozitiv (§7.2) |
| — proxy: shoda severity | **PROŠLO** | 6/6, žádné snížení člověkem |
| — proxy: míra duplicit | **PROŠLO výrazně** | 80 % shod, 0 založených duplikátů |
| — proxy: sebekorekce | **PROŠLO** | 1 kontaminovaný nález opraven, 1 falzifikován, 3 nejisté nezaloženy |
| Cena za nález > cena člověka | **NEMĚŘENO** | žádný běh nezaznamenává cost — viz §7 |
| Jediný uživatel po 3 měsících | neaplikovatelné | projekt je starý dny |
| Třetí provider adapter před třetím packem | **PROŠLO** | zatím 2 providery, 2 packy |

**Souhrn: nic neukazuje na zastavení. Ukazuje to na jednu chybějící instrumentaci.**

---

## 7. Co udělat — čtyři drobnosti, ne projekt

### 7.1 Přidat do Projectu stav pro zamítnutí — ✅ **hotovo 31. 8.**

Do pole `Stav` přidána volba `Rejected` (červená, id `513adc60`) a založeno nové pole `Reason` — **single-select, ne textové**, s hodnotami `not-reproducible` · `by-design` · `wrong-diagnosis` · `duplicate-missed` · `out-of-scope`.

Single-select proto, že se z něj dá počítat; volný text by dal stejnou práci a žádné číslo. Je to týchž pět hodnot jako enum v [`implementation-plan-v0.md`](implementation-plan-v0.md) kroku 3, takže export z Agency nepotřebuje mapování.

```
Stav    PVTSSF_lADOEBAhWs4BhkDWzhgfVmw   + Rejected (513adc60)
Reason  PVTSSF_lADOEBAhWs4BhkDWzhg4xJY   (nové)
projekt PVT_kwDOEBAhWs4BhkDW
```

> **Pozor při dalších zásazích do voleb.** `updateProjectV2Field` nahrazuje **celý** seznam voleb single-select pole. Existující volby se musí poslat zpátky **i s jejich `id`** (vstup `ProjectV2SingleSelectFieldOptionInput` ho přijímá jako volitelné) — jinak vzniknou nové volby a přiřazení na položkách zaniknou. Ověřeno: po zásahu si všech pět původních voleb nechalo svoje id a hodnota `Stav` se nezměnila ani na jedné ze 71 položek.

### 7.2 Zpětně doplnit známé falešné pozitivy — ❌ **neprovedeno, a je to správně**

**Původní předpis byl chybný.** Zněl: přenést dvě položky z `known-regressions.md` § „Must be reverified in clean isolation" plus poznámku o #348 jako `Rejected / wrong-diagnosis`. Při pokusu o provedení 31. 8. se ukázaly tři důvody, proč to nejde:

1. **Dva ze tří kandidátů v Projectu vůbec nejsou** — žijí jen v markdownu. Musely by se založit jen proto, aby se vzápětí zamítly. To není měření, to je výroba jmenovatele.
2. **Ani jeden ze tří není prokázaný falešný pozitiv.** Zdroj u všech tří říká „musí se přeověřit", ne „je špatně". Označit je `Rejected` znamená tvrdit něco, co evidence neříká, a **zkreslit precision směrem dolů** — udělat agenta horším, než je.
3. **Ten třetí kandidát v Projectu je ve skutečnosti opravená verze, ne vadná.** Položka `[QA] Google Calendar connect always fails: Supabase manual identity link` je výstup té korekční smyčky popsané v §4: kontaminovaný byl nález `401 no_authorization`, následující běh ho v čisté izolaci přeověřil a nahradil diagnózou `404 manual_linking_disabled`, **100% reprodukovatelnou na dvou nezávislých implementacích**. V Projectu je ta správná verze. Zamítnout ji by znamenalo zahodit platný nález — a započítat vlastní chybu jako chybu agenta.

> **Tohle je nejdůležitější řádek celé sekce.** Při provádění jsem tu položku podle titulku spároval s kontaminovaným nálezem a na pár minut ji označil `Rejected`. Vráceno, data ověřena proti záloze na nulu odchylek. Ale kdyby se to nechalo, precision by spadla na 86 % **kvůli chybě měřicího, ne měřeného** — a nikdo by to už nerozpletl.

**Závěr: v Projectu není žádný potvrzený falešný pozitiv.** Jmenovatel zůstává nula, dokud nezačne skutečná triage. To není selhání kroku 0 — instrumentace z §7.1 stojí, takže **od 31. 8. je precision měřitelná dopředu**, jen ne zpětně.

**Tři pravidla, která z toho plynou pro triage v kroku 4:**

1. Zpětné doplnění smí použít jen nálezy, které už v evidenci jsou. Zakládat položku kvůli jejímu zamítnutí je výroba jmenovatele.
2. Zamítá se jen tam, kde zdroj tvrdí „je to špatně", ne „musí se přeověřit". Rozdíl mezi tím dvojím je celý rozdíl mezi měřením a jeho výrobou.
3. **Nikdy nepárovat nález podle titulku.** Titulek přežije korekci diagnózy — obsah ne. Párovat se musí přes `anchor` a `run-id`, což je přesně to, k čemu je kontrakt v [`implementation-plan-v0.md`](implementation-plan-v0.md) kroku 3.

### 7.3 Zaznamenávat cost per run *(1 hodina)*

Nikde není, co jeden běh stál. Bez toho nelze zodpovědět test z [`implementation-plan-v0.md`](implementation-plan-v0.md) §3.3 („je to výhodné i při plné API ceně?"). Do run recordu: provider, model, tokeny, doba běhu, počet person. **Zařazeno jako součást kroku 3 plánu.**

### 7.4 Přeměřit 15. 9. 2026

Nechat cohort z 28.–29. 8. dozrát ~2 týdny po launchi a spočítat skutečnou fix-rate. **Teprve to je precision.** Dnešní měření je baseline, ne výsledek.

---

## 8. Co to mění v původním review

| Tvrzení v oponentním review z 30. 8. | Verdikt po měření |
|---|---|
| „Precision jde spočítat za hodinu" | **Nepřesné.** Spočítat nejde vůbec — chybí stav pro zamítnutí. Hodina stačila na zjištění *proč*, ne na číslo. |
| „AI generuje bambilion nálezů, hrozí nadprodukce" | **Vyvráceno.** 3 nové nálezy na 4personový běh, 80 % dedup. Úzké hrdlo je triage, ne generování. |
| „Precision pod 25 % → automatizace zhorší situaci" | **Riziko nepotvrzeno.** Všechny dostupné proxy jsou příznivé. |
| „`nalekci-po-agent` je nejslabší článek" | **Potvrzeno a zesíleno.** 47 položek `Observed`, 16 `New`, 0 promoce z lidských zdrojů. Zácpa je přesně tam, kde jsem ji čekal. |
| „QA agent je nejzralejší komponenta" | **Potvrzeno**, ale hlavním producentem nálezů je **review-graph skill nad PR** (36 vs. 15). Roadmapa by měla začít tam, nebo obojím. |
| „Změř precision dřív než napíšeš řádek Agency" | **Reformulováno:** *Přidej stav pro zamítnutí dřív, než napíšeš řádek Agency.* Měření bez něj nebude existovat nikdy. |

---

## 9. Doporučení

**Jdi dál.** Data neodpovídají projektu, který potřebuje ospravedlnit svoji existenci — odpovídají fungujícímu nástroji, kterému chybí měřidlo a odbytiště.

Upravené pořadí oproti původní roadmapě F0–F5 z oponentního review (ta je dnes nahrazená kroky 0–6 v [`implementation-plan-v0.md`](implementation-plan-v0.md) §4):

1. **Teď (45 min):** stav `Rejected` + zpětné doplnění (§7.1, §7.2). Bez toho zůstáváš slepý.
2. **Po 1. 9. (launch):** cost per run (§7.3).
3. **F1 zůstává:** bezobslužný běh + run record — ale **rozšířený i na review-graph skill**, ne jen QA. Je to větší proud.
4. **F4 povýšit:** PO/triage konzument. Zácpa je prokázaná — 47 `Observed` položek čeká na rozhodnutí. To je dnes největší ztráta hodnoty v celém systému, ne chybějící orchestrace.
5. **15. 9.:** přeměřit fix-rate a rozhodnout o zbytku roadmapy.

**Jedna věta, kterou si z toho odnes:** systém, který sám zachytí kontaminovanou evidenci, označí ji ke znovuověření a v dalším běhu ji nahradí správnou diagnózou, nemá problém s kvalitou. Má problém s tím, že o tom nevede záznam, ze kterého by to šlo dokázat.
