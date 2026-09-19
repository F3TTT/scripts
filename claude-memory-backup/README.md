# claude-memory-backup

Claude Code's state lives in `C:\Users\ADMIN\.claude\`, outside OneDrive's sync
root (`C:\Users\ADMIN\OneDrive\`), so nothing there is backed up unless
something copies it out. `backup-memory.ps1` does that daily.

## What's backed up

Each snapshot contains:

- `projects\<project-name>\memory\` — memory for **every** project that has
  memory files (auto-discovered; new projects are picked up automatically)
- `global\` — `CLAUDE.md`, `settings.json`, `settings.local.json`,
  `statusline.js`, `keybindings.json`, `commands\`, `skills\`

Deliberately excluded: `.credentials.json` (secret — never put in OneDrive),
`history.jsonl`/session transcripts, `plugins\` (reinstallable), caches,
`file-history`. To add something, edit `$GlobalFiles` / `$GlobalDirs` in the script.

(Snapshots written before 2026-09-19 use the old flat layout: only the
`c--scripts` memory, files at the snapshot root.)

## Rotation

Three independent tiers rather than one:

- `daily\<yyyy-MM-dd>\` — last 7
- `weekly\<yyyy-Www>\` — last 5
- `monthly\<yyyy-MM>\` — last 12

If OneDrive's sync corrupts or clobbers one copy, the other tiers give separate
recovery points.

## Safety properties

- Snapshot is staged once in `%TEMP%`, then copied to each tier as `<name>.tmp`,
  file-count verified, and only then swapped in — a failed copy never destroys
  the previous good snapshot.
- Fails loudly: exits 1 and logs `ERROR:` if the stage is empty or a verify fails.
- Log is rotated at 256 KB (`backup.log` → `backup.log.old`).

Destination: `C:\Users\ADMIN\OneDrive\Backups\claude-memory\`
Log: `...\claude-memory\backup.log`

## Restore

Copy `projects\<name>\memory` back to `~\.claude\projects\<name>\memory` and
the `global\` contents back to `~\.claude\`.

## Scheduled task

Task `ClaudeMemoryBackup`, daily 8:40 PM, `StartWhenAvailable` (catches up if the
machine was off/asleep). Registered with:

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\scripts\claude-memory-backup\backup-memory.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 8:40PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "ClaudeMemoryBackup" -Action $action -Trigger $trigger -Settings $settings -Description "Daily/weekly/monthly rotating backup of Claude Code memory + config into OneDrive" -Force
```

Check: `Get-ScheduledTask -TaskName ClaudeMemoryBackup | Get-ScheduledTaskInfo`
Remove: `Unregister-ScheduledTask -TaskName ClaudeMemoryBackup -Confirm:$false`

## Manual run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\scripts\claude-memory-backup\backup-memory.ps1"
```
