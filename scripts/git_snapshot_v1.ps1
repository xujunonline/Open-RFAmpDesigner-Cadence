# Commit the current working tree as the "v1" snapshot and tag it (local only, never pushes).
# v1 = agent implementation where the Searcher is a program and the LLM decides only at the
# Manager (power split) and Refiner (next action) decision points. See docs/125, docs/127.
# Double-click scripts\git_snapshot_v1.cmd (asks for Y) or git_snapshot_v1_auto.cmd (-Auto: no prompts; the
# same safety checks still abort). A log is written to results\windows_checks\<ts>_git\ (git-ignored).
param([switch]$Auto)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$tag = "v1-decision-points"
$ts = Get-Date -Format "yyyyMMddTHHmmss"
$out = Join-Path $repo "results\windows_checks\${ts}_git"
New-Item -ItemType Directory -Force $out | Out-Null
$log = Join-Path $out "git_snapshot.log"
function Log([string]$m) { Write-Host $m; $m | Out-File -Append -Encoding utf8 $log }
function Stop-With([string]$m) { Log "ABORT: $m"; "aborted $(Get-Date -Format s): $m" | Out-File -Encoding utf8 (Join-Path $out "RESULT.txt"); if (-not $Auto) { Read-Host "Press Enter to close" }; exit 1 }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-With "git not found on PATH" }
if (-not (Test-Path (Join-Path $repo ".git"))) { Stop-With "no .git folder in $repo" }
$existing = git tag --list $tag
if ($existing) { Stop-With "tag $tag already exists" }

Log "== repo: $repo"
Log "== HEAD before: $(git log -1 --format='%h %s')"
git add -A
if ($LASTEXITCODE -ne 0) { Stop-With "git add failed" }

# --- safety checks on what is staged ---------------------------------------------------------
$staged = @(git diff --cached --name-only)
Log "== files staged: $($staged.Count)"
$bad = @($staged | Where-Object {
    $_ -match '\.local\.ya?ml$' -or $_ -match '^results/windows_checks/' -or $_ -match '^results/runs/' -or
    $_ -match '(^|/)id_(rsa|ed25519|ecdsa)' -or $_ -match '\.(pem|key|pfx|p12)$' -or $_ -match '^_to_delete/' -or
    $_ -match '(^|/)\.env$' })
if ($bad.Count -gt 0) {
    git reset -q
    Log ($bad -join "`n")
    Stop-With "sensitive or PDK-derived files would be committed (listed above); nothing was committed"
}
$big = @($staged | Where-Object { (Test-Path $_) -and ((Get-Item $_).Length -gt 20MB) })
if ($big.Count -gt 0) { git reset -q; Log ($big -join "`n"); Stop-With "files larger than 20 MB staged (listed above); nothing was committed" }

git diff --cached --stat | Out-File -Encoding utf8 (Join-Path $out "staged_stat.txt")
$staged | Out-File -Encoding utf8 (Join-Path $out "staged_files.txt")
Log "== top-level summary:"
$staged | ForEach-Object { ($_ -split '/')[0] } | Group-Object | Sort-Object Name | ForEach-Object { Log ("   {0,-22} {1}" -f $_.Name, $_.Count) }
Log ""
Log "Full list: $out\staged_files.txt"
if ($Auto) { $ans = "Y"; Log "== -Auto: committing without prompt" } else { $ans = Read-Host "Commit these $($staged.Count) files and tag '$tag'? Type Y to continue" }
if ($ans -ne "Y" -and $ans -ne "y") { git reset -q; Stop-With "cancelled by user; nothing was committed" }

$msgFile = Join-Path $out "commit_msg.txt"
$msg = @"
v1: runnable RFAmpDesigner reproduction (decision-point agents)

Surrogate pipeline (src/orfadc/repro), Cadence/Spectre PDK backend, tests,
docs 115-127, scripts and Claude environment (.claude, .mcp.json).
Agent implementation v1: Searcher is a program; the LLM decides only at the
Manager power-split and Refiner next-action points.
Key results: illustrative-PDK pass@1 34/40 at the paper budget (docs/127),
Codex backbone does not beat the rule policy on S9s/S10s (docs/119).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012u6oGYiYxynZwm4ormr2mw
"@
[IO.File]::WriteAllText($msgFile, $msg, (New-Object Text.UTF8Encoding($false)))   # no BOM in the commit message
git commit -q -F $msgFile
if ($LASTEXITCODE -ne 0) { Stop-With "git commit failed (check git user.name / user.email)" }
git tag -a $tag -m "v1 snapshot: decision-point agents (see docs/125, docs/127)"
if ($LASTEXITCODE -ne 0) { Stop-With "git tag failed" }
Log "== HEAD after: $(git log -1 --format='%h %s')"
Log "== tag: $(git describe --tags)"
Log "== working tree after commit:"
(git status --short | Select-Object -First 20) | ForEach-Object { Log "   $_" }
"ok $(Get-Date -Format s) $(git rev-parse --short HEAD) $tag" | Out-File -Encoding utf8 (Join-Path $out "RESULT.txt")
Log "Done. Nothing was pushed."
if (-not $Auto) { Read-Host "Press Enter to close" }
