# Nálezy: GitHub Project je pravda — finální plán

**Datum:** 2026-09-03 · **Stav:** finální, k provedení
**Doplňuje:** [`agency-v1.md`](agency-v1.md) — §2 (W1–W3), §3.1 (`export`), §3.4 (paměť). Ruší `export.py`, lidský `agency triage` a rozhodovací tlačítka v extension. Přidává presety spuštění a hromadný úklid běhů.
**Zadání (uživatel, 3. 9. 2026):** pro main-panel je hlavní zdroj org Project #1. Uživatel nechce vědět nic o sincích ani flagech. Lokální ledger smí existovat, když je potřeba — ale agenti ho nesmějí obejít. Když někdo online (bez repa) povýší draft na issue, změní stav nebo něco smaže, lokální ledger se tím **nesmí rozbít** — nikdo kvůli tomu nebude aktualizovat repozitář. K tomu: rychlé předvolby „který runner, který model" v extension (limit Claude uprostřed W2 je reálný důvod) a „smazat všechny staré/testovací běhy".

---

## 0. Instrukce pro exekutora

- Pracuj v `veriflow-agency` (jádro + extension) a v `main-panel/.claude/skills/agency-*/` (pack). **Ničeho jiného v main-panelu se nedotýkej**; `main-panel/.agency/` nesahej vůbec.
- Pořadí kroků v §8 je závazné. **Každý krok končí zelenými testy** (`pwsh scripts/test.ps1` = pytest jádra + `node packages/extension/test/harness.js`) a **jedním commitem**. Zpráva commitu česky, tvar `feat(findings): …` / `feat(extension): …`, poslední řádek `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. **Nikdy `git push`.**
- Jazyk: kód, komentáře, texty CLI a extension, `SKILL.md` **anglicky**; tento plán a `README.md` česky/anglicky jak jsou; nálezy a texty na boardu česky (to píše agent, ne ty).
- **Nespouštěj reálné agenty** (`agency run`/`chain` bez `--json`) a **nezapisuj na GitHub** (`gh project …`, `gh issue …`). Přejímka v §8 kroku 6 je uživatelova.
- Když něco v tomto plánu nesedí s kódem, který čteš, **zastav se a napiš to** — neopravuj plán potichu.
- Fakta níže jsou ověřená 3. 9. 2026 proti commitu `2e2ac62`. Čísla řádků jsou orientační; hledej podle jmen.

---

## 1. Proč

V1 má dva vlastníky pravdy a nerozhodla mezi nimi:

- `packages/core/src/agency/export.py:1-7`: *„Pravda o rozhodnutí je run record v repu. Project je publikační cíl… Když někdo změní stav přímo v Projectu, další export ho přepíše."*
- `main-panel/.claude/skills/agency-po/SKILL.md` + `scripts/backlog.py`: rozhodnutí se zapisuje **na board**, podepsané, s markerem.

Data main-panelu (ověřeno): `agency export` **nikdy neběžel** (0 nálezů se `sinks.githubProjectItem`); vše na GitHubu (#480–482, #488, #489) napsal `backlog.py`. `decisions.md:31` má rozhodnutí *„přijato, nezapsáno na board"*. `index.md` sekce *Open* drží 7 nálezů, z toho dva už PO okomentoval jinde. Dva *Rejected* kotví `.agency/po.json`, soubor, který neexistuje. A 3. 9. zmizel celý adresář běhu W4 — nález přežil jen díky tomu, že ledger byl už vygenerovaný, ale příští `agency knowledge --rebuild` by ho smazal (`knowledge.bundle()` maže, co v `.agency/runs/` není — `test_a_discarded_run_disappears_from_the_ledger_too`).

Lokální vrstva je druhý backlog a zároveň není spolehlivá paměť. Tenhle plán ji zúží na to, co board neumí: **bránu** a **stopu**.

---

## 2. Tři věty (invarianty — každý krok se proti nim kontroluje)

1. **Board je stav.** Otevřené / přijaté / odmítnuté / hotové / milník říká Project #1. Repozitář to **nikdy neukládá** a nikdy z boardu nečte, aby to uložil.
2. **Lokál je brána a stopa.** `RUN_DIR/findings.json` je jediný vstup pro nález agenta. Co projde branou, jde na board *přes jádro* (sink packu). Co neprojde nebo je odmítnuto, zůstane jako paměť „nehlásit znovu". Stopa je **append-only** a **commitovaná**: fakta o tom, co agent udělal a kam to šlo — ne co teď platí.
3. **Lokál nikdy nečte board, aby věděl, co sám je.** Čtení boardu je živé, v běhu, agentem nebo sink skriptem, a nikdy se neukládá. Proto nic, co člověk udělá online, nemůže stopu rozbít.

---

## 3. Model

### 3.1 Stavy nálezu (`finding.v1` → `state`)

| stav | kde | význam |
|---|---|---|
| `candidate` | `RUN_DIR/findings.json` | prošel branou, ještě nikam nešel. Klidový stav **jen** v projektu bez sinku (§3.4). |
| `held` | `RUN_DIR/findings.json` | v řetězu čeká na dalšího člena (`chain.position < chain.of`). Dočasné. |
| `sent` | `RUN_DIR/findings.json` + stopa | na boardu; `sinks.githubProjectItem` = ref položky. **Koncový.** |
| `rejected` | `RUN_DIR/findings.json` + stopa | odmítnut dalším členem řetězu (`agency triage reject --reason`). **Koncový.** Nejde na board. |
| `duplicate` | `RUN_DIR/findings.json` | jako dnes — brána ho označila (`duplicateOf`). Nejde na board. |

Pryč: `accepted`, `published`, `deferred`. Vyřazené branou zůstávají v `RUN_DIR/gated.json` (jako dnes) a ve stopě s `state: "gated-out"`.

### 3.2 Stopa — `.agency/knowledge/trail.jsonl`

Jeden řádek na nález, **append-only**, **commitovaný** (leží v `knowledge/`, který už je v gitu). Píše ho jádro v `ingest.py` a `cmd_triage`; nikdo ho needituje. Tvar řádku:

```json
{"at":"2026-09-03T09:04:32Z","id":"01M1K7…","runId":"01M1K6…","pack":"qa","state":"sent",
 "title":"…","severity":"high","dimension":"errors","fingerprint":"…",
 "anchor":{"file":"src/…/AccountSubscriptionPanel.tsx","line":199,"commit":"36e52651…","symbol":"AccountSubscriptionPanel"},
 "by":"hire:qa@claude","ref":"PVTI_…","url":null,"reason":null}
