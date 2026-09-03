# Agency v1 — redefinice od začátku

**Datum:** 2026-09-02
**Nahrazuje:** [`packs-concrete.md`](packs-concrete.md) (smazáno — byl to plán zmenšení konfigurace, tohle je plán nástroje), [`../implementation-plan-v0.md`](../implementation-plan-v0.md) jako definici tvaru. [`../product-brief.md`](../product-brief.md) zůstává s opravou pravidla 5 (§7).
**Bere v potaz:** [`po-writes.md`](po-writes.md), [`unattended.md`](unattended.md), [`teams.md`](teams.md), [`shared-memory.md`](shared-memory.md), [`graph-abstraction.md`](graph-abstraction.md), původní agenty `../nalekci-po-agent` a `../nalekci-qa-agent`, a článek *I Asked for a CLI. AI Built Me a Platform.*
**Pořadí prací:** [`tasks.md`](tasks.md) → Fáze 10.

---

## 0. Proč od začátku

Za tři dny (30. 8. – 2. 9.) vzniklo 14 000 řádků jádra, 3 100 řádků extension, 2 500 řádků packů, osm plánů a 373 testů. Funguje z toho hodně — brána nad nálezy, dedup, kotvy, řetěz, neattended běh, paměť čitelná bez nástroje. Ale nástroj mezitím dostal tvar platformy: registr providerů v `~/.agency/providers.json`, roster pracovníků, registr projektů, šablony konfigurace po 180 řádcích, driver grafu s `capabilities()`, OKF parser s `stale_after`, lexikální ranker, formulář na Playwright v editoru. Každá ta věc má v plánu odstavec, proč je správně. Dohromady je to nástroj, který jeho jediný uživatel nedokáže nastavit — což se ukázalo na konfiguraci QA agenta, kde je 40 klíčů a všech 40 je `null`.

Původní agenti (`nalekci-po-agent`, `nalekci-qa-agent`) měli přesně opačný tvar: jeden projekt, fakta natvrdo, politika jako text, paměť jako markdown, dva skripty. Chyběl jim jen obal — záznam běhu, brána, triage, dedup, paměť napříč běhy. To je to, co má Agency dodat. Ne to, co dodává navíc.

Definice se proto píše znovu, od uživatele a workflow, a teprve z ní se odvozuje, co z dnešního kódu zůstane. Většina zůstane — ale **jako výsledek odvození, ne jako výchozí stav.**

---

## 1. Co to je

> **Agency spouští specialisty nad repozitářem `main-panel` a nechává po nich záznam.** Specialista je skill v repu — recenzent, product owner, QA, právník. Běh má začátek, konec a adresář. Co specialista najde, projde branou, dostane rozhodnutí od člověka a zůstane v paměti projektu, kterou přečte i holá session bez Agency.

Jeden uživatel, jeden projekt, čtyři specialisté, pět workflow. Druhý projekt (s Jirou) dostane **kopii** packů a přepíše si fakta a skripty. Třetí projekt ukáže, co je společné. Do té doby se nic neabstrahuje.

Co to **není**: platforma pro cizí packy, registr providerů, multi-projektový přehled, konfigurační systém. Když se má něco změnit, změní se kód. Na to je tu agent.

---

## 2. Pět workflow nad main-panelem

Tohle je celý produkt. Když je tohle hotové a jde to z jedné řádky, je v1 hotová.

### W1 — Review pull requestu

```
agency run review-graph --pr 479
```

Připraví jednorázový worktree na hlavičce PR, nechá `code-review-graph` spočítat dopad, **spustí agenta v tomhle terminálu**, počká, a když skončí, pustí bránu. Na obrazovce: průběh, pak počty — kolik nálezů prošlo, kolik brána zahodila, kolik je duplicit. Pak:

```
agency findings                     co čeká na rozhodnutí
agency triage accept 01M1…          nebo reject --reason by-design, defer
agency export --project 1           přijaté nálezy → drafty v Project #1 (Technical findings), jednou
```

Totéž v editoru: nálezy u řádku kódu, tlačítka accept / reject / defer.

### W2 — Review s produktovým soudem

```
agency chain review-graph po --pr 479 --prompt "dává tahle změna produktový smysl?"
```

Recenzent běží první, product owner dostane jeho nálezy **jako zadání**: každý rozhodne (`accept` / `reject` s důvodem / `defer`), odpoví na otázku a zapíše, co z toho plyne pro frontu. Na člověka jde rozhodnutá fronta, ne surová. To je ta věta z článku — *technical review, PO review, merge, decision* — v jednom příkazu.

