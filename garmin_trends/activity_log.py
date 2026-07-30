"""Print recent activities (date, type, duration, distance) from the cached
bulk pull, so activity-mix shifts (e.g. walking vs running vs strength) are
easy to eyeball. Run pull_report.py first (or with --refresh) to update the
underlying data/bulk.json cache this reads from.

Usage:
    venv/bin/python activity_log.py [--last 30]
"""
import argparse
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BULK_CACHE = BASE_DIR / "data" / "bulk.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=30, help="Number of most recent activities to show")
    args = parser.parse_args()

    if not BULK_CACHE.exists():
        raise SystemExit(f"{BULK_CACHE} not found - run pull_report.py first to populate the cache.")

    bulk = json.loads(BULK_CACHE.read_text())
    acts = bulk.get("activities", [])
    if not isinstance(acts, list):
        raise SystemExit(f"No usable activity data in cache: {acts}")

    acts_sorted = sorted(acts, key=lambda a: a.get("startTimeLocal", ""))
    for a in acts_sorted[-args.last:]:
        d = (a.get("startTimeLocal") or "?")[:10]
        typ = (a.get("activityType") or {}).get("typeKey", "?")
        dur_min = (a.get("duration") or 0) / 60
        dist_km = (a.get("distance") or 0) / 1000
        print(f"{d}  {typ:20s}  {dur_min:6.1f} min  {dist_km:5.2f} km")


if __name__ == "__main__":
    main()
