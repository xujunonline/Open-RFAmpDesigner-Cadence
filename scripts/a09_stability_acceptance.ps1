param(
    [string]$VmxPath = 'F:\ic25\RedHat_9_7_A_and_D_10T\RedHat_9_7_A_and_D_10T.vmx',
    [string]$OutputDir = "results/logs/a09_$(Get-Date -Format 'yyyyMMdd_HHmmss')",
    [string]$VmrunPath = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe',
    [int]$Rounds = 15,
    [int]$IntervalSeconds = 60,
    [int]$MinimumFreeMb = 1024
)

$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'src'
if (-not (Test-Path -LiteralPath $VmrunPath)) { throw "vmrun not found: $VmrunPath" }
if ($Rounds -lt 1 -or $IntervalSeconds -lt 0 -or $MinimumFreeMb -lt 1) { throw 'Invalid acceptance parameters' }
if (Test-Path -LiteralPath $OutputDir) { throw "Output directory already exists: $OutputDir" }
New-Item -ItemType Directory -Path $OutputDir | Out-Null
$records = [System.Collections.Generic.List[object]]::new()

for ($round = 1; $round -le $Rounds; $round++) {
    $freeMb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024, 0)
    $record = [ordered]@{
        round = $round
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        host_free_mb = $freeMb
        ssh = 'not_run'
        tools = 'not_run'
        ocean = 'not_run'
        status = 'pending'
    }
    if ($freeMb -lt $MinimumFreeMb) {
        $record.status = 'low_host_memory'
    } else {
        $sshOutput = python -m orfadc.cadence.verify_remote 2>&1 | Out-String
        $sshExit = $LASTEXITCODE
        $record.ssh = if ($sshExit -eq 0) { 'ok' } else { 'failed' }
        $sshOutput | Set-Content -Path (Join-Path $OutputDir "ssh_$round.json")

        $vmrun = [System.Diagnostics.Process]::new()
        $vmrun.StartInfo.FileName = $VmrunPath
        $vmrun.StartInfo.Arguments = '-T ws getGuestIPAddress "' + $VmxPath + '"'
        $vmrun.StartInfo.UseShellExecute = $false
        $vmrun.StartInfo.RedirectStandardOutput = $true
        $vmrun.StartInfo.CreateNoWindow = $true
        [void]$vmrun.Start()
        if (-not $vmrun.WaitForExit(30000)) {
            $vmrun.Kill()
            $record.tools = 'timeout'
        } else {
            $toolsOutput = $vmrun.StandardOutput.ReadToEnd()
            $record.tools = if ($vmrun.ExitCode -eq 0 -and $toolsOutput.Trim() -match '^\d+\.\d+\.\d+\.\d+$') { 'ok' } else { 'failed' }
        }
        $vmrun.Dispose()

        if ($record.ssh -eq 'ok' -and $record.tools -eq 'ok' -and $round -in @(1, [math]::Ceiling($Rounds / 2), $Rounds)) {
            $oceanDir = Join-Path $OutputDir "ocean_$round"
            $oceanOutput = python -m orfadc.cadence.verify_cadence_environment --output-dir $oceanDir 2>&1 | Out-String
            $record.ocean = if ($LASTEXITCODE -eq 0) { 'ok' } else { 'failed' }
            $oceanOutput | Set-Content -Path (Join-Path $oceanDir 'command_output.txt')
        }
        $record.status = if ($record.ssh -eq 'ok' -and $record.tools -eq 'ok' -and $record.ocean -ne 'failed') { 'ok' } else { 'failed' }
    }

    $records.Add([pscustomobject]$record)
    $records | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $OutputDir 'a09_records.json')
    Write-Output ("round={0}/{1} free_mb={2} ssh={3} tools={4} ocean={5} status={6}" -f $round, $Rounds, $record.host_free_mb, $record.ssh, $record.tools, $record.ocean, $record.status)
    if ($record.status -ne 'ok') { exit 1 }
    if ($round -lt $Rounds) { Start-Sleep -Seconds $IntervalSeconds }
}
