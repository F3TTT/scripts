#!/bin/bash
# Runs ON the seedbox. Post-upgrade verification for Radarr.
: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${R:?R not set}" "${K:?K not set}"

curl -s "$R/system/status?apikey=$K"        -o /tmp/rv_status.json
curl -s "$R/customformat?apikey=$K"          -o /tmp/rv_cf.json
curl -s "$R/qualityprofile?apikey=$K"        -o /tmp/rv_qp.json
curl -s "$R/queue?pageSize=100&apikey=$K"    -o /tmp/rv_q.json
curl -s "$R/health?apikey=$K"                -o /tmp/rv_health.json

python3 <<'PYEOF'
import json

def load(p):
    try: return json.load(open(p))
    except Exception as e: return {"_err": str(e)}

print("=== 1. SERVICE / VERSION ===")
st = load("/tmp/rv_status.json")
if isinstance(st, dict) and st.get("version"):
    print("  Radarr version:", st.get("version"), "| branch:", st.get("branch"), "| OK — API responding")
else:
    print("  PROBLEM: status did not return cleanly:", st)

print("=== 2. HEALTH WARNINGS ===")
h = load("/tmp/rv_health.json")
if isinstance(h, list):
    if not h: print("  none")
    for w in h:
        print("  [{}] {}".format(w.get("type"), w.get("message")))
else:
    print("  could not read health:", h)

print("=== 3. CUSTOM FORMATS (codec-block filter) ===")
cf = load("/tmp/rv_cf.json")
if isinstance(cf, list):
    print("  count:", len(cf), "(expected 9)")
    for c in sorted(cf, key=lambda x: x.get("id",0)):
        print("   id {:>2} | {}".format(c.get("id"), c.get("name")))
else:
    print("  could not read custom formats:", cf)

print("=== 4. PROFILE FORMAT SCORES (expect -10000 on each block format; minFormatScore 0) ===")
qp = load("/tmp/rv_qp.json")
if isinstance(qp, list):
    for prof in qp:
        if prof.get("id") not in (1, 4):   # "Any" and "HD-1080p" are the ones we scored
            continue
        items = prof.get("formatItems", [])
        scored = [(i.get("name"), i.get("score")) for i in items if i.get("score")]
        neg = [s for s in scored if s[1] == -10000]
        other = [s for s in scored if s[1] != -10000]
        print("  Profile {} '{}': minFormatScore={} | formats scored -10000: {}".format(
            prof.get("id"), prof.get("name"), prof.get("minFormatScore"), len(neg)))
        for name, score in neg:
            print("     -10000  {}".format(name))
        for name, score in other:
            print("     {:>6}  {}  <-- NOT -10000, review".format(score, name))
        if not scored:
            print("     WARNING: no non-zero format scores on this profile — filter may have been reset!")
else:
    print("  could not read profiles:", qp)

print("=== 5. JADOTVILLE QUEUE ===")
q = load("/tmp/rv_q.json")
recs = q.get("records", []) if isinstance(q, dict) else []
hit = [r for r in recs if "jadotville" in (r.get("title","").lower())]
if not hit:
    print("  not in queue — either finished/imported, or removed. (Check library separately.)")
for r in hit:
    sl = r.get("sizeleft",0); sz = r.get("size",1) or 1
    print("  {:.1f}% | {:.2f}GB | {}/{} | ETA {} | {}".format(
        100*(1-sl/sz), sz/1024**3, r.get("status"), r.get("trackedDownloadState"),
        r.get("timeleft","?"), r.get("title","")[:60]))
PYEOF
