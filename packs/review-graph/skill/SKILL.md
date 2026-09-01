---
name: agency-review-graph
description: "Use when asked to review a GitHub pull request — open or already merged — with graph-backed evidence and record the result durably. Triggered by `agency run review-graph`, which prepares a disposable worktree, refreshes the code-review-graph index against the PR's head commit and writes a context bundle; this skill then reviews across dimensions, filters false positives, and writes findings.json. Also usable directly: 'review PR #12 with agency', 'retrospective audit of the last merged PR'. Not for an uncommitted local diff with no PR — use the built-in `code-review` skill for that."
---

# Graph-augmented PR review

Recenze pull requestu s **doloženými** nálezy. Strukturální signál, který samotný diff nedá — blast radius, dotčené uložené flows, chybějící testy na úrovni funkcí — pochází z `code-review-graph`.

**Výstupem není komentář. Výstupem je `findings.json`.** Komentář na PR i položka v GitHub Projectu jsou z něj odvozené a volitelné. Když sink selže nebo je vypnutý, nález se neztratí — to je celý důvod, proč tenhle pack existuje.

## Co dostáváš hotové

`agency run review-graph` už udělalo deterministickou část a vyrobilo běhový adresář. **Nedělej ji znovu.** Přečti si:

```
<RUN_DIR>/context.json     konfigurace projektu, metadata PR, seznam souborů k recenzi
<RUN_DIR>/evidence/        grafový signál — detect-changes, impact, dead-code, graph-capabilities
<RUN_DIR>/run.json         záznam běhu, který na konci doplníš
```

`context.json` nese mimo jiné:

| Klíč | Význam |
|---|---|
| `worktree` | absolutní cesta k jednorázovému worktree na hlavičce PR — **čti soubory odtud**, ne z pracovní kopie uživatele |
| `target.kind` | `pull-request` (otevřený) nebo `merged-pull-request` (retrospektivní audit) |
| `target.headRefOid` / `baseRefOid` | přesné commity, proti kterým se recenzuje |
| `files[]` | soubory po odfiltrování lockfilů, generovaných a snapshotů |
| `review.dimensions` | které dimenze pustit |
| `review.rules` / `review.docMap` | odkazy do dokumentace projektu, nebo `null` |
| `review.verifyCommand` | co dělá CI — **k zahazování nálezů, ne ke spouštění** |
| `review.minScore` / `review.language` | práh a jazyk výstupu |
| `brief.standing` / `brief.focus` | volitelné zadání od člověka — na co se u téhle recenze zaměřit. `focus` platí pro tenhle běh, `standing` pro projekt pořád. |
| `by` | čím se podepsat pod rozhodnutí o nálezu (`agency triage … --by <by>`). Hotové z jádra — neskládej ho sám. |

Když `context.json` chybí, běžíš mimo `agency run`. Řekni to uživateli a nabídni `agency run review-graph --pr <n>` — deterministickou přípravu ručně nesimuluj, je to zdroj tichých chyb.

## 1. Načti kontext projektu

- Pokud `review.docMap` není `null`, otevři tu sekci a podle ní přečti **jen** dokumentaci odpovídající dotčeným cestám. Nečti dokumentaci, která se změn netýká.
- Pokud `review.rules` není `null`, přečti tu sekci celou — je to vstup dimenze `repo-rules`.
- Pro každý soubor z `files[]` čti **celý obsah z worktree**, ne jen hunky z `gh pr diff`. Worktree má úplný soubor po změně, takže není důvod uvažovat z osekaného kontextu.

## 2. Recenze po dimenzích, paralelně

Pusť dimenze z `review.dimensions` jako **paralelní čerstvé agenty**. Nemají kontext téhle konverzace, takže každému předej: diff, seznam souborů s cestami do worktree, odpovídající výřez grafového signálu z `evidence/` a výňatky dokumentace z kroku 1.

