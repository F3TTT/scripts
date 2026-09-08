# Nightly backup of Actual Budget's local data directory to OneDrive.
# Zips a timestamped snapshot rather than live-syncing the raw SQLite files,
# since OneDrive syncing an open/actively-written DB risks corruption or
# "conflicted copy" duplicates. Keeps the last 90 days of snapshots.

$source = "C:\Users\ADMIN\actual-budget-data"
$destDir = "C:\Users\ADMIN\OneDrive\Desktop\Financial\Actual Budget\backups"
$retentionDays = 90

if (-not (Test-Path $source)) {
    Write-Output "Source not found: $source"
    exit 1
}

if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$destZip = Join-Path $destDir "actual-budget-$stamp.zip"
$staging = Join-Path $env:TEMP "actual-budget-backup-staging"

if (Test-Path $destZip) {
    Remove-Item $destZip -Force
}
if (Test-Path $staging) {
    Remove-Item $staging -Recurse -Force
}

# robocopy tolerates the server's open/locked SQLite files better than
# Compress-Archive does directly; stage a plain copy first, then zip that.
robocopy $source $staging /E /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null

Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $destZip -CompressionLevel Optimal
Remove-Item $staging -Recurse -Force

# Prune snapshots older than $retentionDays
Get-ChildItem -Path $destDir -Filter "actual-budget-*.zip" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$retentionDays) } |
    Remove-Item -Force

Write-Output "Backup written: $destZip"
