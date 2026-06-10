#!/usr/bin/env python3
"""One-off: query ABS for the HIMH 2026-05-29 episode and print chapters."""
import os, sys, json, urllib.request, time, importlib.util

spec = importlib.util.spec_from_file_location("sync", os.path.expanduser("~/.rollins-sync/sync.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cfg = m.load_config()
abs_cfg = cfg["abs"]
HIMH = cfg["category_settings"]["harmony-in-my-head"]["abs_podcast_item_id"]

time.sleep(5)  # let ABS finish scanning
token = m.abs_login(abs_cfg)
req = urllib.request.Request(
    f"{abs_cfg['url']}/api/items/{HIMH}?expanded=1",
    headers={"Authorization": f"Bearer {token}"},
)
item = json.loads(urllib.request.urlopen(req).read())
for ep in item.get("media", {}).get("episodes", []):
    path = (ep.get("audioFile", {}) or {}).get("metadata", {}).get("path", "")
    if "2026-05-29" in path:
        chs = ep.get("chapters", []) or []
        print(f"ep: {os.path.basename(path)}")
        print(f"{len(chs)} chapters:")
        for c in chs:
            mm, ss = int(c["start"]) // 60, int(c["start"]) % 60
            title = c["title"]
            print(f"  {mm:02d}:{ss:02d}  {title}")
