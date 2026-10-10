# privacy-settings

Keeps Windows and Office privacy settings where the user put them. Microsoft re-enables
these through feature updates, Office updates and "finish setting up" flows, so the
check runs weekly for good, not just during the 2026 privacy project.

- `settings.psd1`: every expected value, with a one-line reason. Policy keys are preferred
  (updates reset the ordinary Settings toggles more often than policies). Only settings that
  Windows **Home** honors are listed.
- `privacy-settings.ps1`: no switch = check only; `-Apply` sets everything; `-Fix` = check,
  re-apply drifted values, email a report (Proton Bridge, f3ttt → billsmaphia) only when
  something was off; `-ClearHistory` one-shot clears recent-files lists (irreversible, Jump
  List pins too); `-Register` registers the task; `-NoEmail` prints instead.

Also flags retired apps that come back (new Outlook and Copilot are auto-removed; OneDrive is
only reported) and any Microsoft account signed in to Windows that isn't on the allowlist.

The allowlist is local only, never in the repo: `%LOCALAPPDATA%\privacy-settings\config.json`
(`{ "allowedMicrosoftIdentities": [...] }`). Logs and any unsent alert: same folder.

HKLM policies need admin, so the task runs with highest privileges. Registering it (and the
first `-Apply`) needs an elevated shell:

```
pwsh -File C:\scripts\privacy-settings\privacy-settings.ps1 -Apply -Register
```

Task `privacy-settings-weekly`: Sundays 11:00, StartWhenAvailable, via `conhost.exe --headless`.

To add a setting: add a row to `settings.psd1`, run `-Apply`. To drop one Microsoft keeps
flipping that you've decided you don't care about, remove its row rather than living with
weekly emails.
