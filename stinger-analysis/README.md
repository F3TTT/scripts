# stinger-analysis

Exploratory scripts from investigating the "sparkly electronic" news/ad **stinger**
that the transcript-based chapter pipeline can't catch (it's a wordless sound). None
is production-ready — they're kept to document what was tried.

Full write-up, reference audio, and spectrograms live outside the repo (personal
media notes): `OneDrive\Desktop\Entertainment\Rollins\stinger-reference\README.md`.

Each script takes a 44.1 kHz mono WAV of an episode and runs on the WSL laptop (never
the seedbox — ultra.cc bans sustained CPU). Summary of approaches, all with unusable
precision on a dense-music episode from a single masked reference:

- `onset.py` — brightness-tilt onset (11–16 kHz vs mid); pinpoints the ~30 dB jump at the stinger.
- `detect_v2.py` — sustained high-band (11–16 kHz) brightness bloom over local baseline.
- `sparkle.py` — earlier 9–16 kHz brightness-excess variant.
- `match.py` / `match2.py` — full-spectrum matched filter (chunked); noise floor too high.
- `match_hi.py` — 11–16 kHz-only matched filter; self-matches but doesn't discriminate.
- `scan_tones.py` — sustained pure-tone scan (rejected: the stinger is broadband, not a tone).
- `analyze.py` / `sting.py` — tonal-prominence probes used early on.

**If the stinger recurs and this gets built for real:** switch to acoustic
fingerprinting (Shazam-style spectral-peak constellation, e.g. dejavu) or normalized
time-domain cross-correlation from a *clean* template — far more specific than these
spectral-cosine attempts.
