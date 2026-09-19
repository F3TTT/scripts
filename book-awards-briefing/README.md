# book-awards-briefing

`book_awards_briefing.py` (WSL) — monthly audio briefing on newly announced book awards. Runs
headless Claude (`claude --print`, tools limited to WebSearch/Read/Write/Edit, no Bash) to check a
fixed award list, picks books against the taste profile in `Entertainment\books.md`, then
narrates (edge-tts) and rsyncs to Audiobookshelf as the "Book-Awards" podcast. No news → no episode.

- Scheduled: `book-awards-monthly`, 1st of month 6:15 AM. Definition: `book-awards-monthly-task.xml`
  (recreate with `schtasks /create /xml <path>`; not in git).
- State: `~/.book-awards-briefing/state.json` (WSL) — which award stages are already covered.
- Design notes: `OneDrive\Desktop\Operations - Life Systems\book-awards-briefing.md`.
- Check `LastTaskResult` in Task Scheduler if an episode is missing.
