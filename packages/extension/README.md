# Agency — VS Code extension

Klient nad příkazem `agency`. Sám o sobě neumí nic: všechnu práci dělá jádro,
extension ji jen zobrazuje a zadává. Ta hranice je záměr, ne provizorium —
díky ní může tutéž věc udělat člověk klikem, ty v terminálu i agent, a všichni
tři píšou do stejného místa.

## Co je v panelu

Ikona **Agency** v activity baru, čtyři stromy podle otázek, které si kladeš
v tomhle pořadí:

| Pohled | Odpovídá na |
|---|---|
| **Přehled** | Co se tu děje a je to v pořádku? Předpoklady, poslední běh, fronta, precision. |
| **Nálezy** | Co ode mě čeká rozhodnutí? Fronta, rozhodnuté, duplicity. |
| **Běhy** | Co proběhlo a jak to dopadlo? |
| **Specialisté** | Koho si můžu najmout a na co se dívá? |

Detail nálezu se otevírá **jako tab v editoru**, ne v panelu — tvrzení,
evidence, kotva, historie a tlačítka rozhodnutí se do 300 px nevejdou.

U specialisty, který zadání bere, je v **Specialistech** uzel **Brief**: trvalé
zadání projektu a uložené scénáře. Klik ho změní — a protože bydlí v konfiguraci
projektu, platí pak i pro běh z terminálu a pro agenta.

Uzel **Browser** otevře nastavení prohlížeče: jestli sezení jede přes Playwright,
kam se ukládají reprodukční specy a co se smí založit v projektu, když Playwright
zatím nemá. Je to jediné místo v Agency, kde se nastavení mění formulářem — a i to
se ukládá přes `agency config`, do konfigurace projektu.

Nálezy jsou navíc **inline komentáře u řádku kódu** (panel *Comments*). To je
jediná věc, kterou desktopová aplikace fyzicky neumí, a hlavní důvod, proč UI
Agency žije tady.

## Celý průchod

1. **Zrecenzovat pull request…** — vybereš PR (otevřený i mergnutý; u mergnutého
   se udělá retrospektivní audit). CLI připraví worktree, graf a evidenci a
   spustí agenta ve **viditelném terminálu**.
   Nebo **Spustit QA sezení…** — místo výběru PR se zeptá na zadání: uložený
   scénář, nebo nový text. Na co se pack ptá, říká jeho manifest, ne jméno
   packu; kdyby extension větvila podle jména, byl by každý další specialista
   zásahem do klienta.
2. Agent dopíše `findings.json` a skončí.
3. **Zpracovat výsledek běhu** — brána ověří kontrakt, existenci souborů na
   analyzovaném commitu a duplicitu proti starším nálezům.
4. Nálezy se objeví ve frontě a u řádků kódu. Rozhoduješ **Přijmout ·
   Odložit · Zamítnout ▸ důvod**.
5. **Metriky** ukážou precision — a její rozpad po dimenzích, severitě a modelech.

Fronta je seřazená tak, aby nahoře byly nálezy na kódu, na který od analýzy
nikdo nesáhl. Ty platí doslova a rozhodnou se nejrychleji.

## Rozhodnutí ≠ poznámka

Rozhodnutí má důvod z pevného seznamu, protože se z něj počítá precision.
Poznámka je volný text a má vlastní tlačítko. Nesdílí se — smíchat je znamená
rozbít buď měření, nebo použitelnost.

## Nastavení

`Ctrl+,` → hledej `agency`, nebo z panelu ikonou ozubeného kola.

| Klíč | K čemu |
|---|---|
| `agency.cliPath` | Cesta k `agency`, když není v PATH. |
| `agency.pack` | Kterého specialistu spouští tlačítko recenze. Packy, které pracují nad běžícím projektem, spouští **Spustit QA sezení…** |
| `agency.model`, `agency.provider` | Přebijí konfiguraci packu pro tenhle projekt. |
| `agency.commentThreads` | Vypnout komentáře u řádků. |
| `agency.autoRefresh` | Přenačíst, když `.agency/` změní agent nebo terminál. |

Nastavení **specialisty** (zadání, prohlížeč, model, práh skóre) tady není
schválně: patří projektu, ne editoru. Mění se v panelu Specialisté nebo příkazy
`agency brief` a `agency config` — a platí pak pro všechny tři klienty stejně.

## Instalace

Nejdřív jádro, bez něj je extension prázdná:

```
uv tool install --editable <cesta>/veriflow-agency/packages/core
```

Pak extension — buď VSIX:

```
npm --prefix packages/extension run package
code --install-extension dist/veriflow-agency-0.1.0.vsix
```

…nebo `F5` z tohohle repa (spustí Extension Development Host).

## Vývoj

```
node packages/extension/test/harness.js     # smoke test bez VS Code
```

Harness podstrčí falešný `vscode` a ověří, co ověřit lze strojově: stavbu
stromů, escapování vstupu do HTML a to, že se diff nabízí jen u nálezů dotčených
driftem. Renderování vláken a tlačítka chtějí `F5`.

Falešný `vscode` je záměrně hloupý. Kdyby se do něj musela dopisovat logika,
znamenalo by to, že se logika stěhuje z jádra do extension — a tím padá celá
hranice, na které nástroj stojí.
