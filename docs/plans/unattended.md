# Neattended běh — řetěz, který doběhne sám a něco po něm zbyde

**Datum:** 2026-09-02
**Navazuje na:** [`teams.md`](teams.md) (Kroky 2–4 a 6 jsou hotové; tenhle plán je to, co se ukázalo, když řetěz poprvé běžel doopravdy), [`shared-memory.md`](shared-memory.md)
**Řeší:** `agency chain` se po 12e882d hne sám — ale jeho členové nesmějí nic zapsat, brána to zapíše jako „nic nenašel", orchestrátor to nevidí a product owner soudí jiný pull request, než recenzent recenzoval. Výsledek řetězu je dnes prázdný a záznam o tom lže.
**Pořadí prací napříč plány:** [`tasks.md`](tasks.md) → Fáze 8

---

## 1. Co se stalo 2. 9. 2026

Tři pokusy o tentýž řetěz `review-graph@claude → po@claude` nad PR #479 v projektu `Chci-na-lekci/main-panel`. Ověřeno v `.agency/runs/`, v transkriptech sezení (`~/.claude/projects/…/*.jsonl`) a proti GitHubu — ne z paměti.

| čas (UTC) | co | jak dopadlo | důkaz |
|---|---|---|---|
| 07:13 | řetěz `01M1GF7E…`, ještě před `-p` | krok 1 doběhl, krok 2 (`01M1GFF5…`) spouštěl uživatel ručně; dodnes je `running` a jeho `chain` blok má klíč `handoff: null`, který `run.v1` nezná | `runs/01M1GFF5…/run.json` |
| 08:21 | řetěz `01M1GKB5…`, krok 1 attended přes `--wait` | 586 s, `findings.json` = `[]`, **`handoff.md` 120 řádků** s hotovou produktovou analýzou; status `no-findings` | `runs/01M1GKB6…/handoff.md` |
| 08:36 | uživatel napsal do sezení recenzenta *„Send this to the PO agent to continue the chain"* | recenzent **sám spustil** `agency run po@claude --pr 479 --latest-merged --prompt "…" --wait` ze svého PowerShell nástroje, na pozadí | transkript `1d7eb2e0…`, 08:40:59 a 08:42:28 |
| 08:42 | běh PO `01M1GMHE…` — vnořený `claude` bez terminálu | 473 s, exit 0, **každý Write i Bash(`gh`, `agency`) odmítnut**; analýza zůstala jen ve stdout. Záznam říká `attended: true`, `no-findings`, `credential: subscription`. Recenzent pak text ručně opsal do `summary.md` cizího běhu | `runs/01M1GMHE…/summary.md`, první odstavec |
| 08:57 | řetěz `01M1GNCG…` po 12e882d — krok 1 v `claude -p` | 11 min 40 s. `git diff`, `ls`, `grep` prošly (read-only). **Odmítnuto:** `node -e`, `npx vitest`, `code-review-graph query` (2×), Write `findings.json` (5×), Bash přesměrování, `Set-Content`, Edit `run.json`. Agent našel **jeden nález** (mrtvá větev v `platformIdentity.ts:107-109`) a vypsal ho do terminálu. Exit 0 → brána → `no-findings` → **krok 2 se spustil** | transkript `0c2461b3…`, 08:59–09:08 |
| 09:09 | krok 2 `01M1GP29…`, PO v `claude -p` | 8 min 39 s, totéž odmítání. **Soudil PR #474**, ne #479: `target` je `workspace`, `fix/453-demand-cta-anchor @ 4ee1c26e` — to je hlava PR #474 (*fix(453): CTA poptávky míří na kotvu formuláře*), kterou má uživatel checkoutnutou. Odpověděl na produktovou otázku o CTA kotvě, ne o IČO. `no-findings`, „chain finished — 2 runs" | `gh pr view 474`, `runs/01M1GP29…/run.json` |

Uživatel to viděl takhle: *„launching claude… Ctrl-C stops the run"* a pak dvanáct minut nic. Popsal to jako „zaseklé nebo neinteraktivní". Není to ani jedno: `claude -p` pracuje, ale tiskne až úplně na konci, a mezitím mu systém odmítá jeden zápis za druhým. Z venku se to od zaseknutí nedá odlišit — a to je chyba orchestrátoru, ne uživatele.

