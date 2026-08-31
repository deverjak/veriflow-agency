# Obě sady testů, jedním během.
#
#   pwsh scripts/test.ps1

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$failed = 0

Write-Host "`n  jádro (pytest)" -ForegroundColor Cyan
Push-Location "$repo/packages/core"
try {
    & uv run --with pytest --with jsonschema python -m pytest
    if ($LASTEXITCODE -ne 0) { $failed++ }
} finally { Pop-Location }

Write-Host "`n  extension (smoke)" -ForegroundColor Cyan
& node "$repo/packages/extension/test/harness.js"
if ($LASTEXITCODE -ne 0) { $failed++ }

if ($failed) {
    Write-Host "`n  $failed sada selhala`n" -ForegroundColor Red
    exit 1
}
Write-Host "`n  obojí prošlo`n" -ForegroundColor Green
