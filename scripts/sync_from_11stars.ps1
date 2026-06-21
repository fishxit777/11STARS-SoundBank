param(
    [string]$SourceRoot,
    [switch]$ConfirmLegacySourceSync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ConfirmLegacySourceSync) {
    throw "Legacy sync is disabled by default because 11STARS-SoundBank is now the SoundBank source of truth. Re-run with -ConfirmLegacySourceSync only after comparing old and new files."
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WorkspaceRoot = Resolve-Path (Join-Path $ProjectRoot "..")

if (-not $SourceRoot) {
    $SourceCandidate = Get-ChildItem -LiteralPath $WorkspaceRoot -Directory -Recurse -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "11STARS" -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "soundbank.py"))
        } |
        Select-Object -First 1

    if (-not $SourceCandidate) {
        throw "Could not auto-locate a 11STARS folder with soundbank.py under: $($WorkspaceRoot.Path)"
    }

    $SourceRoot = $SourceCandidate.FullName
}

$SourceSoundBank = Join-Path $SourceRoot "soundbank.py"
$SourceAssets = Join-Path $SourceRoot "static\soundbank_assets"
$TargetSoundBank = Join-Path $ProjectRoot "src\soundbank.py"
$TargetAssets = Join-Path $ProjectRoot "static\soundbank_assets"

if (-not (Test-Path -LiteralPath $SourceSoundBank)) {
    throw "Source soundbank.py not found: $SourceSoundBank"
}
if (-not (Test-Path -LiteralPath $SourceAssets)) {
    throw "Source asset folder not found: $SourceAssets"
}

New-Item -ItemType Directory -Force -Path $TargetAssets | Out-Null
Copy-Item -LiteralPath $SourceSoundBank -Destination $TargetSoundBank -Force

Get-ChildItem -LiteralPath $SourceAssets -File |
    Where-Object { $_.Name -match '\.png$|-preview\.wav$|-rights\.txt$' } |
    ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $TargetAssets -Force
    }

$MasterFiles = @(Get-ChildItem -LiteralPath $TargetAssets -File | Where-Object { $_.Name -match '-master\.wav$' })
if ($MasterFiles.Count -gt 0) {
    throw "Blocked: master WAV files exist in public assets: $($MasterFiles.Count)"
}

$Images = @(Get-ChildItem -LiteralPath $TargetAssets -File | Where-Object { $_.Name -match '\.png$' })
$Previews = @(Get-ChildItem -LiteralPath $TargetAssets -File | Where-Object { $_.Name -match '-preview\.wav$' })
$Rights = @(Get-ChildItem -LiteralPath $TargetAssets -File | Where-Object { $_.Name -match '-rights\.txt$' })

[PSCustomObject]@{
    ProjectRoot = $ProjectRoot.Path
    SourceRoot = $SourceRoot
    Images = $Images.Count
    PreviewWav = $Previews.Count
    RightsTxt = $Rights.Count
    MasterWav = $MasterFiles.Count
} | Format-List

& (Join-Path $PSScriptRoot "verify_standalone.ps1")
