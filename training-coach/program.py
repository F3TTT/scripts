"""The training program as data: HR ranges, the 9-week C25K, the weekly layout,
the Fitbod routines, and builders for Garmin workout JSON.

Pure stdlib and no I/O, so it runs under both Windows Python (coach.py) and the
WSL venv (garmin_ops.py), and is easy to test offline.
"""
import datetime as dt

# HR ranges in bpm, from Max HR 172 / LTHR 150 (Garmin zone floors
# Z1 102 / Z2 128 / Z3 140 / Z4 149). Explicit bpm, so the watch never
# depends on Garmin's own zone tables (the cycling table is still wrong).
RUN_HR = (128, 144)    # C25K run steps: Z2 into low Z3
BIKE_HR = (128, 139)   # Z2 ride
WALK_HR = (115, 139)   # Z2 walk; floor lowered because brisk walks average ~115-125

WARMUP_S = 5 * 60
COOLDOWN_S = 5 * 60
CHANGE_MIN = 15        # calendar buffer before
SHOWER_MIN = 20        # calendar buffer after
BLOCK_TIME = "06:15"   # default calendar start, before work
Z2_MIN = 30            # the doctor's daily 30


def _rep(n, *pairs):
    return [p for _ in range(n) for p in pairs]


R, W = "run", "walk"

# Main set per C25K week and day (the run/walk between warm-up and cool-down),
# as (kind, seconds). A week with one list uses it for all three days.
C25K = {
    1: [_rep(8, (R, 60), (W, 90))],
    2: [_rep(6, (R, 90), (W, 120))],
    3: [_rep(2, (R, 90), (W, 90), (R, 180), (W, 180))],
    4: [[(R, 180), (W, 90), (R, 300), (W, 150), (R, 180), (W, 90), (R, 300)]],
    5: [[(R, 300), (W, 180), (R, 300), (W, 180), (R, 300)],
        [(R, 480), (W, 300), (R, 480)],
        [(R, 1200)]],
    6: [[(R, 300), (W, 180), (R, 480), (W, 180), (R, 300)],
        [(R, 600), (W, 180), (R, 600)],
        [(R, 1320)]],
    7: [[(R, 1500)]],
    8: [[(R, 1680)]],
    9: [[(R, 1800)]],
}
FINAL_WEEK = 9


def c25k_main(week, day):
    """Main set for C25K week 1-9, run day 1-3."""
    sets = C25K[week]
    return sets[day - 1] if len(sets) == 3 else sets[0]


def fmt_s(s):
    return f"{s // 60}:{s % 60:02d}"


def summarize_main(main):
    """'8x (1:00 run / 1:30 walk)' or '5:00 run, 3:00 walk, ...'."""
    if len(main) >= 4 and len(main) % 2 == 0:
        pair = main[:2]
        if all(main[i:i + 2] == pair for i in range(0, len(main), 2)):
            return f"{len(main) // 2}x ({fmt_s(pair[0][1])} {pair[0][0]} / {fmt_s(pair[1][1])} {pair[1][0]})"
    return ", ".join(f"{fmt_s(s)} {k}" for k, s in main)


def c25k_minutes(week, day):
    return (WARMUP_S + sum(s for _, s in c25k_main(week, day)) + COOLDOWN_S) // 60


# Fitbod routines (from the user's Fitbod screenshots, 2026-10-08). Loads come
# from Fitbod; these lists only go in the calendar description.
ROUTINES = {
    "MondayPT": {
        "minutes": 60,
        "where": "gym",
        "exercises": [
            "Cable Row", "Plank", "Terminal Knee Extension (TKE)", "Straight-Arm Pulldown",
            "Dumbbell Lunge", "Band Wall Pull-Aparts", "Russian Twist",
            "Standing Dumbbell Calf Raise", "Dumbbell Bicep Curl", "Mini Loop Band Bridge",
            "Machine Leg Press", "Dumbbell Tricep Extension", "Bolstered Leg Extension",
            "Straight-Leg Isolated Leg Lifts", "Mini Loop Band Side-Lying Clam",
            "Balance Single-Leg Kettlebell Transfers",
        ],
    },
    "WednesdayPT": {
        "minutes": 25,
        "where": "home, bands only",
        "exercises": [
            "Band TKE", "Mini-Band Side-Lying Clam", "Mini-Band Bridge", "Band Wall Pull-Aparts",
            "Band External Rotation", "Band Face Pull or Band Row", "Single-Leg Glute Bridge",
            "Wall Sit", "Side Bridge", "Single-Leg Balance Reach", "Dead Bug",
        ],
    },
    "FridayPT": {
        "minutes": 60,
        "where": "gym",
        "exercises": [
            "Cable Row", "Crunches", "90-Degree Dumbbell Hold", "Mini Loop Band Bridge",
            "Side Bridge", "Straight-Arm Pulldown", "Terminal Knee Extension (TKE)",
            "Dumbbell Bench Press", "Dumbbell Lunge", "Wall Sit", "Single-Leg Glute Bridge",
            "Mini Loop Band Side-Lying Clam", "Box Step Down",
            "Balance Single-Leg Kettlebell Transfers",
        ],
    },
}

# Weekly layout, Monday = 0. Run days are numbered 1-3 within the C25K week.
LAYOUT = {
    0: ("lift", "MondayPT"),
    1: ("run", 1),
    2: ("lift", "WednesdayPT"),
    3: ("run", 2),
    4: ("lift", "FridayPT"),
    5: ("run", 3),
    6: ("z2", None),
}


# --- Garmin workout JSON -------------------------------------------------

SPORTS = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    # Walking is id 12, though /workout/types doesn't list it; garminconnect's
    # id 17 is silently stored as "no sport".
    "walking": {"sportTypeId": 12, "sportTypeKey": "walking", "displayOrder": 11},
}
STEP_TYPES = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}


