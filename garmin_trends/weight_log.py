"""Body-weight trend from the cached Garmin weigh-in pull.

pull_report.py writes data/weight.json (Garmin's get_weigh_ins response) on
each run; this prints the latest reading and monthly averages from that cache
without logging in again. Weights are shown in lb (Garmin stores grams).

Usage:
    venv/bin/python weight_log.py [--months 12]
"""
import argparse
import json
from datetime import date
from pathlib import Path
from statistics import mean

BASE_DIR = Path(__file__).resolve().parent
WEIGHT_CACHE = BASE_DIR / "data" / "weight.json"
GRAMS_PER_LB = 453.592


def load_readings(weigh_ins: dict) -> list[dict]:
    """Flatten Garmin's dailyWeightSummaries into one reading per day, oldest first.

    Each reading: {"date": date, "lb": float, "body_fat": float|None, "bmi": float|None}.
    Days with several weigh-ins use the first entry, which is what Garmin's own summary shows.
    """
    readings = []
    for summary in (weigh_ins or {}).get("dailyWeightSummaries") or []:
        metrics = (summary.get("allWeightMetrics") or [None])[0] or summary.get("latestWeight") or {}
        grams = metrics.get("weight")
        if not grams:
            continue
        readings.append({
            "date": date.fromisoformat(summary["summaryDate"]),
            "lb": grams / GRAMS_PER_LB,
            "body_fat": metrics.get("bodyFat"),
            "bmi": metrics.get("bmi"),
        })
    return sorted(readings, key=lambda r: r["date"])


def monthly_averages(readings: list[dict]) -> list[tuple[str, float, float | None, int]]:
    """(YYYY-MM, avg lb, avg body-fat % or None, number of weigh-ins), oldest first."""
    months: dict[str, list[dict]] = {}
    for r in readings:
        months.setdefault(r["date"].strftime("%Y-%m"), []).append(r)
    out = []
    for key in sorted(months):
        rows = months[key]
        fats = [r["body_fat"] for r in rows if r["body_fat"]]
        out.append((key, mean(r["lb"] for r in rows), mean(fats) if fats else None, len(rows)))
    return out


def print_weight_summary(weigh_ins: dict, months: int = 12) -> None:
    readings = load_readings(weigh_ins)
    if not readings:
        print("  No weigh-ins found (is the scale syncing to Garmin Connect?).")
        return

    latest = readings[-1]
    bmi = f", BMI {latest['bmi']:.1f}" if latest["bmi"] else ""
    print(f"  Latest: {latest['lb']:.1f} lb on {latest['date']}{bmi}")

    recent = [r["lb"] for r in readings if (latest["date"] - r["date"]).days < 30]
    prior = [r["lb"] for r in readings if 30 <= (latest["date"] - r["date"]).days < 90]
    if recent and prior:
        delta = mean(recent) - mean(prior)
        print(f"  Last 30 days avg {mean(recent):.1f} lb vs prior 60 days avg {mean(prior):.1f} lb  [{delta:+.1f} lb]")

    print(f"  Monthly averages (last {months}):")
    for key, lb, fat, n in monthly_averages(readings)[-months:]:
        fat_txt = f"  body fat {fat:.1f}%" if fat else ""
        print(f"    {key}  {lb:6.1f} lb{fat_txt}  ({n} weigh-ins)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=12, help="Number of most recent months to show")
    args = parser.parse_args()

    if not WEIGHT_CACHE.exists():
        raise SystemExit(f"{WEIGHT_CACHE} not found - run pull_report.py first to populate the cache.")
    print_weight_summary(json.loads(WEIGHT_CACHE.read_text()), args.months)


if __name__ == "__main__":
    main()
