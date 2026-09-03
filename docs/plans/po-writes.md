# PO, který svoje rozhodnutí zapíše

**Datum:** 2026-09-02
**Navazuje na:** [`unattended.md`](unattended.md) (Fáze 8 — autorizace ověřená na claudeovi, codexí větev zůstala přiznaně neodjetá), [`teams.md`](teams.md)
**Řeší:** První reálný běh `po@codex` nad ostrým backlogem. Agent za 41 minut prošel 25 otevřených issues a 66 draftů, rozhodl a napsal pět nálezů — a na nástěnce se nehnulo nic. Dva komentáře odešly, sloupce zůstaly, na drafty se zapsat nedalo vůbec a uživatel mezitím odklikával svolení k tomu, aby agent směl zavolat vlastní CLI nástroje.
**Pořadí prací napříč plány:** [`tasks.md`](tasks.md) → Fáze 9

Uživatel to formuloval jako otázku o konceptu: *„vysledky hodil do findings, ale co s nimi mám dělat? PO by se měl starat o tickety."* Odpověď je, že koncept v pořádku je — PO má dva výstupy, rozhodnutí ven a nálezy o frontě — a rozbité je **psaní**. Když agent nemůže zapsat rozhodnutí, zbudou po něm nálezy, a nástroj vypadá jako generátor reportů. Tenhle plán opravuje psaní, ne koncept.

---

## 1. Co se stalo — běh `01M1GZCQ2VV6P31KKHTJVJZNEP`

`po@codex`, `authorized: grant`, exit 0, 11:52:10Z → 12:33:43Z (2493 s). Projekt `Chci-na-lekci/main-panel`, Project #1. Ověřeno v `run.json`, `backlog.jsonl`, `findings.json`, `summary.md` a proti GitHubu — ne z paměti.

| čas (UTC) | co | jak dopadlo | důkaz |
|---|---|---|---|
| 11:52 | start, snapshot fronty | 25 issues + 66 draftů = 91 položek, 5 souborů roadmapy, 193 změněných souborů | `run.json` → `evidence` |
| 12:11:52 | nácvik rozhodnutí na draftu `PVTI_…kBFE` | `would-comment` — dry-run prošel | `backlog.jsonl:1` |
| 12:15:31 | rozhodnutí `now` na #256 | **zapsáno**, komentář na issue | `backlog.jsonl:2` |
| 12:24:57 | rozhodnutí `now` na #343 | **zapsáno** | `backlog.jsonl:3` |
| — | ostrý zápis na drafty | **selhal**: Agency předala `PVTI_…`, GitHub pro tělo draftu chce `DI_…` | `run.json` → `exitReason` |
| — | přesun sloupce u #256 a #343 | **přeskočen**, `writes.labels=false` | `cli.py:2338` |
| — | povýšení P1 draftu (únik jména a e-mailu přes instructor API) | **nemožné**, `writes.promote=false` | `.agency/po.json` |
| 12:33:43 | konec, 5 nálezů, 0 zahozených bránou | dva z pěti nálezů jsou hlášení o rozbité Agency | `findings.json` |
| 12:51:37 | `writes.promote` a `writes.labels` přepnuty ručně na `true` | brána tedy držela — odmítala, dokud se přepínač nepřehodil | mtime `.agency/po.json` |
| 12:52:16–51 | tři drafty povýšeny na #480, #481, #482 | to, co měl udělat běh, udělal člověk o 19 minut později | `backlog.jsonl:4–6`, `gh issue view 480` |

Uživatel to celou dobu viděl jako sérii dotazů na svolení k `agency backlog` a na konci jako sedm nálezů v panelu, se kterými nešlo nic udělat.

**Vedlejší pozorování, které sem nepatří, ale je vidět:** `target` je `workspace` na větvi `fix/453-demand-cta-anchor @ 4ee1c26e`, tedy hlava PR #474. To je vada **D** z [`unattended.md`](unattended.md) a je pořád otevřená. Tentokrát odpověď nezkreslila — zadání bylo o frontě, ne o změně — ale u příštího běhu se zadáním o kódu zkreslí.

---

## 2. Diagnóza — čtyři vady, jedna chybějící podmínka a jedna otevřená otázka

### A. Přesun sloupce visí na přepínači pro štítky

[`backlog.py:52`](../../packages/core/src/agency/backlog.py) mapuje `"status": "labels"`, a [`cli.py:2338`](../../packages/core/src/agency/cli.py) na tom staví:

```python
if not backlog.allowed(cfg, "status")[0]:
    res["status"] = {"action": "skipped", "why": "`writes.labels` is off"}
    res["labels"] = res["status"]
```

Jsou to **dvě různé venkovní akce na jednom vypínači**. Uživatel vypnul `labels` z dobrého důvodu — nechce, aby mu agent přepisoval štítky v repozitáři — a tím mu potichu vzal přesun karty na nástěnce, což je jediný fyzický akt, kterým PO rozhoduje. Zbyl mu komentář, takže se PO chová jako pozorovatel.

Že to opravdu drželo jen na tom, ukázalo 12:51: po přepnutí obou spínačů začalo fungovat obojí — včetně editace štítků, o kterou uživatel nestál a musel ji povolit, aby dostal sloupce.

### B. Poznámka na draft posílá `PVTI_` tam, kde GitHub chce `DI_`

[`backlog.py:546`](../../packages/core/src/agency/backlog.py):

```python
r = proc.gh("project", "item-edit", "--id", ref["item"], "--body", merged, ...)
```

`ref["item"]` je **id položky na nástěnce** (`PVTI_…`). `gh project item-edit --body` je podle nápovědy 2.96.0 *„Body of the draft issue item"* a chce **id obsahu draftu** (`DI_…`). Ta větev tedy nikdy nefungovala.

Ověřeno proti živé nástěnce — `gh project item-list --format json` vrací **obě** id vedle sebe:

```json
{"item":"PVTI_lADOEBAhWs4BhkDWzg4JrLQ", "type":"DraftIssue",
 "contentId":"DI_lADOEBAhWs4BhkDWzgLAJvw", "contentKeys":["body","id","title","type"]}
```

`snapshot()` ([`backlog.py:694`](../../packages/core/src/agency/backlog.py)) i `resolve_ref()` ([`backlog.py:347`](../../packages/core/src/agency/backlog.py)) si nechají jen to první a druhé zahodí.

Podstatná nuance, kvůli které to není jednořádková záměna: **obě id jsou správná, každé na něco jiného.** Editace pole (`set_status`, `--field-id`) chce `PVTI_` plus `--project-id`; editace těla chce `DI_`. Kdo je prohodí, rozbije to druhé.

Dopad: z 91 položek fronty je 66 draftů. **Většina fronty je pro PO nezapsatelná** — a jsou v ní ty nejdražší věci, včetně P1 úniku jména a e-mailu libovolného uživatele přes instructor API.

### C. `grant` na codexu nestačí, a nestačí kvůli vlastnímu CLI

[`providers.py:104`](../../packages/core/src/agency/providers.py) to přiznává předem:

> CAUTION: unlike the claude branch this is **not verified by a real run**, only read off the 0.144.3 help.

Teď ověřená je a neprošla. `agency` na Windows je uv trampolína (`~/.local/bin/agency.EXE`), která se uvnitř `--sandbox workspace-write` nespustí:

```
error: uv trampoline failed to canonicalize script path
```

Codex proto každé volání `agency backlog` eskaluje mimo sandbox a **ptá se uživatele**. Slib Fáze 8 — autorizace se odvodí z manifestu packu a nikdo neklikne — pro codex neplatí. Není to vada codexu ani sandboxu: je to vada v tom, že `agency doctor` ověřuje entrypoint tak, jak ho vidí shell uživatele, a ne tak, jak ho uvidí agent.

`__main__.py` existuje, takže `python -m agency` je druhá cesta k témuž. Která z cest v sandboxu projde, je otázka na sondu (Krok 3), ne na úsudek.

### D. Chybějící cyklus není nález, je nesplněná podmínka

`packs/po/pack.json` → `config.required` je `["repo.slug", "roadmap.file"]`. `roadmap.cycle`, `cycleEnds`, `capacity` a `goals` v seznamu nejsou, takže běh nastartuje bez nich — a po 41 minutách ohlásí jako **nález se skóre 99**, že rozhoduje bez horizontu.

To je správné zjištění doručené nejdražším možným způsobem. Doctor ten mechanismus už má ([`cli.py:468`](../../packages/core/src/agency/cli.py) — `missing required`); jen tam ty klíče nejsou.

Zároveň to nesmí být tvrdá podmínka `agency hire` — projekt bez cyklu si packa nainstalovat smí a `agency doctor` mu má říct, co doplnit. Podmínka patří na `agency run`.

### E. Nález o rozbité Agency nemá kam jít

