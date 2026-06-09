#!/usr/bin/env python3
"""Smoke test: run the live sync.detect_ad_blocks against a VAD-produced
SRT and verify the BBC promo pattern matches. Uses the wide.srt from the
#506 windowed VAD scan stored in ~/.rollins-sync/work/.
"""
import importlib.util, os

spec = importlib.util.spec_from_file_location("sync", os.path.expanduser("~/.rollins-sync/sync.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

cfg = m.load_config()
cat = cfg["category_settings"]["iggy-confidential"]

# Use the wide.srt produced by VAD+medium on 61:40-65:00 of #506 earlier
srt = os.path.expanduser("~/.rollins-sync/work/wide.srt")
if not os.path.exists(srt):
    print("FATAL: wide.srt cache missing")
    raise SystemExit(2)

entries = m.parse_srt(srt)
print(f"loaded {len(entries)} SRT entries")
for s, e, t in entries:
    print(f"  {s:6.2f}s  {t[:80]}")

print()
print("running detect_ad_blocks with live patterns from config...")
blocks = m.detect_ad_blocks(entries, cat["patterns"], cat["merge_window_s"], cat["block_len_s"])
print(f"detected {len(blocks)} blocks:")
for b in blocks:
    print(f"  {b['start']:6.2f}s -> {b['end']:6.2f}s  labels={b['labels']}")

# Sanity: do we see BBC promo at all?
if any("BBC promo" in lbl for b in blocks for lbl in b["labels"]):
    print()
    print("PASS: BBC promo pattern matched")
else:
    print()
    print("FAIL: BBC promo pattern did not match — check pattern list or SRT")
    raise SystemExit(1)
