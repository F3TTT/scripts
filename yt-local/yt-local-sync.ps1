<#
yt-local-sync -- pull YouTube channels to a LOCAL folder on the laptop at the
highest quality available. Sibling of yt-sync.sh / yt-backfill.sh (which push
1080p H.264 to the seedbox for Plex); this one keeps files on the laptop and
runs natively on Windows (no WSL).

Each run, per channel:
  1. New uploads   -- checks the newest $NewCount videos (archive skips repeats).
  2. Backfill      -- grabs $BackfillPerRun older video(s), walking backwards
                      from position $NewCount+1. Same pace as yt-backfill.sh
                      (1/channel/day), so the laptop's IP sees no more traffic
                      than the existing pipeline already generates per channel.

Config:  channels.conf next to this script. One per line: slug|url[|destDir]
         destDir defaults to $DefaultDestRoot\<slug>. # lines are comments.
State:   %LOCALAPPDATA%\yt-local\  (archive\, backfill_state\, log\)
Setup:   see SETUP.md in this folder.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = '',
    [string]$DefaultDestRoot = 'C:\Media\YouTube',
    [int]$NewCount = 5,
    [int]$BackfillPerRun = 1
)

$ErrorActionPreference = 'Continue'
# Resolved here, not in param(): Windows PowerShell 5.1 leaves $PSScriptRoot
# empty in param defaults. Task runs under PowerShell 7; this keeps 5.1 working too.
if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot 'channels.conf' }
$StateRoot = Join-Path $env:LOCALAPPDATA 'yt-local'
$ArchiveDir = Join-Path $StateRoot 'archive'
$PosDir = Join-Path $StateRoot 'backfill_state'
$LogDir = Join-Path $StateRoot 'log'
foreach ($d in $ArchiveDir, $PosDir, $LogDir) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
$Log = Join-Path $LogDir ((Get-Date -Format 'yyyy-MM-dd') + '.log')

function Write-Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $msg
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

# Single-instance lock: a manual run and the scheduled run must not overlap.
$LockPath = Join-Path $StateRoot 'run.lock'
try { $Lock = [IO.File]::Open($LockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { Write-Log 'another run holds the lock -- exiting'; exit 0 }

$YT = (Get-Command yt-dlp -ErrorAction SilentlyContinue).Source
if (-not $YT) { Write-Log 'ERROR: yt-dlp not on PATH (see SETUP.md)'; exit 1 }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Log 'ERROR: ffmpeg not on PATH -- cannot merge best video+audio'; exit 1 }
if (-not (Get-Command deno -ErrorAction SilentlyContinue)) { Write-Log 'WARNING: deno not on PATH -- some high-res formats may be missing' }
if (-not (Test-Path $ConfigPath)) { Write-Log "ERROR: $ConfigPath missing"; exit 1 }

# A stale yt-dlp is the usual way these pipelines die silently. Upgrade weekly.
$Stamp = Join-Path $StateRoot 'last_upgrade'
if (-not (Test-Path $Stamp) -or (Get-Item $Stamp).LastWriteTime -lt (Get-Date).AddDays(-7)) {
    Write-Log 'weekly yt-dlp upgrade check'
    winget upgrade --id yt-dlp.yt-dlp -e --silent --accept-source-agreements --accept-package-agreements 2>&1 |
        Select-Object -Last 2 | ForEach-Object { Write-Log "  $_" }
    Set-Content -Path $Stamp -Value (Get-Date -Format o)
}
Write-Log ("=== yt-local run start (yt-dlp {0}) ===" -f (& $YT --version))

# Highest quality: best video + best audio of any codec (VP9/AV1/4K/60fps
# included), merged to MKV since those codecs don't all fit cleanly in MP4.
# Pacing flags keep request bursts human-looking.
$Common = @(
    '-f', 'bv*+ba/b',
    '--merge-output-format', 'mkv',
    '--embed-metadata', '--embed-thumbnail', '--embed-chapters',
    '--write-info-json', '--no-write-playlist-metafiles',
    '--sleep-requests', '2', '--sleep-interval', '15', '--max-sleep-interval', '45',
    '--no-overwrites', '--ignore-errors', '--no-progress'
)

function Invoke-YT([string[]]$ytArgs) {
    $out = & $YT @ytArgs 2>&1 | ForEach-Object { "$_" }
    $out | Add-Content -Path $Log
    $out | Where-Object { $_ -match '\[Merger\]|ERROR|WARNING' } | ForEach-Object { Write-Log "  $_" }
    return ,$out
}

foreach ($raw in Get-Content $ConfigPath) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    $parts = $line.Split('|') | ForEach-Object { $_.Trim() }
    $slug = $parts[0]; $url = $parts[1]
    $dest = if ($parts.Count -ge 3 -and $parts[2]) { $parts[2] } else { Join-Path $DefaultDestRoot $slug }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $archive = Join-Path $ArchiveDir "$slug.txt"
    if (-not (Test-Path $archive)) { New-Item -ItemType File -Path $archive | Out-Null }
    $outTmpl = Join-Path $dest '%(upload_date>%Y-%m-%d)s - %(title).150B [%(id)s].%(ext)s'
    $countBefore = @(Get-Content $archive).Count

    Write-Log "--- $slug -> $dest ---"
    Invoke-YT ($Common + @('--download-archive', $archive, '--playlist-end', "$NewCount", '-o', $outTmpl, $url)) | Out-Null

    $posFile = Join-Path $PosDir "$slug.pos"
    $pos = if (Test-Path $posFile) { (Get-Content $posFile).Trim() } else { "$($NewCount + 1)" }
    if ($pos -eq 'done') {
        Write-Log '  backfill: complete (nothing older left)'
    } else {
        $pos = [int]$pos
        $last = $pos + $BackfillPerRun - 1
        Start-Sleep -Seconds (Get-Random -Minimum 60 -Maximum 180)
        Write-Log "  backfill: positions $pos-$last"
        $out = Invoke-YT ($Common + @('--download-archive', $archive, '--playlist-items', "$pos-$last", '-o', $outTmpl, $url))
        if ($out -match 'Downloading 0 items') {
            Set-Content -Path $posFile -Value 'done'
            Write-Log '  backfill: reached the oldest video -- marked done'
        } else {
            # Always advance, even on an archive-skip or error, so one bad
            # video can't stall the walk (same rule as yt-backfill.sh).
            Set-Content -Path $posFile -Value ($last + 1)
        }
    }
    $got = @(Get-Content $archive).Count - $countBefore
    Write-Log "  downloaded this run: $got"
}

Write-Log '=== yt-local run end ==='
$Lock.Close()