| Dimenze | Na co se dívá | Čím ji nakrmit |
|---|---|---|
| `correctness` | Logické chyby, rozbitá volající místa, změny kontraktu | `evidence/impact.json`, `evidence/detect-changes.json` |
| `tests` | Jestli testy v PR skutečně pokrývají změněné chování | `evidence/detect-changes.json` → `test_gaps[]`, `code-review-graph query tests_for <symbol> --repo <worktree>` |
| `reuse` | Duplicitní read modely napříč vrstvami, nově mrtvý kód, zbytečná abstrakce | `evidence/dead-code.json` |
| `errors` | Spolknuté chyby, chybějící `await`, neidempotentní handlery | diff |
| `repo-rules` | Pravidla z `review.rules` — **obsah je projektový, ne packový** | sekce z `review.rules` |

Když `brief.focus` nebo `brief.standing` není `null`, **projdi zadanou oblast první a důkladněji.** Zadání mění pořadí a hloubku, ne pravidla: nález mimo zadání se nezahazuje a nález bez evidence neprojde bránou ani tehdy, když si ho zadání výslovně přeje.

`repo-rules` se pouští **jen když `review.rules` není `null`.** Bez projektových pravidel běží čtyři dimenze z pěti a je to legitimní výstup, ne selhání — neuváděj to jako chybu.

Než dimenze cokoli označí za podezřelé, **ověř to dotazem do grafu**:

```bash
agency graph locate "<name>" --repo <worktree>
agency graph neighbors <name> --direction in --repo <worktree>
agency graph tests-for <name> --repo <worktree>
```

To je přesně ta věc, která z dohadu dělá doložitelný nález.

Ptej se přes `agency graph`, ne přímo nástrojem: odpověď je JSON s cestami relativními k repu (přímý nástroj vrací na Windows absolutní OS-native cesty, které se pak nespárují s POSIX cestami z `gh`), a `evidence.source` pak přežije výměnu grafového nástroje.

> **Co driver neumí, se nedokládá.** `evidence/graph-capabilities.json` říká, na které otázky tenhle driver odpovídá. Chybí-li `tests-for` nebo `unreferenced`, dimenze, která na nich stojí, se **přeskočí a napíše se to do `exitReason`** — nedohaduje se z diffu. Chybějící schopnost je legitimní výsledek, vymyšlený nález ne.

## 3. Deterministická brána — dřív než filtr kvality

Zahoď každý nález, který nemá **obojí**:

1. `file` + `line` uvnitř souboru z `files[]`
2. aspoň jednu položku `evidence` — grafový fakt, pravidlo z dokumentace, chybějící test, nebo obsah diffu

Není to úsudek, je to schéma: `finding.v1` takový nález nezvaliduje. Počet zahozených zapiš do `run.json` → `counts.gated`. Nález bez evidence není přísnější nález, je to nález, který nejde ověřit ani zpětně dohledat.

## 4. Filtr falešných pozitivů

Ze zbylých zahoď to, co je:

- **předchozí stav**, ne zavedený tímhle diffem — ověř hranicemi hunků nebo `git blame` ve worktree
- **chytá to CI** — `review.verifyCommand` dělá typecheck/lint/testy/build, nederivuj to znovu
- **vědomě umlčené** — lint-ignore komentář, zdokumentovaná výjimka
- **hnidopišství bez opory** v pravidlech projektu nebo v grafu
- **na řádku, kterého se PR nedotkl**

Co přežije, oskóruj 0–100 a ponech `>= review.minScore`. **Nula nálezů je platný výsledek**, ne selhání běhu.

## 5. Zapiš `findings.json`

Tohle je jediný povinný výstup. Do `<RUN_DIR>/findings.json` zapiš pole objektů podle `finding.v1`:

