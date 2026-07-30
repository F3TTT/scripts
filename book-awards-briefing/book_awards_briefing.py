#!/usr/bin/env python3
"""book-awards-briefing (WSL) — monthly audio briefing on newly-announced book awards.

Modeled on ../morning-briefing/briefing.py: same local-WSL / Task-Scheduler /
edge-tts / rsync-to-seedbox / Audiobookshelf pattern, published as its own
podcast ("Book-Awards") rather than folded into the daily briefing.

Pipeline:
  1. Invoke the local Claude Code CLI headlessly (claude --print, piped via
     stdin to dodge WSL->Windows-exe argv length limits) to check a fixed
     list of book awards for newly-announced longlist/shortlist/winner
     stages, pick one book per newly-announced stage against the reader's
     taste profile (books.md), and write the result as JSON.
     This step is intentionally scoped to WebSearch/Read/Write/Edit only —
     no Bash — so unattended, no-human-present execution never grants an
     LLM (which is reading untrusted web content) shell access.
  2. If nothing new: log and exit, no episode.
  3. If something new: build a narration script, synthesize with edge-tts,
     tag the mp3, rsync it to the seedbox under a dedicated podcast
     subfolder, and trigger an Audiobookshelf library scan.

State (~/.book-awards-briefing/state.json) tracks which stage-years have
already been covered per award, so re-runs don't repeat themselves. On a
brand new award (nothing in state yet), the same lookback window applies —
that's what makes the very first run a "backlog prime" automatically; no
separate backlog mode needed. Pass --lookback-months to force a wider
re-check (e.g. after clearing an award's state) or --lookback-months 999
combined with a fresh state.json to re-prime from scratch.

Config:  ~/.book-awards-briefing/config.json (created with defaults on first run)
State:   ~/.book-awards-briefing/state.json
Log:     ~/.book-awards-briefing/log/<date>.log

Designed for Windows Task Scheduler (monthly):
    wsl.exe -d Ubuntu-24.04 -- bash -lc 'python3 ~/.book-awards-briefing/book_awards_briefing.py'
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

# ----- paths -----

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".book-awards-briefing")
CONFIG = os.path.join(ROOT, "config.json")
STATE = os.path.join(ROOT, "state.json")
LOG_DIR = os.path.join(ROOT, "log")
WORK = os.path.join(ROOT, "work")

# Reuse the morning-briefing venv — edge-tts is the only dependency and it's
# already installed there; no need for a second copy.
EDGE_TTS_BIN = os.path.join(HOME, ".morning-briefing", "venv", "bin", "edge-tts")

BOOKS_MD = "/mnt/c/Users/ADMIN/OneDrive/Desktop/Entertainment/books.md"
ENTERTAINMENT_DIR = "/mnt/c/Users/ADMIN/OneDrive/Desktop/Entertainment"

DEFAULTS = {
    "claude_exe": "/mnt/c/Users/ADMIN/.local/bin/claude.exe",
    "lookback_months": 12,
    "tts_voice": "en-US-ChristopherNeural",
    # remote — placeholders; real values land in ~/.book-awards-briefing/config.json
    # (reuses the same seedbox/ABS account as morning-briefing, different subfolder)
    "ssh_host": "USER@SEEDBOX.example.com",
    "remote_media_root": "~/media/Podcasts",
    "remote_subfolder": "Book-Awards",
    "abs": {
        "url": "https://YOUR-ABS-HOST.example.com",
        "username": "YOUR_ABS_USERNAME",
        "password": "",
        "library_id": "YOUR_ABS_LIBRARY_UUID",
    },
    "awards": [
        {"name": "Booker Prize", "stages": "longlist, shortlist, winner"},
        {"name": "National Book Award (Fiction)", "stages": "longlist, shortlist, winner"},
        {"name": "Bollinger Everyman Wodehouse Prize (comic fiction)",
         "stages": "shortlist, winner (no longlist)"},
        {"name": "Edgar Awards / Mystery Writers of America (crime & mystery)",
         "stages": "shortlist (nominees), winner (no longlist)"},
        {"name": "Hugo Award (Best Novel)", "stages": "shortlist (finalists), winner (no longlist)"},
        {"name": "Nebula Award (Best Novel)", "stages": "shortlist (finalists), winner (no longlist)"},
        {"name": "PEN/Faulkner Award for Fiction",
         "stages": "shortlist (finalists), winner (no longlist)"},
        {"name": "Pulitzer Prize for Fiction",
         "stages": "winner (finalists announced simultaneously with winner; treat as one winner stage)"},
        {"name": "Yoto Carnegie Medal for Writing", "stages": "longlist, shortlist, winner"},
        {"name": "Nobel Prize in Literature",
         "stages": "winner only — SPECIAL CASE, see instructions"},
    ],
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
        cfg = json.load(f)
    # backfill any keys added to DEFAULTS after a config was first written
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


# ----- step 1: headless Claude check -----

def build_prompt(cfg: dict, lookback_months: int, results_path: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    awards_block = "\n".join(
        f"{i}. {a['name']} — stages: {a['stages']}"
        for i, a in enumerate(cfg["awards"], start=1)
    )
    return f"""You are running as an unattended monthly automation. No human is present —
