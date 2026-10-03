# One-click setup of the Codex CLI for the codex-mcp pipeline (ChatGPT subscription, no API key).
# Uses a separate CODEX_HOME (%USERPROFILE%\.codex-cli) so the Codex desktop app's
# %USERPROFILE%\.codex\config.toml is never read or modified.
#   Double-click scripts\setup_codex_cli.cmd   (or run this .ps1 from PowerShell)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repo "results\windows_checks\setup_codex_cli.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Force | Out-Null

Write-Host "[1/4] Checking Node.js / npm" -ForegroundColor Cyan
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "npm not found. Install Node.js LTS from https://nodejs.org and run this again." -ForegroundColor Red
    Stop-Transcript | Out-Null; Read-Host "Press Enter to close"; exit 1
}
node --version

Write-Host "[2/4] Installing / updating @openai/codex" -ForegroundColor Cyan
npm i -g @openai/codex
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
codex --version

Write-Host "[3/4] Signing in with your ChatGPT account (a browser window will open)" -ForegroundColor Cyan
$env:CODEX_HOME = Join-Path $env:USERPROFILE ".codex-cli"
New-Item -ItemType Directory -Force $env:CODEX_HOME | Out-Null
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Write-Host "CODEX_HOME = $env:CODEX_HOME"
codex login

Write-Host "[4/4] Login status" -ForegroundColor Cyan
codex login status
if ($LASTEXITCODE -eq 0) { Write-Host "Codex CLI ready. The pipeline uses $env:CODEX_HOME automatically." -ForegroundColor Green }
else { Write-Host "Login not confirmed - see $log" -ForegroundColor Yellow }
Stop-Transcript | Out-Null
Read-Host "Press Enter to close"
