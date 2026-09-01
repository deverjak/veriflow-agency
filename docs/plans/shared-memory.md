# Sdílená paměť specialistů — napříč běhy, packy a providery

**Datum:** 2026-09-01
**Navazuje na:** [`graph-abstraction.md`](graph-abstraction.md) §5 (OKF pro sdílenou paměť — tenhle dokument ho rozpracovává a přebírá), [`../implementation-plan-v0.md`](../implementation-plan-v0.md) §2 (pravda v repu), [`teams.md`](teams.md) (Krok 1 je společný pro oba plány)
**Řeší:** paměť specialistů (PO, QA, legal, reviewer), která přežívá běhy, patří projektu, a čte se z libovolného provideru — claude dnes, codex zítra, cokoli dalšího pozítří.
**Pořadí prací napříč plány:** [`tasks.md`](tasks.md)

---

## 1. Tři vrstvy paměti — a která z nich je náš problém

Slovo „paměť“ tady znamená tři různé věci a plán stojí na tom, že se nesmíchají:

| vrstva | čí je | příklad | co s ní tenhle plán dělá |
|---|---|---|---|
| **paměť harnessu** | uživatele | claude-mem, Claude Code Auto Memory | **nic** — je osobní, necommituje se, patří člověku, ne projektu |
| **paměť projektu** | projektu, commituje se | `.agency/runs/`, budoucí `.agency/knowledge/` | **jádro plánu** — Kroky 1–4 |
| **sémantický recall** | odvozený index, kdykoli přestavitelný | Hindsight banka, `agency.db` | **volitelný adaptér** — Krok 5, experiment |

Stejné pravidlo, jaké už platí pro `agency.db` ([`implementation-plan-v0.md`](../implementation-plan-v0.md) §2): co se nedá přestavět z repa, nesmí bydlet jen v cizí databázi.

### Co je špatně dnes

1. **Paměť není věc, je to projekce do běhu.** `known_memory()` ([`runs.py:480`](../../packages/core/src/agency/runs.py)) vyrábí `known-findings.json` se stropem 300 položek ([`runs.py:525`](../../packages/core/src/agency/runs.py)), znovu do každého RUN_DIRu. Strop tiše zapomíná, nikdo paměť nevlastní, mimo běh k ní není přístup. (Rozbor v [`graph-abstraction.md`](graph-abstraction.md) §5.1.)
2. **Znalost packu nemá domov.** PO drží „u monetizace preferujeme Free jako growth engine“ nanejvýš jako větu v `brief.default`; QA „payment state machine je dlouhodobě nejrizikovější“ nedrží vůbec. Roadmapa se mrazí per-run ([`runs.py:596`](../../packages/core/src/agency/runs.py)) — to je správně pro přezkoumatelnost rozhodnutí, ale není to paměť, je to snapshot vstupu.
3. **Bez Agency běhu paměť neexistuje.** Obyčejná Claude Code session v repu (nebo kolega bez extension) nevidí nic z toho, co specialisté za měsíce nasbírali.
4. **Atribuce se slévá.** „codex to našel“, „claude to nezávisle potvrdil“, „člověk to schválil“ jsou dnes jeden string `decision` + `by: "cli"`. Rozdíl mezi „jeden model si to myslí“ a „dva modely a člověk se shodli“ je přitom nejcennější vstup pro další běh — a přesně ten signál by mohl vážit `dedup.py`.

---

## 2. Co je na trhu (ověřeno 1. 9. 2026)

Webový průzkum s ověřením proti dokumentaci a registrům; vstupní přehled (LLM výstup) se potvrdil jen zčásti, korekce jsou v tabulce.

