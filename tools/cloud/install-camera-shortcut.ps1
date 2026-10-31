<#
.SYNOPSIS
  Put "VisionGuard Cloud Camera" on the desktop. specs/021-cloud-trial.

.DESCRIPTION
  Double-clicking it opens tools/cloud/webcam_sender.py in a small window:
  paste the day's address from the Kaggle notebook, type the password, press
  Start, and this laptop's webcam is sent to the cloud engine's cam-webcam.

  Runs with pythonw, so no console window opens behind it.

.EXAMPLE
  .\tools\cloud\install-camera-shortcut.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Script = Join-Path $Root 'tools\cloud\webcam_sender.py'
$Icon = Join-Path $Root 'assets\visionguard.ico'

$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw 'pythonw was not found. Install Python, or put it on PATH.' }

$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'VisionGuard Cloud Camera.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$Script`""
$shortcut.WorkingDirectory = $Root
if (Test-Path $Icon) { $shortcut.IconLocation = "$Icon,0" }
$shortcut.Description = 'Send this laptop''s webcam to the VisionGuard cloud trial'
$shortcut.Save()

Write-Host "  created $link"
