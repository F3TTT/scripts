#!/usr/bin/env python3
"""One-off migration: add VAD + medium model + BBC promo patterns to
the runtime ~/.rollins-sync/config.json's iggy-confidential category.

Idempotent: re-running it doesn't duplicate patterns. Backs up the old
config to config.json.bak-pre-vad-medium-migration.
"""
import json, os, shutil

p = os.path.expanduser("~/.rollins-sync/config.json")
shutil.copy2(p, p + ".bak-pre-vad-medium-migration")
cfg = json.load(open(p))
HOME = os.path.expanduser("~")
iggy = cfg["category_settings"]["iggy-confidential"]

iggy["whisper_model"] = os.path.join(HOME, "tools/whisper.cpp/models/ggml-medium.en.bin")
iggy["vad_model"] = os.path.join(HOME, "tools/whisper.cpp/models/ggml-silero-v5.1.2.bin")
iggy["vad_threshold"] = 0.4

promo_patterns = [
    [r"\bcoming up (?:in an? )?(?:hour|few|moment)\b", "BBC promo"],
    [r"\bnext on (?:six|6)\s+music\b", "BBC promo"],
    [r"\btonight at \d", "BBC promo"],
    [r"\bdon'?t miss\b", "BBC promo"],
]
existing = iggy.get("patterns", [])
existing_pats = {e[0] for e in existing}
to_add = [p for p in promo_patterns if p[0] not in existing_pats]
iggy["patterns"] = to_add + existing

with open(p, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(p, 0o600)

print("whisper_model:", iggy["whisper_model"])
print("vad_model:    ", iggy["vad_model"])
print("vad_threshold:", iggy["vad_threshold"])
print("patterns:")
for pat, lbl in iggy["patterns"]:
    print(f"  {lbl:20}  /{pat}/")
