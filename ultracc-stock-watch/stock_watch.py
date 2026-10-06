#!/usr/bin/env python3
"""Watch the Ultra.cc store for seedbox plans coming back in stock, and alert on Discord.

Runs on the seedbox from cron (every 10 minutes). Each store category page lists plans as
"<Name> / N Available / <size>TB / <price>". The script records the counts in state.json
and posts to Discord when a watched plan goes from 0 to >0 available.

It also alerts when the page can't be read or parsed for several runs in a row, so a store
redesign can't make it fail silently (the Trakt discovery job failed silently for 2 months).

Config (~/ultracc-stock-watch/config.json, chmod 600, not in git):
  {
    "discord_webhook": "https://discord.com/api/webhooks/...",
    "categories": ["metaliux-canada"],
    "min_tb": 6,                 # only plans bigger than the current 4TB plan
    "fail_alert_after": 6        # consecutive failed runs before alerting (~1h at */10)
  }

Usage: stock_watch.py [--test]   (--test posts the current status to Discord once)
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state.json")
LOG_PATH = os.path.join(ROOT, "stock_watch.log")
STORE = "https://my.ultra.cc/index.php?rp=/store/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def log(msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")
    print(line)


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch(category):
    req = urllib.request.Request(STORE + category, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def parse_plans(html, category):
    """Return {name: {"available": int, "tb": float|None, "price": str|None, "url": str}}."""
    text = re.sub(r"<[^>]+>", "\n", html)
    lines = [l.strip() for l in text.replace("&nbsp;", " ").splitlines()]
    lines = [l for l in lines if l]
    plans = {}
    for i, line in enumerate(lines):
        m = re.fullmatch(r"(\d+) Available", line)
        if not m or i == 0:
            continue
        name = lines[i - 1]
        tb = None
        size = re.fullmatch(r"([\d.]+)\s*TB", lines[i + 1]) if i + 1 < len(lines) else None
        if size:
            tb = float(size.group(1))
        price = next((l for l in lines[i + 1:i + 25] if re.search(r"\d\S*\s*(EUR|USD|GBP)$", l)), None)
        plans[name] = {
            "available": int(m.group(1)),
            "tb": tb,
            "price": price,
            "url": f"{STORE}{category}/{name.lower()}",
        }
    return plans


def discord(webhook, content):
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(webhook, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    test = "--test" in sys.argv
    cfg = load(CONFIG_PATH, {})
    webhook = cfg.get("discord_webhook")
    if not webhook:
        log("missing discord_webhook in config.json")
        sys.exit(1)
    min_tb = cfg.get("min_tb", 6)
    state = load(STATE_PATH, {"counts": {}, "fail_streak": 0, "fail_alerted": False})

    current, errors = {}, []
    for cat in cfg.get("categories", ["metaliux-canada"]):
        try:
            plans = parse_plans(fetch(cat), cat)
            if not plans:
                raise ValueError("no plans parsed (page layout changed?)")
            for name, p in plans.items():
                current[f"{cat}/{name}"] = p
        except Exception as e:
            errors.append(f"{cat}: {e}")

    if errors:
        state["fail_streak"] = state.get("fail_streak", 0) + 1
        log(f"FAIL ({state['fail_streak']} in a row): {'; '.join(errors)}")
        if state["fail_streak"] >= cfg.get("fail_alert_after", 6) and not state.get("fail_alerted"):
            discord(webhook, f"⚠️ Ultra.cc stock watcher can't read the store ({state['fail_streak']} runs in a row): "
                             f"{'; '.join(errors)}. Check it manually: {STORE}{cfg.get('categories', ['metaliux-canada'])[0]}")
            state["fail_alerted"] = True
    else:
        if state.get("fail_alerted"):
            discord(webhook, "✅ Ultra.cc stock watcher can read the store again.")
        state["fail_streak"], state["fail_alerted"] = 0, False

    watched = {k: p for k, p in current.items() if p["tb"] is not None and p["tb"] >= min_tb}
    newly = [(k, p) for k, p in watched.items()
             if p["available"] > 0 and state["counts"].get(k, 0) == 0]
    summary = ", ".join(f"{k.split('/')[-1]} {p['tb']:g}TB: {p['available']}" for k, p in sorted(watched.items(), key=lambda x: x[1]["tb"]))
    log(f"watched: {summary or 'none parsed'}")

    if newly:
        lines = [f"🟢 **Ultra.cc plan back in stock**, order fast:"]
        for k, p in sorted(newly, key=lambda x: x[1]["tb"]):
            lines.append(f"• **{k.split('/')[-1]}** {p['tb']:g}TB: {p['available']} available, {p['price'] or 'price ?'} → {p['url']}")
        discord(webhook, "\n".join(lines))
        log(f"ALERT sent for {[k for k, _ in newly]}")
    if test:
        discord(webhook, f"🧪 Ultra.cc stock watcher is live. Checking every 10 min for plans ≥{min_tb:g}TB. Right now: {summary}")
        log("test message sent")

    for k, p in current.items():
        state["counts"][k] = p["available"]
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


if __name__ == "__main__":
    main()
