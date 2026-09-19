# scripts

**Last verified: 2026-09-19.** Upkeep rule: if this date is more than 7 days old, or `ls C:\scripts`
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
| `copyNasGranular.ps1` | Per-file copy from Source→Destination with SHA-256 verify and move-to-Processed on success. Paths via CLI params or `~/.copynas/config.json` (CLI wins). Consolidated from six dated one-off variants that used to live in this folder. |
| `rollins-sync.py` | Daily poll of the rollins-archive.com RSS feed. See `rollins-archive-sync/` below for the fuller pipeline this feeds into. |
| `yt-sync.sh` | Downloads new videos from monitored YouTube channels in WSL, rsyncs to the seedbox, removes local copies. Config: `~/yt-sync/channels.conf`. |
| `yt-backfill.sh` | Companion to `yt-sync.sh` — grabs one older video per channel per hourly run, walking backwards through each playlist, paced to look like normal human viewing rather than a scrape. |

## Subdirectory projects

| Folder | What it does | Details |
|---|---|---|
| `garmin_trends/` | Pulls Garmin Connect data (via WSL venv + `garminconnect` lib) into weekly trend/insights reports. `garmin_client.py` (auth/session), `pull_report.py` (main trend report), `activity_log.py` (recent activities), `intensity_minutes_report.py` (yearly weekly intensity-minutes aggregate). | [[reference_garmin_trends_tool]] |
| `morning-briefing/` | `briefing.py` — daily audio briefing generated fresh each morning (WSL). | — |
| `book-awards-briefing/` | `book_awards_briefing.py` — monthly audio briefing on newly-announced book awards (WSL). Scheduled via `book-awards-monthly-task.xml`. | `README.md` (see its claude.exe path gotcha) |
| `ruck-events-briefing/` | `ruck_events_briefing.py` — weekly audio briefing on upcoming local ruck events (WSL). | — |
| `rollins-archive-sync/` | Full pipeline syncing Henry Rollins's *Harmony In My Head* and Iggy Pop's *Iggy Confidential* into a self-hosted Audiobookshelf instance with ad/station-ID/promo chapter markers. `sync.py`, `iggy-backfill.py`, plus a `stinger-analysis/` subfolder. | Has its own `README.md` — read that first for this one, it's substantially more involved than a one-liner covers. |
| `claude-memory-backup/` | `backup-memory.ps1` — backs up all projects' Claude Code memory plus global config (CLAUDE.md, settings, skills, commands; never credentials) — which live outside OneDrive's sync root — to OneDrive on a schedule, with daily/weekly/monthly tiers and verified atomic swaps. | Has its own `README.md`. |
| `email-monitor/` | Read-only incremental scanner for new mail synchronized into Thunderbird through Proton Bridge. It emits JSON for recurring Codex classification and keeps only offsets and Message-IDs as state. | Has its own `README.md`. |

| `actual-budget/` | `backup-actual-budget.ps1` — nightly zip of the local Actual Budget data dir into `OneDrive\Desktop\Financial\Actual Budget\backups\` (90-day retention). Task `ActualBudgetBackup`, 2:00 AM. | `README.md` |
| `workboard/` | Empty as of 2026-09-19 (created 2026-09-13). Purpose not recorded — ask before assuming. | — |

## Housekeeping folders (not projects)

- `.claude/` — Claude Code settings for this directory.
- `.playwright-mcp/` — Playwright MCP scratch output; safe to ignore.
- `.git/` — this repo. Uncommitted as of 2026-09-19: `email-monitor/`, `.claude/`,
  `.playwright-mcp/`, `garmin_trends/intensity_minutes_report.py`, and this README's edits.

## Scheduled tasks (Windows Task Scheduler) → what they run

| Task | Schedule | Runs |
|---|---|---|
| `morning-briefing-daily` | daily 5:30 AM | `morning-briefing/briefing.py` |
| `book-awards-monthly` | 1st of month 6:15 AM | `book-awards-briefing/book_awards_briefing.py` |
| `ruck-events-daily` | daily 6:00 PM | `ruck-events-briefing/ruck_events_briefing.py` |
| `rollins-sync-daily` / `iggy-backfill-daily` | daily 4:00 / 2:00 AM | `rollins-archive-sync/sync.py` / `iggy-backfill.py` |
| `yt-sync-daily` / `yt-sync-backfill-hourly` | daily 6:00 AM / periodic | `yt-sync.sh` / `yt-backfill.sh` |
| `ActualBudgetBackup` | daily 2:00 AM | `actual-budget/backup-actual-budget.ps1` |
| `ClaudeMemoryBackup` | daily 8:40 PM | `claude-memory-backup/backup-memory.ps1` |
| `Personal Email Monitor Intake` | every 15 min | `email-monitor/run-scan.ps1` |

Last-run status: check with `Get-ScheduledTask | Get-ScheduledTaskInfo` (nonzero `LastTaskResult`
= failed). As of 2026-09-19, `book-awards-monthly` (path bug: claude.exe wrote to `C:\home`) and
`iggy-backfill-daily` (stale `~/.rollins-sync/sync.py` path) had both exited 1; the fixes are on
branch `fix-book-awards-iggy` and take effect once merged into `C:\scripts`.
