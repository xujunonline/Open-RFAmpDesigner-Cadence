# Restore the two .claude files to the reviewed versions in scripts\claude_fix\ (byte copy, no text processing).
# v1 of this script replaced every letter "t" with "r" in SKILL.md (PowerShell flattened a one-pair array);
# the originals are kept as *.bak and are not touched here.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $PSScriptRoot "claude_fix"
$map = @{
  "rfamp-refiner.md"         = ".claude\agents\rfamp-refiner.md";
  "rfamp-design-lna.SKILL.md" = ".claude\skills\rfamp-design-lna\SKILL.md"
}
foreach ($k in $map.Keys) {
  $from = Join-Path $src $k
  $to = Join-Path $repo $map[$k]
  Copy-Item -LiteralPath $from -Destination $to -Force
  $h = (Get-FileHash -Algorithm SHA256 -LiteralPath $to).Hash.ToLower()
  Write-Host "$($map[$k])  sha256=$h"
}
Write-Host "done"; Start-Sleep -Seconds 5
