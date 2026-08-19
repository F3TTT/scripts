# backup-memory.ps1
#
# Daily/weekly/monthly rotating backup of Claude Code's persistent memory
# directory into OneDrive, so it survives a laptop loss (the .claude folder
# itself sits outside OneDrive's sync root and is never backed up otherwise).
#
# Three independent retention tiers exist specifically so that if OneDrive's
# sync corrupts or clobbers one copy, the other two tiers (taken at different
# times, pruned on different schedules) give separate recovery points rather
# than all three going bad together.
#
# Intended to run once daily via Windows Task Scheduler (see README.md in
# this folder for the registration command). Safe to re-run multiple times
# on the same day - same-day snapshots are simply overwritten.

$ErrorActionPreference = 'Stop'

$Source   = Join-Path $env:USERPROFILE '.claude\projects\c--scripts\memory'
$DestRoot = Join-Path $env:USERPROFILE 'OneDrive\Backups\claude-memory'
$LogFile  = Join-Path $DestRoot 'backup.log'

$DailyRetentionDays   = 7    # keep last 7 daily snapshots
$WeeklyRetentionCount = 5    # keep last 5 weekly snapshots (~5 weeks)
$MonthlyRetentionCount = 12  # keep last 12 monthly snapshots (~1 year)

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line
}

function Copy-Snapshot {
    param(
        [string]$TargetDir,
        [string]$Label
    )
    if (Test-Path $TargetDir) {
        Remove-Item -Path $TargetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    Copy-Item -Path (Join-Path $Source '*') -Destination $TargetDir -Recurse -Force
    Write-Log "Wrote $Label snapshot -> $TargetDir"
}

function Prune-ByAge {
    param([string]$Dir, [int]$MaxAgeDays)
    if (-not (Test-Path $Dir)) { return }
    Get-ChildItem -Path $Dir -Directory | Where-Object {
        $_.LastWriteTime -lt (Get-Date).AddDays(-$MaxAgeDays)
    } | ForEach-Object {
        Remove-Item -Path $_.FullName -Recurse -Force
        Write-Log "Pruned old snapshot -> $($_.FullName)"
    }
}

function Prune-ByCount {
    param([string]$Dir, [int]$KeepCount)
    if (-not (Test-Path $Dir)) { return }
    $snapshots = Get-ChildItem -Path $Dir -Directory | Sort-Object Name -Descending
    if ($snapshots.Count -gt $KeepCount) {
        $snapshots | Select-Object -Skip $KeepCount | ForEach-Object {
            Remove-Item -Path $_.FullName -Recurse -Force
            Write-Log "Pruned old snapshot -> $($_.FullName)"
        }
    }
}

try {
    if (-not (Test-Path $DestRoot)) {
        New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null
    }
    if (-not (Test-Path $Source)) {
        Write-Log "ERROR: source memory folder not found at $Source - skipping this run."
        exit 1
    }

    $today = Get-Date

    # --- Daily ---
    $dailyDir = Join-Path $DestRoot 'daily'
    $dailySnapshot = Join-Path $dailyDir $today.ToString('yyyy-MM-dd')
    Copy-Snapshot -TargetDir $dailySnapshot -Label 'daily'
    Prune-ByAge -Dir $dailyDir -MaxAgeDays $DailyRetentionDays

    # --- Weekly (ISO-8601-style week number; ISOWeek class isn't available
    #     under Windows PowerShell 5.1 / .NET Framework, so approximate with
    #     Calendar.GetWeekOfYear using the FirstFourDayWeek/Monday rule) ---
    $cal = [System.Globalization.CultureInfo]::InvariantCulture.Calendar
    $isoWeek = $cal.GetWeekOfYear($today, [System.Globalization.CalendarWeekRule]::FirstFourDayWeek, [System.DayOfWeek]::Monday)
    $weekLabel = "{0}-W{1:D2}" -f $today.Year, $isoWeek
    $weeklyDir = Join-Path $DestRoot 'weekly'
    $weeklySnapshot = Join-Path $weeklyDir $weekLabel
    Copy-Snapshot -TargetDir $weeklySnapshot -Label 'weekly'
    Prune-ByCount -Dir $weeklyDir -KeepCount $WeeklyRetentionCount

    # --- Monthly ---
    $monthLabel = $today.ToString('yyyy-MM')
    $monthlyDir = Join-Path $DestRoot 'monthly'
    $monthlySnapshot = Join-Path $monthlyDir $monthLabel
    Copy-Snapshot -TargetDir $monthlySnapshot -Label 'monthly'
    Prune-ByCount -Dir $monthlyDir -KeepCount $MonthlyRetentionCount

    Write-Log "Backup run complete."
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