```jsonc
{
  "id": "<ULID>",
  "runId": "<z run.json>",
  "pack": "review-graph@0.1.0",
  "dimension": "correctness",
  "severity": "high",
  "title": "Jednovětné tvrzení, co je špatně",
  "body": "Markdown: tvrzení + konkrétní scénář selhání — vstupy/stav → špatný výstup.",
  "anchor": {
    "file": "src/foo.ts",          // POSIX, relativní ke kořeni projektu. NIKDY absolutní.
    "line": 142,
    "endLine": 158,
    "commit": "<plných 40 znaků headRefOid>",
    "snippet": "<text bloku 142..158 z worktree>",
    "symbol": { "name": "UserService.getUser", "range": [128, 171] },
    "body": "<tělo symbolu, strop 8 kB>"
  },
  "evidence": [
    { "kind": "graph", "detail": "3 volající v d=1, 0 testů", "source": "agency graph impact --depth 2" }
  ],
  "score": 92,
  "state": "candidate"
}
```

Ke kotvě, protože na ní stojí použitelnost nálezu za měsíc:

- **`commit` je plných 40 znaků.** Zkrácený SHA může později tiše ukázat na jiný řádek.
- **`snippet` je celý blok `line..endLine`,** ne jeden řádek. Jednořádkový snippet selže na `/**`, `}` a podobné boilerplatě — a docblock začíná přesně tím.
- **`symbol` vyplň z grafu,** ne odhadem: `agency graph locate "<name>" --repo <worktree>` vrátí `file`, `line` a `endLine`. Je to jediná vrstva kotvy, která přežije refaktor.
- **`anchor.body`** je záchranná síť pro případ, že commit v klonu už nebude — squash-merge se smazanou větví je na GitHubu default.

Doplň `run.json`: `status`, `finishedAt`, `counts` a `cost` (provider, model, počet dimenzí, doba běhu).

A napiš `<RUN_DIR>/summary.md` — **nejvýš 30 řádků** vlastními slovy: s jakým zadáním jsi běžel, co jsi zkoumal, co jsi našel (počty a to podstatné, ne výpis nálezů), co jsi rozhodl a co doporučuješ dál. Čte to člověk, chronologie paměti projektu a další specialista, který na tenhle běh naváže. `findings.json` to nenahrazuje ani nekopíruje — strukturovaná data jsou tam, tohle jsou tvoje slova.

## 6. Odvozené sinky — až po zápisu

Až teď, a jen když je v konfiguraci zapnuto:

**`sinks.prComment`** — jeden souhrnný komentář, prosa v jazyce z `review.language`, bez emoji, plných 40 znaků SHA v každém odkazu. Marker pro idempotenci vezmi **hotový z `context.json` (`prCommentMarker`)**, neskládej ho sám:

```
<!-- agency:review-graph:<hire>:<headRefOid> -->
```

Nese jméno specialisty, protože nad jedním PR můžou pracovat dva — recenzent na sonnetu a recenzent na codexu. Sdílený marker by znamenal, že první z nich druhého z toho commitu vyzamkne. Kdyby si marker skládal skill sám, byla by pravidla na dvou místech a `agency run` by přestalo poznat vlastní značku.

Před postnutím zkontroluj, jestli komentář s tímtéž markerem už na PR není — tentýž commit tímtéž specialistou se nerecenzuje dvakrát. Posílej přes soubor (`gh pr comment <n> --body-file <tmp>`), ne inline `-b`, kvůli diakritice.

Když v komentáři píšeš, kdo recenzi dělal, ber to z `context.json` → `hire.label`. Dva komentáře od dvou specialistů nad týmž PR jsou zamýšlený stav; dva nerozlišitelné komentáře nejsou.

U `merged-pull-request` se komentář **defaultně neposílá** — retrospektivní audit starého PR nikdo nečte a jen zašumí historii. Pošli ho jen na výslovné vyžádání.

**`sinks.githubProject`** — jednosměrný export. Zpětný sync se nedělá; kdyby někdo změnil stav přímo v Projectu, další export ho přepíše, a to je zamýšlené.

## 7. Úklid

Worktree odstraní `agency run` samo, i když běh spadne. Nemaž ho ručně — CLI si o něm vede záznam a potřebuje ho ještě k výpočtu kotev.
