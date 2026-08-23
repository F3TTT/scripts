#!/bin/bash
# Seedbox health check + auto-fix.
# Writes ISO timestamp to ~/.seedbox_health_last_run on success.
# Run: bash ~/seedbox_health.sh
# Exit 0 if clean, 1 if issues remain.

: "${SEEDBOX_CONFIG:=$HOME/.seedbox/config.sh}"
[ -f "$SEEDBOX_CONFIG" ] || { echo "ERROR: missing $SEEDBOX_CONFIG" >&2; exit 1; }
# shellcheck source=/dev/null
source "$SEEDBOX_CONFIG"
: "${S_KEY:?}" "${R_KEY:?}" "${SONARR:?}" "${RADARR:?}" "${PLEX:?}" "${PLEX_TOKEN:?}" "${BAZARR:?}" "${BAZARR_KEY:?}"
DL="$HOME/downloads/qbittorrent"

# Cron doesn't inherit the user's systemd session env, so `systemctl --user`
# emits "Failed to connect to bus: No medium found" and falls back to a less
# graceful restart. Export the dbus path so systemd-user calls work cleanly.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

echo "== Seedbox Health Check $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
ISSUES=0

# Run provenance — so "how/when did this last run" is answerable at a glance
# without diffing the append-only cron log. TRIGGER is inferred from the parent
# process: 'cron'/'sh' = the 04:30 cron job, 'sshd'/'bash' = a manual SSH run.
START_TS=$(date +%s)
TRIGGER=$(ps -o comm= -p "$PPID" 2>/dev/null | tr -d ' ')
[ -z "$TRIGGER" ] && TRIGGER=unknown

# 1. Malware/blocking files in downloads — auto-delete .exe/.scr/.lnk/.bat
echo
echo "[1] Malware scan"
MAL=$(find "$DL" -type f \( -iname '*.exe' -o -iname '*.scr' -o -iname '*.lnk' -o -iname '*.bat' \) 2>/dev/null)
if [ -n "$MAL" ]; then
    COUNT=$(echo "$MAL" | wc -l)
    echo "    found $COUNT — deleting:"
    echo "$MAL" | while read f; do
        echo "      rm $(basename "$f")"
        rm -- "$f" 2>/dev/null
    done
else
    echo "    clean"
fi

# 2. Sonarr + Radarr queue health + auto-flush of warnings.
# Reports queue stats, then DELETEs any queue items whose status is warning
# or whose trackedDownloadStatus is warning/error. blocklist=true so the
# bad release is permanently rejected; autoRedownloadFailed=True in Sonarr's
# settings means monitored items get re-searched automatically.
echo
echo "[2] Queue health + flush"
python3 - <<PYEOF
import json, urllib.request, sys
def q(url):
    try: return json.loads(urllib.request.urlopen(url, timeout=10).read()).get('records',[])
    except Exception as e: return [{'_err': str(e)}]
def delete(base, key, qid):
    url = f"{base}/queue/{qid}?removeFromClient=true&blocklist=true&skipRedownload=false&apikey={key}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False

issues = 0
for label, base, key in [('sonarr', '$SONARR', '$S_KEY'),
                          ('radarr', '$RADARR', '$R_KEY')]:
    recs = q(f"{base}/queue?pageSize=300&apikey={key}")
    if recs and isinstance(recs[0], dict) and '_err' in recs[0]:
        print(f'    {label}: API ERROR {recs[0]["_err"]}')
        issues += 1
        continue
    warn = [r for r in recs if r.get('status') == 'warning']
    pending = [r for r in recs if r.get('trackedDownloadState') == 'importPending']
    dead = [r for r in recs if r.get('status') == 'warning'
            and r.get('trackedDownloadState') == 'downloading'
            and (1 - r.get('sizeleft', 0) / max(r.get('size', 1), 1)) * 100 < 1]
    print(f'    {label}: total={len(recs)} warning={len(warn)} importPending={len(pending)} dead0pct={len(dead)}')
    # Flush anything whose status or trackedDownloadStatus is warning/error/failed.
    flush = []
    for r in recs:
        tds = (r.get('trackedDownloadStatus') or '').lower()
        st = (r.get('status') or '').lower()
        if tds in ('warning','error') or st in ('warning','failed'):
            flush.append(r)
    if flush:
        for r in flush[:5]:
            sl = r.get('sizeleft', 0); sz = r.get('size', 1) or 1
            pct = 100 * (1 - sl/sz)
            print(f"      FLUSH: qid={r['id']} ({pct:.0f}%) {r.get('title','')[:70]}")
        if len(flush) > 5:
            print(f"      ... and {len(flush) - 5} more")
        ok = sum(1 for r in flush if delete(base, key, r['id']))
        print(f"    {label}: flushed {ok}/{len(flush)} items (blocklisted; auto-redownload for monitored items)")
        if ok < len(flush):
            issues += 1
