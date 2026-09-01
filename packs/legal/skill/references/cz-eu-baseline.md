# CZ/EU baseline — what the provisions actually say

Wordings below were read from the primary sources on **1 September 2026** (e-Sbírka open data and the EU Publications Office; see `sources.md`). Czech quotes are verbatim; the commentary around them is not law.

**This file is a starting point, not the citation.** Re-fetch the provision you are about to rely on and quote the version in force on the day of the run. When `lawSources.offline` is true you may work from here — and then every finding says so.

Everything is written from one angle: *what does this require, and what does it not require*. The second half is the part general models get wrong.

---

## A. Terms and conditions, and changing them

### A.1 Unilateral change of terms — § 1752 Civil Code (89/2012)

> **(1)** Uzavírá-li strana v běžném obchodním styku s větším počtem osob smlouvy zavazující dlouhodobě k opětovným plněním stejného druhu s odkazem na obchodní podmínky a vyplývá-li z povahy závazku již při jednání o uzavření smlouvy rozumná potřeba jejich pozdější změny, lze si ujednat, že strana může obchodní podmínky v přiměřeném rozsahu změnit. Ujednání je platné, pokud bylo předem alespoň ujednáno, jak se změna druhé straně oznámí a pokud se této straně založí právo změny odmítnout a závazek z tohoto důvodu vypovědět ve výpovědní době dostatečné k obstarání obdobných plnění od jiného dodavatele; nepřihlíží se však k ujednání, které s takovou výpovědí spojuje zvláštní povinnost zatěžující vypovídající stranu.
>
> **(2)** Nebyl-li ujednán rozsah změn obchodních podmínek, nepřihlíží se ke změnám vyvolaným takovou změnou okolností, kterou již při uzavření smlouvy strana odkazující na obchodní podmínky musela předpokládat, ani ke změnám vyvolaným změnou jejích osobních nebo majetkových poměrů.

`https://www.e-sbirka.cz/eli/cz/sb/2012/89/2026-01-01#par_1752`

What follows:

- It applies **only** to long-term obligations to repeated performance of the same type. A one-off order is not in scope at all — new terms simply govern new orders.
- The change clause must exist **before** the change and must already say **how** the change is announced and that the other side may **reject it and terminate**.
- The notice period is defined by a standard, not a number: long enough to obtain comparable performance elsewhere. **There is no statutory 30 days, and no statutory 15 days, in § 1752.**
- A change outside the agreed scope, or one driven by circumstances the drafting party had to foresee, is disregarded — writing "účinné dnes" does not fix that.

### A.2 Changing a digital service to the consumer — § 2389q Civil Code

> **(1)** Má-li být digitální obsah poskytován po určitou dobu a nejedná-li se o změnu nezbytnou pro zachování digitálního obsahu bez vad, poskytovatel může digitální obsah změnit, **a)** je-li to ujednáno ve smlouvě spolu se spravedlivým důvodem pro takovou změnu, **b)** nevzniknou-li uživateli změnou dodatečné náklady a **c)** oznámí-li uživateli změnu jasným a srozumitelným způsobem.
>
> **(2)** Zhoršuje-li změna podle odstavce 1 přístup uživatele k digitálnímu obsahu nebo jeho užívání nikoli jen nevýznamně, poskytovatel dále upozorní uživatele **v přiměřené době před provedením změny v textové podobě** na povahu změny, čas jejího provedení a na právo vypovědět závazek podle odstavce 3 nebo na možnost zachovat digitální obsah beze změny podle odstavce 4.
>
> **(3)** Uživatel může závazek bez postihu vypovědět, zhoršuje-li změna jeho přístup k digitálnímu obsahu nebo jeho užívání nikoli jen nevýznamně, a to **do třiceti dnů ode dne, kdy byl o změně vyrozuměn nebo od okamžiku, kdy byl digitální obsah změněn, podle toho, co nastane později**. […]
>
> **(4)** Odstavec 3 se nepoužije, umožní-li poskytovatel uživateli odmítnout změnu a ponechat si digitální obsah bez dodatečných nákladů v původní podobě, aniž by to bylo na úkor jeho poskytování bez vad.

`https://www.e-sbirka.cz/eli/cz/sb/2012/89/2026-01-01#par_2389q`

What follows — this is the single most misquoted provision in this whole area:

- **The thirty days is the consumer's window to terminate, not a notice period.** It runs from notification *or* from the change, whichever is later.
- The advance duty is "v přiměřené době před provedením změny, v textové podobě" — a standard, not a number — and it is triggered only when the change worsens access or use **"nikoli jen nevýznamně"**. A new feature, a redesign, a bug fix, a price list for future orders: not triggered.
- Paragraph 4 is the escape hatch nobody quotes: let the user keep the old version at no extra cost and the termination right does not arise.
- This is about changing **the service**. Changing the *terms document* is § 1752. They are frequently confused, including by the terms themselves.

