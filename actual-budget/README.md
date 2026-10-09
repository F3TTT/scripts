# actual-budget

`backup-actual-budget.ps1` — nightly backup of the local Actual Budget data directory
(`C:\Users\ADMIN\actual-budget-data`). Zips a timestamped snapshot rather than syncing the live
SQLite files (OneDrive syncing an open DB risks corruption/conflicted copies). Keeps 90 days.

- Destination: `C:\Users\ADMIN\Desktop\Financial\Actual Budget\backups\actual-budget-<date>.zip`
- Scheduled: Task Scheduler `ActualBudgetBackup`, daily 2:00 AM.
- Manual run: `powershell.exe -ExecutionPolicy Bypass -File C:\scripts\actual-budget\backup-actual-budget.ps1`
