# rollins-archive-sync

Personal pipeline for syncing Henry Rollins's *Harmony In My Head* (KCRW) and Iggy Pop's *Iggy Confidential* (BBC 6 Music) from [rollins-archive.com](https://rollins-archive.com) into a self-hosted Audiobookshelf instance with chapter markers for ad / station-ID / promo skipping.

## What it does

For each new episode in a watched RSS category:

1. Pull the MediaFire zip via `curl -L`
2. Extract MP3, transcode to 16 kHz mono WAV
3. Transcribe with [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (`ggml-small.en`)
4. Regex-match category-specific marker phrases in the SRT (KCRW sponsor reads, BBC station IDs, etc.)
5. Build an alternating `AD`/`ID`/`Content` chapter list
6. Re-encode to 128k CBR with chapters embedded (CBR — naive iOS players seek by byte offset and mis-land on VBR sources)
7. rsync to seedbox media folder
8. Audiobookshelf: DELETE the episode entry + library scan (ABS's PATCH endpoint silently ignores the `chapters` field; delete-and-rediscover is the only working refresh path)

## Files

| File | What |
|---|---|
| `sync.py` | Daily pipeline. Reads RSS, processes new episodes in watched categories. |
| `iggy-backfill.py` | Walks `/iggy/iggy-YYYY` index pages newest-first, processing one historical episode per run. |
| `scratchpad/` | One-off scripts from #506 chapter-tuning work. Not part of the daily pipeline; preserved for reference. |

## Runtime layout (WSL)

```
~/.rollins-sync/
├── sync.py                  # deployed from this repo
├── iggy-backfill.py         # deployed from this repo
├── config.json              # secrets live here, mode 600
├── state.json               # processed RSS GUIDs
├── iggy_backfill_state.json # backfill cursor (year + processed guids)
├── transcripts/             # SRT cache (last 5 per category)
└── log/<date>.log
```

`config.json` is the only file with secrets (ABS password, seedbox host) and never enters this repo. Hardcoded defaults in `sync.py` are placeholders; first run writes a sample `config.json` to fill in.

## Bootstrap requirements

- Ubuntu 24.04 (WSL2)
- `apt install build-essential cmake ffmpeg python3`
- whisper.cpp built at `~/tools/whisper.cpp/`, `ggml-small.en.bin` model downloaded
- ssh key configured for seedbox host
- Audiobookshelf instance with a Podcast library + folder pointing at the seedbox media root

## Schedule

Windows Task Scheduler:

| Task | Time | Command |
|---|---|---|
| `rollins-sync-daily` | 04:00 daily | `wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 ~/.rollins-sync/sync.py'` |
| `iggy-backfill-daily` | 06:00 daily | `wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 ~/.rollins-sync/iggy-backfill.py'` |

## Deploy

```powershell
wsl -d Ubuntu-24.04 -- bash -c 'cp /mnt/c/scripts/rollins-archive-sync/sync.py ~/.rollins-sync/sync.py'
wsl -d Ubuntu-24.04 -- bash -c 'cp /mnt/c/scripts/rollins-archive-sync/iggy-backfill.py ~/.rollins-sync/iggy-backfill.py'
```