### W3 — Grooming backlogu

```
agency run po --prompt "co se staví teď, když čekáme na zápis s.r.o. a chystáme platby"
```

PO si sejme snímek: otevřené issues s milníky, drafty na boardu s poli `Stav`/`Oblast`, otevřené milníky (nejbližší je cyklus), #255 jako release umbrella. Rozhodne podle pěti dispozic z původního agenta (`BUILD NOW` / `FIX-REMOVE NOW` / `VALIDATE CHEAPLY` / `DEFER WITH TRIGGER` / `REJECT`), **zapíše rozhodnutí na board vlastním skriptem** — podepsaný komentář, přesun `Stav`, štítek `priority:P*`, povýšení draftu — a do `findings.json` dá jen to, co je špatně s frontou samotnou. Do `.agency/knowledge/pages/po/decisions.md` připíše, co rozhodl a proti čemu.

### W4 — QA sezení na stagingu

```
agency run qa --prompt "rezervace a storna jako zákazník, na mobilu"
```

Jen `https://nalekci-staging.chytre.digital`, pět person (`guest`, `customer-a/b`, `trainer-a/b`) sekvenčně, každá ve vlastním prohlížeči. Každý nález má Playwright spec v `RUN_DIR/specs/`, který na něm spadne, a dedup jde i proti živému boardu (fingerprint `entity|action|state|consequence`). Co je v `pages/qa/known-regressions.md`, je replay, ne nález.

### W5 — Právní review

```
agency run legal --prompt "VOP pro lektory před spuštěním online plateb"
```

Applicability gate je napsaný ve skillu (marketplace, lektoři jako podnikatelé, Stripe Connect, CZ, DAC7 z platby), dokumenty a kód souhlasu mají známé cesty. Každý nález cituje ustanovení z primárního zdroje; hlásí i povinnosti, které si produkt vymyslel sám.

### Paměť, kterou přečte kdokoli

`.agency/knowledge/` je **commitovaný** adresář markdownu: ledger nálezů (`findings/<id>.md`, `index.md`, `log.md`) generovaný z běhů, a stránky packů psané agenty (`pages/po/decisions.md`, `pages/qa/coverage.md`, `pages/legal/applicability.md`, …). Holá Claude Code session v repu ho přečte. Codex taky. Člověk v editoru taky.

---

## 3. Tvar

Tři věci, každá s jednou odpovědností. Hranice mezi nimi je kontrakt, ne konfigurace.

```
veriflow-agency/                     tenhle repozitář
  packages/core/     → `agency`      RUNNER: běh, záznam, brána, triage, dedup, paměť, řetěz, providery.
                                     Nezná main-panel. Nezná Playwright, board, roadmapu, VOP.
  packages/extension/                VIEWER: běhy, nálezy u řádku, triage klikem, spuštění běhu do terminálu.
                                     Mluví jen s `agency … --json`.
  packs/                             PŘÍKLADY: referenční kopie packů main-panelu pro příští projekt.
                                     Nebundlují se, neinstalují se.

main-panel/                          projekt
  .claude/skills/agency-po/          PACK = skill. Commitovaný, verzovaný s projektem.
    pack.json                          co runner potřebuje vědět (11 klíčů, §3.2)
    SKILL.md                           metoda + Project facts, anglicky
    references/                        politika (feature-admission.md, severity.md, …)
    scripts/backlog.py                 nástroj packu; volá ho agent, ne runner
  .claude/skills/agency-qa/  … agency-legal/  … agency-review-graph/
  .agency/
    knowledge/                       PAMĚŤ, commitovaná
    runs/<ULID>/                     ZÁZNAMY, gitignored (evidence, transkripty, findings.json, run.json)
    qa-accounts.local.json           gitignored
```

`~/.agency/` **neexistuje.** Konfigurace projektu **neexistuje.** Pack je tam, kde ho Claude Code hledá jako skill, a runner ho tam najde taky — `pack.json` vedle `SKILL.md`. Žádný `agency add`, žádný `installed.json`, žádný hash, žádná dvojí kopie.

### 3.1 Runner — `agency --help`

Tohle je návrh nápovědy. Je to zároveň seznam příkazů, které v1 má, a test z článku: dá se to pochopit za minutu.

