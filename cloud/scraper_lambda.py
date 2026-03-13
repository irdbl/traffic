#!/usr/bin/env python3
"""
Serverless Traffic Scraper for GitHub Actions + Cloudflare R2

Fetches traffic data from:
1. Sigalert.com - speed sensors and incidents
2. CHP CAD - real-time dispatch incidents
3. Waze Live Map - police, accident, hazard, and road closure alerts

Uploads to R2 as timestamped JSON.

Environment variables:
  R2_ACCOUNT_ID: Cloudflare account ID
  R2_ACCESS_KEY_ID: R2 access key
  R2_SECRET_ACCESS_KEY: R2 secret key
  R2_BUCKET_NAME: R2 bucket name (default: traffic-data)
"""

import json
import os
import re
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime, timezone

# Sigalert URLs
STATIC_URL = "https://cdn-static.sigalert.com/240/Zip/RegionInfo/SoCalStatic.json"
DATA_URL = "https://www.sigalert.com/Data/SoCal/4~j/SoCalData.json"

# CHP CAD
CHP_URL = "https://cad.chp.ca.gov/Traffic.aspx"
CHP_CENTERS = ["LACC", "OCCC"]  # Los Angeles, Orange County

# Waze Live Map - split LA into tiles to stay under ~200 alert cap per request
WAZE_URL = "https://www.waze.com/live-map/api/georss"
WAZE_TILES = [
    {"top": 34.10, "bottom": 33.90, "left": -118.40, "right": -118.15},  # Central LA
    {"top": 33.90, "bottom": 33.70, "left": -118.40, "right": -118.10},  # South LA / Long Beach
    {"top": 34.10, "bottom": 33.90, "left": -118.55, "right": -118.40},  # West LA / Santa Monica
    {"top": 34.15, "bottom": 33.95, "left": -118.15, "right": -117.85},  # East LA / SGV
    {"top": 34.30, "bottom": 34.10, "left": -118.65, "right": -118.40},  # SFV West
    {"top": 34.30, "bottom": 34.10, "left": -118.40, "right": -118.10},  # SFV East / Glendale
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.sigalert.com/",
}


class CHPTableParser(HTMLParser):
    """Parse CHP incident table from HTML."""
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.rows = []
        self.current_data = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "gvIncidents" in attrs.get("id", ""):
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.current_data = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "td" and self.in_cell:
            self.current_row.append(self.current_data.strip())
            self.in_cell = False

    def handle_data(self, data):
        if self.in_cell:
            self.current_data += data