do not ask questions, do not wait for confirmation, just complete the task and
write the required output files exactly as specified below. If something is
genuinely ambiguous, make a reasonable call and say so briefly in the "reason"
field rather than stopping.

TASK: Check the book awards listed below for newly-announced longlists/
shortlists/winners, and for each newly-announced list, recommend exactly one
book from that list based on the reader's taste profile.

TASTE PROFILE: Read {BOOKS_MD} for the reader's likes/dislikes/ratings before
picking anything. Weight picks toward: absurdist/comic fiction with substance,
wartime/postcolonial fiction with wit, sharp well-plotted prose, and
character-driven crime/noir. Avoid: bleak literary fiction, preachy/saccharine
tone, and generic thriller machinery.

STATE: Read {STATE} (a JSON file; if missing or unreadable, treat it as
{{"awards": {{}}}}). For each award below, its entry's "covered" list records
stage-year strings (e.g. "shortlist-2026") already reported. Only report a
stage-year if it is NOT already in "covered" for that award AND it was
announced within the last {lookback_months} months of today ({today}). If an
award is missing from state entirely, this is the first run for it — the same
{lookback_months}-month lookback window applies; do not dig up older history
than that window.

AWARDS TO CHECK (verify current facts via web search — don't rely solely on
prior knowledge, award branding/dates/sponsors shift year to year):
{awards_block}

Nobel Prize in Literature SPECIAL CASE: this is a single-author announcement,
not a list of books, and there is no public nominee list at all. When a new
laureate is announced, instead of "picking from a list," recommend one
specific book by that author as an entry point — pick their most acclaimed or
accessible work — and frame the "reason" as introducing the author and why
this particular book. Do not force a taste-fit if the laureate's work is a
poor match for the reader's profile — say so plainly in the reason instead of
overselling it.

FOR EACH genuinely new stage-year found (there may be zero, one, or several
across all awards — zero or one is the normal case most months):
- Pick exactly one book from that list (or, for Nobel, one book by the
  laureate).
- Write a "reason" (1-3 sentences) grounded in the reader's actual documented
  taste — cite what in their profile makes this pick fit, or say plainly if
  it's a stretch.
- Write a "summary" that is EXACTLY three sentences describing the book's
  premise/setup, without spoiling the ending.

OUTPUT CONTRACT (follow exactly):
1. Write the results — a JSON array, or an empty array [] if nothing new this
   run — to {results_path}. Each element:
   {{"award": str, "stage": "longlist"|"shortlist"|"winner", "year": int,
     "book_title": str, "author": str, "reason": str, "summary": str}}
2. Update {STATE}: for every stage-year you included in step 1's output, add
   its "stage-year" string to that award's "covered" list (create the award's
   entry if it's new). Preserve every pre-existing entry and every other
   award untouched. Write the full updated JSON back to the same path.
