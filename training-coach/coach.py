"""training-coach: schedules the C25K + strength week on the Fenix and the work calendar.

  python coach.py init --start 2026-10-12 --week 1     # first Monday and C25K week
  python coach.py plan-week [--monday YYYY-MM-DD] [--dry-run] [--replan]
  python coach.py knee N [--date YYYY-MM-DD]           # knee pain 0-10; >3 repeats the week
  python coach.py status

Windows Python (calendar invites need Credential Manager); the Garmin calls go
through garmin_ops.py in the garmin_trends WSL venv. State lives in
~/.training-coach/state.json.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import program

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TRAINING_COACH_HOME", Path.home() / ".training-coach"))
STATE = DATA_DIR / "state.json"
LOG = DATA_DIR / "coach.log"
INVITES = Path(r"C:\scripts\calendar-invites\invites.py")
WSL_PY = "/mnt/c/scripts/garmin_trends/venv/bin/python"
RUN_TYPES = {"running", "treadmill_running", "trail_running", "track_running", "indoor_running"}
REMINDER_TIME = "18:00"


def log(msg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")
    tmp.replace(STATE)


def wsl_path(p):
    p = str(p)
    return f"/mnt/{p[0].lower()}{p[2:]}".replace("\\", "/")


def garmin(ops):
    """Run Garmin operations in WSL; raise if any failed."""
    if not ops:
        return []
    proc = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
         f"{WSL_PY} {wsl_path(HERE / 'garmin_ops.py')}"],
        input=json.dumps(ops), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"garmin_ops failed ({proc.returncode}): {proc.stderr.strip()[-2000:]}")
    results = json.loads(proc.stdout)
    errors = [f"{op['op']}: {r['error']}" for op, r in zip(ops, results) if not r["ok"]]
    if errors:
        raise SystemExit("Garmin errors:\n" + "\n".join(errors))
    return [r["result"] for r in results]


def invite(*args):
    proc = subprocess.run([sys.executable, str(INVITES), *args], capture_output=True, text=True,
                          cwd=INVITES.parent, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"invites.py {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    out = proc.stdout.strip()
    m = re.match(r"(?:sent|updated) (\S+):", out)
    return m.group(1).rstrip(":") if m else None


def ensure_workouts(state, specs, dry_run):
    """Upload any workout definition that's new or changed; return {name: id}."""
    known = state.setdefault("workouts", {})
    ids, uploads = {}, []
    for spec in specs:
        w = program.build_workout(spec)
        h = hashlib.sha1(json.dumps(w, sort_keys=True).encode()).hexdigest()[:12]
        cur = known.get(w["workoutName"])
        if cur and cur["hash"] == h:
            ids[w["workoutName"]] = cur["id"]
        elif w["workoutName"] not in [u[0] for u in uploads]:
            uploads.append((w["workoutName"], h, w))
    if dry_run:
        for name, _, _ in uploads:
            ids[name] = "(new)"
        return ids
    results = garmin([{"op": "upload", "workout": w} for _, _, w in uploads])
    for (name, h, _), r in zip(uploads, results):
        if name in known:
            state.setdefault("retired_workouts", []).append(known[name]["id"])
        known[name] = {"id": r["workoutId"], "hash": h}
        ids[name] = r["workoutId"]
        log(f"uploaded workout {name} -> {r['workoutId']}")
    return ids


def retire_workouts(state):
    """Delete replaced workout definitions that no planned week still schedules."""
    in_use = {s["workout_id"] for w in state.get("planned", {}).values() for s in w.get("schedules", [])}
    gone = [i for i in state.get("retired_workouts", []) if i not in in_use]
    if gone:
        garmin([{"op": "delete", "workout_id": i} for i in gone])
        log(f"deleted replaced workouts {gone}")
    state["retired_workouts"] = [i for i in state.get("retired_workouts", []) if i in in_use]
    save_state(state)


def upcoming_monday(today):
    return today + dt.timedelta(days=(7 - today.weekday()) or 7)


