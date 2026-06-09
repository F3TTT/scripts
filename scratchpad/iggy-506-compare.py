#!/usr/bin/env python3
"""One-off: re-process Iggy #506 with two alternative chapter strategies and
upload both side-by-side so user can A/B them in Plappa.

  Variant A — BBC station-ID phrases as chapter markers
              (catches "BBC 6 Music", "Iggy Confidential", "I'm Iggy Pop",
               "play six music", etc.)
  Variant B — Song-break detection via gaps in whisper transcript
              (Iggy talks → song [~3-4 min gap in transcript] → Iggy talks again;
               chapter at end of each Iggy-talk block)

Transcribes ONCE, saves the SRT to ~/.rollins-sync/transcripts/iggy-506.srt
so future tweaks can skip the 30-min whisper step.

Uploads to seedbox alongside the original. ABS will see them as additional
episodes of the same podcast.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

# share helpers with rollins-sync
ROOT = os.path.expanduser("~/.rollins-sync")
spec = importlib.util.spec_from_file_location("sync", os.path.join(ROOT, "sync.py"))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

TRANSCRIPT_DIR = os.path.join(ROOT, "transcripts")
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

SOURCE_REMOTE = "USER@SEEDBOX.example.com:/home/USER/media/Audio/Rollins-Archive/iggy-confidential/12-Iggy Confidential 2026-03-29 Iggy Bids Adieu.mp3"  # placeholder; edit before reuse
SOURCE_BASENAME = "12-Iggy Confidential 2026-03-29 Iggy Bids Adieu.mp3"
REMOTE_FOLDER = "~/media/Audio/Rollins-Archive/iggy-confidential"

CACHE_SRT = os.path.join(TRANSCRIPT_DIR, "iggy-506.srt")


# ----- Variant A: BBC station-ID phrases -----

BBC_PATTERNS = [
    (r"BBC\s*(?:Radio\s*)?6\s*music", "BBC 6 Music ID"),
    (r"\b(?:six|6)\s+music\b", "6 Music ID"),
    (r"\bask your smart speaker\b", "Smart speaker ID"),
    (r"this is iggy confidential", "Confidential ID"),
    (r"(?:I am|I'm|this is) iggy pop", "Iggy intro"),
    (r"iggy confidential", "Show name drop"),
]
BBC_MERGE_S = 60


def variant_a_chapters(entries: list, duration_s: float) -> list:
    raw = []
    for start, _end, text in entries:
        for pat, label in BBC_PATTERNS:
            if re.search(pat, text, re.I):
                raw.append({"start": start, "label": label})
                break
    # merge close together
    blocks = []
    for r in raw:
        if blocks and r["start"] - blocks[-1]["start"] < BBC_MERGE_S:
            blocks[-1]["labels"].append(r["label"])
        else:
            blocks.append({"start": r["start"], "labels": [r["label"]]})
    # build chapters: each station-ID marker = its own chapter starting at marker
    chapters = []
    cursor = 0.0
    for i, b in enumerate(blocks):
        if b["start"] > cursor + 5:
            chapters.append((cursor, b["start"], f"Content {len(chapters) + 1}"))
        # ID block length is uncertain - use 15s as a guess
        end = min(duration_s, b["start"] + 15)
        labels = " / ".join(dict.fromkeys(b["labels"]))
        chapters.append((b["start"], end, sync.clean_title(f"ID - {labels}")))
        cursor = end
    if cursor < duration_s:
        chapters.append((cursor, duration_s, f"Content {len(chapters) + 1}"))
    return chapters


# ----- Variant B: song-break detection via transcript gaps -----

SONG_GAP_S = 120        # gaps >= this in the transcript = likely a song
MIN_TALK_BLOCK_S = 8    # ignore micro-bursts


def variant_b_chapters(entries: list, duration_s: float) -> list:
    """Identify Iggy-talk blocks (clusters of segments) separated by song gaps,
    then make chapters: 'Iggy talks N' for each talk block, 'Song N' for each gap."""
    if not entries:
        return [(0.0, duration_s, "Content 1")]

    # Cluster consecutive segments separated by <SONG_GAP_S
    clusters = []
    cur = [entries[0]]
    for e in entries[1:]:
        last_end = cur[-1][1]
        if e[0] - last_end < SONG_GAP_S:
            cur.append(e)
        else:
            clusters.append(cur)
            cur = [e]
    clusters.append(cur)

    # Build chapter list, alternating talk and song segments
    chapters = []
    last_end = 0.0
    for i, cl in enumerate(clusters):
        cl_start = cl[0][0]
        cl_end = cl[-1][1]
        # Song gap before this talk cluster
        if cl_start - last_end >= SONG_GAP_S:
            chapters.append((last_end, cl_start, f"Song {len([c for c in chapters if c[2].startswith('Song')]) + 1}"))
        # Filter tiny clusters as noise into the previous song
        if cl_end - cl_start < MIN_TALK_BLOCK_S:
            last_end = cl_end
            continue
        chapters.append((cl_start, cl_end, f"Iggy talks {len([c for c in chapters if c[2].startswith('Iggy')]) + 1}"))
        last_end = cl_end
    # Trailing song / outro if any
    if last_end < duration_s - 5:
        chapters.append((last_end, duration_s, f"Song {len([c for c in chapters if c[2].startswith('Song')]) + 1}"))
    return chapters


# ----- main -----

def main() -> int:
    work = tempfile.mkdtemp(dir=sync.WORK)
    sync.log("=== iggy-506 compare run start ===")
    try:
        # 1. Pull MP3 from seedbox locally (cheap, ~104 MB)
        local_mp3 = os.path.join(work, SOURCE_BASENAME)
        sync.log(f"  pulling MP3 from seedbox")
        subprocess.run(["rsync", "-a", SOURCE_REMOTE, local_mp3], check=True)

        # 2. Get duration
        duration = sync.get_duration_s(local_mp3)
        sync.log(f"  duration: {duration / 60:.1f} min")

        # 3. Transcript: reuse cached SRT if present, else transcribe
        srt_path = os.path.join(work, "transcript.srt")
        if os.path.exists(CACHE_SRT):
            sync.log(f"  using cached transcript: {CACHE_SRT}")
            shutil.copy2(CACHE_SRT, srt_path)
        else:
            wav = os.path.join(work, "audio.wav")
            sync.log("  ffmpeg -> 16kHz mono WAV")
            sync.to_wav_16k(local_mp3, wav)
            sync.log("  whisper.cpp transcribing (~30 min)")
            cfg = sync.load_config()
            sync.transcribe(wav, cfg["whisper_bin"], cfg["whisper_model"],
                            cfg["whisper_threads"], os.path.join(work, "transcript"))
            os.remove(wav)
            # cache for future runs
            shutil.copy2(srt_path, CACHE_SRT)
            sync.log(f"  transcript cached at {CACHE_SRT}")

        entries = sync.parse_srt(srt_path)
        sync.log(f"  {len(entries)} transcript segments")

        cfg = sync.load_config()

        # 4. Variant A: BBC station IDs
        chs_a = variant_a_chapters(entries, duration)
        sync.log(f"  variant A (BBC IDs): {len(chs_a)} chapters, "
                 f"{sum(1 for c in chs_a if c[2].startswith('ID'))} ID markers")
        meta_a = os.path.join(work, "chapters_a.txt")
        sync.write_chapter_meta(chs_a, meta_a)
        out_a_local = os.path.join(work, "12-Iggy Confidential 2026-03-29 - VARIANT A station IDs.mp3")
        sync.inject_chapters(local_mp3, meta_a, out_a_local)
        sync.log("  variant A injected")

        # 5. Variant B: song-break detection
        chs_b = variant_b_chapters(entries, duration)
        sync.log(f"  variant B (song breaks): {len(chs_b)} chapters, "
                 f"{sum(1 for c in chs_b if c[2].startswith('Iggy'))} talk blocks, "
                 f"{sum(1 for c in chs_b if c[2].startswith('Song'))} songs")
        meta_b = os.path.join(work, "chapters_b.txt")
        sync.write_chapter_meta(chs_b, meta_b)
        out_b_local = os.path.join(work, "12-Iggy Confidential 2026-03-29 - VARIANT B song breaks.mp3")
        sync.inject_chapters(local_mp3, meta_b, out_b_local)
        sync.log("  variant B injected")

        # 6. Upload both to seedbox
        sync.log("  rsync both variants to seedbox")
        subprocess.run(["rsync", "-a", out_a_local,
                        f"USER@SEEDBOX.example.com:{REMOTE_FOLDER}/"], check=True)
        subprocess.run(["rsync", "-a", out_b_local,
                        f"USER@SEEDBOX.example.com:{REMOTE_FOLDER}/"], check=True)

        # 7. ABS refresh — delete any existing variant episodes, trigger scan
        sync.abs_refresh_episode(cfg["abs"], os.path.basename(out_a_local))
        sync.abs_refresh_episode(cfg["abs"], os.path.basename(out_b_local))

        sync.log("=== iggy-506 compare run end ===")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
