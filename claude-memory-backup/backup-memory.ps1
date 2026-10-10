# backup-memory.ps1
#
# Daily/weekly/monthly rotating backup of Claude Code state into Proton Drive, so it
# survives a laptop loss (the .claude folder sits outside every synced folder
# and is never backed up otherwise).
#
# What gets backed up (snapshot layout):
#   projects\<project-name>\memory\...   every project's memory dir that has files
#   global\                              CLAUDE.md, settings.json, settings.local.json,
#                                        statusline.js, keybindings.json, commands\, skills\
# Deliberately NOT backed up: .credentials.json (secret), history/transcripts,
# plugins\ (reinstallable), caches, file-history.
#
# Three independent retention tiers exist so that if Proton Drive's sync corrupts or
# clobbers one copy, the other tiers (written and pruned separately) give
# separate recovery points.
#
# The snapshot is built once in %TEMP%, verified (file count), then copied to each
# tier via a ".tmp" dir + rename, so a failed copy never destroys the previous
# good snapshot. Safe to re-run: same-day/week/month snapshots are replaced.
#
# Runs once daily via Task Scheduler (see README.md). Exits 1 on any failure.

$ErrorActionPreference = 'Stop'

$ClaudeDir = Join-Path $env:USERPROFILE '.claude'
$DestRoot  = Join-Path $env:USERPROFILE 'Proton Drive\f3ttt\My files\Backups\claude-memory'
$LogFile   = Join-Path $DestRoot 'backup.log'
$Stage     = Join-Path $env:TEMP ("claude-backup-{0}" -f [guid]::NewGuid().ToString('N'))

$DailyKeep   = 7
$WeeklyKeep  = 5
$MonthlyKeep = 12
$LogMaxBytes = 256KB

$GlobalFiles = 'CLAUDE.md', 'settings.json', 'settings.local.json', 'statusline.js', 'keybindings.json'
$GlobalDirs  = 'commands', 'skills'

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line
}

function Get-FileCount([string]$Dir) {
    (Get-ChildItem -Path $Dir -Recurse -File -Force | Measure-Object).Count
}

function Build-Stage {
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null

    # Every project memory dir that actually contains files.
    $projects = Join-Path $ClaudeDir 'projects'
    if (Test-Path $projects) {
        foreach ($p in Get-ChildItem -Path $projects -Directory) {
            $mem = Join-Path $p.FullName 'memory'
            if ((Test-Path $mem) -and (Get-FileCount $mem) -gt 0) {
                $dest = Join-Path $Stage "projects\$($p.Name)\memory"
                New-Item -ItemType Directory -Path $dest -Force | Out-Null
                Copy-Item -Path (Join-Path $mem '*') -Destination $dest -Recurse -Force
            }
        }
    }

    # Global config.
    $global = Join-Path $Stage 'global'
    New-Item -ItemType Directory -Path $global -Force | Out-Null
    foreach ($f in $GlobalFiles) {
        $src = Join-Path $ClaudeDir $f
        if (Test-Path $src) { Copy-Item -Path $src -Destination $global -Force }
    }
    foreach ($d in $GlobalDirs) {
        $src = Join-Path $ClaudeDir $d
        if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $global $d) -Recurse -Force }
    }

    if ((Get-FileCount $Stage) -eq 0) { throw "Staged snapshot is empty - nothing to back up." }
}

function Publish-Snapshot {
    param([string]$TargetDir, [string]$Label)
    $tmp = "$TargetDir.tmp"
    if (Test-Path $tmp) { Remove-Item -Path $tmp -Recurse -Force }
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    Copy-Item -Path (Join-Path $Stage '*') -Destination $tmp -Recurse -Force

    $want = Get-FileCount $Stage
    $got  = Get-FileCount $tmp
    if ($want -ne $got) {
        Remove-Item -Path $tmp -Recurse -Force
        throw "$Label verify failed: staged $want files, copied $got."
    }

    # Only now is it safe to replace the previous snapshot.
    if (Test-Path $TargetDir) { Remove-Item -Path $TargetDir -Recurse -Force }
    Rename-Item -Path $tmp -NewName (Split-Path $TargetDir -Leaf)
    Write-Log "Wrote $Label snapshot ($got files) -> $TargetDir"
}

function Prune-ByCount {
    param([string]$Dir, [int]$KeepCount)
    if (-not (Test-Path $Dir)) { return }
    # Names sort chronologically (yyyy-MM-dd, yyyy-Www, yyyy-MM); ignore leftover .tmp dirs.
    Get-ChildItem -Path $Dir -Directory | Where-Object { $_.Name -notlike '*.tmp' } |
        Sort-Object Name -Descending | Select-Object -Skip $KeepCount | ForEach-Object {
            Remove-Item -Path $_.FullName -Recurse -Force
            Write-Log "Pruned old snapshot -> $($_.FullName)"
        }
}

try {
    if (-not (Test-Path $DestRoot)) { New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null }
    if (-not (Test-Path $ClaudeDir)) { throw "Claude dir not found at $ClaudeDir" }

    # Rotate the log so it doesn't grow forever (and re-sync to Proton Drive every night).
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt $LogMaxBytes) {
        Move-Item -Path $LogFile -Destination "$LogFile.old" -Force
    }

    Build-Stage

    $today = Get-Date
    $cal = [System.Globalization.CultureInfo]::InvariantCulture.Calendar
    # ISOWeek isn't available in Windows PowerShell 5.1; approximate with FirstFourDayWeek/Monday.
    # Year-boundary weeks can mislabel the year (e.g. Dec 30 in W01) - use the ISO week-year.
    $isoWeek = $cal.GetWeekOfYear($today, [System.Globalization.CalendarWeekRule]::FirstFourDayWeek, [System.DayOfWeek]::Monday)
    $weekYear = if ($isoWeek -ge 52 -and $today.Month -eq 1) { $today.Year - 1 }
                elseif ($isoWeek -eq 1 -and $today.Month -eq 12) { $today.Year + 1 }
                else { $today.Year }

    $tiers = @(
        @{ Name = 'daily';   Label = $today.ToString('yyyy-MM-dd');            Keep = $DailyKeep }
        @{ Name = 'weekly';  Label = ("{0}-W{1:D2}" -f $weekYear, $isoWeek);   Keep = $WeeklyKeep }
        @{ Name = 'monthly'; Label = $today.ToString('yyyy-MM');               Keep = $MonthlyKeep }
    )
    foreach ($t in $tiers) {
        $dir = Join-Path $DestRoot $t.Name
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Publish-Snapshot -TargetDir (Join-Path $dir $t.Label) -Label $t.Name
        Prune-ByCount -Dir $dir -KeepCount $t.Keep
    }

    Write-Log "Backup run complete."
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
finally {
    if (Test-Path $Stage) { Remove-Item -Path $Stage -Recurse -Force -ErrorAction SilentlyContinue }
}
