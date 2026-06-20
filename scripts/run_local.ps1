Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $env:PORT) { $env:PORT = "5000" }
if (-not $env:SOUNDBANK_ENABLED) { $env:SOUNDBANK_ENABLED = "true" }
if (-not $env:SOUNDBANK_SHOW_STARTER_DEMOS) { $env:SOUNDBANK_SHOW_STARTER_DEMOS = "true" }
if (-not $env:SOUNDBANK_INIT_DB) { $env:SOUNDBANK_INIT_DB = "false" }
if (-not $env:SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS) { $env:SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS = "false" }

Write-Host "Starting SoundBank at http://127.0.0.1:$env:PORT/soundbank"
python (Join-Path $ProjectRoot "src\app.py")
