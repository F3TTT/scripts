#!/bin/bash
# yt-sync — download new videos from monitored YouTube channels in WSL,
# rsync to seedbox, remove local copies (archive list survives).
#
# Note: YouTube interstitial ads are not part of the video file — yt-dlp
# downloads are already ad-free without SponsorBlock. SponsorBlock here
# only removes host-read sponsor reads / intros / outros etc. if a creator
# uses them and the community has flagged them. It's strictly a nice-to-have.
#
# Config: ~/yt-sync/channels.conf
#   One per line, format: <slug>|<url>
#   Use `/videos` suffix on channel URL to skip Live/Shorts sub-playlists.
#   Lines starting with # are comments.
#
# Env vars:
#   LIMIT=N — cap each channel to N most recent videos (default: 5)

set -u
YT="$HOME/.local/bin/yt-dlp"
ROOT="$HOME/yt-sync"
DOWNLOADS="$ROOT/downloads"
ARCHIVES="$ROOT/archive"
LOGS="$ROOT/log"
CONF="$ROOT/channels.conf"
SECRETS="$ROOT/config.sh"

# Load REMOTE_HOST, REMOTE_BASE, PLEX_TOKEN from ~/yt-sync/config.sh.
# Example config.sh:
#   REMOTE_HOST="user@seedbox.example.com"
#   REMOTE_BASE="~/media/YouTube"
#   PLEX_TOKEN="your-plex-token"
if [ ! -f "$SECRETS" ]; then
    echo "ERROR: $SECRETS not found. Create it with REMOTE_HOST, REMOTE_BASE, PLEX_TOKEN." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$SECRETS"
: "${REMOTE_HOST:?REMOTE_HOST must be set in $SECRETS}"
: "${REMOTE_BASE:?REMOTE_BASE must be set in $SECRETS}"
: "${PLEX_TOKEN:?PLEX_TOKEN must be set in $SECRETS}"

LIMIT="${LIMIT:-5}"

# SponsorBlock — optional. If primary up, used; else skipped silently.
SB_PRIMARY="https://sponsor.ajay.app"
SB_MIRRORS=(
    # Add a known-working mirror here if one becomes available.
    # sb.ltn.fi serves an anti-bot challenge to programmatic requests so it's
    # unusable as a direct API mirror despite having the DB dump.
)
SB_CATS='sponsor,selfpromo,interaction'

mkdir -p "$DOWNLOADS" "$ARCHIVES" "$LOGS"
LOG="$LOGS/$(date +%Y-%m-%d).log"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

if [ ! -f "$CONF" ]; then log "ERROR: $CONF missing"; exit 1; fi
log "=== yt-sync run start (LIMIT=$LIMIT per channel) ==="

# === Pick a working SponsorBlock endpoint (optional; never fatal) ===
SB_OPTS=""
SB_BASE=""
for ENDPOINT in "$SB_PRIMARY" "${SB_MIRRORS[@]}"; do
    if curl -sf --max-time 5 -o /dev/null "$ENDPOINT/api/status"; then
        SB_BASE="$ENDPOINT"; break
    fi
done
if [ -n "$SB_BASE" ]; then
    SB_OPTS="--sponsorblock-api $SB_BASE --sponsorblock-remove $SB_CATS"
    log "SponsorBlock: $SB_BASE (segment removal enabled)"
else
    log "SponsorBlock: all endpoints down — downloading without segment removal"
fi

ssh "$REMOTE_HOST" "mkdir -p $REMOTE_BASE" 2>>"$LOG"

# === Per-channel loop ===
# IMPORTANT: read CONF on FD 3, not stdin. yt-dlp's internal progress UI
# consumes bytes from FD 0; if FD 0 is bound to CONF (the usual `done < FILE`
# pattern) yt-dlp eats the next channel and the loop exits early. Reproduced
# 2026-06-10 — first run skipped the third channel entirely after a long
# download finished.
while IFS='|' read -r -u 3 slug url; do
    [[ -z "${slug// /}" || "${slug:0:1}" == "#" ]] && continue
    slug="$(echo "$slug" | xargs)"
    url="$(echo "$url" | xargs)"
    [ -z "$url" ] && continue

    log "--- channel: $slug ---"
    DL="$DOWNLOADS/$slug"
    AR="$ARCHIVES/$slug.txt"
    mkdir -p "$DL"

    "$YT" \
        --download-archive "$AR" \
        --no-overwrites \
        --playlist-end "$LIMIT" \
        --match-filter "duration <= 3600" \
        -f "bv*[height<=1080][vcodec~='^(avc|h264)']+ba[acodec~='^(aac|mp4a)']/b[height<=1080]" \
        --merge-output-format mp4 \
        --write-info-json \
        --write-thumbnail \
        --no-write-playlist-metafiles \
        --embed-metadata \
        --embed-thumbnail \
        $SB_OPTS \
        -o "$DL/%(upload_date>%Y-%m-%d)s - %(title).180B.%(ext)s" \
        --restrict-filenames \
        --ignore-errors \
        "$url" </dev/null 2>&1 | tee -a "$LOG" | grep -E '\[download\] (Destination|100%)|ERROR|WARNING|SponsorBlock' || true

    NEW=$(find "$DL" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.mkv' -o -name '*.webm' \) | wc -l)
    log "  staged for upload: $NEW"
    if [ "$NEW" -gt 0 ]; then
        ssh "$REMOTE_HOST" "mkdir -p $REMOTE_BASE/$slug" 2>>"$LOG"
        rsync -av --remove-source-files "$DL/" "$REMOTE_HOST:$REMOTE_BASE/$slug/" 2>>"$LOG" | tail -10 >>"$LOG" || log "  rsync FAILED"
        log "  upload complete"
    fi
done 3< "$CONF"

# === Trigger Plex YouTube library refresh ===
PLEX_LIB_ID=$(ssh "$REMOTE_HOST" "curl -s -H 'Accept: application/json' -H 'X-Plex-Token: $PLEX_TOKEN' http://127.0.0.1:18725/library/sections" 2>/dev/null \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((x['key'] for x in d['MediaContainer']['Directory'] if x.get('title')=='YouTube'),''))" 2>/dev/null)
if [ -n "$PLEX_LIB_ID" ]; then
    ssh "$REMOTE_HOST" "curl -sf -H 'X-Plex-Token: $PLEX_TOKEN' 'http://127.0.0.1:18725/library/sections/$PLEX_LIB_ID/refresh' >/dev/null" 2>>"$LOG"
    log "Plex library $PLEX_LIB_ID refresh triggered"
fi

log "=== yt-sync run end ==="
