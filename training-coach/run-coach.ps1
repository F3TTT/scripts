# Scheduled-task entry point (task: training-coach-weekly, Sundays 6:00 PM).
# Plans the coming Monday-Sunday: Garmin workouts + calendar invites.
# Propagates the Python exit code so a failed run shows as a nonzero LastTaskResult.
$py = 'C:\Users\ADMIN\AppData\Local\Programs\Python\Python312\python.exe'
& $py (Join-Path $PSScriptRoot 'coach.py') plan-week
exit $LASTEXITCODE
