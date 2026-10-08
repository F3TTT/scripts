# training-coach

Schedules a plain, fixed C25K + strength week (started 2026-10-12) onto the Fenix and the
work Outlook calendar. It replaces Garmin's Daily Suggested Workouts, which shrank to
"15 min recovery" or "rest" after Max HR / LTHR were corrected to 172 / 150.

Sleep and readiness data deliberately do **not** change workouts at this stage; that is
deferred to the next block after C25K. Program rules for the user:
`C:\Users\ADMIN\OneDrive\Desktop\Training\C25K_program_Oct2026.md`.

## The week

| Day | Calendar block (06:15, +15 min change / +20 min shower) | On the Fenix |
|---|---|---|
| Mon | Lift: MondayPT (Fitbod, gym) | Z2 Bike 30, Z2 Walk 30 |
| Tue / Thu / Sat | Run: C25K W*n*D1-3 | C25K W*n*D*d* (run steps 128-144 bpm) |
| Wed | Lift: WednesdayPT (Fitbod, home, bands only) | Z2 Bike 30, Z2 Walk 30 |
| Fri | Lift: FridayPT (Fitbod, gym) | Z2 Bike 30, Z2 Walk 30 |
| Sun | Z2 cardio: bike or walk | Z2 Bike 30, Z2 Walk 30 |

Strength is Fitbod's job (it sets the loads); the user records it on the Fenix as Strength.
HR targets are explicit bpm ranges (`heart.rate.zone` + `targetValueOne/Two`, the same shape
TrainingPeaks syncs), so Garmin's own zone tables don't matter. Walking workouts use sport id 12
(the server's /workout/types list omits it, and garminconnect's id 17 is stored as "no sport").

**Weekly rule** (`program.next_week`): advance a C25K week unless a run was missed (fewer than
3 runs of at least 75% of the scheduled length, from Garmin activities) or knee pain above 3/10
was logged that week, which repeats it. After week 9 completes, week 9 runs continue until a
new plan replaces this one.

**Goal race** (`program.RACE`): Run Santa Run Miami 5K, Sun 2026-12-20, 08:00. In its week the
Saturday run becomes "Shakeout 16" and Sunday is a 07:00-09:30 race block with nothing pushed
to the watch (recorded as a Run, it counts as the third run). With no repeated weeks, week 9 is
Dec 7-13 and the race week is the week-9 hold. The "plan the next block" invite is booked for
race day 18:00 (without a race it falls back to the Sunday ending the first week-9 week).

## Use

```
python coach.py status
python coach.py knee 4 [--date 2026-10-13]       # >3 repeats the week
python coach.py plan-week --dry-run               # preview the coming week
python coach.py plan-week --monday 2026-10-19 --replan   # redo a week (keeps moved invite times)
python test_program.py                            # offline tests
```

`init --start <Monday> --week N` was run once (2026-10-12, week 1).

## Files

- `program.py`: HR ranges, C25K weeks, layout, Fitbod routine lists, Garmin workout JSON. Stdlib only.
- `coach.py`: CLI, Windows Python. Invites go through `C:\scripts\calendar-invites\invites.py`
  (needs Credential Manager, so not WSL); Garmin calls go through `garmin_ops.py`.
- `garmin_ops.py`: runs in the `garmin_trends` WSL venv and reuses its `get_client()` and cached
  tokens. JSON ops on stdin, results on stdout, one login per batch.
- `run-coach.ps1`: task wrapper.
- State outside the repo: `~/.training-coach/state.json` (workout IDs and content hashes,
  planned weeks with Garmin schedule IDs and invite UIDs, weekly results, knee log) and `coach.log`.

Re-planning is idempotent: a planned week is skipped unless `--replan`; changed workout
definitions are re-uploaded and the replaced ones deleted once unscheduled; invites are only
re-sent when their content changed, and updates never touch the start time.

## Scheduled task

`training-coach-weekly`, Sundays 6:00 PM, headless:

```powershell
$a = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument '--headless pwsh -NoProfile -File C:\scripts\training-coach\run-coach.ps1'
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 6pm
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'training-coach-weekly' -Action $a -Trigger $t -Settings $s
```

If Garmin login needs an MFA code, the run fails; run `garmin_trends/garmin_client.py` by hand.
