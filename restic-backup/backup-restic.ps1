#Requires -Version 7
<#
Weekly encrypted backup of the Desktop, Pictures and Videos to Backblaze B2 with restic.
(The Desktop moved from OneDrive\Desktop to C:\Users\ADMIN\Desktop on 2026-10-09; Pictures and Videos left
OneDrive the same night and were added here 2026-10-10. C:\Users\ADMIN\Staging is deliberately NOT included:
it stages material for a separate compartment that must never enter this repo.)

- Config (secrets) lives OUTSIDE OneDrive: ~\.backup-cold\config.json
  { b2KeyId, b2ApplicationKey, bucket, resticPassword }. Never print it.
- --force re-reads every file, so VeraCrypt containers whose modified date
  doesn't change are still picked up (only changed chunks upload).
- Retention: weekly 8, monthly 12, yearly 7 (user policy: one yearly backup kept 7 years).
- Exits 1 and logs "ERROR:" on any failure. Log: %LOCALAPPDATA%\restic-backup\backup.log
#>
param(
    [string[]]$Paths = @("C:\Users\ADMIN\Desktop", "C:\Users\ADMIN\Pictures", "C:\Users\ADMIN\Videos"),
    [string]$ConfigPath = (Join-Path $HOME ".backup-cold\config.json"),
    [switch]$NoPrune
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $env:LOCALAPPDATA "restic-backup"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "backup.log"
if ((Test-Path $log) -and (Get-Item $log).Length -gt 512KB) { Move-Item $log "$log.old" -Force }

function Write-Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line
    Write-Output $line
}

function Invoke-Restic([string[]]$ResticArgs) {
    $out = & $script:restic @ResticArgs 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Log "  $_" }
    if ($code -ne 0) { throw "restic $($ResticArgs[0]) exited $code" }
}

try {
    $restic = (Get-Command restic -ErrorAction SilentlyContinue).Source
    if (-not $restic) {
        $restic = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\restic.restic_*\restic*.exe" -ErrorAction SilentlyContinue |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    }
    if (-not $restic) { throw "restic not found (winget install restic.restic)" }

    $c = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $env:B2_ACCOUNT_ID     = $c.b2KeyId
    $env:B2_ACCOUNT_KEY    = $c.b2ApplicationKey
    $env:RESTIC_PASSWORD   = $c.resticPassword
    $env:RESTIC_REPOSITORY = "b2:$($c.bucket):restic"

    Write-Log "START backup of $($Paths -join ', ')"
    foreach ($p in $Paths) { if (-not (Test-Path $p)) { throw "path missing: $p" } }

    Invoke-Restic (@("backup") + $Paths + @("--force", "--tag", "weekly", "--host", $env:COMPUTERNAME,
                   "--exclude", "node_modules", "--no-scan"))

    if (-not $NoPrune) {
        Write-Log "forget/prune (weekly 8, monthly 12, yearly 7)"
        Invoke-Restic @("forget", "--host", $env:COMPUTERNAME, "--keep-weekly", "8", "--keep-monthly", "12",
                        "--keep-yearly", "7", "--prune")
    }

    Write-Log "check (metadata + 2% of data)"
    Invoke-Restic @("check", "--read-data-subset=2%")

    Write-Log "OK"
    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
finally {
    Remove-Item Env:B2_ACCOUNT_ID, Env:B2_ACCOUNT_KEY, Env:RESTIC_PASSWORD -ErrorAction SilentlyContinue
}