Dva reálné nálezy (recenzentova mrtvá větev, PO-ova prázdná roadmapa v `po.json`) dnes existují jen ve scrollbacku terminálu. Nástroj, jehož smyslem je paměť, o nich neví.

## 2. Diagnóza — sedm příčin, ne jedna

**A. Autonomie bez autorizace.** `-p` udělá z agenta neinteraktivní proces, ale permission model zůstává „zeptej se" — a není koho. Jádro agentovi *cestu* dá (`--add-dir .agency`), ale *právo* do ní zapsat ne. Ověřeno sondou (§7): výchozí `-p` odmítne Write i do adresáře z `--add-dir`; `--permission-mode acceptEdits` ho povolí; cestou omezené pravidlo `Write(//C:/…/**)` na Windows **nefunguje**; `Bash(<prefix> *)` funguje.

**B. Brána nerozliší „nenašel nic" od „nemohl zapsat".** `ingest` čte chybějící `findings.json` jako `[]`, zapíše `[]` zpátky na disk a označí běh `no-findings` — tvrzení „díval se a nic nenašel". `_wait_for_agent` vrací 0, když agent skončil nulou, ať zapsal cokoli. Řetěz proto pokračuje na člena, který soudí nálezy, jež nevznikly — přesně to, čemu měl §3.5 v `teams.md` zabránit.

**C. Orchestrátor je slepý.** `proc.attend` zdědí stdio a čeká na exit code. Neví, kolik tahů agent udělal, co mu bylo odmítnuto, kolik to stálo, ani jestli ještě pracuje. `claude -p --output-format json` přitom vrací `permission_denials[]`, `num_turns`, `total_cost_usd`, `duration_ms`, `session_id` a `usage` (ověřeno, §7) — a `stream-json` totéž průběžně. Nikdo to nečte.

**D. Řetěz nemá vlastní cíl.** `--pr 479` doputuje jen k packu s `target: pull-request`. Packy s `target: workspace` (po, legal, qa) v témže řetězu soudí **pracovní kopii uživatele** — dnes třikrát po sobě větev `fix/453-demand-cta-anchor`, tedy PR #474. Dva členové, dva různé pull requesty, jeden `chain.id`. Uživatel si toho všiml z textu odpovědi („testoval 474 CTA"); záznam mu to neřekl.

**E. Handoff se řeže na 40 řádků.** Recenzentův `handoff.md` z 08:21 má 120 řádků a sekce *„Doporučení pro PO agenta"* — jediná adresná část — je na konci. PO dostal do promptu rekapitulaci zadání a technický popis PR, plus „… (80 more lines in the file)" bez cesty k souboru (ta je jen v `context.json`).

**F. Běh smí spouštět běhy.** Nic nebrání agentovi zavolat `agency run` zevnitř běhu. Recenzent to udělal poslušně, protože zadání znělo „pomocí PO agenta zjisti…". Vznikl běh bez vlastníka, bez terminálu a bez oprávnění, a záznam o něm tvrdí `attended: true`.

**G. Záznam lže na třech místech.** `trigger.attended` popisuje úmysl volajícího, ne fakt (vnořený běh bez TTY je `attended: true`); `cost.credential` se odvozuje z `attended`, takže neattended běh dostane `api-key`, ačkoli `claude -p` jede na tomtéž předplatném; `status: no-findings` u agenta, kterému byl zápis odmítnut.

## 3. Co se dnes opravilo — a proč to nestačilo

Devět commitů z 1.–2. 9., každý opravil to, co bylo vidět. Společný vzor: **ověřovalo se, že se agent spustí, ne že něco zapsal.**

| commit | co opravil | co neviděl |
|---|---|---|
| `8186673` | `--add-dir` je variadický a spolkl poziční prompt — agent startoval s prázdným zadáním; oddělovač `--` | běh „doběhl" i bez promptu, protože brána bere chybějící výstup jako `no-findings` (B) |
| `49e883b` | `--add-dir` dostával jen RUN_DIR, `context.json` posílal jinam — dotazy na svolení | cesta bez práva zápisu (A) |
| `12e882d` | řetěz se nehnul, `claude` startuje interaktivně a nekončí — `unattendedPrefix: ["-p"]`; `--focus` per člen; `record_block` kvůli `run.v1` | `-p` bez autorizace odmítá všechno (A); orchestrátor nečte výsledek (C) |
| `d926430` | extension posílala jeden `--prompt` všem — per člen `--focus` | — |
| `0abae18`, `539759b` | řetěz se neptal na PR; nešel zahodit z panelu | cíl stále patří členům, ne řetězu (D) |
| `291a092` | odvozený pracovník `legal`, který nešel vyhodit | — |
| `585ff9a` | `agency chain`, handoff, `evidence/upstream.json` | strop 40 řádků (E), vnořené běhy (F) |

