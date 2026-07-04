#!/usr/bin/env python3
"""Build ~/discovery/seen.json — the set of things the user has ALREADY
watched, so the discovery pipelines (discovery.py / discovery-trakt.py) can
skip re-adding them.

Primary source: **Plex watch history** (persists even after the media is
deleted from Sonarr/Radarr/Plex — this is how KAOS, watched then deleted,
still gets recognized). We key on normalized TITLE, because deleted media
no longer resolves to a tvdb/tmdb id.

Secondary source (optional): ~/discovery/seen-extra.json — a hand/curated
supplement for things watched entirely outside Plex (old HBO/AMC watches
etc.). Same shape: {"tv_titles": [...], "movie_titles": [...]}.

Output ~/discovery/seen.json:
{
  "generated": "<iso>",
  "tv":     {"titles": [normalized...], "tvdb_ids": [ints...]},
  "movies": {"titles": [normalized...], "tmdb_ids": [ints...]},
  "raw":    {"tv": {display: normalized}, "movies": {display: normalized}}
}
"""
import json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.expanduser("~/discovery")
CONFIG_PATH = os.path.join(ROOT, "config.json")
SEEN_PATH = os.path.join(ROOT, "seen.json")
EXTRA_PATH = os.path.join(ROOT, "seen-extra.json")

cfg = json.load(open(CONFIG_PATH))
PLEX = cfg.get("plex_url", "http://127.0.0.1:18725")
PLEX_TOKEN = cfg["plex_token"]
TV_SECTION = str(cfg.get("plex_tv_section", 2))
MOVIE_SECTION = str(cfg.get("plex_movie_section", 1))


def norm_title(t):
    """Deterministic title key. lowercases, drops a trailing (YYYY),
    &->and, strips punctuation, collapses spaces, drops a leading 'the '."""
    if not t:
        return ""
    t = t.lower()
    t = re.sub(r"\(\s*\d{4}\s*\)", " ", t)      # drop parenthetical year
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)            # punctuation -> space
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^the\s+", "", t)                # leading 'the'
    return t


def plex_get(path):
    url = f"{PLEX}{path}{'&' if '?' in path else '?'}X-Plex-Token={PLEX_TOKEN}"
    return urllib.request.urlopen(url, timeout=30).read()


def history_titles(section, kind):
    """Return {display_title: normalized} for a library section's watch
    history. kind='tv' uses grandparentTitle (show), else title (movie)."""
    out = {}
    data = plex_get(f"/status/sessions/history/all?librarySectionID={section}")
    root = ET.fromstring(data)
    for v in root.findall(".//Video"):
        disp = (v.get("grandparentTitle") if kind == "tv" else v.get("title")) or ""
        disp = disp.strip()
        if not disp:
            continue
        n = norm_title(disp)
        if n:
            out.setdefault(disp, n)
    return out


def library_ids(base_url, key, id_field):
    """Bonus exact-match: ids for titles STILL in the *arr library."""
    try:
        endpoint = "/series" if id_field == "tvdbId" else "/movie"
        data = json.loads(urllib.request.urlopen(
            f"{base_url}{endpoint}?apikey={key}", timeout=30).read())
        return {m.get(id_field) for m in data if m.get(id_field)}
    except Exception as e:
        print(f"  (library id fetch failed for {id_field}: {e})")
        return set()


def main():
    tv_hist = history_titles(TV_SECTION, "tv")
    mv_hist = history_titles(MOVIE_SECTION, "movie")
    print(f"Plex history: {len(tv_hist)} TV shows, {len(mv_hist)} movies")

    # Optional curated supplement (watched entirely outside Plex).
    extra = {}
    if os.path.exists(EXTRA_PATH):
        extra = json.load(open(EXTRA_PATH))
        for t in extra.get("tv_titles", []):
            tv_hist.setdefault(t, norm_title(t))
        for t in extra.get("movie_titles", []):
            mv_hist.setdefault(t, norm_title(t))
        print(f"seen-extra.json merged: +{len(extra.get('tv_titles', []))} TV, "
              f"+{len(extra.get('movie_titles', []))} movies")

    tvdb_ids = library_ids(cfg["sonarr_url"], cfg["sonarr_key"], "tvdbId")
    tmdb_ids = library_ids(cfg["radarr_url"], cfg["radarr_key"], "tmdbId")

    seen = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "tv": {
            "titles": sorted(set(tv_hist.values())),
            "tvdb_ids": sorted(i for i in tvdb_ids if i),
        },
        "movies": {
            "titles": sorted(set(mv_hist.values())),
            "tmdb_ids": sorted(i for i in tmdb_ids if i),
        },
        "raw": {"tv": tv_hist, "movies": mv_hist},
    }

    if "--dry-run" in sys.argv:
        print("\n--- TV titles seen (normalized) ---")
        for disp in sorted(tv_hist):
            print(f"  {disp!r:45s} -> {tv_hist[disp]}")
        print("\n--- Movie titles seen (normalized) ---")
        for disp in sorted(mv_hist):
            print(f"  {disp!r:45s} -> {mv_hist[disp]}")
        print(f"\n(dry-run) would write {SEEN_PATH}")
        print(f"  tv: {len(seen['tv']['titles'])} titles, {len(seen['tv']['tvdb_ids'])} lib tvdb ids")
        print(f"  movies: {len(seen['movies']['titles'])} titles, {len(seen['movies']['tmdb_ids'])} lib tmdb ids")
        return

    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=2)
    os.chmod(SEEN_PATH, 0o600)
    print(f"wrote {SEEN_PATH}: tv={len(seen['tv']['titles'])} titles, "
          f"movies={len(seen['movies']['titles'])} titles")


if __name__ == "__main__":
    main()
