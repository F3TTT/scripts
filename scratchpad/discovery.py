#!/usr/bin/env python3
"""Weekly TV discovery — queries TMDB for newly-released shows in the
user's lanes, applies blocklist filters, adds top picks to Sonarr in
pilot-only mode (so only S01E01 is monitored + grabbed).

Config:    ~/discovery/config.json  (TMDB key, Sonarr URL+key, blocklists)
State:     ~/discovery/state.json   (processed TMDB ids — never re-propose)
Log:       ~/discovery/log/<date>.log
Summary:   ~/discovery/this-week.md (human-readable, overwritten each run)
"""
import json, urllib.request, urllib.parse, os, sys, time, re
from datetime import datetime, timedelta, timezone
import seen_filter

ROOT = os.path.expanduser("~/discovery")
os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)
LOG_PATH = os.path.join(ROOT, "log", datetime.now(timezone.utc).strftime("%Y-%m-%d.log"))
STATE_PATH = os.path.join(ROOT, "state.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
SUMMARY_PATH = os.path.join(ROOT, "this-week.md")

def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def load_json(path, default):
    if not os.path.exists(path):
        return default
    return json.load(open(path))

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)

# ----- TMDB -----

TMDB = "https://api.themoviedb.org/3"

def tmdb_discover(api_key, genre_ids, since_iso, vote_min, page=1):
    qs = urllib.parse.urlencode({
        "api_key": api_key,
        "language": "en-US",
        "sort_by": "vote_average.desc",
        "vote_count.gte": vote_min,
        "first_air_date.gte": since_iso,
        "with_genres": ",".join(str(g) for g in genre_ids),
        # Excluded TMDB TV genres:
        #   10764 reality, 10762 kids, 10763 news, 10766 soap, 10767 talk,
        #   16 animation (user wants live-action by default)
        "without_genres": "10764,10762,10763,10766,10767,16",
        "with_origin_country": "US|GB|CA|AU|NZ|IE",
        "page": page,
    })
    req = urllib.request.urlopen(f"{TMDB}/discover/tv?{qs}", timeout=20)
    return json.loads(req.read())

def tmdb_credits(api_key, tmdb_id):
    qs = urllib.parse.urlencode({"api_key": api_key})
    try:
        req = urllib.request.urlopen(f"{TMDB}/tv/{tmdb_id}/credits?{qs}", timeout=15)
        return json.loads(req.read())
    except Exception as e:
        log(f"  credits lookup failed for {tmdb_id}: {e}")
        return {"cast": []}

def tmdb_external_ids(api_key, tmdb_id):
    qs = urllib.parse.urlencode({"api_key": api_key})
    try:
        req = urllib.request.urlopen(f"{TMDB}/tv/{tmdb_id}/external_ids?{qs}", timeout=15)
        return json.loads(req.read())
    except Exception as e:
        log(f"  external_ids failed for {tmdb_id}: {e}")
        return {}

def tmdb_details(api_key, tmdb_id):
    """Returns the /tv/{id} details — has `created_by` (creators), genres,
    networks, etc. Used to check creator blocklist."""
    qs = urllib.parse.urlencode({"api_key": api_key})
    try:
        req = urllib.request.urlopen(f"{TMDB}/tv/{tmdb_id}?{qs}", timeout=15)
        return json.loads(req.read())
    except Exception as e:
        log(f"  details failed for {tmdb_id}: {e}")
        return {}

# ----- Sonarr -----

def sonarr_get(cfg, path):
    url = f"{cfg['sonarr_url']}{path}{'&' if '?' in path else '?'}apikey={cfg['sonarr_key']}"
    return json.loads(urllib.request.urlopen(url, timeout=30).read())

def sonarr_post(cfg, path, body):
    url = f"{cfg['sonarr_url']}{path}?apikey={cfg['sonarr_key']}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def sonarr_put(cfg, path, body):
    url = f"{cfg['sonarr_url']}{path}?apikey={cfg['sonarr_key']}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="PUT")
    return urllib.request.urlopen(req, timeout=30).read()

