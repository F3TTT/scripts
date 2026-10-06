"""Accept Outlook "Propose New Time" counters for invites sent by invites.py.

Scans Proton (via Bridge IMAP, read-only) for recent calendar mail from the work address.
METHOD:COUNTER -> apply the proposed time, bump SEQUENCE, re-send the REQUEST (Outlook moves
the event). METHOD:REPLY -> record accepted/declined in the ledger. Processed Message-IDs are
kept in state.json. Exits 1 if any message failed, so the scheduled task shows the failure.
"""
import datetime as dt
import sys

import bridge
import invites

LOOKBACK_DAYS = 3
ATTENDEE_DOMAIN = bridge.ATTENDEE.split("@")[1]


def handle_counter(ledger, ve, subject):
    uid = ve["UID"][1]
    if "RECURRENCE-ID" in ve:
        bridge.log(f"SKIP counter for one occurrence of recurring {uid} ({subject}); "
                   "move the whole series or ask Claude")
        return
    ev = ledger.get(uid)
    adopted = ev is None
    if adopted:
        ev = bridge.event_from_vevent(ve)
        ev["history"] = [{"at": dt.datetime.now().isoformat(timespec="seconds"),
                          "event": "adopted from counter"}]
        ledger[uid] = ev
    old_start, old_end = bridge.parse_ledger_time(ev["start"]), bridge.parse_ledger_time(ev["end"])
    start = bridge.ics_time_to_ledger(*ve["DTSTART"])
    if "DTEND" in ve:
        end = bridge.ics_time_to_ledger(*ve["DTEND"])
    else:
        end = bridge.ledger_time(bridge.parse_ledger_time(start) + (old_end - old_start))
    if not adopted and (start, end) == (ev["start"], ev["end"]):
        bridge.log(f"counter for {uid} matches current time; nothing to do")
        return
    counter_seq = int(ve["SEQUENCE"][1]) if "SEQUENCE" in ve else 0
    was = invites.describe_when(ev)
    ev["start"], ev["end"] = start, end
    ev["seq"] = max(ev["seq"], counter_seq) + 1
    ev["status"] = "active"
    invites.send("REQUEST", uid, ev, "Updated")
    ev["history"].append({"at": dt.datetime.now().isoformat(timespec="seconds"),
                          "event": "counter accepted", "from": was, "start": start})
    bridge.log(f"ACCEPTED counter: {ev['summary']} moved {was} -> {invites.describe_when(ev)} [{uid}]")


def handle_reply(ledger, ve):
    uid = ve["UID"][1]
    ev = ledger.get(uid)
    partstat = ve.get("ATTENDEE", ({}, ""))[0].get("PARTSTAT", "").upper()
    if ev is not None and partstat:
        ev["response"] = partstat.lower()
        bridge.log(f"reply {partstat} for {ev['summary']} [{uid}]")


def main():
    state = bridge.load_state()
    processed = set(state["processed"])
    ledger = bridge.load_ledger()
    since = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    m = bridge.imap()
    m.select('"All Mail"', readonly=True)
    typ, data = m.search(None, "SINCE", since, "FROM", f'"{ATTENDEE_DOMAIN}"')
    failures = 0
    for num in data[0].split():
        typ, hdr = m.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        mid = bridge.message_from_bytes(hdr[0][1]).get("Message-ID", "").strip()
        if not mid or mid in processed:
            continue
        typ, b = m.fetch(num, "(BODY.PEEK[])")
        msg = bridge.message_from_bytes(b[0][1])
        try:
            for text in bridge.calendar_parts(msg):
                method, vevents = bridge.parse_ics(text)
                for ve in vevents:
                    if "UID" not in ve:
                        continue
                    if method == "COUNTER":
                        handle_counter(ledger, ve, msg.get("Subject", ""))
                    elif method == "REPLY":
                        handle_reply(ledger, ve)
        except Exception as e:  # keep going; one bad message shouldn't block the rest
            failures += 1
            bridge.log(f"ERROR on {mid} ({msg.get('Subject', '')}): {e!r}")
        processed.add(mid)
        state["processed"].append(mid)
        bridge.save_ledger(ledger)
    m.logout()
    state["processed"] = state["processed"][-1000:]
    state["last_run"] = dt.datetime.now().isoformat(timespec="seconds")
    bridge.save_state(state)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
