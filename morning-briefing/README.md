# morning-briefing

`briefing.py` (runs in WSL) — daily audio briefing: NWS weather, Miami Beach beach-flag
conditions, one headline each from non-political topic RSS feeds, narrated with edge-tts, rsynced
to the seedbox's Audiobookshelf "Podcasts" library (Morning-Briefing folder), old episodes pruned.

- Scheduled: `morning-briefing-daily`, 5:30 AM, `wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 /mnt/c/scripts/morning-briefing/briefing.py'`
- This is the deployed copy (runs in place via the WSL mount).
- Config: `~/.morning-briefing/config.json` (WSL). Logs: `~/.morning-briefing/log/<date>.log`.
- Design notes and change history: `Desktop\Operations - Life Systems\morning-briefing.md`.
