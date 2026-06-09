#!/usr/bin/env python3
"""Reprocess Iggy episodes with BBC-specific station-ID patterns and a
longer ID-chapter window (20 s vs the old 15 s). Used to fix episodes
that the daily backfill produced as single-chapter (because rollins-sync
uses KCRW patterns that don't match BBC content).

For each listed target:
  - try to reuse cached SRT at ~/.rollins-sync/transcripts/iggy-<num>.srt
  - else pull MP3 from seedbox and run whisper (~30 min)
  - cache SRT for future tweaks
  - generate chapters using BBC patterns
  - inject (codec copy) and rsync back to seedbox (overwrites file in place)
  - ABS delete-and-rediscover

Targets are hard-coded near the bottom — edit and re-run.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.expanduser("~/.rollins-sync")
TRANSCRIPT_DIR = os.path.join(ROOT, "transcripts")
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

# share helpers with rollins-sync
spec = importlib.util.spec_from_file_location("sync", os.path.join(ROOT, "sync.py"))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

REMOTE_FOLDER = "~/media/Audio/Rollins-Archive/iggy-confidential"
SSH_HOST = "USER@SEEDBOX.example.com"  # placeholder; edit before reuse

# ----- BBC station-ID patterns -----

BBC_PATTERNS = [
    (r"BBC\s*(?:Radio\s*)?6\s*music", "BBC 6 Music ID"),
    (r"\b(?:six|6)\s+music\b", "6 Music ID"),
    (r"\bask your smart speaker\b", "Smart speaker ID"),
    (r"this is iggy confidential", "Confidential ID"),
    (r"(?:I am|I'm|this is) iggy pop", "Iggy intro"),
    (r"iggy confidential", "Show name drop"),
]
BBC_MERGE_S = 60
ID_CHAPTER_LEN_S = 20   # was 15 in the compare script


def bbc_chapters(entries: list, duration_s: float) -> list:
    raw = []
    for start, _end, text in entries:
        for pat, label in BBC_PATTERNS:
            if re.search(pat, text, re.I):
                raw.append({"start": start, "label": label})
                break
    blocks = []
    for r in raw:
        if blocks and r["start"] - blocks[-1]["start"] < BBC_MERGE_S:
            blocks[-1]["labels"].append(r["label"])
        else:
            blocks.append({"start": r["start"], "labels": [r["label"]]})

    chapters = []
    cursor = 0.0
    for b in blocks:
        if b["start"] > cursor + 5:
            chapters.append((cursor, b["start"], f"Content {len(chapters) + 1}"))
        end = min(duration_s, b["start"] + ID_CHAPTER_LEN_S)
        labels = " / ".join(dict.fromkeys(b["labels"]))
        chapters.append((b["start"], end, sync.clean_title(f"ID - {labels}")))
        cursor = end
    if cursor < duration_s:
        chapters.append((cursor, duration_s, f"Content {len(chapters) + 1}"))
    return chapters


# ----- per-target processing -----

def process_target(target: dict) -> None:
    file_basename = target["file_basename"]
    num = target["num"]
    sync.log(f"--- iggy reprocess: {file_basename}")

    work = tempfile.mkdtemp(dir=sync.WORK)
    try:
        # Pull MP3 from seedbox
        local_mp3 = os.path.join(work, file_basename)
        remote_path = f"{SSH_HOST}:{REMOTE_FOLDER}/{file_basename}"
        sync.log("  rsync MP3 down from seedbox")
        subprocess.run(["rsync", "-a", remote_path, local_mp3], check=True)

        duration = sync.get_duration_s(local_mp3)
        sync.log(f"  duration: {duration / 60:.1f} min")

        # SRT — cache or transcribe
        srt_path = os.path.join(work, "transcript.srt")
        cache_srt = os.path.join(TRANSCRIPT_DIR, f"iggy-{num}.srt")
        if os.path.exists(cache_srt):
            sync.log(f"  using cached transcript: {cache_srt}")
            shutil.copy2(cache_srt, srt_path)
        else:
            wav = os.path.join(work, "audio.wav")
            sync.log("  ffmpeg -> 16kHz mono WAV")
            sync.to_wav_16k(local_mp3, wav)
            sync.log("  whisper.cpp transcribing (~30 min)")
            cfg = sync.load_config()
            sync.transcribe(wav, cfg["whisper_bin"], cfg["whisper_model"],
                            cfg["whisper_threads"], os.path.join(work, "transcript"))
            os.remove(wav)
            shutil.copy2(srt_path, cache_srt)
            sync.log(f"  cached at {cache_srt}")

        entries = sync.parse_srt(srt_path)
        sync.log(f"  {len(entries)} transcript segments")

        # Build BBC chapters
        chs = bbc_chapters(entries, duration)
        n_id = sum(1 for c in chs if c[2].startswith("ID"))
        sync.log(f"  generated {len(chs)} chapters ({n_id} ID markers, ID length {ID_CHAPTER_LEN_S}s)")

        # Inject and replace
        meta = os.path.join(work, "chapters.txt")
        sync.write_chapter_meta(chs, meta)
        chaptered = os.path.join(work, "chaptered.mp3")
        sync.inject_chapters(local_mp3, meta, chaptered)

        sync.log("  rsync back to seedbox (overwrite)")
        subprocess.run(["rsync", "-a", chaptered,
                        f"{SSH_HOST}:{REMOTE_FOLDER}/{file_basename}"], check=True)

        # ABS refresh
        cfg = sync.load_config()
        sync.abs_refresh_episode(cfg["abs"], file_basename)
        sync.log("  done")
    finally:
        shutil.rmtree(work, ignore_errors=True)


TARGETS = [
    {"num": 504, "file_basename": "10-Iggy Confidential 2026-03-15.mp3"},
    {"num": 505, "file_basename": "11-Iggy Confidential 2026-03-22.mp3"},
    {"num": 506, "file_basename": "12-Iggy Confidential 2026-03-29 - VARIANT A station IDs.mp3"},
]


def main() -> int:
    os.makedirs(sync.WORK, exist_ok=True)
    sync.log("=== iggy-reprocess run start ===")
    for t in TARGETS:
        try:
            process_target(t)
        except subprocess.CalledProcessError as e:
            sync.log(f"  FAILED subprocess: {e}")
        except Exception as e:
            sync.log(f"  FAILED: {type(e).__name__}: {e}")
    sync.log("=== iggy-reprocess run end ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