def choose_week(state, monday):
    """C25K week for the week starting monday, by the weekly rule. Returns (week, note, record)."""
    planned = state.get("planned", {})
    prev = (monday - dt.timedelta(days=7)).isoformat()
    if prev not in planned:
        earlier = sorted(k for k in planned if k < monday.isoformat())
        if not earlier:
            return state["start_week"], "first week", None
        week = planned[earlier[-1]]["c25k_week"]
        return week, f"no plan for {prev}; repeating week {week}", None
    prev_week = planned[prev]["c25k_week"]
    start, end = prev, (monday - dt.timedelta(days=1)).isoformat()
    acts = garmin([{"op": "activities", "start": start, "end": end}])[0]
    shortest = min(program.c25k_minutes(prev_week, d) for d in (1, 2, 3)) * 60
    runs = [a for a in acts if a["type"] in RUN_TYPES and a["seconds"] >= 0.75 * shortest]
    knee = [v for d, v in state.get("knee", {}).items() if start <= d <= end]
    knee_max = max(knee) if knee else None
    week, outcome = program.next_week(prev_week, len(runs), knee_max)
    record = {"week_start": prev, "c25k_week": prev_week, "runs_done": len(runs),
              "knee_max": knee_max, "outcome": outcome}
    return week, outcome, record


def cmd_init(a):
    state = load_state()
    start = dt.date.fromisoformat(a.start)
    if start.weekday() != 0:
        raise SystemExit("--start must be a Monday")
    if state.get("planned") and not a.force:
        raise SystemExit("already initialised with planned weeks; use --force to reset start")
    state.update({"start_date": a.start, "start_week": a.week})
    save_state(state)
    log(f"init: start {a.start}, C25K week {a.week}")


def cmd_plan_week(a):
    state = load_state()
    if "start_date" not in state:
        raise SystemExit("run `coach.py init` first")
    start = dt.date.fromisoformat(state["start_date"])
    monday = dt.date.fromisoformat(a.monday) if a.monday else max(start, upcoming_monday(dt.date.today()))
    key = monday.isoformat()
    planned = state.setdefault("planned", {})
    if key in planned and not a.replan:
        print(f"week of {key} already planned (C25K week {planned[key]['c25k_week']}); --replan to redo")
        return

    week, note, record = choose_week(state, monday)
    days = program.week_days(monday, week)
    specs = []
    for d in days:
        for s in d["workouts"]:
            if s not in specs:
                specs.append(s)

    print(f"Week of {key}: C25K week {week} ({note})")
    for d in days:
        names = ", ".join(program.build_workout(s)["workoutName"] for s in d["workouts"])
        print(f"  {d['date']:%a %m-%d}  {program.BLOCK_TIME} {d['block_minutes']:>3} min  {d['summary']:<42} watch: {names}")
    if a.dry_run:
        ensure_workouts(state, specs, dry_run=True)
        if week == program.FINAL_WEEK:
            print(f"  + end-of-plan reminder {monday + dt.timedelta(days=6)} {REMINDER_TIME}")
        return

    old = planned.get(key, {})
    if old.get("schedules"):
        garmin([{"op": "unschedule", "schedule_id": s["schedule_id"]} for s in old["schedules"]])

    ids = ensure_workouts(state, specs, dry_run=False)
    save_state(state)
    sched_ops, sched_meta = [], []
    for d in days:
        for s in d["workouts"]:
            name = program.build_workout(s)["workoutName"]
            sched_ops.append({"op": "schedule", "workout_id": ids[name], "date": d["date"].isoformat()})
            sched_meta.append({"date": d["date"].isoformat(), "workout": name, "workout_id": ids[name]})
    for meta, r in zip(sched_meta, garmin(sched_ops)):
        meta["schedule_id"] = r["scheduleId"]
    planned[key] = {"c25k_week": week, "note": note, "schedules": sched_meta,
                    "invites": old.get("invites", {})}
    if record:
        state.setdefault("history", []).append(record)
    save_state(state)
    log(f"week {key}: C25K week {week} ({note}); scheduled {len(sched_meta)} workouts")

    retire_workouts(state)

    invites = planned[key]["invites"]
    sent = planned[key].setdefault("sent", old.get("sent", {}))
    count = 0
    for d in days:
        date = d["date"].isoformat()
        uid = invites.get(date)
        h = hashlib.sha1((d["summary"] + d["desc"]).encode()).hexdigest()[:12]
        if uid and sent.get(date) == h:
            continue
        if uid:  # keep any time the user moved it to; refresh the content only
            invite("update", "--uid", uid, "--summary", d["summary"], "--desc", d["desc"])
        else:
            invites[date] = invite("new", "--summary", d["summary"],
                                   "--start", f"{date} {program.BLOCK_TIME}",
                                   "--minutes", str(d["block_minutes"]), "--desc", d["desc"])
        sent[date] = h
        count += 1
        save_state(state)
    log(f"week {key}: {count} calendar invites sent or updated")

    end_reminder(state, monday, week, record)
    save_state(state)


