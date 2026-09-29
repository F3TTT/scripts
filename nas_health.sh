#!/bin/sh
# QNAP NAS health check (TS-932PX, 192.168.1.7). Read-only, system-level only:
# firmware version, RAID state, mounted data volumes, installed app versions, load.
# Never lists share contents or folder names — see the nas-maintenance-only-guardrail memory.
#
# Runs ON the NAS; pipe it over SSH from WSL (inline quoting through wsl -> ssh breaks):
#   wsl ssh kneaplro@192.168.1.7 sh -s < C:\scripts\nas_health.sh
# Key login only works once DataVol4 (homes) is unlocked after a reboot.

echo "version: $(getcfg System Version) build $(getcfg System 'Build Number')"
uname -v
uptime
echo "--- raid"
grep -E '^md[0-9]+ :|blocks' /proc/mdstat | sed 's/^ *//'
echo "--- mounted data volumes"
df -h 2>/dev/null | grep -E '_DATA$'
echo "--- apps (name / enabled / version)"
for a in $(grep -oE '^\[[^]]+\]' /etc/config/qpkg.conf | tr -d '[]'); do
  printf '%-20s %-6s %s\n' "$a" "$(getcfg "$a" Enable -f /etc/config/qpkg.conf)" "$(getcfg "$a" Version -f /etc/config/qpkg.conf)"
done
echo "--- cpu"
top -b -n 1 | sed -n 2p