| nástroj | co to je | orchestrátor-API (ne jen MCP) | Windows | verdikt pro nás |
|---|---|---|---|---|
| **Hindsight** (Vectorize) | OSS (MIT) agent memory: banky, retain/recall/reflect, knowledge pages; plugin `@vectorize-io/hindsight-coding-agents` instaluje hooky do Claude Code, Codex CLI, Cursor CLI, Grok Build ad.; výchozí banka `coding-agent::{gitProject}` — jedno repo = jedna banka napříč harnessy | **ano** — REST + `hindsight-client` (Python), lokální daemon bez účtu (`--server daemon`), embedded režim | podporované (x86_64, wheels) | **kandidát na Krok 5** — jediný s čistým orchestrátor-API a sdílenou per-repo bankou |
| **claude-mem** | plugin Claude Code (hooks + MCP search), lokální SQLite; installer detekuje i Cursor/Windsurf/OpenCode/Codex/Antigravity, ale dokumentované jsou jen OpenCode/Antigravity — Codex manifest v repu existuje, hloubka nedoložená | ne — jen in-session MCP | běží (ověřeno lokálně) | zůstává **vrstvou harnessu** uživatele; pro paměť packů nepoužitelný (bez API) |
| **Cognee** | OSS memory engine s knowledge graphem; MCP server (`remember`/`recall`/`forget`); default plně lokální | ano — Python knihovna in-process; vyžaduje LLM klíč pro extrakci | ano | zajímavý, až bude potřeba graf přes zdroje mimo repo (Slack, docs) — teď ne |
| **Mem0 / OpenMemory** | SDK `mem0ai` (lokálně Qdrant + OpenAI klíč) nebo cloud platforma; Claude Code integrace je **cloud plugin**; OpenMemory = lokální Docker stack, nástroje `add_memories`/`search_memory`/… (vstupní přehled měl jména i harness-trojici špatně) | ano (SDK) | ano | cloud plugin porušuje self-hosted princip; SDK by šlo, ale nepřináší nic nad Hindsight |
| **GBrain** | OSS (Garry Tan), 7 memory verbs, brain = markdown v git repu + PGLite; CLI i MCP | ano (CLI) | funkční, ale druhá liga (Bun) | filozoficky nejblíž (markdown v repu!), ale Bun závislost a mladé Windows — sledovat, nestavět na tom |

**Závěr průzkumu:** žádný z nástrojů nedává to, co repo-filozofie vyžaduje jako základ — **commitovanou paměť projektu čitelnou bez nástroje a bez účtu**. Zároveň Hindsight potvrzuje, že vrstva sémantického recallu nad ní má smysl a nemusí se stavět vlastní: lokální daemon, žádný cloud, Python klient přímo z jádra. Proto: **bundle vlastníme, recall adaptujeme.**

Proč je „adresář markdownu v repu“ správný základ pro cross-provider paměť, je vyargumentované v [`graph-abstraction.md`](graph-abstraction.md) §5.2: roster už dnes míchá runtimy, které Agency neovládá, a formát čitelný bez SDK je jediný, který obslouží všechny — OKF (v0.2) k tomu přidává hotová pole `provenance`/`trust`/`freshness`/`lifecycle`.

---

## 3. Kroky

### Krok 1 — společný základ (s [`teams.md`](teams.md); ~1 den) {#krok-1}

Týž krok jako Krok 1 plánu týmů — dělá se jednou, tady je plná specifikace. Tři části:

**a) Strukturovaná identita `by`.** Formát: `hire:<id>` (agent — id z rosteru, agent ho má v `context.json.hire`), `human` (člověk; volitelně `human:<jméno>`). Dnešní hodnoty `cli` / `extension` se při čtení mapují na `human` — historie se nepřepisuje. Dotčená místa: `append_decision`/`append_note` ([`runs.py:804`](../../packages/core/src/agency/runs.py)) validace tvaru, `agency triage`/`note` (`--by`, [`cli.py:1905,1930`](../../packages/core/src/agency/cli.py)), zápis z extension, instrukce v SKILL.md packů, které triagují.

**b) `RUN_DIR/summary.md` jako výstup běhu.** Pack na konci běhu zapíše krátké shrnutí (~do 30 řádků): co zkoumal, co našel (počty + to podstatné), co rozhodl, co doporučuje dál. Kontrakt v SKILL.md; `ingest` jen zaznamená přítomnost do run recordu. Konzumenti: handoff v chainu (teams Krok 3), chronologie `log.md` (Krok 3 zde), retain adaptéru (Krok 5). Nálezová data to nenahrazuje — `findings.json` zůstává jediný strukturovaný výstup.

