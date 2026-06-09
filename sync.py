#!/usr/bin/env python3
"""rollins-sync (WSL) — daily poll of rollins-archive.com RSS feed.

Runs locally on WSL (laptop) because:
  - ultra.cc suspends accounts for sustained CPU work (whisper transcription is heavy)
  - we want to stay off the seedbox until upload time
  - laptop has more CPU per dollar

For each new episode in a watched category:
  1. download zip from MediaFire (curl -L follows the temp redirect)
  2. extract single MP3
  3. transcode to 16 kHz mono WAV (whisper.cpp's preferred input)
  4. transcribe with whisper.cpp + small.en model -> SRT
  5. find ad-marker phrases in the transcript via regex
  6. merge ad markers close together into AD BLOCKS
  7. write ffmpeg metadata file with chapters: alternating AD / Content
  8. inject chapters into MP3 + re-encode to 128k CBR (so naive seekers
        like Absorb can chapter-tap correctly; VBR + Xing-TOC is unreliable)
  9. rsync chaptered MP3 to seedbox media folder
  10. ABS: delete episode from db + trigger library scan to re-read chapters
        (PATCH doesn't accept chapters; delete-and-rediscover is the only way
         to refresh episode.chapters from the file)
  11. clean up WSL tmp files

Config:  ~/.rollins-sync/config.json (created with defaults on first run)
State:   ~/.rollins-sync/state.json  (guids of episodes already processed)
Log:     ~/.rollins-sync/log/<date>.log
Tmp:     ~/.rollins-sync/work/      (cleared per episode)

Designed for Windows Task Scheduler:
    wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 ~/.rollins-sync/sync.py'

No external Python deps — stdlib only.
"""

from __future__ import annotations

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

# ----- paths -----

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".rollins-sync")
CONFIG = os.path.join(ROOT, "config.json")
STATE = os.path.join(ROOT, "state.json")
LOG_DIR = os.path.join(ROOT, "log")
WORK = os.path.join(ROOT, "work")

DEFAULTS = {
    "rss_url": "https://rollins-archive.com/?format=feed&type=rss",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) personal-archive-sync/1.0",
    # category in RSS -> remote subfolder under seedbox media root
    "categories": {
        "Harmony In My Head": "harmony-in-my-head",
        "Iggy": "iggy-confidential",
        "Iggy 2026": "iggy-confidential",
    },
    # whisper.cpp
    "whisper_bin": os.path.join(HOME, "tools/whisper.cpp/build/bin/whisper-cli"),
    "whisper_model": os.path.join(HOME, "tools/whisper.cpp/models/ggml-small.en.bin"),
    "whisper_threads": 8,
    # remote — placeholders; real values land in ~/.rollins-sync/config.json
    "ssh_host": "USER@SEEDBOX.example.com",
    "remote_media_root": "~/media/Audio/Rollins-Archive",
    # ABS — placeholders; real values land in ~/.rollins-sync/config.json.
    # Per-podcast ids live under category_settings.<slug>.abs_podcast_item_id.
    "abs": {
        "url": "https://YOUR-ABS-HOST.example.com",
        "username": "YOUR_ABS_USERNAME",
        "password": "",   # set in config.json before first run
        "library_id": "YOUR_ABS_LIBRARY_UUID",
    },
    # per-category chapter detection. Keyed by target_subfolder so multiple
    # RSS categories that route to the same folder share settings.
    "category_settings": {
        "harmony-in-my-head": {
            # KCRW HIMH — commercial sponsor reads + KCRW pledge drives
            "abs_podcast_item_id": "YOUR_ABS_PODCAST_ITEM_UUID_HIMH",
            "patterns": [
                [r"KCRW sponsors? (?:include|comes?\s+from)", "KCRW sponsor"],
                [r"support (?:for this show|comes?\s+from)", "Sponsor"],
                [r"KCRW\.com/(?:standup|newsletters|donate|comedy|events)", "KCRW self-promo"],
                [r"go to kcrw\.com to donate", "KCRW pledge"],
                [r"(?:in select theaters|now in theaters|nationwide [A-Z][a-z]+)", "Theater ad"],
            ],
            "marker_prefix": "AD",
            "merge_window_s": 120,
            "block_len_s": 60,
        },
        "iggy-confidential": {
            # BBC 6 Music Iggy Confidential — no commercials. Station IDs +
            # "Coming up later" promos read over a music bed (e.g. "Dance the
            # musical spectrum with Mary Ann Hobbs"). Promos need medium.en +
            # silero VAD to extract; small.en without VAD misses them entirely.
            "abs_podcast_item_id": "YOUR_ABS_PODCAST_ITEM_UUID_IGGY",
            "whisper_model": os.path.join(HOME, "tools/whisper.cpp/models/ggml-medium.en.bin"),
            "vad_model":     os.path.join(HOME, "tools/whisper.cpp/models/ggml-silero-v5.1.2.bin"),
            "vad_threshold": 0.4,
            "patterns": [
                # Promos first (more specific). "ID - BBC promo" chapter title
                # is good enough — user just needs to skip past it.
                [r"\bcoming up (?:in an? )?(?:hour|few|moment)\b", "BBC promo"],
                [r"\bnext on (?:six|6)\s+music\b", "BBC promo"],
                [r"\btonight at \d", "BBC promo"],
                [r"\bdon'?t miss\b", "BBC promo"],
                # Then existing station IDs
                [r"BBC\s*(?:Radio\s*)?6\s*music", "BBC 6 Music ID"],
                [r"\b(?:six|6)\s+music\b", "6 Music ID"],
                [r"\bask your smart speaker\b", "Smart speaker ID"],
                [r"this is iggy confidential", "Confidential ID"],
                [r"(?:I am|I'm|this is) iggy pop", "Iggy intro"],
                [r"iggy confidential", "Show name drop"],
            ],
            "marker_prefix": "ID",
            "merge_window_s": 60,
            "block_len_s": 20,
        },
    },
    # transcript cache: keep newest N SRTs per category for retries/troubleshooting
    "transcript_cache_keep_per_category": 5,
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


