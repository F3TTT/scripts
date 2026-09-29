#Requires -Version 7
# Weekly snapshot of the user's Spotify playlists, doubling as a canary for
# Spotify closing off export. Each run:
#   1. saves every readable playlist (+ Liked Songs) as CSV into a dated folder
#      under OneDrive, so the record of what a playlist held survives even after
#      songs grey out or vanish;
#   2. diffs against the previous snapshot and emails a summary of songs that
#      left a playlist or became unplayable;
#   3. emails an alert if Spotify's API refuses the export (403/404/410 or a
#      revoked login) -- that is the "they're closing the door" signal.
# Quiet weeks send nothing. See README.md for one-time setup.
#
# Usage:
#   spotify-watch.ps1 -Setup -ClientId <id>   # one-time browser login
#   spotify-watch.ps1                          # scheduled weekly run
#   spotify-watch.ps1 -NoEmail                 # run, print the report instead of sending

[CmdletBinding()]
param(
    [switch]$Setup,
    [string]$ClientId,
    [switch]$NoEmail
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Web   # HttpUtility, for parsing the OAuth callback

$stateDir     = Join-Path $env:LOCALAPPDATA 'spotify-watch'
$configPath   = Join-Path $stateDir 'config.json'
$tokenPath    = Join-Path $stateDir 'refresh-token.dat'   # DPAPI-encrypted, this user + machine only
$failPath     = Join-Path $stateDir 'consecutive-network-failures.txt'
$pendingPath  = Join-Path $stateDir 'pending-alert.txt'   # alert that couldn't be emailed yet
$logDir       = Join-Path $stateDir 'log'
$snapshotRoot = 'C:\Users\ADMIN\OneDrive\Desktop\Entertainment\Music\spotify-snapshots'
$redirectUri  = 'http://127.0.0.1:8888/callback'
$scopes       = 'playlist-read-private playlist-read-collaborative user-library-read'
$mailFrom     = 'f3ttt@protonmail.com'
$mailTo       = 'billsmaphia@protonmail.com'
# Network blips (laptop offline, DNS) aren't Spotify's doing; only email about
# them if they persist this many runs in a row.
$networkFailuresBeforeAlert = 3

New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null
$logFile = Join-Path $logDir ((Get-Date -Format 'yyyy-MM-dd') + '.log')
function Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 's'), $msg
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

# Raised for failures that mean Spotify itself refused us, as opposed to the network.
class SpotifyRefusedException : System.Exception {
    [int]$Status
    SpotifyRefusedException([string]$msg, [int]$status) : base($msg) { $this.Status = $status }
}

# ---------------------------------------------------------------- email

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

# ---------------------------------------------------------------- auth

function Save-RefreshToken([string]$token) {
    ConvertTo-SecureString $token -AsPlainText -Force | ConvertFrom-SecureString | Set-Content $tokenPath
}

function Read-RefreshToken {
    if (-not (Test-Path $tokenPath)) { return $null }
    $secure = Get-Content $tokenPath | ConvertTo-SecureString
    [System.Net.NetworkCredential]::new('', $secure).Password
}

