# spotify-watch

Weekly snapshot of the user's Spotify playlists. It is also the early warning if Spotify ever closes off
playlist export. Context and the user's exit criteria are in
`Desktop\Entertainment\spotify.md`.

Each run (`spotify-watch.ps1`):

1. Saves every playlist the user owns or collaborates on, plus Liked Songs, as one CSV per playlist in
   `Desktop\Entertainment\Music\spotify-snapshots\YYYY-MM-DD\`, with a `snapshot.json` for diffing.
   Columns: position, name, artists, album, added_at, is_playable, is_local, isrc, duration_ms, uri.
   Snapshots are small and kept forever: they're the record of what a playlist held once songs grey out.
2. Diffs against the previous snapshot. It emails and appends to `changes-log.md` in the same folder when
   a song becomes unplayable (licence lost), leaves a playlist, comes back, or a whole playlist disappears.
   **Quiet weeks send nothing.**
3. If Spotify refuses the export (HTTP 4xx from the API, revoked login, zero playlists returned), it emails
   **"EXPORT BLOCKED"** and exits 2. Plain network failures (laptop offline) only email after 3 runs in a row.

Email goes from `f3ttt@protonmail.com` to `billsmaphia@protonmail.com` through the local Proton Bridge
(credential `ProtonBridgeSMTP`). The user approved these automatic emails on 2026-09-29. If Bridge is down,
the alert is saved to `pending-alert.txt` and resent on the next run.

## Limits of Spotify's API (Development Mode, since Feb/Mar 2026)

- Only playlists the user **owns or collaborates on** have readable contents. Followed playlists by other
  people are listed as "Not covered" in the baseline email.
- The app owner needs an active **Premium** subscription. Cancelling Premium will break the script, and the
  script reports that as EXPORT BLOCKED.
- Playlist contents come from `/playlists/{id}/items`; the old `/tracks` endpoint is gone. Items are under
  `.item`, older shapes under `.track`, and the script handles both.
- Unplayable detection relies on `is_playable` with `market=from_token`.

## One-time setup

1. Go to https://developer.spotify.com/dashboard, log in with your Spotify account, and choose **Create app**.
   Name it something like "spotify-watch". Enter the redirect URI **`http://127.0.0.1:8888/callback`**
   exactly (Spotify rejects `localhost`). Tick **Web API** and save.
2. Copy the app's **Client ID**. No client secret is needed; the script uses PKCE.
3. Run:
   ```
   pwsh C:\scripts\spotify-watch\spotify-watch.ps1 -Setup -ClientId <client id>
   ```
   A browser opens, you approve read-only access, and the script takes the baseline snapshot and emails it.
   Use `-NoEmail` to print the report instead of sending it.

State lives in `%LOCALAPPDATA%\spotify-watch\`: `config.json` (client id), `refresh-token.dat`
(DPAPI-encrypted, readable only by this user on this machine), `log\`. The refresh token rotates on
every run and the script saves the new one.

## Scheduled task

`spotify-watch-weekly`: Sundays 12:00 PM, StartWhenAvailable (a missed run catches up on wake). Headless
like the other pwsh jobs:

```powershell
$a = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument '--headless pwsh -NoProfile -File C:\scripts\spotify-watch\spotify-watch.ps1'
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 12:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'spotify-watch-weekly' -Action $a -Trigger $t -Settings $s
```
