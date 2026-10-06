# Scheduled-task entry point for counter_watch.py (task: calendar-counter-watch, every 5 min).
# Propagates the Python exit code so a failed run shows as a nonzero LastTaskResult.
$py = 'C:\Users\ADMIN\AppData\Local\Programs\Python\Python312\python.exe'
& $py (Join-Path $PSScriptRoot 'counter_watch.py')
exit $LASTEXITCODE