### A.3 The consumer must be given the terms — § 1827 Civil Code

> **(2)** Uzavírá-li se smlouva za použití elektronických prostředků, poskytne podnikatel spotřebiteli v textové podobě kromě znění smlouvy i znění všeobecných obchodních podmínek.

`https://www.e-sbirka.cz/eli/cz/sb/2012/89/2026-01-01#par_1827`

This is the real duty behind the archive question, and it is a **delivery** duty, not a publication duty: the wording that applied goes to that consumer, in textual form, at the time. What the product needs is therefore a stored version identifier per contract and a copy that can be produced — not a public page listing every historical wording.

### A.4 Business users — Regulation (EU) 2019/1150 (P2B), Article 3

> **2.** Poskytovatelé online zprostředkovatelských služeb oznámí **na trvalém nosiči** dotčeným podnikatelským uživatelům jakékoli navržené změny svých podmínek. Navržené změny nelze provést dříve, než uplyne lhůta pro oznámení, která je rozumná a přiměřená povaze a rozsahu zamýšlených změn […]. Tato lhůta pro oznámení činí **nejméně 15 dní** ode dne, kdy poskytovatel […] navržené změny oznámí. Poskytovatelé […] lhůtu pro oznámení prodlouží, je-li to nezbytné pro to, aby měli podnikatelští uživatelé dostatek času pro technické či obchodní úpravy […].
>
> **3.** Podmínky nebo jejich jednotlivá ustanovení, které nesplňují požadavky odstavce 1, jakož i **změny podmínek, které poskytovatel […] provedl v rozporu s odstavcem 2, jsou neplatné**.
>
> **4.** Lhůta […] se nepoužije, pokud poskytovatel musí a) na základě právní nebo regulační povinnosti změnit své podmínky […]; b) výjimečně změnit své podmínky s cílem čelit neočekávanému a bezprostředně hrozícímu nebezpečí […] před podvodem, malwarem, spamem, porušením zabezpečení údajů nebo jinými kybernetickými riziky.

`https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32019R1150`

What follows:

- **This is a hard number and the sanction is severity, not a fine: a change made in breach is void.** If the platform side of the product has no 15-day path, that is a blocker-grade finding.
- Durable medium means e-mail or an in-product message the user can keep — not a changelog page.
- The business user may waive the period; continuing to offer new goods or services during it counts as waiver, **except** where the reasonable period exceeds 15 days because significant technical adaptation is needed.
- Article 3(1) also requires plain language, availability at every stage including pre-contractual, stated grounds for suspension/termination/restriction, and information on additional distribution channels and on effects on the business user's IP.
- Applies by virtue of the *relationship*, not the label. If professionals offer to consumers through you and you intermediate the direct transaction, you are in scope regardless of size — P2B has **no** micro/small exemption for Article 3. (Articles 11 and 12 — internal complaint handling and mediators — do exempt small enterprises.)

### A.5 Every intermediary — Regulation (EU) 2022/2065 (DSA), Article 14

> **2.** Poskytovatelé zprostředkovatelských služeb informují příjemce služby o **každé významné změně** smluvních podmínek.

`https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32022R2065`

Article 14(1) additionally requires the terms to describe restrictions on use, content-moderation policies and tools including algorithmic decision-making and human review, and the rules of the internal complaint-handling system, in a machine-readable, accessible format. Article 14 has **no** size exemption — it binds every intermediary service. What is exempt is elsewhere (see E.2).

---

## B. The archive question

There is **no general obligation to publish an archive of past terms** — not in the Civil Code, not in P2B, not in the DSA. What exists is narrower and harder:

1. **§ 1827(2)** — give the consumer the wording, in textual form, when contracting electronically.
2. **Burden of proof** — you assert the contract had a given content, so you must be able to show which wording the user was shown and accepted, and when.
3. **DAC7 record keeping** — Annex V Section IV B: records of the steps taken and information relied on for due diligence and reporting must remain available (see E.3).

The product-level answer is therefore a **version identifier stored on the contract** plus a retrievable copy of that version — for example `terms_version` on the booking, and an acceptance/notification table with `accepted_at` where consent was actually taken and `notified_at` where it was not. A public `/podminky/archiv` page is cheap, honest and good for trust. It is **not** a legal requirement, and a finding must not claim it is.

---

## C. Consumer duties that do exist

### C.1 ADR information — § 14 Consumer Protection Act (634/1992)

