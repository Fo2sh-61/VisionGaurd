<#
.SYNOPSIS
    VisionGuard developer entry point. One command, a few sub-commands.

.DESCRIPTION
    .\dev.ps1 up            engine + web together, colour-tagged, Ctrl-C stops both
    .\dev.ps1 up -Mock      VG_MOCK=1 - instant start, no models, no camera. UI work
    .\dev.ps1 up -Clip      the recorded clip instead of the webcam. Pipeline work
    .\dev.ps1 up -Mobile    the phone app too, on 5174, against the same engine
    .\dev.ps1 engine        engine only
    .\dev.ps1 web           front end only
    .\dev.ps1 mobile        the phone app only
    .\dev.ps1 down          free ports 8001/5173/5174 and release the webcam
    .\dev.ps1 doctor        pre-flight checks. Run this each morning
    .\dev.ps1 test          pyflakes + pytest + smoke + tsc x2 + parity (same as CI)

.NOTES
    Never opens a second terminal. Never needs a PC restart.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'doctor', 'engine', 'web', 'mobile', 'test', 'help')]
    [string]$Command = 'help',

    # Start the phone app alongside the console. Both talk to the same engine
    # and both proxy to it, so a change made on one shows up on the other.
    [switch]$Mobile,

    # Serve fixtures. Starts in under a second, loads no models, opens no camera.
    [switch]$Mock,

    # Swap the webcam for the labelled walk-through clip. Deterministic, and it
    # locks no device - a crashed run cannot leave the webcam busy.
    [switch]$Clip,

    # Run even without a project venv, on whatever `python` resolves to.
    [switch]$AllowSystemPython
)

$ErrorActionPreference = 'Stop'
$Root     = $PSScriptRoot
$EngineDir = Join-Path $Root 'engine'
$WebDir    = Join-Path $Root 'web'
$MobileDir = Join-Path $Root 'mobile'
$VenvPy    = Join-Path $Root '.venv\Scripts\python.exe'
$ApiPort   = 8001   # not 8000: that is the installed engine service's
$WebPort   = 5173
$MobilePort = 5174

# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------

function Write-Head($text) { Write-Host "`n  $text" -ForegroundColor Cyan }
function Write-Ok  ($text) { Write-Host "  [ ok ] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [warn] $text" -ForegroundColor Yellow }
function Write-Bad ($text) { Write-Host "  [FAIL] $text" -ForegroundColor Red }
function Write-Info($text) { Write-Host "         $text" -ForegroundColor DarkGray }

# ---------------------------------------------------------------------------
# the interpreter
#
# Always explicit, never a bare `python`. Running the engine on the wrong
# interpreter means CPU-only inference: everything still works, roughly 7x
# slower, and nothing on screen says so. That is a very expensive afternoon.
# ---------------------------------------------------------------------------

function Get-Python {
    if (Test-Path $VenvPy) { return $VenvPy }

    if ($AllowSystemPython) {
        $sys = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($sys) {
            Write-Warn 'No project venv - using system python (-AllowSystemPython).'
            Write-Info 'CUDA is NOT guaranteed here. Check the gpu line below.'
            return $sys
        }
    }

    Write-Bad 'No project venv at .venv\Scripts\python.exe'
    Write-Info 'The venv is deliberately not built yet - see DEV_PLAN.md 1.4.'
    Write-Info 'It is blocked on the re-ID model handover, because that decides'
    Write-Info 'the Python version and a PyTorch wheel is ~2.5 GB to redo.'
    Write-Info ''
    Write-Info 'To run anyway on whatever python is on PATH:'
    Write-Info '    .\dev.ps1 up -Mock -AllowSystemPython'
    return $null
}

# ---------------------------------------------------------------------------
# ports
#
# Freeing them BEFORE starting, every time. Starting into an occupied port
# gives WinError 10013, which reads like a permissions problem and is not one.
# ---------------------------------------------------------------------------

function Get-PortOwners([int]$Port) {
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        @()
    }
}