```
agency — specialists for this repository. A specialist is a skill in .claude/skills/agency-<name>/.

run
  run <pack> [--pr N | --prompt "…"] [--provider claude|codex] [--model M]
        prepare the run, launch the agent in this terminal, gate the output when it ends
  chain <pack> <pack>… [--pr N] [--prompt "…"] [--provider …]
        run in sequence; each member judges the previous one's findings first

decide
  findings [--run ID] [--state candidate|accepted|rejected|deferred]
  triage accept|reject|defer <finding-id> [--reason R] [--note "…"]
  note <finding-id> --text "…"
  export --project N [--run ID]        accepted findings → GitHub Project drafts, once each

look
  status        runs here: running, failed, waiting for a decision
  metrics       precision, duplicates, cost per candidate, per specialist
  doctor        what is missing before a run can work here
  packs         the specialists in this repository and what they need

maintain
  ingest [--run ID]       the gate over what an agent wrote (run does this itself)
  cleanup [--run ID]      remove the throwaway worktree of a finished run
  knowledge [--rebuild]   the committed memory in .agency/knowledge
  validate [--fix]        run records and findings against the schema
  graph <verb> …          code-graph queries as JSON (packs call this)
  prs                     open pull requests (the extension calls this)
```

Sedmnáct příkazů. Pryč je: `init`, `add`, `hire`, `fire`, `roster`, `providers`, `projects`, `config`, `brief`, `backlog`. Změna chování: **`run` čeká a pustí bránu sám** — dnešní `--wait` je výchozí, protože běh, na který se zapomene, je běh, který neexistuje. `--json` připraví a vypíše bez spuštění (pro extension a pro ladění).

Providery jsou **dva a jsou v kódu**: tabulka `claude` / `codex` v `providers.py` — binárka, flagy, autorizace, streamovací dialekt. Třetí runner je změna tabulky, ne registr. Autorizace je vždycky `grant` (zápis do worktree a `RUN_DIR` plus `needs` z manifestu); `--bypass` je přepínač příkazu pro případ, kdy sandbox nepustí vlastní binárku ([`po-writes.md`](po-writes.md) Krok 3 zůstává).

Identita rozhodnutí zůstává `hire:<pack>@<provider>` a `human` — stejný tvar jako dnes, aby historie a ledger zůstaly čitelné; „hire" je jen slovo, roster za ním není.

### 3.2 Pack — `pack.json`

```json
{
  "name": "po",
  "title": "Product owner · NaLekci",
  "description": "Decides what gets built now against #255, the milestones and the accepted decisions; writes the decision on the board.",
  "requires": ["git", "gh"],
  "target": "workspace",
  "worktree": false,
  "graph": false,
  "prompt": "required",
  "needs": ["agency triage", "agency note", "agency findings", "git", "gh issue view",
            "python .claude/skills/agency-po/scripts/backlog.py"],
  "minScore": 75,
  "dimensions": ["scope", "readiness", "backlog", "roadmap-drift", "sequencing", "value"]
}
```

Jedenáct klíčů, všechny čte runner: `requires` → doctor; `target`/`worktree`/`graph` → příprava běhu; `prompt` (`required` | `optional` | `none`) → validace `--prompt`; `needs` → allowlist agenta; `minScore` → brána; `dimensions` → validace nálezů a nabídka v extension. Verze není — pack je v gitu projektu. Názvy dimenzí, práh a politika jsou vlastnost packu, ne projektu, protože pack **je** projektový.

Fakta projektu jsou v `SKILL.md`, sekce **Project facts** nahoře. Pro main-panel:

| pack | co tam stojí natvrdo |
|---|---|
| všechny | `Chci-na-lekci/main-panel`; jazyk nálezů, komentářů a stránek **čeština**; `docs/specification/spc.md` + doplňky = kontrakt; pravidla `CLAUDE.md#rules-that-will-bite-you`; mapa `CLAUDE.md#where-the-truth-lives`; brána `npm run verify`; sekce *Mimo rozsah* v PR je nález pro PO |
| po | Project #1 a tři pohledy (*Inbox*, *Rozvoj platformy* = kontejner nápadů z #105, ne fronta, *Technical findings* = sink); pole `Stav` / `Oblast` / `Severity` / `Reason`; #255 + milníky = závazky, cyklus = nejbližší otevřený milník; štítky `priority:P0`–`P4`; precedence zdrojů pravdy; kapacita (věta, mění se ručně); kdo přehlasuje |
| qa | jen staging `https://nalekci-staging.chytre.digital` s basic auth z `main-panel/.env.local`; persony a jejich soubor `.agency/qa-accounts.local.json`; 1440×960 a 390×844; cs pak en; jeden prohlížeč na personu, sekvenčně; nikdy `db:reset`, reálná platba, mazání účtu; playwright-bdd ve `spec/` je dialekt, ne suite k pouštění; reprodukce do `RUN_DIR/specs/` s pojistkou na host |
| legal | marketplace, lektoři B2C přes platformu, Stripe Connect (dnes `ONLINE_PAYMENTS=off`, cíl 1. 10.), předplatné lektorů, CZ, DAC7 z platby (D-0006), s.r.o. čeká na zápis (#257); dokumenty `src/app/[locale]/{terms-and-conditions, terms-of-use-for-instructors, online-payment-terms-for-instructors, privacy-policy, cookies-policy}` + `archiv/[verze]`; souhlas `src/app/api/user/legal/*`, `src/application/legal/`; akceptace `public.user_terms_consents`; oznámení `src/app/api/internal/legal/notify-change`; posture proporcionální, citace povinná, over-compliance se hlásí |
| review-graph | graf přes `agency graph`; všech pět dimenzí; worktree `../main-panel-review-pr-<n>-<provider>` |

Politika jde do `references/`, beze změny z původních agentů: `feature-admission.md`, `pr-findings.md` (PO), `severity.md`, `risk-archetypes.md` (QA), `sources.md`, `cz-eu-baseline.md` (legal).

Nástroje packu jsou skripty v `scripts/`, volá je agent, runner o nich ví jen z `needs`. V1 má jeden: `po/scripts/backlog.py` — `snapshot | comment | draft | promote | decide`, `--dry-run`, konstanty boardu, podpis, marker `<!-- agency:po:<key> -->`, ledger do `$AGENCY_RUN`, obě id draftu (`PVTI_` pro pole, `DI_` pro tělo — [`po-writes.md`](po-writes.md) §2 B). Write gate je to, co skript umí: `issue` a `close` nemá.

### 3.3 Kontrakty

Jediná místa, kde se dvě z těch tří věcí dotýkají. Nic jiného se nesdílí.

| kontrakt | mezi | tvar |
|---|---|---|
| `pack.json` | pack → runner | §3.2 |
| `RUN_DIR` | runner → pack → runner | `context.json`, `evidence/`, `prompt.txt`; zpět `findings.json` (`finding.v1`), `summary.md`, `handoff.md` v řetězu, `specs/`, `drafts/` |
| `context.json` | runner → pack | `runId`, `runDir`, `project`, `target` (+ `headRefOid`), `files`, `prompt`, `by`, `knowledge`, `pages`, `chain`, `review` (`dimensions`, `minScore`), `worktreeOwned` |
| `finding.v1`, `run.v1` | pack → brána; runner → extension | schémata, jediná dvě |
| `AGENCY_RUN` | runner → skripty packu | id běhu; `.agency/runs/<id>/` je jeho adresář |
| `.agency/knowledge/pages/<pack>/` | pack ↔ paměť | markdown; první řádek `Last reviewed: <datum>`; závěry, ne deník |
| `agency … --json` | runner → extension | co dnes |

Pryč z `context.json`: `config`, `sinks`, `hire`, `brief.standing/scenarios` (je jen `prompt`), `prCommentMarker` (recenzent si marker skládá z `runId` — je to jeho věc, ne runneru).

### 3.4 Paměť

Zůstává z [`shared-memory.md`](shared-memory.md): ledger nálezů generovaný z běhů (`findings/<id>.md` s `verified` tiery z `by`), `index.md`, `log.md` ze `summary.md`, stránky packů. Bundle je odvozený, `agency knowledge --rebuild` ho přestaví z `.agency/runs/`.

Mění se tři věci:

- **Commituje se.** Dnes je `.agency/` v main-panelu celé v `.gitignore` — paměť tedy neexistuje mimo jeden stroj. Nově: `.agency/knowledge/` v gitu, `.agency/runs/` a `*.local.json` ne. Důsledek: `--rebuild` na klonu bez běhů **nesmí mazat**, co nedokáže znovu vygenerovat — jen přidává a aktualizuje.
- **Stránky jsou obyčejný markdown.** Bez OKF frontmatteru, bez `stale_after`, bez parseru s číslem řádku. Konvence je jeden řádek `Last reviewed: 2026-09-02` nahoře a pravidlo ve skillu: *přepiš, co přestalo platit; nepřidávej deník.* Doctor ukáže „po/decisions.md · 12 dní". Původní agenti to tak měli a fungovalo to.
- **`rules/` a ranker nejsou.** Pravidla projektu jsou v `CLAUDE.md`, kde je main-panel má; druhé místo s frontmatterem by je jen rozdvojilo. Paměť má desítky nálezů, ne tisíce — do běhu jdou nejnovější, bez BM25.

---

## 4. Co z dnešního kódu zůstává a co ne

Přestavba je **mazání**, ne přepis. Jádro, které dělá zápis běhu, bránu, dedup, kotvy, řetěz a stream, je správně a je otestované; jde pryč to, co obsluhovalo konfiguraci, registry a hypotetické druhé případy.

### Zůstává (odvozeno z §2 a §3, ne z pohodlnosti)

| modul | řádků | proč |
|---|---|---|
| `runs.py` (zúžený) | ~900 z 1270 | záznam běhu, worktree, evidence, `context.json`, rozhodnutí — jádro W1–W5 |
| `ingest.py`, `dedup.py`, `anchor.py` | 230 + 179 + 136 | tři ze šesti pravidel produktu: bez důkazu není nález, neopakovat se, kotva přežije změnu kódu |
| `chain.py`, `events.py`, `proc.py` | 298 + 222 + 307 | W2; řetěz bez streamu je dvacet minut ticha |
| `knowledge.py` (zúžený) | ~450 z 648 | paměť, kterou přečte kdokoli |
| `metrics.py`, `export.py` | 242 + 226 | „vím, kolik z toho bylo k něčemu"; nálezy ven jednou, po schválení |
| `graph.py` (zúžený) | ~180 z 269 | `agency graph` jako JSON s cestami relativními k repu — pack se neptá nástroje přímo; bez `capabilities()` a bez „driveru" |
| `providers.py` (zúžený) | ~200 z 321 | tabulka dvou runnerů, `launch_argv`, `authorization`, `streaming`; bez `~/.agency/providers.json` |
| `packs.py` (přepsaný) | ~60 z 235 | `available(project)` = `.claude/skills/*/pack.json`; nic se neinstaluje |
| `cli.py` (zúžený) | ~1700 z 2701 | sedmnáct příkazů z §3.1 |
| `schemas/finding.v1.json`, `run.v1.json`, `validate` | | jediné dva kontrakty, které píše LLM a čte stroj |
| extension (zúžená) | ~2300 z 3116 | nálezy u řádku, triage, běhy, spuštění do terminálu |

### Jde pryč

| co | řádků | proč to nepřežilo odvození |
|---|---|---|
| `config.template.json` ×4, `Project.pack_config`, `config.detect`, `detect_playwright`, `agency config`, `agency init` | 572 + ~250 | konfigurace projektu neexistuje (§3) |
| `agency brief`, `resolve_brief` scénáře | ~150 | standing brief byl způsob, jak do obecného packu dostat fakta projektu; pack je projektový, fakta má ve skillu. Scénáře nikdo nepoužil (`scenarios: {}` ve všech čtyřech souborech) |
| `hires.py`, `agency hire/fire/roster`, `hires.json`, `test_roster.py` | 257 + ~300 + 718 | „dva providery nad jedním PR" je `--provider` a dva terminály; roster přidával id, tituly a `--as` k něčemu, co je flag |
| `~/.agency/providers.json`, `agency providers --add` | ~120 | třetí runner neexistuje; až bude, je to řádek v tabulce |
| `registry.py`, `agency projects`, `AGENCY_HOME` | 63 + ~60 | jeden projekt; přehled napříč čtyřmi je `ls` |
| `backlog.py`, `agency backlog` | 706 + ~240 | stěhuje se do `po/scripts/backlog.py` bez konfigurace; runner GitHub Project nezná |
| instalace packů: `packs.plan/apply`, hash, `installed.json`, `agency add`, bundling do wheelu | ~180 + ~80 | pack je v projektu; není co instalovat |
| `okf.py`, `rules/`, `rank.py`, `test_okf.py`, `test_rank.py` | 346 + 112 + ~360 | §3.4 |
| `graph.capabilities()`, „driver", `graph-abstraction.md` Krok 3 | ~90 | jeden nástroj; abstrakce pro druhý, který není |
| doctor: kontroly `app`, `playwright`, `board`, `writes`, `required`, `files` | ~120 | domény packů |
| extension: Playwright formulář, uzly Browser/Backlog/Roadmap/Configuration/Brief, roster strom, `packConfig/setConfig/brief`, launch-argv kontrakt | ~800 | viewer nekonfiguruje; spuštění je `agency run …` do terminálu, ne argv od jádra |
| `agent.allow`, `agent.extraArgs`, režim `ask`, `agent.unattended` z konfigurace | ~60 | allowlist je `needs`; bypass je flag |

Celkem odchází zhruba **6 000 z 21 000 řádků** a asi 120 z 373 testů. Co zbývá, dělá totéž, co dnes, jen bez klíčů.

### [`po-writes.md`](po-writes.md) — Fáze 9

| krok | osud |
|---|---|
| 1 `writes.status` | zaniká — brána je nabídka podpříkazů skriptu |
| 2 `draftId` | přežívá, ve `scripts/backlog.py` |
| 3 codex bez dotazů | přežívá beze změny, jádro; skript packu je `python …`, trampolínu obchází, `agency triage` ne |
| 4 cyklus jako podmínka běhu | zaniká — cyklus je otevřený milník ze snímku; kapacita je věta v Project facts |
| 5 `toolIssues[]` v `run.json` | přežívá beze změny, jádro |
| 6 otisk konfigurace | zaniká — není co přepsat |

---

## 5. Kroky

Každý krok končí zelenou sadou testů a funkčním `agency` v main-panelu; nic se nedělá „až to celé přepneme". Napřed se maže, protože mazání nejde rozbít; packy se píšou až nad zúženým jádrem, aby se nepsaly proti klíčům, které za týden nebudou.

### Krok 0 — zmrazit (10 min)

`git tag v0-2026-09-02` v tomhle repu. Původní agenti se nemažou a nemění — jsou to zdroje pro Krok 5.

### Krok 1 — runner bez konfigurace (~1 den)

- Pryč: `config.template.json` ×4, `pack_config`, `detect*`, `cmd_config`, `cmd_init`, `cmd_brief`, `hires.py` + příkazy, `registry.py` + `cmd_projects`, `~/.agency/providers.json` + `cmd_providers`, `agent.*` z `runs.launch_argv`, `sinks`.
- `run`/`chain`: `--provider` (výchozí `claude`), `--model`, `--prompt`, `--bypass`; `--wait` je výchozí, `--json` = připravit a vypsat. `by` = `hire:<pack>@<provider>`.
- `context.json` podle §3.3. `ingest`: `minScore` z manifestu, `SKIP_PATTERNS` konstanta. `worktree_path` konstanta. `export --project` povinné.
- Testy: pryč `test_roster.py`, testy šablon a `detected` v `test_*_pack.py`, `agent.allow` v `test_unattended.py`; zbytek se opraví na nové signatury. Nový test: `run` bez `--wait` čeká a ingestuje.

**Hotovo, když:** `grep -rn 'pack_config\|hires\|providers.json\|AGENCY_HOME\|brief' packages/core/src` vrátí nulu, `agency run review-graph --pr <N>` v main-panelu doběhne od přípravy po bránu jedním příkazem.

### Krok 2 — pack je skill v projektu (~½ dne)

- `packs.available(project)` čte `.claude/skills/*/pack.json`; `packs.py` je ~60 řádků; `load(name)` bez `--from`.
- Pryč: `plan`/`apply`/hash, `installed.json`, `cmd_add`, `materialize_pack` se zúží na „zkopíruj `.claude/skills/agency-<pack>/` do worktree" (recenzent ve worktree na cizí hlavičce skill potřebuje), `[tool.hatch…force-include]` packů z `pyproject.toml` — schémata se bundlují dál.
- `pack.json` podle §3.2: plochý, 11 klíčů; `run_policy` čte přímo. `agency packs` a `doctor` nad tím.
- main-panel: do každého `.claude/skills/agency-*/` přibude `pack.json`; smažou se `.agency/{po,qa,legal,review-graph}.json`, `hires.json`, `installed.json`; `.gitignore` z `.agency/` na `.agency/runs/` + `.agency/*.local.json`.

**Hotovo, když:** `agency packs` v main-panelu vypíše čtyři specialisty z `.claude/skills/`, `ls main-panel/.agency` ukáže jen `knowledge/` a `runs/`, a `git status` v main-panelu vidí `.agency/knowledge/`.

### Krok 3 — paměť bez frontmatteru (~½ dne)

- Pryč: `okf.py`, `rank.py`, `knowledge.rules_summary`, projekce `known-rules.json`, dimenze `repo-rules` čte jen `CLAUDE.md` odkaz z Project facts.
- Stránky: `Last reviewed:` řádek; `pages_summary` hlásí stáří; ledger se generuje jako dnes, jen bez OKF hlavičky (frontmatter s `id`, `status`, `verified`, `anchor` zůstává — je to YAML, který píše stroj a nikdo neparsuje; `okf.dump` se nahradí deseti řádky).
- `--rebuild` na klonu bez běhů nemaže existující `findings/*.md`.

**Hotovo, když:** `test_ledger.py` a `test_pages.py` procházejí bez `okf`; bundle main-panelu přestavěný dvakrát po sobě nemění ani bajt; `doctor` řekne „po 2 · qa 2 · nejstarší 14 dní".

### Krok 4 — extension jako viewer (~½ dne)

- Pryč: Playwright formulář, `PW_FIELDS`, uzly Browser/Backlog/Roadmap/Configuration/Brief, roster strom + `hire.add/remove/run`, `pack.add`, `provider.add`, `packConfig/setConfig/brief`, launch-argv kontrakt v `review.js`.
- Zůstává: strom packů (z `agency packs --json`), běhy (`status`), nálezy u řádku s triage, řetěz; spuštění = `agency run <pack> --pr N` / `--prompt "…"` / `--provider …` **poslané do terminálu** a refresh po skončení.
- `package.json` 0.6.0, harness bez odstraněných kusů.

**Hotovo, když:** `grep -rn "playwright\|backlog\|hire\|brief\|config" packages/extension/src` vrátí nulu; harness prochází; VSIX 0.6.0 nainstalovaný; z panelu jde spustit W1 a W3.

### Krok 5 — čtyři packy pro main-panel (~2,5 dne)

Pořadí: PO, QA, právník, recenzent. Každý: `pack.json`, `SKILL.md` anglicky s Project facts, `references/` z původních agentů, seed stránek.

- **PO (1 den).** `scripts/backlog.py` z dnešního `backlog.py`: konstanty, `snapshot` (issues + milníky + drafty s `draftId` a poli), `comment`, `draft`, `promote`, `decide` (komentář, `Stav`, `priority:P*`), `--dry-run`, ledger, testy nad zaznamenanými odpověďmi `gh`. `SKILL.md`: pět dispozic z `feature-admission.md`, rubrika P0–P4, precedence zdrojů; krok 0 = `snapshot`. Seed `pages/po/decisions.md` z `nalekci-po-agent/memory/DECISIONS.md` (D-0001…D-0007) a `roadmap-state.md` z `priorities/NOW_NEXT_LATER.md`. Tabulka dispozice → board (návrh, potvrdí uživatel): `BUILD NOW` = komentář + `promote` s milníkem a `priority:P*` (u issue jen komentář + štítek + milník); `FIX/REMOVE NOW` = totéž s `P0`/`P1`; `VALIDATE CHEAPLY` = komentář + `Stav` *Worth exploring*; `DEFER WITH TRIGGER` = komentář se spouštěčem + *Observed* / `P4`; `REJECT` = komentář + *Rejected* + `Reason` *out-of-scope* / `P4`; duplicita = *Archived*.
- **QA (½ dne).** Překlad celý. Project facts z `qa.config.json`, `AGENTS.md` a `main-panel/.qa/context.md` (zůstává v produktu jako kontrakt). `references/severity.md`, `risk-archetypes.md`. Dedup proti živému boardu (`needs` + `gh project item-list`). Seed `pages/qa/coverage.md` a `known-regressions.md` z původní paměti; `LEARNINGS.md` jako sekce skillu. `.agency/qa-accounts.local.json` z `nalekci-qa-agent/.env.local` — přenese uživatel, obsahuje hesla.
- **Právník (½ dne).** Pryč `config.*`; Project facts podle §3.2; všech šest dimenzí včetně `partners` a `tax-reporting`.
- **Recenzent (½ dne).** Překlad celý; Project facts; marker PR komentáře si skládá sám z `runId`.

**Hotovo, když:** čtyři skilly bez jediného `config.`, bez české diakritiky mimo citace; `packs/` v tomhle repu = kopie těch čtyř adresářů.

### Krok 6 — README a product-brief (~½ dne)

- `README.md` se píše **z `agency --help`**, ne naopak: pět workflow z §2, tvar z §3, jak založit pack pro další projekt (zkopíruj `packs/<name>` do `.claude/skills/agency-<name>/`, přepiš Project facts a skripty). Pryč instalace packů, roster, providery, brief, konfigurace.
- `product-brief.md`: pravidlo 5 → *jádro patří všem, pack patří projektu*; tabulka pojmů — Specialista = skill v repu; „Kam to půjde dál" bez obchodu se specialisty.
- `tasks.md`: Fáze 10 hotová po přejímce; Fáze 9 zúžená na Kroky 2, 3, 5.
- `nalekci-po-agent` a `nalekci-qa-agent`: jeden řádek v README, kde metoda a paměť žijí teď.

### Krok 7 — přejímka (~½ dne běhů)

Pět workflow z §2 nad `main-panel`, reálně, bez ručního zásahu do souborů mezi příkazy:

1. **W1** `agency run review-graph --pr <otevřený PR>` — jeden příkaz od přípravy po bránu; `findings.raw.json` existuje; `agent.denied == 0`.
2. **W2** `agency chain review-graph po --pr <týž PR> --prompt "…"` — sedm podmínek z [`unattended.md`](unattended.md) Kroku 8.
3. **W3** `agency run po --prompt "…"` — `evidence/backlog.json` má issues s milníky, drafty s `draftId`, cyklus *Online platby — 1. 10. 2026*; jedno `decide` na draftu zapíše poznámku do těla a pohne `Stav`; `decisions.md` má nový řádek; druhý běh vidí marker.
4. **W4** `agency run qa --prompt "…"` proti stagingu — aspoň jeden spec v `RUN_DIR/specs/` spustitelný `npx playwright test -c …`; známá regrese ohlášená jako replay.
5. **W5** `agency run legal --prompt "…"` — nález pod `partners` nebo `tax-reporting`.

A nad tím: `agency --help` je §3.1; `grep -rn 'playwright\|backlog\|roadmap\|baseUrl\|hires\|brief' packages/` vrátí nulu; `ls ~/.agency` neexistuje; `main-panel/.agency` má jen `knowledge/` a `runs/`; `pwsh scripts/test.ps1` prochází; `wc -l packages/core/src/agency/*.py` je pod 9 000.

| krok | rozsah | čeká na |
|---|---|---|
| 0 zmrazit | 10 min | nic |
| 1 runner bez konfigurace | ~1 den | 0 |
| 2 pack v projektu | ~½ dne | 1 |
| 3 paměť | ~½ dne | 1 |
| 4 extension | ~½ dne | 1, 2 |
| 5 packy | ~2,5 dne | 2, 3 |
| 6 dokumentace | ~½ dne | 5 |
| 7 přejímka | ~½ dne | 4, 5 |

Dohromady **~6 dní**.

---

## 6. Co se vědomě nedělá

- **Nepřepisuje se od nuly.** Brána, dedup, kotvy, řetěz, stream a ledger jsou správně a mají testy; „od začátku" se týká definice, ne souborů.
- **Žádný generic pack.** Druhý projekt = kopie. Třetí ukáže, co je společné.
- **Žádný registr ničeho.** Providery jsou tabulka, packy jsou adresáře, projekt je `cwd`.
- **Žádná konfigurace.** Co se má změnit, změní se ve skillu, ve skriptu nebo v kódu. Když někdo napíše `.agency/<něco>.json`, je to chyba návrhu, ne feature request.
- **Extension nic nenastavuje.** Ukazuje a spouští.
- **Stránky paměti nemají schéma.** `Last reviewed:` a věta ve skillu.
- **`run.prepare` hook, packy mimo `.claude/skills/`, export s poli `Oblast`/`Zdroj`, druhý grafový driver, steering v řetězu** — odloženo na spouštěč, jako dosud. Export s poli je první na řadě: ve chvíli, kdy W1 poprvé reálně exportuje, `agency export` se naučí `Severity` podle jména pole (umí to už pro `Stav`) a `Oblast` zůstane na člověku.

---

## 7. Co se mění v [`product-brief.md`](../product-brief.md)

| dnes | nově |
|---|---|
| *Specialista — Nainstalovatelný odborník s vlastní metodou. Jedna verze metody pro všechny projekty.* | *Specialista — skill v repozitáři projektu, s fakty projektu natvrdo. Jedna verze na projekt; další projekt dostane kopii.* |
| pravidlo 5: *Metoda patří specialistovi, stav patří projektu.* | *Jádro patří všem, pack patří projektu. Sdílený je kontrakt, ne konfigurace.* |
| *Nový projekt je hotový za deset minut* přes `agency init` + `agency add` | zkopíruj čtyři adresáře, přepiš Project facts, `agency doctor` |
| „Potom — obchod se specialisty" mezi věcmi, které mají spouštěč | není a nebude; specialisty se kopírují |

Zbylých pět pravidel platí beze změny — a Agency v1 je poprvé plní všech pět naráz: bez důkazu není nález (brána), nic ven bez člověka (`triage` → `export`), neopakovat se (dedup + živý board), bez tebe se neběhá (attended `run`, řetěz jen když sedíš u terminálu), vypnutí nic neztratí (`.agency/knowledge/` v gitu).
