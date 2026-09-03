# VeriFlow Agency — popis produktu

**Verze:** v0 · 2026-08-30
**Pro koho je tenhle dokument:** pro mě a případné teammates. Popisuje *co to je a proč*, ne *jak je to postavené*. Technická část je v [`implementation-plan-v0.md`](implementation-plan-v0.md).

---

## Co to je

**Agentura specialistů pro tvoje repozitáře.**

Otevřeš projekt, najmeš do něj specialisty — recenzenta kódu, QA, product ownera — a oni na něm pracují pod tvým vlastním přihlášením ke Claude Code nebo Codexu. Výsledkem nejsou konverzace, ale **doložené nálezy a rozhodnutí, která zůstanou.**

Běží u tebe na počítači nebo na tvém serveru. Není to služba, není to předplatné, nic se nikam neposílá.

---

## Problém, který řeší

Mám několik specializovaných agentů a fungují dobře. QA agent umí prozkoumat aplikaci jako čtyři různí uživatelé a najít reálné chyby. Recenzent kódu umí projít pull request a doložit, proč je něco rozbité. Za dva dny spolu našli **51 nálezů**, z toho jeden P0 blocker a jednu bezpečnostní díru.

Jenže:

**1. Každý agent umí jen jeden projekt.** QA agent je napsaný pro NaLekci — pro její adresu, její uživatelské role, její repozitář. Nasadit ho na druhý projekt znamená udělat kopii a přepsat ji. Mám tři projekty a další přibývají.

**2. Musím u toho sedět.** Agent běží v terminálu. Zavřu okno, běh je pryč. Nikde nezůstane, co se dělo.

**3. Nálezy přepisuju ručně.** Recenzent najde problém a napíše ho jako komentář k pull requestu. Aby se z toho stala evidovaná položka, musím to přenést rukou. Z 36 nálezů recenzenta jsem takhle přepsal **35**.

**4. Nálezy se hromadí a nikdo o nich nerozhodne.** V evidenci leží **47 položek** ve stavu „zaznamenáno" a čeká. Agenti umí najít víc, než stíhám roztřídit.

**5. Každý nový nápad = nový repozitář.** Protože není kam ho dát.

Není to problém kvality agentů. Ta je prokazatelně dobrá — člověk ani jednou nesnížil závažnost, kterou agent nálezu přiřadil, a agent sám odhalil a opravil jeden svůj vlastní chybný závěr. **Je to problém obalu.**

---

## Pro koho

- **Já** — vývojář na několika projektech současně, s předplatným Claude Code / Codexu.
- **Teammates** — kdokoli, kdo si to nainstaluje na svůj stroj nebo VPS a připojí své vlastní přihlášení.

Není to pro netechnické uživatele a není to produkt na prodej. Je to open source nástroj, který má být použitelný i pro někoho jiného než pro autora.

---

## Jak to vypadá v praxi

### Nový projekt

```
agency init
```

Nástroj se rozhlédne po repozitáři: zjistí, kde je hostovaný, jaký má jazyk, jestli má testy, jaká má pravidla. Zeptá se na to, co si nemůže domyslet. Řekne, co udělal.

```
agency add reviewer
```

Nainstaluje specialistu do projektu a nastaví ho podle toho, co našel při `init`.

```
agency doctor
```

Ověří, že všechno potřebné existuje a funguje. Když ne, řekne **co přesně chybí a co s tím** — ne „selhalo".

**Laťka:** od nuly k prvnímu běhu **do deseti minut, bez čtení dokumentace**.

### Běžný den

```
agency run reviewer --pr 461
```

Recenzent si vezme pull request, postaví si stranou pracovní kopii (tvoje rozdělaná práce se ho netýká), projde změny z pěti různých úhlů, ověří si každý podezřelý nález proti skutečné struktuře kódu, vyhodí nejistá tvrzení a zbytek uloží.

Uvidíš:

> **3 nálezy** · 1 vysoká, 2 střední závažnost
> *„Lekce zdarma se zapnutým zámkem plateb nejde vůbec rezervovat"* — `getAvailabilityCheckout.ts:76`
> Serverová kontrola má tři podmínky, klientská jen dvě. Chybí ta s cenou.
> **3 volající, 0 testů.**
>
> Odloženo jako nejisté: 4 · Už dřív nalezeno: 2

Rozhodneš `agency triage`: co je k opravě, co počká, co je planý poplach. Přijaté nálezy odejdou do GitHubu **až po tvém schválení**.

### Za týden

```
agency status
```

Čtyři projekty, kdo v nich pracoval, co našel, co čeká na rozhodnutí, co je zastaralé.

---

## Základní pojmy

| Pojem | Co to je |
|---|---|
| **Projekt** | Repozitář, na kterém pracuješ. Drží si vlastní stav a vlastní paměť. |
| **Specialista** *(pack)* | Skill v repozitáři projektu, s fakty projektu natvrdo. Recenzent, QA, product owner, právník. Jedna verze na projekt; další projekt dostane kopii. |
| **Běh** | Jedno konkrétní pověření: „prověř tenhle PR", „projdi rezervační flow jako zákazník". Má začátek, konec a záznam. |
| **Nález** | Jedno zjištění s důkazem: kde to je, čím to selže, co to dokládá. Bez důkazu to není nález. |
| **Rozhodnutí** | Co s nálezem — opravit, odložit, zamítnout. Zaznamenané i s důvodem. |
| **Paměť projektu** | Co už specialista o projektu ví. Aby netvrdil podruhé totéž a nezkoumal, co už prozkoumal. |

**Klíčové rozdělení:** *jádro* (běh, záznam, brána, triage, dedup, paměť) patří všem projektům stejně. *Pack* patří jednomu projektu — je to skill s fakty toho projektu natvrdo, ne konfigurace nad obecnou metodou. Sdílený je kontrakt (`pack.json`, `finding.v1`, `run.v1`), ne stav.