**c) `knowledge.py` — jediné místo skládání „co projekt ví“.** Nový modul; `known_memory()` se stává jeho konzumentem (výstupní soubory `known-findings.json`/`known-specs.json` beze změny — žádný pack se nerozbije). Náčrt:

```
assemble(project)            úplný, atribuovaný obraz: nálezy + rozhodnutí
                             + poznámky + spec soubory, napříč běhy
for_run(project, run)        dnešní projekce do běhu (strop zůstává — je to pozadí)
upstream(project, run_ids)   plný výběr bez stropu — zadání pro chain
bundle(project)              zápis .agency/knowledge/ — Kroky 2–4
```

> **Kontrola hotovosti:** rozhodnutí agenta nese `hire:<id>`, běh po sobě nechává `summary.md`, a `runs.py` už paměť neskládá — jen volá `knowledge.py`.

### Krok 2 — pravidla jako koncepty: `.agency/knowledge/rules/` (~1 den)

Nejmenší sousto, převzaté z [`graph-abstraction.md`](graph-abstraction.md) §5.4: projektová pravidla (`review.rules` dnes ukazuje do sekce cizího markdownu) jako OKF koncepty — `type: Rule`, `status`, `stale_after`, `verified`. Dimenze `repo-rules` dostane strukturovaný vstup, doctor umí říct „5 pravidel, 1 po expiraci“. Malé, ohraničené, a vynutí si první reálné rozhodnutí o tvaru frontmatteru.

### Krok 3 — ledger nálezů: `.agency/knowledge/findings/` (~1–2 dny)

Jádro z [`graph-abstraction.md`](graph-abstraction.md) §5.1–5.3: `bundle()` generuje z běhů adresář konceptů — `findings/<id>.md` s `generated`/`verified`/`status`/`stale_after`, `index.md`, `log.md` (chronologie ze `summary.md` běhů). Klíčové vlastnosti:

- **Bundle je odvozený, pravda zůstává v `.agency/runs/`** — přestavitelný kdykoli, stejný statut jako `agency.db`. Zapisuje ho `ingest` (po bráně) a jde přegenerovat příkazem.
- **`verified` tiery vznikají z atribuce Kroku 1**: `hire:review-graph@codex` našel → `hire:review-graph@claude` potvrdil (dedup match napříč hiry) → `human` přijal. Tohle je místo, kde se identita zaplatí.
- Čtenářem je kdokoli: specialista v běhu (odkaz z `context.json`), obyčejná session v repu, kolega v editoru. Žádný nástroj není potřeba — to je celá pointa formátu.

### Krok 4 — knowledge pages packů: `.agency/knowledge/pages/<pack>/` (~1 den)

To, co Hindsight řeší „knowledge pages“ a co dnes nemá domov (§1 bod 2): kurátorovaná znalost packu, psaná agentem, vlastněná projektem.

- PO: `product-decisions.md`, `roadmap-context.md` · QA: `weak-areas.md`, `test-lore.md` · legal: `obligations-map.md`.
- SKILL.md dostane pravidlo: na konci běhu aktualizuj svoje stránky — **závěry, ne log**; co přestalo platit, smaž nebo označ `deprecated`. Příprava běhu stránky packu přibalí do kontextu.
- v1 jen pro packy s `worktree: false` (po, qa, legal — běží v projektu a můžou psát přímo). Reviewer běží ve worktree na jiné hlavičce; jeho zápis stránek musí jít přes RUN_DIR a aplikovat se při `ingest` — až v druhé vlně, ať v1 nestojí na nejsložitějším případu.

### Krok 5 — Hindsight jako recall adaptér (experiment, ~1 den + vyhodnocení; **za flagem**)

