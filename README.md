# scripts

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
| `seedbox_health.sh` | Seedbox health check + auto-fix. Run before other seedbox work — writes an ISO timestamp to `~/.seedbox_health_last_run` on success ([[feedback_seedbox_health_check]] memory enforces checking this first). Exit 0 clean / 1 issues remain. |
| `_radarr_add.sh`, `_radarr_lookup.sh`, `_radarr_verify.sh` | Runs on the seedbox. General-purpose-ish Radarr helpers: add a movie + search, inspect config/look up a movie, post-upgrade verification. Written for one incident (see below) but less hardcoded than their siblings. |
| `_radarr_jado.sh`, `_radarr_queue.sh`, `_radarr_speed.sh` | Runs on the seedbox. **One-off diagnostic scripts, hardcoded to a single title** ("The Siege of Jadotville," Radarr movie ID 162) from a specific stuck-download investigation — not generic Radarr tools. Reuse only as a template, not as-is, for a different movie. |
| `copyNasGranular.ps1` | Per-file copy from Source→Destination with SHA-256 verify and move-to-Processed on success. Paths via CLI params or `~/.copynas/config.json` (CLI wins). Consolidated from six dated one-off variants that used to live in this folder. |
| `rollins-sync.py` | Daily poll of the rollins-archive.com RSS feed. See `rollins-archive-sync/` below for the fuller pipeline this feeds into. |
| `yt-sync.sh` | Downloads new videos from monitored YouTube channels in WSL, rsyncs to the seedbox, removes local copies. Config: `~/yt-sync/channels.conf`. |
| `yt-backfill.sh` | Companion to `yt-sync.sh` — grabs one older video per channel per hourly run, walking backwards through each playlist, paced to look like normal human viewing rather than a scrape. |

## Subdirectory projects

| Folder | What it does | Details |
|---|---|---|
| `garmin_trends/` | Pulls Garmin Connect data (via WSL venv + `garminconnect` lib) into weekly trend/insights reports. `garmin_client.py` (auth/session), `pull_report.py` (main trend report), `activity_log.py` (recent activities), `intensity_minutes_report.py` (yearly weekly intensity-minutes aggregate). | [[reference_garmin_trends_tool]] |
| `morning-briefing/` | `briefing.py` — daily audio briefing generated fresh each morning (WSL). | — |
| `book-awards-briefing/` | `book_awards_briefing.py` — monthly audio briefing on newly-announced book awards (WSL). Scheduled via `book-awards-monthly-task.xml`. | — |
| `ruck-events-briefing/` | `ruck_events_briefing.py` — weekly audio briefing on upcoming local ruck events (WSL). | — |
| `rollins-archive-sync/` | Full pipeline syncing Henry Rollins's *Harmony In My Head* and Iggy Pop's *Iggy Confidential* into a self-hosted Audiobookshelf instance with ad/station-ID/promo chapter markers. `sync.py`, `iggy-backfill.py`, plus a `stinger-analysis/` subfolder. | Has its own `README.md` — read that first for this one, it's substantially more involved than a one-liner covers. |
| `claude-memory-backup/` | `backup-memory.ps1` — backs up this project's Claude Code memory (which lives outside OneDrive's sync root, so nothing there is backed up by default) to OneDrive on a schedule. | Has its own `README.md`. |

## Not yet indexed here

- `garmin_trends/intensity_minutes_report.py` exists on disk but isn't committed as of this
  writing — check `git status` in that folder before assuming the tracked/untracked split
  matches what's actually there.