function ConvertTo-Base64Url([byte[]]$bytes) {
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Invoke-Setup {
    if (-not $ClientId) { throw 'Setup needs -ClientId (from your app at developer.spotify.com/dashboard)' }
    @{ client_id = $ClientId } | ConvertTo-Json | Set-Content $configPath

    # Authorization Code + PKCE: no client secret to store.
    $verifier  = ConvertTo-Base64Url ([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(64))
    $challenge = ConvertTo-Base64Url ([System.Security.Cryptography.SHA256]::HashData([Text.Encoding]::ASCII.GetBytes($verifier)))
    $state     = ConvertTo-Base64Url ([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(16))
    $authUrl = 'https://accounts.spotify.com/authorize?' + (@(
        "client_id=$ClientId", 'response_type=code',
        ('redirect_uri=' + [uri]::EscapeDataString($redirectUri)),
        ('scope=' + [uri]::EscapeDataString($scopes)),
        'code_challenge_method=S256', "code_challenge=$challenge", "state=$state"
    ) -join '&')

    # A raw TcpListener rather than HttpListener: HttpListener needs an admin URL
    # reservation to bind 127.0.0.1, and Spotify no longer accepts "localhost".
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8888)
    $listener.Start()
    try {
        Write-Host 'Opening Spotify login in your browser...'
        Start-Process $authUrl
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        $requestLine = [System.IO.StreamReader]::new($stream).ReadLine()   # GET /callback?code=...&state=... HTTP/1.1
        $query = [System.Web.HttpUtility]::ParseQueryString(([uri]('http://x' + $requestLine.Split(' ')[1])).Query)
        $ok = $query['code'] -and $query['state'] -eq $state
        $page = if ($ok) { 'Spotify login captured. You can close this tab.' } else { "Login failed: $($query['error'])" }
        $bytes = [Text.Encoding]::UTF8.GetBytes("HTTP/1.1 200 OK`r`nContent-Type: text/plain; charset=utf-8`r`nContent-Length: $([Text.Encoding]::UTF8.GetByteCount($page))`r`nConnection: close`r`n`r`n$page")
        $stream.Write($bytes, 0, $bytes.Length)
        $client.Close()
    } finally { $listener.Stop() }
    if (-not $ok) { throw "Authorization failed: $($query['error'])" }

    $resp = Invoke-RestMethod -Method Post -Uri 'https://accounts.spotify.com/api/token' -Body @{
        grant_type = 'authorization_code'; code = $query['code']; redirect_uri = $redirectUri
        client_id = $ClientId; code_verifier = $verifier
    }
    Save-RefreshToken $resp.refresh_token
    Log 'Setup complete; refresh token saved.'
}

function Get-AccessToken {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    $refresh = Read-RefreshToken
    if (-not $refresh) { throw [SpotifyRefusedException]::new('No saved login. Run -Setup.', 401) }
    $r = Invoke-WebRequest -Method Post -Uri 'https://accounts.spotify.com/api/token' -SkipHttpErrorCheck -Body @{
        grant_type = 'refresh_token'; refresh_token = $refresh; client_id = $config.client_id
    }
    if ($r.StatusCode -ne 200) {
        throw [SpotifyRefusedException]::new("Token refresh refused (HTTP $($r.StatusCode)): $($r.Content)", [int]$r.StatusCode)
    }
    $tok = $r.Content | ConvertFrom-Json
    # PKCE refresh tokens rotate; persist the new one or the next run is locked out.
    if ($tok.refresh_token) { Save-RefreshToken $tok.refresh_token }
    $tok.access_token
}

# ---------------------------------------------------------------- API

function Invoke-Spotify([string]$url) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $r = Invoke-WebRequest -Uri $url -Headers @{ Authorization = "Bearer $script:accessToken" } -SkipHttpErrorCheck
        switch ([int]$r.StatusCode) {
            200 { return $r.Content | ConvertFrom-Json -Depth 50 }
            429 {
                $wait = [int]($r.Headers['Retry-After'] | Select-Object -First 1)
                Start-Sleep -Seconds ([Math]::Max($wait, 2))
            }
            { $_ -ge 500 } { Start-Sleep -Seconds (5 * $attempt) }
            default { throw [SpotifyRefusedException]::new("GET $url -> HTTP $($r.StatusCode): $($r.Content)", [int]$r.StatusCode) }
        }
    }
    throw "GET $url kept failing after retries (last HTTP $($r.StatusCode))"
}

function Get-AllPages([string]$url) {
    while ($url) {
        $page = Invoke-Spotify $url
        $page.items
        $url = $page.next
    }
}

function ConvertTo-Row($entry, [int]$position) {
    # Post-Feb-2026 playlist items use .item; Liked Songs and older shapes use .track.
    $t = $entry.item ?? $entry.track
    if (-not $t) {
        return [pscustomobject]@{ position = $position; name = '(no metadata - removed from catalog)'; artists = ''; album = ''
            added_at = $entry.added_at; is_playable = $false; is_local = $false; isrc = ''; duration_ms = ''; uri = "missing:$position" }
    }
    [pscustomobject]@{
        position    = $position
        name        = $t.name
        artists     = ($t.artists | ForEach-Object name) -join '; '
        album       = $t.album.name ?? $t.show.name
        added_at    = $entry.added_at
        # With market=from_token, tracks Spotify can't play in your country come back false.
        # Local files have no is_playable; they're only playable from the device that has them.
        is_playable = if ($t.is_local) { $true } elseif ($null -eq $t.is_playable) { $true } else { [bool]$t.is_playable }
        is_local    = [bool]$t.is_local
        isrc        = $t.external_ids.isrc
        duration_ms = $t.duration_ms
        uri         = $t.uri
    }
}

