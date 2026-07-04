#!/usr/bin/env python3
"""Trakt-based discovery — pulls trending / anticipated / watched-weekly
from Trakt for both TV and movies, applies the user's blocklist, adds
top picks to Sonarr (TV pilots) and Radarr (movies). Designed to run
right after the TMDB discovery so this round de-dupes against TMDB's
just-added picks.

Config: ~/discovery/config.json — adds 'trakt_client_id' field.
Log:    ~/discovery/log/trakt-<date>.log
Summary: ~/discovery/this-week-trakt.md
State:  ~/discovery/state.json (shared with TMDB discovery — same
        processed_tmdb_ids set; Trakt IDs added under processed_trakt_ids)
"""
import json, urllib.request, urllib.parse, os, sys, time, re
from datetime import datetime, timezone
import seen_filter

ROOT = os.path.expanduser("~/discovery")
os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)
LOG_PATH = os.path.join(ROOT, "log", "trakt-" + datetime.now(timezone.utc).strftime("%Y-%m-%d.log"))
STATE_PATH = os.path.join(ROOT, "state.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
SUMMARY_PATH = os.path.join(ROOT, "this-week-trakt.md")

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

# ----- Trakt -----

TRAKT = "https://api.trakt.tv"
def trakt_get(path, client_id, limit=20):
    qs = urllib.parse.urlencode({"limit": limit})
    req = urllib.request.Request(
        f"{TRAKT}{path}?{qs}",
        headers={
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
            "User-Agent": "rollins-archive-sync/discovery-trakt/1.0",
            "Accept": "application/json",
        })
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def trakt_extended(path, client_id, item_id):
    """Fetch extended details for a single item — overview, genres, etc."""
    qs = urllib.parse.urlencode({"extended": "full"})
    req = urllib.request.Request(
        f"{TRAKT}{path}/{item_id}?{qs}",
        headers={
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
            "User-Agent": "rollins-archive-sync/discovery-trakt/1.0",
            "Accept": "application/json",
        })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception:
        return {}

# ----- TMDB (for creator/cast verification — reuse user's TMDB key) -----

TMDB = "https://api.themoviedb.org/3"
def tmdb_details(api_key, kind, tmdb_id):
    """kind = 'tv' or 'movie'."""
    if not tmdb_id: return {}
    qs = urllib.parse.urlencode({"api_key": api_key, "append_to_response": "credits"})
    try:
        return json.loads(urllib.request.urlopen(
            f"{TMDB}/{kind}/{tmdb_id}?{qs}", timeout=15).read())
    except Exception:
        return {}

# ----- Sonarr / Radarr helpers -----

def s_get(cfg, p):
    return json.loads(urllib.request.urlopen(
        f"{cfg['sonarr_url']}{p}{'&' if '?' in p else '?'}apikey={cfg['sonarr_key']}",
        timeout=30).read())
def s_post(cfg, p, b):
    req = urllib.request.Request(
        f"{cfg['sonarr_url']}{p}?apikey={cfg['sonarr_key']}",
        data=json.dumps(b).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())
def s_put(cfg, p, b):
    req = urllib.request.Request(
        f"{cfg['sonarr_url']}{p}?apikey={cfg['sonarr_key']}",
        data=json.dumps(b).encode(),
        headers={"Content-Type":"application/json"}, method="PUT")
    urllib.request.urlopen(req, timeout=30).read()

def r_get(cfg, p):
    return json.loads(urllib.request.urlopen(
        f"{cfg['radarr_url']}{p}{'&' if '?' in p else '?'}apikey={cfg['radarr_key']}",
        timeout=30).read())
def r_post(cfg, p, b):
    req = urllib.request.Request(
        f"{cfg['radarr_url']}{p}?apikey={cfg['radarr_key']}",
        data=json.dumps(b).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# ----- Add helpers (pilot mode TV / monitored+search movies) -----

def add_show_pilot(cfg, show_lookup, dry):
    if dry:
        log(f"  DRY-RUN add TV pilot: {show_lookup['title']!r}")
        return None
    payload = {
        "tvdbId": show_lookup["tvdbId"],
        "title": show_lookup["title"],
        "titleSlug": show_lookup["titleSlug"],
        "year": show_lookup.get("year"),
        "images": show_lookup.get("images", []),
        "seasons": show_lookup.get("seasons", []),
        "qualityProfileId": cfg.get("quality_profile_id", 4),
        "rootFolderPath": cfg.get("root_folder", "/home/zuul6/media/TV Shows"),
        "monitored": True,
        "seasonFolder": True,
        "languageProfileId": 1,
        "addOptions": {"monitor": "pilot", "searchForMissingEpisodes": False},
    }
    data = s_post(cfg, "/series", payload)
    sid = data.get("id")
    # Force-narrow to S01E01 only (Sonarr addOption 'pilot' unmonitors everything)
    full = s_get(cfg, f"/series/{sid}")
    if not full.get("monitored"):
        full["monitored"] = True
    for season in full.get("seasons", []):
        if season["seasonNumber"] == 1 and not season.get("monitored"):
            season["monitored"] = True
    s_put(cfg, f"/series/{sid}", full)
    eps = s_get(cfg, f"/episode?seriesId={sid}")
    s01 = sorted([e for e in eps if e.get("seasonNumber") == 1], key=lambda e: e.get("episodeNumber",0))
    if s01:
        pilot = s01[0]
        to_unmon = [e["id"] for e in eps if e["id"] != pilot["id"] and e.get("monitored")]
        if to_unmon:
            s_put(cfg, "/episode/monitor", {"episodeIds": to_unmon, "monitored": False})
        if not pilot.get("monitored"):
            s_put(cfg, "/episode/monitor", {"episodeIds": [pilot["id"]], "monitored": True})
        s_post(cfg, "/command", {"name": "EpisodeSearch", "episodeIds": [pilot["id"]]})
        log(f"  added TV pilot id={sid} S01E{pilot.get('episodeNumber'):02d}")
    return sid

def add_movie(cfg, lookup, dry):
    if dry:
        log(f"  DRY-RUN add movie: {lookup['title']!r}")
        return None
    payload = {
        "tmdbId": lookup["tmdbId"],
        "title": lookup["title"],
        "titleSlug": lookup["titleSlug"],
        "year": lookup.get("year"),
        "images": lookup.get("images", []),
        "qualityProfileId": cfg.get("quality_profile_id", 4),
        "rootFolderPath": cfg.get("movie_root_folder", "/home/zuul6/media/Movies"),
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": True, "monitor": "movieOnly"},
    }
    try:
        data = r_post(cfg, "/movie", payload)
        log(f"  added movie id={data.get('id')}")
        return data.get("id")
    except urllib.error.HTTPError as e:
        log(f"  add movie FAIL: {e.code} {e.read().decode()[:200]}")
        return None

# ----- disk safety -----

def disk_used_gb():
    import subprocess
    try:
        out = subprocess.run(["quota","-u"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith("/dev/"):
                return int(parts[1].rstrip("*")) / (1024**2)
    except Exception:
        return 0

# ----- main -----

def main():
    dry = "--dry-run" in sys.argv
    cfg = load_json(CONFIG_PATH, {})
    if not cfg.get("trakt_client_id"):
        print("missing trakt_client_id in config.json"); return
    if not cfg.get("radarr_url"):
        cfg["radarr_url"] = "http://127.0.0.1:18727/radarr/api/v3"
    if not cfg.get("radarr_key"):
        print("missing radarr_key in config.json"); return

    state = load_json(STATE_PATH, {"processed_tmdb_ids": [], "processed_trakt_ids": [], "history": []})
    state.setdefault("processed_trakt_ids", [])
    seen = seen_filter.load_seen()
    if seen is None:
        log("  WARNING: seen.json missing — already-watched filter DISABLED this run")
    else:
        log(f"  seen-filter: {len(seen['tv_titles'])} watched shows, {len(seen['movie_titles'])} watched movies")

    log(f"=== Trakt discovery run start (dry={dry}) ===")
    used = disk_used_gb()
    log(f"disk used: {used:.0f} GB")
    if cfg.get("disk_warn_gb") and used > cfg["disk_warn_gb"]:
        log(f"  > {cfg['disk_warn_gb']} GB; pausing adds"); return

    # Build existing-library indexes (so we skip dupes)
    existing_tvdbs = {s.get("tvdbId") for s in s_get(cfg, "/series")}
    existing_tmdbs_radarr = {m.get("tmdbId") for m in r_get(cfg, "/movie")}

    # ----- collect candidates from multiple Trakt endpoints -----
    show_candidates = []   # list of (trakt_show_dict, source_label)
    movie_candidates = []

    show_endpoints = [
        ("/shows/trending", "trending"),
        ("/shows/anticipated", "anticipated"),
        ("/shows/watched/weekly", "watched-weekly"),
    ]
    for path, label in show_endpoints:
        try:
            results = trakt_get(path, cfg["trakt_client_id"], limit=15)
        except Exception as e:
            log(f"  trakt {path} FAILED: {e}")
            continue
        for r in results:
            show = r.get("show") or r
            if show:
                show_candidates.append((show, label))
        log(f"  trakt {label} shows: {len(results)}")

    movie_endpoints = [
        ("/movies/trending", "trending"),
        ("/movies/anticipated", "anticipated"),
        ("/movies/watched/weekly", "watched-weekly"),
    ]
    for path, label in movie_endpoints:
        try:
            results = trakt_get(path, cfg["trakt_client_id"], limit=15)
        except Exception as e:
            log(f"  trakt {path} FAILED: {e}")
            continue
        for r in results:
            mv = r.get("movie") or r
            if mv:
                movie_candidates.append((mv, label))
        log(f"  trakt {label} movies: {len(results)}")

    # ----- dedupe by trakt id (multiple endpoints can return same item) -----
    seen_trakt = set(state["processed_trakt_ids"])
    show_uniq = []; seen_in_run = set()
    for show, label in show_candidates:
        tid = (show.get("ids") or {}).get("trakt")
        if not tid or tid in seen_trakt or tid in seen_in_run: continue
        seen_in_run.add(tid)
        show_uniq.append((show, label))
    movie_uniq = []; seen_mv = set()
    for mv, label in movie_candidates:
        tid = (mv.get("ids") or {}).get("trakt")
        if not tid or tid in seen_trakt or tid in seen_mv: continue
        seen_mv.add(tid)
        movie_uniq.append((mv, label))
    log(f"unique candidates: shows={len(show_uniq)}  movies={len(movie_uniq)}")

    # ----- apply blocklist + library check + filters -----
    bl = cfg.get("blocklist", {})
    title_pats = [re.compile(p, re.I) for p in bl.get("title_keywords", [])]
    overview_pats = [re.compile(p, re.I) for p in bl.get("overview_keywords", [])]
    blocked_actors = set(bl.get("blocked_lead_actors", []))
    blocked_creators = set(bl.get("blocked_creators", []))
    motorsport_pats = [
        re.compile(r"\bformula\s*1\b", re.I),
        re.compile(r"\bf1\b", re.I),
        re.compile(r"\bgrand prix\b", re.I),
    ]

    def passes_filters(item, kind):
        title = item.get("title") or ""
        overview = item.get("overview") or ""
        # Animation TV — exclude per user prefs (per tv.md no kids/animation)
        # Genre check via Trakt 'genres' field
        genres = [(g or "").lower() for g in (item.get("genres") or [])]
        # Animation is NOT a blanket block — adult/absurdist works (Vox Machina,
        # The Tick are loved). Block only kid-style markers; the user's
        # Rick-and-Morty problem is toxicity not zaniness, which is hard to
        # detect from synopsis — leave that for manual triage.
        if kind == "tv" and "animation" in genres:
            tl = title.lower() + " " + overview.lower()
            kid_markers = ("family-friendly", "preschool", "toddler",
                           "for the whole family", "saturday morning")
            if any(k in tl for k in kid_markers):
                return False, "kid-animation"
        if kind == "tv" and "reality" in genres:
            return False, "reality TV"
        # Standard text filters
        for p in title_pats:
            if p.search(title): return False, f"title:{p.pattern}"
        for p in overview_pats:
            if p.search(overview): return False, f"overview:{p.pattern}"
        # Motorsport-as-spectacle
        for p in motorsport_pats:
            if p.search(title) or p.search(overview):
                return False, f"motorsport:{p.pattern}"
        return True, None

    def has_blocked_creator_or_actor(tmdb_id, kind):
        d = tmdb_details(cfg["tmdb_key"], kind, tmdb_id)
        creators = {p.get("name") for p in (d.get("created_by") or []) if p.get("name")}
        creds = d.get("credits") or {}
        for member in (creds.get("crew") or []):
            if (member.get("job") or "").lower() in ("novel","author","based on","story"):
                if member.get("name"): creators.add(member["name"])
        leads = [m.get("name") for m in (creds.get("cast") or [])[:3]]
        if creators & blocked_creators:
            return f"creator:{creators & blocked_creators}"
        if any(a in leads for a in blocked_actors):
            return f"actor:{[a for a in leads if a in blocked_actors]}"
        return None

    # ----- TV process -----
    tv_accepted = []
    for show, label in show_uniq:
        ids = show.get("ids") or {}
        tvdb_id = ids.get("tvdb"); tmdb_id = ids.get("tmdb")
        trakt_slug = ids.get("slug")
        title = show.get("title") or "?"
        if not tvdb_id:
            log(f"  skip (no tvdb): {title!r}")
            continue
        if tvdb_id in existing_tvdbs:
            seen_trakt.add(ids.get("trakt"))
            continue
        watched = seen_filter.seen_tv(seen, title, tvdb_id)
        if watched:
            log(f"  block (already-watched:{watched}): {title!r}")
            seen_trakt.add(ids.get("trakt"))
            continue
        # Fetch extended details (overview, genres) — required for filter
        if trakt_slug:
            ext = trakt_extended("/shows", cfg["trakt_client_id"], trakt_slug)
            show = {**show, **{k: v for k, v in ext.items() if v}}
        ok, why = passes_filters(show, "tv")
        if not ok:
            log(f"  block ({why}): {title!r}")
            continue
        if tmdb_id:
            blocker = has_blocked_creator_or_actor(tmdb_id, "tv")
            if blocker:
                log(f"  block ({blocker}): {title!r}")
                continue
        # Verify Sonarr can resolve this tvdbId
        try:
            sonarr_show = s_get(cfg, f"/series/lookup?term=tvdb:{tvdb_id}")
        except Exception as e:
            log(f"  sonarr lookup failed for {title!r}: {e}"); continue
        match = next((x for x in sonarr_show if x.get("tvdbId") == tvdb_id), None)
        if not match:
            log(f"  sonarr couldn't resolve tvdb={tvdb_id} ({title!r})"); continue
        tv_accepted.append({
            "trakt_id": ids.get("trakt"),
            "tvdb_id": tvdb_id,
            "tmdb_id": tmdb_id,
            "title": title,
            "year": show.get("year"),
            "overview": (show.get("overview") or "")[:280],
            "source": label,
            "watchers": show.get("watchers", 0),
            "rating": show.get("rating", 0),
            "sonarr_show": match,
        })

    # ----- Movie process -----
    movie_accepted = []
    for mv, label in movie_uniq:
        ids = mv.get("ids") or {}
        tmdb_id = ids.get("tmdb")
        slug = ids.get("slug")
        title = mv.get("title") or "?"
        if not tmdb_id:
            log(f"  skip (no tmdb): {title!r}"); continue
        if tmdb_id in existing_tmdbs_radarr:
            seen_trakt.add(ids.get("trakt"))
            continue
        watched = seen_filter.seen_movie(seen, title, tmdb_id)
        if watched:
            log(f"  block (already-watched:{watched}): {title!r}")
            seen_trakt.add(ids.get("trakt"))
            continue
        if slug:
            ext = trakt_extended("/movies", cfg["trakt_client_id"], slug)
            mv = {**mv, **{k: v for k, v in ext.items() if v}}
        ok, why = passes_filters(mv, "movie")
        if not ok:
            log(f"  block ({why}): {title!r}"); continue
        blocker = has_blocked_creator_or_actor(tmdb_id, "movie")
        if blocker:
            log(f"  block ({blocker}): {title!r}"); continue
        # Verify Radarr can resolve this tmdbId
        try:
            qs = urllib.parse.urlencode({"tmdbId": tmdb_id})
            mlook = r_get(cfg, f"/movie/lookup/tmdb?{qs}")
        except Exception as e:
            log(f"  radarr lookup failed for {title!r}: {e}"); continue
        if not mlook or not isinstance(mlook, dict):
            log(f"  radarr couldn't resolve tmdb={tmdb_id} ({title!r})"); continue
        movie_accepted.append({
            "trakt_id": ids.get("trakt"),
            "tmdb_id": tmdb_id,
            "title": title,
            "year": mv.get("year"),
            "overview": (mv.get("overview") or "")[:280],
            "source": label,
            "watchers": mv.get("watchers", 0),
            "rating": mv.get("rating", 0),
            "radarr_lookup": mlook,
        })

    log(f"after filters: shows={len(tv_accepted)}  movies={len(movie_accepted)}")

    # ----- pick caps -----
    max_tv = cfg.get("trakt_max_tv_per_run", 4)
    max_movies = cfg.get("trakt_max_movies_per_run", 3)

    # Sort by source priority (trending first), then by watchers
    src_rank = {"trending": 0, "watched-weekly": 1, "anticipated": 2}
    tv_accepted.sort(key=lambda x: (src_rank.get(x["source"], 9), -x.get("watchers", 0)))
    movie_accepted.sort(key=lambda x: (src_rank.get(x["source"], 9), -x.get("watchers", 0)))

    tv_picks = tv_accepted[:max_tv]
    movie_picks = movie_accepted[:max_movies]

    log(f"PICKS: tv={len(tv_picks)} movies={len(movie_picks)}")

    summary = ["# Discovery (Trakt) — this week's picks", ""]
    for p in tv_picks:
        log(f"TV PICK [{p['source']}]: {p['title']} ({p['year']})  watchers={p.get('watchers')}")
        sid = add_show_pilot(cfg, p["sonarr_show"], dry)
        state["processed_trakt_ids"].append(p["trakt_id"])
        state["history"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "src": "trakt",
            "kind": "tv",
            "source": p["source"],
            "title": p["title"], "year": p["year"],
            "trakt": p["trakt_id"], "tvdb": p["tvdb_id"], "tmdb": p["tmdb_id"],
            "sonarr_id": sid, "dry_run": dry,
        })
        summary.append(f"- **{p['title']} ({p['year']})** — TV pilot, Trakt {p['source']}, {p.get('watchers',0)} active watchers")
        summary.append(f"  - {p['overview']}")
        summary.append("")
    for p in movie_picks:
        log(f"MOVIE PICK [{p['source']}]: {p['title']} ({p['year']})  watchers={p.get('watchers')}")
        mid = add_movie(cfg, p["radarr_lookup"], dry)
        state["processed_trakt_ids"].append(p["trakt_id"])
        state["history"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "src": "trakt",
            "kind": "movie",
            "source": p["source"],
            "title": p["title"], "year": p["year"],
            "trakt": p["trakt_id"], "tmdb": p["tmdb_id"],
            "radarr_id": mid, "dry_run": dry,
        })
        summary.append(f"- **{p['title']} ({p['year']})** — Movie, Trakt {p['source']}, {p.get('watchers',0)} active watchers")
        summary.append(f"  - {p['overview']}")
        summary.append("")

    if (tv_picks or movie_picks) and not dry:
        save_json(STATE_PATH, state)
        with open(SUMMARY_PATH, "w") as f: f.write("\n".join(summary))
        log(f"summary written: {SUMMARY_PATH}")
    log("=== Trakt discovery run end ===")

if __name__ == "__main__":
    main()
