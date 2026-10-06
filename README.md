# scripts

**Last verified: 2026-10-06.** Upkeep rule: if this date is more than 7 days old, or `ls C:\scripts`
shows a file/folder not listed below, re-scan and update this file and the date before relying on
it. Update it in the same session whenever a script or project is added or removed.

Personal automation monorepo. **Check this file before writing a new script** — if
something here already does the job or is close, extend it instead of building a
parallel tool. (This file exists *because* that check didn't happen once — see
`extract-mbox-message.pl` below.)

Two subprojects keep their own, more detailed README — this file gives the one-line
version and points there for specifics.

## Top-level scripts

| Script | What it does |
|---|---|
| `extract-mbox-message.pl` | Pull message(s) out of a Thunderbird mbox file. Two modes: (1) original — find message(s) containing a plain substring, print raw for manual carving; (2) `--out-dir` — single-pass batch mode: match one or more `--subject`/`--from` regexes, RFC2047-decode headers, decode quoted-printable/base64 bodies, extract PDF attachments, write a `manifest.json` index. Handles mbox files that mix CRLF/LF line endings depending on which mail relay wrote a given header. |
| `imap-delete.pl` | Companion to `extract-mbox-message.pl` — acts on the *live* IMAP account instead of the local mbox cache. Given a file of target Message-IDs (e.g. from a manifest.json) and a `--sender=` substring, locates each message across a candidate folder list (read-only unless `--delete` is passed), then deletes matches via COPY→Trash + STORE \Deleted + EXPUNGE (source folder only — refuses to run if "Trash" is in the folder list). Defaults to Proton Bridge on `127.0.0.1:1143`; override via `IMAP_HOST`/`IMAP_PORT`. See the script's header comment for the "sender pattern is a literal substring, not a regex" gotcha before reusing. |
| `seedbox_health.sh` | Seedbox health check + auto-fix. Run before other seedbox work — writes an ISO timestamp to `~/.seedbox_health_last_run` on success ([[feedback_seedbox_health_check]] memory enforces checking this first). Exit 0 clean / 1 issues remain. |
| `_radarr_add.sh`, `_radarr_lookup.sh`, `_radarr_verify.sh` | Runs on the seedbox. General-purpose-ish Radarr helpers: add a movie + search, inspect config/look up a movie, post-upgrade verification. Originally written for one incident but reusable as-is for a different movie. (Three sibling scripts — `_radarr_jado/queue/speed.sh` — were hardcoded to that one incident's movie title and deleted 2026-09-01 once it resolved; if you need queue-progress/history tooling again, write it against a movie ID passed as an argument instead of hardcoded.) |
| `nas_health.sh` | Runs on the QNAP NAS (piped over SSH: `wsl ssh kneaplro@192.168.1.7 sh -s < C:\scripts\nas_health.sh`). Read-only system check: firmware version, RAID, mounted volumes, app versions, CPU. System-level only — never lists share contents. Key login needs DataVol4 unlocked after a reboot. |
| `upnp-port-mappings.ps1` | Read-only: discovers the home router via UPnP and lists any automatic port forwards it holds. Prints "No UPnP gateway answered" when router UPnP is off (the desired state). Re-run after router changes (e.g. the Flint 2). |
| `copyNasGranular.ps1` | Per-file copy from Source→Destination with SHA-256 verify and move-to-Processed on success. Paths via CLI params or `~/.copynas/config.json` (CLI wins). Consolidated from six dated one-off variants that used to live in this folder. |
| `rollins-sync.py` | Daily poll of the rollins-archive.com RSS feed. See `rollins-archive-sync/` below for the fuller pipeline this feeds into. |
| `yt-sync.sh` | Downloads new videos from monitored YouTube channels in WSL, rsyncs to the seedbox, removes local copies. Config: `~/yt-sync/channels.conf`. |
| `restore-claude-sessions.ps1` | After a reboot (e.g. a Windows update), reopens every Claude Code session it killed, one Windows Terminal tab each, running `claude --resume <id>` in the session's own folder with its title on the tab. Finds them as the transcripts last written in the 5 min before boot; already-resumed ones drop out, so re-running is safe. `-List` previews, `-Before <time>` for a crash without a reboot, `-WindowMinutes` to widen. |
| `yt-backfill.sh` | Companion to `yt-sync.sh` — grabs one older video per channel per hourly run, walking backwards through each playlist, paced to look like normal human viewing rather than a scrape. |

## Subdirectory projects

| Folder | What it does | Details |
|---|---|---|
| `garmin_trends/` | Pulls Garmin Connect data (via WSL venv + `garminconnect` lib) into weekly trend/insights reports (now including a body-weight section). `garmin_client.py` (auth/session), `pull_report.py` (main trend report), `activity_log.py` (recent activities), `weight_log.py` (body-weight trend from the weigh-in cache that `pull_report.py` fills; shown in lb), `intensity_minutes_report.py` (yearly weekly intensity-minutes aggregate). | [[reference_garmin_trends_tool]] |
| `morning-briefing/` | `briefing.py` — daily audio briefing generated fresh each morning (WSL). | — |
| `book-awards-briefing/` | `book_awards_briefing.py` — monthly audio briefing on newly-announced book awards (WSL). Scheduled via `book-awards-monthly-task.xml`. | `README.md` (see its claude.exe path gotcha) |
| `ruck-events-briefing/` | `ruck_events_briefing.py` — weekly audio briefing on upcoming local ruck events (WSL). | — |
| `rollins-archive-sync/` | Full pipeline syncing Henry Rollins's *Harmony In My Head* and Iggy Pop's *Iggy Confidential* into a self-hosted Audiobookshelf instance with ad/station-ID/promo chapter markers. `sync.py`, `iggy-backfill.py`, plus a `stinger-analysis/` subfolder. | Has its own `README.md` — read that first for this one, it's substantially more involved than a one-liner covers. |
| `claude-memory-backup/` | `backup-memory.ps1` — backs up all projects' Claude Code memory plus global config (CLAUDE.md, settings, skills, commands; never credentials) — which live outside OneDrive's sync root — to OneDrive on a schedule, with daily/weekly/monthly tiers and verified atomic swaps. | Has its own `README.md`. |
| `email-monitor/` | **Retired 2026-09-29** (backend removed, wasn't working well; task disabled, folder kept uncommitted in case it's revived). Read-only incremental scanner for new mail synchronized into Thunderbird through Proton Bridge. It emits JSON for recurring Codex classification and keeps only offsets and Message-IDs as state. | Has its own `README.md`. |
| `actual-budget/` | `backup-actual-budget.ps1` — nightly zip of the local Actual Budget data dir into `OneDrive\Desktop\Financial\Actual Budget\backups\` (90-day retention). Task `ActualBudgetBackup`, 2:00 AM. | `README.md` |
| `yt-local/` | `yt-local-sync.ps1` — native Windows/PowerShell 7 yt-dlp pull of YouTube channels to `C:\Media\YouTube\<slug>` on the laptop at highest quality (MKV). New uploads + 1 backfill video/channel/day, same pace as `yt-backfill.sh`. Channels in `channels.conf` (Molly Long). | `SETUP.md` (deps, task registration) |
| `spotify-watch/` | `spotify-watch.ps1` — weekly CSV snapshot of the user's Spotify playlists to `OneDrive\Desktop\Entertainment\Music\spotify-snapshots\`, diffed week over week; emails (Proton Bridge) when songs grey out or leave a playlist, or if Spotify blocks API export. Created 2026-09-29. | `README.md` (one-time Spotify developer app setup) |
| `ultracc-stock-watch/` | `stock_watch.py` — runs **on the seedbox** (cron `*/10`) and posts to the "Discord - seedbox alerts" webhook when a 6TB+ Ultra.cc "Metaliux - Canada" plan goes from 0 to >0 available (the user wants to upgrade from the full 4TB plan; Canada has been sold out for months). Also alerts if the store page stops parsing. Deployed copy and `config.json` live in `~/ultracc-stock-watch/` on the seedbox. Created 2026-10-06; retire after upgrading. | `README.md` |
| `bluesky-follower-activity/` | `follower_activity.py` — one-off-but-rerunnable analysis: for a Bluesky account, counts what its followers did (posts, replies, likes) over the last 30 days, bucketed by ET hour. Public APIs only, no auth. Used 2026-10-04 to set kaizengrey.com posting slots (noon / 7:30pm ET). Re-run as the follower count grows. | — |
| `workboard/` | Empty as of 2026-09-19 (created 2026-09-13). Purpose not recorded — ask before assuming. | — |

## Housekeeping folders (not projects)

- `.claude/` — Claude Code settings for this directory.
- `.playwright-mcp/` — Playwright MCP scratch output; safe to ignore.
- `.git/` — this repo. Uncommitted as of 2026-10-06: `email-monitor/`, `.claude/`.
  `.claude/worktrees/` holds per-session git worktrees; as of 2026-10-06 `ebay-watch` and
  `thunderbird-orders` are unmerged branches.

## Git hooks (per-clone setup)

The gitleaks pre-commit hook is versioned at `.githooks/pre-commit`. `core.hooksPath` is a
per-clone setting, so on every fresh clone run once:

```
git config core.hooksPath .githooks
```

The hook runs gitleaks through WSL with `wslpath`-translated git dir/work tree (needed for linked
worktrees) and fails closed: any gitleaks error output blocks the commit, not just a leak finding.

## Scheduled tasks (Windows Task Scheduler) → what they run

| Task | Schedule | Runs |
|---|---|---|
| `morning-briefing-daily` | daily 5:30 AM | `morning-briefing/briefing.py` |
| `book-awards-monthly` | 1st of month 6:15 AM | `book-awards-briefing/book_awards_briefing.py` |
| `ruck-events-daily` | daily 6:00 PM | `ruck-events-briefing/ruck_events_briefing.py` |
| `rollins-sync-daily` / `iggy-backfill-daily` | daily 4:00 / 2:00 AM | `rollins-archive-sync/sync.py` / `iggy-backfill.py` |
| `yt-sync-daily` / `yt-sync-backfill-hourly` | daily 6:00 AM / periodic | `yt-sync.sh` / `yt-backfill.sh` |
| `yt-local-daily` | daily 8:00 AM (+0-30 min random, StartWhenAvailable) | `yt-local/yt-local-sync.ps1` (pwsh via `conhost.exe --headless`). No active channels on this laptop since 2026-09-29; runs only for the weekly yt-dlp upgrade. |
| `ActualBudgetBackup` | daily 2:00 AM | `actual-budget/backup-actual-budget.ps1` |
| `ClaudeMemoryBackup` | daily 8:40 PM | `claude-memory-backup/backup-memory.ps1` (via `conhost.exe --headless`, no window) |
| `spotify-watch-weekly` | Sundays 12:00 PM (StartWhenAvailable) | `spotify-watch/spotify-watch.ps1` (pwsh via `conhost.exe --headless`) — registered 2026-09-29 |
| `Personal Email Monitor Intake` | **DISABLED 2026-09-29** (was every 15 min) | `email-monitor/run-scan.ps1` |

Last-run status: check with `Get-ScheduledTask | Get-ScheduledTaskInfo` (nonzero `LastTaskResult`
= failed). The 2026-09-19 failures of `book-awards-monthly` and `iggy-backfill-daily` were fixed
and merged; both exited 0 on their latest runs (checked 2026-10-06).
