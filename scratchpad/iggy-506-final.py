#!/usr/bin/env python3
"""One-off final cleanup for #12 (Iggy #506).

Replaces all 3 existing #12 files on seedbox with one canonical file that has:
  - BBC station-ID patterns (20-sec ID chapters)
  - BBC News block detection (180-sec chapter when "Six Music News" appears)
  - Cleaner ASCII titles
Also deletes the corresponding episodes from ABS so it re-discovers fresh.

Uses the cached SRT (~/.rollins-sync/transcripts/iggy-506.srt) — no whisper needed.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = os.path.expanduser("~/.rollins-sync")
spec = importlib.util.spec_from_file_location("sync", os.path.join(ROOT, "sync.py"))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

SSH = "USER@SEEDBOX.example.com"  # placeholder; edit before reuse
REMOTE = "~/media/Audio/Rollins-Archive/iggy-confidential"
SRT_CACHE = os.path.join(ROOT, "transcripts/iggy-506.srt")
FINAL_NAME = "12-Iggy Confidential 2026-03-29 Iggy Bids Adieu.mp3"
OLD_FILES = [
    "12-Iggy Confidential 2026-03-29 Iggy Bids Adieu.mp3",
    "12-Iggy Confidential 2026-03-29 - VARIANT A station IDs.mp3",
    "12-Iggy Confidential 2026-03-29 - VARIANT B song breaks.mp3",
]

# Patterns now have per-pattern length override:
#   (regex, label, block_length_seconds)
PATTERNS = [
    # News block FIRST — more specific match before generic "6 music"
    (r"\b(?:six|6)\s+music\s+news\b", "BBC News",       180),
    (r"\bbbc\s+news\b",                "BBC News",       180),
    (r"BBC\s*(?:Radio\s*)?6\s*music", "BBC 6 Music ID",  20),
    (r"\b(?:six|6)\s+music\b",         "6 Music ID",      20),
    (r"\bask your smart speaker\b",    "Smart speaker ID", 20),
    (r"this is iggy confidential",     "Confidential ID",  20),
    (r"(?:I am|I'm|this is) iggy pop", "Iggy intro",       20),
    (r"iggy confidential",             "Show name drop",   20),
]
MERGE_S = 60


def detect_blocks(entries: list) -> list:
    raw = []
    for start, _end, text in entries:
        for pat, label, length in PATTERNS:
            if re.search(pat, text, re.I):
                raw.append({"start": start, "label": label, "length": length})
                break

    blocks = []
    for r in raw:
        if blocks and r["start"] - blocks[-1]["end"] < MERGE_S:
            # Extend end to cover longer override if present
            blocks[-1]["end"] = max(blocks[-1]["end"], r["start"] + r["length"])
            blocks[-1]["labels"].append(r["label"])
        else:
            blocks.append({
                "start": r["start"],
                "end":   r["start"] + r["length"],
                "labels": [r["label"]],
            })
    return blocks


def build_chapters(blocks: list, duration_s: float) -> list:
    chapters = []
    cursor = 0.0
    for b in blocks:
        if b["start"] > cursor + 5:
            chapters.append((cursor, b["start"], f"Content {len(chapters) + 1}"))
        labels = " / ".join(dict.fromkeys(b["labels"]))
        chapters.append((b["start"], b["end"], sync.clean_title(f"ID - {labels}")))
        cursor = b["end"]
    if cursor < duration_s:
        chapters.append((cursor, duration_s, f"Content {len(chapters) + 1}"))
    return chapters


def main() -> int:
    if not os.path.exists(SRT_CACHE):
        sync.log("ERROR: cached SRT not found")
        return 1

    os.makedirs(sync.WORK, exist_ok=True)
    work = tempfile.mkdtemp(dir=sync.WORK)
    try:
        sync.log("=== iggy-506 final cleanup start ===")

        # Pull one existing file for audio (all 3 share identical audio)
        source_remote = f"{SSH}:{REMOTE}/{OLD_FILES[1]}"   # use VARIANT A as source
        local_mp3 = os.path.join(work, "source.mp3")
        sync.log(f"  pulling source MP3 ({OLD_FILES[1]})")
        subprocess.run(["rsync", "-a", source_remote, local_mp3], check=True)

        duration = sync.get_duration_s(local_mp3)
        entries = sync.parse_srt(SRT_CACHE)
        sync.log(f"  duration {duration / 60:.1f} min | {len(entries)} transcript segments")

        blocks = detect_blocks(entries)
        chapters = build_chapters(blocks, duration)
        sync.log(f"  {len(blocks)} marker blocks -> {len(chapters)} chapters")
        for s, e, t in chapters:
            mm, ss = int(s) // 60, int(s) % 60
            sync.log(f"    {mm:02d}:{ss:02d}  {t} ({int(e - s)}s)")

        # Inject + name canonically
        meta = os.path.join(work, "chapters.txt")
        sync.write_chapter_meta(chapters, meta)
        chaptered = os.path.join(work, "chaptered.mp3")
        sync.inject_chapters(local_mp3, meta, chaptered)
        final_local = os.path.join(work, FINAL_NAME)
        os.rename(chaptered, final_local)

        # 1. Delete the two non-canonical files from seedbox (keep FINAL_NAME for now,
        #    will overwrite via rsync)
        cfg = sync.load_config()
        for old in OLD_FILES:
            if old == FINAL_NAME:
                continue
            subprocess.run(["ssh", SSH, "rm", "-f", f"{REMOTE}/{old}"], check=True)
            sync.log(f"  removed seedbox file: {old}")

        # 2. Upload canonical (overwrites the original file in place)
        subprocess.run(["rsync", "-a", final_local, f"{SSH}:{REMOTE}/"], check=True)
        sync.log(f"  uploaded canonical: {FINAL_NAME}")

        # 3. ABS: delete all matching episode entries, trigger rescan
        token = sync.abs_login(cfg["abs"])
        if token:
            item_resp = urllib.request.urlopen(urllib.request.Request(
                f"{cfg['abs']['url']}/api/items/{cfg['abs']['podcast_item_id']}?expanded=1",
                headers={"Authorization": f"Bearer {token}"})).read()
            item = json.loads(item_resp)
            deleted = 0
            for ep in item.get("media", {}).get("episodes", []):
                path = (ep.get("audioFile", {}) or {}).get("metadata", {}).get("path", "")
                if any(old in os.path.basename(path) for old in OLD_FILES):
                    urllib.request.urlopen(urllib.request.Request(
                        f"{cfg['abs']['url']}/api/podcasts/{cfg['abs']['podcast_item_id']}/episode/{ep['id']}?hard=0",
                        method="DELETE", headers={"Authorization": f"Bearer {token}"})).read()
                    deleted += 1
                    sync.log(f"  ABS deleted episode: {os.path.basename(path)}")
            sync.log(f"  ABS deleted {deleted} episode entries")
            urllib.request.urlopen(urllib.request.Request(
                f"{cfg['abs']['url']}/api/libraries/{cfg['abs']['library_id']}/scan?force=1",
                method="POST", headers={"Authorization": f"Bearer {token}"})).read()
            sync.log("  ABS scan triggered")
        sync.log("=== iggy-506 final cleanup end ===")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