Dva z pěti nálezů toho běhu jsou hlášení o vadách **A** a **B** — tedy bug reporty na VeriFlow Agency, zapsané do produktové fronty main-panelu, zakotvené do `.agency/po.json`. Kanál „nástroj, kterým to píšu, je rozbitý" neexistuje, takže to teče do jediného výstupu, který pack má.

Je to správná reakce agenta na špatnou nabídku. Nález ale skončí v paměti projektu main-panel a v jeho precision, kam nepatří: až se Agency opraví, zůstane v `knowledge/` viset zjištění o něčem, co dávno neplatí, a bude ředit číslo, kterým se měří kvalita produktových nálezů.

### F. Otevřená otázka — bránu smí přepsat ten, koho brání

`.agency/po.json` leží v pracovní kopii a agent do `.agency` **má zápis** (`--add-dir`). Jediné, co mu brání si přepínač přehodit, je věta v SKILL.md:

> `config.writes` decides what happens, not your judgement about what would be helpful. […] Record what you would have done and say which switch would allow it; do not look for another way to do it.

U tohohle běhu se přepnutí v 12:51:37 stalo **19 minut po zápisu `run.json`**, v době, kdy sezení codexu podle uživatele ještě běželo a mělo schválené „always run commands that start with `agency backlog`". Kdo přepínač přehodil — člověk, nebo agent — z filesystému zjistit nejde a **je to jedno**: brána, kterou může přepsat gated strana, není brána. Oprava je stejná v obou případech.

---

## 3. Co se opravovat nebude

**`roadmap.cycle`, `capacity` a `goals` zůstávají lidský vstup.** Kapacita je měna, ze které se platí každé „ano". Agent, který si smí dopsat vlastní kapacitu, financuje svoje rozhodnutí penězi, které si vytiskl, a `defaultAnswer: not-now` přestane cokoli znamenat. Krok 4 řeší **kdy** se na jejich absenci přijde, ne kdo je vyplní.

**`writes.issues` a `writes.promote` zůstávají ve výchozím stavu vypnuté.** Šablona ([`packs/po/config.template.json`](../../packs/po/config.template.json)) je zavírá záměrně: issue přistane lidem v inboxu a povýšení je okamžik, kdy se z poznámky stane závazek. Ten P1 PII draft nešel povýšit ani kdyby **B** bylo opravené — a to je pojistka, která funguje, ne vada. Mění se jen to, že se o ní uživatel dozví dřív než z `exitReason` (Krok 4).

**Vada D z [`unattended.md`](unattended.md) — cíl řetězu — se tady neřeší.** Je vidět i v tomhle běhu, ale patří svému plánu a svojí fázi.

---

## 4. Kroky

### Krok 1 — `writes.status` jako vlastní přepínač (~1 h)

- `backlog.py` → `WRITE_GATE["status"] = "status"`.
- `packs/po/config.template.json` → nový klíč `writes.status`, výchozí **`true`** s komentářem: přesun sloupce je to, čím se rozhodnutí projeví; štítky jsou úprava cizího repozitáře a zůstávají vypnuté.
- Čtení s ústupem: chybí-li `writes.status`, zdědí hodnotu `writes.labels`. Existující projekty tím nezmění chování ze dne na den.
- `cli.py:2338` — rozdělit obě větve, každá hlásí svůj přepínač.
- README a `SKILL.md` packa PO: tabulka `writes` má o řádek víc.

**Hotovo, když:** projekt s `labels: false` a `status: true` přesune kartu do sloupce a **nesáhne** na štítky, a `agency backlog decide` to obojí vypíše zvlášť. Test v `test_po_pack.py`.

### Krok 2 — id obsahu draftu skrz snapshot i ref (~2 h)

- `Board.items()` už `content.id` dostává (ověřeno, §7) — přestat ho zahazovat.
- `snapshot()`: k položce typu draft přidat `draftId` vedle `item`.
- `resolve_ref()`: obě větve, které vracejí `kind: "draft"`, nesou `draftId`.
- `comment()`: draftová větev volá `item-edit --id <draftId> --body …`.
- `set_status()` a `set_labels()` se **nemění** — pracují s `PVTI_` a je to správně. Do `backlog.py` k tomu patří komentář, protože příště to znovu splete každého.
- `promote()` bere `ref["item"]` (`PVTI_`) — mutace `convertProjectV2DraftIssueItemToIssue` chce id položky. Taky beze změny.
- Chybí-li `draftId` (starý snapshot, cizí `gh`), zápis **selže s vysvětlením**, ne tiše na `PVTI_`.

