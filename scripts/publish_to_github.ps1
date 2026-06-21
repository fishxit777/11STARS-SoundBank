param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot

try {
    Write-Host "[publish] Running standalone verification..."
    & (Join-Path $PSScriptRoot "verify_standalone.ps1")

    $status = git status --porcelain
    if ($status) {
        Write-Host $status
        throw "Working tree is not clean. Commit or stash local changes before publishing."
    }

    $currentRemote = $null
    $remoteNames = @(git remote)
    if ($remoteNames -contains "origin") {
        $remoteOutput = git remote get-url origin
        if ($LASTEXITCODE -eq 0 -and $remoteOutput) {
            $currentRemote = $remoteOutput.Trim()
        }
    }

    if ($currentRemote) {
        if ($currentRemote -ne $RemoteUrl) {
            throw "origin already points to '$currentRemote'. Refusing to replace it automatically."
        }
        Write-Host "[publish] origin already set to $currentRemote"
    } else {
        Write-Host "[publish] Adding origin $RemoteUrl"
        git remote add origin $RemoteUrl
    }

    git branch -M main

    Write-Host "[publish] Pushing main..."
    git push -u origin main

    Write-Host "[publish] Done."
} finally {
    Pop-Location
}
