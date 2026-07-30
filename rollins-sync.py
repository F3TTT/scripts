#!/usr/bin/env python3
"""rollins-sync — daily poll of rollins-archive.com RSS feed.

For each new episode in a watched category:
  1. download zip from MediaFire (via curl -L, follows redirect)
  2. extract single MP3
  3. detect silence-bordered segments via ffmpeg
  4. inject ID3 chapter markers (codec copy, no re-encode)
  5. drop into the ABS-watched folder
  6. trigger ABS rescan (optional, best-effort)

Designed to run on the seedbox via cron. No external Python deps —
stdlib + system ffmpeg + curl.

Config: ~/.rollins-tmp/config.json (created with defaults on first run)
State:  ~/.rollins-tmp/state.json (guids of episodes already processed)
Log:    ~/.rollins-tmp/sync.log
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from html import unescape

# ---------- config / paths ----------

HOME = os.path.expanduser("~")
TMP_ROOT = os.path.join(HOME, ".rollins-tmp")
CONFIG_PATH = os.path.join(TMP_ROOT, "config.json")
STATE_PATH = os.path.join(TMP_ROOT, "state.json")
LOG_PATH = os.path.join(TMP_ROOT, "sync.log")
WORK_DIR = os.path.join(TMP_ROOT, "work")

DEFAULTS = {
    "rss_url": "https://rollins-archive.com/?format=feed&type=rss",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) personal-archive-sync/1.0",
    "media_root": os.path.join(HOME, "media/Audio/Rollins-Archive"),
    # category in RSS -> subfolder under media_root
    "categories": {
        "Harmony In My Head": "harmony-in-my-head",
        # add "Iggy" -> "iggy-confidential" when Iggy returns in 2027
    },
    "silence_min_seconds": 2.5,
    "silence_noise_db": -40,
    "abs": {
        "enabled": False,
        "url": "https://YOUR-ABS-HOST.example.com",
        "username": "YOUR_ABS_USERNAME",
        "password": "",                       # fill in on first run in ~/.rollins-sync/config.json
        "library_id": "YOUR_ABS_LIBRARY_UUID",
    },
}


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def ensure_dirs(cfg) -> None:
    os.makedirs(TMP_ROOT, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(cfg["media_root"], exist_ok=True)
    for subfolder in cfg["categories"].values():
        os.makedirs(os.path.join(cfg["media_root"], subfolder), exist_ok=True)


def load_config():
    os.makedirs(TMP_ROOT, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
        os.chmod(CONFIG_PATH, 0o600)
        log(f"wrote default config to {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"downloaded_guids": []}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ---------- RSS ----------

def fetch_rss(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=30).read()


def parse_rss(xml_bytes: bytes) -> list:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        categories = [c.text for c in item.iter("category") if c.text]
        # MediaFire URL: <a href="https://www.mediafire.com/...zip/file">DATE</a>
        mf = re.search(r"https?://www\.mediafire\.com/file[^\"'<>]+", description)
        items.append({
            "title": title,
            "guid": guid,
            "categories": categories,
            "mediafire_url": mf.group(0) if mf else None,
            "pub_date": item.findtext("pubDate"),
        })
    return items


def items_to_process(items: list, state: dict, categories: dict) -> list:
    selected = []
    for it in items:
        if it["guid"] in state["downloaded_guids"]:
            continue
        if not it["mediafire_url"]:
            continue
        match = next((c for c in it["categories"] if c in categories), None)
        if not match:
            continue
        it["target_subfolder"] = categories[match]
        it["category_match"] = match
        selected.append(it)
    return selected


# ---------- download / extract ----------

def download_zip(url: str, dest: str, ua: str) -> None:
    subprocess.run(
        ["curl", "-sL", "--fail", "--max-time", "1800",
         "-A", ua, "-o", dest, url],
        check=True,
    )


def extract_single_mp3(zip_path: str, work_dir: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        mp3s = [n for n in zf.namelist() if n.lower().endswith(".mp3")]
        if not mp3s:
            raise RuntimeError(f"no MP3 inside {zip_path}")
        # almost always exactly one
        zf.extract(mp3s[0], work_dir)
        return os.path.join(work_dir, mp3s[0])


# ---------- silence detection / chapters ----------

SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def get_duration(mp3_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         mp3_path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def detect_silence_ends(mp3_path: str, min_s: float, noise_db: int) -> list:
    """Return timestamps (seconds) where silences END — i.e., new content starts."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats",
         "-i", mp3_path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_s}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [float(m.group(1)) for m in SILENCE_END_RE.finditer(proc.stderr)]