```

- `state` ∈ `sent | rejected | gated-out`. `candidate`/`held`/`duplicate` se do stopy **nezapisují** (nejsou koncové, resp. nikam nešly).
- `reason`: u `rejected` jeden z `runs.REJECT_REASONS`; u `gated-out` důvod brány (`phantom-file`, `below-score`, …).
- Stejné `id` se může objevit vícekrát (např. `gated-out` a po opravě kotvy `sent`) — **poslední řádek vyhrává**, jako v `decisions.jsonl`.

K čemu stopa slouží (a k ničemu jinému):
1. **Dedup** (`ingest.earlier_findings`): pool = řádky `sent` + `rejected` ze stopy ∪ nálezy ze stále existujících běhů. `gated-out` **nesuppressuje** — vyřazení branou je mechanika, ne rozhodnutí.
2. **Render `index.md` a `findings/<id>.md`**, i když běh už neexistuje (§3.5).
3. **`agency findings`**, když běh chybí (řádek ze stopy, bez `body`/`evidence`).

### 3.3 Život nálezu

```
agent píše RUN_DIR/findings.json
        │
        ▼
      BRÁNA  ingest.gate()  (schéma · kotva · dedup · minScore)      beze změny
        │
        ├── neprošel ──► gated.json + stopa "gated-out: <důvod>"
        │
        ▼ prošel (state: candidate)
   chain.position < chain.of ?
        │
        ├── ano ──► state: held  (čeká na dalšího člena)
        │              další člen: `agency triage accept <id>` → DISPATCH
        │                          `agency triage reject <id> --reason R` → rejected + stopa
        │
        └── ne ───► DISPATCH každý candidate tohoto běhu
                    + DISPATCH každý `held` nález upstream běhů téhož řetězu,
                      který nikdo nerozhodl (řetěz končí, lokálně nic nečeká)