**Hotovo, když:** `agency backlog decide <PVTI_…> next --because "…"` připíše podepsanou poznámku do těla draftu a `agency backlog list --mine` ten draft najde podle markeru. Test v `test_po_pack.py` s fixture, která obě id rozlišuje.

### Krok 3 — codex, který se neptá (~2–3 h, začíná sondou)

Sonda nejdřív, ve scratchpadu, prázdné git repo, `codex exec --sandbox workspace-write -c sandbox_workspace_write.network_access=true`:

| co zkusit | co to řekne |
|---|---|
| `agency --version` (uv trampolína) | reprodukuje se `failed to canonicalize script path`? |
| `python -m agency --version` | obchází trampolínu modul? |
| totéž s `-c sandbox_workspace_write.writable_roots=["<uv tool root>"]` | stačí přidat kořen, nebo je vada v trampolíně samotné? |
| `gh issue list` uvnitř sandboxu | drží `network_access=true` i pro `gh`? |

Podle výsledku pak **jedna** z těchto oprav, ne všechny:

- `providers.py` → `editsGrant` codexu doplnit o `writable_roots` s kořenem instalace, **nebo**
- `runs.py` → do promptu a `context.json` předat entrypoint, který v sandboxu projde, a SKILL.md packů na něj odkázat.

Nezávisle na výsledku:

- `agency doctor` musí entrypoint ověřit **tak, jak ho zavolá agent** — pro každého najatého providera, ne z shellu uživatele. Dnešní kontrola „`agency` je na PATH" odpovídá na jinou otázku, než která padne za běhu.
- `providers.py:104` — varovný komentář nahradit tím, co sonda zjistila. Datum a verze v textu.
- `agent.unattended: "bypass"` zůstává zdokumentovaný únik, ne doporučení: vypíná sandbox celý, kdežto vada je v jednom binárním souboru.

**Hotovo, když:** `agency run po --provider codex` nad main-panelem projde bez jediného dotazu na svolení a `run.json` → `agent.denied` je `0`.

### Krok 4 — cyklus jako podmínka běhu, ne jako nález (~1 h)

- `packs/po/pack.json` → nová sekce `config.requiredForRun` (vedle `config.required`, které platí pro `hire`): `roadmap.cycle`, `roadmap.capacity`, `roadmap.goals`.
- `agency run po` s prázdným některým z nich **nezačne** a vypíše, co doplnit a proč — pro `goals` větou z šablony, ne odkazem na klíč.
- `agency doctor` je hlásí jako varování už předtím, ne až u běhu.
- `policy.escalate: null` je varování doctoru, ne blok. Agent bez odvolání je překážka, ale rozhodovat umí.
- `SKILL.md` packa PO, sekce *„The cycle"*: pasáž „if `cycle` is null, say so in `run.json` and file a finding" přestává platit — jádro k tomu běh nepustí.

**Hotovo, když:** projekt s prázdným `roadmap.cycle` dostane odpověď do vteřiny, ne po 41 minutách jako nález. Test v `test_po_pack.py`.

### Krok 5 — kam patří nález o nástroji (~1 h)

Nejmenší krok a nejlevnější varianta ze tří zvažovaných:

- `run.json` dostane `toolIssues[]` — volný seznam `{what, where, evidence}`, který pack vyplní, když ho zablokuje **Agency**, ne produkt.
- `SKILL.md` všech čtyř packů: vada nástroje jde sem, ne do `findings.json`. Nález je o produktu; o nástroji je tohle.
- `agency status` a extension je vypíšou u běhu jako samostatný řádek.
- `agency ingest` je **nezapočítá** do `counts` ani do precision.

Zavržené varianty: vlastní pack (nikdo ho nepustí ve chvíli, kdy potřebuje) a automatické zakládání issues do repozitáře Agency (běh cizího projektu nemá psát do našeho).

**Hotovo, když:** běh, kterému selže zápis na draft, to má v `toolIssues[]`, ne mezi nálezy, a precision projektu se tím nehne.

### Krok 6 — brána, kterou gated strana nepřepíše (~2 h)

- `runs.py` — před spuštěním sejmout otisk (sha256) souboru `<pack>.json`; `ingest` ho ověří znovu. Rozdíl = `run.json` → `configChanged: true` a hlasitá věta v `agency status`.
- Zápis přes `agency backlog` čte `writes` **z otisku pořízeného na startu**, ne z disku. Přepis souboru za běhu tedy nic neodemkne, ať ho udělá kdokoli.
- `SKILL.md` packa PO: k větě o `config.writes` doplnit, že se to hlídá, ne že se to slibuje.
- Změna konfigurace mezi běhy je normální a **nesmí** vadit — hlídá se jen změna **uvnitř** jednoho běhu.

