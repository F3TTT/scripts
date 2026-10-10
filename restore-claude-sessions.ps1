<#
.SYNOPSIS
    Reopen the Claude Code sessions that were killed by the last reboot, one Windows Terminal tab each.

.DESCRIPTION
    When Windows reboots, every running Claude Code session flushes its transcript within the same
    few seconds right before shutdown (on 2026-10-05 all 7 open sessions were last written at
    22:30:07; the machine came back at 22:30:28). This script finds every session transcript whose
    last write falls in the window just before the last boot, reads each one's working directory
    and title, and opens a Windows Terminal tab per session running `claude --resume <id>` in the
    right folder. Claude sets each tab's title (and its working/done status) itself.

    A session that has already been resumed is written to after boot, so it falls out of the window.
    Re-running the script only reopens what is still missing.

.PARAMETER WindowMinutes
    How far before the boot time to look for last writes. Default 5. Widen it if a session that was
    open did not show up (e.g. a slow shutdown).

.PARAMETER Before
    Use this time instead of the last boot as the cutoff, e.g. after a crash where Windows Terminal
    died but the machine did not reboot.

.PARAMETER Id
    Reopen these session IDs instead of searching by time.

.PARAMETER List
    Only print the sessions that would be reopened; do not open any tabs.

.PARAMETER Save
    Before a planned reboot: record every Claude Code session running right now (from the live
    records in ~\.claude\sessions) to ~\.claude\restore-snapshot.json, and register a one-shot
    HKCU RunOnce entry that runs this script with -Saved at the next logon. Use this when the reboot
    may not be a clean one (disk encryption, firmware updates), where the last-write timing guess
    can miss sessions.

.PARAMETER Saved
    Reopen the sessions recorded by -Save, skipping any that are already running again.

.EXAMPLE
    .\restore-claude-sessions.ps1 -Save            # right before a planned reboot
    .\restore-claude-sessions.ps1 -Saved -List     # after it: preview (also runs on its own at logon)
    .\restore-claude-sessions.ps1 -List
    .\restore-claude-sessions.ps1
    .\restore-claude-sessions.ps1 -Before '2026-10-05 22:31' -List
#>
param(
    [int]$WindowMinutes = 5,
    [datetime]$Before,
    [string[]]$Id,
    [switch]$List,
    [switch]$Save,
    [switch]$Saved
)

$projectsDir = Join-Path $env:USERPROFILE '.claude\projects'
$snapshotPath = Join-Path $env:USERPROFILE '.claude\restore-snapshot.json'

# Live interactive sessions, from the per-process records Claude Code keeps in ~\.claude\sessions.
# Records can outlive their process (e.g. across a reboot), so only count ones whose PID is running.
function Get-LiveSessions {
    Get-ChildItem -Path (Join-Path $env:USERPROFILE '.claude\sessions\*.json') -File -ErrorAction SilentlyContinue |
        ForEach-Object { try { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch { } } |
        Where-Object { $_.kind -eq 'interactive' -and $_.sessionId -and (Get-Process -Id $_.pid -ErrorAction SilentlyContinue) }
}

if ($Save) {
    $live = @(Get-LiveSessions)
    if (-not $live) { Write-Host 'No running Claude Code sessions to save.'; return }
    [pscustomobject]@{
        SavedAt  = (Get-Date).ToString('o')
        Sessions = @($live | ForEach-Object { [pscustomobject]@{ Id = $_.sessionId; Dir = $_.cwd; Name = $_.name } })
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $snapshotPath -Encoding utf8
    $live | Format-Table @{ n = 'Name'; e = { $_.name } }, @{ n = 'Dir'; e = { $_.cwd } }, @{ n = 'Id'; e = { $_.sessionId } } -AutoSize |
        Out-String -Width 250 | Write-Host
    Write-Host "Saved $($live.Count) session(s) to $snapshotPath."

    # RunOnce entries run once at the next logon and then delete themselves.
    $cmd = "pwsh -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Saved"
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'RestoreClaudeSessions' -Value $cmd
    Write-Host 'They will reopen on their own at the next logon (or run this script with -Saved).'
    return
}

if ($Saved) {
    if (-not (Test-Path -LiteralPath $snapshotPath)) { Write-Host "No snapshot at $snapshotPath; run with -Save first."; return }
    $snap = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
    # The snapshot's folder wins over the one recorded in the transcript: it can be edited after a
    # folder move (e.g. the Desktop leaving OneDrive on 2026-10-09).
    $snapDirs = @{}
    foreach ($s in @($snap.Sessions)) { if ($s.Dir) { $snapDirs[$s.Id] = $s.Dir } }
    $running = @(Get-LiveSessions | ForEach-Object sessionId)
    $Id = @($snap.Sessions | ForEach-Object Id | Where-Object { $_ -notin $running })
    Write-Host "Snapshot from $($snap.SavedAt): $(@($snap.Sessions).Count) session(s), $($Id.Count) not running now."
    if (-not $Id) { return }
}
$boot = if ($PSBoundParameters.ContainsKey('Before')) { $Before } else { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime }
$from = $boot.AddMinutes(-$WindowMinutes)

# Session transcripts sit directly under each project folder; subagent transcripts are nested deeper
# (<session>\subagents\*.jsonl) and are not resumable sessions.
$files = Get-ChildItem -Path (Join-Path $projectsDir '*\*.jsonl') -File |
    Where-Object {
        if ($Id) { $_.BaseName -in $Id }
        else { $_.LastWriteTime -ge $from -and $_.LastWriteTime -le $boot }
    } |
    # The same session can have a transcript in more than one project folder (a copied folder after
    # a move); open it once, from its newest copy.
    Group-Object BaseName | ForEach-Object { $_.Group | Sort-Object LastWriteTime | Select-Object -Last 1 } |
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
    if ($snapDirs -and $snapDirs[$f.BaseName]) { $cwd = $snapDirs[$f.BaseName] }
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

if ($Id) { Write-Host "Sessions to reopen:" }
else { Write-Host "Cutoff: $boot. Sessions last written in the $WindowMinutes min before it:" }
$sessions | Format-Table Title, Dir, Id -AutoSize | Out-String -Width 250 | Write-Host

if ($List) { return }

# No --title: Claude Code sets the tab title itself and updates it with its working/done status,
# and a fixed or suppressed title would freeze that.
#
# Each tab first clears every CLAUDE* environment variable. When this script runs from inside a Claude
# Code session, the tabs would otherwise inherit that session's child-session markers
# (CLAUDE_CODE_CHILD_SESSION etc.), and Claude Code doesn't save transcripts for child sessions
# (2026-10-09: five reopened sessions lost everything after the reopen). The command is base64-encoded
# because wt treats ';' as its own separator.
$tabs = foreach ($s in $sessions) {
    $inner = "Get-ChildItem Env:CLAUDE* | Remove-Item; claude --resume $($s.Id)"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
    "new-tab -d `"$($s.Dir)`" pwsh -NoExit -EncodedCommand $enc"
}
Start-Process wt -ArgumentList (@('-w', 'new') + ($tabs -join ' ; '))
