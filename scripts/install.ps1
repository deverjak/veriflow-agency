# Installing Agency — the core and the extension, in one pass.
#
#   pwsh scripts/install.ps1              # both
#   pwsh scripts/install.ps1 -Core        # the core only
#   pwsh scripts/install.ps1 -Extension   # the extension only
#
# The core is installed EDITABLE. While the tool is being developed, a change
# to the source is immediately a change to the command — without that, every
# edit would need a reinstall and one would be testing the old version
# without noticing.

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
    Step 'core (uv tool install --editable)'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv is not installed. https://docs.astral.sh/uv/getting-started/installation/'
    }
    & uv tool install --editable "$repo/packages/core" --force
    if ($LASTEXITCODE -ne 0) { throw 'installing the core failed' }

    $agency = (Get-Command agency -ErrorAction SilentlyContinue)
    if ($agency) {
        Ok "agency on PATH: $($agency.Source)"
    } else {
        # `uv tool` can place the binary outside PATH — the extension has a
        # setting for that, but saying so now beats hunting for it later in
        # an empty panel.
        Warn 'agency is not on PATH. Run `uv tool update-shell` and open a new terminal,'
        Warn 'or set the path in VS Code: Settings → agency.cliPath'
    }
}

if ($Extension -or $both) {
    Step 'extension (VSIX)'
    Push-Location "$repo/packages/extension"
    try {
        & npm run package
        if ($LASTEXITCODE -ne 0) { throw 'building the VSIX failed' }
    } finally {
        Pop-Location
    }

    $vsix = Get-ChildItem "$repo/dist/*.vsix" | Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $vsix) { throw 'no VSIX found' }

    if (Get-Command code -ErrorAction SilentlyContinue) {
        & code --install-extension $vsix.FullName --force
        Ok "installed: $($vsix.Name)"
        Warn 'VS Code needs a restart (Developer: Reload Window).'
    } else {
        Ok "built: $($vsix.FullName)"
        Warn '`code` is not on PATH — install the VSIX by hand from Extensions → … → Install from VSIX'
    }
}

Step 'next'
Write-Host '  1. open a project with a git repository'
Write-Host '  2. agency init          # copies the author pack in; safe to run twice'
Write-Host '  3. agency doctor'
Write-Host '  4. the Agency icon in the activity bar → Specialists → Write a new specialist…'
Write-Host ''
