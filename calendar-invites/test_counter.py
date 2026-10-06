"""Offline tests: counter parsing/accept logic with sending stubbed out."""
import os, tempfile, unittest
os.environ["CALENDAR_INVITES_HOME"] = tempfile.mkdtemp()
import bridge, invites, counter_watch

SENT = []
invites.bridge.send_calendar = lambda method, subject, body, ics: SENT.append((method, subject, ics))

COUNTER = """BEGIN:VCALENDAR\r\nMETHOD:COUNTER\r\nBEGIN:VTIMEZONE\r\nTZID:Eastern Standard Time\r\nBEGIN:STANDARD\r\nTZOFFSETTO:-0500\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT\r\nUID:u1@f3ttt\r\nSEQUENCE:1\r\nSUMMARY:Return antenna\r\nDTSTART;TZID=Eastern Standard Time:20261007T120000\r\nDTEND;TZID=Eastern Standard Time:20261007T123000\r\nATTENDEE;PARTSTAT=TENTATIVE:mailto:attendee@example.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"""

class T(unittest.TestCase):
    def setUp(self):
        SENT.clear()
        self.ledger = {"u1@f3ttt": {"summary": "Return antenna", "description": "d", "location": "",
            "start": "2026-10-06T18:00", "end": "2026-10-06T18:30", "rrule": "", "seq": 1,
            "alarm_minutes": 30, "organizer_cn": "Reminders", "transp": "OPAQUE", "status": "active",
            "response": "", "history": []}}

    def test_counter_moves_event(self):
        method, ves = bridge.parse_ics(COUNTER)
        self.assertEqual(method, "COUNTER")
        counter_watch.handle_counter(self.ledger, ves[0], "New Time Proposed")
        ev = self.ledger["u1@f3ttt"]
        self.assertEqual((ev["start"], ev["end"], ev["seq"]), ("2026-10-07T12:00", "2026-10-07T12:30", 2))
        self.assertEqual(SENT[0][0], "REQUEST")
        self.assertIn("DTSTART;TZID=America/New_York:20261007T120000", SENT[0][2])
        self.assertIn("SEQUENCE:2", SENT[0][2])
        self.assertIn("RSVP=TRUE", SENT[0][2].replace("\r\n ", ""))

    def test_utc_counter_and_recurrence_skip(self):
        method, ves = bridge.parse_ics(COUNTER.replace(
            "DTSTART;TZID=Eastern Standard Time:20261007T120000", "DTSTART:20261007T160000Z"))
        counter_watch.handle_counter(self.ledger, ves[0], "x")
        self.assertEqual(self.ledger["u1@f3ttt"]["start"], "2026-10-07T12:00")
        method, ves = bridge.parse_ics(COUNTER.replace("SEQUENCE:1", "RECURRENCE-ID:20261007T120000Z"))
        SENT.clear()
        counter_watch.handle_counter(self.ledger, ves[0], "x")
        self.assertEqual(SENT, [])

    def test_unknown_uid_adopted(self):
        method, ves = bridge.parse_ics(COUNTER.replace("u1@f3ttt", "new@x"))
        counter_watch.handle_counter(self.ledger, ves[0], "x")
        self.assertEqual(self.ledger["new@x"]["start"], "2026-10-07T12:00")
        self.assertEqual(SENT[-1][0], "REQUEST")

    def test_reply(self):
        method, ves = bridge.parse_ics(COUNTER.replace("COUNTER", "REPLY"))
        counter_watch.handle_reply(self.ledger, ves[0])
        self.assertEqual(self.ledger["u1@f3ttt"]["response"], "tentative")

unittest.main()
