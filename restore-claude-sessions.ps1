<#
.SYNOPSIS
    Reopen the Claude Code sessions that were killed by the last reboot, one Windows Terminal tab each.

.DESCRIPTION
    When Windows reboots, every running Claude Code session flushes its transcript within the same
    few seconds right before shutdown (on 2026-10-05 all 7 open sessions were last written at
    22:30:07; the machine came back at 22:30:28). This script finds every session transcript whose
    last write falls in the window just before the last boot, reads each one's working directory
    and title, and opens a Windows Terminal tab per session running `claude --resume <id>` in the
    right folder.

    A session that has already been resumed is written to after boot, so it falls out of the window.
    Re-running the script only reopens what is still missing.

.PARAMETER WindowMinutes
    How far before the boot time to look for last writes. Default 5. Widen it if a session that was
    open did not show up (e.g. a slow shutdown).

.PARAMETER Before
    Use this time instead of the last boot as the cutoff, e.g. after a crash where Windows Terminal
    died but the machine did not reboot.

.PARAMETER List
    Only print the sessions that would be reopened; do not open any tabs.

.EXAMPLE
    .\restore-claude-sessions.ps1 -List
    .\restore-claude-sessions.ps1
    .\restore-claude-sessions.ps1 -Before '2026-10-05 22:31' -List
#>
param(
    [int]$WindowMinutes = 5,
    [datetime]$Before,
    [switch]$List
)

$projectsDir = Join-Path $env:USERPROFILE '.claude\projects'
$boot = if ($PSBoundParameters.ContainsKey('Before')) { $Before } else { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime }
$from = $boot.AddMinutes(-$WindowMinutes)

# Session transcripts sit directly under each project folder; subagent transcripts are nested deeper
# (<session>\subagents\*.jsonl) and are not resumable sessions.
$files = Get-ChildItem -Path (Join-Path $projectsDir '*\*.jsonl') -File |
    Where-Object { $_.LastWriteTime -ge $from -and $_.LastWriteTime -le $boot } |
    Sort-Object LastWriteTime

if (-not $files) {
    Write-Host "No sessions were last written between $from and the boot at $boot."
    Write-Host "Try a wider window, e.g. -WindowMinutes 30."
    return
}

$sessions = foreach ($f in $files) {
    # First "cwd" in the transcript is the folder the session was launched in. The value is a JSON
    # string (backslashes escaped), so decode it through ConvertFrom-Json.
    $cwdMatch = Select-String -Path $f.FullName -Pattern '"cwd":("(?:[^"\\]|\\.)*")' -List
    $cwd = if ($cwdMatch) { $cwdMatch.Matches[0].Groups[1].Value | ConvertFrom-Json } else { $null }
    if (-not $cwd -or -not (Test-Path -LiteralPath $cwd)) { $cwd = $env:USERPROFILE }

    # Latest title record wins: a user-set title beats the auto-generated one.
    $title = $null
    foreach ($kind in 'customTitle', 'aiTitle') {
        $m = Select-String -Path $f.FullName -Pattern "`"${kind}`":(`"(?:[^`"\\]|\\.)*`")" | Select-Object -Last 1
        if ($m) { $title = $m.Matches[0].Groups[1].Value | ConvertFrom-Json; break }
    }
    if (-not $title) { $title = Split-Path $cwd -Leaf }

    [pscustomobject]@{
        Title = $title
        Dir   = $cwd
        Id    = $f.BaseName
        Last  = $f.LastWriteTime
    }
}

Write-Host "Cutoff: $boot. Sessions last written in the $WindowMinutes min before it:"
$sessions | Format-Table Title, Dir, Id -AutoSize | Out-String -Width 250 | Write-Host

if ($List) { return }

$tabs = foreach ($s in $sessions) {
    # wt treats ';' as a command separator and '"' would break the quoting, so strip both from the
    # tab title and keep it short enough to read on a tab.
    $tabTitle = ($s.Title -replace '[;"]', '').Trim()
    if ($tabTitle.Length -gt 30) { $tabTitle = $tabTitle.Substring(0, 29) + '…' }
    "new-tab --title `"$tabTitle`" --suppressApplicationTitle -d `"$($s.Dir)`" pwsh -NoExit -Command claude --resume $($s.Id)"
}
Start-Process wt -ArgumentList ($tabs -join ' ; ')
