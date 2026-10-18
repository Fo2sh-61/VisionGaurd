# Install VisionGuard on a site's workstation (spec 016, plan D). Run once,
# in an administrator PowerShell, from the unpacked kit:
#
#     .\app\deploy\install.ps1 -Models D:\models -Root E:\ -Site E:\site
#
#   -Models  the owner's model files (copied into app\models; nothing is
#            ever downloaded)
#   -Root    the USB stick holding visionguard-root.crt and .key, made once
#            with `site_cert.py root --out E:\`
#   -Site    a folder holding this site's engine.yaml (and .env, if cameras
#            need passwords). Only needed the first time: after that the copy
#            in C:\VisionGuard\data is the one that counts.
#
# What it does, in order, stopping at the first step that fails:
#   1. copies the program to C:\VisionGuard\app, makes data\ and logs\
#   2. Python 3.14, from the installer in the kit, if it is missing
#   3. app\.venv with torch, requirements.txt, TensorRT and the appearance
#      matcher (needs internet)
#   4. copies the models, checks every one the site needs, builds TensorRT
#   5. the site certificate, and trusts the root on this machine
#   6. the two services, and folder rights for them
#   7. the first administrator, if there is none
#   8. one desktop shortcut, "VisionGuard", that opens the console
#   9. starts both services and waits for https://localhost/healthz
#
# Safe to run twice: every step checks what is already there first.

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Models,
    [Parameter(Mandatory)] [string]$Root,
    [string]$Site
)

$ErrorActionPreference = 'Stop'

$Home_   = 'C:\VisionGuard'
$App     = Join-Path $Home_ 'app'
$Data    = Join-Path $Home_ 'data'
$Logs    = Join-Path $Home_ 'logs'
$Kit     = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$KitApp  = Join-Path $Kit 'app'
$Python  = Join-Path $App '.venv\Scripts\python.exe'
$Services = @('visionguard-engine', 'visionguard-front')

function Step($n, $what) { Write-Host "`n[$n] $what" -ForegroundColor Cyan }
function Ok($what)       { Write-Host "    ok    $what" -ForegroundColor Green }
function Skip($what)     { Write-Host "    skip  $what" -ForegroundColor DarkGray }
function Stop-Install($why) {
    Write-Host "`n    STOPPED: $why`n" -ForegroundColor Red
    exit 1
}
function Run($exe, [string[]]$argv, $why) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Stop-Install "$why (exit code $LASTEXITCODE)" }
}

# The engine's own tools read the site's config, not the program's.
$env:VG_HOME = $Data
$env:VG_LOGS = $Logs

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Stop-Install 'run this in a PowerShell opened with "Run as administrator".'
}
foreach ($p in @($Models, $Root)) {
    if (-not (Test-Path $p)) { Stop-Install "$p does not exist." }
}

# --- 1. program and folders ---------------------------------------------------
Step 1 'Program and folders'
foreach ($name in $Services) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Stopped') { Stop-Service -Name $name -Force; Ok "stopped $name" }
}
if ((Resolve-Path $KitApp).Path -ne $App) {
    # /MIR would delete the models and the venv, which are not in the kit.
    robocopy $KitApp $App /E /NFL /NDL /NJH /NJS /NP /XD .venv models | Out-Null
    if ($LASTEXITCODE -ge 8) { Stop-Install "copying the program to $App failed (robocopy $LASTEXITCODE)" }
    Ok "program copied to $App"
} else {
    Skip 'running from the installed program already'
}
foreach ($dir in @($Data, $Logs)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
if (-not (Test-Path (Join-Path $Data 'engine.yaml'))) {
    if (-not $Site) {
        Stop-Install ("there is no $Data\engine.yaml yet. Pass -Site <folder> holding this " +
                      "site's engine.yaml: its storage paths under C:\VisionGuard\data, its " +
                      'cameras, and tls.names (this machine''s address, 127.0.0.1, localhost).')
    }
    Copy-Item (Join-Path $Site 'engine.yaml') $Data
    Ok "engine.yaml copied to $Data"
    if (Test-Path (Join-Path $Site '.env')) { Copy-Item (Join-Path $Site '.env') $Data; Ok '.env copied' }
} else {
    Skip "$Data\engine.yaml is already there (this copy is kept)"
}

# --- 2. Python ----------------------------------------------------------------
Step 2 'Python 3.14'
$py = Get-Command py -ErrorAction SilentlyContinue
$have = $false
if ($py) { & py -3.14 -c 'import sys' 2>$null; $have = ($LASTEXITCODE -eq 0) }
if ($have) {
    Skip 'already installed'
} else {
    $installer = Get-ChildItem $Kit -Filter 'python-3.14*-amd64.exe' | Select-Object -First 1
    if (-not $installer) { Stop-Install "no python-3.14*-amd64.exe in $Kit." }
    $p = Start-Process $installer.FullName -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=1', 'Include_launcher=1', 'PrependPath=0', 'Include_test=0')
    if ($p.ExitCode -ne 0) { Stop-Install "the Python installer failed (exit code $($p.ExitCode))." }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    Ok "installed from $($installer.Name)"
}

# --- 3. the program's own Python ------------------------------------------------
Step 3 'Packages (needs internet)'
if (-not (Test-Path $Python)) {
    Run py @('-3.14', '-m', 'venv', (Join-Path $App '.venv')) 'making app\.venv failed'
    Ok 'app\.venv made'
}
Run $Python @('-m', 'pip', 'install', '--upgrade', 'pip') 'upgrading pip failed'
# CUDA 12.8 wheels. torch first: requirements.txt deliberately does not pin it.
Run $Python @('-m', 'pip', 'install', 'torch', 'torchvision',
              '--index-url', 'https://download.pytorch.org/whl/cu128') 'installing torch failed'
Run $Python @('-m', 'pip', 'install', '-r', (Join-Path $App 'engine\requirements.txt')) 'installing requirements.txt failed'
# The cu12 line only: the cu13 wheel segfaults while building (models/README.md).
Run $Python @('-m', 'pip', 'install', 'tensorrt_cu12_bindings', 'tensorrt_cu12_libs', 'tensorrt-cu12') 'installing TensorRT failed'
# The appearance matcher person tracking uses. Code, not a model (P10-FR-002).
# From the kit: step 1 leaves app\models out, and the models arrive in step 4.
Run $Python @('-m', 'pip', 'install', (Join-Path $KitApp 'models\reid\loiterwatch')) 'installing the appearance matcher failed'
Ok 'packages installed'

# --- 4. models -----------------------------------------------------------------
Step 4 'Models'
# Never the .engine files: a TensorRT plan only opens with the TensorRT that
# built it, so plans from another machine are built again below.
robocopy $Models (Join-Path $App 'models') /E /XF *.engine /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Install "copying the models from $Models failed (robocopy $LASTEXITCODE)" }
Run $Python @((Join-Path $App 'engine\tools\check_models.py')) 'a model this site needs is missing (listed above). Nothing was started'
Run $Python @((Join-Path $App 'engine\tools\build_engines.py')) 'building the TensorRT engines failed'
Ok 'models in place'