sys.exit(issues)
PYEOF
[ $? -ne 0 ] && ISSUES=$((ISSUES+1))

# 3. Disk quota
echo
echo "[3] Disk quota"
quota -s 2>/dev/null | tail -1 | awk '{printf "    used=%s quota=%s limit=%s\n", $2, $3, $4}'

# 4. Service health (port-level)
echo
echo "[4] Services"
for portname in 18725:plex 18726:sonarr 18727:radarr 18731:bazarr 18741:qbittorrent; do
    PORT=${portname%:*}
    NAME=${portname#*:}
    if (echo > /dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then
        echo "    $NAME (:$PORT): OK"
    else
        echo "    $NAME (:$PORT): DOWN"
        ISSUES=$((ISSUES+1))
    fi
done

# 5. qBit orphan sweep — categorize torrents:
#   A. "missing":  no file exists anywhere on disk.
#   B. "unmanaged": file exists in ~/downloads/ but is NOT in
#      Sonarr/Radarr's managed file list (queried via API), AND the
#      .torrent file is >7 days old (grace period for items still
#      being imported by Sonarr/Radarr).
# Authority is Sonarr's /episodefile + Radarr's /moviefile by file
# basename — they know what's actually being managed regardless of
# nested directory layout. This avoids false positives from naive
# filesystem path checks where Sonarr nests files under show/season/.
echo
echo "[5] qBit orphan sweep"
python3 - <<PYEOF
import os, glob, re, subprocess, sys, shutil, time, json, urllib.request
BT = os.path.expanduser("~/.local/share/qBittorrent/BT_backup")
HOME = os.path.expanduser("~")
DL_ROOTS = [
    f"{HOME}/downloads/qbittorrent",
    f"{HOME}/downloads/qbittorrent/radarr",
    f"{HOME}/downloads/qbittorrent/sonarr",
    f"{HOME}/downloads",
]
GRACE_DAYS = 7

SONARR = ("http://127.0.0.1:18726/sonarr/api/v3", "$S_KEY")
RADARR = ("http://127.0.0.1:18727/radarr/api/v3", "$R_KEY")

def api(base, key, path):
    try:
        return json.loads(urllib.request.urlopen(
            f"{base}{path}{'&' if '?' in path else '?'}apikey={key}", timeout=20).read())
    except Exception:
        return []

# Build managed-file basename index from Sonarr + Radarr.
managed = set()
for series in api(*SONARR, "/series"):
    for ef in api(*SONARR, f"/episodefile?seriesId={series['id']}"):
        p = ef.get("path") or ef.get("relativePath") or ""
        if p:
            managed.add(os.path.basename(p))
for mf in api(*RADARR, "/moviefile"):
    p = mf.get("path") or mf.get("relativePath") or ""
    if p:
        managed.add(os.path.basename(p))
print(f"    managed-file index: {len(managed)} files")

def bdecode(data, pos=0):
    c = data[pos:pos+1]
    if c == b"i":
        end = data.index(b"e", pos); return int(data[pos+1:end]), end+1
    if c == b"l":
        out = []; pos += 1
        while data[pos:pos+1] != b"e":
            v, pos = bdecode(data, pos); out.append(v)
        return out, pos+1
    if c == b"d":
        out = {}; pos += 1
        while data[pos:pos+1] != b"e":
            k, pos = bdecode(data, pos); v, pos = bdecode(data, pos); out[k] = v
        return out, pos+1
    m = re.match(rb"(\d+):", data[pos:])
    if not m: raise ValueError("bad bencode")
    length = int(m.group(1)); start = pos + len(m.group(0))
    return data[start:start+length], start+length

def torrent_files(path):
    try:
        with open(path, "rb") as f:
            obj, _ = bdecode(f.read())
    except Exception:
        return "", []
    info = obj.get(b"info", {}) or {}
    name = info.get(b"name", b"").decode(errors="replace")
    if b"files" in info:
        return name, [os.path.join(name, *[p.decode(errors="replace") for p in fe.get(b"path",[])])
                      for fe in info[b"files"]]
    return name, [name]

def exists_under(roots, files):
    for rel in files:
        for root in roots:
            if os.path.exists(os.path.join(root, rel)):
                return True
    return False

def basenames(files):
    out = set()
    for rel in files:
        out.add(os.path.basename(rel))
    return out

now = time.time()
removals = []
for tf in glob.glob(os.path.join(BT, "*.torrent")):
    name, files = torrent_files(tf)
    if not name: continue
    in_downloads = exists_under(DL_ROOTS, files)
    is_managed = bool(basenames(files) & managed)
    age_days = (now - os.path.getmtime(tf)) / 86400
    if not in_downloads and not is_managed:
        removals.append((tf, name, "missing", []))
    elif in_downloads and not is_managed and age_days >= GRACE_DAYS:
        dl_paths = []
        for root in DL_ROOTS:
            candidate = os.path.join(root, name)
            if os.path.exists(candidate):
                dl_paths.append(candidate)
        removals.append((tf, name, "unmanaged", dl_paths))

print(f"    orphans found: {len(removals)}")
freed = 0
for tf, name, cat, dl_paths in removals:
    h = os.path.basename(tf).split(".")[0]
    print(f"      [{cat:10s}] {h[:8]}  {name[:80]}")
    for ext in (".torrent", ".fastresume"):
        p = os.path.join(BT, h + ext)
        if os.path.exists(p):
            os.remove(p)
    for dlp in dl_paths:
        if os.path.isdir(dlp):
            for dirpath, _, fnames in os.walk(dlp):
                for fn in fnames:
                    try: freed += os.path.getsize(os.path.join(dirpath, fn))
                    except: pass
            shutil.rmtree(dlp, ignore_errors=True)
        elif os.path.exists(dlp):
            try: freed += os.path.getsize(dlp)
            except: pass
            os.remove(dlp)

if removals:
    print(f"    freed: {freed/1024/1024/1024:.2f} GB")
    subprocess.run(["systemctl", "--user", "restart", "qbittorrent"], check=False)
    print(f"    removed {len(removals)} BT_backup entries; qbittorrent restarted")
else:
    print("    nothing to remove; qbittorrent left running")
PYEOF

# 6. Plex: refresh every section + emptyTrash. Sonarr/Radarr's Plex Connect
# triggers a scan on import but never tells Plex to drop metadata for files
# that have been deleted; without this step the library shows ghost entries
# for everything we removed. Both calls are cheap no-ops on a clean library.
echo
echo "[5] Plex refresh + emptyTrash"
SEC_IDS=$(curl -sf -H "Accept: application/json" \
    "$PLEX/library/sections?X-Plex-Token=$PLEX_TOKEN" \
    | python3 -c "import json,sys; [print(d['key'], d.get('title','?')) for d in json.load(sys.stdin).get('MediaContainer',{}).get('Directory',[])]" 2>/dev/null)
if [ -n "$SEC_IDS" ]; then
    echo "$SEC_IDS" | while read sid title; do
        curl -sf "$PLEX/library/sections/$sid/refresh?X-Plex-Token=$PLEX_TOKEN" >/dev/null
        curl -sf -X PUT "$PLEX/library/sections/$sid/emptyTrash?X-Plex-Token=$PLEX_TOKEN" >/dev/null
        echo "    [$sid] $title — refresh + emptyTrash"
    done
else
    echo "    Plex unreachable; skipping"
    ISSUES=$((ISSUES+1))
fi

echo
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DUR=$(( $(date +%s) - START_TS ))
[ $ISSUES -gt 0 ] && EXIT=1 || EXIT=0

# Authoritative "last run" marker (single line, overwritten) — checked by the
# standing pre-work procedure. NOTE: this lives on the SEEDBOX, not on Windows.
echo "$NOW_ISO" > ~/.seedbox_health_last_run

# Append a one-line run record and keep the last 365 runs. This is the queryable
# history of how/when the check ran (trigger + outcome + duration) — scan it with
# `tail ~/.seedbox_health_history` instead of grepping the giant cron log.
printf '%s | trigger=%-7s | issues=%s | exit=%s | dur=%ss\n' \
    "$NOW_ISO" "$TRIGGER" "$ISSUES" "$EXIT" "$DUR" >> ~/.seedbox_health_history
tail -n 365 ~/.seedbox_health_history > ~/.seedbox_health_history.tmp 2>/dev/null \
    && mv ~/.seedbox_health_history.tmp ~/.seedbox_health_history

echo "timestamp written: $NOW_ISO (trigger=$TRIGGER, issues=$ISSUES, dur=${DUR}s)"
echo "issues requiring manual review: $ISSUES"
exit $EXIT
