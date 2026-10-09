# ruck-events-briefing

`ruck_events_briefing.py` (WSL) — weekly audio briefing on upcoming local ruck events. Fetches
Sweatpals host profiles (JSON), filters to upcoming events within a radius of home that haven't
been reported, narrates (edge-tts), rsyncs to Audiobookshelf as the "Ruck-Events" podcast. No LLM
call. No new events → no episode.

- Scheduled: `ruck-events-daily`, 6:00 PM (script itself skips when nothing is new).
- State: `~/.ruck-events-briefing/state.json` (WSL) — fingerprints of events already reported.
- Status and abandoned approaches (Instagram scraping): `Desktop\Training\ruck-events\STATUS.md`.
