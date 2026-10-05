# Runs the bench commands listed in scripts\jobs\queue.txt (one per line, arguments after
# "python -m orfadc.repro.bench"), logging to results\windows_checks\<ts>_job\.  Lines starting with # are skipped;
# "set ORFADC_NAME=value" lines set an environment variable (only ORFADC_* names) for the following commands.
# Only orfadc.repro.bench subcommands are accepted.  Double-click scripts\run_job_queue.cmd, or pass
# -Queue jobs\queue_llm_uncapped.txt (path relative to scripts\) to run another saved queue.
param([string]$Queue = "jobs\queue.txt")
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
$queue = Join-Path $PSScriptRoot $Queue
$ts = Get-Date -Format "yyyyMMddTHHmmss"
$out = Join-Path $repo "results\windows_checks\${ts}_job"
New-Item -ItemType Directory -Force $out | Out-Null
$progress = Join-Path $out "progress.txt"
function Log([string]$m) { $line = "$(Get-Date -Format 'HH:mm:ss') $m"; Write-Host $line; $line | Out-File -Append -Encoding utf8 $progress }
Copy-Item $queue (Join-Path $out "queue.txt")
$i = 0
foreach ($raw in Get-Content $queue) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith("#")) { continue }
    if ($line -match '^set\s+(ORFADC_[A-Z0-9_]+)=(\S*)$') { Set-Item -Path ("Env:" + $Matches[1]) -Value $Matches[2]; Log "SET $($Matches[1])=$($Matches[2])"; continue }
    $i++
    $parts = @($line -split "\s+")
    if ($parts[0] -notmatch '^[a-z0-9-]+$') { Log "SKIP (not a bench subcommand): $line"; continue }
    $name = "{0:D2}_{1}" -f $i, $parts[0]
    $pyargs = @("-m", "orfadc.repro.bench") + $parts + @("--out", $out)
    Log "START $name : $line"
    $lines = & python @pyargs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $lines | Out-File -Encoding utf8 (Join-Path $out "$name.log")
    Log "END   $name exit=$code"
}
Log "QUEUE DONE"
"done $(Get-Date -Format s)" | Out-File -Encoding utf8 (Join-Path $out "DONE.txt")
