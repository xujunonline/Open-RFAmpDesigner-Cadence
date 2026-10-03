# Follow-up for an existing run_all_windows.ps1 output: (re)installs the pinned deps (mcp<2),
# checks the codex-mcp transport and, if it works, adds the codex-mcp design runs to that same
# results\windows_checks\<ts>_all folder and regenerates llm_table.md there.
#   double-click scripts\run_codex_followup.cmd     (uses the newest *_all folder)
param([int]$Calls = 40, [string[]]$Specs = @("S9", "S10", "S9s", "S10s"), [string]$Into = "")
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

if (-not $Into) {
    $Into = (Get-ChildItem (Join-Path $repo "results\windows_checks") -Directory | Where-Object { $_.Name -like "*_all" } |
             Sort-Object Name | Select-Object -Last 1).FullName
}
$out = $Into
$progress = Join-Path $out "followup_progress.txt"
function Log([string]$m) { $line = "$(Get-Date -Format 'HH:mm:ss') $m"; Write-Host $line; $line | Out-File -Append -Encoding utf8 $progress }
function Run([string]$name, [string[]]$pyargs) {
    Log "START $name"
    $lines = & python @pyargs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $lines | Out-File -Encoding utf8 (Join-Path $out "$name.log")
    Log "END   $name exit=$code"
    return $code
}

Log "target folder: $out"
Run "followup_pip" @("-m", "pip", "install", "-q", "-r", "config\requirements_repro.txt") | Out-Null
Run "followup_mcp_version" @("-c", "import importlib.metadata as m; print('mcp', m.version('mcp')); from mcp.server.fastmcp import FastMCP; print('fastmcp ok')") | Out-Null
$code = Run "followup_codex_llm_check" @("-m", "orfadc.repro.bench", "llm-check", "--policy", "codex-mcp", "--out", $out)
$ok = (Test-Path (Join-Path $out "llm_check_codex-mcp.json")) -and ((Get-Content (Join-Path $out "llm_check_codex-mcp.json") -Raw) -match '"ok": true')
Log "codex-mcp ok=$ok"
if ($ok) {
    foreach ($s in $Specs) {
        Run "design_${s}_codex-mcp" @("-m", "orfadc.repro.bench", "design", "--spec", $s, "--seed", "0", "--policy", "codex-mcp", "--out", $out) | Out-Null
    }
}
Run "llm_table" @("-m", "orfadc.repro.bench", "llm-table", "--out", $out) | Out-Null
Log "FOLLOWUP DONE"
"done $(Get-Date -Format s)" | Out-File -Encoding utf8 (Join-Path $out "FOLLOWUP_DONE.txt")