def sonarr_lookup_tvdb(cfg, tvdb_id):
    qs = urllib.parse.urlencode({"term": f"tvdb:{tvdb_id}"})
    hits = sonarr_get(cfg, f"/series/lookup?{qs}")
    return next((h for h in hits if h.get("tvdbId") == tvdb_id), None)

def already_in_sonarr(cfg, tvdb_id):
    series = sonarr_get(cfg, "/series")
    return any(s.get("tvdbId") == tvdb_id for s in series)

def disk_used_gb(cfg):
    """Use the seedbox `quota` command — the underlying filesystem is shared
    so Sonarr's /diskspace reports the wrong total."""
    import subprocess
    try:
        out = subprocess.run(["quota", "-u"], capture_output=True, text=True, timeout=10).stdout
        # Output line like:
        #   /dev/sdb1   1234567   3812823040       0           ...
        # Numbers are in KB. We want the second column (used).
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith("/dev/"):
                used_kb = int(parts[1].rstrip("*"))
                return used_kb / (1024 ** 2)  # KB -> GB
    except Exception as e:
        log(f"  quota check failed: {e}")
    return 0

def add_with_pilot(cfg, show, dry_run=False):
    """Add to Sonarr with monitor=pilot. Triggers S01E01 search."""
    payload = {
        "tvdbId": show["tvdbId"],
        "title": show["title"],
        "titleSlug": show["titleSlug"],
        "year": show.get("year"),
        "images": show.get("images", []),
        "seasons": show.get("seasons", []),
        "qualityProfileId": cfg.get("quality_profile_id", 4),
        "rootFolderPath": cfg.get("root_folder", "/home/zuul6/media/TV Shows"),
        "monitored": True,
        "seasonFolder": True,
        "languageProfileId": 1,
        "addOptions": {
            "monitor": "pilot",
            "searchForMissingEpisodes": False,
        },
    }
    if dry_run:
        log(f"  DRY-RUN would add: {show['title']!r} (tvdb={show['tvdbId']})")
        return None
    data = sonarr_post(cfg, "/series", payload)
    sid = data.get("id")
    # The Sonarr `monitor: pilot` addOption unmonitors all seasons; we need
    # to flip S01 back on at the SEASON level for the pilot episode to be
    # searchable.
    full = sonarr_get(cfg, f"/series/{sid}")
    changed = False
    for season in full.get("seasons", []):
        if season["seasonNumber"] == 1 and not season.get("monitored"):
            season["monitored"] = True
            changed = True
    if not full.get("monitored"):
        full["monitored"] = True; changed = True
    if changed:
        sonarr_put(cfg, f"/series/{sid}", full)
    # Now narrow EPISODE-level: only the pilot stays monitored
    eps = sonarr_get(cfg, f"/episode?seriesId={sid}")
    s01 = sorted([e for e in eps if e.get("seasonNumber") == 1], key=lambda e: e.get("episodeNumber", 0))
    if s01:
        pilot = s01[0]
        to_unmon = [e["id"] for e in eps if e["id"] != pilot["id"] and e.get("monitored")]
        if to_unmon:
            sonarr_put(cfg, "/episode/monitor",
                       {"episodeIds": to_unmon, "monitored": False})
        if not pilot.get("monitored"):
            sonarr_put(cfg, "/episode/monitor",
                       {"episodeIds": [pilot["id"]], "monitored": True})
        # Trigger search for the pilot only
        sonarr_post(cfg, "/command",
                    {"name": "EpisodeSearch", "episodeIds": [pilot["id"]]})
        log(f"  added id={sid}, S01E{pilot.get('episodeNumber'):02d} monitored + searched")
    return sid

# ----- main -----

BLOCKLIST_DEFAULT = {
    "title_keywords": [r"\bbake\s*off\b", r"\bcooking\b", r"\brestaurant\b",
                       r"\bpawn\b", r"\bstorage wars\b"],
    "overview_keywords": [r"\bcooking competition\b", r"\bdating show\b",
                          r"\bweight[-\s]?loss\b"],
    "blocked_lead_actors": ["Paul Giamatti"],
}

