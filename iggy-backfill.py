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

EPISODE_RE = re.compile(
    r'/iggy/iggy-(?P<year>\d{4})/(?P<slug>\d+-iggy-confidential-(?P<num>\d+)-[a-z0-9-]+)'
)
MEDIAFIRE_RE = re.compile(r'https?://www\.mediafire\.com/file[^"<>]+')


def fetch_year_page(year: int, ua: str) -> str:
    url = f"https://rollins-archive.com/iggy/iggy-{year}"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")


def parse_year_episodes(html: str) -> list[dict]:
    """Returns list of {num, slug, guid, mediafire_url}, newest-first
    by episode number. Each episode is associated to the first MediaFire URL
    within ~3000 chars after the link in the HTML."""
    items = {}
    for m in EPISODE_RE.finditer(html):
        num = m.group("num")
        if num in items:
            continue
        slug = m.group("slug")
        year = m.group("year")
        region = html[m.end():m.end() + 3000]
        mf = MEDIAFIRE_RE.search(region)
        items[num] = {
            "num": int(num),
            "year": int(year),
            "slug": slug,
            "guid": f"https://rollins-archive.com/iggy/iggy-{year}/{slug}",
            "mediafire_url": mf.group(0) if mf else None,
        }
    return sorted(items.values(), key=lambda x: x["num"], reverse=True)


# ---------- main ----------

def pick_next_episode(state: dict, cfg: dict) -> dict | None:
    """Find the most recent episode in the current/next year page that hasn't
    been processed yet. If a year is fully processed, mark it exhausted and
    move back one year."""
    year = state["next_year"]
    earliest_year = 2009  # Iggy Confidential started ~2010 on BBC 6 Music
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
        episodes = parse_year_episodes(html)
        sync.log(f"  year {year}: {len(episodes)} episodes on page")
        for ep in episodes:
            if ep["guid"] in state["processed_guids"]:
                continue
            if ep["guid"] in sync.load_state().get("downloaded_guids", []):
                continue
            if not ep["mediafire_url"]:
                continue
            return ep
        # Year exhausted — back to previous year
        sync.log(f"  year {year}: all processed, moving to {year - 1}")
        state["exhausted_years"].append(year)
        state["next_year"] = year - 1
        year -= 1
    return None


def main() -> int:
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

    item = {
        "title": f"Iggy Confidential #{ep['num']} ({ep['year']}) — backfill",
        "guid": ep["guid"],
        "mediafire_url": ep["mediafire_url"],
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