```

**DISPATCH** = `runs.dispatch(project, run, finding)`:
1. Načte `pack.sink` (§3.4). Když chybí → nic, nález zůstane `candidate` (projekt bez boardu).
2. Spustí sink: `subprocess.run(shlex.split(template.format(id=finding_id, runDir=posix(run.dir))), cwd=project.root, env={**os.environ, "AGENCY_RUN": run.id}, capture_output=True, text=True, encoding="utf-8")`. Na Windows `shlex.split(…, posix=False)`? — **ne**: šablona je jednoduchá (`python path draft --finding {id} --run-dir {runDir}`), použij `shlex.split(template.format(...))` a cesty bez mezer; když cesta mezery má, sink skript ať si to ošetří. Timeout 120 s.
3. Čte JSON ze stdout: `ref = data.get("item") or data.get("ref")`, `url = data.get("url")`. Nenulový exit nebo nečitelný JSON = **selhání dispatch**: nález zůstane `candidate`, do `run.json` se přidá `dispatchErrors: [{id, error}]`, CLI vypíše řádek. Opakovaný `agency ingest --run <id>` dispatch zkusí znovu (sink je idempotentní přes marker).
4. Úspěch: `finding.state = "sent"`, `finding.sinks.githubProjectItem = ref`, zapíše `findings.json`, přidá do `decisions.jsonl` událost `{kind:"decision", findingId, state:"sent", by, ref, url, at}` a řádek do stopy.

### 3.4 Sink — vlastnost packu

`pack.json` dostane **dvanáctý klíč** `sink` (string | absent):

```json
"sink": "python .claude/skills/agency-po/scripts/backlog.py draft --finding {id} --run-dir {runDir}"
```

- Do všech čtyř `main-panel/.claude/skills/agency-*/pack.json` **stejný řádek** (všechny píší na tentýž board). Druhý projekt = jiný skript v jeho packu; jádro beze změny.
- Bez `sink` nálezy zůstávají `candidate` v gitu (`knowledge/`) — fallback „git soubory jako kanál". Uživatel nic nenastavuje.
- `packs.Pack.sink` (property, `str | None`), `agency packs --json` ho vrací, `agency doctor` kontroluje, že první token po `python` je existující soubor (fatal=False).
- **Vynucení „agent neobejde bránu":** (a) `needs` allowlist — na board umí zapsat jen sink skript; (b) skript loguje každý zápis do `RUN_DIR/backlog.jsonl` (už dnes); (c) `SKILL.md` každého packu: *findings go to `findings.json`; never create board items for a finding yourself.* Rozdíl: **nález** má kotvu a prochází branou; **rozhodnutí** PO (`comment`/`decide`/`promote`/`draft` nápadu) má podpis a dispozici. Obojí nechá stopu (nález ve `trail.jsonl`, rozhodnutí v `backlog.jsonl` → `decisions.md`).

### 3.5 `index.md` a `findings/<id>.md` = stopa, ne board

`knowledge._index_md` má sekce **jen tyto**, v tomto pořadí:

1. **Čeká v řetězu** — `held` z běžících/nedokončených řetězů (z `.agency/runs/`). Prázdná = sekce se nevypíše.
2. **Bez boardu** — `candidate` bez sinku (v main-panelu prázdná = nevypíše se).
3. **Stopa — co šlo na board** — `sent`, řádek: `[title](findings/<id>.md) · severity · where · found by · → [ref](url)` (bez url jen ref). **Žádný stav boardu** (Stav, closed, milestone) se nezobrazuje ani nenačítá.
4. **Nehlásit znovu** — `rejected` s důvodem a kým; `stale: true` (kotvený soubor v HEAD neexistuje) se **nevypisuje**, ale zůstává v dedupu.
5. **Vyřazeno branou** — `gated-out` s důvodem, sbalené na posledních 20 (informace, ne fronta).
6. **Pages** — beze změny.

Pryč: *Open — nobody has decided yet*, *Accepted*, *Deferred*. Frontmatter `findings/<id>.md`: `status` → `outcome` (`sent | rejected | gated-out | held | candidate`), `decision` pryč, `sinks` zůstává, přibývá `ref`/`url`. Sekce **Trail** v těle: `sent → PVTI_… (3. 9. 2026)`.

`knowledge.bundle()` **přestane mazat** `findings/<id>.md`, jejichž běh zmizel, pokud `id` je ve stopě — vyrenderuje je ze stopy (bez `body`/`evidence`, s poznámkou *„run directory no longer present; this is the trail record"*). Maže jen soubory, které nejsou ani v bězích, ani ve stopě.

### 3.6 Co se stane, když někdo sáhne na board online

| člověk online udělá | lokální stopa | příští běh |
|---|---|---|
| povýší draft na issue | beze změny — marker přežije v těle issue | dedup podle otisku: neposílá znovu; agent si může `gh issue view` živě a citovat #N |
| smaže draft | beze změny | neposílá znovu — smazání není „nahlas to znovu" |
| přepne `Stav` na Rejected | beze změny | neposílá znovu |
| zavře issue jako opravené | beze změny | QA dimenze `regression` se ptá živě; regrese cituje #N |
| přejmenuje pole na boardu | beze změny | sink spadne nahlas při příštím zápisu; nález zůstane `candidate`, `ingest --run` to zopakuje po opravě packu |
| založí ručně issue na tutéž chybu | lokál neví | agentův živý dedup (best effort); nejhůř jeden duplicitní draft, který člověk sloučí |

V žádném řádku není „aktualizuj repozitář".

---

## 4. Změny v jádru (`packages/core`)

### 4.1 `schemas/finding.v1.json`
- `state.enum` → `["candidate", "held", "sent", "rejected", "duplicate"]`; description: *Five states. `candidate` rests only where the pack has no sink; `held` waits for the next chain member; `sent` and `rejected` are terminal; a decision event in decisions.jsonl carries who and why.*
- `sinks` beze změny.

### 4.2 `schemas/run.v1.json`
- `counts` přidat `sent` (integer) a `held` (integer), oba volitelné.
- Nový volitelný `dispatchErrors`: array of `{id, error}`.

### 4.3 `packs.py`
- `Pack.sink` property: `str | None` = `manifest.get("sink")` stripnutý, prázdný → `None`.
- `cmd_packs` (cli.py) přidá `"sink": p.sink` do výstupu.
- `cmd_doctor`: pro každý pack se `sink`: token za `python` (nebo první token, když nezačíná `python`) → `project.root / token` musí existovat; jinak `check(f"pack {p.name} sink", False, "… not found", fatal=False)`.

### 4.4 `runs.py`
- Nové: `TRAIL = "trail.jsonl"`, `trail_path(project) -> Path` (= `project.agency_dir / "knowledge" / TRAIL`), `append_trail(project, row: dict) -> dict` (přidá `at`, zapíše řádek UTF-8 `\n`), `read_trail(project) -> dict[str, dict]` (poslední řádek na `id` vyhrává; chybný řádek se přeskočí).
- Nové: `dispatch(project, run, finding) -> dict` podle §3.3 (vrací `{"id", "ok", "ref", "url", "error"}`).
- `append_decision`: povolené `state` jen `sent | rejected` (+ volitelné `ref`, `url` v události). `deferred`/`accepted` už nikdo nezapisuje; **čtení** starých událostí zůstává funkční.
- `REJECT_REASONS` beze změny.

### 4.5 `ingest.py`
- `earlier_findings()`: pool = (nálezy z existujících starších běhů se `state in (None, "candidate", "held", "sent")`) ∪ (řádky stopy se `state in ("sent", "rejected")`, převedené na minimální dict s `id`, `fingerprint`, `title`, `anchor`, `state`). Bez duplicit podle `id` — běh má přednost.
- `ingest()` po `write_json(run.findings_path, kept)`:
  1. pro každé `dropped` → `append_trail(... state="gated-out", reason=d["reason"])`.
  2. `chain = rec.get("chain")`; `last = not chain or chain["position"] >= chain["of"]`.
  3. `if not last`: každý kept `candidate` → `state = "held"`.
  4. `if last`: pro každý kept `candidate` → `dispatch()`; navíc pro každý upstream běh (`chain["upstream"]` + rekurzivně jejich upstream) každý nález `held` bez rozhodnutí v `decisions(run)` → `dispatch()` s `note="not judged by the chain"` (sink dostane `--note`? **ne** — jednodušší: jádro to jen zapíše do stopy jako `by: "chain"`; tělo draftu je stejné).
  5. `rec["counts"]["sent"]`, `["held"]`, `rec["dispatchErrors"]` (jen když nějaké).
- `_bundle()` beze změny (bundle už umí stopu, §4.6).

### 4.6 `knowledge.py`
- `ledger(project)` / `_view()`: koncepty se skládají z běhů **a** ze stopy; pro `id` bez běhu vznikne koncept ze stopy (`body=None`, `evidence=[]`, `trailOnly=True`).
- `GROUPS` → podle §3.5 (klíče `held`, `candidate`, `sent`, `rejected`, `gated-out`).
- `_finding_md`: frontmatter `outcome`, `ref`, `url`; sekce **Trail**; pro `trailOnly` poznámka.
- `bundle()`: `removed` = jen soubory, jejichž `id` není ani v bězích, ani ve stopě.
- `for_run()`: `known-findings.json` = z `assemble()` jako dnes **plus** řádky stopy `sent`/`rejected` pro běhy, které už neexistují (aby agent na klonu dostal paměť).
- `_log_md` beze změny.

### 4.7 `cli.py`
- **Pryč:** `cmd_export`, parser `export`, import `export`; smazat `export.py`.
- `cmd_triage`: `action` ∈ `accept | reject` (**`defer` pryč** z parseru). `accept` = `runs.dispatch()`; při neúspěchu vrátí 1 a vypíše chybu, nález zůstane `candidate`/`held`. `reject` vyžaduje `--reason`. Oba přidají řádek do stopy. `--by` beze změny (agent posílá `hire:<pack>@<provider>`).
- `cmd_findings`: řádek `decision` → `state` nálezu (`sent | rejected | …`); přidat `ref`, `url` ze `sinks`/rozhodnutí; když `--all`, doplnit řádky ze stopy pro `id`, která nemají běh (`runId`, `id`, `title`, `severity`, `file`, `line`, `state`, `ref`, `url`, `trailOnly: true`; bez `anchor.resolve` když soubor chybí). Lidský výpis: značky `→` (sent), `✘` (rejected), `·` (jinak).
- `cmd_status`: do `project` přidat `"providers": providers.catalog()` (§6.1).
- `cmd_cleanup`: `--all` (§7).
- `_wait_for_agent` a `cmd_ingest`: nic navíc — dispatch je uvnitř `ingest.ingest()`. `_ingest_report` vypíše `sent`/`held`/`dispatchErrors`.
- Nápověda `agency --help`: skupina **decide** = `findings`, `triage`, `note`; `export` pryč.

### 4.8 `metrics.py`
- `verdicts`: `accepted` (staré záznamy) a `sent` se počítají jako přijaté; `deferred` jako nerozhodnuté; `rejected` beze změny. Precision = přijaté / (přijaté + odmítnuté) **jen z rozhodnutí, jejichž `by` začíná `hire:`** (rozhodnutí dalšího člena řetězu). Lidská rozhodnutí lokálně neexistují; `human` řádky ze starých dat se ignorují.

### 4.9 `providers.py`
- `catalog() -> list[dict]`: `[{"id", "title", "models", "defaultModel"}]` pro `known()`.

### 4.10 Testy jádra
- `test_gate.py`: (a) standalone běh bez sinku → kept zůstane `candidate`, stopa nic; (b) standalone běh se sinkem (pack manifest `sink: "python sink.py {id}"`, kde `sink.py` je fixture v tmp, která vytiskne `{"item":"PVTI_X"}`) → `state == "sent"`, `sinks.githubProjectItem == "PVTI_X"`, řádek ve stopě; (c) sink vrátí exit 1 → `candidate`, `dispatchErrors` má 1 záznam, druhý `ingest` to zopakuje; (d) řetěz `position 1/2` → `held`; `position 2/2` → dispatch vlastních i upstream `held` bez rozhodnutí.
- `test_decisions.py`: `triage accept` = dispatch; `triage reject` vyžaduje reason; `defer` je `SystemExit`/argparse chyba; staré `accepted` v `decisions.jsonl` se čtou.
- `test_ledger.py`: **obrátit** `test_a_discarded_run_disappears_from_the_ledger_too` → *a discarded run stays in the ledger through the trail* (soubor existuje, obsahuje `trail record`); `index.md` nemá řetězec `Open — nobody`; má `Stopa`.
- Nový `test_trail.py`: append/read (poslední vyhrává, vadný řádek se přeskočí); `earlier_findings` bere `sent`/`rejected` ze stopy a **ne** `gated-out`; `for_run` přidá stopu do `known-findings.json`.
- `test_anchor_metrics.py`: precision jen z `hire:*`.
- Nový `test_cleanup.py` (§7) a test `status --json` má `providers` (§6.1).
- Nikde v testech se nespouští reálný `python` sink přes `gh` — fixture skript je lokální soubor.

---

## 5. Změny v packu (`main-panel/.claude/skills/agency-*/`)

### 5.1 `agency-po/scripts/backlog.py`
- `draft` dostane alternativu k `--title/--body-file`: `--finding <id>` (vzájemně výlučné). S `--finding`:
  1. najde nález: `RUN_DIR/findings.json` (z `--run-dir`), jinak `.agency/runs/*/findings.json`, jinak řádek `.agency/knowledge/trail.jsonl` (`id`); nenajde → `BacklogError`.
  2. `key = f"finding:{id.lower()}"` (marker regex je lowercase: `[a-z0-9][a-z0-9._@:-]{0,120}`); `Board.by_key(key)` → když existuje, vrátí `{"action":"exists","item":…}` (idempotence, i po povýšení na issue — marker je v těle).
  3. tělo (česky, jak píše agent; skript jen skládá): `title` jako nadpis, `severity · dimension · pack`, **Kde:** `file:line @ commit[:8]` (+ symbol), **Tvrzení:** `body`, **Evidence:** odrážky `kind — detail (source)`, prázdný řádek, `compose(body, key, run_id)` doplní podpis a marker `<!-- agency:po:finding:<id> -->`. Přidej druhý marker `<!-- agency:finding:<ID> -->` (velká písmena, tvar z `export.py` — ať jde dohledat i mimo tento skript).
  4. `gh project item-create` jako dnes; pak nastaví `Stav` na `New` — použij stejný helper, kterým `cmd_decide` nastavuje `Stav` (přečti `cmd_decide`, `backlog.py:385-438`); když pole/hodnota neexistuje, zaloguj `warning` do výsledku, nepadej.
  5. výsledek `{"action":"created","kind":"draft","key":key,"item":"PVTI_…","finding":id}` → `append(run_dir, …)`; stdout = JSON (jak dnes `main()`).
- `--dry-run` vrátí `would-create` s celým tělem.
- `snapshot` beze změny.

### 5.2 `pack.json` ×4
- Přidat `sink` podle §3.4. Zkontroluj, že `packs/` v `veriflow-agency` (referenční kopie) dostane totéž.

### 5.3 `SKILL.md` ×4
- Odstavec **Findings go to the board through the core** (anglicky): *Write findings to `RUN_DIR/findings.json`. Do not create board items, PR comments or issues for a finding yourself — `agency ingest` sends what passes the gate through `backlog.py draft --finding`. In a chain, judge the upstream findings with `agency triage accept <id>` (it goes to the board) or `agency triage reject <id> --reason <r>` (it is remembered, never reported again). There is no `defer`: what you do not reject goes to the board when the chain ends.*
- `agency-po/SKILL.md`: rozdíl nález × rozhodnutí (§3.4 poslední odrážka). Krok „zapiš do `decisions.md`" zůstává.
- `agency-review-graph/SKILL.md`: PR komentář zůstává agentův (`gh pr comment` v `needs`), ale odkazuje na nálezy `id`, nezakládá nic na boardu.

---

## 6. Změny v extension (`packages/extension`)

Jeden průchod, tři věci: Findings bez voleb, presety, Clear all. Verze `0.7.0`.

### 6.1 Findings = mapa nálezů na kód, bez rozhodování
- `views.js` `FindingsTree.roots()`: skupiny **On the board** (`state === 'sent'`, description `→ ref`, řazení drift *untouched* první), **In a chain** (`held`), **Waiting — no board here** (`candidate`; v main-panelu prázdná), **Not reported again** (`rejected`, description `reason`), **Duplicates** (sbalené). `findingNode`: `contextValue` vždy `agencyFinding` (žádné `.open`/`.decided`); ikona podle severity; tooltip s `→ ref` a `by`.
- `OverviewTree`: řádek **Decision queue** pryč. **Precision** zůstává, tooltip: *judged by the next specialist in a chain — human verdicts live on the board and are not read.*
- `state.js`: `queue()` pryč (a všechna volání).
- `extension.js`: pryč `agency.finding.accept`, `.defer`, `.reject.*`, `.rejectPick`, `.decision.apply`, funkce `decide()`. Zůstává `open`, `reveal`, `openAtCommit`, `diffAgainstHead`, `addNote`. Nový `agency.finding.openOnBoard` (otevře `url`, když je; jinak zkopíruje `ref` do schránky a řekne to).
- `panel.js`: tlačítka Accept/Defer/Reject a `REASONS` pryč; místo nich řádek **Outcome:** `→ ref (url jako odkaz)` / `rejected — reason (by)` / `held` / `candidate`.
- `threads.js`: hlavička vlákna `→ #ref` místo značek rozhodnutí; `thread.state = Resolved` když `sent` nebo `rejected`.
- `package.json`: pryč všechny `agency.finding.accept|defer|reject.*|rejectPick|decision.apply` (commands, commandPalette, view/item/context, comments/commentThread/title) a submenu `agency.rejectMenu`; přidat `agency.finding.openOnBoard` (inline `$(link-external)` na `viewItem == agencyFinding`).
- `cli.js`: `triage()` pryč; `note()` zůstává.

### 6.2 Presety spuštění (náhrada za starý „hire", bez registru)
- **Kde žijí:** VS Code setting `agency.presets` (workspace), `type: array`, položka `{pack, provider, model?, label?}`. Jádro o nich neví — preset je jen `agency run <pack> --provider X --model Y` vyslovený předem. Žádný `.agency/*.json`.
- Nový `src/presets.js`: `all()`, `forPack(name)`, `label(p)` (= `label || model || provider`), `same(a,b)`, `add(p)` (bez duplicit; vrací bool), `remove(p)`; zápis přes `getConfiguration('agency').update('presets', list, ConfigurationTarget.Workspace)`.
- `views.js` `ToolsTree`: pod řádkem packu **napřed** řádky presetů (`presetNode`: label = `label(p)`, description = `provider · model`, `iconId: 'rocket'`, `contextValue: 'agencyPreset'`, na uzlu `_preset` a `_pack`), pak dosavadní `packChildren`.
- `review.js`: `runOverWorkspace(cwd, pack, log, extra = {})` → `runEach(…, { ...extra, prompt })`; `launch()` název terminálu doplní ` · provider/model`.
- `extension.js`: `runOneOverPr(pack, extra = {})`; příkazy `agency.preset.run` (uzel → `{provider, model}` → stejná větev jako `agency.pack.run`), `agency.preset.add` (z řádku packu nebo z titulku pohledu: pack → runner z `state.snapshot.project.providers` (fallback `claude`/`codex`) → model: *provider's default* / `models[]` / *another model…* input → `presets.add` → `state.emitter.fire()`), `agency.preset.remove` (kontextové menu na presetu).
- `package.json`: `configuration.properties["agency.presets"]`; commands `agency.preset.add` (`$(add)`, v paletě), `agency.preset.run` (`$(play)`, skryté), `agency.preset.remove` (`$(trash)`, skryté); `view/title`: `agency.preset.add` na `view == agency.tools`; `view/item/context`: `agency.preset.run` inline na `agencyPreset`, `agency.preset.remove` `9_remove` na `agencyPreset`, `agency.preset.add` `1_preset` na `agencyPack`.
- Řetěz (`pickAndChain`) presety zatím nepoužívá — `--provider` pro celý tým je další krok, ne tenhle.

### 6.3 Clear all v Runs
- `package.json`: `agency.runs.clearAll` („Discard all finished runs…", `$(clear-all)`), `view/title` na `view == agency.runs`, `navigation@5`.
- `extension.js`: modal — *Discard every finished run? (N listed here.) Their records, evidence and F finding(s) are deleted from `.agency/runs/`; the committed trail in `.agency/knowledge/` keeps what went to the board and what was rejected. Runs still marked running are left alone.* → `cli.cleanup(cwd, { all: true, discard: true, force: true })` → `refresh()`.
- `cli.js` `cleanup()`: flag `all`.

### 6.4 Testy extension (`test/harness.js`)
- Fake `vscode`: `getConfiguration` vrací objekt s mutable `settings` (`get(k, d)`, `update(k, v)`), `ConfigurationTarget: {Global: 1, Workspace: 2}`, `env.clipboard.writeText`, `env.openExternal`.
- Přepsat testy na řádcích ~247 (`['To decide','Decided','Duplicates']` → nové skupiny), ~275 (Overview bez *Decision queue*), package.json testy: `agency.finding.accept` **není** contributed; `agency.finding.openOnBoard` inline na `agencyFinding`; `agency.runs.clearAll` ve `view/title` pro `agency.runs`; `agency.preset.run` inline na `agencyPreset`; starý seznam (`agency.hire.*` atd.) zůstává **nepřítomný**.
- Nové: preset řádky pod packem (`forPack`), `agency.preset.run` předá `provider`/`model` do `cli.run` (stub zachytí opts), `presets.add` odmítne duplicitu.

---

## 7. `agency cleanup --all`

- Parser `cleanup`: `--all` — *every finished run; only with --discard*.
- `cmd_cleanup`: `--all` bez `--discard` → `SystemExit("--all only goes with --discard. To close runs whose terminal is gone, use --unfinished.")`. Cíle = běhy se `status != "running"`. Bez `--force` se běh s rozhodnutími **přeskočí** (ne chyba) a vrátí se v `skipped: [{run, decisions}]`; s `--force` jde pryč taky. JSON: `{"closed": [...], "skipped": [...], "unfinished": n}`; lidsky: `N run(s) discarded — F findings went with them` + `M kept, they carry decisions: … — --force takes those too`.
- Stopa se **nemaže** nikdy (§3.2) — proto je Clear all bezpečné.

---

## 8. Kroky (pořadí závazné, každý = testy zelené + commit)

| # | krok | soubory | hotovo, když |
|---|---|---|---|
| 1 | **Stopa + schéma + brána** | `runs.py` (trail, dispatch), `ingest.py`, `finding.v1.json`, `run.v1.json`, `packs.py` (sink), `providers.catalog`, `test_trail.py`, `test_gate.py` | testy §4.10 (a)–(d) zelené; `agency validate` nad fixture během prochází |
| 2 | **CLI**: triage/findings/status/doctor/cleanup, `export` pryč | `cli.py`, smazat `export.py`, `test_decisions.py`, `test_cleanup.py` | `agency --help` nemá `export`; `triage defer` = chyba; `status --json` má `providers`; `cleanup --all` testy |
| 3 | **Paměť**: index/ledger ze stopy, bundle nemaže | `knowledge.py`, `test_ledger.py`, `metrics.py`, `test_anchor_metrics.py` | obrácený ledger test; `index.md` bez *Open*; precision jen `hire:*` |
| 4 | **Pack**: `backlog.py draft --finding`, `sink` ×4, `SKILL.md` ×4, kopie v `packs/` | main-panel skills, `veriflow-agency/packs/` | `python backlog.py draft --finding <id> --dry-run --run-dir <fixture>` vytiskne tělo s oběma markery (bez `gh`); `agency packs --json` má `sink` u všech čtyř; `agency doctor` zelený |
| 5 | **Extension**: §6.1–6.4, VSIX 0.7.0 | `packages/extension/**` | harness zelený; `npm run package` vytvoří `dist/veriflow-agency-0.7.0.vsix`; `code --install-extension … --force` |
| 6 | **Docs** | `README.md` (W1 bez `export`; „what passes the gate is on the board"; presety; Clear all), `product-brief.md` pravidlo 2 (draft v Inboxu je výstupní schránka brány — D-0008; issue/komentář pořád vyžaduje člověka nebo podepsané rozhodnutí PO), `tasks.md` Fáze 11 | — |
| 7 | **Přejímka (uživatel)** | — | viz níže |

**Přejímka:** `agency run review-graph --pr N --wait` → draft na boardu s markerem, `Stav: New`. Draft **online** povýšit na issue, na repo nesáhnout. Znovu `agency run review-graph --pr N --force --wait` → **0 nových draftů**; `git status` v main-panelu ukáže jen nový řádek v `trail.jsonl` z prvního běhu, nic z druhého. Pak v extension: preset `Reviewer · codex` přidat, spustit z řádku, smazat; **Clear all** smaže testovací běhy a `index.md` pořád ukazuje oba nálezy pod *Stopa*. To je celý test: *povýšeno online, nic k commitu; smazáno lokálně, stopa zůstala.*

**Hotovo, když:** projde přejímka; `grep -rn "accepted\|deferred\|published" packages/core/src/agency schemas/` vrátí jen zpětnou kompatibilitu v `metrics.py`/`runs.decisions`; `export.py` neexistuje; `grep -rn "finding.accept\|rejectPick\|Decision queue" packages/extension/src` vrátí nulu; `~/.agency` neexistuje; `pwsh scripts/test.ps1` zelené.

---

## 9. Co se vědomě nedělá

- **Žádná synchronizace** oběma směry. Ani jedním — lokál nikdy nečte board kvůli sobě.
- **Žádná cache stavu boardu** v repu. Ani „naposledy viděno".
- **Žádný flag** `findings: on/off`. Kanál je vlastnost packu (`sink` ano/ne).
- **Dedup nečte board.** Jen stopu a běhy. Agentův živý dedup je best effort navíc.
- **Odmítnuté nálezy nejdou na board.** To je jediná paměť, kterou board nemá mít.
- **Presety nezná jádro.** Jsou to VS Code settings; terminálový uživatel má flagy.
- **Řetěz s presety** — až bude potřeba (`--provider` pro tým).
- **`agency findings` na klonu bez běhů** ukáže jen řádky ze stopy (bez těla) — stačí; tělo je v `findings/<id>.md`.