> **(1)** Prodávající informuje spotřebitele jasným, srozumitelným a snadno dostupným způsobem o subjektu mimosoudního řešení spotřebitelských sporů, který je pro daný typ […] výrobku nebo služby věcně příslušný. Informace musí zahrnovat též internetovou adresu tohoto subjektu. Jestliže prodávající provozuje internetové stránky, uvede tyto informace i na těchto internetových stránkách. **Pokud smlouva uzavřená mezi prodávajícím a spotřebitelem odkazuje na obchodní podmínky, uvede informace podle věty první a druhé rovněž v těchto obchodních podmínkách.**
>
> **(2)** V případě sporu […], který se nepodařilo mezi stranami urovnat přímo, poskytne prodávající spotřebiteli informace uvedené v odstavci 1 v listinné podobě nebo na jiném trvalém nosiči dat.

`https://www.e-sbirka.cz/eli/cz/sb/1992/634/2025-08-20#par_14`

Checkable in one grep: the terms must name the ADR body and its web address. In the Czech Republic that is normally the Czech Trade Inspection Authority (`coi.gov.cz`).

### C.2 The ODR platform is gone — Regulation (EU) 2024/3228

> Článek 1 — Nařízení (EU) č. 524/2013 se zrušuje s účinkem ode dne **20. července 2025**. […] Podávání stížností do platformy se zastavuje dne 20. března 2025.

`https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32024R3228`

A link to `ec.europa.eu/consumers/odr` in live terms now points consumers at a dead service — remove it. The § 14 ADR duty above is unaffected and stays.

### C.3 Accessibility — Directive (EU) 2019/882, act 424/2023

> **5.** Mikropodniky poskytující služby jsou osvobozeny od povinnosti splňovat požadavky na přístupnost uvedené v odstavci 3 tohoto článku a jakékoli povinnosti související s plněním těchto požadavků.

`https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32019L0882`, transposed by act 424/2023 (`/eli/cz/sb/2023/424`), in application since **28 June 2025** for services including e-commerce.

Micro means fewer than 10 staff **and** ≤ EUR 2M — the same definition the DSA uses. Above that, an e-shop or booking flow is in scope and the accessibility statement is part of the legal surface, not a nice-to-have.

---

## D. Personal data, cookies, commercial messages

### D.1 Consent is one basis among six

Contract performance is Article 6(1)(b) GDPR, legal obligation is 6(1)(c), legitimate interest is 6(1)(f). Asking for consent where 6(1)(b) applies is not "extra safe" — consent is withdrawable, so it makes the processing you actually need to run stand on the weakest available footing. Flag it under `over-compliance`.

### D.2 Changing a privacy notice does not require fresh consent

The transparency guidelines (WP29 WP260 rev.01, endorsed by the EDPB) say that changes must be **communicated**, and that material changes — a new purpose, a new controller identity, a change in how rights are exercised — must be **actively** brought to data subjects' attention rather than quietly published. Typos and rewording are not material. Fresh consent is needed only where consent is the basis and the change goes beyond what was consented to; a new purpose triggers Article 13(3) information before the further processing, not a consent wall on the whole product.

### D.3 Cookies — § 89(3) act 127/2005, verbatim

> **(3)** Každý, kdo hodlá používat nebo používá sítě elektronických komunikací k ukládání údajů nebo k získávání přístupu k údajům uloženým v koncových zařízeních účastníků nebo uživatelů, **získá od těchto účastníků nebo uživatelů předem prokazatelný souhlas** s rozsahem a účelem jejich zpracování. Tato povinnost neplatí pro technické ukládání nebo přístup výhradně pro potřeby přenosu zprávy prostřednictvím sítě elektronických komunikací nebo je-li to nezbytné pro potřeby poskytování služby informační společnosti, která je výslovně vyžádána účastníkem nebo uživatelem.

`https://www.e-sbirka.cz/eli/cz/sb/2005/127/2026-01-01#par_89`

Opt-in since 1 January 2022, provable, in advance. Only strictly necessary storage is exempt — **analytics is not**, and legitimate interest is not available here because this is not GDPR Article 6, it is the ePrivacy rule on the device. Two things to check in code rather than in the banner: that nothing non-essential loads before the click, and that refusing is as easy as accepting.

### D.4 Marketing e-mail — § 7 act 480/2004, verbatim

> **(2)** Podrobnosti elektronického kontaktu lze za účelem šíření obchodních sdělení elektronickými prostředky využít pouze ve vztahu k uživatelům, kteří k tomu dali předchozí souhlas.
>
> **(3)** Nehledě na odstavec 2, pokud fyzická nebo právnická osoba získá **od svého zákazníka** podrobnosti jeho elektronického kontaktu pro elektronickou poštu **v souvislosti s prodejem výrobku nebo služby** […], může […] využít tyto podrobnosti […] pro potřeby šíření obchodních sdělení týkajících se **jejích vlastních obdobných výrobků nebo služeb** za předpokladu, že zákazník má jasnou a zřetelnou možnost jednoduchým způsobem, zdarma nebo na účet této osoby **odmítnout** souhlas s takovýmto využitím svého elektronického kontaktu **i při zasílání každé jednotlivé zprávy**, pokud původně toto využití neodmítl.

