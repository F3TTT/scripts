"""Bluesky follower activity by hour (ET).

For an account (ACTOR), pulls every follower and counts what they did in the last 30 days:
posts + replies (public getAuthorFeed) and likes (com.atproto.repo.listRecords on each
follower's PDS, resolved via plc.directory). Prints raw counts per ET hour and a
"people-weighted" version where each follower contributes equally. No auth needed.

Used 2026-10-04 to set kaizengrey.com posting slots (noon / 7:30pm ET); see that repo's README.
Note: ET is a fixed UTC-4 offset (no tzdata on this machine) - adjust for EST windows (Nov-Mar).

Usage: python follower_activity.py > out.json   (progress goes to stderr; ~3 min for ~170 followers)
"""
import json, urllib.request, urllib.parse, datetime, collections, time, sys


ACTOR = "kaizengrey.bsky.social"
API = "https://public.api.bsky.app/xrpc/"
ET = datetime.timezone(datetime.timedelta(hours=-4))  # EDT; whole 30-day window is in EDT
NOW = datetime.datetime.now(datetime.timezone.utc)
CUTOFF = NOW - datetime.timedelta(days=30)

def get(url, params):
    q = urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url + "?" + q, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(1)

def parse(ts):
    try:
        d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

# followers
followers, cursor = [], None
while True:
    p = {"actor": ACTOR, "limit": 100}
    if cursor: p["cursor"] = cursor
    d = get(API + "app.bsky.graph.getFollowers", p)
    if not d: break
    followers += d.get("followers", [])
    cursor = d.get("cursor")
    if not cursor: break
print(f"followers: {len(followers)}", file=sys.stderr)

pds_cache = {}
def pds_for(did):
    if did in pds_cache: return pds_cache[did]
    url = f"https://plc.directory/{did}" if did.startswith("did:plc:") else None
    pds = None
    if url:
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                doc = json.load(r)
            for s in doc.get("service", []):
                if s.get("type") == "AtprotoPersonalDataServer":
                    pds = s["serviceEndpoint"]
        except Exception:
            pass
    pds_cache[did] = pds
    return pds

raw = collections.Counter()
weighted = collections.defaultdict(float)
dow_hour = collections.Counter()
active_people = 0
for i, f in enumerate(followers):
    did = f["did"]
    stamps = []
    # posts + replies
    cur = None
    for _ in range(5):
        p = {"actor": did, "limit": 100, "filter": "posts_with_replies"}
        if cur: p["cursor"] = cur
        d = get(API + "app.bsky.feed.getAuthorFeed", p)
        if not d: break
        stop = False
        for item in d.get("feed", []):
            post = item.get("post", {})
            if post.get("author", {}).get("did") != did: continue
            t = parse(post.get("record", {}).get("createdAt", ""))
            if not t: continue
            if t < CUTOFF: stop = True; continue
            stamps.append(t)
        cur = d.get("cursor")
        if stop or not cur: break
    # likes from their PDS
    pds = pds_for(did)
    if pds:
        cur = None
        for _ in range(5):
            p = {"repo": did, "collection": "app.bsky.feed.like", "limit": 100}
            if cur: p["cursor"] = cur
            d = get(pds + "/xrpc/com.atproto.repo.listRecords", p)
            if not d: break
            stop = False
            for rec in d.get("records", []):
                t = parse(rec.get("value", {}).get("createdAt", ""))
                if not t: continue
                if t < CUTOFF: stop = True; continue
                stamps.append(t)
            cur = d.get("cursor")
            if stop or not cur: break
    stamps = [s for s in stamps if CUTOFF <= s <= NOW]
    if stamps:
        active_people += 1
        hc = collections.Counter(s.astimezone(ET).hour for s in stamps)
        n = len(stamps)
        for h, c in hc.items():
            raw[h] += c
            weighted[h] += c / n
        for s in stamps:
            e = s.astimezone(ET)
            dow_hour[(e.strftime("%a"), e.hour)] += 1
    if i % 25 == 0:
        print(f"  {i}/{len(followers)}", file=sys.stderr)

out = {"followers": len(followers), "active_last_30d": active_people,
       "raw_by_hour": {h: raw[h] for h in range(24)},
       "people_weighted_by_hour": {h: round(weighted[h], 2) for h in range(24)}}
print(json.dumps(out, indent=1))


