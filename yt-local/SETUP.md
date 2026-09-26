# yt-local — setup

Pulls YouTube channels to a **local folder on the laptop** at the **highest quality available**,
on a daily Windows scheduled task. Native Windows + PowerShell 7 — no WSL.

Separate from `yt-sync.sh` / `yt-backfill.sh` (repo root), which push capped 1080p H.264 to the
seedbox for Plex. Different destination and quality goal, so different script. The pacing is the same.

| Piece | Where |
|---|---|
| Script | `C:\scripts\yt-local\yt-local-sync.ps1` |
| Channel list | `C:\scripts\yt-local\channels.conf` (`slug|url[|destDir]`) |
| Task registration | `C:\scripts\yt-local\register-task.ps1` |
| Videos | `C:\Media\YouTube\<slug>\` (outside OneDrive on purpose, since video would eat the sync quota) |
| State (archive, backfill position, logs) | `%LOCALAPPDATA%\yt-local\` |

Current channels: **Molly Long** (`@mollylongchoreo`), 105 videos, ~4 h total, newest upload 2017.

## What each run does

Per channel:

1. **New uploads.** Looks at the newest 5 videos. The download archive skips anything already fetched.
2. **Backfill.** Grabs **1** older video, walking backwards from position 6. Position is saved in
   `backfill_state\<slug>.pos`. When it runs past the oldest video the file says `done` and backfill stops.

That's the same pace as the seedbox pipeline's `yt-backfill.sh` (1 old video per channel per day).
Both pipelines run from this laptop's IP, so adding a channel adds one video's worth of traffic a day,
not a burst. Extra politeness: 2 s between API requests, a random 15–45 s pause before each download,
a random 1–3 min gap between the new-upload check and the backfill, and a random 0–30 min task start delay.

**Molly Long timeline:** the first run (2026-09-26) pulled the newest 6. The remaining ~99 then arrive at
1/day and finish around **early January 2027**. To go faster, raise `-BackfillPerRun` (see below), but
2–3/day is about the ceiling before it stops looking like a person watching.

**Quality:** format `bv*+ba/b` means the best video stream of any codec (AV1/VP9/H.264, up to 4K/60 if it
exists) plus the best audio, merged to **MKV**. Many of these 2017 uploads only exist at 480p on YouTube.
That's the source, not the script. Check with `yt-dlp -F <url>`.

## Dependencies

Install from a normal (non-admin) PowerShell 7 prompt:

```powershell
winget install --id Microsoft.PowerShell -e   # PowerShell 7 (skip if `pwsh` already works)
winget install --id yt-dlp.yt-dlp -e          # the downloader
winget install --id DenoLand.Deno -e          # JS runtime yt-dlp needs for YouTube's player; without it some formats go missing
winget install --id Gyan.FFmpeg -e            # merges video+audio. Skip if `ffmpeg -version` already works (this laptop has it via Chocolatey)
```

Then **open a new terminal** (winget changes PATH) and check:

```powershell
yt-dlp --version; deno --version; ffmpeg -version | Select-Object -First 1
```

yt-dlp goes stale fast, and a stale yt-dlp is the usual way these jobs silently stop working. The script
runs `winget upgrade --id yt-dlp.yt-dlp` itself once a week, so no manual upkeep is needed.

## First run (manual)

```powershell
pwsh -NoProfile -File C:\scripts\yt-local\yt-local-sync.ps1
```

Output goes to the console and to `%LOCALAPPDATA%\yt-local\log\YYYY-MM-DD.log`.
If `Get-ExecutionPolicy` blocks it, add `-ExecutionPolicy Bypass`.

## Scheduled task

```powershell
cd C:\scripts\yt-local
.\register-task.ps1            # daily 8:00 AM + up to 30 min random delay
.\register-task.ps1 -At 9:15AM # different time. Re-running replaces the task
```

This registers **`yt-local-daily`**, which runs as you under PowerShell 7, only while you're logged on.
**StartWhenAvailable** is on, so if the laptop was asleep at 8 it runs once on wake instead of being
skipped. 8:00 stays clear of the 02/04/05/06 AM WSL jobs.

Check or run it:

```powershell
Get-ScheduledTask yt-local-daily | Get-ScheduledTaskInfo   # LastTaskResult 0 = ok
Start-ScheduledTask yt-local-daily                          # run now
Unregister-ScheduledTask yt-local-daily -Confirm:$false     # remove
```

## Common changes

- **Add a channel:** add a line to `channels.conf`, e.g. `somechannel|https://www.youtube.com/@handle/videos`.
  Add a third field for a custom folder. Use the `/videos` tab to skip Shorts and livestreams.
- **Backlog faster/slower:** add `-BackfillPerRun 2` to the task's argument string in `register-task.ps1`
  and re-run it.
- **Re-walk a backlog:** delete `%LOCALAPPDATA%\yt-local\backfill_state\<slug>.pos`. The archive still
  prevents re-downloads.
- **Retire a finished channel:** once its `.pos` says `done` and the channel is dormant, comment out its line.

## Troubleshooting

- **`HTTP Error 429` / "Sign in to confirm you're not a bot"** means YouTube is rate-limiting this IP.
  Stop, let it cool off for a day or two, and don't raise the backfill rate. If it persists, run
  `winget upgrade yt-dlp.yt-dlp` first.
- **Missing high-res formats / "no JS runtime" warning:** deno isn't on PATH for the task. Log off and on
  after installing it.
- **Two runs at once:** the second logs "another run holds the lock" and exits. That's harmless.
