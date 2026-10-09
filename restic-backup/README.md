# restic-backup

Weekly **client-side-encrypted** backup of the OneDrive Desktop to Backblaze B2, using restic.
Part of the user's data-tiers plan: see `Desktop\Operations - Life Systems\data-tiers-and-backups.md`.

| File | What |
|---|---|
| `backup-restic.ps1` | `restic backup --force` of the Desktop, then `forget --keep-weekly 8 --keep-monthly 12 --keep-yearly 7 --prune`, then `check --read-data-subset=2%`. Exits 1 and logs `ERROR:` on failure. |
| `make-recovery-kit.ps1` | Regenerates the printable recovery kit (restore sheet + "Backup keys" sheet) into `%TEMP%\recovery-kit`. Print both, then **delete `kit-B-keys.html`** (it holds the secrets). |

## Config (secrets, never in this repo)

`C:\Users\ADMIN\.backup-cold\config.json`, ACL restricted to the user:
`{ "b2KeyId", "b2ApplicationKey", "bucket", "resticPassword" }`. The same values are in 1Password item
**"Backup - restic B2 cold repo"** and on the printed "Backup keys" sheets (safe + off-site).
**Losing the restic password = losing the backup.**

Repository: `b2:<bucket>:restic` (created 2026-10-08, id `cad189952b`). The B2 application key is scoped to that one bucket.

## Schedule

Task Scheduler **`ResticBackupB2`**: Sundays 10:00 AM, runs as the logged-on user via
`conhost.exe --headless pwsh -File backup-restic.ps1` (no window), *Run task as soon as possible after a
scheduled start is missed* on. Log: `%LOCALAPPDATA%\restic-backup\backup.log` (rotated at 512 KB).

## Why `--force`

VeraCrypt can keep a container's modified date unchanged after use, and restic normally skips files
whose date and size haven't changed. `--force` re-reads everything (a few minutes for ~11 GB of local
disk). Only changed chunks upload.

## Restore

See the printed restore sheet, or:

```powershell
$env:B2_ACCOUNT_ID="<keyID>"; $env:B2_ACCOUNT_KEY="<appKey>"; $env:RESTIC_REPOSITORY="b2:<bucket>:restic"
restic snapshots
restic restore latest --target C:\Restored
```

Yearly restore test (October): restore a few files on a different computer using only the paper sheet.
