"""Shared helpers for calendar-invites: Proton Bridge auth/IMAP/SMTP, the event ledger, and
minimal iCalendar build/parse.

Stdlib only. This laptop has no tzdata package, so Eastern time is converted with the US DST
rule directly (second Sunday of March to first Sunday of November).
"""
import ctypes
import ctypes.wintypes as w
import datetime as dt
import email
import imaplib
import json
import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from pathlib import Path

CRED_TARGET = "ProtonBridgeSMTP"
TZID = "America/New_York"

# Addresses, the ledger and watcher state are personal; keep them out of the (public) repo.
DATA_DIR = Path(os.environ.get("CALENDAR_INVITES_HOME", Path.home() / ".calendar-invites"))
CONFIG = DATA_DIR / "config.json"
LEDGER = DATA_DIR / "events.json"
STATE = DATA_DIR / "state.json"
LOG = DATA_DIR / "watch.log"

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


def _config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"organizer": "organizer@example.com", "attendee": "attendee@example.com",
                "attendee_name": "Attendee"}


_cfg = _config()
ORGANIZER = _cfg["organizer"]          # Bridge identity that sends invites
ATTENDEE = _cfg["attendee"]            # calendar that receives them
ATTENDEE_NAME = _cfg.get("attendee_name", "")


# ---------- Bridge credentials and connections ----------

class _Cred(ctypes.Structure):
    _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR),
                ("Comment", w.LPWSTR), ("LastWritten", w.FILETIME),
                ("CredentialBlobSize", w.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_char)), ("Persist", w.DWORD),
                ("AttributeCount", w.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", w.LPWSTR), ("UserName", w.LPWSTR)]


def bridge_credentials():
    p = ctypes.POINTER(_Cred)()
    if not ctypes.windll.advapi32.CredReadW(CRED_TARGET, 1, 0, ctypes.byref(p)):
        raise RuntimeError(f"Credential Manager target {CRED_TARGET!r} not found")
    try:
        c = p.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        pw = raw.decode("utf-16-le") if b"\x00" in raw else raw.decode()
        return c.UserName, pw
    finally:
        ctypes.windll.advapi32.CredFree(p)


def _tls():
    # Bridge uses a self-signed cert on localhost.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def imap():
    user, pw = bridge_credentials()
    m = imaplib.IMAP4("127.0.0.1", 1143)
    m.starttls(_tls())
    m.login(user, pw)
    return m


def send_calendar(method, subject, body, ics_text):
    user, pw = bridge_credentials()
    msg = EmailMessage()
    msg["From"] = ORGANIZER
    msg["To"] = ATTENDEE
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(ics_text.encode(), maintype="text", subtype="calendar",
                       filename="invite.ics", params={"method": method})
    with smtplib.SMTP("127.0.0.1", 1025) as s:
        s.starttls(context=_tls())
        s.login(user, pw)
        s.send_message(msg)


# ---------- Ledger ----------

def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _save(path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_ledger():
    return _load(LEDGER, {})


def save_ledger(ledger):
    _save(LEDGER, ledger)


def load_state():
    return _load(STATE, {"processed": []})


def save_state(state):
    _save(STATE, state)


def log(line):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    print(line)


def new_uid():
    return f"{uuid.uuid4()}@f3ttt"


# ---------- Time ----------
# Ledger times are Eastern wall-clock strings "YYYY-MM-DDTHH:MM", or "YYYY-MM-DD" for all-day.

def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """UTC offset of US Eastern at the given naive UTC datetime."""
    y = utc.year
    dst_start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7))   # 2 AM EST = 07:00 UTC
    dst_end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6))    # 2 AM EDT = 06:00 UTC
    return dt.timedelta(hours=-4 if dst_start <= utc < dst_end else -5)


def utc_to_eastern(utc):
    return utc + eastern_offset(utc)


def ledger_time(value):
    return value.strftime("%Y-%m-%dT%H:%M") if isinstance(value, dt.datetime) else value.isoformat()


