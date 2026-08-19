# claude-memory-backup

Claude Code's persistent memory for this project lives at
`C:\Users\ADMIN\.claude\projects\c--scripts\memory\` — outside OneDrive's
sync root (`C:\Users\ADMIN\OneDrive\`), so nothing there is backed up unless
something copies it out.

`backup-memory.ps1` copies that folder into OneDrive daily, keeping three
independent rotation tiers rather than one:

- `daily\<yyyy-MM-dd>\` — last 7 days
- `weekly\<yyyy-Www>\` — last 5 weeks
- `monthly\<yyyy-MM>\` — last 12 months

The point of three tiers instead of one running copy: if OneDrive's sync
corrupts or clobbers a backup, the other tiers (written and pruned on
different schedules) give separate recovery points instead of the
corruption propagating through the only copy that exists.

Destination: `C:\Users\ADMIN\OneDrive\Backups\claude-memory\`
Log: `...\claude-memory\backup.log`

## Scheduled task

Registered as a Windows Scheduled Task, `ClaudeMemoryBackup`, daily at
8:40 PM, `StartWhenAvailable` (catches up if the machine was off/asleep at
trigger time). Registered with:

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\scripts\claude-memory-backup\backup-memory.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 8:40PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "ClaudeMemoryBackup" -Action $action -Trigger $trigger -Settings $settings -Description "Daily/weekly/monthly rotating backup of Claude Code memory folder into OneDrive" -Force
```

To check it: `Get-ScheduledTask -TaskName ClaudeMemoryBackup`
To remove it: `Unregister-ScheduledTask -TaskName ClaudeMemoryBackup -Confirm:$false`

## Manual run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\scripts\claude-memory-backup\backup-memory.ps1"
```
