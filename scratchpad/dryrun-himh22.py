#!/usr/bin/env python3
"""Dry-run: load the live HIMH patterns + the cached #22 SRT, run
detect_ad_blocks and build_chapters, show what chapters we'd produce.
"""
import os, sys, importlib.util

spec = importlib.util.spec_from_file_location("sync", os.path.expanduser("~/.rollins-sync/sync.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

cfg = m.load_config()
cat = cfg["category_settings"]["harmony-in-my-head"]
srt = os.path.expanduser("~/.rollins-sync/transcripts/harmony-in-my-head/22-Harmony In My Head 2026-05-29.srt")

entries = m.parse_srt(srt)
print(f"{len(entries)} SRT segments")
blocks = m.detect_ad_blocks(entries, cat["patterns"], cat["merge_window_s"], cat["block_len_s"])
print(f"\n{len(blocks)} ad blocks detected:")
for b in blocks:
    mm1, ss1 = int(b["start"]) // 60, int(b["start"]) % 60
    mm2, ss2 = int(b["end"]) // 60, int(b["end"]) % 60
    print(f"  {mm1:02d}:{ss1:02d} -> {mm2:02d}:{ss2:02d}  labels={b['labels']}")

duration = 7195.0   # known from earlier ffprobe
chapters = m.build_chapters(blocks, duration, cat["marker_prefix"])
print(f"\n{len(chapters)} chapters:")
for s, e, t in chapters:
    mm, ss = int(s) // 60, int(s) % 60
    print(f"  {mm:02d}:{ss:02d}  {t}")
