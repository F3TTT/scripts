#!/bin/bash
# yt-backfill — grab ONE older video per channel, walking backwards through
# the playlist (newest=position 1). State persisted per channel so each
# hourly run picks up where the last left off.
#
# Uses same config + same archive + same rsync target as sync.sh.
# Designed to run hourly via Task Scheduler at a low rate that looks like
# a regular human viewer to YouTube.
#
# State: ~/yt-sync/backfill_state/<slug>.pos
#   Holds the next playlist position to fetch (1-indexed).
#   When a position returns no video (channel exhausted), the file is left
#   at the final value and subsequent runs no-op.

set -u
YT="$HOME/.local/bin/yt-dlp"
ROOT="$HOME/yt-sync"
DOWNLOADS="$ROOT/downloads"
ARCHIVES="$ROOT/archive"
STATE="$ROOT/backfill_state"
LOGS="$ROOT/log"
CONF="$ROOT/channels.conf"
SECRETS="$ROOT/config.sh"

# Load REMOTE_HOST, REMOTE_BASE, PLEX_TOKEN from ~/yt-sync/config.sh (shared with yt-sync.sh).
if [ ! -f "$SECRETS" ]; then
    echo "ERROR: $SECRETS not found. Create it with REMOTE_HOST, REMOTE_BASE, PLEX_TOKEN." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$SECRETS"
: "${REMOTE_HOST:?REMOTE_HOST must be set in $SECRETS}"
: "${REMOTE_BASE:?REMOTE_BASE must be set in $SECRETS}"
: "${PLEX_TOKEN:?PLEX_TOKEN must be set in $SECRETS}"

# Where to start backfilling FROM if no state yet. Should match sync.sh LIMIT
# so we don't re-attempt videos the daily sync already covers.
INITIAL_POS=6

mkdir -p "$DOWNLOADS" "$ARCHIVES" "$STATE" "$LOGS"
LOG="$LOGS/$(date +%Y-%m-%d).log"
log() { echo "[$(date +%H:%M:%S)] backfill: $*" | tee -a "$LOG"; }

[ -f "$CONF" ] || { log "ERROR: $CONF missing"; exit 1; }

# Optional SponsorBlock (same as sync.sh — best-effort)
SB_OPTS=""
if curl -sf --max-time 5 -o /dev/null https://sponsor.ajay.app/api/status; then
    SB_OPTS="--sponsorblock-remove sponsor,selfpromo,interaction"
fi

# Read CONF on FD 3 so yt-dlp's stdin can't consume conf lines (see
# yt-sync.sh comment for the failure mode).
while IFS='|' read -r -u 3 slug url; do
    [[ -z "${slug// /}" || "${slug:0:1}" == "#" ]] && continue
    slug="$(echo "$slug" | xargs)"
    url="$(echo "$url" | xargs)"
    [ -z "$url" ] && continue

    POSFILE="$STATE/$slug.pos"
    POS=$INITIAL_POS
    [ -f "$POSFILE" ] && POS=$(cat "$POSFILE")
    log "$slug @ position $POS"

    DL="$DOWNLOADS/$slug"
    AR="$ARCHIVES/$slug.txt"
    mkdir -p "$DL"
    touch "$AR"

    # Try to fetch the video at this position. yt-dlp returns success even
    # when the position is past the end (just no output), so we check whether
    # a file actually landed.
    BEFORE=$(find "$DL" -maxdepth 1 -type f -name '*.mp4' | wc -l)
    "$YT" \
        --download-archive "$AR" \
        --no-overwrites \
        --playlist-items "$POS" \
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
        "$url" </dev/null 2>&1 | tee -a "$LOG" | grep -E '\[download\] (Destination|100%)|ERROR' || true

    AFTER=$(find "$DL" -maxdepth 1 -type f -name '*.mp4' | wc -l)
    GOT=$((AFTER - BEFORE))
    log "  position $POS: grabbed $GOT video(s)"

    # Always advance — even if archive-skipped (we don't need to re-try it)
    # or end-of-channel (further increments will continue to be no-ops)
    echo $((POS + 1)) > "$POSFILE"

    # Upload anything that landed
    if [ "$AFTER" -gt 0 ]; then
        ssh "$REMOTE_HOST" "mkdir -p $REMOTE_BASE/$slug" 2>>"$LOG"
        rsync -av --remove-source-files "$DL/" "$REMOTE_HOST:$REMOTE_BASE/$slug/" 2>>"$LOG" | tail -10 >>"$LOG" || log "  rsync FAILED"
        log "  upload complete"
    fi
done 3< "$CONF"

# Plex refresh if anything moved
PLEX_LIB_ID=$(ssh "$REMOTE_HOST" "curl -s -H 'Accept: application/json' -H 'X-Plex-Token: $PLEX_TOKEN' http://127.0.0.1:18725/library/sections" 2>/dev/null \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(next((x['key'] for x in d['MediaContainer']['Directory'] if x.get('title')=='YouTube'),''))" 2>/dev/null)
if [ -n "$PLEX_LIB_ID" ]; then
    ssh "$REMOTE_HOST" "curl -sf -H 'X-Plex-Token: $PLEX_TOKEN' 'http://127.0.0.1:18725/library/sections/$PLEX_LIB_ID/refresh' >/dev/null" 2>>"$LOG"
fi
