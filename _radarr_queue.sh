#!/bin/bash
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}" "${P:?P not set}" "${PK:?PK not set}"

curl -s "$R/queue?pageSize=100&apikey=$K" -o /tmp/rq.json
curl -s "$P/search?query=Siege+of+Jadotville&type=search&apikey=$PK" -o /tmp/rp.json

python3 <<'PYEOF'
import json, re

print("===RADARR QUEUE (Jadotville)===")
recs = json.load(open("/tmp/rq.json")).get("records", [])
hit = [r for r in recs if "jadotville" in (r.get("title","").lower())]
if not hit:
    print("  nothing in queue yet for Jadotville")
for r in hit:
    sl = r.get("sizeleft",0); sz = r.get("size",1) or 1
    pct = 100*(1-sl/sz)
    status = r.get("status"); state = r.get("trackedDownloadState")
    tl = r.get("timeleft","?"); title = r.get("title","")[:70]
    print("  {:.0f}% | {:.1f}GB | {}/{} | ETA {} | {}".format(pct, sz/1024**3, status, state, tl, title))

print("===PROWLARR: releases sorted by seeders (BLOCKED = filtered by your profile)===")
def bad(t):
    return re.search(r"REMUX|TrueHD|DTS.?HD|2160p|UHD|\b4K\b|MULTi|TRUEFRENCH|iTALiAN|GERMAN|SPANISH|VOSTFR|DUBBED|HINDI|RUSSIAN|POLISH|BR-DISK|BDMV|AV1|OPUS|DOVI|DolbyVision", t, re.I)
rows = [r for r in json.load(open("/tmp/rp.json")) if isinstance(r, dict)]
rows.sort(key=lambda x:-x.get("seeders",0))
shown = 0
for r in rows:
    t = r.get("title","")
    flag = "BLOCKED" if bad(t) else "ok"
    seed = r.get("seeders",0); gb = (r.get("size",0) or 0)//1024**3
    idx = (r.get("indexer","") or "")[:10]
    print("  {:>4} seed | {:>2}G | {:7s} | {:10s} | {}".format(seed, gb, flag, idx, t[:66]))
    shown += 1
    if shown >= 12: break
if not shown:
    print("  no results")
PYEOF
