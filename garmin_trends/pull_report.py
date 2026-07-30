"""Pull Garmin Connect data and print a trend/insights report.

Usage:
    venv/bin/python pull_report.py [--days 84] [--refresh]

Data is cached per-day under data/daily/ so re-runs only hit the API for
new days (today's record is always refetched since it's still accumulating).
"""
import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

from garmin_client import get_client

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "data" / "daily"
BULK_CACHE = BASE_DIR / "data" / "bulk.json"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def dig(d, *path, default=None):
    """Safely walk a nested dict/list; returns `default` if anything's missing."""
    cur = d
    for key in path:
        if cur is None:
            return default
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return default
    return cur if cur is not None else default


def safe_call(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:
        return {"error": str(exc)}


PER_DAY_CALLS = {
    "stats": lambda c, d: c.get_stats(d),
    "sleep": lambda c, d: c.get_sleep_data(d),
    "hrv": lambda c, d: c.get_hrv_data(d),
    "readiness": lambda c, d: c.get_training_readiness(d),
    "training_status": lambda c, d: c.get_training_status(d),
}


def fetch_day(client, day: date, force: bool = False) -> dict:
    cache_file = CACHE_DIR / f"{day.isoformat()}.json"
    if cache_file.exists() and not force and day != date.today():
        return json.loads(cache_file.read_text())

    record = {"date": day.isoformat()}
    for key, fn in PER_DAY_CALLS.items():
        record[key] = safe_call(fn, client, day.isoformat())
        time.sleep(0.2)

    cache_file.write_text(json.dumps(record, default=str))
    return record


def fetch_range(client, start: date, end: date, refresh: bool) -> list[dict]:
    days = []
    d = start
    while d <= end:
        days.append(fetch_day(client, d, force=refresh))
        d += timedelta(days=1)
    return days


def fetch_bulk(client, start: date, end: date) -> dict:
    s, e = start.isoformat(), end.isoformat()
    bulk = {
        "activities": safe_call(client.get_activities_by_date, s, e),
        "body_battery": safe_call(client.get_body_battery, s, e),
        "endurance_score": safe_call(client.get_endurance_score, s, e),
        "race_predictions": safe_call(client.get_race_predictions, s, e),
    }
    BULK_CACHE.write_text(json.dumps(bulk, default=str))
    return bulk


# ---- extraction helpers (Garmin's JSON shape varies a bit by device/account) ----

def extract_rhr(day_record):
    return dig(day_record, "stats", "restingHeartRate")


def extract_stress(day_record):
    return dig(day_record, "stats", "averageStressLevel")


def extract_body_battery_low(day_record):
    return dig(day_record, "stats", "bodyBatteryLowestValue")


def extract_sleep_seconds(day_record):
    return dig(day_record, "sleep", "dailySleepDTO", "sleepTimeSeconds")


def extract_sleep_score(day_record):
    return dig(day_record, "sleep", "dailySleepDTO", "sleepScores", "overall", "value")


def extract_hrv(day_record):
    return dig(day_record, "hrv", "hrvSummary", "lastNightAvg")


def extract_readiness(day_record):
    readiness = day_record.get("readiness")
    if isinstance(readiness, list) and readiness:
        return dig(readiness[0], "score")
    return None


def extract_vo2max(day_record):
    ts = day_record.get("training_status")
    if not isinstance(ts, dict):
        return None
    for device_data in dig(ts, "mostRecentVO2Max", default={}).values() if isinstance(dig(ts, "mostRecentVO2Max"), dict) else []:
        val = dig(device_data, "vo2MaxPreciseValue") or dig(device_data, "vo2MaxValue")
        if val:
            return val
    return None


def week_bucket(d: date, today: date) -> int:
    """0 = current week (Mon-start), 1 = last week, etc."""
    return (today.toordinal() - d.toordinal() + today.weekday()) // 7


def build_weekly_series(days: list[dict], extractor, today: date) -> dict[int, list]:
    buckets: dict[int, list] = {}
    for rec in days:
        d = datetime.strptime(rec["date"], "%Y-%m-%d").date()
        val = extractor(rec)
        if val is None:
            continue
        wk = week_bucket(d, today)
        buckets.setdefault(wk, []).append(val)
    return buckets


def trend_line(label, buckets: dict[int, list], unit="", higher_is_better=True, precision=1):
    weeks = sorted(k for k in buckets if k >= 1)  # exclude current partial week
    if len(weeks) < 4:
        print(f"  {label}: not enough data yet")
        return
    weekly_avg = {w: mean(buckets[w]) for w in weeks}
    recent = [weekly_avg[w] for w in weeks if w <= 2]
    baseline_weeks = [w for w in weeks if w > 2]
    if not baseline_weeks or not recent:
        print(f"  {label}: not enough data yet")
        return
    baseline = mean(weekly_avg[w] for w in baseline_weeks)
    recent_avg = mean(recent)
    delta = recent_avg - baseline
    pct = (delta / baseline * 100) if baseline else 0
    arrow = "-"
    if abs(pct) >= 3:
        arrow = ("UP" if delta > 0 else "DOWN")
    flag = ""
    if abs(pct) >= 8:
        good = (delta > 0) == higher_is_better
        flag = "  <-- notable, looks GOOD" if good else "  <-- notable, worth watching"
    print(
        f"  {label}: last 2wk avg {recent_avg:.{precision}f}{unit} vs prior baseline "
        f"{baseline:.{precision}f}{unit}  [{arrow} {pct:+.0f}%]{flag}"
    )


def summarize_activities(activities: list[dict], today: date):
    if not isinstance(activities, list):
        print("  Activity data unavailable.")
        return
    buckets: dict[int, list] = {}
    for act in activities:
        start_str = act.get("startTimeLocal") or act.get("startTimeGMT")
        if not start_str:
            continue
        d = datetime.strptime(start_str[:10], "%Y-%m-%d").date()
        wk = week_bucket(d, today)
        buckets.setdefault(wk, []).append(act)

    weeks = sorted(k for k in buckets if k >= 1)
    if len(weeks) < 4:
        print("  Not enough activity history yet")
        return

    def week_minutes(wk):
        return sum((a.get("duration") or 0) for a in buckets.get(wk, [])) / 60

    def week_count(wk):
        return len(buckets.get(wk, []))

    recent_weeks = [w for w in weeks if w <= 2]
    baseline_weeks = [w for w in weeks if w > 2]
    recent_min = mean(week_minutes(w) for w in recent_weeks)
    baseline_min = mean(week_minutes(w) for w in baseline_weeks)
    recent_cnt = mean(week_count(w) for w in recent_weeks)
    baseline_cnt = mean(week_count(w) for w in baseline_weeks)
    pct = ((recent_min - baseline_min) / baseline_min * 100) if baseline_min else 0
    flag = ""
    if pct >= 30:
        flag = "  <-- ramping volume fast, watch recovery metrics"
    elif pct <= -30:
        flag = "  <-- volume down sharply vs your recent baseline"
    print(
        f"  Weekly training time: last 2wk avg {recent_min:.0f} min "
        f"({recent_cnt:.1f} sessions) vs baseline {baseline_min:.0f} min "
        f"({baseline_cnt:.1f} sessions)  [{pct:+.0f}%]{flag}"
    )

    hrs = [a.get("averageHR") for a in [x for wk in weeks for x in buckets.get(wk, [])] if a.get("averageHR")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=84, help="Lookback window in days (default 84 = 12 weeks)")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and refetch every day")
    args = parser.parse_args()

    today = date.today()
    start = today - timedelta(days=args.days)

    print(f"Logging in to Garmin Connect...")
    client = get_client()
    print(f"Fetching {args.days} days of data (this can take a few minutes on first run)...")

    days = fetch_range(client, start, today, args.refresh)
    bulk = fetch_bulk(client, start, today)

    print()
    print("=" * 60)
    print(f"GARMIN TRAINING TRENDS  ({start} to {today})")
    print("=" * 60)

    print("\n[Volume]")
    summarize_activities(bulk.get("activities", []), today)

    print("\n[Recovery]")
    trend_line("Resting heart rate", build_weekly_series(days, extract_rhr, today), " bpm", higher_is_better=False)
    trend_line("Overnight HRV", build_weekly_series(days, extract_hrv, today), " ms", higher_is_better=True)
    trend_line("Sleep duration", build_weekly_series(days, lambda r: (extract_sleep_seconds(r) or 0) / 3600 or None, today), " hrs", higher_is_better=True)
    trend_line("Sleep score", build_weekly_series(days, extract_sleep_score, today), "", higher_is_better=True)
    trend_line("Body battery (daily low)", build_weekly_series(days, extract_body_battery_low, today), "", higher_is_better=True)
    trend_line("Training readiness", build_weekly_series(days, extract_readiness, today), "", higher_is_better=True)
    trend_line("Avg stress", build_weekly_series(days, extract_stress, today), "", higher_is_better=False)

    print("\n[Fitness]")
    trend_line("VO2max (est.)", build_weekly_series(days, extract_vo2max, today), "", higher_is_better=True)

    print()
    print("Raw daily JSON cached under data/daily/*.json if any of the above")
    print("looks off and needs re-parsing (Garmin's field names vary by device).")


if __name__ == "__main__":
    main()
