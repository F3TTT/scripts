#!/usr/bin/env python3
"""ruck-events-briefing (WSL) — weekly audio briefing on upcoming local ruck events.

Modeled on ../book-awards-briefing/book_awards_briefing.py: same local-WSL /
Task-Scheduler / edge-tts / rsync-to-seedbox / Audiobookshelf pattern, published
as its own podcast ("Ruck-Events") under the same seedbox podcasts library.

Unlike book-awards, there is NO headless Claude check — Sweatpals returns
structured JSON per-host, so events are fetched, filtered, and narrated
directly. Free to run.

Pipeline:
  1. For each configured Sweatpals host, fetch the profile JSON (via the
     Next.js data endpoint) and extract upcoming events.
  2. Filter by:
       - upcoming only (startsAt >= now)
       - within radius_mi of home_lat/home_lng (haversine)
       - not already reported (state.json fingerprint check)
  3. If nothing new: log and exit, no episode.
  4. If something new: build narration, synthesize with edge-tts, tag mp3,
     rsync to seedbox under Ruck-Events subfolder, trigger ABS scan.

State (~/.ruck-events-briefing/state.json) records fingerprints of events
already reported, so re-runs don't repeat them.

Fistbumps (GORUCK Community) is NOT yet integrated — their tRPC API is
private and undocumented. To add it, pull one authenticated tRPC request
URL from browser DevTools Network tab and drop it into fetch_fistbumps().

Config:  ~/.ruck-events-briefing/config.json (created with defaults on first run)
State:   ~/.ruck-events-briefing/state.json
Log:     ~/.ruck-events-briefing/log/<date>.log

Designed for Windows Task Scheduler (weekly):
    wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 /mnt/c/scripts/ruck-events-briefing/ruck_events_briefing.py'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Optional

# ----- paths -----

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".ruck-events-briefing")
CONFIG = os.path.join(ROOT, "config.json")
STATE = os.path.join(ROOT, "state.json")
LOG_DIR = os.path.join(ROOT, "log")
WORK = os.path.join(ROOT, "work")

# Reuse morning-briefing venv for edge-tts.
EDGE_TTS_BIN = os.path.join(HOME, ".morning-briefing", "venv", "bin", "edge-tts")

# Shared with book-awards-briefing: ssh_host, abs.*, remote_media_root. Those values
# live in ~/.book-awards-briefing/config.json and are auto-inherited on each run,
# so a password rotation in book-awards flows through here automatically.
BOOK_AWARDS_CONFIG = os.path.join(HOME, ".book-awards-briefing", "config.json")

DEFAULTS = {
    # Fill these into ~/.ruck-events-briefing/config.json before first run:
    #   home_lat/home_lng: your "home" point (rides are filtered by distance from here)
    #   home_label: what the TTS calls that point ("home", "downtown", etc.)
    #   sweatpals_hosts: list of Sweatpals host handles to poll each week
    "radius_mi": 15,
    "home_lat": 0.0,
    "home_lng": 0.0,
    "home_label": "home",
    "sweatpals_hosts": [],
    "tts_voice": "en-US-ChristopherNeural",
    "remote_subfolder": "Ruck-Events",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# ----- helpers -----

def log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(path, "a") as f:
        f.write(line + "\n")


def load_config() -> dict:
    """Load ruck-events config, then inherit ssh_host / remote_media_root / abs.*
    from book-awards config (same seedbox and ABS server for both projects).
    The user can override any inherited value by adding it to the ruck-events
    config file — an explicit key here wins over the book-awards value."""
    os.makedirs(ROOT, exist_ok=True)
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
        os.chmod(CONFIG, 0o600)
        log(f"wrote default config to {CONFIG}")
    with open(CONFIG) as f:
        cfg = json.load(f)
    # backfill defaults for any missing keys
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)

    # Inherit shared infra values from book-awards config if not overridden.
    inherited_keys = ("ssh_host", "remote_media_root", "abs")
    if os.path.exists(BOOK_AWARDS_CONFIG):
        with open(BOOK_AWARDS_CONFIG) as f:
            ba = json.load(f)
        for k in inherited_keys:
            if k not in cfg and k in ba:
                cfg[k] = ba[k]
    else:
        log(f"WARNING: {BOOK_AWARDS_CONFIG} not found — ssh_host and abs.* values must be set explicitly in {CONFIG}")

    # Validate the inherited/set values look real (not placeholders)
    missing = []
    for k in ("ssh_host", "remote_media_root"):
        if not cfg.get(k) or "example.com" in str(cfg[k]):
            missing.append(k)
    abs_cfg = cfg.get("abs") or {}
    for k in ("url", "username", "password", "library_id"):
        v = abs_cfg.get(k)
        if not v or "example.com" in str(v) or str(v).startswith("YOUR_"):
            missing.append(f"abs.{k}")
    if missing:
        log(f"config missing/placeholder values: {', '.join(missing)}")
    return cfg


def load_state() -> dict:
    if not os.path.exists(STATE):
        return {"reported": {}}
    with open(STATE) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE)


def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles."""
    R = 3958.7613  # earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def fingerprint(source: str, event_id: str) -> str:
    """Stable ID for state tracking."""
    h = hashlib.sha256(f"{source}:{event_id}".encode()).hexdigest()
    return h[:16]