---

## Čím se to liší od pouhého spuštění Claude Code

Claude Code umí totéž — jednou. Rozdíl je ve všem, co má trvat.

| Bez Agency | S Agency |
|---|---|
| Konverzace v terminálu | Běh se záznamem |
| Zavřeš okno, výsledek je pryč | Nález zůstane v projektu |
| Agent najde znovu, co už našel minule | Ví, co už našel, a řekne „tohle už známe" |
| Nálezy přepisuješ ručně | Zapíšou se samy, do GitHubu po schválení |
| Každý projekt nastavený jinak | Stejní specialisté, stejný postup, jeden příkaz |
| Nevíš, kolik z toho bylo k něčemu | Vidíš, co se potvrdilo a co byl planý poplach |

Zkráceně: **Claude Code ti dá odpověď. Agency ti dá záznam.**

---

## Co to není

- **Není to editor ani lepší terminál.** Píšeš dál, v čem píšeš.
- **Není to služba.** Žádný účet, žádné předplatné, žádný náš server.
- **Nedrží tvoje přihlášení.** Přihlašuješ se přímo u Anthropicu nebo OpenAI, svým nástrojem. Agency se tvých přístupů nikdy nedotkne.
- **Neběží, když u toho nejsi.** Žádné noční automatizace. Když spouštěč zjistí, že u počítače nesedíš, běh zařadí a počká.
- **Nenahrazuje CI.** Testy, linter a build zůstávají, kde jsou. Agency nálezy, které už chytá CI, naopak zahazuje.
- **Nic neposílá ven bez tebe.** Do GitHubu jde nález až po tvém schválení.

---

## Šest pravidel produktu

1. **Nález bez důkazu není nález.** Musí ukázat kde, čím to selže a co to dokládá. Dohad se zahazuje.
2. **Nic ven bez souhlasu člověka.** Agent připravuje, člověk rozhoduje.
3. **Neopakovat se.** Co už bylo nalezeno, se nehlásí znovu jako nové. Doplní se novým důkazem k původnímu nálezu.
4. **Bez tebe se neběhá.** „Jsem u toho" je vlastnost systému, ne slib.
5. **Jádro patří všem, pack patří projektu.** Sdílený je kontrakt, ne konfigurace.
6. **Vypnutí nesmí nic ztratit.** Když Agency smažeš, projekty i nálezy zůstanou čitelné bez ní.

---

## Specialisté

| Specialista | Co dělá | Stav |
|---|---|---|
| **Recenzent** | Projde pull request, zkříží změny se skutečnou strukturou kódu — kdo co volá, co není otestované — a doloží nálezy. | Funguje, největší producent nálezů |
| **QA** | Prozkoumá běžící aplikaci jako několik různých uživatelů, ověří, co našel, a nezakládá duplicity. | Funguje, zatím na jednom projektu |
| **Architekt** | Odpoví, jak aplikace doopravdy funguje, a hlídá, jak moc se kód od té odpovědi vzdálil. | Engine hotový, nezapojený |
| **Ověřovatel specifikace** | Porovná, co je slíbeno, co je otestováno a co doloženo. | Engine hotový, nezapojený |
| **Product owner** | Roztřídí nálezy, rozhodne priority, drží rozhodnutí. | Nejslabší článek — dnes jen dokumenty |
| **Vedení** | Deterministický týdenní přehled: co přibylo, co se vyřešilo, co stárne. | Plánováno jako přehled, ne jako agent |

Specialisté se instalují podle potřeby. Projekt bez testovacího prostředí prostě QA mít nebude.

---

## Jak poznám, že to funguje

Ne „máme hezkou appku", ale:

1. **Vím, co se rozbilo, a nemusím to hledat** — nálezy jsou v editoru u toho řádku kódu, kterého se týkají.
2. **Nález mi neuteče.** Dnes 35 ze 36 přepisuju rukou. Cíl: nula.
3. **Nový projekt je hotový za deset minut.** Zkopíruješ čtyři adresáře z `packs/`, přepíšeš Project facts a skripty, pustíš `agency doctor`. Ne za odpoledne kopírování.
4. **Fronta se hýbe.** Dnes 47 nerozhodnutých položek. Cíl: pod 15.
5. **Vím, kolik z toho bylo k něčemu.** Dnes to spočítat nejde — evidence nemá stav pro zamítnutý nález. To je první věc k opravě.

**Bod, kdy je v0 hotová:**

> Do projektu, který s agenty nikdy nic neměl, nainstaluju jedním příkazem recenzenta, proběhne pod mým přihlášením, nálezy skončí ve stejné evidenci jako nálezy z ostatních projektů — a nemusel jsem sáhnout do jediného souboru.

---

## Kam to půjde dál

**Teď** — jeden nástroj z příkazové řádky **a rozšíření do VS Code**, čtyři projekty, dva specialisté, evidence nálezů, ruční schvalování.

**Potom** — sdílení stavu s teammates (rozhodnutí a nálezy, nikdy přístupy), další specialisté podle toho, co bude reálně chybět.

**Vědomě zatím ne** — samostatná desktopová aplikace (zrušená, ne odložená), noční automatizace, víceuživatelský server. Každá z těch věcí má svůj spouštěč a žádný zatím nenastal.

**Není a nebude** — obchod se specialisty ani registr packů. Specialisté se kopírují mezi projekty a přepisují ručně; to je rozhodnutí, ne mezikrok.

---

## Jedna věta

> Specialisté, které si najmeš do repozitáře, pracují na tvém přihlášení, a to, co najdou, ti zůstane — s důkazem, bez duplicit a bez toho, abys u toho seděl.