def load_state() -> dict:
    if not os.path.exists(STATE):
        return {"downloaded_guids": []}
    with open(STATE) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE, "w") as f:
        json.dump(state, f, indent=2)


# ----- RSS -----

def fetch_rss(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=30).read()


def parse_rss(xml_bytes: bytes) -> list:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        desc = it.findtext("description") or ""
        cats = [c.text for c in it.iter("category") if c.text]
        mf = re.search(r"https?://www\.mediafire\.com/file[^\"'<>]+", desc)
        items.append({
            "title": title,
            "guid": guid,
            "categories": cats,
            "mediafire_url": mf.group(0) if mf else None,
        })
    return items


def filter_new(items: list, state: dict, categories: dict) -> list:
    out = []
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
        out.append(it)
    return out


# ----- download + extract -----

def download_zip(url: str, dest: str, ua: str) -> None:
    subprocess.run(
        ["curl", "-sL", "--fail", "--max-time", "1800",
         "-A", ua, "-o", dest, url],
        check=True,
    )


def extract_single_mp3(zip_path: str, work: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        mp3s = [n for n in zf.namelist() if n.lower().endswith(".mp3")]
        if not mp3s:
            raise RuntimeError(f"no MP3 in {zip_path}")
        zf.extract(mp3s[0], work)
        return os.path.join(work, mp3s[0])


# ----- audio prep + whisper -----

def to_wav_16k(mp3: str, wav: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", mp3, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
        check=True,
    )


def transcribe(wav: str, bin_path: str, model: str, threads: int, out_prefix: str,
               vad_model: str | None = None, vad_threshold: float = 0.5) -> str:
    """Run whisper.cpp, return path to SRT.

    If vad_model is given, enables silero VAD pre-pass. This is what lets
    medium.en pick up speech buried under music beds (e.g. BBC "coming up"
    promos read over a music track). Without VAD, whisper segments tend to
    over-stretch into music and miss the spoken word.
    """
    cmd = [bin_path, "-m", model, "-f", wav, "-t", str(threads),
           "-osrt", "-of", out_prefix]
    if vad_model:
        cmd += ["--vad", "-vm", vad_model, "-vt", str(vad_threshold)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
    srt = out_prefix + ".srt"
    if not os.path.exists(srt):
        raise RuntimeError(f"whisper produced no SRT: {srt}")
    return srt


def parse_srt(srt: str) -> list:
    entries = []
    for block in open(srt).read().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", lines[1])
            if m:
                g = list(map(int, m.groups()))
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = " ".join(lines[2:]).strip()
                entries.append((start, end, text))
    return entries


def get_duration_s(mp3: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


# ----- ad detection + chapters -----

def clean_title(s: str) -> str:
    # ABS clients (Plappa in particular) can't render certain chars in chapter
    # titles. Keep it boring ASCII.
    return s.replace("|", " / ").replace(":", " -")


def detect_ad_blocks(entries: list, patterns: list, merge_window_s: int, block_min_len_s: int) -> list:
    raw = []
    for start, _end, text in entries:
        for pat, label in patterns:
            if re.search(pat, text, re.I):
                raw.append({"start": start, "label": label})
                break

    blocks = []
    for a in raw:
        if blocks and a["start"] - blocks[-1]["end"] < merge_window_s:
            blocks[-1]["end"] = a["start"] + block_min_len_s
            blocks[-1]["labels"].append(a["label"])
        else:
            blocks.append({
                "start": a["start"],
                "end": a["start"] + block_min_len_s,
                "labels": [a["label"]],
            })
    return blocks


def build_chapters(blocks: list, duration_s: float, marker_prefix: str = "AD") -> list:
    """Returns list of (start, end, title). marker_prefix prefixes ad/ID labels."""
    chapters = []
    cursor = 0.0
    for b in blocks:
        if b["start"] > cursor + 5:
            chapters.append((cursor, b["start"], f"Content {len(chapters) + 1}"))
        labels = " / ".join(dict.fromkeys(b["labels"]))
        chapters.append((b["start"], b["end"], clean_title(f"{marker_prefix} - {labels}")))
        cursor = b["end"]
    if cursor < duration_s:
        chapters.append((cursor, duration_s, f"Content {len(chapters) + 1}"))
    return chapters


# ----- transcript cache (rotate to last N per category) -----

TRANSCRIPT_CACHE_DIR = os.path.join(ROOT, "transcripts")


def cache_transcript(srt_src: str, category_subfolder: str, basename_no_ext: str,
                     keep_per_category: int) -> str:
    """Copy SRT into ~/.rollins-sync/transcripts/<category>/<basename>.srt
    and prune to keep only newest N. Returns the cached path."""
    dest_dir = os.path.join(TRANSCRIPT_CACHE_DIR, category_subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, basename_no_ext + ".srt")
    shutil.copy2(srt_src, dest)
    # rotate by mtime, keep newest N
    files = sorted(
        (os.path.join(dest_dir, f) for f in os.listdir(dest_dir) if f.endswith(".srt")),
        key=os.path.getmtime, reverse=True,
    )
    for old in files[keep_per_category:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dest


def find_cached_transcript(category_subfolder: str, basename_no_ext: str) -> str | None:
    p = os.path.join(TRANSCRIPT_CACHE_DIR, category_subfolder, basename_no_ext + ".srt")
    return p if os.path.exists(p) else None


def write_chapter_meta(chapters: list, path: str) -> None:
    with open(path, "w") as f:
        f.write(";FFMETADATA1\n")
        for start, end, title in chapters:
            f.write("\n[CHAPTER]\nTIMEBASE=1/1000\n")
            f.write(f"START={int(start * 1000)}\nEND={int(end * 1000)}\n")
            f.write(f"title={title}\n")


def inject_chapters(in_mp3: str, meta: str, out_mp3: str) -> None:
    # Re-encode to 128k CBR. Naive players (Absorb, others) seek by
    # byte-offset using avg-bitrate × time and ignore the Xing TOC, which
    # causes chapter-tap to land on the wrong audio in VBR sources.
    # CBR makes byte-offset and time-offset equivalent so seek lands true.
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", in_mp3, "-i", meta,
         "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
         "-c:a", "libmp3lame", "-b:a", "128k",
         "-minrate", "128k", "-maxrate", "128k",
         "-id3v2_version", "3",
         out_mp3],
        check=True,
    )


# ----- remote upload + ABS refresh -----

def rsync_to_seedbox(local_path: str, ssh_host: str, remote_root: str, subfolder: str) -> str:
    """Returns the remote path written."""
    # Ensure remote dir exists
    subprocess.run(
        ["ssh", ssh_host, f"mkdir -p {remote_root}/{subfolder}"],
        check=True,
    )
    remote_path = f"{ssh_host}:{remote_root}/{subfolder}/{os.path.basename(local_path)}"
    subprocess.run(["rsync", "-a", local_path, remote_path], check=True)
    return remote_path


def abs_login(cfg: dict) -> str:
    body = json.dumps({
        "username": cfg["username"],
        "password": cfg["password"],
    }).encode()
    req = urllib.request.Request(
        cfg["url"] + "/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    return (d.get("user") or {}).get("token") or d.get("token") or ""


def abs_find_episode_id(cfg: dict, token: str, podcast_item_id: str, file_basename: str) -> str | None:
    """Find ABS episode id matching the file basename (e.g. for delete-and-rediscover)."""
    req = urllib.request.Request(
        f"{cfg['url']}/api/items/{podcast_item_id}?expanded=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    item = json.loads(urllib.request.urlopen(req, timeout=15).read())
    for ep in item.get("media", {}).get("episodes", []):
        af = ep.get("audioFile", {}) or {}
        path = af.get("metadata", {}).get("path", "") or ""
        if os.path.basename(path) == file_basename:
            return ep.get("id")
    return None


def abs_refresh_episode(cfg: dict, podcast_item_id: str, file_basename: str) -> None:
    """Delete the episode entry then trigger library scan so ABS re-reads file
    metadata (chapters). Safe when no listening progress has been made."""
    if not podcast_item_id:
        log("  ABS refresh: no podcast_item_id for this category — skipping")
        return
    try:
        token = abs_login(cfg)
        if not token:
            log("  ABS login: empty token")
            return
        ep_id = abs_find_episode_id(cfg, token, podcast_item_id, file_basename)
        if ep_id:
            req = urllib.request.Request(
                f"{cfg['url']}/api/podcasts/{podcast_item_id}/episode/{ep_id}?hard=0",
                method="DELETE",
                headers={"Authorization": f"Bearer {token}"},
            )
            urllib.request.urlopen(req, timeout=15).read()
            log("  ABS: deleted old episode entry")
        req = urllib.request.Request(
            f"{cfg['url']}/api/libraries/{cfg['library_id']}/scan?force=1",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib.request.urlopen(req, timeout=15).read()
        log("  ABS: library scan triggered")
    except Exception as e:
        log(f"  ABS refresh failed: {e}")


# ----- per-item flow -----

def process_item(item: dict, cfg: dict, state: dict) -> None:
    log(f"--- {item['title']!r} [{item['category_match']}]")
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        zip_path = os.path.join(tmp, "ep.zip")
        log("  download mediafire zip")
        download_zip(item["mediafire_url"], zip_path, cfg["user_agent"])

        mp3_path = extract_single_mp3(zip_path, tmp)
        mp3_basename = os.path.basename(mp3_path)
        log(f"  extracted: {mp3_basename}  ({os.path.getsize(mp3_path):,} bytes)")

        # Per-category settings (patterns, marker style, ID/AD length).
        subfolder = item["target_subfolder"]
        cat_settings = cfg.get("category_settings", {}).get(subfolder)
        if not cat_settings:
            # Backwards-compat fallback: use old top-level KCRW config.
            cat_settings = {
                "patterns": cfg.get("ad_patterns", []),
                "marker_prefix": "AD",
                "merge_window_s": cfg.get("ad_merge_window_s", 120),
                "block_len_s": cfg.get("ad_block_min_len_s", 60),
            }
        log(f"  using category settings for {subfolder!r}: "
            f"prefix={cat_settings['marker_prefix']} merge={cat_settings['merge_window_s']}s "
            f"len={cat_settings['block_len_s']}s")

        # Transcript: try cache, then transcribe + cache.
        basename_no_ext = os.path.splitext(mp3_basename)[0]
        srt_path = os.path.join(tmp, "transcript.srt")
        cached = find_cached_transcript(subfolder, basename_no_ext)
        if cached:
            log(f"  reusing cached transcript: {cached}")
            shutil.copy2(cached, srt_path)
        else:
            wav_path = os.path.join(tmp, "audio.wav")
            log("  ffmpeg -> 16kHz mono WAV")
            to_wav_16k(mp3_path, wav_path)

            # Per-category overrides for model + VAD (Iggy uses medium.en + silero
            # VAD to extract BBC promos buried under music beds; HIMH uses small.en
            # with no VAD since KCRW sponsor reads are clean voiceover).
            whisper_model = cat_settings.get("whisper_model", cfg["whisper_model"])
            vad_model = cat_settings.get("vad_model")
            vad_threshold = cat_settings.get("vad_threshold", 0.5)
            log(f"  whisper.cpp (model: {os.path.basename(whisper_model)}, "
                f"{cfg['whisper_threads']} threads"
                f"{', VAD on' if vad_model else ''})"
                f" — medium+VAD takes ~60 min/2hr; small no-VAD ~30 min")
            transcribe(
                wav_path, cfg["whisper_bin"], whisper_model,
                cfg["whisper_threads"], os.path.join(tmp, "transcript"),
                vad_model=vad_model, vad_threshold=vad_threshold,
            )
            os.remove(wav_path)   # free disk fast (~235 MB)
            # Cache + rotate to keep newest N per category
            keep_n = cfg.get("transcript_cache_keep_per_category", 5)
            cache_transcript(srt_path, subfolder, basename_no_ext, keep_n)
            log(f"  cached transcript (keep newest {keep_n} per category)")

        entries = parse_srt(srt_path)
        duration = get_duration_s(mp3_path)
        log(f"  transcript: {len(entries)} segments | duration: {duration / 60:.1f} min")

        blocks = detect_ad_blocks(
            entries, cat_settings["patterns"],
            cat_settings["merge_window_s"], cat_settings["block_len_s"],
        )
        log(f"  marker blocks detected: {len(blocks)}")

        chapters = build_chapters(blocks, duration, cat_settings["marker_prefix"])
        log(f"  chapters generated: {len(chapters)}")

        meta = os.path.join(tmp, "chapters.txt")
        write_chapter_meta(chapters, meta)
        chaptered = os.path.join(tmp, "chaptered.mp3")
        inject_chapters(mp3_path, meta, chaptered)
        # rename to original basename so file lands at canonical path
        final_local = os.path.join(tmp, mp3_basename)
        os.rename(chaptered, final_local)

        log("  rsync to seedbox")
        rsync_to_seedbox(
            final_local, cfg["ssh_host"],
            cfg["remote_media_root"], item["target_subfolder"],
        )

        log("  ABS: delete-and-rediscover so new chapters get read into episode db")
        podcast_id = (cat_settings or {}).get("abs_podcast_item_id")
        abs_refresh_episode(cfg["abs"], podcast_id, mp3_basename)

    state["downloaded_guids"].append(item["guid"])
    save_state(state)
    log("  done")


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    cfg = load_config()
    state = load_state()

    log("=== rollins-sync run start ===")
    if not cfg["abs"].get("password"):
        log("ABS password missing from config — fill in and rerun")
        return 1

    try:
        xml = fetch_rss(cfg["rss_url"], cfg["user_agent"])
        items = parse_rss(xml)
    except Exception as e:
        log(f"RSS fetch/parse failed: {e}")
        return 2

    log(f"rss: {len(items)} items")
    new = filter_new(items, state, cfg["categories"])
    log(f"new + watched-category: {len(new)}")

    for item in new:
        try:
            process_item(item, cfg, state)
        except subprocess.CalledProcessError as e:
            log(f"  FAILED subprocess: {e}")
        except Exception as e:
            log(f"  FAILED: {type(e).__name__}: {e}")

    log("=== rollins-sync run end ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
