#!/usr/bin/env bash
SRT="/home/worldtar/.rollins-sync/transcripts/harmony-in-my-head/22-Harmony In My Head 2026-05-29.srt"
echo "=== sponsor / KCRW / support language ==="
grep -inE 'kcrw|sponsor|brought to you|support (for|comes)|underwrit' "$SRT" | head -30
echo
echo "=== station IDs / show name ==="
grep -inE "harmony in my head|henry rollins|listening to|tune in|on the air" "$SRT" | head -20
echo
echo "=== promo / pledge / CTA ==="
grep -inE 'coming up|tonight|tomorrow|donate|nationwide|theaters|next on|streaming|pledge|membership|members' "$SRT" | head -20
echo
echo "=== ad-y verbs and product mentions ==="
grep -inE 'available now|out now|find (it|out|us)|join us|on tour|app store|google play|visit|learn more|sign up' "$SRT" | head -20
