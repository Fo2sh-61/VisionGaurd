# Install VisionGuard on a site's workstation (spec 016, plan D). Run once,
# in an administrator PowerShell, from the unpacked kit:
#
#     .\app\deploy\install.ps1 -Models D:\models -Root E:\ -Site E:\site
#
#   -Models  the owner's model files (copied into app\models; nothing is
#            ever downloaded)
#   -Root    the USB stick holding visionguard-root.crt and .key, made once
#            with `site_cert.py root --out E:\`
#   -AdminEmail, -AdminName
#            the first administrator, made without any question when the
#            password is in the environment variable VG_ADMIN_PASSWORD. Setup
#            (the wizard) passes all three; the password is never an argument.
#   -Site    a folder holding this site's engine.yaml (and .env, if cameras
#            need passwords). Only needed the first time: after that the copy
#            in C:\VisionGuard\data is the one that counts.
#   -NoPrompt
#            never ask anything; Setup always passes it, because nobody can
#            see or answer a question in its hidden window.
#
# Remote access (spec 020) needs no parameter: when the environment variable
# VG_NETBIRD_SETUP_KEY holds a NetBird setup key (Setup's "Remote access" page),
# step 5 installs NetBird from the kit and joins this PC to the site's private
# network with it. Like the password, the key is never an argument or a file.
#
# What it does, in order, stopping at the first step that fails:
#   1. copies the program to C:\VisionGuard\app, makes data\ and logs\
#   2. Python 3.14, from the installer in the kit, if it is missing
#   3. app\.venv with torch, requirements.txt, TensorRT and the appearance
#      matcher (needs internet)
#   4. copies the models, checks every one the site needs, builds TensorRT
#   5. remote access (NetBird), when there is a key or it is already here, and
#      the site certificate - covering the NetBird address too - and trusts the
#      root on this machine
#   6. the two services, folder rights for them, the startup task that starts
#      them at boot unless the switch in VisionGuard Control is off, and the
#      firewall
#   7. the first administrator, if there is none
#   8. one desktop shortcut, "VisionGuard", that opens the console
#   9. starts both services and waits for https://localhost/healthz
#
# Nothing here waits for the keyboard when run hidden by Setup: the Python
# installer is /quiet, pip never asks, and step 7 only prompts at a real console.
#
# Safe to run twice: every step checks what is already there first.

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Models,
    [Parameter(Mandatory)] [string]$Root,
    [string]$Site,
    [string]$AdminEmail,
    [string]$AdminName,
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'

# Out of the environment at once, so pip, the Python installer and every other
# child of steps 1-6 never inherit it. Step 7 hands it to create_user.py alone.
$adminPassword = $env:VG_ADMIN_PASSWORD
Remove-Item Env:\VG_ADMIN_PASSWORD -ErrorAction SilentlyContinue
# The same for the NetBird setup key: step 5 hands it to `netbird up` alone.
$netbirdKey = $env:VG_NETBIRD_SETUP_KEY
Remove-Item Env:\VG_NETBIRD_SETUP_KEY -ErrorAction SilentlyContinue

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
    # /E without /MIR deletes nothing, so the venv and the models already in
    # $App stay. The kit carries the appearance matcher's code under app\models
    # (and no weights), so models is copied; .venv is left out.
    robocopy $KitApp $App /E /NFL /NDL /NJH /NJS /NP /XD .venv | Out-Null
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
# From $App, where step 1 put the kit's copy: this also works on a second run.
Run $Python @('-m', 'pip', 'install', (Join-Path $App 'models\reid\loiterwatch')) 'installing the appearance matcher failed'
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

