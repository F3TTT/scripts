$ErrorActionPreference = "Stop"
$c = Get-Content "C:\Users\ADMIN\.backup-cold\config.json" -Raw | ConvertFrom-Json
# Writes kit-A-restore.html (no secrets) and kit-B-keys.html (SECRETS) to %TEMP%ecovery-kit.
# Print both, then DELETE kit-B-keys.html. Never write the output into the repo or OneDrive.
$out = Join-Path $env:TEMP "recovery-kit"; New-Item -ItemType Directory -Force $out | Out-Null
$today = Get-Date -Format "yyyy-MM-dd"
$css = @"
<style>
body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.35;color:#000;margin:0}
h1{font-size:17pt;margin:0 0 4pt} h2{font-size:12.5pt;margin:12pt 0 3pt;border-bottom:1px solid #888}
.store{border:3px solid #000;padding:8pt;margin:0 0 10pt;font-size:12pt}
.store b{font-size:13pt}
code,pre{font-family:Consolas,monospace;font-size:10pt} pre{background:#eee;padding:5pt;white-space:pre-wrap}
td{border:1px solid #666;padding:5pt 7pt;vertical-align:top} table{border-collapse:collapse;width:100%}
.secret{font-family:Consolas,monospace;font-size:14pt;letter-spacing:1px}
li{margin:2pt 0}
</style>
"@

# ---------- Sheet A: restore instructions (no secrets) ----------
$a = @"
<!doctype html><html><head><meta charset="utf-8"><title>Restore sheet</title>$css</head><body>
<div class="store"><b>WHERE TO STORE THIS SHEET:</b> Print 2 copies. <b>Copy 1:</b> in the safe, with the "Backup keys" envelope.
<b>Copy 2:</b> in the sealed off-site envelope, with the second "Backup keys" sheet. This sheet has no secrets on it.</div>
<h1>How to get the backups back</h1>
<p>Printed $today. Written for a <b>new or borrowed Windows computer</b>, with the laptop lost or dead.</p>

<h2>Where the copies are</h2>
<table>
<tr><td><b>1. Proton Drive</b> (account f3ttt@protonmail.com)</td><td>Folder <code>My files\Backups\Desktop\</code>. One dated folder per year, kept 7 years. Log in at proton.me/drive and download. Needs the Proton password + 2FA (in 1Password).</td></tr>
<tr><td><b>2. Backblaze B2</b>, encrypted with restic</td><td>Weekly snapshots of the Desktop: weekly for 2 months, monthly for 1 year, <b>yearly for 7 years</b>. Unreadable without the restic password. Bucket, keys and password: on the "Backup keys" sheet and in 1Password item <b>"Backup - restic B2 cold repo"</b>.</td></tr>
</table>

<h2>Restore from Backblaze (copy 2)</h2>
<ol>
<li>Download restic for Windows: <b>github.com/restic/restic/releases</b> → the file ending <code>windows_amd64.zip</code>. Unzip it; rename the .exe to <code>restic.exe</code>.</li>
<li>Open <b>PowerShell</b> in that folder and type (values from the "Backup keys" sheet):
<pre>`$env:B2_ACCOUNT_ID     = "&lt;keyID&gt;"
`$env:B2_ACCOUNT_KEY    = "&lt;applicationKey&gt;"
`$env:RESTIC_REPOSITORY = "b2:&lt;bucket&gt;:restic"
.\restic.exe snapshots</pre>
It asks for the <b>restic password</b> → type it. You should see a list of dated snapshots.</li>
<li>Restore the newest snapshot to a folder:
<pre>.\restic.exe restore latest --target C:\Restored</pre>
Or a specific date: use the ID from the <code>snapshots</code> list instead of <code>latest</code>.</li>
<li>The files appear under <code>C:\Restored\C\Users\ADMIN\Desktop\</code> (snapshots from before 2026-10-09: <code>C:\Restored\C\Users\ADMIN\OneDrive\Desktop\</code>).</li>
</ol>

<h2>If something is missing</h2>
<ul>
<li><b>Lost the restic password?</b> It's in 3 places: 1Password, the "Backup keys" sheet in the safe, and the off-site copy. <b>Without it the B2 copy cannot be opened by anyone.</b></li>
<li><b>Locked out of 1Password?</b> Use the <b>1Password Emergency Kit</b> (Secret Key + master password), also kept in the safe and off-site.</li>
<li><b>Backblaze key revoked or lost?</b> Log in to backblaze.com (login in 1Password), Application Keys → make a new key for the same bucket. The data and restic password are unaffected.</li>
</ul>

<h2>Yearly test (due each October)</h2>
<p>On a computer other than the main laptop, follow this sheet and restore 3 files. If it works, the system works. Then replace both copies of this sheet if anything changed.</p>
</body></html>
"@
Set-Content "$out\kit-A-restore.html" $a -Encoding UTF8

# ---------- Sheet B: secrets ----------
$b = @"
<!doctype html><html><head><meta charset="utf-8"><title>Backup keys</title>$css</head><body>
<div class="store"><b>SECRET. WHERE TO STORE THIS SHEET:</b> Print 2 copies.
<b>Copy 1:</b> fold into an envelope marked "Backup keys" and put it <b>in the safe</b>, next to the 1Password Emergency Kit.
<b>Copy 2:</b> in the <b>sealed off-site envelope</b>, together with the restore sheet and a second 1Password Emergency Kit.
Never photograph it, scan it or keep it in a desk drawer.</div>
<h1>Backup keys: Backblaze B2 + restic</h1>
<p>Printed $today. Same values as 1Password item <b>"Backup - restic B2 cold repo"</b>.</p>
<table>
<tr><td style="width:32%"><b>restic password</b><br><small>Without this the backup can never be opened.</small></td><td class="secret">$($c.resticPassword)</td></tr>
<tr><td><b>Repository</b></td><td class="secret">b2:$($c.bucket):restic</td></tr>
<tr><td><b>B2 bucket</b></td><td class="secret">$($c.bucket)</td></tr>
<tr><td><b>B2 keyID</b></td><td class="secret">$($c.b2KeyId)</td></tr>
<tr><td><b>B2 applicationKey</b><br><small>Replaceable: a new key can be made at backblaze.com.</small></td><td class="secret">$($c.b2ApplicationKey)</td></tr>
</table>
<p>The restic password uses only A–Z (no I, L, O) and 2–9. <b>There is no letter O or digit 0, and no letter I/L or digit 1.</b></p>
<h2>Also in the safe and off-site (print separately)</h2>
<ul><li><b>1Password Emergency Kit</b>: download it from 1Password (Account → Emergency Kit), print 2 copies, one per location.</li></ul>
</body></html>
"@
Set-Content "$out\kit-B-keys.html" $b -Encoding UTF8
"written to $out (delete kit-B-keys.html after printing)"
