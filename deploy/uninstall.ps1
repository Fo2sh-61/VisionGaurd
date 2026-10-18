# Remove VisionGuard from this machine (spec 016). Run hidden, as administrator,
# by the uninstaller. Best effort and safe to run twice: a problem is reported
# and the next step still runs. It never touches C:\VisionGuard\data, where the
# faces, the database and the site's settings live.

$ErrorActionPreference = 'Continue'

$Home_    = 'C:\VisionGuard'
$App      = Join-Path $Home_ 'app'
$Data     = Join-Path $Home_ 'data'
$Services = @('visionguard-engine', 'visionguard-front')

function Step($n, $what) { Write-Host "`n[$n] $what" }
function Ok($what)       { Write-Host "    ok    $what" }
function Skip($what)     { Write-Host "    skip  $what" }
function Warn($what)     { Write-Host "    WARNING  $what" }

# --- 1. the control icon ----------------------------------------------------------
Step 1 'Control icon'
$procs = @(Get-Process -Name 'VisionGuardControl' -ErrorAction SilentlyContinue)
if ($procs.Count -eq 0) { Skip 'the control icon is not running' }
foreach ($proc in $procs) {
    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop; Ok "ended the control icon (process $($proc.Id))" }
    catch { Warn "could not end the control icon (process $($proc.Id)): $($_.Exception.Message)" }
}

# --- 2. services ---------------------------------------------------------------------
Step 2 'Services'
foreach ($name in $Services) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) { Skip "$name is not installed"; continue }
    if ($svc.Status -ne 'Stopped') {
        try { Stop-Service -Name $name -Force -ErrorAction Stop; Ok "stopped $name" }
        catch { Warn "could not stop ${name}: $($_.Exception.Message)" }
    }
    $wrapper = Join-Path $App "service\$name.exe"
    if (Test-Path $wrapper) {
        & $wrapper uninstall | Out-Null
    } else {
        & sc.exe delete $name | Out-Null
    }
    Start-Sleep -Seconds 1
    if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
        Warn "$name is still listed; it goes away when this PC restarts"
    } else {
        Ok "removed $name"
    }
}

# --- 2b. startup task ----------------------------------------------------------------
Step '2b' 'Startup task'
$taskName = 'VisionGuard start at boot'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop; Ok "removed the task '$taskName'" }
    catch { Warn "could not remove the task '${taskName}': $($_.Exception.Message)" }
} else {
    Skip "no task '$taskName'"
}

# --- 3. firewall -----------------------------------------------------------------------
Step 3 'Firewall'
foreach ($port in 443, 8443) {
    $rule = "VisionGuard HTTPS $port"
    if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
        try { Remove-NetFirewallRule -DisplayName $rule -ErrorAction Stop; Ok "removed the firewall rule '$rule'" }
        catch { Warn "could not remove the firewall rule '$rule': $($_.Exception.Message)" }
    } else {
        Skip "no firewall rule '$rule'"
    }
}

# --- 4. trusted root ---------------------------------------------------------------------
Step 4 'Site certificate'
# site_cert.py names the root O=VisionGuard, CN=VisionGuard site root. Windows may print
# those two parts in either order, so compare the parts; it must also be self-signed.
$wanted = (@('CN=VisionGuard site root', 'O=VisionGuard') | Sort-Object) -join '|'
$roots = @(Get-ChildItem Cert:\LocalMachine\Root | Where-Object {
    ((@($_.Subject -split ',\s*') | Sort-Object) -join '|') -eq $wanted -and $_.Subject -eq $_.Issuer
})
if ($roots.Count -eq 0) { Skip 'the VisionGuard site root is not trusted on this machine' }
foreach ($cert in $roots) {
    try { Remove-Item -Path $cert.PSPath -ErrorAction Stop; Ok "no longer trusts the VisionGuard site root ($($cert.Thumbprint))" }
    catch { Warn "could not remove the VisionGuard site root: $($_.Exception.Message)" }
}

# --- 5. desktop shortcut -------------------------------------------------------------------
Step 5 'Desktop shortcut'
foreach ($link in @('C:\Users\Public\Desktop\VisionGuard.lnk', 'C:\Users\Public\Desktop\VisionGuard Control.lnk')) {
    if (Test-Path $link) {
        try { Remove-Item -Path $link -ErrorAction Stop; Ok "removed $link" }
        catch { Warn "could not remove ${link}: $($_.Exception.Message)" }
    } else {
        Skip "no $link"
    }
}

Write-Host "`n  Your data folder was kept: $Data`n  (faces, database and settings). Delete it yourself only if you are sure.`n"
exit 0
