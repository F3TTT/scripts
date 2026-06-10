#!/usr/bin/env python3
"""Find timestamps for the missed sponsor/station-ID/promo segments
in HIMH #22's whisper SRT."""
import re, os
SRT = os.path.expanduser("~/.rollins-sync/transcripts/harmony-in-my-head/22-Harmony In My Head 2026-05-29.srt")
text = open(SRT).read()

NEEDLES = [
    ("voice of choice",                 "opening station ID"),
    ("Fanatic, Henry Rollins",          "show ID (Fanatic)"),
    ("Jose Gonzalez live from KCRW",    "KCRW music promo"),
    ("We start Monday at 9",            "show-promo Monday"),
    ("Directed by John Carney",         "in-theaters-now ad"),
    ("Support comes from the Colburn",  "Colburn sponsor"),
    ("This is KCRW. We're all about",   "KCRW Love Letters self-promo"),
    ("I'm Tom Staubel",                 "station-ID montage start"),
    ("You're listening to the Reggae Beat", "Reggae Beat station ID"),
    ("Vintage 24",                      "Vintage 24 promo"),
    ("Only in the KCRW app",            "KCRW app self-promo tail"),
]

# Parse SRT into (start_seconds, text)
entries = []
for block in text.split("\n\n"):
    lines = block.strip().split("\n")
    if len(lines) >= 3:
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> ", lines[1])
        if m:
            h, mn, s, _ = map(int, m.groups())
            t = h * 3600 + mn * 60 + s
            entries.append((t, " ".join(lines[2:])))

print(f"{len(entries)} SRT segments\n")
print("missed-candidate timestamps:")
for needle, label in NEEDLES:
    for t, txt in entries:
        if needle.lower() in txt.lower():
            mm, ss = t // 60, t % 60
            print(f"  {mm:3d}:{ss:02d}  [{label}]  {txt[:80]}")
            break
    else:
        print(f"  --:--   [{label}]  NOT FOUND")
