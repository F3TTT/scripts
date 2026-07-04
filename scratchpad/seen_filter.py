#!/usr/bin/env python3
"""Shared 'already watched' gate for the discovery pipelines.

Reads ~/discovery/seen.json (built by build-seen-list.py from Plex watch
history) and answers: has the user already watched this show/movie?

Matching is by NORMALIZED TITLE first (works even for media that's been
deleted, e.g. KAOS — watched in Plex, then removed from Sonarr, so no
tvdb id survives), with in-library tvdb/tmdb ids as an exact-match bonus.
"""
import json, os, re

SEEN_PATH = os.path.join(os.path.expanduser("~/discovery"), "seen.json")


def norm_title(t):
    """Deterministic title key — must match build-seen-list.py exactly."""
    if not t:
        return ""
    t = t.lower()
    t = re.sub(r"\(\s*\d{4}\s*\)", " ", t)
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^the\s+", "", t)
    return t


def load_seen(path=SEEN_PATH):
    """Returns a lookup dict, or None if seen.json is missing (fail-open:
    no seen.json => nothing is filtered, pipelines behave as before)."""
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    return {
        "tv_titles": set(d.get("tv", {}).get("titles", [])),
        "tv_tvdb": set(d.get("tv", {}).get("tvdb_ids", [])),
        "movie_titles": set(d.get("movies", {}).get("titles", [])),
        "movie_tmdb": set(d.get("movies", {}).get("tmdb_ids", [])),
    }


def seen_tv(seen, title, tvdb_id=None):
    """Return a reason string if already watched, else None."""
    if not seen:
        return None
    if tvdb_id and tvdb_id in seen["tv_tvdb"]:
        return "tvdb"
    if norm_title(title) in seen["tv_titles"]:
        return "title"
    return None


def seen_movie(seen, title, tmdb_id=None):
    if not seen:
        return None
    if tmdb_id and tmdb_id in seen["movie_tmdb"]:
        return "tmdb"
    if norm_title(title) in seen["movie_titles"]:
        return "title"
    return None