function Clear-Port([int]$Port) {
    $owners = Get-PortOwners $Port
    if (-not $owners) { return $false }

    foreach ($processId in $owners) {
        if ($processId -eq 0 -or $processId -eq $PID) { continue }
        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            Write-Warn "port $Port held by $($proc.ProcessName) (pid $processId) - stopping it"
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Bad "could not stop pid $processId on port $Port : $($_.Exception.Message)"
        }
    }
    Start-Sleep -Milliseconds 400
    return $true
}

function Clear-Ports {
    $freed = $false
    foreach ($p in @($ApiPort, $WebPort, $MobilePort)) {
        if (Clear-Port $p) { $freed = $true }
    }
    if (-not $freed) { Write-Ok "ports $ApiPort / $WebPort / $MobilePort already free" }
}

# ---------------------------------------------------------------------------
# down - the panic button
# ---------------------------------------------------------------------------

function Invoke-Down {
    Write-Head 'Stopping everything'
    Clear-Ports

    # Anything still sitting on the webcam. Narrow on purpose: only processes
    # running THIS repo's code, so a stray editor or notebook is left alone.
    $stale = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'serve\.py|vg\.api\.app' }

    foreach ($proc in $stale) {
        Write-Warn "stale engine process (pid $($proc.ProcessId)) - stopping it"
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch {}
    }

    if (-not $stale) { Write-Ok 'no stale engine process holding the camera' }
    Write-Host ''
    Write-Ok 'clean'
}

# ---------------------------------------------------------------------------
# doctor
#
# Every check here is a failure that has already cost time, or will.
# ---------------------------------------------------------------------------

function Invoke-Doctor {
    Write-Head 'VisionGuard pre-flight'
    $problems = 0
    $py = if (Test-Path $VenvPy) { $VenvPy } else { (Get-Command python -ErrorAction SilentlyContinue).Source }

    # -- interpreter + GPU --------------------------------------------------
    if (Test-Path $VenvPy) {
        Write-Ok "venv          .venv"
    } else {
        Write-Warn 'venv          missing - blocked on the re-ID handover (DEV_PLAN 1.4)'
        if ($py) { Write-Info "falling back to $py for the remaining checks" }
    }

    if (-not $py) {
        Write-Bad 'python        not found on PATH either - cannot check anything else'
        return 1
    }

    $ver = & $py --version 2>&1
    Write-Info "python        $ver"

    $cuda = & $py -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "torch         not importable - engine will not start"
        $problems++
    } elseif ($cuda -match 'True') {
        Write-Ok "gpu           $cuda"
    } else {
        Write-Bad "gpu           CPU ONLY (~7x slower, and invisible otherwise): $cuda"
        $problems++
    }

    # -- tzdata -------------------------------------------------------------
    # Without it zoneinfo cannot resolve Africa/Cairo on Windows and every
    # timestamp silently renders in UTC - three hours out, all year.
    & $py -c "from zoneinfo import ZoneInfo; ZoneInfo('Africa/Cairo')" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'timezone      Africa/Cairo resolves' }
    else { Write-Bad 'timezone      cannot resolve Africa/Cairo - pip install tzdata'; $problems++ }

    # -- config, models, hours ----------------------------------------------
    $probe = @'
import sys, pathlib
sys.path.insert(0, "engine")
from vg import config as c
try:
    cfg = c.load()
except Exception as exc:
    print("CONFIG_ERROR", exc); raise SystemExit(0)
print("SITE", cfg.site_name)
print("HOURS", cfg.hours.start, cfg.hours.end, cfg.hours.late_cutoff)
for name, m in cfg.models.items():
    print("MODEL", name, "OK" if m.weights.is_file() else "MISSING", m.weights)
for cam in cfg.cameras:
    print("CAM", cam.id, "on" if cam.enabled else "off", ",".join(cam.features))
