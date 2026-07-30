#!/bin/bash
# Runs ON the seedbox. Add The Siege of Jadotville to Radarr (profile 4 = HD-1080p) and search.
# Config: sources ~/.seedbox/config.sh (see repo README for expected variables).
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}" "${MOVIES_ROOT:?MOVIES_ROOT not set}"

# Build the add payload from the lookup result so all metadata/images are correct.
curl -s "$R/movie/lookup?term=Siege+of+Jadotville&apikey=$K" | R="$R" K="$K" MOVIES_ROOT="$MOVIES_ROOT" python3 -c '
import json, os, sys, urllib.request
R = os.environ["R"]; K = os.environ["K"]
cands=json.load(sys.stdin)
m=next(x for x in cands if x.get("tmdbId")==334517)
m["qualityProfileId"]=4
m["rootFolderPath"]=os.environ["MOVIES_ROOT"]
m["monitored"]=True
m["minimumAvailability"]="released"
m["addOptions"]={"searchForMovie":True}
data=json.dumps(m).encode()
req=urllib.request.Request(f"{R}/movie?apikey={K}",data=data,headers={"Content-Type":"application/json"},method="POST")
try:
    res=json.load(urllib.request.urlopen(req))
    print("ADDED id",res["id"],"|",res["title"],res["year"],"| profile",res["qualityProfileId"],"| monitored",res["monitored"])
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read().decode()[:500])
'
