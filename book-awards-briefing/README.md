# book-awards-briefing

`book_awards_briefing.py` (WSL) — monthly audio briefing on newly announced book awards. Runs
headless Claude (`claude --print`, tools limited to WebSearch/Read/Write/Edit, no Bash) to check a
fixed award list, picks books against the taste profile in `Entertainment\books.md`, then
narrates (edge-tts) and rsyncs to Audiobookshelf as the "Book-Awards" podcast. No news → no episode.

- Scheduled: `book-awards-monthly`, 1st of month 6:15 AM. Definition: `book-awards-monthly-task.xml`
  (recreate with `schtasks /create /xml <path>`; not in git).
- State: `~/.book-awards-briefing/state.json` (WSL) — which award stages are already covered.
- Design notes: `Desktop\Operations - Life Systems\book-awards-briefing.md`.
- Check `LastTaskResult` in Task Scheduler if an episode is missing.

## Gotcha: claude.exe is a Windows binary

`claude_exe` is `/mnt/c/Users/ADMIN/.local/bin/claude.exe`, launched from WSL. Any path handed to it
(prompt text, `--add-dir`) must be a Windows path — `/home/x` is read as `C:\home\x`. The script
converts them with `winpath()` (`wslpath -w`) and keeps using WSL paths itself. Before this fix
(2026-09-19) Claude wrote results and state to `C:\home\worldtar\.book-awards-briefing\`, the script
never saw them, and the job exited 1 on 8/1, 9/1 and 9/19 with "claude did not write ...".

Diagnostics: each run logs Claude's result text and any `permission_denials` to
`~/.book-awards-briefing/log/<date>.log`. `--dry-run` skips TTS/rsync/ABS but the Claude step still
updates state.json and books.md. `--publish-from <results.json>` republishes a saved results file.