# --- 5. certificate ------------------------------------------------------------
Step 5 'Site certificate'
Run $Python @((Join-Path $App 'engine\tools\site_cert.py'), 'site', '--root', $Root) 'making the site certificate failed'
$rootCrt = Join-Path $Root 'visionguard-root.crt'
$thumb = (New-Object Security.Cryptography.X509Certificates.X509Certificate2 $rootCrt).Thumbprint
if (Get-ChildItem Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $thumb) {
    Skip 'root already trusted on this machine'
} else {
    Import-Certificate -FilePath $rootCrt -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Ok 'root trusted on this machine'
}

# --- 6. services ----------------------------------------------------------------
Step 6 'Services'
$winsw = Join-Path $App 'bin\WinSW-x64.exe'
if (-not (Test-Path $winsw)) { Stop-Install "$winsw is missing from the kit." }
$serviceDir = Join-Path $App 'service'
New-Item -ItemType Directory -Force -Path $serviceDir | Out-Null
foreach ($name in $Services) {
    # WinSW reads the XML with the same name as its own exe.
    Copy-Item $winsw (Join-Path $serviceDir "$name.exe") -Force
    Copy-Item (Join-Path $App "deploy\service\$name.xml") $serviceDir -Force
    if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
        Run (Join-Path $serviceDir "$name.exe") @('refresh') "refreshing $name failed"
        Ok "$name updated"
    } else {
        Run (Join-Path $serviceDir "$name.exe") @('install') "installing $name failed"
        Ok "$name installed"
    }
}
# Least privilege: the services write to data\ and logs\ and nowhere else.
foreach ($dir in @($Data, $Logs)) {
    Run icacls @($dir, '/grant', 'NT AUTHORITY\LocalService:(OI)(CI)M', '/Q') "giving the service rights on $dir failed"
}
Ok 'LocalService may write to data\ and logs\ only'
foreach ($port in 443, 8443) {
    $rule = "VisionGuard HTTPS $port"
    if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP `
            -LocalPort $port -Action Allow -Profile Private,Domain | Out-Null
        Ok "firewall: TCP $port open on private networks"
    }
}

# --- 7. first administrator -------------------------------------------------------
Step 7 'First administrator'
& $Python -c "import sys; sys.path[:0] = [r'$App\engine', r'$App\engine\tools']; import create_user; from vg.auth.store import UserStore; s = UserStore(create_user._database()); sys.exit(0 if any(u.role == 'admin' and not u.disabled for u in s.users()) else 3)"
if ($LASTEXITCODE -eq 0) {
    Skip 'an administrator already exists'
} else {
    Write-Host '    Type the head''s name, email and a password. There is no default password.'
    Run $Python @((Join-Path $App 'engine\tools\create_user.py'), '--role', 'admin') 'creating the administrator failed'
}

# --- 8. shortcut -------------------------------------------------------------------
Step 8 'Desktop shortcut'
$edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" }
$link = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'VisionGuard.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($link)
$lnk.TargetPath = $edge
$lnk.Arguments = '--app=https://localhost/'
$lnk.IconLocation = (Join-Path $App 'assets\visionguard.ico')
$lnk.Description = 'Open the VisionGuard console'
$lnk.Save()
Ok "$link (opens the console; starts and stops nothing)"

# --- 9. start ----------------------------------------------------------------------
Step 9 'Start'
foreach ($name in $Services) { Start-Service -Name $name; Ok "$name started" }
$deadline = (Get-Date).AddMinutes(3)
do {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'https://localhost/healthz' -TimeoutSec 5
        if ($r.StatusCode -eq 200) { Ok 'https://localhost/healthz answers'; break }
    } catch { Start-Sleep -Seconds 3 }
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) {
    $failure = Join-Path $Logs 'start-failure.txt'
    $why = if (Test-Path $failure) { Get-Content $failure -Raw } else { "see $Logs" }
    Stop-Install "the engine did not answer within 3 minutes: $why"
}

Write-Host "`n  VisionGuard is installed. Open it from the VisionGuard icon on the desktop.`n" -ForegroundColor Green