def write_chapter_metadata(boundaries_s: list, duration_s: float, out_path: str) -> int:
    """boundaries_s = sorted list of silence-end timestamps in seconds.
    Writes an ffmpeg metadata file. Returns number of chapters generated."""
    pts = [0.0] + sorted(b for b in boundaries_s if 0 < b < duration_s) + [duration_s]
    # collapse near-duplicate points
    cleaned = [pts[0]]
    for p in pts[1:]:
        if p - cleaned[-1] >= 1.0:
            cleaned.append(p)
    n_chapters = len(cleaned) - 1
    with open(out_path, "w") as f:
        f.write(";FFMETADATA1\n")
        for i in range(n_chapters):
            start_ms = int(cleaned[i] * 1000)
            end_ms = int(cleaned[i + 1] * 1000)
            f.write("\n[CHAPTER]\n")
            f.write("TIMEBASE=1/1000\n")
            f.write(f"START={start_ms}\n")
            f.write(f"END={end_ms}\n")
            mm = int(cleaned[i] // 60)
            ss = int(cleaned[i] % 60)
            f.write(f"title=Segment {i+1} ({mm:02d}:{ss:02d})\n")
    return n_chapters


def inject_chapters(in_mp3: str, meta_path: str, out_mp3: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-y",
         "-i", in_mp3, "-i", meta_path,
         "-map", "0", "-map_metadata", "1",
         "-codec", "copy",
         "-id3v2_version", "3",
         out_mp3],
        check=True, capture_output=True,
    )


# ---------- ABS rescan (best effort) ----------

def abs_trigger_scan(abs_cfg) -> None:
    if not abs_cfg.get("enabled") or not abs_cfg.get("password"):
        return
    try:
        body = json.dumps({
            "username": abs_cfg["username"],
            "password": abs_cfg["password"],
        }).encode()
        req = urllib.request.Request(
            abs_cfg["url"] + "/login",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            login = json.loads(r.read())
        token = (login.get("user") or {}).get("token") or login.get("token")
        if not token:
            log("  ABS login: no token returned")
            return
        scan_url = f"{abs_cfg['url']}/api/libraries/{abs_cfg['library_id']}/scan"
        req = urllib.request.Request(
            scan_url, method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib.request.urlopen(req, timeout=15).read()
        log("  ABS scan triggered")
    except Exception as e:
        log(f"  ABS scan trigger failed: {e}")


# ---------- main per-item flow ----------

def process_item(item, cfg, state) -> None:
    log(f"--- {item['title']!r} [{item['category_match']}]")
    target_dir = os.path.join(cfg["media_root"], item["target_subfolder"])
    os.makedirs(target_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=WORK_DIR) as tmp:
        zip_path = os.path.join(tmp, "ep.zip")
        log("  download mediafire zip...")
        download_zip(item["mediafire_url"], zip_path, cfg["user_agent"])
        log(f"  zip size: {os.path.getsize(zip_path):,} bytes")

        mp3_path = extract_single_mp3(zip_path, tmp)
        mp3_size = os.path.getsize(mp3_path)
        log(f"  extracted mp3: {os.path.basename(mp3_path)} ({mp3_size:,} bytes)")

        duration = get_duration(mp3_path)
        log(f"  duration: {duration:.0f}s ({duration/60:.1f} min)")

        silence_ends = detect_silence_ends(
            mp3_path,
            cfg["silence_min_seconds"],
            cfg["silence_noise_db"],
        )
        log(f"  silence ends >= {cfg['silence_min_seconds']}s : {len(silence_ends)}")

        meta_path = os.path.join(tmp, "chapters.txt")
        n = write_chapter_metadata(silence_ends, duration, meta_path)
        log(f"  chapters written: {n}")

        # Final filename in target folder, preserve the in-zip name
        final_path = os.path.join(target_dir, os.path.basename(mp3_path))
        inject_chapters(mp3_path, meta_path, final_path)
        log(f"  installed: {final_path}")

    state["downloaded_guids"].append(item["guid"])
    save_state(state)


def main() -> int:
    cfg = load_config()
    ensure_dirs(cfg)
    state = load_state()

    log("=== rollins-sync run start ===")
    try:
        xml = fetch_rss(cfg["rss_url"], cfg["user_agent"])
        items = parse_rss(xml)
    except Exception as e:
        log(f"RSS fetch/parse failed: {e}")
        return 2

    log(f"rss: {len(items)} total items")
    selected = items_to_process(items, state, cfg["categories"])
    log(f"new + matching: {len(selected)} items to process")

    for item in selected:
        try:
            process_item(item, cfg, state)
        except subprocess.CalledProcessError as e:
            log(f"  FAILED: subprocess err: {e}")
        except Exception as e:
            log(f"  FAILED: {e}")

    if selected:
        abs_trigger_scan(cfg["abs"])

    log("=== rollins-sync run end ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
