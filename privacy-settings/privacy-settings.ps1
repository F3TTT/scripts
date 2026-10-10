# privacy-settings.ps1
#
# Applies the privacy settings in settings.psd1 and checks weekly that Microsoft
# hasn't turned any of them back on (feature updates, Office updates and "welcome"
# flows regularly do). Created 2026-10-10 as part of the privacy project.
#
#   (no switches)   check only: print what drifted, exit 1 if anything did
#   -Apply          set everything (HKLM entries need an elevated shell)
#   -Fix            check, re-apply whatever drifted, email a report if anything had drifted
#                   (this is what the weekly task runs)
#   -ClearHistory   one-shot: clear the recent-files lists (Start, Jump Lists, Explorer,
#                   Run box, Office's recent list). Irreversible; Jump List pins go too.
#   -Register       register the weekly task (needs an elevated shell)
#   -NoEmail        print the report instead of emailing it
#
# Also checks that retired apps (new Outlook, Copilot, OneDrive) stay uninstalled and
# that no Microsoft account outside the allowlist has signed in to Windows. The
# allowlist lives OUTSIDE the repo: %LOCALAPPDATA%\privacy-settings\config.json
#   { "allowedMicrosoftIdentities": [ "someone@example.com", ... ] }

param(
    [switch]$Apply,
    [switch]$Fix,
    [switch]$ClearHistory,
    [switch]$Register,
    [switch]$NoEmail
)

$ErrorActionPreference = 'Stop'

$settings    = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'settings.psd1')
$stateDir    = Join-Path $env:LOCALAPPDATA 'privacy-settings'
$configPath  = Join-Path $stateDir 'config.json'
$pendingPath = Join-Path $stateDir 'pending-alert.txt'   # alert that couldn't be emailed yet
$logDir      = Join-Path $stateDir 'log'
$mailFrom    = 'f3ttt@protonmail.com'
$mailTo      = 'billsmaphia@protonmail.com'
$taskName    = 'privacy-settings-weekly'

New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null
$logFile = Join-Path $logDir ((Get-Date -Format 'yyyy-MM-dd') + '.log')
function Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 's'), $msg
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

# ---------------------------------------------------------------- email (same as spotify-watch)