function Get-SafeFileName([string]$name, [string]$id) {
    $clean = ($name -replace '[\\/:*?"<>|]', '_').Trim().TrimEnd('.')
    if ($clean.Length -gt 80) { $clean = $clean.Substring(0, 80) }
    "$clean [$id].csv"
}

# ---------------------------------------------------------------- snapshot + diff

function New-Snapshot {
    $me = Invoke-Spotify 'https://api.spotify.com/v1/me'
    $playlists = @(Get-AllPages 'https://api.spotify.com/v1/me/playlists?limit=50')
    Log "Found $($playlists.Count) playlists for $($me.id)"

    $snap = [ordered]@{ taken = (Get-Date -Format 's'); user = $me.id; playlists = [ordered]@{}; unreadable = @() }
    foreach ($p in $playlists | Where-Object { $_ }) {
        # Dev-mode apps may only read the contents of playlists you own or collaborate on;
        # followed playlists come back metadata-only. Record them so it's visible what isn't covered.
        if ($p.owner.id -ne $me.id -and -not $p.collaborative) {
            $snap.unreadable += "$($p.name) (by $($p.owner.display_name ?? $p.owner.id))"
            continue
        }
        $url = "https://api.spotify.com/v1/playlists/$($p.id)/items?limit=50&market=from_token&additional_types=track,episode"
        $i = 0
        $rows = @(Get-AllPages $url | ForEach-Object { ConvertTo-Row $_ (++$i) })
        $snap.playlists[$p.id] = [ordered]@{ name = $p.name; snapshot_id = $p.snapshot_id; tracks = $rows }
    }

    # Liked Songs isn't a real playlist; treat a failure here as a warning, not an export block.
    try {
        $i = 0
        $rows = @(Get-AllPages 'https://api.spotify.com/v1/me/tracks?limit=50&market=from_token' | ForEach-Object { ConvertTo-Row $_ (++$i) })
        $snap.playlists['liked-songs'] = [ordered]@{ name = 'Liked Songs'; snapshot_id = ''; tracks = $rows }
    } catch {
        Log "Liked Songs not readable: $($_.Exception.Message)"
        $snap.unreadable += 'Liked Songs (API refused - see log)'
    }
    $snap
}

function Save-Snapshot($snap) {
    $dir = Join-Path $snapshotRoot (Get-Date -Format 'yyyy-MM-dd')
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }   # re-run on the same day replaces it
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($id in $snap.playlists.Keys) {
        $pl = $snap.playlists[$id]
        $pl.tracks | Export-Csv -LiteralPath (Join-Path $dir (Get-SafeFileName $pl.name $id)) -NoTypeInformation -Encoding utf8
    }
    $snap | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $dir 'snapshot.json') -Encoding utf8
    Log "Snapshot saved: $dir"
    $dir
}

function Get-PreviousSnapshot {
    $today = Get-Date -Format 'yyyy-MM-dd'
    $prev = Get-ChildItem $snapshotRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and $_.Name -ne $today -and (Test-Path (Join-Path $_.FullName 'snapshot.json')) } |
        Sort-Object Name | Select-Object -Last 1
    if ($prev) { Get-Content (Join-Path $prev.FullName 'snapshot.json') -Raw | ConvertFrom-Json -Depth 20 -AsHashtable }
}

function Format-Track($t) { "$($t.artists) - $($t.name)" }

function Compare-Snapshots($old, $new) {
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($id in $old.playlists.Keys) {
        $o = $old.playlists[$id]
        if (-not $new.playlists.Contains($id)) {
            $lines.Add("PLAYLIST GONE: '$($o.name)' ($($o.tracks.Count) songs) is no longer in your library. Its last copy is in the previous snapshot folder.")
            continue
        }
        $n = $new.playlists[$id]
        $newUris = @{}; foreach ($t in $n.tracks) { $newUris[$t.uri] = $t }
        $oldUris = @{}; foreach ($t in $o.tracks) { $oldUris[$t.uri] = $t }

        $removed = @($o.tracks | Where-Object { -not $newUris.ContainsKey($_.uri) })
        $greyed  = @($n.tracks | Where-Object { -not $_.is_playable -and $oldUris.ContainsKey($_.uri) -and $oldUris[$_.uri].is_playable })
        $back    = @($n.tracks | Where-Object { $_.is_playable -and $oldUris.ContainsKey($_.uri) -and -not $oldUris[$_.uri].is_playable })
        if (-not ($removed -or $greyed -or $back)) { continue }

        $lines.Add("`n$($n.name):")
        foreach ($t in $greyed)  { $lines.Add("  - now UNPLAYABLE (greyed out): $(Format-Track $t)") }
        foreach ($t in $removed) { $lines.Add("  - no longer in playlist (you or Spotify removed it): $(Format-Track $t)") }
        foreach ($t in $back)    { $lines.Add("  + playable again: $(Format-Track $t)") }
    }
    $lines
}