**Hotovo, když:** test přepíše `writes.promote` na `true` uprostřed běhu a `agency backlog promote` to i tak odmítne s odkazem na otisk.

---

## 5. Pořadí a rozsah

| krok | rozsah | čeká na | proč v tomhle pořadí |
|---|---|---|---|
| 4 — cyklus jako podmínka | ~1 h | nic | nejlevnější, a bez něj další běh znovu zaplatí 41 minut za totéž |
| 1 — `writes.status` | ~1 h | nic | odemkne sloupce, aniž by se muselo povolovat psaní štítků |
| 2 — `draftId` | ~2 h | nic | odemkne 66 ze 91 položek fronty |
| 3 — codex bez dotazů | ~2–3 h | sonda | blokuje **každý** codexí běh, nejen PO |
| 5 — `toolIssues[]` | ~1 h | 1, 2 | až budou vady A a B pryč, ať se do fronty nepíšou další |
| 6 — otisk konfigurace | ~2 h | 1 | poslední, protože jako jediný nic neodemyká |

Kroky 1, 2 a 4 jsou na sobě nezávislé a dohromady jsou to **čtyři hodiny**, po kterých PO na tomtéž backlogu zapíše, co rozhodne. Krok 3 je jediný, který se dělá pro celý nástroj a ne pro PO.

---

## 6. Přejímka

Jeden běh `agency run po --provider codex` nad `Chci-na-lekci/main-panel`, se stejným zadáním jako 2. 9. Šest podmínek, všechny najednou:

1. **Ani jeden dotaz na svolení.** `run.json` → `agent.denied == 0`.
2. **Cyklus je vyplněný**, jinak běh vůbec nezačal (Krok 4) — a nález o chybějícím horizontu se už neopakuje.
3. **Rozhodnutí na draftu je vidět na kartě.** Podepsaná poznámka v těle, marker `agency:po:<key>` v něm, druhý běh ji najde a nepřipíše podruhé.
4. **Karty se přesunuly** do sloupců podle rozhodnutí, se `writes.labels = false` — tedy bez jediné změny štítku v repozitáři.
5. **Žádný nález o Agency v `findings.json`.** Co selhalo v nástroji, je v `toolIssues[]`.
6. **Přepis `po.json` za běhu nic neodemkne.**

A jedna podmínka nad výstupem, kterou nesplní kód, ale ověří ji člověk: po tom běhu má být na nástěnce vidět, co PO rozhodl, **aniž by se otevíral VS Code**. To byla původní otázka a je to jediná odpověď na ni.

---

## 7. Ověřeno 2. 9. 2026

`gh` 2.96.0, `codex-cli` 0.144.3, Windows 11, projekt `Chci-na-lekci/main-panel` (Project #1, 91 položek).

| tvrzení | jak ověřeno |
|---|---|
| `item-list --format json` vrací u draftu `id` (`PVTI_…`) i `content.id` (`DI_…`) | živý dotaz na Project #1, tři položky, `--jq` na klíče `content` |
| `item-edit --body` je *„Body of the draft issue item"* | `gh project item-edit --help`, 2.96.0 |
| snapshot `content.id` zahazuje | [`backlog.py:694`](../../packages/core/src/agency/backlog.py); `evidence/backlog.json` z běhu nese jen `item` |
| přesun sloupce visí na `writes.labels` | [`backlog.py:58`](../../packages/core/src/agency/backlog.py), [`cli.py:2338`](../../packages/core/src/agency/cli.py) |
| brána `promote` držela | `.agency/po.json` zapsáno 12:51:37Z, povýšení 12:52:16Z — tedy až po přepnutí, ne přes ně |
| `agency` je uv trampolína | `shutil.which` → `C:\Users\…\.local\bin\agency.EXE`; `agency/__main__.py` existuje, takže `python -m agency` je druhá cesta |
| trampolína padá v codexím sandboxu | `error: uv trampoline failed to canonicalize script path` z transkriptu běhu — **jednou, na jednom stroji**; příčina zúžená na dva kandidáty, sonda v Kroku 3 je má rozhodnout |

**Neověřeno:** že `writable_roots` problém vyřeší, a že `python -m agency` v sandboxu projde. Obojí je návrh, ne zjištění — proto Krok 3 začíná sondou a ne opravou.