db = pathlib.Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
print("DB", db, db.is_file())
'@
    $probeFile = Join-Path $env:TEMP 'vg_doctor_probe.py'
    Set-Content -Path $probeFile -Value $probe -Encoding utf8
    $out = & $py $probeFile 2>&1
    Remove-Item $probeFile -ErrorAction SilentlyContinue

    $configError = $out | Where-Object { $_ -match '^CONFIG_ERROR' }
    if ($configError) {
        Write-Bad "config        $configError"
        $problems++
    } else {
        Write-Ok 'config        engine.yaml parses'

        foreach ($line in $out) {
            if ($line -match '^MODEL (\S+) (\S+) (.+)$') {
                if ($Matches[2] -eq 'OK') { Write-Info "model         $($Matches[1])" }
                else { Write-Bad "model         $($Matches[1]) MISSING: $($Matches[3])"; $problems++ }
            }
            elseif ($line -match '^HOURS (\S+) (\S+) (\S+)$') {
                # A 00:00-23:59 window marks a 01:14 sighting as an on-time
                # arrival. Correct for night testing, wrong for a register.
                if ($Matches[1] -eq '00:00:00' -and $Matches[2] -eq '23:59:00') {
                    Write-Warn "hours         $($Matches[1]) - $($Matches[2])  NIGHT-TEST MODE, not real school hours"
                    $problems++
                } else {
                    Write-Ok "hours         $($Matches[1]) - $($Matches[2])  (late after $($Matches[3]))"
                }
            }
            elseif ($line -match '^CAM (\S+) (\S+) (.*)$') {
                Write-Info "camera        $($Matches[1]) [$($Matches[2])] $($Matches[3])"
            }
            elseif ($line -match '^DB (.+) (True|False)$') {
                if ($Matches[2] -eq 'True') { Write-Ok "database      $($Matches[1])" }
                else { Write-Warn "database      not created yet: $($Matches[1])" }
            }
        }
    }

    # -- enrolment ----------------------------------------------------------
    # Zero enrolled looks exactly like broken recognition, from the console.
    $enrolled = & $py -c "import sys; sys.path.insert(0,'engine'); import sqlite3; print(sqlite3.connect('engine/data/visionguard.db').execute('select count(*) from person').fetchone()[0])" 2>&1
    if ($LASTEXITCODE -eq 0) {
        if ([int]$enrolled -eq 0) { Write-Warn 'enrolled      0 people - recognition will match nobody' }
        else { Write-Ok "enrolled      $enrolled people" }
    } else {
        Write-Warn 'enrolled      no person table yet'
    }

    # -- ports --------------------------------------------------------------
    foreach ($p in @($ApiPort, $WebPort)) {
        $owners = Get-PortOwners $p
        if ($owners) { Write-Bad "port $p      in use by pid $($owners -join ', ') - run .\dev.ps1 down"; $problems++ }
        else { Write-Ok "port $p      free" }
    }

    # -- node ---------------------------------------------------------------
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        if (Test-Path (Join-Path $WebDir 'node_modules')) { Write-Ok 'web           node_modules installed' }
        else { Write-Warn 'web           node_modules missing - run: npm --prefix web install'; $problems++ }
    } else {
        Write-Warn 'web           npm not on PATH'
    }

    # -- disk ---------------------------------------------------------------
    # Footage recording (Phase 6) will happily fill a drive.
    $drive = Get-PSDrive -Name ($Root.Substring(0,1)) -ErrorAction SilentlyContinue
    if ($drive) {
        $freeGb = [math]::Round($drive.Free / 1GB, 1)
        if ($freeGb -lt 10) { Write-Bad "disk          ${freeGb} GB free - too little for footage"; $problems++ }
        else { Write-Ok "disk          ${freeGb} GB free" }
    }

    Write-Host ''
    if ($problems -eq 0) { Write-Ok 'all clear'; return 0 }
    Write-Warn "$problems problem(s) above"
    return $problems
}

# ---------------------------------------------------------------------------
# up
# ---------------------------------------------------------------------------