LANES_DEFAULT = {
    # TMDB TV genre ids: 10765 Sci-Fi & Fantasy, 10759 Action & Adventure,
    # 18 Drama, 35 Comedy, 9648 Mystery
    "sci-fi":    [10765],
    "action":    [10759],
    "dramedy":   [18, 35],
    "mystery":   [9648],
}

def main():
    dry = "--dry-run" in sys.argv

    if not os.path.exists(CONFIG_PATH):
        # First run — bootstrap a stub config
        default = {
            "tmdb_key": "REPLACE_ME",
            "sonarr_url": "http://127.0.0.1:18726/sonarr/api/v3",
            "sonarr_key": "REPLACE_ME",
            "quality_profile_id": 4,
            "root_folder": "/home/zuul6/media/TV Shows",
            "lanes": LANES_DEFAULT,
            "blocklist": BLOCKLIST_DEFAULT,
            "since_days": 180,        # look back this far for "new"
            "candidates_per_lane": 6, # query depth per lane
            "max_adds_per_run": 4,    # cap weekly proposals
            "disk_warn_gb": 3500,     # pause if used > this
        }
        save_json(CONFIG_PATH, default)
        print(f"wrote stub {CONFIG_PATH} — fill in TMDB + Sonarr keys")
        return

    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"processed_tmdb_ids": [], "history": []})
    seen = seen_filter.load_seen()
    log(f"=== discovery run start (dry={dry}) ===")
    if seen is None:
        log("  WARNING: seen.json missing — already-watched filter DISABLED this run")
    else:
        log(f"  seen-filter: {len(seen['tv_titles'])} watched shows loaded")

    # Disk safety
    used = disk_used_gb(cfg)
    log(f"disk used: {used:.0f} GB")
    if cfg.get("disk_warn_gb") and used > cfg["disk_warn_gb"]:
        log(f"  >{cfg['disk_warn_gb']} GB used; pausing adds this run")
        return

    since = (datetime.now(timezone.utc) - timedelta(days=cfg.get("since_days", 180))).strftime("%Y-%m-%d")

    # Gather candidates per lane
    seen_tmdb = set(state["processed_tmdb_ids"])
    candidates = []   # (lane, tmdb_obj)
    seen_in_this_run = set()
    vote_min = cfg.get("vote_count_min", 500)
    for lane, genre_ids in cfg["lanes"].items():
        log(f"lane {lane}: querying TMDB genres={genre_ids} since={since} vote_min={vote_min}")
        try:
            page = tmdb_discover(cfg["tmdb_key"], genre_ids, since, vote_min, page=1)
        except Exception as e:
            log(f"  TMDB query failed: {e}")
            continue
        for r in (page.get("results") or [])[:cfg.get("candidates_per_lane", 6)]:
            if r["id"] in seen_tmdb or r["id"] in seen_in_this_run:
                continue
            seen_in_this_run.add(r["id"])
            candidates.append((lane, r))

    log(f"{len(candidates)} raw candidates")

    # Compile blocklist patterns
    bl = cfg.get("blocklist", {})
    title_pats = [re.compile(p, re.I) for p in bl.get("title_keywords", [])]
    overview_pats = [re.compile(p, re.I) for p in bl.get("overview_keywords", [])]
    blocked_actors = set(bl.get("blocked_lead_actors", []))
    blocked_creators = set(bl.get("blocked_creators", []))

    accepted = []
    for lane, c in candidates:
        title = c.get("name") or ""
        overview = c.get("overview") or ""
        watched = seen_filter.seen_tv(seen, title)
        if watched:
            log(f"  block (already-watched:{watched}): {title!r}")
            continue
        if any(p.search(title) for p in title_pats):
            log(f"  block-title: {title!r}")
            continue
        if any(p.search(overview) for p in overview_pats):
            log(f"  block-overview: {title!r}")
            continue
        # Creator check (TMDB created_by + crew "Writer"/"Novel" credits — catches
        # adaptations like Stephen King novels).
        details = tmdb_details(cfg["tmdb_key"], c["id"])
        creators = {p.get("name") for p in (details.get("created_by") or []) if p.get("name")}
        # Some "based on a novel" credits show up in /credits crew as "Novel"
        creds = tmdb_credits(cfg["tmdb_key"], c["id"])
        for member in (creds.get("crew") or []):
            if (member.get("job") or "").lower() in ("novel", "author", "based on", "story") \
               or (member.get("department") or "").lower() == "writing":
                if member.get("name"):
                    creators.add(member.get("name"))
        if creators & blocked_creators:
            log(f"  block-creator: {title!r} creators_seen={creators & blocked_creators}")
            continue
        # Lead-actor check (top 3 cast)
        leads = [m.get("name") for m in (creds.get("cast") or [])[:3]]
        if any(a in leads for a in blocked_actors):
            log(f"  block-actor: {title!r} leads={leads}")
            continue
        # TVDB mapping (Sonarr uses TVDB ids)
        ext = tmdb_external_ids(cfg["tmdb_key"], c["id"])
        tvdb_id = ext.get("tvdb_id")
        if not tvdb_id:
            log(f"  no TVDB id for {title!r}; skipping")
            continue
        watched = seen_filter.seen_tv(seen, title, tvdb_id)
        if watched == "tvdb":
            log(f"  block (already-watched:tvdb): {title!r}")
            continue
        # Already in Sonarr?
        try:
            if already_in_sonarr(cfg, tvdb_id):
                log(f"  already in library: {title!r}")
                seen_tmdb.add(c["id"])
                continue
        except Exception as e:
            log(f"  sonarr check failed for {title!r}: {e}")
            continue
        # Look up Sonarr-side metadata via TVDB
        sonarr_show = sonarr_lookup_tvdb(cfg, tvdb_id)
        if not sonarr_show:
            log(f"  Sonarr couldn't resolve tvdb={tvdb_id} ({title!r})")
            continue
        accepted.append({
            "lane": lane,
            "title": title,
            "tmdb_id": c["id"],
            "tvdb_id": tvdb_id,
            "year": c.get("first_air_date", "")[:4],
            "rating": c.get("vote_average"),
            "votes": c.get("vote_count"),
            "overview": overview[:280],
            "sonarr_show": sonarr_show,
        })

    log(f"{len(accepted)} candidates passed filters")

    # Take top N by lane diversity then rating
    accepted.sort(key=lambda x: -(x.get("rating") or 0))
    cap = cfg.get("max_adds_per_run", 4)
    picks, picked_lanes = [], set()
    # First pass: 1 per lane
    for a in accepted:
        if len(picks) >= cap:
            break
        if a["lane"] in picked_lanes:
            continue
        picks.append(a); picked_lanes.add(a["lane"])
    # Fill remainder by rating
    for a in accepted:
        if len(picks) >= cap:
            break
        if a not in picks:
            picks.append(a)

    log(f"picks: {len(picks)}")
    summary = ["# Discovery — this week's picks", ""]
    for p in picks:
        log(f"PICK ({p['lane']}): {p['title']} ({p['year']}) rating={p['rating']}/{p['votes']}")
        sid = add_with_pilot(cfg, p["sonarr_show"], dry_run=dry)
        state["processed_tmdb_ids"].append(p["tmdb_id"])
        state["history"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "lane": p["lane"],
            "title": p["title"],
            "year": p["year"],
            "tmdb": p["tmdb_id"],
            "tvdb": p["tvdb_id"],
            "rating": p["rating"],
            "sonarr_id": sid,
            "dry_run": dry,
        })
        summary.append(f"- **{p['title']} ({p['year']})** — {p['lane']}, rating {p['rating']}/10 ({p['votes']} votes)")
        summary.append(f"  - {p['overview']}")
        summary.append("")

    if picks and not dry:
        save_json(STATE_PATH, state)
        with open(SUMMARY_PATH, "w") as f:
            f.write("\n".join(summary))
        log(f"summary written: {SUMMARY_PATH}")
    log("=== discovery run end ===")

if __name__ == "__main__":
    main()
