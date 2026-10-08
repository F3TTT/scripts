"""Offline tests for program.py: python test_program.py"""
import datetime as dt
import unittest

import program


class ProgramTests(unittest.TestCase):
    def test_c25k_shapes(self):
        self.assertEqual(program.c25k_minutes(1, 1), 30)   # 5 + 8x2:30 + 5
        self.assertEqual(program.c25k_minutes(9, 3), 40)   # 5 + 30 + 5
        self.assertEqual(program.summarize_main(program.c25k_main(1, 1)), "8x (1:00 run / 1:30 walk)")
        self.assertEqual(program.c25k_main(5, 3), [("run", 1200)])
        for week in range(1, 10):
            for day in (1, 2, 3):
                self.assertTrue(program.c25k_main(week, day))

    def test_run_workout_targets(self):
        w = program.c25k_workout(1, 1)
        steps = w["workoutSegments"][0]["workoutSteps"]
        self.assertEqual(len(steps), 18)
        runs = [s for s in steps if s["description"] == "Run"]
        self.assertEqual(len(runs), 8)
        for s in runs:
            self.assertEqual(s["targetType"]["workoutTargetTypeKey"], "heart.rate.zone")
            self.assertEqual((s["targetValueOne"], s["targetValueTwo"]), (128.0, 144.0))
        self.assertEqual(w["estimatedDurationInSecs"], 30 * 60)
        self.assertEqual([s["stepOrder"] for s in steps], list(range(1, 19)))

    def test_z2(self):
        bike = program.z2_workout("cycling")
        self.assertEqual(bike["sportType"]["sportTypeKey"], "cycling")
        self.assertEqual(bike["estimatedDurationInSecs"], 30 * 60)
        main = bike["workoutSegments"][0]["workoutSteps"][1]
        self.assertEqual((main["targetValueOne"], main["targetValueTwo"]), (128.0, 139.0))
        self.assertEqual(program.z2_workout("walking")["sportType"]["sportTypeId"], 12)

    def test_week(self):
        days = program.week_days(dt.date(2026, 10, 12), 1)
        self.assertEqual([d["date"].weekday() for d in days], list(range(7)))
        self.assertEqual(days[0]["summary"], "Lift: MondayPT (Fitbod, gym)")
        self.assertEqual(days[1]["summary"], "Run: C25K W1D1 (30 min)")
        self.assertEqual(days[1]["block_minutes"], 15 + 30 + 20)
        self.assertEqual(days[2]["block_minutes"], 15 + 25 + 20)
        self.assertIn("Cable Row", days[0]["desc"])
        self.assertEqual(days[6]["workouts"], [("z2", "cycling"), ("z2", "walking")])
        self.assertTrue(all("ledger" not in d["desc"].lower() for d in days))

    def test_race_week(self):
        days = program.week_days(dt.date(2026, 12, 14), 9)
        sat, sun = days[5], days[6]
        self.assertEqual(sat["workouts"], [("shakeout",)])
        self.assertEqual(sun["workouts"], [])
        self.assertTrue(sun["summary"].startswith("RACE: Run Santa Run"))
        self.assertEqual((sun["start"], sun["block_minutes"]), ("07:00", 150))
        self.assertEqual(days[1]["workouts"], [("c25k", 9, 1)])
        self.assertEqual(program.build_workout(("shakeout",))["estimatedDurationInSecs"], 16 * 60)
        # other weeks untouched
        self.assertEqual(program.week_days(dt.date(2026, 12, 7), 9)[6]["workouts"],
                         [("z2", "cycling"), ("z2", "walking")])

    def test_weekly_rule(self):
        self.assertEqual(program.next_week(1, 3, None)[0], 2)
        self.assertEqual(program.next_week(1, 3, 3)[0], 2)
        self.assertEqual(program.next_week(1, 3, 4), (1, "repeat: knee 4/10"))
        self.assertEqual(program.next_week(4, 2, 0), (4, "repeat: 2/3 runs"))
        self.assertEqual(program.next_week(9, 3, None), (9, "complete: holding week 9"))
        self.assertEqual(program.next_week(8, 4, None)[0], 9)


if __name__ == "__main__":
    unittest.main()