# ----- step 1: Sweatpals fetch -----

_SP_BUILD_ID_CACHE: Optional[str] = None


def sweatpals_build_id() -> str:
    """Fetch current Next.js buildId. Cached per-process."""
    global _SP_BUILD_ID_CACHE
    if _SP_BUILD_ID_CACHE:
        return _SP_BUILD_ID_CACHE
    # Sweatpals /discover is a generic public Next.js page that reliably renders
    # the current buildId in its HTML (the homepage is a marketing landing that
    # doesn't; individual host pages do but hardcoding one leaks the handle).
    html = http_get("https://www.sweatpals.com/discover")
    m = re.search(r'"buildId":"([^"]+)"', html)
    if not m:
        raise RuntimeError("could not extract Sweatpals buildId — page structure may have changed")
    _SP_BUILD_ID_CACHE = m.group(1)
    return _SP_BUILD_ID_CACHE


def fetch_sweatpals_host(handle: str) -> list[dict]:
    """Return list of upcoming events for a Sweatpals host, or [] on any error."""
    try:
        bid = sweatpals_build_id()
        raw = http_get(f"https://www.sweatpals.com/_next/data/{bid}/host/{handle}.json")
        payload = json.loads(raw)
    except Exception as e:
        log(f"  sweatpals fetch failed for {handle}: {e}")
        return []

    queries = payload.get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    host_user = None
    events_pages = []
    for q in queries:
        qk = q.get("queryKey")
        if not isinstance(qk, list) or len(qk) < 1:
            continue
        if qk[0] == "user" and len(qk) > 1 and qk[1] == handle:
            host_user = q.get("state", {}).get("data") or {}
        elif qk[0] == "events":
            data = q.get("state", {}).get("data") or {}
            events_pages = data.get("pages") or []

    now = datetime.now(tz=timezone.utc)
    events = []
    for page in events_pages:
        if not isinstance(page, dict):
            continue
        for e in page.get("data") or []:
            if not isinstance(e, dict):
                continue
            event_id = e.get("id") or ""
            title = e.get("name") or e.get("title") or "(untitled)"
            starts_at = e.get("startDate") or e.get("startsAt") or e.get("dateTime")
            location_name = e.get("locationName") or e.get("addressName") or ""
            lat = e.get("addressLat") or e.get("lat")
            lng = e.get("addressLng") or e.get("lng")
            description = e.get("description") or ""

            if not starts_at:
                continue
            try:
                start_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if start_dt < now:
                continue

            events.append({
                "source": "sweatpals",
                "host": handle,
                "id": event_id,
                "title": title,
                "start_dt_utc": start_dt.astimezone(timezone.utc).isoformat(),
                "location_name": location_name,
                "lat": float(lat) if lat is not None else (host_user or {}).get("homeAddressLat"),
                "lng": float(lng) if lng is not None else (host_user or {}).get("homeAddressLng"),
                "url": f"https://www.sweatpals.com/event/{event_id}",
                "description": description,
            })

    # If lat/lng came from host_user (string), coerce
    for ev in events:
        for k in ("lat", "lng"):
            v = ev[k]
            if isinstance(v, str):
                try:
                    ev[k] = float(v)
                except Exception:
                    ev[k] = None
    return events