function Invoke-Up([bool]$WithEngine, [bool]$WithWeb, [bool]$WithMobile) {
    $py = $null
    if ($WithEngine) {
        $py = Get-Python
        if (-not $py) { return 1 }
    }

    Write-Head 'Freeing ports'
    Clear-Ports

    $env:PYTHONUNBUFFERED = '1'
    if ($Mock) {
        $env:VG_MOCK = '1'
        Write-Warn 'VG_MOCK=1 - fixtures only. No models, no cameras.'
    } else {
        Remove-Item Env:\VG_MOCK -ErrorAction SilentlyContinue
    }

    if ($Clip) {
        $env:VG_CAMERAS = 'cam-clip'
        Write-Ok 'cameras       cam-clip only (the labelled walk-through recording)'
    } else {
        Remove-Item Env:\VG_CAMERAS -ErrorAction SilentlyContinue
    }

    $jobs = @()

    if ($WithEngine) {
        Write-Head 'Starting engine'
        $jobs += Start-Job -Name 'engine' -ScriptBlock {
            param($py, $root)
            Set-Location $root
            $env:PYTHONUNBUFFERED = '1'
            & $py 'engine\tools\serve.py' 2>&1
        } -ArgumentList $py, $Root
    }

    if ($WithWeb) {
        Write-Head 'Starting web'
        $jobs += Start-Job -Name 'web' -ScriptBlock {
            param($webDir)
            Set-Location $webDir
            & npm run dev 2>&1
        } -ArgumentList $WebDir
    }

    # The phone app. A separate Vite server on 5174 with its own proxy to the
    # same engine - it has to be same-origin or the session cookie
    # (SameSite=Strict) never reaches a camera stream and every tile is black.
    if ($WithMobile) {
        Write-Head 'Starting mobile'
        $jobs += Start-Job -Name 'mobile' -ScriptBlock {
            param($mobileDir)
            Set-Location $mobileDir
            & npm run dev 2>&1
        } -ArgumentList $MobileDir
    }

    Write-Host ''
    Write-Info 'Ctrl-C stops everything cleanly.'
    Write-Host ''

    $colours = @{ engine = 'Cyan'; web = 'Magenta'; mobile = 'Yellow' }

    # Nobody asked for this to stop. Set when the jobs end on their own, which
    # is a failed start however tidily it printed - and it decides the exit
    # code, which is the only thing launch.ps1 can see. Returning 0 here meant
    # a double-clicked icon closed its window the instant the engine died,
    # taking the error with it.
    $died = $false

    try {
        while ($true) {
            $running = $false
            foreach ($job in $jobs) {
                foreach ($line in (Receive-Job -Job $job)) {
                    Write-Host "[$($job.Name)] " -ForegroundColor $colours[$job.Name] -NoNewline
                    Write-Host $line
                }
                if ($job.State -eq 'Running') { $running = $true }
            }
            if (-not $running) {
                Write-Warn 'every job has exited'
                foreach ($job in $jobs) {
                    Write-Info "$($job.Name) ended $($job.State.ToString().ToLower())"
                }
                $died = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
    } finally {
        # Runs on Ctrl-C too. Drain whatever is buffered, stop the jobs, then
        # free the ports again so the next `up` starts clean regardless of how
        # this one ended.
        Write-Host ''
        Write-Head 'Stopping'
        foreach ($job in $jobs) {
            foreach ($line in (Receive-Job -Job $job -ErrorAction SilentlyContinue)) {
                Write-Host "[$($job.Name)] " -ForegroundColor $colours[$job.Name] -NoNewline
                Write-Host $line
            }
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
        Clear-Ports
        Write-Ok 'stopped'
    }
    if ($died) { return 1 }
    return 0
}

# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

<#
    One front end's type check. Returns 1 if it failed, 0 otherwise, so the
    caller can just add it up.

    `tsc -b --force`, NOT `tsc --noEmit`.

    Both apps use project references, and `--noEmit` against the solution
    tsconfig checks nothing and exits 0. It looked like a passing type check
    while real errors sat in the source. `-b` builds the referenced projects;
    `--force` stops a stale .tsbuildinfo from skipping the work.

    Invoked through node, not npx. `& npx tsc` failed here with "could not
    determine executable to run" while the very same check passed from a
    shell, so the gate reported a type error that did not exist - the worst
    way for a gate to fail. This runs the TypeScript the lockfile pinned,
    with no shim in the way.
#>
function Invoke-Tsc([string]$Dir, [string]$Label, [string]$Name) {
    Write-Head $Label
    if (-not (Test-Path (Join-Path $Dir 'node_modules'))) {
        Write-Warn "skipped - run: npm --prefix $Name install"
        return 0
    }

    Push-Location $Dir
    try {
        $tsc = Join-Path $Dir 'node_modules\typescript\bin\tsc'
        if (Test-Path $tsc) {
            & node $tsc -b --force
        } else {
            & npx tsc -b --force
        }
        if ($LASTEXITCODE -ne 0) { return 1 }
        return 0
    } finally { Pop-Location }
}

function Invoke-Test {
    $py = Get-Python
    if (-not $py) { return 1 }
    $failed = 0

    Write-Head 'pytest'
    & $py -m pytest engine -q
    if ($LASTEXITCODE -ne 0) { $failed++ }

    # pyflakes catches the exact bug class that broke face recognition - a name
    # used but never bound, swallowed at runtime by a broad except. One second.
    #
    # engine/tests is included: a broken test helper hides a failure just as
    # effectively as broken source, and it is the same one-second check.
    Write-Head 'pyflakes'
    & $py -m pyflakes engine/vg engine/tools engine/tests
    if ($LASTEXITCODE -ne 0) { $failed++ }

    # Boot the real process, ask it one question, stop it. Unit tests start the
    # app object; this starts the program, which is where a startup that fails
    # after the app is built shows up. VG_MOCK, so it opens no camera and needs
    # no weights - safe to run with an engine already up on 8001.
    Write-Head 'smoke'
    & $py engine/tools/smoke.py
    if ($LASTEXITCODE -ne 0) { $failed++ }

    # Both front ends. The phone app was never typechecked at all until
    # 3 Sep 2026 - it had no CI job and no local gate, which is how a whole
    # app of fixtures stayed green-looking for months.
    $failed += Invoke-Tsc $WebDir    'tsc web'    'web'
    $failed += Invoke-Tsc $MobileDir 'tsc mobile' 'mobile'

    # The console and the phone are two apps holding one copy of the truth.
    # This is what stops the shared half quietly becoming two halves - the
    # palette file had already drifted while carrying a comment claiming it
    # could not have.
    Write-Head 'parity'
    & $py tools/check_parity.py
    if ($LASTEXITCODE -ne 0) { $failed++ }

    # Nothing on the phone may be invented. `tsc` catches a stale import of a
    # deleted fixture module; this catches new ones written by hand.
    Write-Head 'fixtures'
    & $py tools/check_parity.py --no-fixtures
    if ($LASTEXITCODE -ne 0) { $failed++ }

    Write-Host ''
    if ($failed -eq 0) { Write-Ok 'all green'; return 0 }
    Write-Bad "$failed suite(s) failed"
    return $failed
}

# ---------------------------------------------------------------------------

function Show-Help {
    Write-Head 'VisionGuard'
    Write-Host @'
  .\dev.ps1 up            engine + web, one window, Ctrl-C stops both
  .\dev.ps1 up -Mock      instant start, fixtures only. UI work
  .\dev.ps1 up -Clip      the labelled recording instead of the webcam
  .\dev.ps1 up -Mobile    the phone app too, on 5174, same engine
  .\dev.ps1 engine        engine only
  .\dev.ps1 web           front end only
  .\dev.ps1 mobile        the phone app only (5174)
  .\dev.ps1 down          free the ports, release the webcam. Panic button
  .\dev.ps1 doctor        pre-flight checks. Run this each morning
  .\dev.ps1 test          pyflakes + pytest + smoke + tsc x2 + parity + fixtures

  -AllowSystemPython      run without the project venv (not yet built)
'@
}

switch ($Command) {
    'up'     { exit (Invoke-Up  -WithEngine $true  -WithWeb $true  -WithMobile $Mobile.IsPresent) }
    'engine' { exit (Invoke-Up  -WithEngine $true  -WithWeb $false -WithMobile $false) }
    'web'    { exit (Invoke-Up  -WithEngine $false -WithWeb $true  -WithMobile $false) }
    'mobile' { exit (Invoke-Up  -WithEngine $false -WithWeb $false -WithMobile $true) }
    'down'   { Invoke-Down; exit 0 }
    'doctor' { exit (Invoke-Doctor) }
    'test'   { exit (Invoke-Test) }
    default  { Show-Help; exit 0 }
}