Bundle dává strukturu a přenositelnost, ale ne sémantické „najdi relevantní“ přes stovky konceptů. To se nestaví — adaptuje se (stejné pravidlo jako u grafu: engine nestavíme, [`implementation-plan-v0.md`](../implementation-plan-v0.md) §3.1).

- **Režim výhradně lokální daemon** (`--server daemon`, bez účtu, bez cloudu). Banka `coding-agent::{gitProject}` — táž, kterou plní harness pluginy, takže interaktivní session a `agency` běh sdílejí paměť.
- Zapojení v jádru přes `hindsight-client`, dvě místa kolem `agency run --wait` (teams Krok 2): **recall** před spuštěním → `evidence/recall.json` (zaznamenaný vstup, ne volná magie), **retain** po `ingest` → `summary.md` + přijaté nálezy.
- Volitelně navíc harness hooky (`npx @vectorize-io/hindsight-coding-agents install claude-code` / `codex` — Codex vyžaduje `codex_hooks = true` v `~/.codex/config.toml`; zda hooky střílí i pod `codex exec`, není doložené — ověřit empiricky, stejně jako unixové log cesty na Windows). **Hooky nezávisejí na ničem z tohoto plánu** — dají se nainstalovat a vyhodnotit kdykoli, klidně souběžně s Krokem 1; na Krocích z plánů závisí jen orchestrátorová část (recall/retain kolem `--wait`).
- **Kill criteria:** po ~10 bězích se změří, jestli recall přinesl něco, co bundle nedal (nález/rozhodnutí, ke kterému by se běh jinak nedostal). Když ne, adaptér se vypne a zůstane bundle. Flag v konfiguraci packu, výchozí vypnuto.

---

## 4. Co se vědomě nedělá

- **Žádné cloudové paměťové účty.** Mem0 platform plugin, Hindsight Cloud, claude-mem sign-in sync — všechno proti principu self-hosted single-user. Lokální daemon je hranice.
- **claude-mem se nepřebírá pro packy.** Je to paměť harnessu (vrstva 1, osobní) a nemá orchestrátor-API. Zůstává, k čemu je.
- **Nestaví se vlastní embeddings/sémantické hledání.** Od toho je adaptér v Kroku 5 — a když neobstojí, je odpovědí „bundle stačí“, ne vlastní engine.
- **Cognee/GBrain/Mem0-SDK jako jádro ne.** LLM-klíč v extrakci, Bun na Windows, respektive nic navíc proti Hindsightu. GBrain (markdown v git repu) sledovat — filozoficky je nejblíž a konverguje k témuž závěru jako §5.2.
- **Paměť není databáze ticketů.** Backlog má zdroj pravdy na GitHubu a per-run snapshoty ([`runs.py:596`](../../packages/core/src/agency/runs.py)); do knowledge patří „proč jsme se tak rozhodli“, ne kopie fronty.
- **Nečeká se na OKF v1.0.** Spec je v0.2 a sám se prohlašuje za nehotový; pole se mapují dnes a případné přejmenování ve v0.3 je mechanická migrace nad odvozeným (přestavitelným) bundlem.

---

## 5. Souhrn rozsahu

| krok | rozsah | kdy |
|---|---|---|
| 1 — identita `by` + `summary.md` + `knowledge.py` | ~1 den | první; **společný s [`teams.md`](teams.md)** |
| 2 — `rules/` koncepty | ~1 den | po 1 |
| 3 — `findings/` ledger + `index.md` + `log.md` | ~1–2 dny | po 2 |
| 4 — knowledge pages packů | ~1 den | po 3 |
| 5 — Hindsight recall adaptér (za flagem) | ~1 den + vyhodnocení | harness hooky **kdykoli** (nezávislé); orchestrátorová část po 3 + `--wait` z teams Kroku 2 |

Kroky 1–4 jsou **~4 dny** a dávají paměť, která patří projektu, commituje se, a čte ji každý provider i holá session bez Agency. Krok 5 je ohraničený experiment s kill criteria — přidá recall, ne závislost.