# ----- step 2: Fistbumps placeholder (private tRPC API — see docstring) -----

def fetch_fistbumps_group(group_id: str) -> list[dict]:
    """Placeholder. Fistbumps uses a private tRPC API that requires reverse
    engineering. When we have a tRPC request URL from browser DevTools,
    implement fetch here. For now: log + return []."""
    log(f"  fistbumps: NOT IMPLEMENTED (need tRPC URL to add group {group_id})")
    return []


# ----- step 3: filter -----

def filter_events(events: list[dict], home_lat: float, home_lng: float,
                  radius_mi: float, state: dict) -> list[dict]:
    reported = state.get("reported", {})
    out = []
    for e in events:
        # distance filter
        if e.get("lat") is None or e.get("lng") is None:
            log(f"  drop (no lat/lng): {e['title']}")
            continue
        d = haversine_mi(home_lat, home_lng, e["lat"], e["lng"])
        if d > radius_mi:
            log(f"  drop (dist {d:.1f}mi > {radius_mi}mi): {e['title']}")
            continue
        e["distance_mi"] = round(d, 1)

        # already-reported filter
        fp = fingerprint(e["source"], e["id"])
        if fp in reported:
            log(f"  drop (already reported): {e['title']}")
            continue
        e["_fingerprint"] = fp

        out.append(e)
    return out


# ----- step 4: narration + TTS + publish -----

def build_script(events: list[dict], home_label: str = "home") -> str:
    lines = ["Good morning. This is your Ruck Events briefing."]
    lines.append(f"Here's what's coming up in the next few weeks within {events[0].get('_radius_mi', 15)} miles.")
    for e in events:
        # parse date for narration; render in the machine's local timezone
        try:
            dt = datetime.fromisoformat(e["start_dt_utc"])
            local = dt.astimezone()  # system local tz
            date_phrase = local.strftime("%A, %B %-d at %-I:%M %p")
        except Exception:
            date_phrase = "(date unavailable)"
        loc = e.get("location_name") or "an unspecified location"
        lines.append(
            f'{e["host"]} has an event: "{e["title"]}". '
            f'{date_phrase}, at {loc}, about {e["distance_mi"]} miles from {home_label}.'
        )
        desc = (e.get("description") or "").strip()
        if desc:
            # first 2 sentences of description, capped
            short = re.split(r'(?<=[.!?])\s+', desc)[:2]
            snippet = " ".join(short)[:400]
            lines.append(snippet)
    lines.append("That's your Ruck Events briefing.")
    return "\n".join(lines)


def synthesize(text: str, voice: str, out_mp3: str) -> None:
    subprocess.run(
        [EDGE_TTS_BIN, "--voice", voice, "--text", text, "--write-media", out_mp3],
        check=True,
    )


def tag_mp3(mp3: str, title: str, tagged_out: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", mp3, "-c", "copy",
         "-metadata", f"title={title}",
         "-metadata", "artist=Ruck Events Briefing",
         "-id3v2_version", "3",
         tagged_out],
        check=True,
    )


def rsync_to_seedbox(local_path: str, ssh_host: str, remote_root: str, subfolder: str) -> None:
    subprocess.run(
        ["ssh", ssh_host, f"mkdir -p {remote_root}/{subfolder}"],
        check=True,
    )
    remote_path = f"{ssh_host}:{remote_root}/{subfolder}/{os.path.basename(local_path)}"
    subprocess.run(["rsync", "-a", local_path, remote_path], check=True)


