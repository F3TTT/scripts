#!/usr/bin/env python3
"""Walk qBittorrent's BT_backup, parse each .torrent for the content name
+ piece set, and check the typical save paths to determine whether files
are actually present. Reports torrents that look orphaned (no files exist
under any plausible save path)."""
import os, re, sys, glob

BT_BACKUP = os.path.expanduser("~/.local/share/qBittorrent/BT_backup")
SAVE_ROOTS = [
    "/home/zuul6/downloads/qbittorrent",
    "/home/zuul6/downloads",
    "/home/zuul6/media/TV",
    "/home/zuul6/media/Movies",
    "/home/zuul6/media",
]

def bdecode(data, pos=0):
    """Tiny bencode decoder. Returns (value, next_pos)."""
    c = data[pos:pos+1]
    if c == b"i":
        end = data.index(b"e", pos)
        return int(data[pos+1:end]), end + 1
    if c == b"l":
        out = []
        pos += 1
        while data[pos:pos+1] != b"e":
            v, pos = bdecode(data, pos)
            out.append(v)
        return out, pos + 1
    if c == b"d":
        out = {}
        pos += 1
        while data[pos:pos+1] != b"e":
            k, pos = bdecode(data, pos)
            v, pos = bdecode(data, pos)
            out[k] = v
        return out, pos + 1
    # bytes: <length>:<bytes>
    m = re.match(rb"(\d+):", data[pos:])
    if not m:
        raise ValueError(f"bad bencode at {pos}: {data[pos:pos+50]!r}")
    length = int(m.group(1))
    start = pos + len(m.group(0))
    return data[start:start+length], start + length

def torrent_name_and_files(torrent_path):
    """Returns (name, [relative file paths])"""
    with open(torrent_path, "rb") as f:
        try:
            obj, _ = bdecode(f.read())
        except Exception:
            return None, []
    info = obj.get(b"info", {}) or {}
    name = info.get(b"name", b"").decode(errors="replace")
    if b"files" in info:
        # multi-file
        files = []
        for fe in info[b"files"]:
            parts = [p.decode(errors="replace") for p in fe.get(b"path", [])]
            files.append(os.path.join(name, *parts))
        return name, files
    return name, [name]   # single-file torrent

def files_exist_anywhere(rel_paths):
    """Check if at least one of the rel_paths exists under any save root."""
    for rel in rel_paths:
        for root in SAVE_ROOTS:
            if os.path.exists(os.path.join(root, rel)):
                return True
    return False

orphans = []
total = 0
for tf in glob.glob(os.path.join(BT_BACKUP, "*.torrent")):
    total += 1
    h = os.path.basename(tf).split(".")[0]
    name, files = torrent_name_and_files(tf)
    if not name:
        continue
    if not files_exist_anywhere(files):
        orphans.append((h, name, len(files)))

print(f"scanned {total} torrents, found {len(orphans)} with no files present on disk")
print()
# Print orphans, grouped roughly
orphans.sort(key=lambda x: x[1].lower())
for h, name, n in orphans:
    print(f"  {h[:8]}  ({n}f)  {name[:100]}")