3. If and only if step 1's output array is non-empty, append one line per
   entry to a "## Award Picks" section at the end of {BOOKS_MD} (create that
   section if it doesn't exist yet) in the form:
   `- **{{book_title}}** — {{author}} ({{award}} {{stage}} {{year}})`
   Do not modify or remove anything else in that file.

Use only the WebSearch, Read, Write, and Edit tools. Do not run shell
commands, install anything, or access the network beyond web search.
"""


def run_claude_check(cfg: dict, prompt: str) -> bool:
    """Runs the headless Claude check. Returns True if the process completed
    (regardless of whether it found anything new — check the results file
    for that)."""
    cmd = [
        cfg["claude_exe"],
        "--print",
        "--output-format", "json",
        "--permission-mode", "default",
        "--allowedTools", "WebSearch,Read,Write,Edit",
        "--add-dir", WORK,
        "--add-dir", ENTERTAINMENT_DIR,
    ]
    log(f"  invoking claude headless: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        log("  claude check FAILED: timed out after 30 min")
        return False

    if proc.returncode != 0:
        log(f"  claude check FAILED: exit {proc.returncode}: {proc.stderr[:500]}")
        return False

    try:
        envelope = json.loads(proc.stdout)
        cost = envelope.get("total_cost_usd")
        is_error = envelope.get("is_error")
        log(f"  claude check completed: is_error={is_error} cost=${cost}")
        if is_error:
            log(f"  claude result: {str(envelope.get('result'))[:500]}")
    except json.JSONDecodeError:
        log(f"  claude check: non-JSON stdout (first 500 chars): {proc.stdout[:500]}")

    return True


# ----- step 2: narration + TTS + publish -----

def build_script(entries: list[dict]) -> str:
    date_str = datetime.now().strftime("%B %Y")
    lines = ["Good morning. This is your Book Awards briefing."]
    lines.append(f"Here's what's new as of {date_str}.")
    for e in entries:
        lines.append(
            f"{e['award']}'s {e['stage']} for {e['year']} has been announced. "
            f"My pick for you is \"{e['book_title']}\" by {e['author']}."
        )
        lines.append(e["reason"])
        lines.append(e["summary"])
    lines.append("That's your Book Awards briefing.")
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
         "-metadata", "artist=Book Awards Briefing",
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
    import urllib.request
    body = json.dumps({"username": cfg["username"], "password": cfg["password"]}).encode()
    req = urllib.request.Request(
        cfg["url"] + "/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    return (d.get("user") or {}).get("token") or d.get("token") or ""


def abs_scan(cfg: dict) -> None:
    import urllib.request
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback-months", type=int, default=None,
                     help="Override config's lookback_months (e.g. for a forced re-prime).")
    ap.add_argument("--dry-run", action="store_true",
                     help="Run the check and print what would be published, but skip TTS/rsync/ABS.")
    ap.add_argument("--publish-from", metavar="RESULTS_JSON",
                     help="Skip the (paid) headless check entirely and publish an episode "
                          "directly from an existing results JSON file — e.g. to retry "
                          "publishing after a TTS/rsync/ABS failure, or to render the audio "
                          "for a check that was run with --dry-run.")
    args = ap.parse_args()

    if args.publish_from:
        os.makedirs(LOG_DIR, exist_ok=True)
        cfg = load_config()
        log(f"=== book-awards-briefing publish-from {args.publish_from} ===")
        with open(args.publish_from) as f:
            entries = json.load(f)
        if not entries:
            log("  results file is empty — nothing to publish")
            return 0
        return _publish(cfg, entries)

    os.makedirs(WORK, exist_ok=True)
    cfg = load_config()
    lookback = args.lookback_months or cfg["lookback_months"]

    log("=== book-awards-briefing run start ===")
    if not args.dry_run and not cfg["abs"].get("password"):
        log("ABS password missing from config — fill in and rerun (or use --dry-run)")
        return 1

    date_tag = datetime.now().strftime("%Y-%m-%d")
    results_path = os.path.join(WORK, f"results-{date_tag}.json")
    if os.path.exists(results_path):
        os.remove(results_path)

    prompt = build_prompt(cfg, lookback, results_path)
    if not run_claude_check(cfg, prompt):
        log("=== book-awards-briefing run end (check failed) ===")
        return 1

    if not os.path.exists(results_path):
        log(f"  claude did not write {results_path} — treating as failure")
        log("=== book-awards-briefing run end (no results file) ===")
        return 1

    with open(results_path) as f:
        entries = json.load(f)

    if not entries:
        log("  no new award stages this run — no episode")
        log("=== book-awards-briefing run end (nothing new) ===")
        return 0

    log(f"  {len(entries)} new pick(s): " +
        ", ".join(f"{e['award']} {e['stage']} {e['year']}" for e in entries))

    if args.dry_run:
        script_text = build_script(entries)
        log("  --dry-run: skipping TTS/rsync/ABS. Script would be:")
        log(script_text)
        log("=== book-awards-briefing run end (dry-run) ===")
        return 0

    rc = _publish(cfg, entries)
    log("=== book-awards-briefing run end ===")
    return rc


def _publish(cfg: dict, entries: list[dict]) -> int:
    date_tag = datetime.now().strftime("%Y-%m-%d")
    script_text = build_script(entries)
    raw_mp3 = os.path.join(WORK, f"book-awards-raw-{date_tag}.mp3")
    final_mp3 = os.path.join(WORK, f"book-awards-{date_tag}.mp3")

    log("  synthesizing audio")
    synthesize(script_text, cfg["tts_voice"], raw_mp3)
    tag_mp3(raw_mp3, f"Book Awards - {date_tag}", final_mp3)
    os.remove(raw_mp3)

    log("  rsync to seedbox")
    rsync_to_seedbox(final_mp3, cfg["ssh_host"], cfg["remote_media_root"], cfg["remote_subfolder"])
    os.remove(final_mp3)

    abs_scan(cfg["abs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
