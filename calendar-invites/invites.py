"""Send reminder invites to the work Outlook calendar through Proton Bridge, and keep a ledger.

Every invite asks for a response (RSVP=TRUE), so Outlook offers Propose New Time;
counter_watch.py accepts those proposals. Times are US Eastern wall-clock.

  python invites.py new --summary "Return antenna" --start "2026-10-06 18:00" [--minutes 30]
                        [--end ...] [--desc ...] [--location ...] [--alarm 15] [--all-day]
  python invites.py update --uid UID [--start ...] [--end ...] [--summary ...] [--desc ...]
  python invites.py cancel --uid UID
  python invites.py list [--all]
  python invites.py import-sent [--since 01-Aug-2026]
"""
import argparse
import datetime as dt
import sys

import bridge


def parse_when(s):
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I%p"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return dt.date.fromisoformat(s)


def describe_when(ev):
    start = bridge.parse_ledger_time(ev["start"])
    if isinstance(start, dt.datetime):
        return f"{start:%a %b} {start.day}, {start.strftime('%I:%M %p').lstrip('0')}"
    return f"{start:%a %b} {start.day} (all day)"


def send(method, uid, ev, prefix):
    subject = f"{prefix}: {ev['summary']} - {describe_when(ev)}"
    body = (ev.get("description") or ev["summary"]) + f"\n\nWhen: {describe_when(ev)} ET"
    if method == "REQUEST":
        body += ("\nTo move it: in Outlook choose Tentative & Propose New Time; "
                 "the new time is accepted automatically.")
    bridge.send_calendar(method, subject, body, bridge.build_ics(method, uid, ev))


def cmd_new(a):
    start = parse_when(a.start)
    if a.all_day or not isinstance(start, dt.datetime):
        start = start.date() if isinstance(start, dt.datetime) else start
        end = parse_when(a.end) if a.end else start + dt.timedelta(days=1)
    else:
        end = parse_when(a.end) if a.end else start + dt.timedelta(minutes=a.minutes)
    ev = {"summary": a.summary, "description": a.desc or "", "location": a.location or "",
          "start": bridge.ledger_time(start), "end": bridge.ledger_time(end), "rrule": a.rrule or "",
          "seq": 0, "alarm_minutes": a.alarm, "organizer_cn": "Reminders", "transp": "OPAQUE",
          "status": "active", "response": "", "history": []}
    uid = bridge.new_uid()
    send("REQUEST", uid, ev, "Invite")
    ledger = bridge.load_ledger()
    ev["history"].append({"at": dt.datetime.now().isoformat(timespec="seconds"), "event": "created"})
    ledger[uid] = ev
    bridge.save_ledger(ledger)
    print(f"sent {uid}: {ev['summary']} at {describe_when(ev)}")


def _get(ledger, uid):
    if uid not in ledger:
        sys.exit(f"UID {uid} not in ledger (try import-sent)")
    return ledger[uid]


def cmd_update(a):
    ledger = bridge.load_ledger()
    ev = _get(ledger, a.uid)
    if a.start:
        old_start = bridge.parse_ledger_time(ev["start"])
        old_end = bridge.parse_ledger_time(ev["end"])
        start = parse_when(a.start)
        end = parse_when(a.end) if a.end else start + (old_end - old_start)
        ev["start"], ev["end"] = bridge.ledger_time(start), bridge.ledger_time(end)
    elif a.end:
        ev["end"] = bridge.ledger_time(parse_when(a.end))
    for field, value in (("summary", a.summary), ("description", a.desc), ("location", a.location)):
        if value is not None:
            ev[field] = value
    if a.alarm is not None:
        ev["alarm_minutes"] = a.alarm
    ev["seq"] += 1
    send("REQUEST", a.uid, ev, "Updated")
    ev["history"].append({"at": dt.datetime.now().isoformat(timespec="seconds"),
                          "event": "updated", "start": ev["start"]})
    bridge.save_ledger(ledger)
    print(f"updated {a.uid}: {ev['summary']} at {describe_when(ev)} (seq {ev['seq']})")


