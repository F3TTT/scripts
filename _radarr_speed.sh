#!/bin/bash
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}"
curl -s "$R/queue?pageSize=100&apikey=$K" -o /tmp/rq.json
python3 <<'PYEOF'
import json
recs = json.load(open("/tmp/rq.json")).get("records", [])
for r in recs:
    if "jadotville" not in (r.get("title","").lower()): continue
    sl = r.get("sizeleft",0); sz = r.get("size",1) or 1
    pct = 100*(1-sl/sz)
    print("  progress {:.1f}%  |  {:.2f}GB total  |  {:.2f}GB left  |  ETA {}".format(
        pct, sz/1024**3, sl/1024**3, r.get("timeleft","?")))
    print("  state:", r.get("status"), "/", r.get("trackedDownloadState"), "| status msgs:",
          [m.get("title") for m in r.get("statusMessages",[])][:2])
PYEOF
