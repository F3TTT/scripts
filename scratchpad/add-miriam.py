#!/usr/bin/env python3
"""Append the Minute-with-Miriam pattern to the HIMH category in
runtime config. Idempotent."""
import json, os

p = os.path.expanduser("~/.rollins-sync/config.json")
cfg = json.load(open(p))
himh = cfg["category_settings"]["harmony-in-my-head"]
pat = [r"\bminute with [mM]iriam\b", "Miriam segment"]
if pat not in himh["patterns"]:
    himh["patterns"].append(pat)
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(p, 0o600)
    print("added Miriam pattern")
else:
    print("Miriam pattern already present")
print(f'now {len(himh["patterns"])} HIMH patterns:')
for pat, lbl in himh["patterns"]:
    print(f"  {lbl:20}  /{pat}/")
