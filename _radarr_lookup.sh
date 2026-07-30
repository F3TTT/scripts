#!/bin/bash
# Runs ON the seedbox. Inspect Radarr config + look up the movie.
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}"

echo "===ROOTFOLDER==="
curl -s "$R/rootfolder?apikey=$K" | python3 -c 'import json,sys
for f in json.load(sys.stdin): print(f["path"], f["freeSpace"]//1024**3, "GB free")'

echo "===PROFILES==="
curl -s "$R/qualityprofile?apikey=$K" | python3 -c 'import json,sys
for p in json.load(sys.stdin): print(p["id"], p["name"])'

echo "===LOOKUP==="
curl -s "$R/movie/lookup?term=Siege+of+Jadotville&apikey=$K" | python3 -c 'import json,sys
for m in json.load(sys.stdin)[:6]:
    print(m.get("tmdbId"), m.get("year"), "|", m.get("title"), "|", "ALREADY-IN-RADARR" if m.get("id") else "new")'