def fetch_chp_incidents(center: str) -> list:
    """Fetch incidents from CHP CAD for a communication center."""
    headers = {"User-Agent": HEADERS["User-Agent"]}

    try:
        # GET to get ViewState
        req = urllib.request.Request(CHP_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        vs_match = re.search(r'id="__VIEWSTATE" value="([^"]*)"', html)
        vsg_match = re.search(r'id="__VIEWSTATEGENERATOR" value="([^"]*)"', html)

        if not vs_match or not vsg_match:
            return []

        # POST to get data for specific center
        data = urllib.parse.urlencode({
            "__VIEWSTATE": vs_match.group(1),
            "__VIEWSTATEGENERATOR": vsg_match.group(1),
            "__EVENTTARGET": "ddlComCenter",
            "ddlComCenter": center,
            "ddlSearches": "Choose One",
            "ddlResources": "Choose One",
        }).encode()

        req = urllib.request.Request(CHP_URL, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        # Parse table
        parser = CHPTableParser()
        parser.feed(html)

        # Extract incidents
        # row: [0]=id_link, [1]=time, [2]=type, [3]=location, [4]=loc_desc, [5]=area, [6]=log_id (optional)
        incidents = []
        for row in parser.rows:
            if len(row) >= 6:
                incidents.append({
                    "id": row[0].replace("Details", "").strip(),
                    "time": row[1],
                    "type": row[2],
                    "loc": row[3],
                    "desc": row[4],
                    "area": row[5],
                })
        return incidents
    except Exception as e:
        print(f"  CHP {center} error: {e}")
        return []


def fetch_waze_alerts() -> list:
    """Fetch Waze alerts from all LA tiles, deduplicated by UUID."""
    seen = set()
    all_alerts = []
    headers = {"User-Agent": HEADERS["User-Agent"]}

    for tile in WAZE_TILES:
        try:
            params = urllib.parse.urlencode({
                "top": tile["top"], "bottom": tile["bottom"],
                "left": tile["left"], "right": tile["right"],
                "env": "na", "types": "alerts",
            })
            req = urllib.request.Request(f"{WAZE_URL}?{params}", headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for a in data.get("alerts", []):
                uid = a.get("uuid")
                if uid and uid not in seen:
                    seen.add(uid)
                    all_alerts.append(a)
        except Exception as e:
            print(f"  Waze tile error: {e}")

    return all_alerts


def compact_waze_alert(a: dict) -> dict:
    """Extract structured fields from a Waze alert."""
    loc = a.get("location", {})
    out = {
        "uuid": a.get("uuid", ""),
        "type": a.get("type", ""),
        "subtype": a.get("subtype", ""),
        "lat": round(loc.get("y", 0), 5),
        "lon": round(loc.get("x", 0), 5),
        "street": a.get("street", ""),
        "city": a.get("city", ""),
        "reliability": a.get("reliability", 0),
        "thumbs_up": a.get("nThumbsUp", 0),
        "pub_utc": a.get("pubMillis", 0),
        "road_type": a.get("roadType", -1),
    }
    if a.get("reportDescription"):
        out["description"] = a["reportDescription"]
    if a.get("nComments", 0) > 0:
        out["num_comments"] = a["nComments"]
    return out


def fetch_json(url: str) -> dict:
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload_to_r2(data: bytes, key: str):
    """Upload data to Cloudflare R2 using boto3."""
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

    bucket = os.environ.get("R2_BUCKET_NAME", "traffic-data")
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/json")
    print(f"Uploaded to r2://{bucket}/{key}")


def scrape_and_upload():
    """Main scrape function."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%H")

    print(f"Scraping at {timestamp}...")

    # Fetch Sigalert data
    cb = int(now.timestamp() * 1000) % 100000000
    data = fetch_json(f"{DATA_URL}?cb={cb}")

    # Fetch CHP CAD data
    chp_incidents = {}
    for center in CHP_CENTERS:
        incidents = fetch_chp_incidents(center)
        if incidents:
            chp_incidents[center] = incidents
            print(f"  CHP {center}: {len(incidents)} incidents")

    # Fetch Waze alerts
    waze_alerts = fetch_waze_alerts()
    waze_compact = [compact_waze_alert(a) for a in waze_alerts]
    waze_by_type = {}
    for a in waze_alerts:
        t = a.get("type", "?")
        waze_by_type[t] = waze_by_type.get(t, 0) + 1
    print(f"  Waze: {len(waze_alerts)} alerts {dict(waze_by_type)}")

    # Extract just speeds and incidents (cameras are large and rarely needed)
    compact_data = {
        "t": timestamp,
        "s": [[s[0], s[2]] for s in data["speeds"]],  # [speed, incidents] only
        "i": [
            [i[1], i[3], i[4], i[8]]  # [id, location, description, start_time]
            for i in data.get("incidents", [])
            if len(i) >= 9
        ],
        "chp": chp_incidents,  # CHP CAD incidents by center
        "waze": waze_compact,  # Waze alerts as structured objects
    }

    # Stats
    valid_speeds = sum(1 for s in compact_data["s"] if s[0] is not None)
    print(f"Sigalert: {valid_speeds}/{len(compact_data['s'])} speeds, {len(compact_data['i'])} incidents")

    # Compress and upload
    json_bytes = json.dumps(compact_data, separators=(",", ":")).encode("utf-8")
    print(f"Payload size: {len(json_bytes):,} bytes")

    # Key format: data/YYYY-MM-DD/HH/MMSS.json
    key = f"data/{date_str}/{hour_str}/{now.strftime('%M%S')}.json"

    if os.environ.get("R2_ACCOUNT_ID"):
        upload_to_r2(json_bytes, key)
    else:
        # Local mode - save to file
        out_dir = f"data/{date_str}/{hour_str}"
        os.makedirs(out_dir, exist_ok=True)
        out_path = f"{out_dir}/{now.strftime('%M%S')}.json"
        with open(out_path, "wb") as f:
            f.write(json_bytes)
        print(f"Saved locally to {out_path}")

    return compact_data


def main():
    """Entry point."""
    try:
        scrape_and_upload()
        print("Done!")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
