#!/usr/bin/env python3
"""morning-briefing (WSL) — daily audio briefing generated fresh each morning.

Pulls together:
  1. NWS forecast for a fixed lat/lon (set in config)
  2. Beach flag condition, scraped from a local Ocean Rescue current-conditions
     page (plain HTML, no API; URL set in config)
  3. One headline each from a handful of topic-siloed RSS feeds chosen to be
     inherently non-political (tech / science / business / sports / local),
     rather than filtering a general news firehose for politics
  4. Text-to-speech via edge-tts (free, local, no API key)
  5. rsync to the seedbox's ABS "Podcasts" library, under a dedicated
     Morning-Briefing subfolder
  6. Prune remote episodes older than N days, then trigger an ABS library
     scan so the new episode appears (and old ones drop off) in the app

Unlike rollins-sync, there is no delete-and-rediscover step: each day is a
brand new episode file (dated filename), not an update to an existing one,
so a plain library scan is all ABS needs.

Config:  ~/.morning-briefing/config.json (created with defaults on first run)
Log:     ~/.morning-briefing/log/<date>.log

Designed for Windows Task Scheduler:
    wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 ~/.morning-briefing/briefing.py'

Only external dep: edge-tts (installed in ~/.morning-briefing/venv).
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Traditional/public-domain Buddhist blessings — one picked at random each morning.
# Deliberately spread across different teachings/themes (metta, impermanence, mind
# training, gratitude) rather than all being metta-formula variants, since a pool
# that's mostly reworded "may all beings be happy" lines reads as repetitive even
# when the pick is genuinely random.
BLESSINGS = [
    "May all beings be happy. May all beings be free from suffering. "
    "May all beings never be separated from the great happiness devoid of suffering. "
    "May all beings dwell in equanimity, free from attachment and aversion.",

    "May you be free from danger. May you have mental happiness. "
    "May you have physical happiness. May you have ease of well-being.",

    "Just as a mother would protect her only child with her life, even so let one "
    "cultivate a boundless heart towards all beings.",

    "Peace comes from within. Do not seek it without.",

    "Three things cannot be long hidden: the sun, the moon, and the truth.",

    "You yourself, as much as anybody in the entire universe, deserve your love "
    "and affection.",

    "In the sky, there is no distinction of east and west; people create "
    "distinctions out of their own minds and then believe them to be true.",

    "Holding onto anger is like drinking poison and expecting the other person "
    "to die.",

    "The mind is everything. What you think, you become.",

    "Do not dwell in the past, do not dream of the future, concentrate the mind "
    "on the present moment.",

    "A jug fills drop by drop.",

    "Better than a thousand hollow words is one word that brings peace.",

    "There is no path to happiness. Happiness is the path.",

    "If you light a lamp for somebody, it will also brighten your own path.",

    "Nothing ever exists entirely alone. Everything is in relation to everything else.",

    "Every morning we are born again. What we do today is what matters most.",

    "Let go of the things that no longer serve you, and make room for what does.",

    "Gratitude for what is here now is itself a form of wealth.",
]

# ----- paths -----

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".morning-briefing")
CONFIG = os.path.join(ROOT, "config.json")
LOG_DIR = os.path.join(ROOT, "log")
WORK = os.path.join(ROOT, "work")

DEFAULTS = {
    # Fill these into ~/.morning-briefing/config.json before first run.
    "greeting_name": "there",
    "lat": 0.0,
    "lon": 0.0,
    "beach_url": "https://YOUR-BEACH-CONDITIONS-URL.example.com/",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) personal-morning-briefing/1.0",
    # topic -> RSS feed. Chosen to be inherently non-political by section,
    # so no keyword filtering is needed. "Local" URL is a placeholder — swap
    # in your city's news feed.
    "feeds": {
        "Technology": "http://feeds.bbci.co.uk/news/technology/rss.xml",
        "Science": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
        "Sports": "https://www.espn.com/espn/rss/news",
        "Local": "https://YOUR-LOCAL-NEWS-FEED.example.com/rss",
    },
    "tts_voice": "en-US-ChristopherNeural",
    "keep_days": 14,
    # remote — placeholders; real values land in ~/.morning-briefing/config.json
    "ssh_host": "USER@SEEDBOX.example.com",
    "remote_media_root": "~/media/Podcasts",
    "remote_subfolder": "Morning-Briefing",
    "abs": {
        "url": "https://YOUR-ABS-HOST.example.com",
        "username": "YOUR_ABS_USERNAME",
        "password": "",
        "library_id": "YOUR_ABS_LIBRARY_UUID",
    },
}


# ----- helpers -----

def log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(path, "a") as f:
        f.write(line + "\n")


def load_config() -> dict:
    os.makedirs(ROOT, exist_ok=True)
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
        os.chmod(CONFIG, 0o600)
        log(f"wrote default config to {CONFIG} — fill in abs.password before running")
    with open(CONFIG) as f:
        return json.load(f)


def http_get(url: str, ua: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=timeout).read()


# ----- weather (NWS) -----

def get_weather(lat: float, lon: float, ua: str) -> str:
    points = json.loads(http_get(f"https://api.weather.gov/points/{lat},{lon}", ua))
    forecast_url = points["properties"]["forecast"]
    forecast = json.loads(http_get(forecast_url, ua))
    periods = forecast["properties"]["periods"]
    # A 4am run can still be inside the "Overnight"/"Tonight" period until
    # sunrise, which reads oddly in a morning briefing — always report the
    # next daytime period instead of whatever's chronologically first.
    today = next((p for p in periods if p["isDaytime"]), periods[0])
    return f"{today['name']}: {today['detailedForecast']}"


# ----- beach flag (local Ocean Rescue current-conditions page) -----

def get_beach_flag(url: str, ua: str) -> str:
    """Scrapes a local Ocean Rescue page for current beach flag / hazard status.
    The specific page layout expected below (hazard-flag alt text + labeled
    condition sections) matches a common Ocean Rescue template — adjust regexes
    if your city uses a different structure."""
    html = http_get(url, ua).decode("utf-8", errors="replace")
    hazard_m = re.search(r'alt="Beach Warning (\w+) Hazard Flag"', html)
    # Labels sit right up against inline tags (e.g. "...Hours:</strong> 9:00 a.m."),
    # so strip tags to plain text first rather than regexing the raw markup —
    # far less brittle if the page's markup shifts around, only the label text matters.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[\xa0\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    date_m = re.search(r"Today's Beach Conditions:\s*([A-Za-z]+ \d{1,2}, \d{4})", text)
    water_m = re.search(r"Water Temperature is Currently:\s*([\d.]+)\s*°F", text)
    lifeguard_m = re.search(
        r"Lifeguard Duty Hours:\s*(\d{1,2}:\d{2}\s*[ap]\.m\.\s*-\s*\d{1,2}:\d{2}\s*[ap]\.m\.)",
        text, re.I,
    )
    swim_m = re.search(r"Swimming Conditions:\s*(\w+)", text)

    if not hazard_m:
        return "Beach flag conditions were unavailable this morning."

    parts = [f"Beach flag: {hazard_m.group(1)} hazard"]
    if date_m:
        parts[0] += f", reported {date_m.group(1)}"
    parts[0] += "."
    if swim_m:
        parts.append(f"Swimming conditions: {swim_m.group(1)}.")
    if water_m:
        parts.append(f"Water temperature: {water_m.group(1)} degrees.")
    if lifeguard_m:
        parts.append(f"Lifeguards on duty {lifeguard_m.group(1).strip()}")

    msg = " ".join(parts)
    if date_m:
        try:
            reported_dt = datetime.strptime(date_m.group(1), "%B %d, %Y")
            age_hours = (datetime.now() - reported_dt).total_seconds() / 3600
            if age_hours > 36:
                days = int(age_hours // 24)
                msg += (f" Note: that report is {days} day{'s' if days != 1 else ''} old — "
                        f"the source hasn't refreshed recently, treat with caution.")
        except ValueError:
            pass
    return msg


# ----- headlines (topic-siloed RSS, top item only) -----

def get_top_headline(url: str, ua: str) -> str | None:
    xml_bytes = http_get(url, ua)
    root = ET.fromstring(xml_bytes)
    item = root.find(".//item")
    if item is None:
        return None
    title = (item.findtext("title") or "").strip()
    return title or None


def get_headlines(feeds: dict, ua: str) -> list[tuple[str, str]]:
    out = []
    for topic, url in feeds.items():
        try:
            title = get_top_headline(url, ua)
            if title:
                out.append((topic, title))
            else:
                log(f"  headline: {topic} — no items found")
        except Exception as e:
            log(f"  headline: {topic} — FAILED: {e}")
    return out


# ----- script assembly -----

def build_script(weather: str, beach: str, headlines: list[tuple[str, str]], greeting_name: str) -> str:
    date_str = datetime.now().strftime("%A, %B %-d")
    lines = [f"Good morning, {greeting_name}."]
    blessing_idx = random.SystemRandom().randrange(len(BLESSINGS))
    log(f"  blessing #{blessing_idx}: {BLESSINGS[blessing_idx][:50]}...")
    lines.append(BLESSINGS[blessing_idx])
    lines.append(f"Here's your briefing for {date_str}.")
    lines.append(f"Weather: {weather}")
    lines.append(beach)
    lines.append("In the news:")
    for topic, title in headlines:
        lines.append(f"{topic}: {title}.")
    lines.append("That's your morning briefing.")
    return "\n".join(lines)


# ----- TTS -----

def synthesize(text: str, voice: str, out_mp3: str) -> None:
    edge_tts_bin = os.path.join(ROOT, "venv", "bin", "edge-tts")
    subprocess.run(
        [edge_tts_bin, "--voice", voice, "--text", text, "--write-media", out_mp3],
        check=True,
    )


def tag_mp3(mp3: str, title: str, tagged_out: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", mp3, "-c", "copy",
         "-metadata", f"title={title}",
         "-metadata", "artist=Morning Briefing",
         "-id3v2_version", "3",
         tagged_out],
        check=True,
    )


# ----- remote upload + ABS scan -----

def rsync_to_seedbox(local_path: str, ssh_host: str, remote_root: str, subfolder: str) -> None:
    subprocess.run(
        ["ssh", ssh_host, f"mkdir -p {remote_root}/{subfolder}"],
        check=True,
    )
    remote_path = f"{ssh_host}:{remote_root}/{subfolder}/{os.path.basename(local_path)}"
    subprocess.run(["rsync", "-a", local_path, remote_path], check=True)


def prune_remote(ssh_host: str, remote_root: str, subfolder: str, keep_days: int) -> None:
    subprocess.run(
        ["ssh", ssh_host,
         f"find {remote_root}/{subfolder} -maxdepth 1 -name '*.mp3' -mtime +{keep_days} -delete"],
        check=True,
    )


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

def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    cfg = load_config()

    log("=== morning-briefing run start ===")
    if not cfg["abs"].get("password"):
        log("ABS password missing from config — fill in and rerun")
        return 1

    try:
        weather = get_weather(cfg["lat"], cfg["lon"], cfg["user_agent"])
        log(f"  weather: {weather[:80]}...")
    except Exception as e:
        weather = "Weather forecast was unavailable this morning."
        log(f"  weather FAILED: {e}")

    try:
        beach = get_beach_flag(cfg["beach_url"], cfg["user_agent"])
        log(f"  {beach}")
    except Exception as e:
        beach = "Beach flag conditions were unavailable this morning."
        log(f"  beach FAILED: {e}")

    headlines = get_headlines(cfg["feeds"], cfg["user_agent"])
    log(f"  headlines: {len(headlines)}/{len(cfg['feeds'])} fetched")

    script_text = build_script(weather, beach, headlines, cfg.get("greeting_name", "there"))
    date_tag = datetime.now().strftime("%Y-%m-%d")
    raw_mp3 = os.path.join(WORK, f"briefing-raw-{date_tag}.mp3")
    final_mp3 = os.path.join(WORK, f"morning-briefing-{date_tag}.mp3")

    log("  synthesizing audio")
    synthesize(script_text, cfg["tts_voice"], raw_mp3)
    tag_mp3(raw_mp3, f"Morning Briefing - {date_tag}", final_mp3)
    os.remove(raw_mp3)

    log("  rsync to seedbox")
    rsync_to_seedbox(final_mp3, cfg["ssh_host"], cfg["remote_media_root"], cfg["remote_subfolder"])
    os.remove(final_mp3)

    log(f"  pruning remote episodes older than {cfg['keep_days']} days")
    prune_remote(cfg["ssh_host"], cfg["remote_media_root"], cfg["remote_subfolder"], cfg["keep_days"])

    abs_scan(cfg["abs"])

    log("=== morning-briefing run end ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