def end_reminder(state, monday, week, record):
    """Book (or move) 'plan the next block' for the Sunday that ends the first week-9 week."""
    if week != program.FINAL_WEEK:
        return
    rem = state.get("end_reminder")
    if record and record["outcome"].startswith("complete"):
        return  # week 9 already done; the reminder stays where it fired
    sunday = (monday + dt.timedelta(days=6)).isoformat()
    hist = state.get("history", [])
    repeats = sum(1 for h in hist if h["outcome"].startswith("repeat"))
    desc = (f"C25K week 9 ends today. Weeks planned so far: {len(state.get('planned', {}))}; "
            f"repeated weeks: {repeats}.\nOpen Claude in Desktop\\Training and plan the next block "
            "(this is where sleep/readiness rules were deferred to).")
    if rem:
        invite("update", "--uid", rem["uid"], "--start", f"{sunday} {REMINDER_TIME}", "--desc", desc)
        rem["date"] = sunday
        log(f"end-of-plan reminder moved to {sunday}")
    else:
        uid = invite("new", "--summary", "C25K complete: plan the next block with Claude",
                     "--start", f"{sunday} {REMINDER_TIME}", "--minutes", "30", "--desc", desc)
        state["end_reminder"] = {"uid": uid, "date": sunday}
        log(f"end-of-plan reminder booked for {sunday}")


def cmd_knee(a):
    if not 0 <= a.pain <= 10:
        raise SystemExit("pain is 0-10")
    state = load_state()
    date = a.date or dt.date.today().isoformat()
    state.setdefault("knee", {})[date] = a.pain
    save_state(state)
    log(f"knee {date}: {a.pain}/10" + ("  (above 3: this week will repeat)" if a.pain > 3 else ""))


def cmd_status(a):
    state = load_state()
    if not state:
        print("not initialised")
        return
    print(f"start {state.get('start_date')}  start week {state.get('start_week')}")
    for k, v in sorted(state.get("planned", {}).items()):
        print(f"  week of {k}: C25K week {v['c25k_week']} ({v.get('note', '')})")
    for h in state.get("history", []):
        print(f"  result {h['week_start']}: W{h['c25k_week']} runs {h['runs_done']}/3 knee {h['knee_max']} -> {h['outcome']}")
    if state.get("knee"):
        print("  knee log:", ", ".join(f"{d} {v}" for d, v in sorted(state["knee"].items())[-7:]))
    if state.get("end_reminder"):
        print(f"  end-of-plan reminder: {state['end_reminder']['date']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--start", required=True)
    i.add_argument("--week", type=int, default=1, choices=range(1, 10))
    i.add_argument("--force", action="store_true")
    w = sub.add_parser("plan-week")
    w.add_argument("--monday")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--replan", action="store_true")
    k = sub.add_parser("knee")
    k.add_argument("pain", type=int)
    k.add_argument("--date")
    sub.add_parser("status")
    a = p.parse_args()
    {"init": cmd_init, "plan-week": cmd_plan_week, "knee": cmd_knee, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
