#!/usr/bin/env python3
"""Scrape Waze live map for police reports and other alerts near LA."""

import urllib.request
import ssl
import json
from datetime import datetime, timezone

ssl_ctx = ssl.create_default_context()

# LA metro bounding boxes - split to stay under 200 alert cap per request
LA_TILES = {
    "Central LA": {"top": 34.10, "bottom": 33.90, "left": -118.40, "right": -118.15},
    "South LA / Long Beach": {"top": 33.90, "bottom": 33.70, "left": -118.40, "right": -118.10},
    "West LA / Santa Monica": {"top": 34.10, "bottom": 33.90, "left": -118.55, "right": -118.40},
    "East LA / SGV": {"top": 34.15, "bottom": 33.95, "left": -118.15, "right": -117.85},
    "SFV West": {"top": 34.30, "bottom": 34.10, "left": -118.65, "right": -118.40},
    "SFV East / Glendale": {"top": 34.30, "bottom": 34.10, "left": -118.40, "right": -118.10},
}

WAZE_URL = "https://www.waze.com/live-map/api/georss"

ALERT_EMOJI = {
    "POLICE": "🚔",
    "ACCIDENT": "💥",
    "HAZARD": "⚠️",
    "ROAD_CLOSED": "🚧",
    "JAM": "🚗",
}


def fetch_waze(bounds):
    """Fetch alerts from Waze for a bounding box."""
    params = (
        f"top={bounds['top']}&bottom={bounds['bottom']}"
        f"&left={bounds['left']}&right={bounds['right']}"
        f"&env=na&types=alerts,traffic"
    )
    url = f"{WAZE_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_la():
    """Fetch alerts from all LA tiles, deduplicating by UUID."""
    seen = set()
    all_alerts = []
    all_jams = []

    for name, bounds in LA_TILES.items():
        try:
            data = fetch_waze(bounds)
            for a in data.get("alerts", []):
                uid = a.get("uuid")
                if uid and uid not in seen:
                    seen.add(uid)
                    all_alerts.append(a)
            all_jams.extend(data.get("jams", []))
        except Exception as e:
            print(f"  Warning: {name} failed: {e}")

    return all_alerts, all_jams


def format_alert(alert):
    """Format a single alert for display."""
    atype = alert.get("type", "UNKNOWN")
    subtype = alert.get("subtype", "")
    loc = alert.get("location", {})
    lat, lon = loc.get("y", 0), loc.get("x", 0)
    street = alert.get("street", "Unknown")
    city = alert.get("city", "")
    emoji = ALERT_EMOJI.get(atype, "❓")
    reliability = alert.get("reliability", 0)
    thumbs = alert.get("nThumbsUp", 0)

    pub_ms = alert.get("pubMillis", 0)
    if pub_ms:
        pub_time = datetime.fromtimestamp(pub_ms / 1000, tz=timezone.utc)
        age_min = (datetime.now(timezone.utc) - pub_time).total_seconds() / 60
        time_str = f"{int(age_min)}m ago"
    else:
        time_str = "?"

    label = subtype.replace("_", " ").title() if subtype else atype.replace("_", " ").title()
    return {
        "type": atype,
        "subtype": subtype,
        "label": label,
        "emoji": emoji,
        "lat": lat,
        "lon": lon,
        "street": street,
        "city": city,
        "reliability": reliability,
        "thumbs_up": thumbs,
        "time_str": time_str,
        "pub_millis": pub_ms,
        "uuid": alert.get("uuid"),
    }


def get_police_alerts():
    """Get just police alerts, sorted by recency."""
    alerts, _ = fetch_all_la()
    police = [format_alert(a) for a in alerts if a.get("type") == "POLICE"]
    police.sort(key=lambda x: x["pub_millis"], reverse=True)
    return police


def get_all_alerts():
    """Get all alerts grouped by type."""
    alerts, jams = fetch_all_la()
    formatted = [format_alert(a) for a in alerts]
    formatted.sort(key=lambda x: x["pub_millis"], reverse=True)
    return formatted, jams


def print_summary():
    """Print a summary of current LA Waze alerts."""
    alerts, jams = get_all_alerts()

    from collections import Counter
    types = Counter(a["type"] for a in alerts)

    print(f"\n{'='*60}")
    print(f"  Waze LA Alert Summary — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  Total alerts: {len(alerts)}  |  Traffic jams: {len(jams)}")
    for t, count in types.most_common():
        print(f"    {ALERT_EMOJI.get(t, '?')} {t}: {count}")

    # Police detail
    police = [a for a in alerts if a["type"] == "POLICE"]
    if police:
        print(f"\n{'─'*60}")
        print(f"  🚔 Police Reports ({len(police)})")
        print(f"{'─'*60}")
        for p in police:
            print(f"  {p['time_str']:>6s}  {p['label']:22s}  {p['street']}, {p['city']}")
            print(f"          ({p['lat']:.4f}, {p['lon']:.4f})  reliability={p['reliability']}  👍{p['thumbs_up']}")

    # Accidents
    accidents = [a for a in alerts if a["type"] == "ACCIDENT"]
    if accidents:
        print(f"\n{'─'*60}")
        print(f"  💥 Accidents ({len(accidents)})")
        print(f"{'─'*60}")
        for a in accidents:
            print(f"  {a['time_str']:>6s}  {a['label']:22s}  {a['street']}, {a['city']}")

    print()


if __name__ == "__main__":
    print_summary()