`https://www.e-sbirka.cz/eli/cz/sb/2004/480/2023-03-23#par_7`

So the existing-customer exception is real and does not need a checkbox — it needs an opt-out at collection, an opt-out in every message, and staying inside "own similar products". Transactional messages are not commercial messages at all.

---

## E. Platform side

### E.1 P2B — see A.4. Fifteen days, durable medium, breach means void.

### E.2 DSA — what a small platform is actually exempt from

> **Článek 19 — Vynětí mikropodniků a malých podniků.** 1. Tento oddíl se s výjimkou čl. 24 odst. 3 nevztahuje na poskytovatele online platforem, kteří jsou mikropodniky nebo malými podniky ve smyslu doporučení 2003/361/ES. […] a to po dobu dvanácti měsíců po ztrátě tohoto postavení […], pokud nejsou velmi velkými online platformami podle článku 33.
>
> **Článek 29 — Vynětí mikropodniků a malých podniků.** 1. Tento oddíl se nevztahuje na ty poskytovatele online platforem umožňujících spotřebitelům uzavírat s obchodníky smlouvy na dálku, kteří jsou mikropodniky nebo malými podniky […].

So a micro or small marketplace is out of the online-platform obligations of Section 3 (except Article 24(3)) and out of the marketplace-specific Section 4 — trader traceability, compliance by design, the right-to-inform duty. It is **not** out of Chapter III Section 1: points of contact, legal representative where relevant, **Article 14 terms and conditions including 14(2) notice of significant changes**, and the notice-and-action machinery of Article 16. The twelve-month grace after outgrowing the status is worth knowing before a funding round changes the answer. The Czech Digital Services Coordinator is ČTÚ.

### E.3 DAC7 — Directive (EU) 2021/514, transposed in act 164/2013

Reporting is annual to the Specialised Tax Office, **by 31 January** for the preceding calendar year, and the platform must **also hand the reported seller their own figures**:

> **Oddíl III A bod 5.** Oznamující provozovatel platformy rovněž poskytne informace stanovené v pododdíle B bodě 2 a 3 **oznamovanému prodejci**, k němuž se vztahují, **nejpozději do 31. ledna** roku následujícího po kalendářním roce, v němž je prodejce identifikován jako oznamovaný prodejce.

That is a product feature — an annual statement per seller — and it is the DAC7 duty most often missing from a backlog.

Enforcement has a hard product consequence too:

> **Oddíl IV A bod 2.** Pokud prodejce neposkytne informace požadované podle oddílu II po **dvou upomínkách** následujících po prvotní žádosti […], ne však před uplynutím **60 dní**, oznamující provozovatel platformy **uzavře účet prodejce a zabrání mu v opětovné registraci** na platformě **nebo zadrží platbu** protiplnění prodejci, dokud prodejce neposkytne požadované informace.

Who is out of scope — the de-minimis everyone half-remembers:

> **Oddíl I B bod 4.** „Vyloučeným prodejcem" se rozumí kterýkoli prodejce, a) který je vládním subjektem; b) […] jehož akcie jsou pravidelně obchodovány […]; c) […] jemuž provozovatel platformy usnadnil více než 2 000 příslušných činností prostřednictvím pronájmu nemovitého majetku ve vztahu k určité nabízené nemovitosti […]; nebo **d) jemuž provozovatel platformy usnadnil méně než 30 příslušných činností spočívajících v prodeji zboží, přičemž celková zaplacená nebo připsaná částka protiplnění během oznamovacího období nepřesáhla 2 000 EUR.**

**Read (d) carefully: it is limited to the sale of goods.** A platform intermediating personal services — lessons, cleaning, repairs, consulting — has no de-minimis at all: every active seller who is not otherwise excluded is reportable from the first transaction. Relevant activities are the rental of immovable property, personal services, sale of goods and rental of any mode of transport.

Data to collect per seller (Annex V Section II B): natural person — name, primary address, all TINs (or place of birth if none), VAT number if available, date of birth; entity — official name, primary address, TINs, VAT number if available, business registration number, and any permanent establishment in the Union. Non-EU operators register in one Member State; registration can be cancelled after two reminders, which effectively ends EU operation.

`https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32021L0514` · Czech guidance and the filing channel: Finanční správa, DAC7 section.

---

## F. Where this baseline stops

Not covered here, and worth a named question to counsel rather than a guessed finding: VAT and OSS, payment services and e-money, AML for platforms handling funds, sector licensing, employment vs. contractor classification of sellers, AI Act duties, NIS2, and any market outside the Czech Republic. If a run needs one of these, say so in the finding and stop — a confident answer from this baseline would be worth less than the question.