Bod, ze kterého všechno ostatní plyne: `teams.md` Krok 2 slíbil *„spustit agenta a vědět, kdy skončil"*. Exit code je „kdy". Tenhle plán dodává „jak dopadl" — a bez něj je řetěz smyčka, která umí spustit dva prázdné běhy za sebou a nahlásit úspěch.

---

## 4. Tvarová rozhodnutí

**1. Autorizace je vlastnost metody, ne přepínač uživatele.** Pack ví, co jeho metoda dělá: zapisuje do RUN_DIR, volá `agency triage|note`, ptá se grafu, čte `git`/`gh`, pouští testy. Tohle patří do manifestu (`run.needs`), jádro to překládá na tvar konkrétního providera (`providers.py` zůstává data, ne kód). Bypass (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`) zůstává **opt-in projektu** — uživatel o něj výslovně stál a má na něj právo, ale nikdy není výchozí: worktree je na jedno použití, stroj ne.

**2. Jedna autorizace, dva režimy.** Attended `--wait` i neattended člen řetězu dostanou tentýž seznam povolení. Liší se jen tím, jestli se agent smí zeptat na zbytek (attended) nebo je zbytek odmítnut (neattended). Díky tomu se attended běh ptá míň — a neattended běh neumí nic, co by attended neuměl bez otázky.

**3. Orchestrátor čte proud událostí, ne exit code.** Neattended člen běží s výstupem v JSONL (`claude -p --output-format stream-json --verbose`, `codex exec --json`); jádro ho parsuje, kreslí průběh (jedna řádka na nástroj), ukládá celý proud do `RUN_DIR/agent.jsonl` a poslední zprávu agenta do `RUN_DIR/agent.md`. Do záznamu jde `agent.turns`, `agent.denied`, `agent.sessionId`, `cost.usd`, tokeny. Attended `--wait` zůstává s děděným stdio — tam agent mluví s člověkem a roura by mu to vzala.

**4. Chybějící výstup je selhání, ne prázdný výsledek.** `findings.json`, který agent nezapsal, brána **nevyrábí**. Běh je `failed` s `exitReason: "no-output"` a s počtem odmítnutých volání; řetěz na něm stojí. `no-findings` zůstává vyhrazené pro `[]`, které napsal agent.

**5. Cíl patří řetězu.** `agency chain --pr N` vyřeší cíl jednou, postaví jeden worktree na hlavě PR a všichni členové pracují v něm, se stejným `target` v záznamu. Bez `--pr` sdílí všichni pracovní kopii a jeden `headRefOid`. Pack, který potřebuje živou aplikaci (qa), zůstane v pracovní kopii i v PR řetězu — cíl v záznamu má přesto řetězový.

**6. Běh je list.** Proces agenta dostane `AGENCY_RUN=<id>`; `agency run` a `agency chain` s touhle proměnnou odmítnou start. Kdo chce dalšího specialistu, sestaví řetěz — to je rozhodnutí člověka (§3.3 `teams.md`), ne agenta, který splnil větu ze zadání.

**7. Handoff jde celý.** Strop je v bajtech a velkorysý; cesta k souboru je v promptu vždycky. Řádkový strop stavěl na tom, že vykopávací věta má být krátká — jenže handoff není vykopávací věta, je to zadání.

---

## 5. Kroky

### Krok 1 — autorizace neattended běhu (~půl dne)

**`providers.py`** — tvar spuštění dostane nové řádky dat (názvy jsou návrh; tvar je podstatný):

| pole | claude | codex | k čemu |
|---|---|---|---|
| `unattendedPrefix` | `["-p"]` | `["exec"]` | už je |
| `editsGrant` | `["--permission-mode", "acceptEdits"]` | `["--sandbox", "workspace-write"]` | zápis do pracovního adresáře a do `--add-dir` bez otázky |
| `allowFlag` / `allowShape` | `--allowedTools` / `Bash({cmd} *)` | `-c` / `sandbox_permissions…` **(ověřit)** | povolené příkazy |
| `streamArgs` | `["--output-format", "stream-json", "--verbose"]` | `["--json"]` | Krok 3 |
| `lastMessageFlag` | — (je v proudu) | `-o <file>` | `agent.md` |
| `bypassArgs` | `["--dangerously-skip-permissions"]` | `["--dangerously-bypass-approvals-and-sandbox"]` | jen opt-in |

Codex: `--add-dir` je v `codex exec` *zapisovatelný* adresář vedle workspace (nápověda 0.144.3), takže `dirFlag: "--add-dir"` se doplní i codexu. `workspace-write` má vypnutou síť — `gh` selže, dokud se nenastaví `-c sandbox_workspace_write.network_access=true`; jestli to stačí, se musí ověřit sondou stejně jako u claude, ne odvodit.

**Manifest packu** — `run.needs`: seznam příkazů, které metoda volá. Návrh pro dnešní packy:

```
review-graph: agency triage, agency note, code-review-graph, git, gh pr view, gh pr diff, gh issue view, npx vitest, npm test
po:           agency triage, agency note, git, gh issue view, gh issue list, gh project, gh api graphql   (+ gh issue edit/comment jen když writes.* povoluje)
legal:        agency triage, agency note, git, gh issue view
qa:           agency triage, agency note, git, npm run, npx playwright, curl
```

Projekt může seznam **rozšířit** (`agent.allow` v `.agency/<pack>.json`, tam, kde dnes bydlí `extraArgs`), nikdy ne zúžit. `agency *` jako celek nikdy — viz Krok 5.

**`launch_argv`** — pořadí: `bin → unattendedPrefix → --model → editsGrant → allow… → extraArgs → streamArgs → --add-dir → -- → prompt`. `--allowedTools` je variadický stejně jako `--add-dir`, takže musí stát před jinou volbou, ne před promptem; dnešní pořadí (extraArgs před dirFlag) to už drží.

**Bypass** — `agent.unattended: "bypass"` v konfiguraci packu → `bypassArgs` místo `editsGrant` + allow. `agency doctor` to hlásí jako varování s cestou k souboru, ne jako chybu.

**Testy** — `launch_argv` pro každý provider a režim (attended/unattended/bypass) proti zafixovanému argv; `run.needs` neznámé pole → chyba při `packs.load`.

> **Hotovo, když:** `agency run review-graph@claude --pr N --wait` v attended režimu se neptá na Write do RUN_DIR ani na `agency triage`; člen řetězu má v `agent.denied` nulu; `agency doctor` u packu vypíše, s čím agenta pouští.

### Krok 2 — brána rozliší „nic" od „nic nemohl" (~2 h)

- `ingest`: `findings.json` chybí a `findings.raw.json` chybí → **nezapisovat `[]`**, vrátit `{"noOutput": true}`; `_wait_for_agent` na to zavolá `runs.failed(run, "no-output")` a vrátí 1, i když exit code byl 0.
- `runs.failed` zapíše `agent.denied` (Krok 3 ho dodá; do té doby `null`).
- `cmd_chain`: krok s návratem ≠ 0 řetěz zastaví — to už platí; nově se to spustí i pro exit 0 bez výstupu.
- `run.v1`: `exitReason` je volný string — `"no-output"` je konvence, ne enum.
- Extension: `failed` ikonu má; tooltip doplní `exitReason`.

> **Hotovo, když:** běh, jehož agent nezapsal `findings.json`, je `failed` s `exitReason: no-output`, na disku není vyrobené `[]`, a `agency chain` se na něm zastaví s hlášením, kolik volání bylo odmítnuto.

### Krok 3 — orchestrátor, který agenta vidí (~1 den)

- `proc.stream(argv, cwd, on_event)`: subprocess se `stdout=PIPE` (utf-8, `errors="replace"`), **`stdin=DEVNULL`** (claude jinak tři vteřiny čeká na stdin — vidět v sondě), stderr děděné. Řádek = událost.
- Dva dialekty jako data v provideru (`streamDialect`): `claude-stream-json` (`system/init` → `session_id`; `assistant` s bloky `tool_use`; `user` s `tool_result`; `result` s `permission_denials`, `num_turns`, `total_cost_usd`, `usage`) a `codex-jsonl` (`item.*`, `turn.completed`). Parser je malý modul `events.py`; neznámá událost se zaloguje a ignoruje.
- Průběh v terminálu: `· Read src/shared/billing/ico.ts`, `· Bash git diff 8d3ba5d…`, `✗ Write findings.json — denied`, na konci `✓ 41 turns · 12m 03s · $0.84 · 0 denied`. Text agenta se netiskne průběžně — poslední zpráva jde do `RUN_DIR/agent.md` (to je místo, kde dnes analýzy obou členů zmizely), celý proud do `RUN_DIR/agent.jsonl`.
- Záznam: `agent.sessionId`, `agent.turns`, `agent.denied: {count, tools: [...]}`; `cost.usd`, `cost.inputTokens`, `cost.outputTokens` (v `run.v1` jsou, nikdy se nevyplňovaly). Schéma: `agent` i `cost` mají zavřený seznam klíčů — **rozšířit napřed, jinak čtvrtá past téhož druhu.**
- Strop času: `agent.maxMinutes` v konfiguraci packu (výchozí žádný); po jeho uplynutí `terminate` → `failed: timeout`. Rozpočet v dolarech se nedělá — na předplatném je `total_cost_usd` odhad, ne účet.
- Ctrl-C: zabít dítě, `abandon`, jako dnes.
- Attended `--wait` a `--launch` beze změny.

**Co se u tohohle kroku nepovedlo napoprvé:** `streamArgs` skončily v tabulce
providera a **nikdo je nepřidal na příkazovou řádku**. `streamDialect` se četl
zvlášť v místě spuštění, takže orchestrátor parsoval proud, o který nikdy
nepožádal — `claude -p` běžel v textovém režimu, dvacet minut mlčel a pak vypsal
jeden blok prózy, který parser neuměl přečíst. `agent.jsonl` zůstal prázdný,
`turns`/`usd`/`denied` null. Testy to nechytily, protože podstrkávaly JSONL rovnou
parseru: ověřovaly překladač, ne to, že se o překlad vůbec požádá.

Oprava má dvě části a druhá je ta důležitá: `providers.streaming()` vrací **flagy
i dialekt jedním voláním**, takže „mám dialekt, ale neposlal jsem flagy" je stav,
který nejde vyrobit. Plus test, který kouká do argv, ne do parseru.

**Reasoning se tiskne taky.** První verze ho schválně skrývala, aby výstup zůstal
čistý — špatný kompromis: seznam nástrojů řekne, čeho se agent dotkl, nikdy ne co
se snaží udělat. Bloky `thinking` chodí v proudu živě (ověřeno sondou: první
v 4,8 s, tool_use v 5,1 s), tisknou se zkrácené na tři řádky a celé zůstávají
v `agent.jsonl`.

> **Hotovo, když:** člen řetězu v terminálu ukazuje, co agent právě dělá; po doběhnutí je v `run.json` počet tahů, odmítnutí a cena; `RUN_DIR/agent.md` obsahuje poslední zprávu agenta; `tests/test_events.py` parsuje zaznamenaný proud obou dialektů (fixtury z reálného běhu, ne vymyšlené).

### Krok 4 — cíl patří řetězu (~půl dne)

- `cmd_chain` vyřeší cíl **jednou** (`resolve_target` s `--pr`, jinak `resolve_workspace_target`) a předá ho členům v `chain["target"]`; `cmd_run` s chainem cíl neřeší znovu.
- PR řetěz: jeden worktree na hlavě PR, pojmenovaný po řetězu (`…-chain-<id>`), postavený před krokem 1 a předaný všem; `worktree: true` packy v něm pracují místo vlastního, `worktree: false` packy v něm pracují, pokud nemají `run.needsWorkingCopy: true` (dostane ho jen qa). Graf se aktualizuje jednou.
- Záznamy všech členů mají stejný `target` (`kind`, `pr`, `headRefOid`, `baseRefOid`) a stejný `worktree`; `worktreeOwned` → vlastník je řetěz: po úspěšném doběhnutí se worktree odstraní (`--keep-worktree` ho nechá), po zastavení zůstane.
- `collect_workspace_evidence` dostane rozsah `baseRefOid..headRefOid` z cíle místo `--since`.
- Marker `already-reviewed` zůstává per hire; `--force` platí pro celý řetěz.

> **Hotovo, když:** `agency chain review-graph@claude po@claude --pr 479` má v obou záznamech `target.pr = 479` a jeden společný `worktree`; po doběhnutí worktree neexistuje; `agency validate` je čistý. Dnešní chyba — PO soudí #474, protože je checkoutnutý — se nedá zopakovat.

### Krok 5 — předání celé, prompt bez lží, běh jako list (~2 h)

- `handoff_text`: celý soubor do 16 KB; nad strop hlava + „the rest is in <absolutní cesta>". Cesta k `handoff.md` upstream běhu i k `evidence/upstream.json` je v promptu vždy.
- `step_prompt` při nule upstream nálezů neříká „First judge those findings"; říká, že upstream nic nenahlásil a jeho handoff je zadání — otázky v něm se zodpoví v `findings.json` (dimenze packu) nebo v `summary.md`.
- `AGENCY_RUN=<id>` a `AGENCY_CHAIN=<id>` v prostředí agenta (`proc.attend` i `proc.stream`); `cmd_run`/`cmd_chain` s nastavenou proměnnou skončí: *„This is run <id>'s agent. A run does not start runs — write findings.json and handoff.md, the chain continues on its own."* Věta o tom i do `step_prompt` a do SKILL.md všech packů.
- Testy: `per_member` už je; přidat `handoff_text` nad 40 řádků, prompt při 0 nálezech, guard přes `monkeypatch.setenv`.

### Krok 6 — záznam, který nelže, a zpráva řetězu (~2 h)

- `trigger.attended` = fakt o procesu: `sys.stdin.isatty()` a ne unattended. Vnořený běh guard z Kroku 5 znemožní, ale záznam se má odvozovat z toho, co je, ne z toho, co by mělo být.
- `cost.credential`: z prostředí providera (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` → `api-key`, jinak `subscription`), ne z `attended`.
- `_chain_report`: na člena stav, `kept` nálezů, odmítnutí, cena, čas — a soubory, které po něm zbyly (`summary.md`, `handoff.md`, `agent.md`). Návratový kód `agency chain` ≠ 0, když kterýkoli krok selhal.
- `agency validate --fix`: z `chain` bloku odstraní klíče mimo `run.v1` (dnešní `01M1GFF5…`), zombie `running` starší než den nabídne k `abandon`.

