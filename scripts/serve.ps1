# Hold the projects open for a phone, as a process that outlives this terminal.
#
#   pwsh scripts/serve.ps1              # start, open for a week
#   pwsh scripts/serve.ps1 -Hours 8     # start, open for a working day
#   pwsh scripts/serve.ps1 -Status      # is it up, where, and for how much longer
#   pwsh scripts/serve.ps1 -Code        # show the pairing code again
#   pwsh scripts/serve.ps1 -Stop
#
# `agency serve` in a terminal is the right thing when you are sitting at the
# machine: the window is the activation, and closing it closes the door. It is
# the wrong thing for a daemon meant to stand for a week — a console job dies
# with its console, and anything supervising background work (an editor, an
# agent harness) may reap it when memory gets tight, which is how this one was
# killed twice in an afternoon while a phone was pointed at it.
#
# Start-Process detaches it: its own process, no console, no parent to lose.
# It still does not survive a logoff or a reboot; that belongs in Task
# Scheduler, and is a decision about a machine rather than about a session.

[CmdletBinding()]
param(
    [double]$Hours = 168,
    [int]$Port = 7777,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Code
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $env:LOCALAPPDATA 'agency\serve.log'

function Ok($text)   { Write-Host "  ✓ $text" -ForegroundColor Green }
function Note($text) { Write-Host "  ! $text" -ForegroundColor Yellow }
function Dim($text)  { Write-Host "  $text" -ForegroundColor DarkGray }

function Get-Daemon {
    # By command line, not by name: the process is python running the agency
    # shim, so its name says `python` and tells nobody anything. One daemon is
    # several processes — the shim launches the interpreter — so this is the
    # tree to stop, not a count of daemons.
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%agency%serve%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -notlike '*serve.ps1*' -and $_.Name -notlike 'pwsh*' }
}

function Get-Listener {
    # Which of them actually holds the port. That is the daemon; the rest of
    # the tree is how Windows got there.
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        return ($conn | Select-Object -First 1).OwningProcess
    } catch { return $null }
}

function Get-Agency {
    $cmd = Get-Command agency -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = Join-Path $env:USERPROFILE '.local\bin\agency.exe'
    if (Test-Path $fallback) { return $fallback }
    throw 'agency is not on PATH. Run scripts/install.ps1 first.'
}

function Read-PairingCode {
    # Named for what it reads, and assigned to a variable that is not $Code:
    # PowerShell variables are case-insensitive, so `$code = ...` writes to the
    # `-Code` switch parameter and fails on the type. It took a run to find.
    if (-not (Test-Path $log)) { return $null }
    $line = Select-String -Path $log -Pattern 'Pairing code:\s+(\d+)' | Select-Object -Last 1
    if ($line) { return $line.Matches[0].Groups[1].Value }
    return $null
}

function Get-TailnetUrl {
    # Entirely optional: the daemon is reachable on the loopback whether or not
    # Tailscale publishes it, so a missing or unconfigured tailscale is not an
    # error here — it just means there is no address worth printing.
    $ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (-not (Test-Path $ts)) { return $null }
    try {
        $published = & $ts serve status 2>$null | Out-String
        if ($published -notmatch "127\.0\.0\.1:$Port") { return $null }
        $self = (& $ts status --json 2>$null | ConvertFrom-Json).Self
        if (-not $self.DNSName) { return $null }
        return "https://$($self.DNSName.TrimEnd('.'))/"
    } catch { return $null }
}

function Test-Serving {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# ---------------------------------------------------------------- stop

if ($Stop) {
    $running = Get-Daemon
    if (-not $running) { Note 'nothing to stop — no agency serve is running'; return }
    foreach ($p in $running) {
        # Stopping the shim takes its interpreter with it, so by the time the
        # loop reaches the child there is nothing left to stop. That is the
        # job done, not a failure worth a red traceback.
        if (-not (Microsoft.PowerShell.Management\Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue)) { continue }
        Microsoft.PowerShell.Management\Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Ok "stopped PID $($p.ProcessId)"
    }
    if (Test-Serving) { Note "something is still answering on port $Port" }
    Dim 'The tailscale serve config stays — the address works again on the next start.'
    return
}

# ---------------------------------------------------------------- status

if ($Status -or $Code) {
    $running = Get-Daemon
    if (-not $running) {
        # And no pairing code either: the log outlives the daemon, and a code
        # from a window that has closed is worse than none — you would type it.
        Note 'not running'
    } else {
        $listener = Get-Listener
        if ($listener) { Ok "running, PID $listener" }
        else { Ok "running, PID $(($running | ForEach-Object ProcessId) -join ', ')" }
        if (Test-Serving) { Ok "serving on http://127.0.0.1:$Port/" }
        else { Note "the process is up but nothing answers on port $Port" }
        $url = Get-TailnetUrl
        if ($url) { Ok "on the tailnet: $url" }
        else { Dim "not published to the tailnet — ``tailscale serve --bg $Port``" }

        $pairing = Read-PairingCode
        if ($pairing) { Ok "pairing code: $pairing   (valid for its window, and for one device)" }
        else { Note 'no pairing code in the log yet' }
    }
    return
}

# ---------------------------------------------------------------- start

$running = Get-Daemon
if ($running) {
    $listener = Get-Listener
    Note "already running, PID $(if ($listener) { $listener } else { $running[0].ProcessId }) — that one is the activation."
    Dim 'Stop it first (-Stop) if you want a new window or a fresh pairing code.'
    return
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }

$agency = Get-Agency
# `--allow-bypass` every time, with no switch to forget. The flag exists in the
# core because the core cannot know whose machine it is on; this script does —
# it is one person's laptop, serving one person's phone over their own tailnet,
# and the phone still has to tick the box per run. Making it an argument here
# only meant restarting the daemon on the day you wanted it.
$argv = @('serve', '--hours', $Hours, '--port', $Port, '--allow-bypass')
$proc = Microsoft.PowerShell.Management\Start-Process -FilePath $agency `
    -ArgumentList $argv `
    -WorkingDirectory $repo -RedirectStandardOutput $log `
    -WindowStyle Hidden -PassThru

# The daemon prints what it opened and then runs; wait for that block rather
# than reporting a PID and leaving the pairing code to be hunted for.
$pairing = $null
foreach ($i in 1..100) {
    Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 100
    $pairing = Read-PairingCode
    if ($pairing) { break }
    if ($proc.HasExited) { break }
}

if ($proc.HasExited) {
    Note "agency serve exited immediately (code $($proc.ExitCode)). What it said:"
    if (Test-Path $log) { Get-Content $log | ForEach-Object { Dim $_ } }
    return
}

# The PID worth printing is the one holding the port, not the shim that
# launched it — otherwise this line and `-Status` name two different numbers
# for the same daemon, and the number is the handle you are told to keep.
$pid_ = Get-Listener
if (-not $pid_) { $pid_ = $proc.Id }
Ok "running detached, PID $pid_   ·   open for $Hours h"
Note 'the device paired with this code may run with the authorization checks off'
if ($pairing) { Ok "pairing code: $pairing" }
else { Note "started, but no pairing code in $log yet" }

$url = Get-TailnetUrl
if ($url) { Ok "on the tailnet: $url" }
else { Dim "not published to the tailnet yet — ``tailscale serve --bg $Port``" }

Write-Host ''
Dim "log:   $log"
Dim "stop:  pwsh scripts/serve.ps1 -Stop"
Dim 'It survives this terminal closing, but not a logoff or a reboot.'
