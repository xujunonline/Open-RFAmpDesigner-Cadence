# Unattended end-to-end run on the Windows host (double-click scripts\run_all_windows.cmd).
#  1. environment + subscription + Cadence checks (windows_llm_cadence_check.ps1)
#  2. LLM-backbone runs: {rule, claude-cli, codex-mcp} x {S9, S10, S9s, S10s}, seed 0
#  3. llm_table.md summary
#  4. Spectre-verified design run (Stage 4 on Cadence) if the Cadence VM is reachable
# Progress: results\windows_checks\<ts>_all\progress.txt ; DONE.txt is written at the end.
param([int]$Calls = 40, [string[]]$Specs = @("S9", "S10", "S9s", "S10s"))
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONPATH = Join-Path $repo "src"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$cliHome = Join-Path $env:USERPROFILE ".codex-cli"
if ((-not $env:CODEX_HOME) -and (Test-Path $cliHome)) { $env:CODEX_HOME = $cliHome }
$env:ORFADC_LLM_MAX_CALLS = "$Calls"

$ts = Get-Date -Format "yyyyMMddTHHmmss"
$out = Join-Path $repo "results\windows_checks\${ts}_all"
New-Item -ItemType Directory -Force $out | Out-Null
$progress = Join-Path $out "progress.txt"
function Log([string]$m) { $line = "$(Get-Date -Format 'HH:mm:ss') $m"; Write-Host $line; $line | Out-File -Append -Encoding utf8 $progress }
function Run([string]$name, [string[]]$pyargs) {
    Log "START $name"
    $lines = & python @pyargs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $lines | Out-File -Encoding utf8 (Join-Path $out "$name.log")
    Log "END   $name exit=$code"
}

Log "step 1: checks"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "windows_llm_cadence_check.ps1") *> (Join-Path $out "checks.console.log")
$latest = Get-ChildItem (Join-Path $repo "results\windows_checks") -Directory | Where-Object { $_.Name -notlike "*_all" } | Sort-Object Name | Select-Object -Last 1
if ($latest) { Copy-Item (Join-Path $latest.FullName "summary.txt") (Join-Path $out "checks_summary.txt") -ErrorAction SilentlyContinue; Log "checks dir: $($latest.Name)" }

$claudeOk = (Test-Path (Join-Path $latest.FullName "llm_check_claude-cli.json")) -and ((Get-Content (Join-Path $latest.FullName "llm_check_claude-cli.json") -Raw) -match '"ok": true')
$codexOk = (Test-Path (Join-Path $latest.FullName "llm_check_codex-mcp.json")) -and ((Get-Content (Join-Path $latest.FullName "llm_check_codex-mcp.json") -Raw) -match '"ok": true')
Log "claude-cli ok=$claudeOk  codex-mcp ok=$codexOk"

Log "step 2: design runs"
foreach ($s in $Specs) {
    Run "design_${s}_rule" @("-m", "orfadc.repro.bench", "design", "--spec", $s, "--seed", "0", "--policy", "rule", "--out", $out)
    if ($claudeOk) { Run "design_${s}_claude-cli" @("-m", "orfadc.repro.bench", "design", "--spec", $s, "--seed", "0", "--policy", "claude-cli", "--out", $out) }
    if ($codexOk)  { Run "design_${s}_codex-mcp"  @("-m", "orfadc.repro.bench", "design", "--spec", $s, "--seed", "0", "--policy", "codex-mcp", "--out", $out) }
}

Log "step 3: summary table"
Run "llm_table" @("-m", "orfadc.repro.bench", "llm-table", "--out", $out)

Log "step 4: Cadence"
if (Test-NetConnection 192.168.44.128 -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue) {
    Run "cadence_check" @("-m", "orfadc.repro.bench", "cadence-check", "--spec", "S2", "--out", $out)
    Run "design_S2_cadence" @("-m", "orfadc.repro.bench", "design", "--spec", "S2", "--seed", "0", "--policy", "rule", "--backend", "cadence", "--out", $out)
} else {
    Log "Cadence VM 192.168.44.128:22 unreachable - skipped (start the VMware VM and rerun)"
}
Log "ALL DONE"
"done $(Get-Date -Format s)" | Out-File -Encoding utf8 (Join-Path $out "DONE.txt")
