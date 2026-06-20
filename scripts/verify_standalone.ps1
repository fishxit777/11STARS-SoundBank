Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

python (Join-Path $PSScriptRoot "verify_standalone.py")
if ($LASTEXITCODE -ne 0) {
    throw "Standalone Python verification failed."
}

$SecretPattern = "rnd_[A-Za-z0-9]|sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_[A-Za-z0-9]|xox[baprs]-|SG\.[A-Za-z0-9_-]|AKIA[0-9A-Z]{16}"
$Matches = @(rg -n $SecretPattern $ProjectRoot 2>$null)
if ($LASTEXITCODE -eq 0 -and $Matches.Count -gt 0) {
    throw "Potential secret-like token pattern found. Output suppressed; review locally before publishing."
}
if ($LASTEXITCODE -gt 1) {
    throw "rg failed with exit code $LASTEXITCODE."
}

Write-Host "PASS: no common token patterns"
