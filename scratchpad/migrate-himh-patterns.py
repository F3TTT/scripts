#!/usr/bin/env python3
"""Replace harmony-in-my-head patterns in runtime config.json with the
expanded set (sponsor + KCRW self-promo + station-ID + theater ad).
Idempotent: rerunning is a no-op if the pattern list already matches.
"""
import json, os, shutil

p = os.path.expanduser("~/.rollins-sync/config.json")
shutil.copy2(p, p + ".bak-pre-himh-pattern-expansion")
cfg = json.load(open(p))
himh = cfg["category_settings"]["harmony-in-my-head"]

himh["patterns"] = [
    [r"KCRW sponsors? (?:include|comes?\s+from)", "KCRW sponsor"],
    [r"support (?:for this show|comes?\s+from)", "Sponsor"],
    [r"KCRW\.com/\w+", "KCRW self-promo"],
    [r"go to kcrw\.com to donate", "KCRW pledge"],
    [r"\b(?:only in the|on the) KCRW app\b", "KCRW app promo"],
    [r"\bin theaters (?:now|today|this|nationwide)\b", "Theater ad"],
    [r"(?:in select theaters|now in theaters|nationwide [A-Z][a-z]+)", "Theater ad"],
    [r"\bvoice of choice\b", "Station ID"],
    [r"\bthis is KCRW\b", "Station ID"],
    [r"\b89\.9\s*(?:FM,?\s*)?KCRW\b", "Station ID"],
    [r"\byou'?re listening to\b", "Station ID"],
    [r"\blive from KCRW\b", "KCRW music promo"],
    [r"\bVintage 24\b", "Vintage 24 promo"],
]

with open(p, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(p, 0o600)

print(f"{len(himh['patterns'])} patterns in HIMH category:")
for pat, lbl in himh["patterns"]:
    print(f"  {lbl:20}  /{pat}/")