# --- 5. remote access and certificate ----------------------------------------------
Step 5 'Remote access and site certificate'
# Remote access (spec 020): NetBird joins this PC to the site's private network,
# so phones and laptops the owner enrolled reach the console from anywhere and
# nothing else can. There is no public address and nothing opens on the router.
# Only with a setup key from Setup, or when NetBird is already here.
$netbird = Join-Path $env:ProgramFiles 'NetBird\netbird.exe'
$netbirdIp = $null
function Get-NetbirdStatus {
    # 'Continue' here: under 'Stop', Windows PowerShell turns a native
    # program's error output into a terminating error once it is redirected.
    $ErrorActionPreference = 'Continue'
    $out = & $netbird status --json 2>$null
    try { ($out | Out-String) | ConvertFrom-Json } catch { $null }
}
if ($netbirdKey -and -not (Test-Path $netbird)) {
    $msi = Get-ChildItem (Join-Path $App 'bin') -Filter 'netbird_installer_*_windows_amd64.msi' `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $msi) { Stop-Install "the NetBird installer is missing from the kit ($App\bin)." }
    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
        '/i', "`"$($msi.FullName)`"", '/quiet', '/norestart')
    if ($p.ExitCode -notin 0, 3010) { Stop-Install "installing NetBird failed (msiexec exit code $($p.ExitCode))." }
    Ok "NetBird installed from $($msi.Name)"
}
if (Test-Path $netbird) {
    # Its background service must start with Windows, with nobody signed in.
    $nbService = Get-Service -Name netbird -ErrorAction SilentlyContinue
    if ($nbService) {
        if ($nbService.StartType -ne 'Automatic') { Set-Service -Name netbird -StartupType Automatic }
        if ($nbService.Status -ne 'Running') { Start-Service -Name netbird }
    }
    $status = Get-NetbirdStatus
    if ($status -and $status.management.connected) {
        Skip 'NetBird is already connected (no new key needed)'
    } elseif ($netbirdKey) {
        # Joined with the key only, never through a sign-in page: a device that
        # signs in drops off after a day, a key-joined one never does. The key
        # is in this one child's environment (NB_SETUP_KEY), never its command line.
        # Whether it worked is read from its status below, not its exit code.
        $env:NB_SETUP_KEY = $netbirdKey
        $ErrorActionPreference = 'Continue'
        try { & $netbird up }
        finally {
            Remove-Item Env:\NB_SETUP_KEY -ErrorAction SilentlyContinue
            $ErrorActionPreference = 'Stop'
        }
        $deadline = (Get-Date).AddSeconds(60)
        do {
            $status = Get-NetbirdStatus
            if ($status -and $status.management.connected -and $status.netbirdIp) { break }
            Start-Sleep -Seconds 3
        } while ((Get-Date) -lt $deadline)
        if (-not ($status -and $status.management.connected)) {
            $why = if ($status -and $status.management.error) { $status.management.error } else { 'no answer' }
            Stop-Install ("NetBird did not connect: $why. Check this PC has internet, and that the setup " +
                          'key is new: each key works once, for one day. Make a new one and run Setup again.')
        }
        Ok 'NetBird joined the site''s private network with the setup key'
    } else {
        Write-Host ('    WARNING  NetBird is installed but not connected, so remote access is off. Make a ' +
                    'setup key in the NetBird dashboard and run Setup again with it.') -ForegroundColor Yellow
    }
    if ($status -and $status.netbirdIp) { $netbirdIp = ($status.netbirdIp -split '/')[0] }
    if ($netbirdIp) {
        Run $Python @((Join-Path $App 'engine\tools\tls_names.py'), 'add', $netbirdIp) `
            'adding the NetBird address to the certificate''s names failed'
        Ok "remote addresses: https://$netbirdIp/ (console) and https://${netbirdIp}:8443/ (phone app)"
    }
} else {
    Skip 'remote access is not set up (no NetBird setup key was given)'
}
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
        # WinSW 2.12 has no `refresh` (that is WinSW 3); the second install
        # drill stopped here on it. The wrapper reads its XML every time the
        # service starts, so the files copied above are the update. What
        # Windows recorded at install (account, start mode) stays as it was.
        Ok "$name kept; its program and settings file were updated"
    } else {
        Run (Join-Path $serviceDir "$name.exe") @('install') "installing $name failed"
        Ok "$name installed"
    }
}
# Anyone signed in at this PC may query, start and stop the two services, so the
# control icon works without an administrator prompt. SDDL, per ACE:
#   SY / BA  SYSTEM and Administrators keep full control (BA also keeps delete and owner rights)
#   IU       Interactive Users: CC query config, LC query status, SW enum dependents,
#            RP start, WP stop, DT pause, LO interrogate, CR user control, RC read permissions
#   SU       services themselves: query only
$serviceSddl = 'D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)' +
               '(A;;CCLCSWRPWPDTLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)'
foreach ($name in $Services) {
    Run sc.exe @('sdset', $name, $serviceSddl) "setting who may stop and start $name failed"
    Ok "anyone signed in at this PC may stop and start $name"
}
# Both services start on demand. Windows no longer starts them by itself; the
# startup task below does, when data\autostart.txt does not say "off". Letting
# users change the switch therefore never lets them change what a service runs.
foreach ($name in $Services) {
    Run sc.exe @('config', $name, 'start=', 'demand') "setting $name to start on demand failed"
}
Ok 'both services now start through the startup task (crash restarts still apply)'
# The task's few lines are inside the task itself, never a file from $App: that
# folder is writable by any user (Mohamed's decision, 18 Oct 2026), and a task
# that runs as SYSTEM must not run a file anybody can replace. The only thing it
# reads from disk is the first line of autostart.txt, compared with 'off'; that
# text is never run.
$bootLines = @'
$f = 'C:\VisionGuard\data\autostart.txt'
$l = ''
if (Test-Path -LiteralPath $f) { $l = '' + (Get-Content -LiteralPath $f -TotalCount 1) }
if ($l.Trim() -ne 'off') { Start-Service visionguard-engine; Start-Service visionguard-front }
'@
$bootCommand = (($bootLines -split '\r?\n' | Where-Object { $_ }) -join '; ')
# The switch is the user's choice: made "on" the first time, never overwritten.
$autostart = Join-Path $Data 'autostart.txt'
if (-not (Test-Path $autostart)) { Set-Content -Path $autostart -Value 'on' -Encoding ASCII }
$taskName = 'VisionGuard start at boot'
$taskAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$bootCommand`""
$taskTrigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger `
    -Principal $taskPrincipal -Settings $taskSettings -Force | Out-Null
# Signed-in users may READ the task (never change or run it), so VisionGuard
# Control can say truthfully whether automatic start is set up; by default only
# administrators can see a SYSTEM task.
try {
    $scheduler = New-Object -ComObject Schedule.Service
    $scheduler.Connect()
    $scheduler.GetFolder('\').GetTask($taskName).SetSecurityDescriptor('D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;AU)', 0)
} catch {
    Write-Host ("    WARNING  users cannot read the startup task, so VisionGuard Control may say it " +
                "cannot tell whether automatic start is set up: $($_.Exception.Message)") -ForegroundColor Yellow
}
Ok 'VisionGuard starts when the PC starts unless the switch in VisionGuard Control is off'
# The service account is given write access to data\ and logs\, where it writes.
foreach ($dir in @($Data, $Logs)) {
    Run icacls @($dir, '/grant', 'NT AUTHORITY\LocalService:(OI)(CI)M', '/Q') "giving the service rights on $dir failed"
}
Ok 'LocalService was given write access to data\ and logs\'
foreach ($port in 443, 8443) {
    $rule = "VisionGuard HTTPS $port"
    if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
        # An older run, or someone, may have left it open on Public too.
        Set-NetFirewallRule -DisplayName $rule -Profile Private,Domain
        Skip "firewall: TCP $port rule is already there (kept on private networks)"
    } else {
        New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP `
            -LocalPort $port -Action Allow -Profile Private,Domain | Out-Null
        Ok "firewall: TCP $port open on private networks"
    }
}
# Windows makes its own allow rule when somebody answers its firewall prompt for
# a program ("Query User" rules): for caddy.exe that opens both ports to every
# address on Public networks, which is the hole the two rules above keep shut.
# Found on the first workstation on 19 Oct 2026. Turned off, never deleted, so
# they are not made again and anyone can see what was done.
$ourPrograms = @((Join-Path $App 'bin\caddy.exe'), $Python)
foreach ($filter in @(Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue |
                      Where-Object { $p = $_.Program; $ourPrograms | Where-Object { $_ -ieq $p } })) {
    $stray = $filter | Get-NetFirewallRule
    if ($stray.Enabled -eq 'True' -and $stray.Direction -eq 'Inbound' -and $stray.Action -eq 'Allow' -and
            $stray.DisplayName -notlike 'VisionGuard*') {
        Disable-NetFirewallRule -Name $stray.Name
        Ok "firewall: turned off '$($stray.DisplayName)', which Windows made for $($filter.Program) (open to everyone on $($stray.Profile) networks)"
    }
}
# Remote access (spec 020): both ports from NetBird's addresses only, and only
# on its own adapter, because some internet providers use 100.64/10 too. Every
# profile, because which one Windows gives the NetBird adapter is not documented.
$remoteRule = 'VisionGuard remote access (NetBird)'
$nbAlias = $null
if ($netbirdIp) {
    $nbAlias = (Get-NetIPAddress -IPAddress $netbirdIp -ErrorAction SilentlyContinue |
                Select-Object -First 1).InterfaceAlias
}
if ($nbAlias) {
    Remove-NetFirewallRule -DisplayName $remoteRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $remoteRule -Direction Inbound -Protocol TCP -LocalPort 443, 8443 `
        -RemoteAddress 100.64.0.0/10 -InterfaceAlias $nbAlias -Profile Any -Action Allow | Out-Null
    Ok "firewall: TCP 443 and 8443 open to the site's private network only, on '$nbAlias'"
} elseif ($netbirdIp) {
    Write-Host ("    WARNING  NetBird's address $netbirdIp is on no network adapter, so the firewall " +
                'rule for remote access was not made. Restart the PC and run Setup again.') -ForegroundColor Yellow
} else {
    Skip 'firewall: no remote access rule (remote access is not set up)'
}
# Public stays closed on purpose. Say so when this machine is on such a network.
foreach ($net in @(Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public')) {
    Write-Host ("    WARNING  '$($net.Name)' is a Public network, so phones and other PCs " +
                'cannot reach the console until Windows marks it Private. To do that: ' +
                "Set-NetConnectionProfile -InterfaceAlias '$($net.InterfaceAlias)' -NetworkCategory Private") `
        -ForegroundColor Yellow
}