### Krok 7 — extension (~2 h)

- Uzel řetězu: krok `failed` červeně, tooltip s `exitReason` a počtem odmítnutí. Průběh v terminálu přijde z Kroku 3 zadarmo.
- Uzel běhu: „Open summary / handoff / agent's last message".
- „Rerun this step" až po prvním reálném použití; dnes stačí `agency chain` znovu.

### Krok 8 — přejímka na reálném řetězu (protokol, ~1 h běhu)

Není to krok kódu, je to kontrola, která dnešním opravám chyběla. Nad `main-panel`:

```
agency chain review-graph@claude po@claude --pr 479 --force \
  --focus review-graph@claude:"projdi PR technicky" \
  --focus po@claude:"dává tahle změna produktový smysl, nebo je to práce pro práci?"
```

Prošlo, když **všechno** platí:

1. oba `findings.json` napsal agent (`findings.raw.json` existuje u obou, i když je `[]`),
2. `agent.denied.count = 0` u obou,
3. `target.pr = 479` u obou, jeden společný `worktree`, po doběhnutí odstraněný,
4. `prompt.txt` kroku 2 obsahuje celý `handoff.md` kroku 1,
5. zpráva řetězu ukazuje tahy, čas a cenu obou kroků,
6. `agency validate` je čistý,
7. `RUN_DIR/agent.md` kroku 2 obsahuje odpověď na produktovou otázku — a když PO otázku zodpověděl jako nález, je v `findings.json` s dimenzí `value` nebo `scope`.

