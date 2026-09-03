# Instalace Agency — jádro i extension, jedním během.
#
#   pwsh scripts/install.ps1              # nainstaluje obojí
#   pwsh scripts/install.ps1 -Core        # jen jádro
#   pwsh scripts/install.ps1 -Extension   # jen extension
#
# Jádro se instaluje jako EDITABLE. Dokud se nástroj vyvíjí, je změna zdroje
# okamžitě změnou příkazu — bez toho by se každá úprava musela přeinstalovat
# a člověk by testoval starou verzi, aniž by to poznal.

[CmdletBinding()]
param(
    [switch]$Core,
    [switch]$Extension
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$both = -not ($Core -or $Extension)

function Step($text) { Write-Host "`n  $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  ✓ $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  ! $text" -ForegroundColor Yellow }

if ($Core -or $both) {
    Step 'jádro (uv tool install --editable)'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv není nainstalované. https://docs.astral.sh/uv/getting-started/installation/'
    }
    & uv tool install --editable "$repo/packages/core" --force
    if ($LASTEXITCODE -ne 0) { throw 'instalace jádra selhala' }

    $agency = (Get-Command agency -ErrorAction SilentlyContinue)
    if ($agency) {
        Ok "agency v PATH: $($agency.Source)"
    } else {
        # `uv tool` umí položit binárku mimo PATH — extension na to má nastavení,
        # ale je lepší to říct hned než ji pak hledat v prázdném panelu.
        Warn 'agency není v PATH. Spusť `uv tool update-shell` a otevři nový terminál,'
        Warn 'nebo nastav cestu ve VS Code: Settings → agency.cliPath'
    }
}

if ($Extension -or $both) {
    Step 'extension (VSIX)'
    Push-Location "$repo/packages/extension"
    try {
        & npm run package
        if ($LASTEXITCODE -ne 0) { throw 'sestavení VSIX selhalo' }
    } finally {
        Pop-Location
    }

    $vsix = Get-ChildItem "$repo/dist/*.vsix" | Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $vsix) { throw 'VSIX se nenašel' }

    if (Get-Command code -ErrorAction SilentlyContinue) {
        & code --install-extension $vsix.FullName --force
        Ok "nainstalováno: $($vsix.Name)"
        Warn 'VS Code je potřeba restartovat (Developer: Reload Window).'
    } else {
        Ok "sestaveno: $($vsix.FullName)"
        Warn 'příkaz `code` není v PATH — nainstaluj VSIX ručně z Extensions → … → Install from VSIX'
    }
}

Step 'dál'
Write-Host '  1. otevři projekt s git repem'
Write-Host '  2. cp -r packs/author <projekt>/.claude/skills/agency-author'
Write-Host '  3. agency doctor'
Write-Host '  4. ikona Agency v activity baru → Specialists → Write a new specialist…'
Write-Host ''