function Get-BridgePassword {
    if (-not ('CredMan' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CredMan {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct CREDENTIAL {
        public int Flags; public int Type; public string TargetName; public string Comment;
        public long LastWritten; public int CredentialBlobSize; public IntPtr CredentialBlob;
        public int Persist; public int AttributeCount; public IntPtr Attributes;
        public string TargetAlias; public string UserName;
    }
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CredRead(string target, int type, int flags, out IntPtr cred);
    [DllImport("advapi32.dll")] static extern void CredFree(IntPtr cred);
    public static string Read(string target) {
        IntPtr p;
        if (!CredRead(target, 1, 0, out p)) return null;
        try {
            var c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
            return Marshal.PtrToStringUni(c.CredentialBlob, c.CredentialBlobSize / 2);
        } finally { CredFree(p); }
    }
}
'@
    }
    $pw = [CredMan]::Read('ProtonBridgeSMTP')
    if (-not $pw) { throw 'No ProtonBridgeSMTP credential in Windows Credential Manager' }
    $pw
}

function Send-Alert([string]$subject, [string]$body) {
    if ($NoEmail) {
        Write-Host "`n=== [NoEmail] $subject ===`n$body"
        return
    }
    try {
        # Bridge presents a self-signed cert on 127.0.0.1.
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        $smtp = [System.Net.Mail.SmtpClient]::new('127.0.0.1', 1025)
        $smtp.EnableSsl = $true
        $smtp.Credentials = [System.Net.NetworkCredential]::new($mailFrom, (Get-BridgePassword))
        $msg = [System.Net.Mail.MailMessage]::new($mailFrom, $mailTo, $subject, $body)
        $smtp.Send($msg)
        $msg.Dispose(); $smtp.Dispose()
        Log "Emailed: $subject"
        Remove-Item $pendingPath -ErrorAction SilentlyContinue
    } catch {
        # Bridge not running, etc. Keep the alert and retry on the next run.
        Log "Email failed ($($_.Exception.Message)); saved to $pendingPath"
        Set-Content -Path $pendingPath -Value "$subject`n$body"
    }
}

# ---------------------------------------------------------------- registry

function Get-RegValue($item) {
    try { (Get-ItemProperty -Path $item.Path -Name $item.Name -ErrorAction Stop).($item.Name) } catch { $null }
}

function Set-RegValue($item) {
    if (-not (Test-Path $item.Path)) { New-Item -Path $item.Path -Force | Out-Null }
    New-ItemProperty -Path $item.Path -Name $item.Name -Value $item.Value -PropertyType DWord -Force | Out-Null
}

# ---------------------------------------------------------------- one-shot actions

function Clear-RecentHistory {
    $recent = Join-Path $env:APPDATA 'Microsoft\Windows\Recent'
    foreach ($dir in $recent, (Join-Path $recent 'AutomaticDestinations'), (Join-Path $recent 'CustomDestinations')) {
        if (Test-Path $dir) { Get-ChildItem -Path $dir -File -Force | Remove-Item -Force -ErrorAction SilentlyContinue }
    }
    $explorer = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer'
    foreach ($key in 'RecentDocs', 'RunMRU', 'TypedPaths', 'WordWheelQuery',
                     'ComDlg32\OpenSavePidlMRU', 'ComDlg32\LastVisitedPidlMRU') {
        $p = Join-Path $explorer $key
        if (Test-Path $p) { Remove-Item -Path $p -Recurse -Force; New-Item -Path $p -Force | Out-Null }
    }
    # Office keeps its own recent list per app ("User MRU" and the older "File MRU"/"Place MRU").
    $office = 'HKCU:\Software\Microsoft\Office\16.0'
    if (Test-Path $office) {
        Get-ChildItem -Path $office -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -in 'File MRU', 'Place MRU' } |
            ForEach-Object { Remove-Item -Path $_.PSPath -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Log 'Cleared recent-files history (Recent, Jump Lists, Explorer MRUs, Office MRUs)'
}

function Register-WeeklyTask {
    if (-not $isAdmin) { throw '-Register needs an elevated shell' }
    $pwsh = (Get-Command pwsh).Source
    $action = New-ScheduledTaskAction -Execute 'conhost.exe' `
        -Argument "--headless `"$pwsh`" -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Fix"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '11:00'
    $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    # Highest so it can also restore the HKLM policies; runs as this user so HKCU is this user's hive.
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $taskSettings `
        -Principal $principal -Description 'Weekly: re-check privacy settings Microsoft likes to re-enable (C:\scripts\privacy-settings)' -Force | Out-Null
    Log "Registered scheduled task $taskName (Sundays 11:00, highest privileges)"
}

# ---------------------------------------------------------------- main

if (Test-Path $pendingPath) {
    $pending = Get-Content $pendingPath
    Send-Alert $pending[0] (($pending | Select-Object -Skip 1) -join "`n")
}

$drift   = [System.Collections.Generic.List[string]]::new()   # found wrong
$fixed   = [System.Collections.Generic.List[string]]::new()   # found wrong and corrected
$blocked = [System.Collections.Generic.List[string]]::new()   # wrong, couldn't correct

$write = $Apply -or $Fix
foreach ($item in $settings.Registry) {
    $current = Get-RegValue $item
    if ($null -ne $current -and [int]$current -eq [int]$item.Value) { continue }
    $label = "$($item.Why)  [$($item.Path)\$($item.Name) = $(if ($null -eq $current) { 'unset' } else { $current }), want $($item.Value)]"
    if (-not $write) { $drift.Add($label); continue }
    if ($item.Path -like 'HKLM:*' -and -not $isAdmin) { $blocked.Add("$label (needs admin)"); continue }
    try {
        Set-RegValue $item
        if ([int](Get-RegValue $item) -eq [int]$item.Value) { $fixed.Add($label) } else { $blocked.Add("$label (write didn't stick)") }
    } catch {
        $blocked.Add("$label ($($_.Exception.Message))")
    }
}

foreach ($pkg in $settings.ForbiddenPackages) {
    $found = Get-AppxPackage -Name $pkg.Name
    if (-not $found) { continue }
    $label = "App is back: $($pkg.Name) ($($pkg.Why))"
    if (-not $write) { $drift.Add($label); continue }
    try { $found | Remove-AppxPackage; $fixed.Add("${label}: uninstalled") } catch { $blocked.Add("$label ($($_.Exception.Message))") }
}

foreach ($p in $settings.ForbiddenPaths) {
    $path = [Environment]::ExpandEnvironmentVariables($p.Path)
    # Reported, never auto-removed: uninstalling a classic app is a bigger step than a registry value.
    if (Test-Path $path) { $blocked.Add("Installed again: $path ($($p.Why))") }
}

if (Test-Path $configPath) {
    $allowed = @((Get-Content $configPath -Raw | ConvertFrom-Json).allowedMicrosoftIdentities)
    $ids = Get-ChildItem 'HKCU:\Software\Microsoft\IdentityCRL\UserExtendedProperties' -ErrorAction SilentlyContinue |
        ForEach-Object PSChildName
    foreach ($id in $ids) {
        if ($id -notin $allowed) { $blocked.Add("Microsoft account signed in to Windows that isn't on the allowlist: $id") }
    }
} else {
    $blocked.Add("No account allowlist at $configPath, so Windows sign-ins weren't checked")
}

if ($ClearHistory) { Clear-RecentHistory }
if ($Register) { Register-WeeklyTask }

$report = @()
if ($drift.Count)   { $report += "DRIFTED (not changed, check-only run):"; $report += $drift | ForEach-Object { "  - $_" } }
if ($fixed.Count)   { $report += $(if ($Apply) { 'SET:' } else { 'HAD DRIFTED, RESET:' }); $report += $fixed | ForEach-Object { "  - $_" } }
if ($blocked.Count) { $report += "NEEDS ATTENTION:"; $report += $blocked | ForEach-Object { "  - $_" } }
if (-not $report)   { $report = @('All privacy settings as expected.') }
$report | ForEach-Object { Log $_ }

# Per-device inventory: one status file per machine in the folder named by config.json's
# "statusDir" (none = skip). Each compartment's machines must point at their own compartment's
# storage, never at another's.
$statusDir = if (Test-Path $configPath) { (Get-Content $configPath -Raw | ConvertFrom-Json).statusDir }
if ($statusDir) {
    $statePath = Join-Path $stateDir 'state.json'
    $state = if (Test-Path $statePath) { Get-Content $statePath -Raw | ConvertFrom-Json } else { [pscustomobject]@{ lastApplied = $null } }
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm'
    if ($Apply -or $fixed.Count) { $state.lastApplied = $now }
    $state | ConvertTo-Json | Set-Content $statePath
    $mode = if ($Apply) { 'apply' } elseif ($Fix) { 'weekly check + fix' } else { 'check only' }
    $commit = try { (git -C $PSScriptRoot rev-parse --short HEAD 2>$null) } catch { '?' }
    $os = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    # Windows 11 still reports "Windows 10" in ProductName; the build number tells them apart.
    if ([int]$os.CurrentBuild -ge 22000) { $os.ProductName = $os.ProductName -replace 'Windows 10', 'Windows 11' }
    $result = if ($blocked.Count -or $drift.Count) { 'NEEDS ATTENTION' } elseif ($fixed.Count -and -not $Apply) { 'drift found and reset' } else { 'all as expected' }
    $lines = @(
        "# ${env:COMPUTERNAME}: privacy settings status"
        ''
        'Written automatically by `C:\scripts\privacy-settings\privacy-settings.ps1` on every run; do not edit.'
        ''
        "| | |"
        "|---|---|"
        "| Last checked | $now ($mode) |"
        "| Last applied / reset | $(if ($state.lastApplied) { $state.lastApplied } else { 'never' }) |"
        "| Result | $result |"
        "| Settings in baseline | $($settings.Registry.Count) registry values, $($settings.ForbiddenPackages.Count + $settings.ForbiddenPaths.Count) retired apps |"
        "| Script version | $commit |"
        "| Windows | $($os.ProductName) $($os.DisplayVersion), build $($os.CurrentBuild).$($os.UBR) |"
        ''
        '## Last run'
        ''
    ) + ($report | ForEach-Object { if ($_ -match '^\s+- ') { $_.Trim() } else { "**$_**" } })
    try {
        New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
        Set-Content -Path (Join-Path $statusDir "$env:COMPUTERNAME.md") -Value $lines -Encoding utf8
    } catch {
        Log "Couldn't write status file ($($_.Exception.Message))"
    }
}

# Email only from the weekly run, and only when something was off.
if ($Fix -and -not $Apply -and ($fixed.Count -or $blocked.Count)) {
    Send-Alert "Privacy settings: $($fixed.Count) reset, $($blocked.Count) need attention" (
        ($report -join "`n") + "`n`nScript: C:\scripts\privacy-settings\privacy-settings.ps1   Log: $logFile")
}

if ($blocked.Count -or $drift.Count) { exit 1 }
exit 0
