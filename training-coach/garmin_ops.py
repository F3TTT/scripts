"""Garmin side of training-coach. Runs in the garmin_trends WSL venv.

Reads a JSON list of operations on stdin, runs them with one login, and writes a
JSON list of results to stdout. coach.py (Windows Python) drives this.

Operations:
  {"op": "activities", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
  {"op": "upload", "workout": {...}}              -> {"workoutId": N}
  {"op": "schedule", "workout_id": N, "date": "YYYY-MM-DD"} -> {"scheduleId": N}
  {"op": "unschedule", "schedule_id": N}
  {"op": "delete", "workout_id": N}
  {"op": "get_workout", "workout_id": N}
"""
import contextlib
import json
import sys

# Always the main checkout: the .env, cached tokens and venv live only there.
sys.path.insert(0, "/mnt/c/scripts/garmin_trends")
from garmin_client import get_client  # noqa: E402


def _schedule_id(resp):
    for key in ("workoutScheduleId", "scheduleId", "id"):
        if isinstance(resp, dict) and resp.get(key):
            return resp[key]
    raise RuntimeError(f"no schedule id in response: {resp}")


def run(client, op):
    kind = op["op"]
    if kind == "activities":
        acts = client.get_activities_by_date(op["start"], op["end"])
        return [{"date": a["startTimeLocal"][:10], "type": a["activityType"]["typeKey"],
                 "seconds": a.get("duration") or 0, "name": a.get("activityName")} for a in acts]
    if kind == "upload":
        return {"workoutId": client.upload_workout(op["workout"])["workoutId"]}
    if kind == "schedule":
        return {"scheduleId": _schedule_id(client.schedule_workout(op["workout_id"], op["date"]))}
    if kind == "unschedule":
        client.unschedule_workout(op["schedule_id"])
        return {}
    if kind == "delete":
        client.delete_workout(op["workout_id"])
        return {}
    if kind == "get_workout":
        return client.get_workout_by_id(op["workout_id"])
    raise ValueError(f"unknown op {kind}")


def main():
    ops = json.load(sys.stdin)
    out = sys.stdout
    results = []
    # The login path prints status lines; keep stdout clean for the JSON reply.
    with contextlib.redirect_stdout(sys.stderr):
        client = get_client()
        for op in ops:
            try:
                results.append({"ok": True, "result": run(client, op)})
            except Exception as exc:  # report per-op so one failure doesn't hide the rest
                results.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    json.dump(results, out)


if __name__ == "__main__":
    main()
