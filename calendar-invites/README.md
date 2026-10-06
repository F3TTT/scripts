# calendar-invites

Reminders for the work Outlook calendar, sent as iCalendar invites from the Proton Bridge
identity through the local Proton Mail Bridge. A real calendar sync with the
work account isn't allowed (infosec), so this is a one-way invite plus a way back:

- Every invite asks for a response (`RSVP=TRUE`). Outlook only offers **Propose New Time** when
  a response is requested; the older `RSVP=FALSE` invites could be neither moved nor countered.
- `counter_watch.py` runs every 5 minutes. When Outlook sends a Propose New Time
  (`METHOD:COUNTER`), it accepts it: applies the new time, bumps `SEQUENCE`, and re-sends the
  invite, so the event moves in Outlook. Accept/decline replies are recorded too.

## Use

```
python invites.py new --summary "Return antenna" --start "2026-10-06 18:00" --minutes 30 \
    --desc "..." --location "..." [--alarm 15] [--all-day] [--rrule "FREQ=WEEKLY;BYDAY=TU"]
python invites.py update --uid UID --start "2026-10-07 12:00"     # keeps the duration
python invites.py cancel --uid UID
python invites.py list [--all]                                    # upcoming, with UIDs
python invites.py import-sent [--since 01-Aug-2026]               # rebuild ledger from Sent
```

Times are US Eastern wall-clock. To move a reminder: Propose New Time in Outlook (applied within
~5 minutes) or tell Claude, which runs `update`.

## Files

- `bridge.py`: Bridge credentials (Credential Manager target `ProtonBridgeSMTP` via `CredRead`),
  IMAP/SMTP on 127.0.0.1:1143/1025, the ledger, and minimal iCalendar build/parse. Stdlib only;
  no tzdata on this laptop, so Eastern DST is computed directly.
- `invites.py`: the CLI above. `counter_watch.py`: the watcher. `run-watch.ps1`: task wrapper.
- `test_counter.py`: offline tests (sending stubbed): `python test_counter.py`.
- Data lives **outside the repo** in `~/.calendar-invites/` (the repo is public and events
  include medical appointments): `config.json` (`organizer`, `attendee`, `attendee_name`; the
  addresses are deliberately not in the code), `events.json` (ledger: UID -> times, sequence, history),
  `state.json` (processed Message-IDs), `watch.log`.

## Limits

- Needs the laptop on and Bridge running; a proposal made while it's off is applied on the next
  run (the watcher looks back 3 days).
- A counter for a single occurrence of a recurring event is logged and skipped, not applied.
- Mail is only read; the watcher never moves or deletes messages.

## Scheduled task

`calendar-counter-watch`, every 5 minutes, headless like the other pwsh jobs:

```powershell
$a = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument '--headless pwsh -NoProfile -File C:\scripts\calendar-invites\run-watch.ps1'
$t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
Register-ScheduledTask -TaskName 'calendar-counter-watch' -Action $a -Trigger $t -Settings $s
```