# --- 7. first administrator -------------------------------------------------------
Step 7 'First administrator'
& $Python -c "import sys; sys.path[:0] = [r'$App\engine', r'$App\engine\tools']; import create_user; from vg.auth.store import UserStore; s = UserStore(create_user._database()); sys.exit(0 if any(u.role == 'admin' and not u.disabled for u in s.users()) else 3)"
if ($LASTEXITCODE -eq 0) {
    Skip 'an administrator already exists'
} elseif ($AdminEmail -and $AdminName -and $adminPassword) {
    # Back in the environment for this one child only, never on a command line.
    $env:VG_ADMIN_PASSWORD = $adminPassword
    try {
        Run $Python @((Join-Path $App 'engine\tools\create_user.py'), '--email', $AdminEmail,
                      '--name', $AdminName, '--role', 'admin',
                      '--password-from-env', 'VG_ADMIN_PASSWORD') 'creating the administrator failed'
    } finally {
        Remove-Item Env:\VG_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    }
    Ok "administrator $AdminEmail created"
} elseif (-not $NoPrompt -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host '    Type the head''s name, email and a password. There is no default password.'
    Run $Python @((Join-Path $App 'engine\tools\create_user.py'), '--role', 'admin') 'creating the administrator failed'
} else {
    Stop-Install 'there is no administrator account yet; run Setup again and fill in the first administrator page'
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
# Before Start-Service: a start that fails at once writes its file within a
# second, and a later timestamp would miss it.
$started = Get-Date
foreach ($name in $Services) { Start-Service -Name $name; Ok "$name started" }
$deadline = $started.AddMinutes(3)
$failure = Join-Path $Logs 'start-failure.txt'
do {
    # serve.py deletes this file when it starts and writes it when the start
    # fails, so one written since $started describes this start.
    if ((Test-Path $failure) -and (Get-Item $failure).LastWriteTime -ge $started) {
        Stop-Install ("the engine failed to start: $((Get-Content $failure -Raw).Trim()) " +
                      'The service retries 3 times by itself. Fix the cause, then run: ' +
                      'Start-Service visionguard-engine')
    }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'https://localhost/healthz' -TimeoutSec 5
        if ($r.StatusCode -eq 200) { Ok 'https://localhost/healthz answers'; break }
    } catch { }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) {
    $why = if (Test-Path $failure) { Get-Content $failure -Raw } else { "see $Logs" }
    Stop-Install "the engine did not answer within 3 minutes: $why"
}

Write-Host "`n  VisionGuard is installed. Open it from the VisionGuard icon on the desktop.`n" -ForegroundColor Green