def cmd_cancel(a):
    ledger = bridge.load_ledger()
    ev = _get(ledger, a.uid)
    ev["seq"] += 1
    send("CANCEL", a.uid, ev, "Canceled")
    ev["status"] = "cancelled"
    ev["history"].append({"at": dt.datetime.now().isoformat(timespec="seconds"), "event": "cancelled"})
    bridge.save_ledger(ledger)
    print(f"cancelled {a.uid}: {ev['summary']}")


def cmd_list(a):
    today = dt.date.today()
    rows = []
    for uid, ev in bridge.load_ledger().items():
        start = bridge.parse_ledger_time(ev["start"])
        day = start.date() if isinstance(start, dt.datetime) else start
        if not a.all and (ev["status"] != "active" or (day < today and not ev.get("rrule"))):
            continue
        rows.append((ev["start"], uid, ev))
    for _, uid, ev in sorted(rows, key=lambda r: r[0]):
        flags = " ".join(f for f in (ev["status"] if ev["status"] != "active" else "",
                                     "weekly" if ev.get("rrule") else "", ev.get("response", "")) if f)
        print(f"{describe_when(ev):<24} {ev['summary']}  [{uid}] {flags}".rstrip())


def cmd_import_sent(a):
    """Rebuild ledger entries from REQUEST/CANCEL invites already in Proton's Sent folder."""
    m = bridge.imap()
    m.select("Sent", readonly=True)
    typ, data = m.search(None, "SINCE", a.since, "TO", f'"{bridge.ATTENDEE}"')
    found = []
    for num in data[0].split():
        typ, b = m.fetch(num, "(BODY.PEEK[])")
        msg = bridge.message_from_bytes(b[0][1])
        for text in bridge.calendar_parts(msg):
            method, vevents = bridge.parse_ics(text)
            for ve in vevents:
                if method in ("REQUEST", "CANCEL") and "UID" in ve and "DTSTART" in ve:
                    found.append((method, ve))
    m.logout()
    ledger = bridge.load_ledger()
    added = 0
    for method, ve in found:
        uid = ve["UID"][1]
        try:
            ev = bridge.event_from_vevent(ve)
        except ValueError as e:
            print(f"skip {uid}: {e}")
            continue
        cur = ledger.get(uid)
        if cur and cur["seq"] > ev["seq"]:
            continue
        if method == "CANCEL":
            if cur:
                cur["status"], cur["seq"] = "cancelled", max(cur["seq"], ev["seq"])
            continue
        if cur and cur["seq"] == ev["seq"] and cur.get("history"):
            continue
        if not cur:
            added += 1
        ev["history"] = (cur or {}).get("history", []) + [
            {"at": dt.datetime.now().isoformat(timespec="seconds"), "event": "imported"}]
        ev["status"] = (cur or {}).get("status", "active")
        ledger[uid] = ev
    bridge.save_ledger(ledger)
    print(f"imported {added} new events ({len(ledger)} in ledger)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--summary", required=True)
    n.add_argument("--start", required=True)
    n.add_argument("--end")
    n.add_argument("--minutes", type=int, default=30)
    n.add_argument("--desc")
    n.add_argument("--location")
    n.add_argument("--alarm", type=int, default=15)
    n.add_argument("--rrule")
    n.add_argument("--all-day", action="store_true")
    u = sub.add_parser("update")
    u.add_argument("--uid", required=True)
    for f in ("--start", "--end", "--summary", "--desc", "--location"):
        u.add_argument(f)
    u.add_argument("--alarm", type=int)
    c = sub.add_parser("cancel")
    c.add_argument("--uid", required=True)
    l = sub.add_parser("list")
    l.add_argument("--all", action="store_true")
    i = sub.add_parser("import-sent")
    i.add_argument("--since", default="01-Aug-2026")
    a = p.parse_args()
    {"new": cmd_new, "update": cmd_update, "cancel": cmd_cancel, "list": cmd_list,
     "import-sent": cmd_import_sent}[a.cmd](a)


if __name__ == "__main__":
    main()
