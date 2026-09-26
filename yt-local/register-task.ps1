# Registers (or re-registers) the yt-local-daily scheduled task.
# Run from a normal (non-admin) PowerShell: .\register-task.ps1
param([string]$At = '8:00AM')

$script = Join-Path $PSScriptRoot 'yt-local-sync.ps1'
# pwsh.exe = PowerShell 7 via its app-execution alias (stable across PS7 updates,
# unlike the versioned WindowsApps install path).
$pwsh = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\pwsh.exe'
$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
# Random delay so the hit time isn't identical every day.
$trigger = New-ScheduledTaskTrigger -Daily -At $At -RandomDelay (New-TimeSpan -Minutes 30)
# StartWhenAvailable: if the laptop was asleep at 8, run once when it wakes.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName 'yt-local-daily' -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description 'yt-local: new + 1 backfill video per channel, highest quality, to C:\Media\YouTube' | Out-Null
Get-ScheduledTask -TaskName 'yt-local-daily' | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
