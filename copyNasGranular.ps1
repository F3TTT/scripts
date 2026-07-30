# copyNasGranular.ps1 — per-file copy from Source to Destination with SHA-256
# verify and move-to-Processed on success. Consolidated from six dated variants
# in this folder (copyNasGranular.1252/1303/1324/1328/1337.ps1); the .1337
# version was the final working iteration and this script is its parameterized
# form.
#
# Paths are supplied via CLI parameters OR loaded from a JSON config at
# ~/.copynas/config.json. CLI values win over config values.
#
# Example config file (~/.copynas/config.json):
#   {
#     "Source": "D:\\path\\to\\source",
#     "Destination": "Z:\\path\\to\\destination",
#     "LogDir": "C:\\Logs"
#   }
#
# Example call (CLI override):
#   .\copyNasGranular.ps1 -Source "D:\foo" -Destination "Z:\foo"

param(
    [string]$Source,
    [string]$Destination,
    [string]$LogDir       = "C:\Logs",
    [string]$ConfigPath   = (Join-Path $env:USERPROFILE ".copynas\config.json")
)

# --- CONFIG MERGE (CLI wins over file) ---
if (Test-Path $ConfigPath) {
    $cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    if (-not $Source      -and $cfg.Source)      { $Source      = $cfg.Source }
    if (-not $Destination -and $cfg.Destination) { $Destination = $cfg.Destination }
    if ($cfg.LogDir)                              { if (-not $PSBoundParameters.ContainsKey('LogDir')) { $LogDir = $cfg.LogDir } }
}

if (-not $Source -or -not $Destination) {
    Write-Error "Source and Destination are required (via -Source/-Destination or $ConfigPath)."
    exit 1
}

$processedRoot = Join-Path $Source "Processed"

# --- RUN ID & LOGS ---
$hostname  = $env:COMPUTERNAME
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runID     = "$hostname-$timestamp"

$logFile   = Join-Path $LogDir "FileCopyProgress-$runID.log"
$errorLog  = Join-Path $LogDir "FileCopyErrors-$runID.log"

# --- SETUP ---
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
"[$runID] Starting .NET-based file copy: $Source -> $Destination" | Add-Content $logFile
Write-Host "[$runID] Starting .NET-based file copy: $Source -> $Destination"

# --- GET FILES ---
$allFiles = Get-ChildItem -Path $Source -Recurse -File -ErrorAction SilentlyContinue
$filesToProcess = $allFiles | Where-Object {
    $_ -and $_.FullName -and
    (-not $_.FullName.ToLower().StartsWith($processedRoot.ToLower()))
}

if (-not $filesToProcess) {
    "[$runID] No files to process. Either none found or all excluded." | Add-Content $logFile
    Write-Host "[$runID] No matching files found."
    return
}

foreach ($file in $filesToProcess) {
    $srcFile       = $file.FullName
    $relativePath  = $srcFile.Substring($Source.Length).TrimStart('\')
    $destFile      = Join-Path $Destination $relativePath
    $processedFile = Join-Path $processedRoot $relativePath

    Write-Host "`n[$runID] Processing: $relativePath"

    # Ensure destination folder exists
    $destDir = Split-Path $destFile -Parent
    if (-not [System.IO.Directory]::Exists($destDir)) {
        [System.IO.Directory]::CreateDirectory($destDir) | Out-Null
    }

    # Skip if file already exists and matches
    if ([System.IO.File]::Exists($destFile)) {
        try {
            $srcHash = Get-FileHash -Path $srcFile -Algorithm SHA256
            $dstHash = Get-FileHash -Path $destFile -Algorithm SHA256

            if ($srcHash.Hash -eq $dstHash.Hash) {
                $procDir = Split-Path $processedFile -Parent
                if (-not [System.IO.Directory]::Exists($procDir)) {
                    [System.IO.Directory]::CreateDirectory($procDir) | Out-Null
                }

                if ([System.IO.File]::Exists($processedFile)) {
                    [System.IO.File]::Delete($processedFile)
                }
                [System.IO.File]::Move($srcFile, $processedFile)

                if ([System.IO.File]::Exists($processedFile)) {
                    "[$runID] SKIPPED & MOVED TO PROCESSED: $relativePath" | Add-Content $logFile
                    Write-Host "[$runID] SKIPPED & MOVED: $relativePath"
                } else {
                    $msg = "[$runID] ERROR: Move failed after skip: $relativePath"
                    $msg | Add-Content $errorLog
                    Write-Host $msg
                }
                continue
            }
        } catch {
            $msg = "[$runID] ERROR comparing hashes for existing file: $relativePath - $_"
            $msg | Add-Content $errorLog
            Write-Host $msg
        }
    }

    # .NET COPY
    try {
        [System.IO.File]::Copy($srcFile, $destFile, $true)
        if (-not [System.IO.File]::Exists($destFile)) {
            $msg = "[$runID] ERROR: Copy succeeded but file not found at destination: $relativePath"
            $msg | Add-Content $errorLog
            Write-Host $msg
            continue
        }
    } catch {
        $msg = "[$runID] ERROR during .NET copy: $relativePath - $_"
        $msg | Add-Content $errorLog
        Write-Host $msg
        continue
    }

    # VERIFY & MOVE TO PROCESSED
    try {
        $srcHash = Get-FileHash -Path $srcFile -Algorithm SHA256
        $dstHash = Get-FileHash -Path $destFile -Algorithm SHA256

        if ($srcHash.Hash -eq $dstHash.Hash) {
            $procDir = Split-Path $processedFile -Parent
            if (-not [System.IO.Directory]::Exists($procDir)) {
                [System.IO.Directory]::CreateDirectory($procDir) | Out-Null
            }

            if ([System.IO.File]::Exists($processedFile)) {
                [System.IO.File]::Delete($processedFile)
            }
            [System.IO.File]::Move($srcFile, $processedFile)

            if ([System.IO.File]::Exists($processedFile)) {
                "[$runID] COPIED & MOVED TO PROCESSED: $relativePath" | Add-Content $logFile
                Write-Host "[$runID] COPIED & MOVED: $relativePath"
            } else {
                $msg = "[$runID] ERROR: File was copied but move failed: $relativePath"
                $msg | Add-Content $errorLog
                Write-Host $msg
            }
        } else {
            $msg = "[$runID] ERROR: Hash mismatch after copy, NOT moving: $relativePath"
            $msg | Add-Content $errorLog
            Write-Host $msg
        }
    } catch {
        $msg = "[$runID] ERROR during verify/move: $relativePath - $_"
        $msg | Add-Content $errorLog
        Write-Host $msg
    }
}

Write-Host "`n[$runID] Operation complete."
Write-Host "Logs saved to:"
Write-Host "  $logFile"
Write-Host "  $errorLog"
