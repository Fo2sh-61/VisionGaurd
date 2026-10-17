# Build an install kit for a site (spec 016, plan D). Developer machine only.
#
#     .\tools\make_release.ps1 v0.16.0 -Python D:\installers
#
#   <tag>     the git tag to package. The program comes from the tag, not
#             from the working folder, so uncommitted edits never ship.
#   -Python   a folder holding the python.org installer
#             (python-3.14.x-amd64.exe), which goes into the kit as-is.
#
# Writes release\<tag>\ and release\<tag>.zip:
#
#   <tag>\python-3.14.x-amd64.exe
#   <tag>\app\engine\              git archive of engine/ at the tag
#   <tag>\app\deploy\              git archive of deploy/ (install.ps1 is here)
#   <tag>\app\models\reid\loiterwatch\   the appearance matcher: code, not weights
#   <tag>\app\assets\visionguard.ico     the desktop shortcut's icon
#   <tag>\app\web\dist\  <tag>\app\mobile\dist\   both apps, built
#   <tag>\app\bin\                 caddy.exe and WinSW-x64.exe, checked
#                                  against deploy\versions.txt
#
# No model files: the owner supplies them at install time (P10-FR-003).

[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)] [string]$Tag,
    [Parameter(Mandatory)] [string]$Python
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Out = Join-Path $Repo "release\$Tag"
$App = Join-Path $Out 'app'

function Fail($why) { Write-Host "`n  NOT BUILT: $why`n" -ForegroundColor Red; exit 1 }
function Ok($what) { Write-Host "  ok  $what" -ForegroundColor Green }

Push-Location $Repo
try {
    git rev-parse --verify --quiet "refs/tags/$Tag" | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "there is no tag $Tag." }
    if (Test-Path $Out) { Fail "$Out already exists. Remove it to build again." }
    New-Item -ItemType Directory -Force -Path $App | Out-Null

    # The program, at the tag. The weights under models/ are never in git,
    # so only the matcher's source comes from there.
    $tar = Join-Path $Out 'src.tar'
    git archive --format=tar -o $tar $Tag engine deploy models/reid/loiterwatch assets/visionguard.ico
    if ($LASTEXITCODE -ne 0) { Fail 'git archive failed.' }
    tar -xf $tar -C $App
    Remove-Item $tar
    # loiterwatch's own examples carry a yolov8n.pt in git. The matcher never
    # loads it, and the kit holds no weights at all.
    Get-ChildItem -Recurse (Join-Path $App 'models') -Include *.pt, *.onnx, *.pth | Remove-Item
    Ok "program at $Tag"

    # Both apps, built from the tag's sources in a clean worktree.
    $wt = Join-Path $env:TEMP "vg-release-$Tag"
    git worktree add --detach $wt $Tag | Out-Null
    try {
        foreach ($ui in 'web', 'mobile') {
            Push-Location (Join-Path $wt $ui)
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { Fail "npm ci failed in $ui." }
            npm run build
            if ($LASTEXITCODE -ne 0) { Fail "npm run build failed in $ui." }
            Pop-Location
            New-Item -ItemType Directory -Force -Path (Join-Path $App $ui) | Out-Null
            Copy-Item -Recurse (Join-Path $wt "$ui\dist") (Join-Path $App "$ui\dist")
            Ok "$ui built"
        }
    } finally {
        git worktree remove --force $wt | Out-Null
    }

    # The two programs the owner downloaded, refused unless they are the
    # exact files versions.txt names.
    $versions = Join-Path $Repo 'deploy\versions.txt'
    if (-not (Test-Path $versions)) { Fail 'deploy\versions.txt is missing (task T004).' }
    New-Item -ItemType Directory -Force -Path (Join-Path $App 'bin') | Out-Null
    foreach ($line in Get-Content $versions) {
        if ($line -match '^\s*#' -or -not $line.Trim()) { continue }
        # <file> <version> <sha256>
        $file, $version, $sha = -split $line
        $path = Join-Path $Repo "deploy\bin\$file"
        if (-not (Test-Path $path)) { Fail "deploy\bin\$file is missing." }
        $actual = (Get-FileHash -Algorithm SHA256 $path).Hash
        if ($actual -ne $sha.ToUpper()) {
            Fail "deploy\bin\$file does not match versions.txt ($version): expected $sha, got $actual."
        }
        if ($file -like '*.zip') {
            Expand-Archive -Path $path -DestinationPath (Join-Path $Out 'unzip') -Force
            Copy-Item (Join-Path $Out 'unzip\caddy.exe') (Join-Path $App 'bin\caddy.exe')
            Remove-Item -Recurse (Join-Path $Out 'unzip')
        } else {
            Copy-Item $path (Join-Path $App 'bin')
        }
        Ok "$file $version, checked"
    }
    foreach ($need in 'caddy.exe', 'WinSW-x64.exe') {
        if (-not (Test-Path (Join-Path $App "bin\$need"))) { Fail "versions.txt names no file giving bin\$need." }
    }

    $installer = Get-ChildItem $Python -Filter 'python-3.14*-amd64.exe' | Select-Object -First 1
    if (-not $installer) { Fail "no python-3.14*-amd64.exe in $Python." }
    Copy-Item $installer.FullName $Out
    Ok "Python installer $($installer.Name)"

    $weights = Get-ChildItem -Recurse $App -Include *.pt, *.onnx, *.engine, *.pth
    if ($weights) { Fail "model files ended up in the kit: $($weights.Name -join ', ')." }

    Compress-Archive -Path "$Out\*" -DestinationPath "$Out.zip"
    Ok "release\$Tag.zip"
} finally {
    Pop-Location
}
