<#
.SYNOPSIS
  Make the cloud trial's code dataset from the current commit. specs/021-cloud-trial.

.DESCRIPTION
  Builds the console (web/dist), then writes visionguard-trial.zip:
  `git archive HEAD` plus the fresh web/dist, under one visionguard/ folder.
  Upload the zip as a new version of your PRIVATE Kaggle dataset
  "visionguard-code".

  From a commit, never the working tree: what runs in the cloud is then
  exactly a commit you can name. The footage and most model weights are not
  in git, so they are not in this zip; they live in the separate private
  models dataset. (The falls checkpoints are in git and come with the code.)

  Refuses when tracked files have uncommitted changes.

.EXAMPLE
  .\tools\cloud\pack.ps1
#>
[CmdletBinding()]
param(
  [string]$Out = (Join-Path (Get-Location) 'visionguard-trial.zip')
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo

$dirty = git status --porcelain --untracked-files=no
if ($dirty) {
  Write-Host 'Tracked files have uncommitted changes. Commit first, so the cloud runs a commit you can name:' -ForegroundColor Red
  $dirty | ForEach-Object { Write-Host "  $_" }
  exit 1
}
$commit = (git rev-parse --short HEAD).Trim()

Write-Host '  building the console (web/dist) ...'
Push-Location (Join-Path $repo 'web')
try {
  npm.cmd run build | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'npm run build failed' }
} finally { Pop-Location }

if (Test-Path $Out) { Remove-Item $Out -Confirm:$false }
# No archives inside the archive. Kaggle unpacks nested zips too, and
# models/reid/loiterwatch.zip (an unused copy of models/reid/loiterwatch/)
# unpacked onto the real folder and failed the upload:
# "Directory already exists: loiterwatch".
git archive --format=zip --prefix=visionguard/ -o $Out HEAD -- . ':(exclude,glob)**/*.zip'
if ($LASTEXITCODE -ne 0) { throw 'git archive failed' }

Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($Out, 'Update')
try {
  $dist = Join-Path $repo 'web\dist'
  Get-ChildItem $dist -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($dist.Length + 1).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
      $zip, $_.FullName, "visionguard/web/dist/$relative") | Out-Null
  }
} finally { $zip.Dispose() }

$size = [math]::Round((Get-Item $Out).Length / 1MB, 1)
Write-Host ''
Write-Host "  wrote $Out  ($size MB, commit $commit)"
Write-Host '  upload it as a new version of your private Kaggle dataset "visionguard-code"'
