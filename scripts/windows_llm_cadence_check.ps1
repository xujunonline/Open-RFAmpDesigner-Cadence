# Windows end-to-end check for the subscription LLM transports and the Cadence backend.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows_llm_cadence_check.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\windows_llm_cadence_check.ps1 -RunS9 -S9Calls 40
#
# One-time setup (interactive, done by the user; no API keys needed):
#   npm i -g @anthropic-ai/claude-code   ; claude auth login --claudeai   (Claude Pro/Max account)
#   npm i -g @openai/codex
#   $env:CODEX_HOME="$env:USERPROFILE\.codex-cli"; mkdir $env:CODEX_HOME -Force; codex login
#   (a separate CODEX_HOME keeps the Codex desktop app's ~\.codex\config.toml untouched;
#    the pipeline picks ~\.codex-cli up automatically)
#
# Every step is logged to results\windows_checks\<timestamp>\ ; summary.txt lists exit codes.
param(
    [switch]$SkipClaude,
    [switch]$SkipCodex,
    [switch]$SkipCadence,
    [switch]$RunS9,
    [int]$S9Calls = 40
)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONPATH = Join-Path $repo "src"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:ORFADC_RUN_LIVE_SSH_AUDIT = "0"
# Make sure the CLIs use the subscription login, not a paid API key that may be set globally.
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$cliHome = Join-Path $env:USERPROFILE ".codex-cli"
if ((-not $env:CODEX_HOME) -and (Test-Path $cliHome)) { $env:CODEX_HOME = $cliHome }

$ts = Get-Date -Format "yyyyMMddTHHmmss"
$out = Join-Path $repo "results\windows_checks\$ts"
New-Item -ItemType Directory -Force $out | Out-Null
$summary = Join-Path $out "summary.txt"
"started $ts" | Out-File -Encoding utf8 $summary

function Step([string]$name, [scriptblock]$block) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    $log = Join-Path $out "$name.log"
    $global:LASTEXITCODE = 0
    $lines = & $block 2>&1 | ForEach-Object { "$_" }
    $code = $global:LASTEXITCODE
    $lines | Out-Host
    $lines | Out-File -Encoding utf8 $log
    "$name exit=$code" | Out-File -Append -Encoding utf8 $summary
}

Step "01_env" {
    python --version
    node --version
    python -m pip install -q -r config\requirements_repro.txt
    python -c "import numpy, yaml, matplotlib, mcp; print('python deps ok')"
}
Step "02_pytest" {
    python -m pytest tests\test_repro_core.py tests\test_repro_llm_cli.py tests\test_repro_cadence_backend.py -q -p no:cacheprovider
}

if (-not $SkipClaude) {
    Step "10_claude_cli" {
        $c = Get-Command claude -ErrorAction SilentlyContinue
        if ($c) { $c.Source; claude --version; claude auth status }
        else { "claude CLI not found. Install: npm i -g @anthropic-ai/claude-code ; then: claude auth login --claudeai"; $global:LASTEXITCODE = 9 }
    }
    Step "11_claude_llm_check" {
        python -m orfadc.repro.bench llm-check --policy claude-cli --out $out
    }
}

if (-not $SkipCodex) {
    Step "20_codex_cli" {
        $c = Get-Command codex -ErrorAction SilentlyContinue
        if ($c) { $c.Source; "CODEX_HOME=$env:CODEX_HOME"; codex --version; codex login status }
        else { "codex CLI not found. Install: npm i -g @openai/codex ; then log in (see header)"; $global:LASTEXITCODE = 9 }
    }
    Step "21_codex_mcp_llm_check" {
        python -m orfadc.repro.bench llm-check --policy codex-mcp --out $out
    }
}

if (-not $SkipCadence) {
    Step "30_cadence_check" {
        if (-not (Test-NetConnection 192.168.44.128 -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
            "Cadence VM 192.168.44.128:22 unreachable - start the VMware VM (and check its IP) first."
        }
        python -m orfadc.repro.bench cadence-check --spec S2 --out $out
    }
}

if ($RunS9) {
    $env:ORFADC_LLM_MAX_CALLS = "$S9Calls"
    if (-not $SkipClaude) {
        Step "40_S9_claude_cli" { python -m orfadc.repro.bench design --spec S9 --seed 0 --policy claude-cli --out $out }
    }
    if (-not $SkipCodex) {
        Step "41_S9_codex_mcp" { python -m orfadc.repro.bench design --spec S9 --seed 0 --policy codex-mcp --out $out }
    }
}

Write-Host ""
Write-Host "Done. Logs: $out" -ForegroundColor Green
Get-Content $summary
