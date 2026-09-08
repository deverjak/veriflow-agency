# Both suites, in one run.
#
#   pwsh scripts/test.ps1

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$failed = 0

Write-Host "`n  core (pytest)" -ForegroundColor Cyan
Push-Location "$repo/packages/core"
try {
    & uv run --with pytest --with jsonschema python -m pytest
    if ($LASTEXITCODE -ne 0) { $failed++ }
} finally { Pop-Location }

Write-Host "`n  extension (smoke)" -ForegroundColor Cyan
& node "$repo/packages/extension/test/harness.js"
if ($LASTEXITCODE -ne 0) { $failed++ }

if ($failed) {
    Write-Host "`n  $failed suite(s) failed`n" -ForegroundColor Red
    exit 1
}
Write-Host "`n  both passed`n" -ForegroundColor Green