function Format-Unplayable($snap) {
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($id in $snap.playlists.Keys) {
        $pl = $snap.playlists[$id]
        $bad = @($pl.tracks | Where-Object { -not $_.is_playable })
        if ($bad) {
            $lines.Add("`n$($pl.name): $($bad.Count) unplayable")
            foreach ($t in $bad) { $lines.Add("  - $(Format-Track $t)") }
        }
    }
    $lines
}

# ---------------------------------------------------------------- main

if ($Setup) { Invoke-Setup }

if (Test-Path $pendingPath) {
    $pending = Get-Content $pendingPath
    Send-Alert $pending[0] (($pending | Select-Object -Skip 1) -join "`n")
}

try {
    $script:accessToken = Get-AccessToken
    $snap = New-Snapshot
    if ($snap.playlists.Count -eq 0) {
        throw [SpotifyRefusedException]::new('Spotify returned zero readable playlists.', 0)
    }
    $prev = Get-PreviousSnapshot
    $dir = Save-Snapshot $snap
    Remove-Item $failPath -ErrorAction SilentlyContinue

    $trackCount = ($snap.playlists.Values | ForEach-Object { $_.tracks.Count } | Measure-Object -Sum).Sum
    $summary = "$($snap.playlists.Count) playlists, $trackCount songs saved to:`n$dir"
    if ($snap.unreadable) {
        $summary += "`n`nNot covered (Spotify only lets personal apps read playlists you own or collaborate on):`n  " + ($snap.unreadable -join "`n  ")
    }

    if (-not $prev) {
        $unplayable = Format-Unplayable $snap
        $body = "Baseline snapshot of your Spotify playlists is saved.`n`n$summary"
        $body += if ($unplayable) { "`n`nAlready unplayable (greyed out) today:$($unplayable -join "`n")" } else { "`n`nNo unplayable songs today." }
        Send-Alert 'Spotify watch: baseline saved' $body
    } else {
        $changes = Compare-Snapshots $prev $snap
        if ($changes) {
            Send-Alert 'Spotify watch: songs changed in your playlists' ("Changes since $(([datetime]$prev.taken).ToString('yyyy-MM-dd')):`n$($changes -join "`n")`n`n$summary")
            Add-Content (Join-Path $snapshotRoot 'changes-log.md') ("`n## $(Get-Date -Format 'yyyy-MM-dd')`n" + ($changes -join "`n"))
        } else {
            Log 'No changes since last snapshot; no email.'
        }
    }
    exit 0
} catch [SpotifyRefusedException] {
    $e = $_.Exception
    Log "REFUSED: $($e.Message)"
    $hint = if ($e.Status -in 400, 401) {
        "This looks like the saved login was revoked or expired. Re-run setup:`n  pwsh C:\scripts\spotify-watch\spotify-watch.ps1 -Setup -ClientId <id>`nIf that also fails, Spotify may have changed who can use its API."
    } else {
        "Spotify refused a request the export depends on. This is the signal the watch exists for: Spotify may be restricting playlist export or its developer API.`nCheck https://developer.spotify.com/documentation/web-api (changelog) and consider taking a fresh copy by other means (Account > Privacy > Download your data) while it still works."
    }
    Send-Alert 'Spotify watch: EXPORT BLOCKED' "$hint`n`nDetails: $($e.Message)`n`nThe last good snapshot is in $snapshotRoot"
    exit 2
} catch {
    $fails = 1 + [int](Get-Content $failPath -ErrorAction SilentlyContinue)
    Set-Content $failPath $fails
    Log "Run failed ($fails in a row): $($_.Exception.Message)"
    if ($fails -eq $networkFailuresBeforeAlert) {
        Send-Alert 'Spotify watch: failing repeatedly' "The weekly Spotify snapshot has failed $fails runs in a row. Last error:`n$($_.Exception.Message)`n`nLogs: $logDir"
    }
    exit 1
}
