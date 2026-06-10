#!/usr/bin/env python3
"""Dump everything spoken (non-music, non-lyrics) between 18:41 and 118:22
in the HIMH #22 SRT so we can see what other ads/IDs got missed."""
import re, os

SRT = os.path.expanduser("~/.rollins-sync/transcripts/harmony-in-my-head/22-Harmony In My Head 2026-05-29.srt")
text = open(SRT).read()

GAP_START = 18 * 60 + 41   # 1121 s
GAP_END = 118 * 60 + 22    # 7102 s

entries = []
for block in text.split("\n\n"):
    lines = block.strip().split("\n")
    if len(lines) >= 3:
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> ", lines[1])
        if m:
            h, mn, s, _ = map(int, m.groups())
            t = h * 3600 + mn * 60 + s
            entries.append((t, " ".join(lines[2:])))

print(f"--- speech between {GAP_START//60}:{GAP_START%60:02d} and {GAP_END//60}:{GAP_END%60:02d} ---")

# Show all segments with non-lyric text. Skip lyrics (♪ ... ♪), short noise.
prev_t = -999
for t, txt in entries:
    if not (GAP_START <= t <= GAP_END):
        continue
    if re.fullmatch(r"[\s♪♫]*", txt):
        continue
    if len(txt) < 20:
        continue
    mm, ss = t // 60, t % 60
    gap_marker = "  <-- after gap" if t - prev_t > 30 else ""
    print(f"  {mm:3d}:{ss:02d}  {txt[:100]}{gap_marker}")
    prev_t = t