Druhý reálný případ (`legal → po` nad VOP) je spouštěč Kroku 5 v `teams.md` (steering). Do té doby se steering nedělá.

---

## 6. Co se vědomě nedělá

- **Bypass jako výchozí.** `acceptEdits` + seznam příkazů pokrývá, co metoda dělá; bypass pokrývá, co metoda dělat nemá. Uživatel ho může zapnout, nástroj ho nezapíná.
- **LLM koordinátor, který dělí společné zadání mezi členy.** Vrací se otázka z 2. 9. (*„měl by tam být koordinátor, který globální prompt rozdělí"*). Odpověď zůstává: dělení je rozhodnutí, a rozhodnutí bez záznamu tenhle nástroj nedělá. `--focus` per člen je deterministická odpověď; extension se na něj ptá po členech. Jediné, co koordinátor přidává, je pohodlí jednoho textového pole — a to nestojí za třetí model, jehož úsudek nikde nebydlí.
- **Automatické opakování odmítnutého kroku.** Odmítnutí není náhoda, je to chybějící právo. Oprava je v Kroku 1, ne ve smyčce.
- **Rozpočet v dolarech jako strop.** Na předplatném je `total_cost_usd` odhad. Strop je čas.
- **Message bus, živý chat, paralelní fan-out** — viz `teams.md` §5, nic se nemění.

---

## 7. Ověřeno sondou 2. 9. 2026

`claude` 2.1.258, `codex-cli` 0.144.3, Windows 11. Sondy běžely v prázdném git repu ve scratchpadu, model haiku, `--output-format json`; cílový adresář byl mimo pracovní adresář a předaný přes `--add-dir`.

| spuštění | Write do `--add-dir` | `permission_denials` | exit |
|---|---|---|---|
| `-p` (výchozí) | **odmítnut** | `[{"tool_name":"Write",…}]` | 0 |
| `-p --permission-mode acceptEdits` | zapsáno | `[]` | 0 |
| `-p --allowedTools "Write(//C:/…/out/**)" "Edit(//C:/…/out/**)"` | **odmítnut** | Write | 0 |
| `-p --permission-mode acceptEdits --allowedTools "Bash(git status *)"` + `echo > file` přes bash | `git status` prošel, `echo >` odmítnut | Bash | 0 |

Z reálného transkriptu (`-p` bez povolení): `git diff`, `ls`, `grep`, `find`, `printf | wc` prošly bez otázky (read-only klasifikace); `node -e`, `npx vitest`, `code-review-graph query`, přesměrování výstupu, `Set-Content`, Write, Edit odmítnuty. Prefix `PYTHONIOENCODING=utf-8 code-review-graph …` je pro pravidlo jiný příkaz než `code-review-graph …` — SKILL.md má agentovi říct, ať proměnné nepředřazuje.

Výsledný JSON `claude -p` má klíče: `type, subtype, is_error, num_turns, duration_ms, duration_api_ms, total_cost_usd, usage, modelUsage, permission_denials, session_id, result, stop_reason, …`. `is_error` je `false` i při odmítnutí — signál je jen v `permission_denials`.

Bez stdin (roura bez dat) claude tři vteřiny čeká a varuje; `DEVNULL` to řeší.

**Proud teče průběžně** — ověřeno druhou sondou (`-p --output-format stream-json
--verbose`, haiku, úkol se čtením adresáře):

| čas | událost |
|---|---|
| 1,8 s | `system` (init, `session_id`) |
| 4,8 s | `assistant` · blocks=**thinking** |
| 5,1 s | `assistant` · blocks=**tool_use** |
| 6,6 s | `user` (tool_result) |
| 7,8 s | `assistant` · thinking, pak text |
| 8,4 s | `result` — `num_turns`, `total_cost_usd`, `permission_denials` |

Tedy: reasoning i volání nástrojů jsou k dispozici **živě**, kdežto odmítnutí až
v závěrečném `result`. Počet odmítnutých volání se proto ukáže na konci kroku, ne
během něj — to není chyba orchestrátoru, tak to claude posílá.

---

## 8. Souhrn rozsahu

| krok | rozsah | čeká na |
|---|---|---|
| 1 — autorizace neattended běhu | ~půl dne | nic |
| 2 — brána rozliší „nic" od „nic nemohl" | ~2 h | nic |
| 3 — orchestrátor čte proud událostí | ~1 den | 1 |
| 4 — cíl patří řetězu | ~půl dne | nic |
| 5 — handoff celý, prompt, běh jako list | ~2 h | nic |
| 6 — pravdivý záznam, zpráva řetězu, `validate --fix` | ~2 h | 3 |
| 7 — extension | ~2 h | 2, 3 |
| 8 — přejímka na reálném řetězu | ~1 h běhu | 1–6 |

Kroky 1 + 2 + 4 + 5 jsou **něco přes den** a stačí na to, aby řetěz doběhl s výstupem, nad správným PR a bez lži v záznamu. Krok 3 je den navíc a je to rozdíl mezi „řetěz funguje" a „řetěz je vidět" — bez něj se každá další chyba bude zase hledat v transkriptech `~/.claude/projects`.