def _step(order, kind, seconds, desc, hr=None):
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": STEP_TYPES[kind], "stepTypeKey": kind, "displayOrder": STEP_TYPES[kind]},
        "description": desc,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
        "endConditionValue": float(seconds),
        "targetType": dict(HR_TARGET if hr else NO_TARGET),
    }
    if hr:
        # Custom bpm range: same shape TrainingPeaks-synced workouts use.
        step["targetValueOne"], step["targetValueTwo"] = float(hr[0]), float(hr[1])
    return step


def _workout(name, sport, steps, description):
    return {
        "workoutName": name,
        "description": description,
        "sportType": SPORTS[sport],
        "estimatedDurationInSecs": int(sum(s["endConditionValue"] for s in steps)),
        "workoutSegments": [{"segmentOrder": 1, "sportType": SPORTS[sport], "workoutSteps": steps}],
    }


def c25k_workout(week, day):
    main = c25k_main(week, day)
    steps = [_step(1, "warmup", WARMUP_S, "Brisk walk")]
    for kind, secs in main:
        if kind == R:
            steps.append(_step(len(steps) + 1, "interval", secs, "Run", RUN_HR))
        else:
            steps.append(_step(len(steps) + 1, "recovery", secs, "Walk"))
    steps.append(_step(len(steps) + 1, "cooldown", COOLDOWN_S, "Walk"))
    desc = f"C25K week {week} day {day}: {summarize_main(main)}. Run steps {RUN_HR[0]}-{RUN_HR[1]} bpm."
    return _workout(f"C25K W{week}D{day}", "running", steps, desc)


def z2_workout(sport):
    hr = BIKE_HR if sport == "cycling" else WALK_HR
    label = "Bike" if sport == "cycling" else "Walk"
    steps = [
        _step(1, "warmup", WARMUP_S, "Easy"),
        _step(2, "interval", (Z2_MIN * 60) - WARMUP_S, f"Zone 2 {label.lower()}", hr),
    ]
    return _workout(f"Z2 {label} {Z2_MIN}", sport, steps, f"{Z2_MIN} min Zone 2 {label.lower()}, {hr[0]}-{hr[1]} bpm.")


def hr_lines():
    return (f"HR: run {RUN_HR[0]}-{RUN_HR[1]} bpm, walk breaks untargeted. "
            f"Z2 bike {BIKE_HR[0]}-{BIKE_HR[1]}, Z2 walk {WALK_HR[0]}-{WALK_HR[1]}.")


# --- The week ---------------------------------------------------------------

def week_days(monday, c25k_week):
    """Each day of the week: what goes on the watch and what goes on the calendar."""
    days = []
    z2_note = (f"Daily 30: Z2 bike or Z2 walk ({Z2_MIN} min) is on the watch for today; "
               "do either one, any time.")
    for i in range(7):
        date = monday + dt.timedelta(days=i)
        kind, arg = LAYOUT[i]
        if kind == "run":
            mins = c25k_minutes(c25k_week, arg)
            main = c25k_main(c25k_week, arg)
            days.append({
                "date": date, "workouts": [("c25k", c25k_week, arg)],
                "summary": f"Run: C25K W{c25k_week}D{arg} ({mins} min)",
                "minutes": mins,
                "desc": (f"C25K week {c25k_week}, run {arg} of 3: 5 min brisk walk, "
                         f"{summarize_main(main)}, 5 min walk.\n"
                         f"On the Fenix as 'C25K W{c25k_week}D{arg}'. "
                         f"Run steps {RUN_HR[0]}-{RUN_HR[1]} bpm; walk breaks have no target.\n"
                         "Knee check: pain above 3/10 during or after, tell Claude (it repeats the week)."),
            })
        elif kind == "lift":
            r = ROUTINES[arg]
            days.append({
                "date": date, "workouts": [("z2", "cycling"), ("z2", "walking")],
                "summary": f"Lift: {arg} (Fitbod, {r['where']})",
                "minutes": r["minutes"],
                "desc": (f"{arg} in Fitbod, {r['where']}. Weights per Fitbod. "
                         "Record it on the Fenix as a Strength activity.\n\n"
                         + "\n".join(f"- {e}" for e in r["exercises"]) + "\n\n" + z2_note),
            })
        else:
            days.append({
                "date": date, "workouts": [("z2", "cycling"), ("z2", "walking")],
                "summary": f"Z2 cardio: bike or walk ({Z2_MIN} min)",
                "minutes": Z2_MIN,
                "desc": (f"Pick one: 'Z2 Bike {Z2_MIN}' ({BIKE_HR[0]}-{BIKE_HR[1]} bpm) or "
                         f"'Z2 Walk {Z2_MIN}' ({WALK_HR[0]}-{WALK_HR[1]} bpm). Both are on the Fenix today."),
            })
    for d in days:
        d["block_minutes"] = CHANGE_MIN + d["minutes"] + SHOWER_MIN
        d["desc"] += f"\n\nBlock includes {CHANGE_MIN} min to change before and {SHOWER_MIN} min to shower after."
    return days


def build_workout(spec):
    if spec[0] == "c25k":
        return c25k_workout(spec[1], spec[2])
    return z2_workout(spec[1])


def next_week(prev_week, runs_done, knee_max):
    """Weekly rule. Returns (next C25K week, outcome)."""
    if knee_max is not None and knee_max > 3:
        return prev_week, f"repeat: knee {knee_max}/10"
    if runs_done < 3:
        return prev_week, f"repeat: {runs_done}/3 runs"
    if prev_week >= FINAL_WEEK:
        return FINAL_WEEK, "complete: holding week 9"
    return prev_week + 1, "advance"