def abs_login(cfg: dict) -> str:
    body = json.dumps({"username": cfg["username"], "password": cfg["password"]}).encode()
    req = urllib.request.Request(
        cfg["url"] + "/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    return (d.get("user") or {}).get("token") or d.get("token") or ""


def abs_scan(cfg: dict) -> None:
    try:
        token = abs_login(cfg)
        if not token:
            log("  ABS login: empty token")
            return
        req = urllib.request.Request(
            f"{cfg['url']}/api/libraries/{cfg['library_id']}/scan?force=1",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib.request.urlopen(req, timeout=15).read()
        log("  ABS: library scan triggered")
    except Exception as e:
        log(f"  ABS scan failed: {e}")


# ----- main -----

def _publish(cfg: dict, events: list[dict]) -> int:
    date_tag = datetime.now().strftime("%Y-%m-%d")
    for e in events:
        e["_radius_mi"] = cfg["radius_mi"]
    script_text = build_script(events, cfg.get("home_label", "home"))
    raw_mp3 = os.path.join(WORK, f"ruck-events-raw-{date_tag}.mp3")
    final_mp3 = os.path.join(WORK, f"ruck-events-{date_tag}.mp3")

    log("  synthesizing audio")
    synthesize(script_text, cfg["tts_voice"], raw_mp3)
    tag_mp3(raw_mp3, f"Ruck Events - {date_tag}", final_mp3)
    os.remove(raw_mp3)

    log("  rsync to seedbox")
    rsync_to_seedbox(final_mp3, cfg["ssh_host"], cfg["remote_media_root"], cfg["remote_subfolder"])
    os.remove(final_mp3)

    abs_scan(cfg["abs"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and filter, but skip TTS/rsync/ABS. Prints the narration script.")
    ap.add_argument("--force-report", action="store_true",
                    help="Ignore state's 'already reported' filter (re-emit events even if seen).")
    ap.add_argument("--print-events", action="store_true",
                    help="Print raw filtered events as JSON and exit (no narration).")
    args = ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    cfg = load_config()

    log("=== ruck-events-briefing run start ===")
    # ABS password only required when we'll actually publish (skipped in dry-run & print-events)
    if not (args.dry_run or args.print_events) and not cfg["abs"].get("password"):
        log("ABS password missing — fill in ~/.ruck-events-briefing/config.json or use --dry-run")
        return 1

    all_events: list[dict] = []
    for handle in cfg.get("sweatpals_hosts", []):
        log(f"  fetching Sweatpals: {handle}")
        found = fetch_sweatpals_host(handle)
        log(f"    {len(found)} upcoming event(s)")
        all_events.extend(found)

    state = load_state()
    if args.force_report:
        state_for_filter = {"reported": {}}
    else:
        state_for_filter = state

    filtered = filter_events(
        all_events,
        cfg["home_lat"],
        cfg["home_lng"],
        cfg["radius_mi"],
        state_for_filter,
    )

    log(f"  {len(filtered)} event(s) after filter")

    if args.print_events:
        print(json.dumps(filtered, indent=2, default=str))
        return 0

    if not filtered:
        log("  no new events in range this run — no episode")
        log("=== ruck-events-briefing run end (nothing new) ===")
        return 0

    if args.dry_run:
        for e in filtered:
            e["_radius_mi"] = cfg["radius_mi"]
        text = build_script(filtered, cfg.get("home_label", "home"))
        log("  --dry-run: skipping TTS/rsync/ABS. Script would be:")
        log(text)
        log("=== ruck-events-briefing run end (dry-run) ===")
        return 0

    rc = _publish(cfg, filtered)

    # mark events as reported
    for e in filtered:
        state.setdefault("reported", {})[e["_fingerprint"]] = {
            "first_seen": datetime.now(tz=timezone.utc).isoformat(),
            "title": e["title"],
            "start_dt_utc": e["start_dt_utc"],
            "host": e["host"],
            "source": e["source"],
        }
    save_state(state)

    log("=== ruck-events-briefing run end ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())
