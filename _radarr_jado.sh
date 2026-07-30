#!/bin/bash
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}"
curl -s "$R/movie/162?apikey=$K" -o /tmp/jm.json
curl -s "$R/history?pageSize=30&sortKey=date&sortDirection=descending&apikey=$K" -o /tmp/jh.json
python3 <<'PYEOF'
import json
m = json.load(open("/tmp/jm.json"))
print("Movie:", m.get("title"), m.get("year"), "| hasFile:", m.get("hasFile"), "| monitored:", m.get("monitored"))
mf = m.get("movieFile") or {}
if mf:
    print("  file:", mf.get("relativePath"))
    print("  quality:", (mf.get("quality") or {}).get("quality", {}).get("name"),
          "| size:", round((mf.get("size",0))/1024**3, 2), "GB")
h = json.load(open("/tmp/jh.json")).get("records", [])
jado = [r for r in h if r.get("movieId") == 162]
print("Recent history for movie 162:")
for r in jado[:6]:
    print("  ", r.get("eventType"), "|", r.get("date","")[:19], "|", r.get("sourceTitle","")[:55])
PYEOF
