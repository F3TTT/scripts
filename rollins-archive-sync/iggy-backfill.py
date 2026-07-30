#!/usr/bin/env python3
"""iggy-backfill — walk rollins-archive.com Iggy year pages newest-first,
process one historical episode per run. Uses the same per-item pipeline
as rollins-sync (whisper + chapters + upload + ABS rediscover).

Polite to the archive:
  - 1 page fetch per day (only the current year page until exhausted, then
    moves back to /iggy/iggy-<year-1>)
  - actual MP3 downloads are MediaFire, not the archive
  - resumable state file tracks progress

Config: shares `~/.rollins-sync/config.json` with rollins-sync
State:  `~/.rollins-sync/iggy_backfill_state.json`
        { "next_year": 2026, "exhausted_years": [],
          "processed_guids": [...] }

Schedule: Windows Task Scheduler, daily, AFTER rollins-sync-daily (offset by 1-2
hours so they don't both transcribe at the same time on the same CPU).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

ROOT = os.path.expanduser("~/.rollins-sync")
STATE_PATH = os.path.join(ROOT, "iggy_backfill_state.json")
SYNC_PY = os.path.join(ROOT, "sync.py")

# Load shared rollins-sync as a module so we can call its pipeline functions
spec = importlib.util.spec_from_file_location("sync", SYNC_PY)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        # Default starts at the most recent year we know Iggy aired
        return {
            "next_year": datetime.now().year,
            "exhausted_years": [],
            "processed_guids": [],
        }
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ---------- year page scraping ----------

# The show was slugged `iggy-pop-NN-title` in the early years and renamed to
# `iggy-confidential-NNN-title` later on. Matching only the latter made every
# pre-rename year look empty, which the walk below read as "already done".
EPISODE_RE = re.compile(
    r'/iggy/iggy-(?P<year>\d{4})/'
    r'(?P<slug>(?P<artid>\d+)-iggy-(?:confidential|pop)-[a-z0-9-]+)'
)
# Episode number, where there is one. Some early items are unnumbered specials
# (`iggy-pop-the-john-peel-lecture`) and some carry a letter suffix (`14b`).
EPISODE_NUM_RE = re.compile(r'-iggy-(?:confidential|pop)-(\d+[a-z]?)-')
MEDIAFIRE_RE = re.compile(r'https?://www\.mediafire\.com/file[^"<>]+')
# Episode-page probes cost a request each. Cap them so a run of link-less
# episodes can't turn one run into a burst against the archive.
MAX_EPISODE_PROBES = 5
PROBE_DELAY_S = 45
# Recent episodes are offloaded to MediaFire; older ones are zips hosted on the
# archive itself. Those are linked inconsistently — root-relative in some years
# (`/2014/iggy27.zip`), absolute in others
# (`http://www.rollins-archive.com/2025/Iggy_Confidential_2025-11-16.zip`) — so
# match any .zip href and normalise afterwards.
ARCHIVE_ZIP_RE = re.compile(r'href="(?P<url>[^"]+\.zip)"', re.I)


def fetch_page(url: str, ua: str, referer: str | None = None) -> str:
    headers = {"User-Agent": ua}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")


def fetch_year_page(year: int, ua: str) -> str:
    return fetch_page(f"https://rollins-archive.com/iggy/iggy-{year}", ua)


def parse_year_episodes(html: str, year: int) -> list[dict]:
    """Returns list of {num, artid, slug, guid} for `year`, newest-first.

    Only episodes whose URL year matches `year` are returned — a year listing
    also links to neighbouring years in its nav, and letting those through
    would mark the wrong year exhausted.

    Ordering is by Joomla article id, not episode number: it is present on
    every item (numbers are not) and increases monotonically with post date.
    """
    items = {}
    for m in EPISODE_RE.finditer(html):
        if int(m.group("year")) != year:
            continue
        slug = m.group("slug")
        if slug in items:
            continue
        num_m = EPISODE_NUM_RE.search(slug)
        items[slug] = {
            "num": num_m.group(1) if num_m else None,
            "artid": int(m.group("artid")),
            "year": year,
            "slug": slug,
            "guid": f"https://rollins-archive.com/iggy/iggy-{year}/{slug}",
            # Recent years render the full article inline, download link and all.
            "download_url": extract_download_url(html[m.end():m.end() + 3000]),
        }
    return sorted(items.values(), key=lambda x: x["artid"], reverse=True)


def extract_download_url(html: str) -> str | None:
    """Pull a zip link out of a chunk of article HTML.

    Recent episodes are offloaded to MediaFire; older ones are zips hosted on
    the archive itself and linked relative.
    """
    mf = MEDIAFIRE_RE.search(html)
    if mf:
        return mf.group(0)
    zip_m = ARCHIVE_ZIP_RE.search(html)
    if not zip_m:
        return None
    url = zip_m.group("url")
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        # Normalise to https — the archive links some zips over plain http.
        return "https://" + url.split("://", 1)[1]
    return "https://rollins-archive.com" + ("" if url.startswith("/") else "/") + url


def find_download_url(guid: str, ua: str) -> str | None:
    """Fetch a single episode page and pull its zip link.

    Only needed for years whose listing shows intros rather than full articles —
    the link is on the episode page in that case. Costs one extra request.
    """
    html = fetch_page(guid, ua, referer=guid.rsplit("/", 1)[0])
    return extract_download_url(html)


# ---------- main ----------

def pick_next_episode(state: dict, cfg: dict) -> dict | None:
    """Find the most recent episode in the current/next year page that hasn't
    been processed yet. If a year is fully processed, mark it exhausted and
    move back one year."""
    year = state["next_year"]
    # The archive's Iggy nav runs 2013-2026; nothing exists before that.
    earliest_year = 2013
    probes = 0
    while year >= earliest_year:
        sync.log(f"iggy: scanning year {year}")
        try:
            html = fetch_year_page(year, cfg["user_agent"])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                sync.log(f"  year {year}: 404 (no page)")
                state["exhausted_years"].append(year)
                state["next_year"] = year - 1
                year -= 1
                continue
            raise
        episodes = parse_year_episodes(html, year)
        sync.log(f"  year {year}: {len(episodes)} episodes on page")
        done = set(state["processed_guids"]) | set(
            sync.load_state().get("downloaded_guids", [])
        )
        # Episodes we probed and found no zip for. Tracked separately from
        # processed_guids so "we have this" and "this had no file" stay
        # distinguishable — clear the list to re-probe if the archive backfills
        # its own links later.
        no_download = set(state.setdefault("no_download_guids", []))
        for ep in episodes:
            if ep["guid"] in done or ep["guid"] in no_download:
                continue
            url = ep.get("download_url")
            if not url:
                if probes >= MAX_EPISODE_PROBES:
                    sync.log(f"  probe budget spent ({probes}) — resuming here next run")
                    return None
                if probes:
                    time.sleep(PROBE_DELAY_S)
                probes += 1
                url = find_download_url(ep["guid"], cfg["user_agent"])
            if not url:
                sync.log(f"  no download link: {ep['slug']}")
                state["no_download_guids"].append(ep["guid"])
                save_state(state)
                continue
            ep["download_url"] = url
            return ep
        # Year exhausted — back to previous year
        sync.log(f"  year {year}: all processed, moving to {year - 1}")
        state["exhausted_years"].append(year)
        state["next_year"] = year - 1
        year -= 1
    return None


def main() -> int:
    # Shared with rollins-sync — see acquire_pipeline_lock() in sync.py for why
    # it's one lock across both scripts rather than one each.
    if not sync.acquire_pipeline_lock():
        sync.log("iggy-backfill: another pipeline run holds the lock — exiting")
        return 0

    cfg = sync.load_config()
    state = load_state()
    main_state = sync.load_state()

    sync.log("=== iggy-backfill run start ===")

    if not cfg["abs"].get("password"):
        sync.log("ABS password missing from config — bail")
        return 1

    ep = pick_next_episode(state, cfg)
    if not ep:
        sync.log("nothing to process (history exhausted)")
        return 0

    sync.log(f"selected: year={ep['year']} num={ep['num']} guid={ep['guid'][:80]}")

    label = f"#{ep['num']}" if ep["num"] else ep["slug"].split("-", 1)[1]
    item = {
        "title": f"Iggy Confidential {label} ({ep['year']}) — backfill",
        "guid": ep["guid"],
        "download_url": ep["download_url"],
        "target_subfolder": "iggy-confidential",
        "category_match": f"Iggy (backfill year {ep['year']})",
    }
    try:
        sync.process_item(item, cfg, main_state)
        state["processed_guids"].append(ep["guid"])
        save_state(state)
        sync.log("=== iggy-backfill run end (1 episode) ===")
        return 0
    except Exception as e:
        sync.log(f"FAILED: {type(e).__name__}: {e}")
        sync.log("=== iggy-backfill run end (failure) ===")
        return 2


if __name__ == "__main__":
    sys.exit(main())
