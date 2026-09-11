# Put a VisionGuard shortcut on the desktop.
#
# Run once. Run it again after moving the repo, or after re-generating the
# icon - a .lnk stores absolute paths, so it does not follow the folder.
#
#     .\tools\install-shortcut.ps1
#     .\tools\install-shortcut.ps1 -Mobile     the phone app's, beside it
#     .\tools\install-shortcut.ps1 -Remove     (add -Mobile for that one)
#
# The shortcut points at `launch.ps1`, which is the file to change if you want
# different behaviour. Nothing about the launcher lives in the .lnk except
# where to find it and what to draw.

[CmdletBinding()]
param(
    [switch]$Remove,
    # The phone app's shortcut instead: "VisionGuard Mobile", with the
    # phone-shaped icon, running `launch.ps1 -Mobile`.
    [switch]$Mobile,
    # Where to put it. Defaults to the desktop of whoever runs this; nothing
    # is written anywhere else and no administrator rights are needed.
    [string]$Directory = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Launcher = Join-Path $Root 'launch.ps1'
if ($Mobile) {
    $Icon = Join-Path $Root 'assets\visionguard-mobile.ico'
    $Link = Join-Path $Directory 'VisionGuard Mobile.lnk'
    $Flags = ' -Mobile'
    $What = 'Start the VisionGuard engine, console and phone app'
} else {
    $Icon = Join-Path $Root 'assets\visionguard.ico'
    $Link = Join-Path $Directory 'VisionGuard.lnk'
    $Flags = ''
    $What = 'Start the VisionGuard engine and console'
}

if ($Remove) {
    if (Test-Path $Link) {
        Remove-Item $Link -Force
        Write-Host "  removed $Link" -ForegroundColor Green
    } else {
        Write-Host "  nothing to remove at $Link" -ForegroundColor DarkGray
    }
    exit 0
}

# Checked rather than assumed: a shortcut to a file that is not there fails
# with a Windows dialog that says nothing useful about which file.
foreach ($required in @($Launcher, $Icon)) {
    if (-not (Test-Path $required)) {
        Write-Host "  [FAIL] missing $required" -ForegroundColor Red
        if ($required -eq $Icon) {
            Write-Host '         build it with: python tools/make_icon.py' -ForegroundColor DarkGray
        }
        exit 1
    }
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($Link)

# powershell.exe rather than pwsh: it is on every Windows machine, and this
# launcher uses nothing newer than it provides.
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

# -NoProfile so a slow or noisy user profile cannot delay or clutter the
# start. -ExecutionPolicy Bypass because a fresh Windows refuses to run any
# local .ps1 at all, and this one is in the repo the user already trusts.
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`"$Flags"

# So relative paths inside the scripts resolve, and so `npm run dev` starts in
# a folder that has the project in it.
$shortcut.WorkingDirectory = $Root
$shortcut.IconLocation = "$Icon,0"
$shortcut.Description = $What
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host ''
Write-Host '  VisionGuard' -ForegroundColor Cyan
Write-Host "  [ ok ] shortcut  $Link" -ForegroundColor Green
Write-Host "  [ ok ] runs      $Launcher$Flags" -ForegroundColor Green
Write-Host "  [ ok ] icon      $Icon" -ForegroundColor Green
Write-Host ''
Write-Host '  Double-click it. Closing the window stops everything.' -ForegroundColor DarkGray
Write-Host ''