def parse_ledger_time(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M") if "T" in s else dt.date.fromisoformat(s)


def ics_time_prop(name, s):
    v = parse_ledger_time(s)
    if isinstance(v, dt.datetime):
        return f"{name};TZID={TZID}:{v.strftime('%Y%m%dT%H%M%S')}"
    return f"{name};VALUE=DATE:{v.strftime('%Y%m%d')}"


EASTERN_TZIDS = ("america/new_york", "eastern standard time", "us/eastern", "us-eastern")


def ics_time_to_ledger(params, value):
    """Convert an iCalendar DTSTART/DTEND value to a ledger string, or raise ValueError."""
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return dt.datetime.strptime(value, "%Y%m%d").date().isoformat()
    if value.endswith("Z"):
        return ledger_time(utc_to_eastern(dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ")))
    tzid = params.get("TZID", "").strip('"').lower()
    if any(t in tzid for t in EASTERN_TZIDS):
        return ledger_time(dt.datetime.strptime(value, "%Y%m%dT%H%M%S"))
    raise ValueError(f"unsupported time zone {params.get('TZID')!r} for {value}")


# ---------- iCalendar text ----------

def escape(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def unescape(text):
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def fold(line):
    """Fold to 75-octet lines per RFC 5545 without splitting UTF-8 sequences."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def build_ics(method, uid, ev):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cn = ev.get("organizer_cn") or "Reminders"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//f3ttt//calendar-invites//EN",
             "CALSCALE:GREGORIAN", f"METHOD:{method}", *VTIMEZONE.splitlines(),
             "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"SEQUENCE:{ev['seq']}",
             ics_time_prop("DTSTART", ev["start"]), ics_time_prop("DTEND", ev["end"])]
    if ev.get("rrule"):
        lines.append(f"RRULE:{ev['rrule']}")
    lines.append(f"SUMMARY:{escape(ev['summary'])}")
    if ev.get("location"):
        lines.append(f"LOCATION:{escape(ev['location'])}")
    if ev.get("description"):
        lines.append(f"DESCRIPTION:{escape(ev['description'])}")
    lines += [f"ORGANIZER;CN={cn}:mailto:{ORGANIZER}",
              f"ATTENDEE;CN={ATTENDEE_NAME};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE"
              f":mailto:{ATTENDEE}",
              "TRANSP:" + ev.get("transp", "OPAQUE"),
              "STATUS:" + ("CANCELLED" if method == "CANCEL" else "CONFIRMED")]
    if ev.get("alarm_minutes") and method != "CANCEL":
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape(ev['summary'])}",
                  f"TRIGGER:-PT{int(ev['alarm_minutes'])}M", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def parse_ics(text):
    """Return (method, [vevent dicts]). Each vevent maps NAME -> (params, value) for its first
    occurrence; nested components (VALARM) are skipped except for the alarm trigger."""
    raw = text.replace("\r\n", "\n").split("\n")
    lines = []
    for l in raw:
        if l[:1] in (" ", "\t") and lines:
            lines[-1] += l[1:]
        elif l:
            lines.append(l)
    method, events, cur, depth = None, [], None, []
    for l in lines:
        name_part, _, value = l.partition(":")
        name, *pparts = name_part.split(";")
        name = name.upper()
        params = {}
        for p in pparts:
            k, _, v = p.partition("=")
            params[k.upper()] = v
        if name == "BEGIN":
            depth.append(value.upper())
            if value.upper() == "VEVENT":
                cur = {}
            continue
        if name == "END":
            if depth:
                depth.pop()
            if value.upper() == "VEVENT" and cur is not None:
                events.append(cur)
                cur = None
            continue
        if name == "METHOD" and not depth[1:]:
            method = value.strip().upper()
        if cur is None:
            continue
        if depth and depth[-1] == "VALARM":
            if name == "TRIGGER":
                cur.setdefault("_ALARM", (params, value))
            continue
        cur.setdefault(name, (params, value))
    return method, events


def calendar_parts(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/calendar":
            payload = part.get_payload(decode=True)
            if payload:
                yield payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def event_from_vevent(ve):
    """Ledger record from a parsed VEVENT (used for imports and counter fallbacks)."""
    def val(name, default=""):
        return unescape(ve[name][1]) if name in ve else default
    start = ics_time_to_ledger(*ve["DTSTART"])
    end = ics_time_to_ledger(*ve["DTEND"]) if "DTEND" in ve else start
    alarm = None
    if "_ALARM" in ve:
        trig = ve["_ALARM"][1].upper()
        if trig.startswith("-PT") and trig.endswith("M"):
            alarm = int(trig[3:-1])
        elif trig.startswith("-PT") and trig.endswith("H"):
            alarm = int(trig[3:-1]) * 60
    org_cn = ve.get("ORGANIZER", ({}, ""))[0].get("CN", "Reminders").strip('"')
    return {"summary": val("SUMMARY"), "description": val("DESCRIPTION"),
            "location": val("LOCATION"), "start": start, "end": end,
            "rrule": ve["RRULE"][1] if "RRULE" in ve else "",
            "seq": int(ve["SEQUENCE"][1]) if "SEQUENCE" in ve else 0,
            "alarm_minutes": alarm, "organizer_cn": org_cn,
            "transp": ve["TRANSP"][1] if "TRANSP" in ve else "OPAQUE",
            "status": "active", "response": "", "history": []}


def message_from_bytes(b):
    return email.message_from_bytes(b)
